"""Project-scoped analytics used by the intelligence dashboard and reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

VALID_SENTIMENTS = {"positive", "negative", "neutral", "mixed"}
PERIOD_DAYS = {"7d": 7, "30d": 30, "all": None}
EMOTION_AXES = ("joy", "trust", "anticipation", "anger", "disgust", "fear")
TONE_TO_EMOTION = {
    "positive": "joy",
    "enthusiastic": "joy",
    "humorous": "joy",
    "formal": "trust",
    "optimistic": "anticipation",
    "angry": "anger",
    "critical": "anger",
    "negative": "disgust",
    "sarcastic": "disgust",
    "concerned": "fear",
    "skeptical": "fear",
}


def compute_overall_tone(article_tone, writer_tone):
    """Mirror the article helper without importing the scraper-heavy module."""
    valid = set(TONE_TO_EMOTION) | {"neutral", "informal"}
    article = str(article_tone or "neutral").strip().lower()
    writer = str(writer_tone or "neutral").strip().lower()
    article = article if article in valid else "neutral"
    writer = writer if writer in valid else "neutral"
    if article == writer:
        return article
    if article == "neutral":
        return writer
    if writer == "neutral":
        return article
    return "mixed"


def _database_ready() -> bool:
    import config
    return bool(config.DATABASE_URL)


def normalize_period(period: str | None) -> str:
    return period if period in PERIOD_DAYS else "30d"


def period_start(period: str, now: datetime | None = None) -> datetime | None:
    days = PERIOD_DAYS[normalize_period(period)]
    if days is None:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


def _parse_date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def article_date(row: dict) -> datetime | None:
    return _parse_date(row.get("published")) or _parse_date(row.get("created_at"))


def filter_rows_for_period(rows: list[dict], period: str, now: datetime | None = None) -> list[dict]:
    start = period_start(period, now)
    if start is None:
        return rows
    return [row for row in rows if (date := article_date(row)) is not None and date >= start]


def classify_platform(row: dict) -> str:
    values = [row.get("url"), row.get("source_url"), row.get("source")]
    for value in values:
        text = str(value or "").strip().lower()
        host = urlparse(text if "://" in text else f"https://{text}").netloc.removeprefix("www.")
        if host in {"x.com", "twitter.com"} or host.endswith(".x.com") or host.endswith(".twitter.com"):
            return "X"
        if host == "reddit.com" or host.endswith(".reddit.com"):
            return "Reddit"
        if host in {"t.me", "telegram.me"}:
            return "Telegram"
    return "Web"


def net_sentiment(counts: Counter | dict, total: int | None = None) -> int:
    total = int(total if total is not None else sum(counts.values()))
    if total <= 0:
        return 0
    return round(((int(counts.get("positive", 0)) - int(counts.get("negative", 0))) / total) * 100)


def emotion_signature(rows: list[dict]) -> list[dict]:
    counts = Counter()
    for row in rows:
        tone = compute_overall_tone(row.get("article_tone"), row.get("writer_tone"))
        emotion = TONE_TO_EMOTION.get(tone)
        if emotion:
            counts[emotion] += 1
    mapped_total = sum(counts.values())
    return [
        {
            "axis": axis,
            "value": round((counts[axis] / mapped_total) * 100) if mapped_total else 0,
            "count": counts[axis],
        }
        for axis in EMOTION_AXES
    ]


def count_configured_terms(rows: list[dict], hashtags=None, keywords=None) -> list[dict]:
    terms = []
    seen = set()
    for kind, values in (("hashtag", hashtags or []), ("keyword", keywords or [])):
        for raw in values if isinstance(values, list) else [values]:
            label = str(raw or "").strip()
            key = (kind, label.lower())
            if not label or key in seen:
                continue
            seen.add(key)
            normalized = label.lstrip("#") if kind == "hashtag" else label
            if not normalized:
                continue
            expression = rf"(?<!\w)#?{re.escape(normalized)}(?!\w)" if kind == "hashtag" else rf"(?<!\w){re.escape(normalized)}(?!\w)"
            mentions = sum(
                len(re.findall(expression, " ".join(str(row.get(field) or "") for field in ("title", "summary", "text")), re.IGNORECASE))
                for row in rows
            )
            terms.append({"term": f"#{normalized}" if kind == "hashtag" else label, "kind": kind, "mentions": mentions})
    return sorted(terms, key=lambda item: (-item["mentions"], item["term"].lower()))


def keyword_existence_over_time(
    rows: list[dict],
    keywords: list[str],
    source_url: str | None = None,
    all_keywords: bool = False,
) -> list[dict]:
    """Per-day counts of articles that contain each keyword at least once.

    When `all_keywords` is True, each day carries one count per keyword (for
    the "one series per keyword" view). Otherwise the keywords are combined
    into a single `matches` count per day, i.e. articles matching any of the
    given keywords, without double-counting an article against itself.
    """
    cleaned = []
    seen = set()
    for raw in keywords or []:
        label = str(raw or "").strip()
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        cleaned.append(label)
    if not cleaned:
        return []

    scoped_rows = rows
    if source_url:
        target = str(source_url).strip().lower()
        scoped_rows = [row for row in rows if str(row.get("source_url") or "").strip().lower() == target]

    patterns = {label: rf"(?<!\w){re.escape(label)}(?!\w)" for label in cleaned}
    daily = defaultdict(lambda: {label: 0 for label in cleaned})
    daily_any = defaultdict(int)
    for row in scoped_rows:
        date = article_date(row)
        if not date:
            continue
        key = date.date().isoformat()
        bucket = daily[key]
        daily_any.setdefault(key, 0)
        haystack = " ".join(str(row.get(field) or "") for field in ("title", "summary", "text"))
        matched_any = False
        for label in cleaned:
            if re.search(patterns[label], haystack, re.IGNORECASE):
                bucket[label] += 1
                matched_any = True
        if matched_any:
            daily_any[key] += 1

    dates = sorted(daily.keys())
    if all_keywords:
        return [{"date": date, **daily[date]} for date in dates]
    return [{"date": date, "matches": daily_any[date]} for date in dates]


def pipeline_discovery_series(runs: list[dict]) -> list[dict]:
    points = []
    previous = None
    for run in runs:
        discovered = max(0, int(run.get("articles_scraped") or 0))
        if previous is None:
            change = None
        elif previous == 0:
            change = 0 if discovered == 0 else 100
        else:
            change = round(((discovered - previous) / previous) * 100)
        points.append({
            "run_id": run.get("id"),
            "sequence_number": run.get("sequence_number"),
            "completed_at": run.get("finished_at") or run.get("created_at"),
            "articles_discovered": discovered,
            "change_pct": change,
        })
        previous = discovered
    return points


def sentiment_by_run_series(runs: list[dict], counts_by_run: dict) -> list[dict]:
    """Per-run sentiment breakdown, aligned with pipeline_discovery_series'
    run ordering - lets the dashboard compare how sentiment mix varies from
    one pipeline run to the next, not just how many articles each found."""
    points = []
    for run in runs:
        run_id = run.get("id")
        counts = counts_by_run.get(run_id) or {}
        values = {key: int(counts.get(key, 0)) for key in VALID_SENTIMENTS}
        points.append({
            "run_id": run_id,
            "sequence_number": run.get("sequence_number"),
            "completed_at": run.get("finished_at") or run.get("created_at"),
            "total": sum(values.values()),
            **values,
        })
    return points


def _fetch_project_rows(project_id: int, run_id: str | None = None) -> list[dict]:
    if not _database_ready():
        return []
    import db
    if run_id:
        return db.fetch_all(
            """
            select a.id, a.url, a.source, a.source_url, a.title, a.summary, a.text,
                   a.sentiment, a.writer_tone, a.article_tone, a.insight_json,
                   a.published, a.created_at
            from articles a
            join article_projects ap on ap.article_id = a.id
            where ap.project_id = %s and a.pipeline_run_id = %s
            order by a.created_at asc
            """,
            (int(project_id), str(run_id)),
        )
    return db.fetch_all(
        """
        select a.id, a.url, a.source, a.source_url, a.title, a.summary, a.text,
               a.sentiment, a.writer_tone, a.article_tone, a.insight_json,
               a.published, a.created_at
        from articles a
        join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s
        order by a.created_at asc
        """,
        (int(project_id),),
    )


def _fetch_pipeline_runs(project_id: int) -> list[dict]:
    if not _database_ready():
        return []
    import db
    # sequence_number is numbered over every scrape run for this project
    # (any status), matching list_pipeline_runs() - not just the successful,
    # finished ones selected below - so "Pipeline #N" means the same run
    # whether it's read off a chart here or off the run-picker tabs.
    return db.fetch_all(
        """
        select id, finished_at, created_at, articles_scraped, sequence_number
        from (
            select id, finished_at, created_at, articles_scraped, sequence_number
            from (
                select id, finished_at, created_at, articles_scraped, status,
                       row_number() over (order by created_at asc) as sequence_number
                from pipeline_runs
                where project_id = %s and pipeline = 'scrape'
            ) numbered
            where status = 'success' and finished_at is not null
            order by finished_at desc
            limit 12
        ) latest
        order by finished_at asc
        """,
        (int(project_id),),
    )


def _fetch_sentiment_counts_by_run(project_id: int, run_ids: list) -> dict:
    ids = [run_id for run_id in run_ids if run_id]
    if not _database_ready() or not ids:
        return {}
    import db
    rows = db.fetch_all(
        """
        select a.pipeline_run_id as run_id, a.sentiment, count(*)::int as total
        from articles a
        join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s and a.pipeline_run_id = any(%s)
        group by a.pipeline_run_id, a.sentiment
        """,
        (int(project_id), ids),
    )
    counts_by_run = defaultdict(dict)
    for row in rows:
        sentiment = str(row.get("sentiment") or "").lower()
        if sentiment in VALID_SENTIMENTS:
            counts_by_run[row.get("run_id")][sentiment] = int(row.get("total") or 0)
    return counts_by_run


def _fetch_active_source_count(project_id: int) -> int:
    if not _database_ready():
        return 0
    import db
    row = db.fetch_one("select count(*)::int as total from project_sources where project_id = %s", (int(project_id),))
    return int((row or {}).get("total") or 0)


def get_project_intelligence(project: dict, period: str = "30d", run_id: str | None = None) -> dict:
    from services.articles.articles_store import _topic_summary
    period = normalize_period(period)
    if run_id:
        rows = _fetch_project_rows(project["id"], run_id=run_id)
    else:
        rows = filter_rows_for_period(_fetch_project_rows(project["id"]), period)
    pipeline_runs = _fetch_pipeline_runs(project["id"])
    counts = Counter(str(row.get("sentiment") or "").lower() for row in rows)
    sentiment = {key: int(counts[key]) for key in ("positive", "negative", "neutral", "mixed")}

    daily = defaultdict(lambda: Counter())
    for row in rows:
        date = article_date(row)
        if not date:
            continue
        bucket = daily[date.date().isoformat()]
        bucket["total"] += 1
        value = str(row.get("sentiment") or "").lower()
        if value in VALID_SENTIMENTS:
            bucket[value] += 1

    platforms = defaultdict(lambda: Counter())
    for row in rows:
        bucket = platforms[classify_platform(row)]
        bucket["total"] += 1
        value = str(row.get("sentiment") or "").lower()
        if value in VALID_SENTIMENTS:
            bucket[value] += 1

    return {
        "project_id": project["id"],
        "period": period,
        "run_id": run_id,
        "total": len(rows),
        **sentiment,
        "net_sentiment": net_sentiment(counts, len(rows)),
        "active_sources": _fetch_active_source_count(project["id"]),
        "sentiment_over_time": [
            {"date": date, "total": values["total"], **{key: values[key] for key in VALID_SENTIMENTS}}
            for date, values in sorted(daily.items())
        ],
        "emotional_signature": emotion_signature(rows),
        "platforms": [
            {"platform": platform, "total": values["total"], **{key: values[key] for key in VALID_SENTIMENTS}, "net_sentiment": net_sentiment(values, values["total"])}
            for platform, values in sorted(platforms.items())
        ],
        "trending_terms": count_configured_terms(rows, project.get("hashtags"), project.get("keywords")),
        "pipeline_discovery": pipeline_discovery_series(pipeline_runs),
        "sentiment_by_pipeline_run": sentiment_by_run_series(
            pipeline_runs, _fetch_sentiment_counts_by_run(project["id"], [run.get("id") for run in pipeline_runs]),
        ),
        "insights": _topic_summary(rows),
    }


def get_project_keyword_existence(
    project: dict,
    period: str = "30d",
    source_url: str | None = None,
    keyword: str | None = None,
    run_id: str | None = None,
) -> dict:
    period = normalize_period(period)
    if run_id:
        rows = _fetch_project_rows(project["id"], run_id=run_id)
    else:
        rows = filter_rows_for_period(_fetch_project_rows(project["id"]), period)
    configured_keywords = [str(term).strip() for term in (project.get("keywords") or []) if str(term or "").strip()]

    normalized_keyword = str(keyword or "").strip()
    all_keywords = not normalized_keyword or normalized_keyword.lower() == "all"
    selected_keywords = (
        configured_keywords
        if all_keywords
        else [term for term in configured_keywords if term.lower() == normalized_keyword.lower()]
    )

    normalized_source = str(source_url or "").strip()
    scoped_source = None if not normalized_source or normalized_source.lower() == "all" else normalized_source

    return {
        "project_id": project["id"],
        "period": period,
        "run_id": run_id,
        "keywords": configured_keywords,
        "selected_keywords": selected_keywords,
        "all_keywords": all_keywords,
        "source_url": scoped_source,
        "series": keyword_existence_over_time(rows, selected_keywords, source_url=scoped_source, all_keywords=all_keywords),
    }
