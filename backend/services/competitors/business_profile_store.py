"""The user's own business: the reference point for every competitor judgement.

A competitor report is only useful if the tool knows what the user actually does.
Asking them to type it produces a sentence or two of marketing copy; reading their
website produces what the business says about itself at length. So the profile is
built by scraping their site with the extractor already in the stack (trafilatura,
same as the article scraper) and having the LLM read it back as structured market
context.

Everything derived is stored, including which pages were read and how much text
came back, so a thin or failed scrape is visible rather than quietly producing a
vague profile that then degrades every downstream comparison.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin, urlparse

import requests

import db
from llm_client import LLMError, chat_completion

PROMPT_VERSION = "competitor-profile-2026-07-27"

# A handful of pages is plenty: the home page says what the company does, and
# about/product/pricing pages say who it is for and how it positions itself.
CANDIDATE_PATHS = (
    "", "/about", "/about-us", "/company", "/products", "/product",
    "/services", "/solutions", "/pricing", "/platform",
)
MAX_PAGES = 6
MAX_CHARS_PER_PAGE = 6000
MAX_CONTEXT_CHARS = 18000
FETCH_TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 StrataProfile"
    )
}

PROFILE_SYSTEM_PROMPT = """You read a company's own website and describe the business factually.

Rules:
- Use ONLY the supplied page text. Never invent products, customers, or claims.
- If the text does not support a field, return "" or [] — never a placeholder.
- Write every field in English regardless of the site's language.
- Be concrete. "Project management software for construction subcontractors" is
  useful; "innovative solutions provider" is not.

Return ONLY this JSON object, no markdown and no commentary:
{
  "name": "",
  "industry": "",
  "market": "the specific market/category this business competes in",
  "geography": "",
  "positioning": "one sentence on how it positions itself",
  "offerings": [],
  "audience": [],
  "differentiators": [],
  "keywords": [],
  "context_summary": "3-4 sentences an analyst could use to judge whether a competitor's move matters to this business"
}"""


def _normalize_website(value: str | None) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else ""


def _extract(url: str) -> str:
    """Fetch one page and return clean text, or "" on any failure."""
    try:
        import trafilatura

        response = requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT)
        if not response.ok:
            return ""
        text = trafilatura.extract(response.text, url=url, include_comments=False) or ""
        return text.strip()[:MAX_CHARS_PER_PAGE]
    except Exception:
        return ""


def _discover_internal_links(base: str, html: str, limit: int = 6) -> list[str]:
    """Same-domain links from the home page, as a fallback when guessed paths 404."""
    try:
        from parsel import Selector
    except Exception:
        return []
    try:
        selector = Selector(text=html)
    except Exception:
        return []

    domain = urlparse(base).netloc
    wanted = ("about", "product", "service", "solution", "pricing", "platform", "company")
    found: list[str] = []
    for href in selector.css("a::attr(href)").getall():
        link = urljoin(base, str(href).split("#")[0].strip())
        if urlparse(link).netloc != domain or link in found:
            continue
        if any(token in link.lower() for token in wanted):
            found.append(link)
        if len(found) >= limit:
            break
    return found


def scrape_website(website: str) -> dict:
    """Read a company's site and return the raw material for profiling.

    Returns `{pages: [{url, chars, text}], text, chars, status, error}`. Never
    raises — a failed scrape is a reportable state, not an exception, because the
    onboarding flow has to keep going and tell the user what happened.
    """
    base = _normalize_website(website)
    if not base:
        return {"pages": [], "text": "", "chars": 0, "status": "skipped",
                "error": "No website supplied."}

    pages: list[dict] = []
    seen: set[str] = set()

    home_html = ""
    try:
        response = requests.get(base, headers=HEADERS, timeout=FETCH_TIMEOUT)
        if response.ok:
            home_html = response.text
    except Exception as exc:
        return {"pages": [], "text": "", "chars": 0, "status": "failed",
                "error": f"Could not reach {base}: {exc}"}

    candidates = [urljoin(base, path) for path in CANDIDATE_PATHS]
    candidates.extend(_discover_internal_links(base, home_html))

    for url in candidates:
        if len(pages) >= MAX_PAGES:
            break
        if url in seen:
            continue
        seen.add(url)
        text = _extract(url)
        if len(text) < 120:  # nav-only or empty page
            continue
        pages.append({"url": url, "chars": len(text), "text": text})

    combined = "\n\n---\n\n".join(
        f"[{page['url']}]\n{page['text']}" for page in pages
    )[:MAX_CONTEXT_CHARS]

    if not pages:
        return {"pages": [], "text": "", "chars": 0, "status": "failed",
                "error": f"Reached {base} but extracted no readable page text."}

    return {"pages": pages, "text": combined, "chars": len(combined),
            "status": "success", "error": None}


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _as_list(value, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def derive_profile(name: str, website: str, description: str, scraped_text: str) -> dict:
    """Turn scraped site text into structured market context via the LLM."""
    supplied = json.dumps(
        {"name": name or "", "website": website or "", "description": description or ""}
    )
    user_prompt = (
        f"What the user told us:\n{supplied}\n\n"
        f"Text extracted from their website:\n{scraped_text or '(none — rely on what the user told us)'}"
    )

    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1400,
            timeout=90,
        )
        parsed = json.loads(_strip_fences(raw))
    except (LLMError, json.JSONDecodeError, ValueError) as exc:
        print(f"  business profile derivation failed: {exc}")
        return {}

    if not isinstance(parsed, dict):
        return {}

    return {
        "name": str(parsed.get("name") or name or "").strip(),
        "industry": str(parsed.get("industry") or "").strip(),
        "market": str(parsed.get("market") or "").strip(),
        "geography": str(parsed.get("geography") or "").strip(),
        "positioning": str(parsed.get("positioning") or "").strip(),
        "offerings": _as_list(parsed.get("offerings")),
        "audience": _as_list(parsed.get("audience")),
        "differentiators": _as_list(parsed.get("differentiators")),
        "keywords": _as_list(parsed.get("keywords"), limit=20),
        "context_summary": str(parsed.get("context_summary") or "").strip(),
    }


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
PROFILE_COLUMNS = """
    id, project_id, name, website, description, industry, market, geography,
    positioning, offerings, audience, differentiators, keywords,
    scrape_status, scrape_error, scraped_pages, scraped_chars, scraped_at,
    context_summary, analysis_model, prompt_version, created_at, updated_at
"""


def get_profile(project_id: int) -> dict | None:
    return db.fetch_one(
        f"select {PROFILE_COLUMNS} from business_profiles where project_id = %s",
        (int(project_id),),
    )


def upsert_profile(project_id: int, values: dict) -> dict | None:
    """Insert or update the profile for a project."""
    from psycopg.types.json import Jsonb

    payload = {
        "name": str(values.get("name") or "").strip() or "Unnamed business",
        "website": _normalize_website(values.get("website")) or None,
        "description": (str(values.get("description") or "").strip() or None),
        "industry": (str(values.get("industry") or "").strip() or None),
        "market": (str(values.get("market") or "").strip() or None),
        "geography": (str(values.get("geography") or "").strip() or None),
        "positioning": (str(values.get("positioning") or "").strip() or None),
        "offerings": Jsonb(_as_list(values.get("offerings"))),
        "audience": Jsonb(_as_list(values.get("audience"))),
        "differentiators": Jsonb(_as_list(values.get("differentiators"))),
        "keywords": Jsonb(_as_list(values.get("keywords"), limit=20)),
        "scrape_status": str(values.get("scrape_status") or "pending"),
        "scrape_error": (str(values.get("scrape_error") or "").strip() or None),
        "scraped_pages": int(values.get("scraped_pages") or 0),
        "scraped_chars": int(values.get("scraped_chars") or 0),
        "scraped_at": values.get("scraped_at"),
        "context_summary": (str(values.get("context_summary") or "").strip() or None),
        "analysis_model": (str(values.get("analysis_model") or "").strip() or None),
        "prompt_version": PROMPT_VERSION,
    }

    fields = list(payload)
    assignments = ", ".join(f"{field} = excluded.{field}" for field in fields)
    return db.fetch_one(
        f"""
        insert into business_profiles (project_id, {', '.join(fields)})
        values (%s, {', '.join(['%s'] * len(fields))})
        on conflict (project_id) do update set {assignments}
        returning {PROFILE_COLUMNS}
        """,
        (int(project_id), *[payload[field] for field in fields]),
    )


def build_profile(project_id: int, values: dict) -> dict:
    """Scrape the website, derive market context, and persist. Returns the profile.

    The scrape outcome is always recorded, so onboarding can say "we read 5 pages"
    or "we couldn't reach that site" instead of silently producing a thin profile.
    """
    name = str(values.get("name") or "").strip()
    website = str(values.get("website") or "").strip()
    description = str(values.get("description") or "").strip()

    scrape = scrape_website(website) if website else {
        "pages": [], "text": "", "chars": 0, "status": "skipped",
        "error": "No website supplied.",
    }
    derived = derive_profile(name, website, description, scrape["text"])

    import config
    from datetime import datetime, timezone

    merged = {
        "name": derived.get("name") or name,
        "website": website,
        "description": description,
        **{key: derived.get(key) for key in (
            "industry", "market", "geography", "positioning",
            "offerings", "audience", "differentiators", "keywords",
            "context_summary",
        )},
        "scrape_status": scrape["status"],
        "scrape_error": scrape["error"],
        "scraped_pages": len(scrape["pages"]),
        "scraped_chars": scrape["chars"],
        "scraped_at": datetime.now(timezone.utc) if scrape["pages"] else None,
        "analysis_model": config.LLM_CHAT_MODEL if derived else None,
    }

    saved = upsert_profile(project_id, merged)
    return {
        "profile": saved,
        "scrape": {
            "status": scrape["status"],
            "error": scrape["error"],
            "pages": [{"url": page["url"], "chars": page["chars"]} for page in scrape["pages"]],
            "chars": scrape["chars"],
        },
        "ai_derived": bool(derived),
    }


def profile_context(profile: dict | None) -> str:
    """Compact text block describing the business, for prompts."""
    if not profile:
        return ""
    parts = [f"Business: {profile.get('name') or 'unknown'}"]
    for label, key in (
        ("Industry", "industry"), ("Market", "market"),
        ("Geography", "geography"), ("Positioning", "positioning"),
    ):
        value = str(profile.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    for label, key in (
        ("Offerings", "offerings"), ("Audience", "audience"),
        ("Differentiators", "differentiators"),
    ):
        values = profile.get(key) or []
        if isinstance(values, list) and values:
            parts.append(f"{label}: {', '.join(str(v) for v in values[:8])}")
    summary = str(profile.get("context_summary") or "").strip()
    if summary:
        parts.append(f"Context: {summary}")
    return "\n".join(parts)
