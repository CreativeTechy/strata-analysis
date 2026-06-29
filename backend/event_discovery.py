"""Event link discovery for hashtags and keywords.

DeepSeek proposes feed sources directly from the event terms, then we validate
those URLs, resolve domains/RSS pages, and upsert the selected links as
reusable feed records.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from html import unescape
from urllib.parse import parse_qs, quote_plus, urlparse, unquote, urlunparse

import requests
from parsel import Selector

import config
from feeds_store import create_feed
from events_store import set_event_feeds

SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 StrataEventDiscovery"
    )
}


def _clean_terms(values):
    if values is None:
        return []
    if isinstance(values, str):
        items = [part.strip() for part in re.split(r"[\n,]", values)]
    elif isinstance(values, list):
        items = values
    else:
        items = [values]

    cleaned = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _search_term(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("#"):
        text = text[1:].strip()
    return text


def _event_context(event):
    if not isinstance(event, dict):
        return ""

    parts = []
    for key, label in (
        ("name", "Name"),
        ("status", "Status"),
        ("location", "Location"),
        ("target_audience", "Target audience"),
        ("description", "Description"),
    ):
        value = str(event.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")

    hashtags = _clean_terms(event.get("hashtags"))
    if hashtags:
        parts.append(f"Hashtags: {', '.join(hashtags)}")

    keywords = _clean_terms(event.get("keywords"))
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")

    return "\n".join(parts)


def _normalize_url(url):
    url = unescape((url or "").strip())
    if not url:
        return ""

    parsed = urlparse(url)
    if "duckduckgo.com" in (parsed.netloc or "").lower() and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        candidate = (qs.get("uddg") or [""])[0]
        if candidate:
            url = unquote(candidate)
            parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return ""

    query = parse_qs(parsed.query, keep_blank_values=True)
    tracked = {
        key: value
        for key, value in query.items()
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "ref", "ref_src"}
    }
    normalized_query = "&".join(
        f"{quote_plus(key)}={quote_plus(value[0])}" if value else quote_plus(key)
        for key, value in tracked.items()
    )
    normalized = urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path or "", parsed.params or "", normalized_query, parsed.fragment or ""))
    return normalized.rstrip("/")


def _result_entry(url, title="", snippet="", source="", query=""):
    return {
        "url": _normalize_url(url),
        "title": (title or "").strip(),
        "snippet": (snippet or "").strip(),
        "source": (source or "").strip(),
        "query": (query or "").strip(),
    }


def _search_duckduckgo(query, limit=5):
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=SEARCH_HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
    except Exception:
        return []

    selector = Selector(text=resp.text or "")
    results = []
    for item in selector.css("div.result"):
        if len(results) >= limit:
            break
        link = item.css("a.result__a::attr(href)").get()
        title = " ".join(part.strip() for part in item.css("a.result__a::text").getall() if part.strip())
        snippet = " ".join(part.strip() for part in item.css(".result__snippet ::text, .result__snippet::text").getall() if part.strip())
        entry = _result_entry(link, title=title, snippet=snippet, source="duckduckgo", query=query)
        if entry["url"]:
            results.append(entry)
    return results


def _search_bing(query, limit=5):
    try:
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers=SEARCH_HEADERS,
            timeout=25,
        )
        resp.raise_for_status()
    except Exception:
        return []

    selector = Selector(text=resp.text or "")
    results = []
    for item in selector.css("li.b_algo"):
        if len(results) >= limit:
            break
        link = item.css("h2 a::attr(href)").get()
        title = " ".join(part.strip() for part in item.css("h2 a::text").getall() if part.strip())
        snippet = " ".join(part.strip() for part in item.css("p::text").getall() if part.strip())
        entry = _result_entry(link, title=title, snippet=snippet, source="bing", query=query)
        if entry["url"]:
            results.append(entry)
    return results


def _build_queries(event):
    terms = []
    terms.extend(_clean_terms(event.get("hashtags")))
    terms.extend(_clean_terms(event.get("keywords")))
    name = str(event.get("name") or "").strip()
    description = str(event.get("description") or "").strip()

    combined = []
    for term in terms:
        query_term = _search_term(term)
        if not query_term:
            continue
        combined.append(query_term)
        if name:
            combined.append(f"{name} {query_term}")
        if description:
            combined.append(f"{query_term} {description[:80]}")
        combined.append(f"site:x.com {query_term}")
        combined.append(f"site:twitter.com {query_term}")

    if name and not combined:
        combined.append(name)

    return combined[:12]


def _fallback_candidates(event):
    name = str(event.get("name") or "").strip()
    terms = []
    terms.extend(_clean_terms(event.get("hashtags")))
    terms.extend(_clean_terms(event.get("keywords")))
    terms = [_search_term(term) for term in terms if _search_term(term)]

    candidates = []
    seen = set()
    for term in terms:
        x_query = quote_plus(term)
        x_url = f"https://x.com/search?q={x_query}&src=typed_query&f=live"
        google_news_url = f"https://news.google.com/search?q={quote_plus(term)}"
        for url, title, source in (
            (x_url, f"X search: {term}", "x-search"),
            (google_news_url, f"News search: {term}", "news-search"),
        ):
            normalized = _normalize_url(url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(
                {
                    "url": normalized,
                    "title": title,
                    "snippet": name or term,
                    "source": source,
                    "query": term,
                }
            )
    return candidates


def _collect_candidates(event):
    candidates = OrderedDict()
    queries = _build_queries(event)
    for query in queries:
        for result in _search_duckduckgo(query, limit=5) + _search_bing(query, limit=5):
            url = result.get("url")
            if not url:
                continue
            if url in candidates:
                continue
            candidates[url] = result
    collected = list(candidates.values())
    if not collected:
        collected = _fallback_candidates(event)
    return queries, collected


def _extract_json_blob(text):
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
    raw = raw.strip()
    if raw:
        return raw
    match = re.search(r"\{.*\}", text or "", re.S)
    return match.group(0).strip() if match else ""


def _deepseek_source_suggestions(event):
    if not config.DEEPSEEK_API_KEY:
        return []

    event_context = _event_context(event)
    prompt = (
        "You are helping discover feed sources for an event.\n"
        "Use only the event hashtags and keywords to propose likely feed sources.\n"
        "Return ONLY JSON with this shape:\n"
        '{ "suggested_sources": [ { "kind": "url|domain|rss", "value": "https://...", "title": "...", "reason": "..." } ], "links": ["https://..."] }\n'
        "Return 5 to 10 suggestions when possible.\n"
        "Suggested sources may be full article URLs, RSS feed URLs, publisher domains, or official social profile URLs.\n"
        "Prefer official publisher or source URLs. Do not include Bing, DuckDuckGo, or generic search results.\n"
        "If you return a domain, make it the publisher's main domain or homepage. If you return rss, make it the actual feed URL.\n\n"
        f"Event context:\n{event_context or '(none)'}\n"
    )

    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 700,
            },
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        payload = json.loads(_extract_json_blob(content))
    except Exception:
        return []

    suggestions = []
    if isinstance(payload, dict):
        suggestions = payload.get("suggested_sources") or payload.get("links") or []
    if not isinstance(suggestions, list):
        return []

    normalized = []
    seen = set()
    for item in suggestions:
        if isinstance(item, str):
            item = {"kind": "url", "value": item}
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or "url").strip().lower()
        value = str(item.get("value") or item.get("url") or "").strip()
        if not value:
            continue
        key = f"{kind}:{value.lower()}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "kind": kind,
                "value": value,
                "title": str(item.get("title") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return normalized[:10]


def _lightweight_fetch(url):
    if not url:
        return None

    headers = {"User-Agent": "StrataEventDiscovery/1.0", "Accept": "*/*"}
    try:
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        if resp.status_code not in {401, 403, 405}:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            return {
                "url": resp.url or url,
                "content_type": content_type,
                "status_code": resp.status_code,
            }
    except Exception:
        pass

    try:
        resp = requests.get(url, headers=headers, allow_redirects=True, timeout=10, stream=True)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        resp.close()
        return {
            "url": resp.url or url,
            "content_type": content_type,
            "status_code": resp.status_code,
        }
    except Exception:
        return None


def _looks_like_feed_url(url, content_type=""):
    url = (url or "").lower()
    content_type = (content_type or "").lower()
    return (
        _search_term(url).endswith(".rss")
        or _search_term(url).endswith(".xml")
        or _search_term(url).endswith("/feed")
        or "rss" in content_type
        or "xml" in content_type
        or "atom" in content_type
    )


def _resolve_source(item):
    kind = str(item.get("kind") or "url").strip().lower()
    value = str(item.get("value") or "").strip()
    title = str(item.get("title") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if not value:
        return []

    normalized = _normalize_url(value if value.startswith("http") else f"https://{value.lstrip('/')}")
    if not normalized:
        return []

    resolved = []
    root_url = normalized

    if kind == "domain":
        parsed = urlparse(normalized)
        root_url = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path}".rstrip("/")
        feed_urls = config._discover_feed_urls(root_url)
        if feed_urls:
            for feed_url in feed_urls[:1]:
                resolved.append(
                    {
                        "url": _normalize_url(feed_url),
                        "title": title or _default_name(root_url),
                        "reason": reason or "Resolved from DeepSeek domain suggestion.",
                        "source_type": "rss",
                    }
                )
            return resolved

    validated = _lightweight_fetch(root_url)
    if not validated:
        return []

    final_url = _normalize_url(validated.get("url") or root_url)
    content_type = validated.get("content_type") or ""

    if kind == "rss" or _looks_like_feed_url(final_url, content_type):
        feed_urls = [final_url]
        if not _looks_like_feed_url(final_url, content_type):
            resolved_feeds = config._discover_feed_urls(final_url)
            if resolved_feeds:
                feed_urls = resolved_feeds[:1]
        for feed_url in feed_urls[:1]:
            resolved.append(
                {
                    "url": _normalize_url(feed_url),
                    "title": title or _default_name(feed_url),
                    "reason": reason or "Resolved from DeepSeek feed suggestion.",
                    "source_type": "rss",
                }
            )
        return resolved

    if "x.com" in final_url or "twitter.com" in final_url:
        resolved.append(
            {
                "url": final_url,
                "title": title or _default_name(final_url),
                "reason": reason or "Resolved from DeepSeek social suggestion.",
                "source_type": "social",
            }
        )
        return resolved

    resolved_feeds = config._discover_feed_urls(final_url)
    if resolved_feeds:
        for feed_url in resolved_feeds[:1]:
            resolved.append(
                {
                    "url": _normalize_url(feed_url),
                    "title": title or _default_name(feed_url),
                    "reason": reason or "Resolved from DeepSeek page suggestion.",
                    "source_type": "rss",
                }
            )
        return resolved

    resolved.append(
        {
            "url": final_url,
            "title": title or _default_name(final_url),
            "reason": reason or "Resolved from DeepSeek page suggestion.",
            "source_type": "web",
        }
    )
    return resolved


def discover_event_links(event):
    """Ask DeepSeek for event sources, validate them, and create reusable feeds."""
    if not isinstance(event, dict):
        return {"suggested_sources": [], "feed_ids": [], "feeds": [], "resolved_urls": []}

    suggestions = _deepseek_source_suggestions(event)
    resolved_sources = []
    seen_urls = set()
    for item in suggestions:
        for resolved in _resolve_source(item):
            url = resolved.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            resolved_sources.append(resolved)

    feed_ids = []
    feeds = []
    for item in resolved_sources:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        payload = {
            "url": url,
            "name": (item.get("title") or "").strip() or urlparse(url).netloc or url,
            "source_type": item.get("source_type") or config._infer_source_type(url),
            "category": "discovered",
            "enabled": True,
        }
        feed = create_feed(payload)
        if feed and feed.get("id"):
            feed_ids.append(int(feed["id"]))
            feeds.append(feed)

    merged_ids = []
    seen = set()
    for value in list(event.get("feed_ids") or []) + feed_ids:
        try:
            feed_id = int(value)
        except Exception:
            continue
        if feed_id in seen:
            continue
        seen.add(feed_id)
        merged_ids.append(feed_id)

    event_id = event.get("id")
    if event_id is not None and merged_ids:
        set_event_feeds(event_id, merged_ids)

    return {
        "suggested_sources": suggestions,
        "resolved_urls": [item.get("url") for item in resolved_sources if item.get("url")],
        "feed_ids": merged_ids,
        "feeds": feeds,
    }
