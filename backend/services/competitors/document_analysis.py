"""Analysis for offline (document-upload) studies.

An online study knows its competitors before it has any evidence: the user
names them, or discovery does, and scraping then goes looking for what they've
been up to. An offline study arrives the other way round - the evidence is
already here, sitting in uploaded documents, and nobody has said who it is
about. So this module supplies the one missing piece and then hands off:

  1. `derive_competitors` reads the articles approved out of those documents and
     asks the LLM which companies they actually name.
  2. Each is upserted as a *tracked* competitor, so
     `competitor_analysis.generate_findings` - unchanged, the same code path an
     online study uses - can produce the report.

Two details make step 1 more than a convenience. `generate_findings` refuses to
run with no tracked competitors, and `validate_competitor_articles` only lets an
article inform a finding when the competitor's name is whole-word matched in its
text. Deriving the names *from that same text* satisfies both by construction:
every competitor created here is guaranteed to have at least the evidence it was
read out of, so the report can't come back empty for want of a name that was
spelled differently.

The period filter is deliberately dropped (`period_days=None`). Uploaded
documents describe activity from whenever the document is about, but their
articles are stamped with the moment they were uploaded, so a trailing-30-day
window either lets everything through or nothing, and never means what it says.
"""

from __future__ import annotations

import json
import logging

import config
import db
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.competitors import competitor_analysis, competitors_store
from services.competitors.business_profile_store import get_profile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = load_prompt("document_competitor_extraction_system_prompt.txt")
PROMPT_VERSION = "document-competitor-extraction-2026-08-07"

MAX_CHARS_PER_ARTICLE = 1500
MAX_INPUT_CHARS = 24000
MAX_COMPANIES = 15


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def approved_articles(project_id: int) -> list[dict]:
    """The real `articles` rows behind this study's approved candidates.

    Reads through `competitor_document_articles.article_id` rather than matching
    on the synthetic `document://` URL, so this stays correct if the URL scheme
    in _materialize ever changes.
    """
    return db.fetch_all(
        """
        select a.id, a.title, a.summary, a.text
        from competitor_document_articles cda
        join articles a on a.id = cda.article_id
        where cda.project_id = %s and cda.status = 'approved'
        order by cda.id
        """,
        (int(project_id),),
    )


def _corpus(articles: list[dict]) -> str:
    """One block of article text for the naming call, capped both per article and
    in total so a big upload can't blow past the model's context."""
    blocks: list[str] = []
    used = 0
    for index, article in enumerate(articles, start=1):
        body = str(article.get("text") or article.get("summary") or "")[:MAX_CHARS_PER_ARTICLE]
        block = f"[{index}] {article.get('title') or '(untitled)'}\n{body}"
        if used + len(block) > MAX_INPUT_CHARS:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _ask_llm(corpus: str, own_business: str) -> list[dict]:
    user_prompt = (
        f"The reader's own business: {own_business or '(not known - exclude nobody on this basis)'}\n\n"
        f"<articles>\n{corpus}\n</articles>\n\n"
        "Return the JSON now."
    )
    raw = chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
        timeout=120,
        model=config.COMPETITOR_LLM_CHAT_MODEL,
        api_key=config.COMPETITOR_LLM_API_KEY,
        base_url=config.COMPETITOR_LLM_CHAT_BASE_URL,
        api_style=config.COMPETITOR_LLM_API_STYLE,
        reasoning_effort=config.COMPETITOR_LLM_REASONING_EFFORT,
        api_key_env_name=config.COMPETITOR_LLM_API_KEY_ENV_NAME,
    )
    parsed = json.loads(_strip_fences(raw))
    items = parsed.get("companies") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        return []

    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in items[:MAX_COMPANIES]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if len(name) < 2 or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        cleaned.append({
            "name": name[:200],
            "website": str(item.get("website") or "").strip() or None,
            "description": str(item.get("description") or "").strip()[:500] or None,
        })
    return cleaned


def derive_competitors(project_id: int) -> dict:
    """Name the companies this study's approved articles are about, and track them.

    Returns `{competitors, considered, error}`. Created as 'tracked' rather than
    'suggested': the user already reviewed this evidence article by article on
    the previous step, so asking them to confirm the companies read out of it
    would be a second review of the same decision. `upsert_competitor` keeps an
    existing 'tracked' status and a manual `discovery_source`, so re-running this
    can't downgrade or relabel a competitor the user set up by hand.
    """
    articles = approved_articles(project_id)
    if not articles:
        return {
            "competitors": [],
            "considered": 0,
            "error": "No approved articles to analyze. Approve at least one on the review step.",
        }

    profile = get_profile(project_id)
    try:
        companies = _ask_llm(_corpus(articles), str((profile or {}).get("name") or ""))
    except Exception as exc:  # LLMError, json/ValueError - all mean "no names this run"
        logger.warning("document competitor derivation failed for project %s: %s", project_id, exc)
        return {
            "competitors": [],
            "considered": len(articles),
            "error": f"Could not read competitor names out of your documents: {exc}",
        }

    saved = []
    for company in companies:
        record = competitors_store.upsert_competitor(project_id, {
            **company,
            "status": "tracked",
            "discovery_source": "document",
        })
        if record:
            saved.append(record)

    if saved:
        competitors_store.rerank_competitors(project_id)
    return {"competitors": saved, "considered": len(articles), "error": None}


def analyze_documents(project_id: int) -> dict:
    """Derive competitors from the approved documents, then generate findings.

    A derivation that names nobody is not fatal on its own - a study can already
    have tracked competitors from an earlier run or a manual entry, and
    `generate_findings` reports the "nothing to analyze" case itself - so the
    derivation error is carried through as `derivation_error` for the UI to show
    rather than raised over the top of a report that may still be fine.
    """
    derived = derive_competitors(project_id)
    result = competitor_analysis.generate_findings(project_id, period_days=None)

    # generate_findings' own "No tracked competitors" message is written for the
    # online flow (go track one); it's a non sequitur when there was nothing to
    # track it with in the first place, so replace it with what actually happened.
    if result.get("error") and not derived["competitors"]:
        result = {
            **result,
            "error": derived["error"] or "No competitor names could be read out of your approved articles.",
        }

    return {
        **result,
        "derived_competitors": derived["competitors"],
        "articles_considered": derived["considered"],
        "derivation_error": derived["error"],
    }
