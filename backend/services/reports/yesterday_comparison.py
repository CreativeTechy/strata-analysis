"""The Export Summary PDF's "Variation from Yesterday" section: an LLM
executive narrative built strictly on top of metrics this app computes and
verifies itself, never on the model's own arithmetic or invention.

Two distinct things happen here, and only the second one calls the LLM:

1. Metrics (deterministic, in Python): reconstruct "yesterday's" analyzed
   state from article_analyses (see services/articles/article_analyses.py's
   fetch_state_as_of) and diff it against the report's own in-scope rows
   (services/reports/report_data.py) - counts, sentiment, net sentiment,
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

Cached in project_report_variation_summaries per (project, scope, today/
yesterday dates), invalidated by a data_fingerprint over the actual rows on
both sides rather than by "has more time passed" - same reasoning as
report_data.py's own executive-summary freshness check, and the same
cache-unless-asked shape as trend_summary.py/idea_comparisons.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb
from services.articles.article_analyses import earliest_snapshot_at, fetch_state_as_of
from services.intelligence.intelligence import VALID_SENTIMENTS, filter_rows_for_period, net_sentiment
from services.reports.report_data import report_timezone

logger = logging.getLogger(__name__)

PROMPT_VERSION = "report-variation/1"
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


def _day_start_utc(day: date, tz) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)


def _scope_dates(report_data: dict, tz) -> tuple[date, date]:
    scope = report_data["scope"]
    if scope["type"] == "run":
        # Anchor to the run's own analysis date, not "today" - a PDF exported
        # for a run from three weeks ago must compare against the day before
        # *that* run, not the day before the export itself.
        run = report_data.get("_run") or {}
        when = run.get("finished_at") or run.get("created_at")
        if isinstance(when, datetime):
            today = when.astimezone(tz).date()
        else:
            today = datetime.now(tz).date()
    else:
        today = datetime.now(tz).date()
    return today, today - timedelta(days=1)


def _rows_by_id(rows: list[dict]) -> dict[int, dict]:
    return {int(row["id"]): row for row in rows if row.get("id") is not None}


def _sentiment_metrics(rows: list[dict]) -> dict:
    counts = Counter(str(row.get("sentiment") or "").lower() for row in rows)
    values = {key: int(counts.get(key, 0)) for key in VALID_SENTIMENTS}
    total = len(rows)
    return {"total": total, **values, "net_sentiment": net_sentiment(values, total)}


def _deltas(today: dict, yesterday: dict) -> dict:
    return {key: today.get(key, 0) - yesterday.get(key, 0) for key in ("total", "positive", "negative", "neutral", "mixed", "net_sentiment")}


def _coverage(today_ids: set, yesterday_ids: set, sampled: bool) -> dict:
    return {
        "today_ids": len(today_ids),
        "yesterday_ids": len(yesterday_ids),
        "common": len(today_ids & yesterday_ids),
        "added": len(today_ids - yesterday_ids),
        "removed": len(yesterday_ids - today_ids),
        "sampled": sampled,
    }


def _row_fingerprint(row: dict) -> str:
    payload = "|".join(str(row.get(field) or "") for field in ("id", "sentiment", "summary", "relevance_score"))
    return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()[:12]


def _data_fingerprint(today_rows: list[dict], yesterday_rows: list[dict]) -> str:
    parts = sorted(_row_fingerprint(r) for r in today_rows) + ["|"] + sorted(_row_fingerprint(r) for r in yesterday_rows)
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


def _load_cached(project_id: int, scope_key: str, today: date, yesterday: date) -> dict | None:
    if not config.DATABASE_URL:
        return None
    row = db.fetch_one(
        """
        select status, reason, today_metrics, yesterday_metrics, deltas, coverage,
               data_fingerprint, narrative, evidence, generated_at
        from public.project_report_variation_summaries
        where project_id = %s and scope_key = %s and today_date = %s and yesterday_date = %s
        """,
        (project_id, scope_key, today, yesterday),
    )
    if not row:
        return None
    return {
        "status": row["status"],
        "reason": row["reason"],
        "metrics": {
            "today": row["today_metrics"],
            "yesterday": row["yesterday_metrics"],
            "deltas": row["deltas"],
            "coverage": row["coverage"],
        },
        "narrative": row["narrative"],
        "evidence": row["evidence"] or [],
        "_fingerprint": row["data_fingerprint"],
        "cached": True,
    }


def _save_cached(project_id: int, scope_key: str, today: date, yesterday: date, tz_name: str, result: dict) -> None:
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
            project_id, scope_key, today, yesterday, tz_name,
            result["status"], result.get("reason"),
            Jsonb(metrics["today"]) if metrics["today"] is not None else None,
            Jsonb(metrics["yesterday"]) if metrics["yesterday"] is not None else None,
            Jsonb(metrics["deltas"]) if metrics["deltas"] is not None else None,
            Jsonb(metrics["coverage"]) if metrics["coverage"] is not None else None,
            result["_fingerprint"], result.get("narrative"), Jsonb(result.get("evidence") or []),
            config.LLM_CHAT_MODEL or None, PROMPT_VERSION,
        ),
    )


def _generate_narrative(today_rows: list[dict], yesterday_rows: list[dict], metrics: dict, today_date: date, yesterday_date: date) -> tuple[str | None, list[dict]]:
    today_sample, today_sampled = _sample(today_rows, config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE)
    yesterday_sample, yesterday_sampled = _sample(yesterday_rows, config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE)
    allowed_ids = {int(r["id"]) for r in today_sample if r.get("id") is not None} | {
        int(r["id"]) for r in yesterday_sample if r.get("id") is not None
    }

    sampling_note = ""
    if today_sampled or yesterday_sampled:
        sampling_note = (
            f"\nNote: this project has more analyzed articles than fit in one prompt; the evidence below is a "
            f"representative sample (today: {len(today_sample)}/{metrics['today']['total']}, "
            f"yesterday: {len(yesterday_sample)}/{metrics['yesterday']['total']}), not the full set."
        )

    user_prompt = (
        f"TODAY ({today_date.isoformat()}) verified metrics: {json.dumps(metrics['today'])}\n"
        f"YESTERDAY ({yesterday_date.isoformat()}) verified metrics: {json.dumps(metrics['yesterday'])}\n"
        f"Change: {json.dumps(metrics['deltas'])}\n"
        f"Article coverage: {json.dumps(metrics['coverage'])}"
        f"{sampling_note}\n\n"
        f"TODAY's articles:\n{_evidence_block(today_sample, 'today')}\n\n"
        f"YESTERDAY's articles:\n{_evidence_block(yesterday_sample, 'yesterday')}\n\n"
        f"Respond with JSON matching exactly: {_RESPONSE_SCHEMA_HINT}\n"
        f"article_ids in `evidence` must be article ids from the lists above only, prefixed with nothing "
        f"(just the number), e.g. an id referenced as [today#41] is 41."
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


def build_variation_from_yesterday(project: dict, report_data: dict, run: dict | None = None, force: bool = False) -> dict:
    """`report_data` is the dict report_data.build_report_data() returned for
    this same export - its `_analyzed_rows` become the "today" side so the
    PDF's comparison section can never disagree with its own sentiment
    section about which articles are in scope. `run` is passed through
    separately (report_data doesn't keep the raw pipeline_runs row) only to
    anchor the comparison date for a run-scoped export."""
    project_id = report_data["project"]["id"]
    scope = report_data["scope"]
    scope_key = f"run:{scope['run_id']}" if scope["type"] == "run" else f"period:{scope['period']}"
    tz = report_timezone()
    report_data = {**report_data, "_run": run}
    today_date, yesterday_date = _scope_dates(report_data, tz)

    today_rows = report_data.get("_analyzed_rows") or []
    earliest = earliest_snapshot_at(project_id)
    yesterday_cutoff = _day_start_utc(today_date, tz)
    yesterday_rows_raw = fetch_state_as_of(project_id, yesterday_cutoff)
    yesterday_rows = [r for r in yesterday_rows_raw if str(r.get("analysis_status") or "").lower() == "success"]
    if scope["type"] == "period" and scope.get("period") and scope["period"] != "all":
        # Same rolling window as today's report (relative to the real "now",
        # not re-anchored to yesterday) - so both sides describe the exact
        # same population definition, just at two different points in time.
        yesterday_rows = filter_rows_for_period(yesterday_rows, scope["period"])

    base_result = {
        "status": "unavailable",
        "reason": None,
        "today_date": today_date.isoformat(),
        "yesterday_date": yesterday_date.isoformat(),
        "timezone": config.REPORT_TIMEZONE,
        "today_scope_label": f"{report_data['scope']['analysis_date_label']}",
        "yesterday_scope_label": f"As of {yesterday_date.isoformat()}",
        "metrics": {"today": None, "yesterday": None, "deltas": None, "coverage": None},
        "narrative": None,
        "evidence": [],
        "cached": False,
    }

    if not today_rows:
        base_result["reason"] = "No analyzed articles in the current report scope."
        return base_result
    if not earliest or earliest >= yesterday_cutoff or not yesterday_rows:
        base_result["reason"] = f"No analysis history recorded before {yesterday_date.isoformat()}."
        base_result["metrics"]["today"] = _sentiment_metrics(today_rows)
        return base_result

    today_ids = {int(r["id"]) for r in today_rows if r.get("id") is not None}
    yesterday_ids = {int(r["id"]) for r in yesterday_rows if r.get("id") is not None}
    today_metrics = _sentiment_metrics(today_rows)
    yesterday_metrics = _sentiment_metrics(yesterday_rows)
    metrics = {
        "today": today_metrics,
        "yesterday": yesterday_metrics,
        "deltas": _deltas(today_metrics, yesterday_metrics),
        "coverage": _coverage(today_ids, yesterday_ids, sampled=False),
    }
    fingerprint = _data_fingerprint(today_rows, yesterday_rows)

    if not force:
        cached = _load_cached(project_id, scope_key, today_date, yesterday_date)
        if cached and cached["_fingerprint"] == fingerprint:
            return {**base_result, "status": cached["status"], "reason": cached["reason"],
                     "metrics": cached["metrics"], "narrative": cached["narrative"],
                     "evidence": cached["evidence"], "cached": True}

    result = {**base_result, "status": "ok", "metrics": metrics}
    try:
        narrative, evidence = _generate_narrative(today_rows, yesterday_rows, metrics, today_date, yesterday_date)
        result["narrative"] = narrative
        result["evidence"] = evidence
        if metrics["coverage"] and (len(today_rows) > config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE
                                      or len(yesterday_rows) > config.REPORT_COMPARISON_MAX_ARTICLES_PER_SIDE):
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

    _save_cached(project_id, scope_key, today_date, yesterday_date, config.REPORT_TIMEZONE, {**result, "_fingerprint": fingerprint})
    return result
