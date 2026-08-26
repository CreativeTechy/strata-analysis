"""The user's own business: the reference point for every competitor judgement.

A competitor report is only useful if the tool knows what the user actually
does. The original product read that off their website; this one has no web
access, so the profile is built the only honest way left: the user types what
their business is, and the LLM turns that into the same structured market
context (industry, market, positioning, offerings, audience, differentiators)
the analysis prompts expect.

That makes the description the user writes load-bearing rather than decorative -
a one-line description produces a thin profile, and a thin profile weakens every
"how does this affect us" judgement downstream - so the wizard asks for it
properly instead of treating it as an optional field.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

import config
import db
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from services.competitors.countries import country_label, validate_countries

PROMPT_VERSION = "competitor-profile-2026-08-24"

PROFILE_SYSTEM_PROMPT = load_prompt("competitor_profile_system_prompt.txt")


def _normalize_website(value: str | None) -> str:
    """Shape-check an optional website. Never fetched - it is recorded as
    reference information and, where the user gives no description, as one more
    hint about what the business is called."""
    url = str(value or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    netloc = urlparse(url).netloc.lower()
    if not netloc or "." not in netloc:
        return ""
    return url


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


def derive_profile(name: str, website: str, description: str) -> dict:
    """Turn what the user typed into structured market context via the LLM."""
    supplied = json.dumps(
        {"name": name or "", "website": website or "", "description": description or ""}
    )
    user_prompt = (
        f"What the user told us about their business:\n{supplied}\n\n"
        "There is no website text available - work only from what they told you, "
        "and leave a field empty rather than inventing detail it does not support."
    )

    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1400,
            timeout=config.BUSINESS_PROFILE_LLM_TIMEOUT_SECONDS,
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
    target_countries, positioning, offerings, audience, differentiators, keywords,
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
        "target_countries": Jsonb(validate_countries(values.get("target_countries"))),
        "positioning": (str(values.get("positioning") or "").strip() or None),
        "offerings": Jsonb(_as_list(values.get("offerings"))),
        "audience": Jsonb(_as_list(values.get("audience"))),
        "differentiators": Jsonb(_as_list(values.get("differentiators"))),
        "keywords": Jsonb(_as_list(values.get("keywords"), limit=20)),
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
    """Derive market context from what the user typed, and persist it.

    `ai_derived` is False when the model call failed or came back unusable; the
    profile is still saved from the raw input in that case, so the wizard can
    say the structuring step didn't run rather than losing what was typed.
    """
    import config

    name = str(values.get("name") or "").strip()
    website = _normalize_website(values.get("website"))
    description = str(values.get("description") or "").strip()

    derived = derive_profile(name, website, description)

    merged = {
        "name": derived.get("name") or name,
        "website": website,
        "description": description,
        "target_countries": validate_countries(values.get("target_countries")),
        **{key: derived.get(key) for key in (
            "industry", "market", "geography", "positioning",
            "offerings", "audience", "differentiators", "keywords",
            "context_summary",
        )},
        "analysis_model": config.LLM_CHAT_MODEL if derived else None,
    }

    saved = upsert_profile(project_id, merged)
    return {"profile": saved, "ai_derived": bool(derived)}


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
    countries = validate_countries(profile.get("target_countries"))
    if countries:
        parts.append(f"Target countries: {', '.join(country_label(code) for code in countries)}")
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
