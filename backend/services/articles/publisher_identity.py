"""Offline publisher-domain identity using the bundled public suffix snapshot."""
from urllib.parse import urlsplit

import tldextract

_extract = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


def publisher_domain(value) -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith("document://"):
        return None
    try:
        parsed = urlsplit(text if "://" in text else f"//{text}")
        host = (parsed.hostname or "").lower().rstrip(".").encode("idna").decode("ascii")
        if "." not in host or any(c.isspace() for c in host):
            return None
        result = _extract(host)
        # Reserved .example domains are useful in local fixtures.
        return result.top_domain_under_public_suffix or host.removeprefix("www.")
    except (ValueError, UnicodeError):
        return None
