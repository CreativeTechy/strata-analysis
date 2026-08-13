"""Turn scraped competitor content into decision-grade analysis cards.

Two stages, and the first one matters more than the second.

**Validation (`validate_competitor_articles`).** Reports here are read as input to
business decisions — what to build, what to price, where to move. So an article is
only allowed to inform a finding if it survives explicit gates, each of which
records *why* a row was dropped:

  - it passes the existing `content_guard` (no consent interstitials, no search pages)
  - it has enough body text to say anything
  - **the competitor is actually named in it** — this is the gate that matters. A
    competitor's own domain publishes plenty that is about nobody in particular,
    and keyword-adjacent articles routinely mention a whole market. Without this,
    a report attributes the industry's news to one company.
  - it is not a near-duplicate of a story already counted, using `story_id` from
    migration 0003, so a press release carried by twenty outlets is one move and
    not twenty

Rejections are stored rather than discarded, because a silently dropped article
and a silently included irrelevant one are both ways a report ends up misleading,
and the user needs to be able to inspect both.

**Generation (`generate_findings`).** For each competitor, the surviving evidence
becomes one card answering exactly three questions: what they're up to, how it
affects us, and what we should do. Counts on the card come from SQL, never from
the model, and every card carries the evidence rows behind it.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

import config
import db
from content_guard import is_blocked_article
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt

PROMPT_VERSION = "competitor-analysis-2026-07-27"

MIN_BODY_CHARS = 400
# Uploaded-document candidates are LLM-split excerpts, often a paragraph or two
# by nature (see document_article_extraction_system_prompt.txt) - holding them
# to the scraped-article floor would reject good evidence as "too short" simply
# for being short-form, which is what it's supposed to be.
MIN_DOCUMENT_BODY_CHARS = 80
DOCUMENT_URL_PREFIX = "document://"
MAX_EVIDENCE_PER_CARD = 8
MAX_TEXT_PER_EVIDENCE = 1800
DEFAULT_PERIOD_DAYS = 30

IMPACT_LEVELS = {"high", "medium", "low"}

ANALYSIS_SYSTEM_PROMPT = load_prompt("competitor_analysis_system_prompt.txt")


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _aliases(competitor: dict) -> list[str]:
    """Names to look for in article text: the company name, and its bare domain."""
    names = []
    name = str(competitor.get("name") or "").strip()
    if name:
        names.append(name)
        # "Acme Inc." also appears as plain "Acme".
        bare = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|gmbh|plc|sa|ag|co)\b\.?", "", name, flags=re.I)
        bare = bare.replace(",", " ").strip()
        if bare and bare.casefold() != name.casefold() and len(bare) >= 3:
            names.append(bare)
    domain = str(competitor.get("domain") or "").strip()
    if domain:
        label = domain.split(".")[0]
        if len(label) >= 3 and label.casefold() not in {n.casefold() for n in names}:
            names.append(label)
    return names


def _mentions(text: str, aliases: list[str]) -> str | None:
    """Return the alias found in the text, or None. Whole-word match only.

    Substring matching would let "Ford" match "Bradford"; at report-grade stakes
    that is the difference between a real signal and a fabricated one.
    """
    haystack = str(text or "")
    for alias in aliases:
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", haystack, re.IGNORECASE):
            return alias
    return None


def _effective_date(article: dict) -> datetime | None:
    """The date to judge an article's recency by.

    published_at is authoritative for rss/social content, which carries a real
    publish timestamp. Plain `web` pages (menus, terms, careers...) are usually
    evergreen and don't have one; htmldate's fallback extraction latches onto
    whatever date-shaped text it can find instead (a copyright year, a footer
    notice), so for those the scrape date is the only trustworthy signal.
    """
    source_type = config._infer_source_type(str(article.get("source_url") or article.get("source") or ""))
    if source_type == "web":
        return article.get("created_at")
    return article.get("published_at") or article.get("created_at")


def _candidate_articles(project_id: int) -> list[dict]:
    """Project articles that could plausibly concern a competitor."""
    return db.fetch_all(
        """
        select a.id, a.url, a.source, a.source_url, a.title, a.summary, a.text,
               a.published_at, a.published_precision, a.created_at, a.story_id,
               a.sentiment, a.article_category
        from articles a
        join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s
        order by a.created_at desc
        """,
        (int(project_id),),
    )


def validate_competitor_articles(project_id: int, competitors: list[dict], period_days: int = DEFAULT_PERIOD_DAYS) -> dict:
    """Attribute articles to competitors, recording accept/reject reasons.

    Returns per-competitor counts plus an aggregate rejection breakdown, so the
    workspace can show what was filtered and why instead of a bare total.
    """
    since = datetime.now(timezone.utc) - timedelta(days=period_days) if period_days else None
    articles = _candidate_articles(project_id)
    if since is not None:
        articles = [a for a in articles if (_effective_date(a) or since) >= since]

    alias_map = {int(c["id"]): _aliases(c) for c in competitors}
    per_competitor: dict[int, dict] = {
        int(c["id"]): {"valid": 0, "rejected": 0, "stories": set()} for c in competitors
    }
    rejection_reasons: dict[str, int] = {}
    rows: list[tuple] = []

    for article in articles:
        body = str(article.get("text") or "")
        title = str(article.get("title") or "")
        haystack = f"{title}\n{article.get('summary') or ''}\n{body}"

        blocked = is_blocked_article(article.get("url"), title)
        is_document = str(article.get("url") or "").startswith(DOCUMENT_URL_PREFIX)
        too_short = len(body) < (MIN_DOCUMENT_BODY_CHARS if is_document else MIN_BODY_CHARS)

        for competitor_id, aliases in alias_map.items():
            matched = _mentions(haystack, aliases) if aliases else None
            if matched is None:
                continue  # not about this competitor at all: not a rejection, just unrelated

            reason = None
            if blocked:
                reason = "blocked_page"
            elif too_short:
                reason = "body_too_short"
            else:
                story_id = article.get("story_id")
                if story_id is not None and story_id in per_competitor[competitor_id]["stories"]:
                    reason = "duplicate_story"

            if reason:
                per_competitor[competitor_id]["rejected"] += 1
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rows.append((competitor_id, int(article["id"]), matched, None, "rejected", reason))
                continue

            if article.get("story_id") is not None:
                per_competitor[competitor_id]["stories"].add(article["story_id"])
            per_competitor[competitor_id]["valid"] += 1
            rows.append((competitor_id, int(article["id"]), f"mentions:{matched}", 1.0, "valid", None))

    if rows:
        with db.transaction() as cur:
            cur.executemany(
                """
                insert into competitor_articles
                    (competitor_id, article_id, match_reason, match_score,
                     validation_status, rejected_reason)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (competitor_id, article_id) do update set
                    match_reason = excluded.match_reason,
                    match_score = excluded.match_score,
                    validation_status = excluded.validation_status,
                    rejected_reason = excluded.rejected_reason
                """,
                rows,
            )

    return {
        "scanned": len(articles),
        "linked": len(rows),
        "per_competitor": {
            competitor_id: {
                "valid": stats["valid"],
                "rejected": stats["rejected"],
                "stories": len(stats["stories"]),
            }
            for competitor_id, stats in per_competitor.items()
        },
        "rejection_reasons": rejection_reasons,
        "period_days": period_days,
    }


def _evidence_for(competitor_id: int, limit: int = MAX_EVIDENCE_PER_CARD) -> list[dict]:
    """Validated evidence for one competitor, newest first, one row per story."""
    return db.fetch_all(
        """
        select distinct on (coalesce(a.story_id, -a.id))
               a.id, a.url, a.source, a.title, a.summary, a.text,
               a.published_at, a.created_at, a.story_id, ca.match_reason
        from competitor_articles ca
        join articles a on a.id = ca.article_id
        where ca.competitor_id = %s and ca.validation_status = 'valid'
        order by coalesce(a.story_id, -a.id),
                 coalesce(a.published_at, a.created_at) desc
        """,
        (int(competitor_id),),
    )[:limit]


def _counts_for(competitor_id: int) -> dict:
    row = db.fetch_one(
        """
        select count(*)::int as articles,
               count(distinct coalesce(a.story_id, -a.id))::int as stories
        from competitor_articles ca
        join articles a on a.id = ca.article_id
        where ca.competitor_id = %s and ca.validation_status = 'valid'
        """,
        (int(competitor_id),),
    )
    return {"articles": int((row or {}).get("articles") or 0),
            "stories": int((row or {}).get("stories") or 0)}


def _normalize_actions(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    actions = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if not action:
            continue
        effort = str(item.get("effort") or "medium").strip().lower()
        urgency = str(item.get("urgency") or "this_quarter").strip().lower()
        actions.append({
            "action": action[:400],
            "rationale": str(item.get("rationale") or "").strip()[:500],
            "effort": effort if effort in {"low", "medium", "high"} else "medium",
            "urgency": urgency if urgency in {"now", "this_quarter", "watch"} else "this_quarter",
        })
    return actions


def _format_evidence(rows: list[dict]) -> str:
    blocks = []
    for index, row in enumerate(rows, start=1):
        when = row.get("published_at") or row.get("created_at")
        date_label = when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else "undated"
        body = (row.get("summary") or row.get("text") or "")[:MAX_TEXT_PER_EVIDENCE]
        blocks.append(
            f"[{index}] {date_label} | {row.get('source') or 'unknown source'}\n"
            f"    {row.get('title') or '(untitled)'}\n"
            f"    {body}"
        )
    return "\n\n".join(blocks)


def generate_finding(business_profile: dict, competitor: dict, period_days: int = DEFAULT_PERIOD_DAYS) -> dict | None:
    """Build one analysis card for one competitor, or None when evidence is absent."""
    from services.competitors.business_profile_store import profile_context

    evidence = _evidence_for(int(competitor["id"]))
    if not evidence:
        return None

    counts = _counts_for(int(competitor["id"]))
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days) if period_days else None

    user_prompt = (
        f"OUR BUSINESS:\n{profile_context(business_profile) or '(no profile on file)'}\n\n"
        f"COMPETITOR: {competitor.get('name')}\n"
        f"  website: {competitor.get('website') or 'unknown'}\n"
        f"  size: {competitor.get('size_tier') or 'unknown'}\n"
        f"  description: {competitor.get('description') or '(none)'}\n\n"
        f"EVIDENCE ({len(evidence)} distinct stories):\n{_format_evidence(evidence)}"
    )

    # LLMError (bad key, insufficient balance, rate limit, provider outage...) is
    # deliberately NOT caught here - it means the call never produced a usable
    # answer at all, which is a different situation from "no evidence" and must
    # not be reported as a silent skip. It propagates to generate_findings,
    # which surfaces it as a real error instead of a false "0 reports" success.
    raw = chat_completion(
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1600,
        timeout=120,
        model=config.COMPETITOR_LLM_CHAT_MODEL,
        api_key=config.COMPETITOR_LLM_API_KEY,
        base_url=config.COMPETITOR_LLM_CHAT_BASE_URL,
        api_style=config.COMPETITOR_LLM_API_STYLE,
        reasoning_effort=config.COMPETITOR_LLM_REASONING_EFFORT,
        api_key_env_name=config.COMPETITOR_LLM_API_KEY_ENV_NAME,
    )
    try:
        parsed = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"  finding generation returned unparsable output for {competitor.get('name')}: {exc}")
        return None

    if not isinstance(parsed, dict):
        return None

    whats_up = str(parsed.get("whats_up") or "").strip()
    impact = str(parsed.get("impact") or "").strip()
    if not whats_up or not impact:
        return None

    impact_level = str(parsed.get("impact_level") or "medium").strip().lower()
    if impact_level not in IMPACT_LEVELS:
        impact_level = "medium"

    try:
        confidence = max(0.0, min(float(parsed.get("confidence", 0.5)), 1.0))
    except (TypeError, ValueError):
        confidence = 0.5

    signals = [str(s).strip().lower() for s in (parsed.get("signals") or []) if str(s).strip()][:8]

    evidence_payload = [
        {
            "article_id": row["id"],
            "url": row.get("url"),
            "title": row.get("title"),
            "source": row.get("source"),
            "published_at": (row.get("published_at") or row.get("created_at")).isoformat()
            if (row.get("published_at") or row.get("created_at")) else None,
            "excerpt": (row.get("summary") or row.get("text") or "")[:400],
        }
        for row in evidence
    ]

    return db.fetch_one(
        """
        insert into competitor_findings (
            project_id, competitor_id, period_start, period_end, headline,
            whats_up, impact, impact_level, actions, signals, evidence,
            confidence, article_count, story_count, validation_status,
            analysis_model, prompt_version, generated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id, project_id, competitor_id, period_start, period_end, headline,
                  whats_up, impact, impact_level, actions, signals, evidence,
                  confidence, article_count, story_count, validation_status,
                  validation_notes, analysis_model, prompt_version, generated_at
        """,
        (
            int(competitor["project_id"]),
            int(competitor["id"]),
            period_start,
            now,
            str(parsed.get("headline") or f"{competitor.get('name')} activity").strip()[:200],
            whats_up,
            impact,
            impact_level,
            Jsonb(_normalize_actions(parsed.get("actions"))),
            Jsonb(signals),
            Jsonb(evidence_payload),
            confidence,
            counts["articles"],
            counts["stories"],
            "pending",
            config.COMPETITOR_LLM_CHAT_MODEL,
            PROMPT_VERSION,
            now,
        ),
    )


def generate_findings(project_id: int, period_days: int = DEFAULT_PERIOD_DAYS) -> dict:
    """Validate evidence then produce one card per tracked competitor."""
    from services.competitors.business_profile_store import get_profile
    from services.competitors.competitors_store import list_competitors

    profile = get_profile(project_id)
    competitors = list_competitors(project_id, status="tracked")
    if not competitors:
        return {"generated": 0, "skipped": 0, "validation": None,
                "error": "No tracked competitors. Track at least one to analyze."}

    validation = validate_competitor_articles(project_id, competitors, period_days)

    generated = 0
    skipped: list[dict] = []
    llm_errors: list[LLMError] = []
    for competitor in competitors:
        try:
            finding = generate_finding(profile, competitor, period_days)
        except LLMError as exc:
            print(f"  finding generation failed for {competitor.get('name')}: {exc.detail or exc}")
            llm_errors.append(exc)
            continue
        if finding:
            generated += 1
            db.execute(
                "update competitors set last_analyzed_at = now() where id = %s",
                (int(competitor["id"]),),
            )
        else:
            stats = validation["per_competitor"].get(int(competitor["id"]), {})
            skipped.append({
                "competitor_id": competitor["id"],
                "name": competitor["name"],
                "reason": "No validated evidence in this period."
                          if not stats.get("valid") else "Analysis could not be generated.",
            })

    # An LLM/provider failure (bad key, insufficient balance, rate limit,
    # outage...) is never reported as a plain "0 reports generated" success -
    # that reads as "nothing needed reporting" when the real story is the AI
    # provider call itself failed. Surface it as an error even if some
    # competitors did get findings, so the caller doesn't miss it.
    error = None
    error_code = None
    if llm_errors:
        first = llm_errors[0]
        affected = len(llm_errors)
        error_code = first.code
        error = (
            f"{first.user_message} ({affected} of {len(competitors)} "
            f"competitor{'s' if len(competitors) != 1 else ''} could not be analyzed "
            f"- provider error: {first.code})"
        )

    return {
        "generated": generated,
        "skipped": skipped,
        "validation": validation,
        "error": error,
        "error_code": error_code,
    }


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
FINDING_COLUMNS = """
    id, project_id, competitor_id, period_start, period_end, headline,
    whats_up, impact, impact_level, actions, signals, evidence, confidence,
    article_count, story_count, validation_status, validation_notes,
    analysis_model, prompt_version, generated_at
"""

_IMPACT_ORDER = "case impact_level when 'high' then 0 when 'medium' then 1 else 2 end"


def list_findings(project_id: int, competitor_id: int | None = None,
                  impact_level: str | None = None, latest_only: bool = True,
                  search: str | None = None, date_from: str | None = None,
                  date_to: str | None = None) -> list[dict]:
    """Findings for the workspace, highest impact and most recent first.

    `latest_only` keeps one card per competitor — the newest — so the card grid
    shows the current picture rather than every historical run.
    """
    clauses = ["f.project_id = %s"]
    params: list = [int(project_id)]
    if competitor_id:
        clauses.append("f.competitor_id = %s")
        params.append(int(competitor_id))
    if impact_level in IMPACT_LEVELS:
        clauses.append("f.impact_level = %s")
        params.append(impact_level)
    search = (search or "").strip()
    if search:
        clauses.append("(f.headline ilike %s or f.whats_up ilike %s or c.name ilike %s)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if date_from:
        clauses.append("f.generated_at >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("f.generated_at < (%s::date + interval '1 day')")
        params.append(date_to)

    dedupe = (
        "distinct on (f.competitor_id) " if latest_only else ""
    )
    ordering = (
        "f.competitor_id, f.generated_at desc"
        if latest_only
        else f"{_IMPACT_ORDER.replace('impact_level', 'f.impact_level')}, f.generated_at desc"
    )

    rows = db.fetch_all(
        f"""
        select {dedupe}{_finding_select()},
               c.name as competitor_name, c.website as competitor_website,
               c.domain as competitor_domain, c.size_tier, c.size_rank
        from competitor_findings f
        join competitors c on c.id = f.competitor_id
        where {' and '.join(clauses)}
        order by {ordering}
        """,
        tuple(params),
    )
    if latest_only:
        rows.sort(key=lambda row: (
            {"high": 0, "medium": 1, "low": 2}.get(row.get("impact_level"), 3),
            row.get("size_rank") or 999,
        ))
    return rows


def list_recent_findings(project_id: int, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
    """Findings for one study, highest impact first, with a total count for pagination."""
    where = "f.project_id = %s and f.validation_status != 'rejected'"

    total = (db.fetch_one(
        f"select count(*)::int as total from competitor_findings f where {where}",
        (int(project_id),),
    ) or {}).get("total") or 0

    rows = db.fetch_all(
        f"""
        select {_finding_select()},
               c.name as competitor_name, c.size_tier,
               p.id as study_id, p.name as study_name
        from competitor_findings f
        join competitors c on c.id = f.competitor_id
        join projects p on p.id = f.project_id
        where {where}
        order by {_IMPACT_ORDER.replace('impact_level', 'f.impact_level')}, f.generated_at desc
        limit %s offset %s
        """,
        (int(project_id), int(limit), int(offset)),
    )
    return rows, total


def _finding_select() -> str:
    return ", ".join(f"f.{name.strip()}" for name in FINDING_COLUMNS.replace("\n", " ").split(",") if name.strip())


def get_finding(finding_id: int) -> dict | None:
    return db.fetch_one(
        f"""
        select {_finding_select()},
               c.name as competitor_name, c.website as competitor_website,
               c.domain as competitor_domain, c.description as competitor_description,
               c.size_tier, c.size_rank, c.size_signals, c.status as competitor_status
        from competitor_findings f
        join competitors c on c.id = f.competitor_id
        where f.id = %s
        """,
        (int(finding_id),),
    )


def set_finding_validation(finding_id: int, status: str, notes: str = "") -> dict | None:
    if status not in {"pending", "validated", "rejected"}:
        return None
    return db.fetch_one(
        f"""
        update competitor_findings
           set validation_status = %s, validation_notes = %s
         where id = %s
        returning {FINDING_COLUMNS}
        """,
        (status, notes.strip() or None, int(finding_id)),
    )


def rejected_evidence(competitor_id: int, limit: int = 50) -> list[dict]:
    """What was filtered out and why — the audit trail behind a card's numbers."""
    return db.fetch_all(
        """
        select a.id, a.url, a.title, a.source, ca.rejected_reason,
               coalesce(a.published_at, a.created_at) as dated
        from competitor_articles ca
        join articles a on a.id = ca.article_id
        where ca.competitor_id = %s and ca.validation_status = 'rejected'
        order by dated desc
        limit %s
        """,
        (int(competitor_id), int(limit)),
    )
