"""The Export Summary PDF's "Variation from Last Run" section: an LLM
executive narrative built strictly on top of metrics this app computes and
verifies itself, never on the model's own arithmetic or invention.

Two distinct things happen here, and only the second one calls the LLM:

1. Metrics (deterministic, in Python): load the immediately preceding
   analytics-eligible analysis run and diff its frozen article snapshots
   against the selected run's snapshots - counts, sentiment, net sentiment,
   deltas, and how much the article *coverage* itself differs between the
   two snapshots (so a changed sample is never mistaken for changed
   opinions).
2. Narrative (the LLM): handed those verified metrics plus grounded evidence
   (article id/title/summary/topics/key_points/opinions, bounded and
   sampled for large projects) and asked for structured prose with evidence
   references. Every evidence reference is validated against the actual ids
   shown to the model before being trusted; an unparseable or ungrounded
   response degrades to `status="llm_failed"` with the verified metrics kept
   intact, never a fabricated comparison.

Cached in project_report_variation_summaries per selected-run scope and run
dates, invalidated by a data_fingerprint over the actual rows on
both sides rather than by "has more time passed" - same reasoning as
report_data.py's own executive-summary freshness check, and the same
cache-unless-asked shape as trend_summary.py/idea_comparisons.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import date, datetime

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb
from services.articles.article_analyses import fetch_run_article_rows
from services.intelligence.intelligence import VALID_SENTIMENTS, net_sentiment
from services.pipeline.pipeline_runs import get_previous_analysis_run
from services.reports.report_data import report_timezone

logger = logging.getLogger(__name__)

PROMPT_VERSION = "report-variation/2"
_SYSTEM_PROMPT = load_prompt("report_variation_system_prompt.txt")

_SECTION_ORDER = (
    ("ideas", "Ideas & Themes"),
    ("sentiment", "Sentiment Shift"),
    ("opinions", "Expressed Opinions"),
    ("topics", "Topic Movement"),
    ("implications", "Practical Implications"),
)

_RESPONSE_SCHEMA_HINT = (
    '{"ideas": "...", "sentiment": "...", "opinions": "...", "topics": "...", '
    '"implications": "...", "evidence": [{"point": "...", "article_ids": [1, 2]}]}'
)


def _run_date(run: dict | None, tz) -> date:
    when = (run or {}).get("finished_at") or (run or {}).get("created_at")
    return when.astimezone(tz).date() if isinstance(when, datetime) else datetime.now(tz).date()


def _run_label(run: dict | None, tz) -> str:
    run = run or {}
    sequence = run.get("sequence_number")
    name = f"Analysis #{sequence}" if sequence else "Analysis run"
    when = run.get("finished_at") or run.get("created_at")
    date_label = when.astimezone(tz).strftime("%b %d, %Y") if isinstance(when, datetime) else "unknown date"
    return f"{name} - {date_label}"


def _rows_by_id(rows: list[dict]) -> dict[int, dict]:
    return {int(row["id"]): row for row in rows if row.get("id") is not None}


def _sentiment_metrics(rows: list[dict]) -> dict:
    counts = Counter(str(row.get("sentiment") or "").lower() for row in rows)
    values = {key: int(counts.get(key, 0)) for key in VALID_SENTIMENTS}
    total = len(rows)
    return {"total": total, **values, "net_sentiment": net_sentiment(values, total)}


def _deltas(current: dict, previous: dict) -> dict:
    return {key: current.get(key, 0) - previous.get(key, 0) for key in ("total", "positive", "negative", "neutral", "mixed", "net_sentiment")}


def _coverage(current_ids: set, previous_ids: set, sampled: bool) -> dict:
    return {
        "current_ids": len(current_ids),
        "previous_ids": len(previous_ids),
        "common": len(current_ids & previous_ids),
        "added": len(current_ids - previous_ids),
        "removed": len(previous_ids - current_ids),
        "sampled": sampled,
    }


def _row_fingerprint(row: dict) -> str:
    payload = "|".join(str(row.get(field) or "") for field in ("id", "sentiment", "summary", "relevance_score"))
    return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()[:12]


def _data_fingerprint(current_rows: list[dict], previous_rows: list[dict]) -> str:
    parts = sorted(_row_fingerprint(r) for r in current_rows) + ["|"] + sorted(_row_fingerprint(r) for r in previous_rows)
    return hashlib.sha256("".join(parts).encode("utf-8")).hexdigest()


def _sample(rows: list[dict], limit: int) -> tuple[list[dict], bool]:
    if len(rows) <= limit:
        return rows, False
    # Evenly across the set (by id order) rather than first-N, so a large
    # project's sample isn't just whatever happened to be inserted first.
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)], True


def _evidence_block(rows: list[dict], label: str) -> str:
    lines = []
    for row in rows:
        insight = row.get("insight_json") or {}
        topics = ", ".join(str(t) for t in (row.get("topics") or [])[:5])
        key_points = "; ".join(str(k) for k in (row.get("key_points") or [])[:3])
        opinions = insight.get("people_opinions") or []
        opinion_line = "; ".join(
            f"{str(o.get('opinion') or '').strip()[:120]}" for o in opinions[:3] if isinstance(o, dict) and o.get("opinion")
        )
        lines.append(
            f"[{label}#{row.get('id')}] sentiment={row.get('sentiment') or 'neutral'} | "
            f"{str(row.get('title') or '').strip()[:120]}\n"
            f"  summary: {str(row.get('summary') or '').strip()[:300]}\n"
            + (f"  topics: {topics}\n" if topics else "")
            + (f"  key points: {key_points}\n" if key_points else "")
            + (f"  opinions: {opinion_line}\n" if opinion_line else "")
        )
    return "\n".join(lines) if lines else "(none)"


def _load_cached(project_id: int, scope_key: str, current_date: date, previous_date: date) -> dict | None:
    if not config.DATABASE_URL:
        return None
    row = db.fetch_one(
        """
        select status, reason, today_metrics, yesterday_metrics, deltas, coverage,
               data_fingerprint, narrative, evidence, prompt_version, generated_at
        from public.project_report_variation_summaries
        where project_id = %s and scope_key = %s and today_date = %s and yesterday_date = %s
        """,
        (project_id, scope_key, current_date, previous_date),
    )
    if not row:
        return None
    return {
        "status": row["status"],
        "reason": row["reason"],
        "metrics": {
            "current": row["today_metrics"],
            "previous": row["yesterday_metrics"],
            "deltas": row["deltas"],
            "coverage": row["coverage"],
        },
        "narrative": row["narrative"],
        "evidence": row["evidence"] or [],
        "prompt_version": row.get("prompt_version"),
        "_fingerprint": row["data_fingerprint"],
        "cached": True,
    }


def _save_cached(project_id: int, scope_key: str, current_date: date, previous_date: date, tz_name: str, result: dict) -> None:
    if not config.DATABASE_URL:
        return
    metrics = result["metrics"]
    db.execute(
        """
        insert into public.project_report_variation_summaries (
            project_id, scope_key, today_date, yesterday_date, timezone,
            status, reason, today_metrics, yesterday_metrics, deltas, coverage,
            data_fingerprint, narrative, evidence, analysis_model, prompt_version, generated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (project_id, scope_key, today_date, yesterday_date) do update set
            timezone = excluded.timezone,
            status = excluded.status,
            reason = excluded.reason,
            today_metrics = excluded.today_metrics,
            yesterday_metrics = excluded.yesterday_metrics,
            deltas = excluded.deltas,
            coverage = excluded.coverage,
            data_fingerprint = excluded.data_fingerprint,
            narrative = excluded.narrative,
            evidence = excluded.evidence,
            analysis_model = excluded.analysis_model,
            prompt_version = excluded.prompt_version,
            generated_at = now()
        """,
        (
            project_id, scope_key, current_date, previous_date, tz_name,
            result["status"], result.get("reason"),
            Jsonb(metrics["current"]) if metrics["current"] is not None else None,
            Jsonb(metrics["previous"]) if metrics["previous"] is not None else None,
            Jsonb(metrics["deltas"]) if metrics["deltas"] is not None else None,
            Jsonb(metrics["coverage"]) if metrics["coverage"] is not None else None,
            result["_fingerprint"], result.get("narrative"), Jsonb(result.get("evidence") or []),
            config.LLM_CHAT_MODEL or None, PROMPT_VERSION,
        ),
    )


def _generate_narrative(current_rows: list[dict], previous_rows: list[dict], metrics: dict, current_label: str, previous_label: str) -> tuple[str | None, list[dict]]:
    current_sample, current_sampled = _sample(current_rows, config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE)
    previous_sample, previous_sampled = _sample(previous_rows, config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE)
    allowed_ids = {int(r["id"]) for r in current_sample if r.get("id") is not None} | {
        int(r["id"]) for r in previous_sample if r.get("id") is not None
    }

    sampling_note = ""
    if current_sampled or previous_sampled:
        sampling_note = (
            f"\nNote: this project has more analyzed articles than fit in one prompt; the evidence below is a "
            f"representative sample (selected run: {len(current_sample)}/{metrics['current']['total']}, "
            f"previous run: {len(previous_sample)}/{metrics['previous']['total']}), not the full set."
        )

    user_prompt = (
        f"SELECTED RUN ({current_label}) verified metrics: {json.dumps(metrics['current'])}\n"
        f"PREVIOUS RUN ({previous_label}) verified metrics: {json.dumps(metrics['previous'])}\n"
        f"Change: {json.dumps(metrics['deltas'])}\n"
        f"Article coverage: {json.dumps(metrics['coverage'])}"
        f"{sampling_note}\n\n"
        f"SELECTED RUN's articles:\n{_evidence_block(current_sample, 'current')}\n\n"
        f"PREVIOUS RUN's articles:\n{_evidence_block(previous_sample, 'previous')}\n\n"
        f"Respond with JSON matching exactly: {_RESPONSE_SCHEMA_HINT}\n"
        f"article_ids in `evidence` must be article ids from the lists above only, prefixed with nothing "
        f"(just the number), e.g. an id referenced as [current#41] is 41."
    )

    raw = chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1800,
        timeout=config.REPORT_VARIATION_LLM_TIMEOUT_SECONDS,
        json_mode=True,
    )
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        raise JSONParseError("response was not a JSON object")

    sections = []
    for key, heading in _SECTION_ORDER:
        text = str(parsed.get(key) or "").strip()
        if text:
            sections.append(f"{heading}:\n{text}")
    if not sections:
        raise JSONParseError("no narrative sections in response")

    evidence = []
    for item in parsed.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        point = str(item.get("point") or "").strip()
        try:
            ids = [int(i) for i in (item.get("article_ids") or []) if int(i) in allowed_ids]
        except (TypeError, ValueError):
            ids = []
        if point and ids:
            evidence.append({"point": point, "article_ids": ids})

    return "\n\n".join(sections), evidence


def build_variation_from_last_run(project: dict, report_data: dict, run: dict | None = None, force: bool = False) -> dict:
    """Compare the selected analysis run with its immediately preceding run.

    The comparison is based solely on run order. Calendar distance between
    the runs has no effect. Both sides use immutable `article_analyses`
    snapshots, with the selected side reused from `report_data` so its totals
    cannot disagree with the rest of the PDF.
    """
    project_id = report_data["project"]["id"]
    tz = report_timezone()
    current_rows = report_data.get("_analyzed_rows") or []
    current_date = _run_date(run, tz)
    current_label = _run_label(run, tz)

    base_result = {
        "status": "unavailable",
        "reason": None,
        "current_date": current_date.isoformat(),
        "previous_date": None,
        "timezone": config.REPORT_TIMEZONE,
        "current_scope_label": current_label,
        "previous_scope_label": None,
        "current_run_id": (run or {}).get("id"),
        "previous_run_id": None,
        "metrics": {"current": None, "previous": None, "deltas": None, "coverage": None},
        "narrative": None,
        "evidence": [],
        "cached": False,
    }

    if not run or report_data.get("scope", {}).get("type") != "run":
        base_result["reason"] = "Select an analysis run to compare it with the previous run."
        return base_result

    if not current_rows:
        base_result["reason"] = "No analyzed articles exist in the selected run."
        return base_result

    base_result["metrics"]["current"] = _sentiment_metrics(current_rows)
    previous_run = get_previous_analysis_run(project_id, run["id"])
    if not previous_run:
        base_result["reason"] = "No previous analysis run with saved results exists for this project."
        return base_result

    previous_date = _run_date(previous_run, tz)
    previous_label = _run_label(previous_run, tz)
    base_result.update({
        "previous_date": previous_date.isoformat(),
        "previous_scope_label": previous_label,
        "previous_run_id": previous_run["id"],
    })
    previous_rows = [
        row for row in fetch_run_article_rows(project_id, previous_run["id"])
        if str(row.get("analysis_status") or "").lower() == "success"
    ]
    if not previous_rows:
        base_result["reason"] = "The previous analysis run has no successfully analyzed articles."
        return base_result

    current_ids = {int(r["id"]) for r in current_rows if r.get("id") is not None}
    previous_ids = {int(r["id"]) for r in previous_rows if r.get("id") is not None}
    current_metrics = _sentiment_metrics(current_rows)
    previous_metrics = _sentiment_metrics(previous_rows)
    metrics = {
        "current": current_metrics,
        "previous": previous_metrics,
        "deltas": _deltas(current_metrics, previous_metrics),
        "coverage": _coverage(current_ids, previous_ids, sampled=False),
    }
    fingerprint = _data_fingerprint(current_rows, previous_rows)
    scope_key = f"run:{run['id']}"

    if not force:
        cached = _load_cached(project_id, scope_key, current_date, previous_date)
        if (cached and cached["_fingerprint"] == fingerprint
                and cached.get("prompt_version") == PROMPT_VERSION):
            return {**base_result, "status": cached["status"], "reason": cached["reason"],
                    "metrics": cached["metrics"], "narrative": cached["narrative"],
                    "evidence": cached["evidence"], "cached": True}

    result = {**base_result, "status": "ok", "metrics": metrics}
    try:
        narrative, evidence = _generate_narrative(
            current_rows, previous_rows, metrics, current_label, previous_label,
        )
        result["narrative"] = narrative
        result["evidence"] = evidence
        if (len(current_rows) > config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE
                or len(previous_rows) > config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE):
            metrics["coverage"]["sampled"] = True
    except LLMError as e:
        logger.warning("Report variation narrative failed (%s): %s", e.code, e.detail or e)
        result["status"] = "llm_failed"
        result["reason"] = e.user_message
    except JSONParseError as e:
        logger.warning("Report variation narrative unparsable: %s", e)
        result["status"] = "llm_failed"
        result["reason"] = "The AI narrative could not be generated in a usable format."
    except Exception:
        logger.exception("Report variation narrative failed unexpectedly")
        result["status"] = "llm_failed"
        result["reason"] = "Something went wrong while generating the AI narrative."

    _save_cached(project_id, scope_key, current_date, previous_date, config.REPORT_TIMEZONE, {**result, "_fingerprint": fingerprint})
    return result


# Transitional alias for callers outside this repository that imported the
# old name. Its behavior is intentionally run-to-run.
build_variation_from_yesterday = build_variation_from_last_run
