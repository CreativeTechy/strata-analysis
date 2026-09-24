"""Cross-source idea comparison: for a project's idea_clusters (see
idea_clustering.py) that more than one distinct source has talked about,
build a card showing what each source specifically said - most usefully,
when sources state different values/figures for what is otherwise the same
idea (e.g. one source's stated petrol price vs. another's).

Reuses idea_clusters/idea_cluster_articles rather than re-deriving idea
grouping: those tables already do the embedding-based attach-or-create
clustering of frequent_ideas across a project's articles. This module only
adds the "group by source, did they actually diverge, summarize it" layer on
top, and persists the result (idea_comparisons) the same way
services/intelligence/trend_summary.py caches its LLM paragraph - a plain
call returns whatever is cached, and only an explicit regenerate spends
another LLM call.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

PROMPT_VERSION = "idea-comparison/2"
_SYSTEM_PROMPT = load_prompt("idea_comparison_system_prompt.txt")

MAX_EXCERPT_LENGTH = 300
VALUE_KINDS = {"actual", "forecast", "estimate", "target", "unknown"}
_NUMBER_PATTERN = re.compile(
    r"(?P<prefix>[£$€])?\s*(?P<number>[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s*(?P<suffix>.*)",
    re.IGNORECASE,
)


def _source_label(row: dict) -> str:
    """Best-effort human-readable source name for an article: the hostname
    of whichever URL it has (source_url for an uploaded-document article,
    else its own url), falling back to the document filename in `source`,
    since this app has no separate publisher/outlet column (see CLAUDE.md -
    there is no scraper or `sources` table here)."""
    for candidate in (row.get("source_url"), row.get("url")):
        text = str(candidate or "").strip()
        if not text:
            continue
        host = urlparse(text).netloc.strip().lower()
        if host:
            return host[4:] if host.startswith("www.") else host
    source = str(row.get("source") or "").strip()
    return source or "Unknown source"


def _cluster_candidates(project_id: int, limit: int, run_id: str | None = None) -> list[dict]:
    # Two steps rather than one join-then-LIMIT query: capping the joined
    # rows directly would truncate a single high-frequency cluster's own
    # articles before ever reaching the next cluster. Picking the top cluster
    # ids first, then fetching every one of *their* articles with no further
    # limit, is what actually bounds this to "at most `limit` clusters".
    #
    # idea_cluster_articles has no run history of its own - each article's row
    # is fully replaced on every (re)analysis (idea_clustering.py's
    # _replace_idea_clusters_for_article), so it only ever reflects whichever
    # run last touched that article, exactly like articles.pipeline_run_id.
    # A run-scoped comparison therefore restricts candidate articles to that
    # column rather than filtering idea_clusters' own (global, cross-run)
    # frequency_estimate.
    if run_id:
        cluster_ids = db.fetch_all(
            """
            select ic.id as id, count(distinct ica.article_id) as run_count
            from idea_clusters ic
            join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
            join articles a on a.id = ica.article_id
            where ic.project_id = %s and a.pipeline_run_id = %s
            group by ic.id
            having count(distinct ica.article_id) >= 2
            order by run_count desc, ic.id desc
            limit %s
            """,
            (int(project_id), str(run_id), int(limit)),
        )
    else:
        cluster_ids = db.fetch_all(
            """
            select id from idea_clusters
            where project_id = %s and frequency_estimate >= 2
            order by frequency_estimate desc, id desc
            limit %s
            """,
            (int(project_id), int(limit)),
        )
    ids = [row["id"] for row in cluster_ids or []]
    if not ids:
        return []
    if run_id:
        return db.fetch_all(
            """
            select ic.id as idea_cluster_id, ic.idea, ic.type, ic.frequency_estimate,
                   a.id as article_id, a.title, a.url, a.source, a.source_url, a.published,
                   a.summary, ica.value
            from idea_clusters ic
            join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
            join articles a on a.id = ica.article_id
            where ic.id = any(%s) and a.pipeline_run_id = %s
            """,
            (ids, str(run_id)),
        )
    return db.fetch_all(
        """
        select ic.id as idea_cluster_id, ic.idea, ic.type, ic.frequency_estimate,
               a.id as article_id, a.title, a.url, a.source, a.source_url, a.published,
               a.summary, ica.value
        from idea_clusters ic
        join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
        join articles a on a.id = ica.article_id
        where ic.id = any(%s)
        """,
        (ids,),
    )


def _group_clusters(rows: list[dict]) -> dict[int, dict]:
    clusters: dict[int, dict] = {}
    for row in rows:
        cluster_id = row["idea_cluster_id"]
        cluster = clusters.setdefault(cluster_id, {
            "idea_cluster_id": cluster_id,
            "idea": row["idea"],
            "type": row["type"],
            "frequency_estimate": row["frequency_estimate"],
            "sources": [],
        })
        cluster["sources"].append({
            "source_label": _source_label(row),
            "value": str(row.get("value") or "").strip(),
            "article_id": row["article_id"],
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "published": row.get("published"),
            "excerpt": str(row.get("summary") or "")[:MAX_EXCERPT_LENGTH],
        })
    return clusters


def _qualifying_clusters(clusters: dict[int, dict], limit: int) -> list[dict]:
    """Only clusters more than one distinct source contributed to - a single
    source repeating its own idea across several of its own articles is not
    a cross-source comparison. Clusters where sources stated different
    non-empty values are surfaced first (`diverges`), since that is the
    scenario this feature exists for; same-value/no-value clusters ("multiple
    sources agree") fill the remaining slots."""
    diverging, agreeing = [], []
    for cluster in clusters.values():
        distinct_sources = {s["source_label"] for s in cluster["sources"]}
        if len(distinct_sources) < 2:
            continue
        distinct_values = {s["value"].lower() for s in cluster["sources"] if s["value"]}
        cluster["diverges"] = len(distinct_values) >= 2
        (diverging if cluster["diverges"] else agreeing).append(cluster)

    diverging.sort(key=lambda c: -c["frequency_estimate"])
    agreeing.sort(key=lambda c: -c["frequency_estimate"])
    return (diverging + agreeing)[:limit]


def _format_sources(sources: list[dict]) -> str:
    blocks = []
    for index, source in enumerate(sources, start=1):
        stated = f'stated value: "{source["value"]}"' if source["value"] else "no specific figure stated"
        blocks.append(
            f'[{index}] {source["source_label"]} - {stated}\n'
            f'    "{source["title"]}": {source["excerpt"]}'
        )
    return "\n\n".join(blocks)


def _fact_as_source(fact: dict) -> dict:
    label = str(fact.get("reference_label") or "User-provided fact").strip()
    text = str(fact.get("fact_text") or "").strip()
    date = fact.get("observed_at")
    date_note = f" (dated {date.isoformat() if hasattr(date, 'isoformat') else date})" if date else ""
    observations = fact.get("observations") or []
    observation_values = [item.get("display_value") for item in observations if item.get("display_value")]
    return {
        "source_label": f"{label} [user-provided]",
        "value": str(fact.get("stated_value") or "").strip() or ", ".join(observation_values),
        "title": f"User-provided fact{date_note}",
        "excerpt": text[:MAX_EXCERPT_LENGTH],
    }


def _current_facts_revision(project_id: int, idea_cluster_id: int) -> int:
    row = db.fetch_one(
        "select revision from idea_comparison_fact_revisions where project_id = %s and idea_cluster_id = %s",
        (int(project_id), int(idea_cluster_id)),
    )
    return int(row["revision"] or 0) if row else 0


def list_comparison_facts(project_id: int, idea_cluster_id: int) -> list[dict]:
    rows = db.fetch_all(
        """
        select id, fact_text, reference_label, reference_url, stated_value,
               observed_at, created_by_id, created_by_name, created_at, updated_at
        from idea_comparison_facts
        where project_id = %s and idea_cluster_id = %s
        order by created_at asc, id asc
        """,
        (int(project_id), int(idea_cluster_id)),
    )
    fact_ids = [row["id"] for row in rows or []]
    observation_rows = db.fetch_all(
        """
        select id, fact_id, metric, numeric_value, unit, period_label, value_kind, sort_order
        from idea_comparison_fact_observations
        where fact_id = any(%s)
        order by fact_id, sort_order, id
        """,
        (fact_ids,),
    ) if fact_ids else []
    observations_by_fact: dict[int, list[dict]] = {}
    for observation in observation_rows or []:
        numeric_value = float(observation["numeric_value"])
        unit = str(observation["unit"])
        observations_by_fact.setdefault(observation["fact_id"], []).append({
            "id": observation["id"],
            "metric": observation["metric"],
            "numeric_value": numeric_value,
            "unit": unit,
            "period_label": observation.get("period_label"),
            "value_kind": observation.get("value_kind") or "unknown",
            "display_value": _display_numeric_value(numeric_value, unit),
        })
    return [
        {
            **row,
            "observations": observations_by_fact.get(row["id"], []),
            "observed_at": row["observed_at"].isoformat() if row.get("observed_at") else None,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
        for row in rows or []
    ]


def _validate_fact(payload: dict) -> dict:
    fact_text = str(payload.get("fact_text") or "").strip()
    if not fact_text:
        raise ValueError("Fact text is required.")
    if len(fact_text) > 4000:
        raise ValueError("Fact text must be 4,000 characters or fewer.")
    reference_url = str(payload.get("reference_url") or "").strip()
    parsed_reference = urlparse(reference_url)
    if reference_url and (parsed_reference.scheme.lower() not in {"http", "https"} or not parsed_reference.netloc):
        raise ValueError("Reference URL must be a complete http:// or https:// URL.")
    observed_at = str(payload.get("observed_at") or "").strip()
    if observed_at:
        try:
            date.fromisoformat(observed_at)
        except ValueError as exc:
            raise ValueError("Date must use YYYY-MM-DD format.") from exc
    raw_observations = payload.get("observations") or []
    if not isinstance(raw_observations, list):
        raise ValueError("Numeric observations must be a list.")
    if len(raw_observations) > 20:
        raise ValueError("A fact can contain at most 20 numeric observations.")
    observations = []
    for index, raw in enumerate(raw_observations):
        if not isinstance(raw, dict):
            raise ValueError("Each numeric observation must be an object.")
        metric = str(raw.get("metric") or "").strip()
        unit = str(raw.get("unit") or "").strip()
        if not metric or not unit:
            raise ValueError("Each numeric observation needs a metric and unit.")
        try:
            numeric_value = Decimal(str(raw.get("numeric_value", "")).replace(",", ""))
        except (InvalidOperation, ValueError):
            raise ValueError("Each numeric observation needs a valid number.") from None
        if not numeric_value.is_finite():
            raise ValueError("Numeric observation values must be finite.")
        value_kind = str(raw.get("value_kind") or "unknown").strip().lower()
        if value_kind not in VALUE_KINDS:
            raise ValueError("Value type must be actual, forecast, estimate, target, or unknown.")
        observations.append({
            "metric": metric[:200],
            "numeric_value": numeric_value,
            "unit": unit[:80],
            "period_label": str(raw.get("period_label") or "").strip()[:100] or None,
            "value_kind": value_kind,
            "sort_order": index,
        })
    return {
        "fact_text": fact_text,
        "reference_label": str(payload.get("reference_label") or "").strip()[:200] or None,
        "reference_url": reference_url[:2000] or None,
        "stated_value": str(payload.get("stated_value") or "").strip()[:300] or None,
        "observed_at": observed_at or None,
        "observations": observations,
    }


def _replace_fact_observations(fact_id: int, observations: list[dict]) -> None:
    db.execute("delete from idea_comparison_fact_observations where fact_id = %s", (int(fact_id),))
    for observation in observations:
        db.execute(
            """
            insert into idea_comparison_fact_observations (
                fact_id, metric, numeric_value, unit, period_label, value_kind, sort_order
            ) values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (int(fact_id), observation["metric"], observation["numeric_value"], observation["unit"],
             observation["period_label"], observation["value_kind"], observation["sort_order"]),
        )


def _compact_number(value: float) -> str:
    return f"{value:,.6f}".rstrip("0").rstrip(".")


def _display_numeric_value(value: float, unit: str) -> str:
    number = _compact_number(value)
    if unit.startswith(("£", "$", "€")):
        return f"{unit[0]}{number}{unit[1:]}"
    if unit == "%":
        return f"{number}%"
    return f"{number} {unit}".strip()


def _normalise_unit(prefix: str, suffix: str) -> str:
    suffix = re.sub(r"\s+", " ", suffix.strip().lower())
    if "%" in suffix:
        return "%"
    if prefix:
        meaningful_suffix = suffix
        for noise in ("estimated", "estimate", "forecast", "projected", "actual"):
            meaningful_suffix = meaningful_suffix.replace(noise, "")
        meaningful_suffix = re.sub(r"\s+", " ", meaningful_suffix).strip()
        return f"{prefix}{meaningful_suffix}"
    return suffix.rstrip(".,;")


def _parse_numeric_value(text: str) -> dict | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = _NUMBER_PATTERN.fullmatch(raw)
    if not match:
        return None
    try:
        numeric_value = float(Decimal(match.group("number").replace(",", "")))
    except (InvalidOperation, ValueError):
        return None
    unit = _normalise_unit(match.group("prefix") or "", match.group("suffix") or "")
    if not unit:
        return None
    return {
        "numeric_value": numeric_value,
        "unit": unit,
        "display_value": raw,
    }


def _normalise_group_key(value: str) -> str:
    normalised = re.sub(r"[^a-z0-9%£$€]+", " ", str(value or "").lower()).strip()
    return re.sub(r"([£$€])\s+", r"\1", normalised)


def _numeric_evidence(idea: str, sources: list[dict], facts: list[dict]) -> dict:
    observations: list[dict] = []
    for index, source in enumerate(sources):
        explicit = source.get("numeric_observations") or []
        if explicit:
            candidates = explicit
        else:
            parsed = _parse_numeric_value(source.get("value") or "")
            candidates = [{**parsed, "metric": idea}] if parsed else []
        for item_index, item in enumerate(candidates):
            try:
                value = float(item["numeric_value"])
            except (KeyError, TypeError, ValueError):
                continue
            unit = str(item.get("unit") or "").strip()
            if not unit:
                continue
            observations.append({
                "id": f"source-{index}-{item_index}",
                "origin": "document",
                "evidence_id": f"document-evidence-{index}",
                "source_label": source.get("source_label") or f"Source {index + 1}",
                "metric": str(item.get("metric") or idea).strip(),
                "numeric_value": value,
                "unit": unit,
                "period_label": item.get("period_label"),
                "value_kind": item.get("value_kind") or "unknown",
                "display_value": item.get("display_value") or _display_numeric_value(value, unit),
            })
    for fact in facts:
        candidates = fact.get("observations") or []
        if not candidates:
            parsed = _parse_numeric_value(fact.get("stated_value") or "")
            candidates = [{**parsed, "metric": idea}] if parsed else []
        for item_index, item in enumerate(candidates):
            value = float(item["numeric_value"])
            unit = str(item["unit"])
            observations.append({
                "id": f"fact-{fact['id']}-{item.get('id', item_index)}",
                "origin": "user",
                "evidence_id": f"user-fact-{fact['id']}",
                "source_label": fact.get("reference_label") or "User-provided fact",
                "metric": str(item.get("metric") or idea).strip(),
                "numeric_value": value,
                "unit": unit,
                "period_label": item.get("period_label") or fact.get("observed_at"),
                "value_kind": item.get("value_kind") or "unknown",
                "display_value": item.get("display_value") or _display_numeric_value(value, unit),
            })

    grouped: dict[tuple[str, str], list[dict]] = {}
    for observation in observations:
        key = (_normalise_group_key(observation["metric"]), _normalise_group_key(observation["unit"]))
        grouped.setdefault(key, []).append(observation)

    groups = []
    for items in grouped.values():
        periods = {str(item.get("period_label") or "").strip() for item in items}
        periods.discard("")
        display_type = "single"
        direction = None
        change = None
        change_percent = None
        if len(items) >= 2:
            display_type = "trend" if len(periods) >= 2 and all(item.get("period_label") for item in items) else "comparison"
        if display_type == "trend":
            items.sort(key=lambda item: str(item.get("period_label") or ""))
            change = items[-1]["numeric_value"] - items[0]["numeric_value"]
            direction = "up" if change > 0 else "down" if change < 0 else "flat"
            if items[0]["numeric_value"]:
                change_percent = change / abs(items[0]["numeric_value"]) * 100
        values = [item["numeric_value"] for item in items]
        groups.append({
            "id": f"{_normalise_group_key(items[0]['metric'])}-{_normalise_group_key(items[0]['unit'])}",
            "metric": items[0]["metric"],
            "unit": items[0]["unit"],
            "display_type": display_type,
            "observations": items,
            "minimum": min(values),
            "maximum": max(values),
            "spread": max(values) - min(values),
            "direction": direction,
            "change": change,
            "change_percent": change_percent,
        })
    groups.sort(key=lambda group: (-len(group["observations"]), group["metric"].lower()))
    return {"groups": groups, "total_observations": len(observations)}


def _bump_facts_revision(project_id: int, idea_cluster_id: int) -> int:
    row = db.execute(
        """
        insert into idea_comparison_fact_revisions (project_id, idea_cluster_id, revision)
        values (%s, %s, 1)
        on conflict (project_id, idea_cluster_id) do update set
            revision = idea_comparison_fact_revisions.revision + 1,
            updated_at = now()
        returning revision
        """,
        (int(project_id), int(idea_cluster_id)),
    )
    return int(row["revision"])


def create_comparison_fact(project_id: int, idea_cluster_id: int, payload: dict, user: dict) -> dict | None:
    clean = _validate_fact(payload)
    cluster = db.fetch_one(
        "select id from idea_clusters where id = %s and project_id = %s",
        (int(idea_cluster_id), int(project_id)),
    )
    if not cluster:
        return None
    row = db.execute(
        """
        insert into idea_comparison_facts (
            project_id, idea_cluster_id, fact_text, reference_label, reference_url,
            stated_value, observed_at, created_by_id, created_by_name
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (int(project_id), int(idea_cluster_id), clean["fact_text"], clean["reference_label"],
         clean["reference_url"], clean["stated_value"], clean["observed_at"], user.get("id"),
         str(user.get("username") or "").strip() or None),
    )
    _replace_fact_observations(row["id"], clean["observations"])
    _bump_facts_revision(project_id, idea_cluster_id)
    return next((fact for fact in list_comparison_facts(project_id, idea_cluster_id) if fact["id"] == row["id"]), None)


def update_comparison_fact(project_id: int, idea_cluster_id: int, fact_id: int, payload: dict) -> dict | None:
    clean = _validate_fact(payload)
    row = db.execute(
        """
        update idea_comparison_facts set
            fact_text = %s, reference_label = %s, reference_url = %s,
            stated_value = %s, observed_at = %s, updated_at = now()
        where id = %s and project_id = %s and idea_cluster_id = %s
        returning id
        """,
        (clean["fact_text"], clean["reference_label"], clean["reference_url"], clean["stated_value"],
         clean["observed_at"], int(fact_id), int(project_id), int(idea_cluster_id)),
    )
    if not row:
        return None
    _replace_fact_observations(row["id"], clean["observations"])
    _bump_facts_revision(project_id, idea_cluster_id)
    return next((fact for fact in list_comparison_facts(project_id, idea_cluster_id) if fact["id"] == row["id"]), None)


def delete_comparison_fact(project_id: int, idea_cluster_id: int, fact_id: int) -> bool:
    row = db.execute(
        "delete from idea_comparison_facts where id = %s and project_id = %s and idea_cluster_id = %s returning id",
        (int(fact_id), int(project_id), int(idea_cluster_id)),
    )
    if not row:
        return False
    _bump_facts_revision(project_id, idea_cluster_id)
    return True


def _synthesize_summary(cluster: dict) -> str | None:
    user_prompt = f'IDEA: {cluster["idea"]}\n\nSOURCES:\n{_format_sources(cluster["sources"])}'
    raw = chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=400,
        json_mode=True,
    )
    try:
        parsed = parse_json_response(raw)
    except JSONParseError as exc:
        logger.warning("Idea comparison summary unparsable for cluster %s: %s", cluster["idea_cluster_id"], exc)
        return None
    if not isinstance(parsed, dict):
        return None
    summary = str(parsed.get("summary") or "").strip()
    return summary or None


def _save_comparison(project_id: int, cluster: dict, summary: str | None, run_id: str | None, facts_revision: int = 0) -> None:
    db.execute(
        """
        insert into idea_comparisons (
            project_id, idea_cluster_id, run_id, idea, type, diverges, sources, summary,
            article_count, analysis_model, prompt_version, facts_revision, generated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (project_id, idea_cluster_id, run_id) do update set
            idea = excluded.idea,
            type = excluded.type,
            diverges = excluded.diverges,
            sources = excluded.sources,
            summary = excluded.summary,
            article_count = excluded.article_count,
            analysis_model = excluded.analysis_model,
            prompt_version = excluded.prompt_version,
            facts_revision = excluded.facts_revision,
            generated_at = excluded.generated_at
        """,
        (
            int(project_id),
            cluster["idea_cluster_id"],
            str(run_id or ""),
            cluster["idea"],
            cluster["type"],
            cluster["diverges"],
            Jsonb(cluster["sources"]),
            summary,
            len(cluster["sources"]),
            config.LLM_CHAT_MODEL or None,
            PROMPT_VERSION,
            int(facts_revision),
        ),
    )


def _mark_run_generation_attempt(project_id: int, run_id: str) -> None:
    db.execute(
        """
        insert into idea_comparisons_generation_attempts (project_id, run_id, generated_at)
        values (%s, %s, now())
        on conflict (project_id, run_id) do update set generated_at = now()
        """,
        (int(project_id), str(run_id)),
    )


def has_run_generation_attempt(project_id: int, run_id: str) -> bool:
    """Whether generate_idea_comparisons has already completed (successfully,
    even with zero qualifying clusters) for this run scope.

    idea_comparisons itself can't tell "generated, nothing qualified" apart
    from "never generated" - both read back empty - so without this,
    get_project_idea_comparisons_view would regenerate (and, during a
    provider outage, re-fail) on every single view of a run that genuinely
    has fewer than two cross-source ideas. Only meaningful for a run scope:
    the project-wide view (run_id='') already regenerates only on an
    explicit request, never as a side effect of a plain GET.
    """
    if not config.DATABASE_URL or not run_id:
        return False
    row = db.fetch_one(
        "select 1 from idea_comparisons_generation_attempts where project_id = %s and run_id = %s",
        (int(project_id), str(run_id)),
    )
    return bool(row)


def generate_idea_comparisons(project_id: int, run_id: str | None = None) -> int:
    """(Re)build the comparison cards for a project's qualifying idea
    clusters, either across the whole project (run_id=None) or scoped to one
    analysis run's articles (run_id set). Returns how many were written.

    An LLMError (bad key, provider unreachable, ...) is deliberately NOT
    caught here - it propagates to the caller exactly like
    competitor_analysis.generate_findings does, since it means the provider
    call itself never produced an answer, not "this one cluster had nothing
    to say". Whatever was already written to idea_comparisons in this call
    stays, since each cluster is saved as soon as it is synthesized. Note
    that the run-scoped "already attempted" marker below is only reached once
    every cluster has synthesized successfully - a provider failure partway
    through leaves it unmarked, so the next view retries rather than caching
    a transient outage as "nothing to show".
    """
    if not config.DATABASE_URL:
        return 0

    rows = _cluster_candidates(project_id, config.IDEA_COMPARISON_MAX_CLUSTERS, run_id=run_id)
    clusters = _qualifying_clusters(_group_clusters(rows), config.IDEA_COMPARISON_MAX_CLUSTERS)

    written = 0
    for cluster in clusters:
        facts = list_comparison_facts(project_id, cluster["idea_cluster_id"])
        revision = _current_facts_revision(project_id, cluster["idea_cluster_id"])
        summary_cluster = {**cluster, "sources": [*cluster["sources"], *[_fact_as_source(fact) for fact in facts]]}
        summary = _synthesize_summary(summary_cluster)
        _save_comparison(project_id, cluster, summary, run_id, facts_revision=revision)
        written += 1

    if run_id:
        _mark_run_generation_attempt(project_id, run_id)
    return written


def list_idea_comparisons(project_id: int, run_id: str | None = None) -> list[dict]:
    if not config.DATABASE_URL:
        return []
    rows = db.fetch_all(
        """
        select idea_cluster_id, idea, type, diverges, sources, summary,
               article_count, facts_revision, generated_at
        from idea_comparisons
        where project_id = %s and run_id = %s
        order by diverges desc, article_count desc, generated_at desc
        """,
        (int(project_id), str(run_id or "")),
    )
    return [
        {
            "idea_cluster_id": row["idea_cluster_id"],
            "idea": row["idea"],
            "type": row["type"],
            "diverges": bool(row["diverges"]),
            "sources": row["sources"] or [],
            "summary": row["summary"],
            "article_count": int(row["article_count"] or 0),
            "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
            "facts_revision": int(row.get("facts_revision") or 0),
        }
        for row in rows or []
    ]


def get_idea_comparison(project_id: int, idea_cluster_id: int, run_id: str | None = None) -> dict | None:
    row = db.fetch_one(
        """
        select idea_cluster_id, idea, type, diverges, sources, summary,
               article_count, facts_revision, generated_at
        from idea_comparisons
        where project_id = %s and idea_cluster_id = %s and run_id = %s
        """,
        (int(project_id), int(idea_cluster_id), str(run_id or "")),
    )
    if not row:
        return None
    revision = _current_facts_revision(project_id, idea_cluster_id)
    facts = list_comparison_facts(project_id, idea_cluster_id)
    sources = row["sources"] or []
    return {
        "idea_cluster_id": row["idea_cluster_id"], "idea": row["idea"], "type": row["type"],
        "diverges": bool(row["diverges"]), "sources": sources, "summary": row["summary"],
        "article_count": int(row["article_count"] or 0), "facts": facts,
        "numeric_evidence": _numeric_evidence(row["idea"], sources, facts),
        "facts_revision": revision, "summary_facts_revision": int(row.get("facts_revision") or 0),
        "summary_stale": revision != int(row.get("facts_revision") or 0),
        "generated_at": row["generated_at"].isoformat() if row.get("generated_at") else None,
    }


def regenerate_idea_comparison(project_id: int, idea_cluster_id: int, run_id: str | None = None) -> dict | None:
    comparison = get_idea_comparison(project_id, idea_cluster_id, run_id=run_id)
    if not comparison:
        return None
    revision = comparison["facts_revision"]
    evidence = [*comparison["sources"], *[_fact_as_source(fact) for fact in comparison["facts"]]]
    summary = _synthesize_summary({**comparison, "sources": evidence})
    if not summary:
        raise ValueError("The model did not return a usable summary. Please retry.")
    if _current_facts_revision(project_id, idea_cluster_id) != revision:
        raise ValueError("Facts changed while the summary was being generated. Please retry.")
    values = {str(item.get("value") or "").strip().lower() for item in evidence if str(item.get("value") or "").strip()}
    db.execute(
        """
        update idea_comparisons set summary = %s, diverges = %s, analysis_model = %s,
            prompt_version = %s, facts_revision = %s, generated_at = now()
        where project_id = %s and idea_cluster_id = %s and run_id = %s
        """,
        (summary, len(values) >= 2, config.LLM_CHAT_MODEL or None, PROMPT_VERSION, revision,
         int(project_id), int(idea_cluster_id), str(run_id or "")),
    )
    return get_idea_comparison(project_id, idea_cluster_id, run_id=run_id)
