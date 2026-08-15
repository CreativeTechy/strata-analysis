"""Turn scraped competitor content into decision-grade analysis cards.

Two stages, and the first one matters more than the second.

**Validation (`validate_competitor_articles`).** Reports here are read as input to
business decisions — what to build, what to price, where to move. So an article is
only allowed to inform a finding if it survives explicit gates, each of which
records *why* a row was dropped:

  - it passes the existing `content_guard` (no consent interstitials, no search pages)
  - it is not evergreen site furniture — a Contact Us or Careers page names the
    company in its own nav on every one, so presence alone can't tell it apart
    from news about the company
  - it has enough body text to say anything
  - **the competitor is actually named in it, prominently** — this is the gate
    that matters. A competitor's own domain publishes plenty that is about
    nobody in particular, and keyword-adjacent articles routinely mention a
    whole market. Without this, a report attributes the industry's news to one
    company. Prominence rather than presence, because a company named once in
    paragraph nine of a twenty-company roundup is not what that piece is about.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from psycopg.types.json import Jsonb

import config
import db
from content_guard import is_blocked_article
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from services.competitors.job_runs import ACTIVE_STATUSES, JobRegistry

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

# Below this, the competitor is mentioned but the piece is not about them.
# See _mention_profile for what the tiers mean; 0.35 admits a body-only mention
# that is either repeated or up front, and drops a lone late one.
MIN_MENTION_SCORE = 0.35

# One LLM call per competitor, so a study with a dozen of them serialized into a
# dozen sequential round trips on a request the user is watching. Kept modest
# rather than unbounded for the same reason ENRICH_CONCURRENCY is: the ceiling
# is the provider's, and this shares an account with enrichment and Copilot.
ANALYSIS_CONCURRENCY = 4

IMPACT_LEVELS = {"high", "medium", "low"}

ANALYSIS_SYSTEM_PROMPT = load_prompt("competitor_analysis_system_prompt.txt")


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


# Nav labels a discovery pass can come back with as a company name. As a
# plain-text matcher a word like this fires on any article that happens to
# contain it: the live data had a competitor named "Stories" matching "Fact
# Check: Photos Show..." at full title prominence, i.e. a fabricated signal
# carrying a confident score. A name that is only a common word cannot be
# matched on text alone, so it is not used as an alias at all.
_GENERIC_ALIASES = {
    "about", "blog", "brand", "brands", "cart", "collection", "collections",
    "contact", "event", "events", "gallery", "help", "home", "media", "menu",
    "menus", "news", "press", "product", "products", "service", "services",
    "shop", "stories", "story", "support", "team", "work",
}


def _aliases(competitor: dict) -> list[str]:
    """Names to look for in article text: the company name, and its bare domain.

    Aliases that are just a common word are dropped — see _GENERIC_ALIASES. A
    competitor left with none of them matches nothing, which is the intended
    outcome: no card at all beats a card built from every article containing
    the word "news".
    """
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
    return [name for name in names if name.casefold() not in _GENERIC_ALIASES]


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


# Evergreen furniture on a company's own site. Every one of these names the
# company in its nav and footer, so the mention gate passes them on presence
# alone, and `_effective_date` dates a `web` page by when it was scraped — so a
# Contact Us page looks freshly published every crawl and never ages out of the
# window. Left in, they crowd out actual news and the model gets asked what
# changed while looking at a careers listing and a store locator.
_BOILERPLATE_PATH_RE = re.compile(
    r"/(contact|about|about-us|careers?|jobs|work-with-us|team|locations?|stores?|"
    r"store-locator|find-us|franchise|faq|help|support|terms|privacy|policy|policies|"
    r"shipping|returns?|refunds?|cart|checkout|account|login|sign-?in|register|"
    r"wishlist|sitemap)(/|$|\?)",
    re.I,
)
_BOILERPLATE_TITLE_RE = re.compile(
    r"^\s*(contact|about|careers?|jobs|work with us|our team|locations?|stores?|"
    r"find us|franchise|faq|frequently asked|terms|privacy|shipping|returns?|"
    r"my account|shopping cart|checkout|log ?in|sign ?in|register|wishlist)\b",
    re.I,
)


def _is_boilerplate_page(url: str, title: str) -> bool:
    path = urlparse(str(url or "")).path
    return bool(_BOILERPLATE_PATH_RE.search(path) or _BOILERPLATE_TITLE_RE.search(str(title or "")))


def _mention_profile(title: str, summary: str, body: str, aliases: list[str]) -> tuple[str | None, float]:
    """Which alias the article names, and how central it is to the piece.

    Prominence, not presence. A competitor in the headline is what the article
    is about. A competitor named once, late, in a twenty-company market roundup
    is not — and handing that to the model as evidence of "what they're doing"
    is how a card ends up describing a move that never happened.

    The score is stored as `competitor_articles.match_score`, which until now
    was always a hardcoded 1.0 and therefore carried no information at all.
    """
    for field, score in ((title, 1.0), (summary, 0.7)):
        alias = _mentions(field, aliases)
        if alias:
            return alias, score

    alias = _mentions(body, aliases)
    if not alias:
        return None, 0.0

    hits = [match.start() for match in re.finditer(
        rf"(?<!\w){re.escape(alias)}(?!\w)", body, re.IGNORECASE
    )]
    # Repeated, or introduced up front: the piece keeps coming back to them.
    leads = bool(hits) and hits[0] < max(1, len(body)) * 0.25
    return alias, 0.45 if (len(hits) >= 3 or leads) else 0.2


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


def validate_competitor_articles(project_id: int, competitors: list[dict],
                                 period_days: int = DEFAULT_PERIOD_DAYS, log=None) -> dict:
    """Attribute articles to competitors, recording accept/reject reasons.

    Returns per-competitor counts plus an aggregate rejection breakdown, so the
    workspace can show what was filtered and why instead of a bare total.
    """
    log = log or (lambda _message: None)
    since = datetime.now(timezone.utc) - timedelta(days=period_days) if period_days else None
    articles = _candidate_articles(project_id)
    if since is not None:
        articles = [a for a in articles if (_effective_date(a) or since) >= since]
    window = f"the last {period_days} days" if period_days else "all time"
    log(f"Checking {len(articles)} article(s) from {window} against each competitor...")

    alias_map = {int(c["id"]): _aliases(c) for c in competitors}
    per_competitor: dict[int, dict] = {
        int(c["id"]): {"valid": 0, "rejected": 0, "stories": set()} for c in competitors
    }
    rejection_reasons: dict[str, int] = {}
    rows: list[tuple] = []

    for article in articles:
        body = str(article.get("text") or "")
        title = str(article.get("title") or "")
        summary = str(article.get("summary") or "")

        blocked = is_blocked_article(article.get("url"), title)
        # Uploaded-document candidates are LLM-split excerpts, not crawled
        # pages: they have no URL path to read and are short-form by design
        # (see MIN_DOCUMENT_BODY_CHARS above), so both the site-furniture and
        # the prominence gates would reject them for being what they are.
        is_document = str(article.get("url") or "").startswith(DOCUMENT_URL_PREFIX)
        boilerplate = not is_document and _is_boilerplate_page(article.get("url"), title)
        too_short = len(body) < (MIN_DOCUMENT_BODY_CHARS if is_document else MIN_BODY_CHARS)

        for competitor_id, aliases in alias_map.items():
            matched, score = _mention_profile(title, summary, body, aliases) if aliases else (None, 0.0)
            if matched is None:
                continue  # not about this competitor at all: not a rejection, just unrelated

            reason = None
            if blocked:
                reason = "blocked_page"
            elif boilerplate:
                reason = "boilerplate_page"
            elif too_short:
                reason = "body_too_short"
            elif score < MIN_MENTION_SCORE and not is_document:
                reason = "passing_mention"
            else:
                story_id = article.get("story_id")
                if story_id is not None and story_id in per_competitor[competitor_id]["stories"]:
                    reason = "duplicate_story"

            if reason:
                per_competitor[competitor_id]["rejected"] += 1
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
                rows.append((competitor_id, int(article["id"]), matched, score, "rejected", reason))
                continue

            if article.get("story_id") is not None:
                per_competitor[competitor_id]["stories"].add(article["story_id"])
            per_competitor[competitor_id]["valid"] += 1
            rows.append((competitor_id, int(article["id"]), f"mentions:{matched}", score, "valid", None))

    # Everything this run did *not* visit has to go, or the table stops
    # describing the period the card claims. Only in-window articles are
    # scanned above, and nothing here ever deleted, so a row written by an
    # earlier run against a longer window survived untouched and kept counting:
    # `_counts_for` has no date bound, so article_count grew monotonically for
    # the life of the study, and a 30-day card could report the numbers - and
    # serve the evidence - of a 365-day one. Rejections are pruned on the same
    # rule, so the audit trail stays consistent with the counts rather than
    # explaining filtering the card never did.
    with db.transaction() as cur:
        cur.execute(
            """
            delete from competitor_articles
             where competitor_id = any(%s)
               and not (article_id = any(%s))
            """,
            (list(alias_map.keys()), [int(article["id"]) for article in articles]),
        )
        if rows:
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

    kept = sum(stats["valid"] for stats in per_competitor.values())
    log(f"Kept {kept} article(s) as evidence.")
    if rejection_reasons:
        log("Filtered out: " + ", ".join(
            f"{count} {reason.replace('_', ' ')}"
            for reason, count in sorted(rejection_reasons.items(), key=lambda item: -item[1])
        ) + ".")
    for competitor in competitors:
        stats = per_competitor[int(competitor["id"])]
        if not stats["valid"]:
            log(f"{competitor.get('name')}: nothing usable found.")

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
    """Validated evidence for one competitor, newest first, one row per story.

    Two orderings, and they have to be separate. `distinct on` forces its own
    expression to lead the `order by`, so the inner query can only rank rows
    *within* a story group - that is what picks the newest member of each. The
    result set then comes back ordered by story id, which is an identity
    sequence (migration 0003), i.e. oldest group first. Taking the top `limit`
    of that would hand the model the stalest stories it has and ask it what
    changed. The outer query re-sorts the deduplicated rows by date so the
    limit actually means "most recent".
    """
    return db.fetch_all(
        """
        select * from (
            select distinct on (coalesce(a.story_id, -a.id))
                   a.id, a.url, a.source, a.title, a.summary, a.text,
                   a.published_at, a.created_at, a.story_id, ca.match_reason
            from competitor_articles ca
            join articles a on a.id = ca.article_id
            where ca.competitor_id = %s and ca.validation_status = 'valid'
            order by coalesce(a.story_id, -a.id),
                     coalesce(a.published_at, a.created_at) desc
        ) newest_per_story
        order by coalesce(published_at, created_at) desc
        limit %s
        """,
        (int(competitor_id), int(limit)),
    )


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
        # The card is parsed as JSON below and dropped entirely when that
        # fails, which the user sees as the indistinguishable "Analysis could
        # not be generated". Asking the provider to enforce the shape is free -
        # both api_styles support it (see llm_client._build_body).
        json_mode=True,
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

    # Left null rather than defaulted to a placeholder: a card whose model
    # didn't explain its score should show no explanation, not a fabricated
    # one. Pre-migration findings read the same way.
    confidence_reason = str(parsed.get("confidence_reason") or "").strip()[:500] or None

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
            confidence, confidence_reason, article_count, story_count,
            validation_status, analysis_model, prompt_version, generated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id, project_id, competitor_id, period_start, period_end, headline,
                  whats_up, impact, impact_level, actions, signals, evidence,
                  confidence, confidence_reason, article_count, story_count,
                  validation_status, validation_notes, analysis_model,
                  prompt_version, generated_at
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
            confidence_reason,
            counts["articles"],
            counts["stories"],
            "pending",
            config.COMPETITOR_LLM_CHAT_MODEL,
            PROMPT_VERSION,
            now,
        ),
    )


def generate_findings(project_id: int, period_days: int = DEFAULT_PERIOD_DAYS, log=None) -> dict:
    """Validate evidence then produce one card per tracked competitor.

    `log` receives one human-readable progress line per step. It exists because
    this runs as a background job the user watches (see run_analysis_job) and
    the interesting part - which competitor is being analyzed, what evidence
    survived, what came back - is otherwise invisible until the whole thing
    finishes. Defaults to a no-op so the CLI/seed path can call this unchanged.
    """
    from services.competitors.business_profile_store import get_profile
    from services.competitors.competitors_store import list_competitors

    log = log or (lambda _message: None)

    profile = get_profile(project_id)
    competitors = list_competitors(project_id, status="tracked")
    if not competitors:
        return {"generated": 0, "skipped": 0, "validation": None,
                "error": "No tracked competitors. Track at least one to analyze."}

    log(f"Analyzing {len(competitors)} tracked competitor{'' if len(competitors) == 1 else 's'}.")
    validation = validate_competitor_articles(project_id, competitors, period_days, log=log)

    generated = 0
    skipped: list[dict] = []
    llm_errors: list[LLMError] = []

    def _analyze(competitor: dict) -> tuple[dict, dict | None, LLMError | None]:
        """One competitor's card. Returns the error rather than raising it so a
        single provider failure doesn't cancel the rest of the pool."""
        name = competitor.get("name")
        stats = validation["per_competitor"].get(int(competitor["id"]), {})
        stories = stats.get("stories") or 0
        # Validation already reported the ones with nothing to read; claiming to
        # write a report from zero stories would just be noise contradicting it.
        if stories:
            log(f"{name}: writing a report from {stories} stor{'y' if stories == 1 else 'ies'}...")
        try:
            finding = generate_finding(profile, competitor, period_days)
        except LLMError as exc:
            log(f"{name}: failed - {exc.user_message}")
            return competitor, None, exc
        if finding:
            log(f"{name}: {finding.get('impact_level')} impact - {finding.get('headline')}")
        return competitor, finding, None

    # Independent LLM calls that were being awaited one at a time on a request
    # the user is sitting in front of. `map` keeps the results in competitor
    # order, so `skipped` stays deterministic. DB writes are left to the main
    # thread below; the reads inside generate_finding each open their own
    # connection (db.connect), which is why this is safe to thread at all.
    # Progress lines are appended from the worker threads, hence the lock in
    # JobRegistry.append_log - they interleave, which is the point: the user
    # sees several competitors in flight rather than a stalled single line.
    with ThreadPoolExecutor(max_workers=min(ANALYSIS_CONCURRENCY, len(competitors))) as pool:
        results = list(pool.map(_analyze, competitors))

    for competitor, finding, error in results:
        if error is not None:
            print(f"  finding generation failed for {competitor.get('name')}: {error.detail or error}")
            llm_errors.append(error)
            continue
        if finding:
            generated += 1
            db.execute(
                "update competitors set last_analyzed_at = now() where id = %s",
                (int(competitor["id"]),),
            )
        else:
            stats = validation["per_competitor"].get(int(competitor["id"]), {})
            if not _aliases(competitor):
                # Distinguishable from "nothing was published": nothing could
                # have been matched in the first place, and the fix is to give
                # the competitor a real name/domain, not to widen the period.
                reason = "Name is too generic to identify in article text. Add a website or a more specific name."
            elif not stats.get("valid"):
                reason = "No validated evidence in this period."
            else:
                reason = "Analysis could not be generated."
            log(f"{competitor['name']}: skipped - {reason}")
            skipped.append({
                "competitor_id": competitor["id"],
                "name": competitor["name"],
                "reason": reason,
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

    log(f"Done. Generated {generated} report{'' if generated == 1 else 's'}"
        + (f", skipped {len(skipped)}." if skipped else "."))

    return {
        "generated": generated,
        "skipped": skipped,
        "validation": validation,
        "error": error,
        "error_code": error_code,
    }


# --------------------------------------------------------------------------- #
# Background job
# --------------------------------------------------------------------------- #
# Analysis is one LLM call per tracked competitor, optionally preceded by a full
# scrape+enrich of every source in the study. That is minutes, not seconds, and
# it was being awaited inline in the POST handler - the user stared at a spinner
# with no idea whether it was scraping, which competitor it was on, or whether
# it had hung. It now runs the same way discovery does: queued as a FastAPI
# BackgroundTask against the shared registry, streaming progress lines the UI
# polls for.
_analysis_runs = JobRegistry("Queued for analysis.")

ACTIVE_ANALYSIS_STATUSES = ACTIVE_STATUSES


def create_analysis_run(project_id: int) -> str:
    return _analysis_runs.create(project_id, generated=0, skipped=[], validation=None, scrape_run=None)


def get_analysis_run(run_id: str) -> dict | None:
    return _analysis_runs.get(run_id)


def get_active_analysis_run(project_id: int) -> dict | None:
    return _analysis_runs.active_for_project(project_id)


def run_analysis_job(run_id: str, project_id: int, period_days: int, scrape_first: bool) -> None:
    """Scrape (optionally), validate, and write one card per competitor.

    Every failure path ends as a `failed` run carrying a readable message
    rather than an exception nobody sees: this executes after the response has
    already been sent, so raising here would only reach the server log.
    """
    log = _analysis_runs.logger(run_id)
    _analysis_runs.update(run_id, status="running", stage="scraping" if scrape_first else "analyzing",
                          message="Gathering articles." if scrape_first else "Analyzing competitors.")
    try:
        scrape_run = None
        if scrape_first:
            # Deferred, and scoped to the branch that needs it: services.pipeline
            # pulls in the whole scraper, which analysis has no reason to load
            # when it is running against evidence that is already stored.
            import uuid as _uuid

            from services.pipeline.pipeline import run_scraper_pipeline
            from services.pipeline.pipeline_runs import create_pipeline_run, get_pipeline_run

            log("Scraping this study's sources for new articles...")
            queued = create_pipeline_run(status="queued", stage="queued",
                                         message="Queued for execution.", project_id=project_id)
            scrape_id = queued["id"] if queued else _uuid.uuid4().hex
            run_scraper_pipeline(scrape_id, project_id)
            scrape_run = get_pipeline_run(scrape_id)
            if not scrape_run or scrape_run.get("status") != "success":
                raise RuntimeError(
                    "Could not gather articles before analysis: "
                    + ((scrape_run or {}).get("error") or "scrape and enrichment did not complete.")
                )
            log(f"Scrape finished: {scrape_run.get('articles_scraped') or 0} article(s) gathered.")
            _analysis_runs.update(run_id, scrape_run=scrape_run, stage="analyzing",
                                  message="Analyzing competitors.")

        result = generate_findings(project_id, period_days=period_days, log=log)

        # A provider failure is a failed run, not a run that generated zero
        # reports - same distinction generate_findings itself draws.
        if result.get("error"):
            _analysis_runs.update(
                run_id, status="failed", stage="error", error=result["error"],
                error_code=result.get("error_code"), message=result["error"],
                generated=result.get("generated") or 0, skipped=result.get("skipped") or [],
                validation=result.get("validation"), scrape_run=scrape_run,
            )
            return

        _analysis_runs.update(
            run_id, status="success", stage="done",
            message=f"Generated {result['generated']} report(s).",
            generated=result["generated"], skipped=result["skipped"],
            validation=result["validation"], scrape_run=scrape_run,
        )
    except Exception as exc:  # noqa: BLE001 - terminal state must carry the reason
        log(f"Analysis failed: {exc}")
        _analysis_runs.update(run_id, status="failed", stage="error",
                              error=str(exc), message=str(exc))


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
FINDING_COLUMNS = """
    id, project_id, competitor_id, period_start, period_end, headline,
    whats_up, impact, impact_level, actions, signals, evidence, confidence,
    confidence_reason, article_count, story_count, validation_status,
    validation_notes, analysis_model, prompt_version, generated_at
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
