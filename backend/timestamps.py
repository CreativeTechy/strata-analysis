"""Publish-date normalization.

`articles.published` is whatever string the feed or the page gave us. Sorting,
trending and any "since when" question need a real `timestamptz`, so this module
is the one place that turns those strings into `(datetime, precision)`.

Two rules that matter more than the parsing itself:

1. **Never guess.** An unparseable or implausible date returns precision
   `unknown` with no datetime. Callers must exclude those rows from trend math
   rather than substituting `created_at` — "when we scraped it" is not "when it
   was said", and silently conflating the two makes every time series wrong in a
   way nobody can see.
2. **Naive datetimes are treated as UTC**, and that assumption is recorded by
   returning precision `exact`/`day` all the same. Feeds are inconsistent about
   offsets; pretending we know the local zone would be a second guess.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Anything older than this is almost always a parse artefact (a "1970" epoch
# default, a template placeholder, a page-footer copyright year).
MIN_PLAUSIBLE = datetime(1995, 1, 1, tzinfo=timezone.utc)
# Feeds routinely run a few hours ahead through timezone sloppiness; a week of
# slack absorbs that without accepting obvious garbage.
MAX_FUTURE_SKEW = timedelta(days=7)

PRECISION_EXACT = "exact"
PRECISION_DAY = "day"
PRECISION_UNKNOWN = "unknown"

# Tried in order, after ISO and RFC 2822 both fail.
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%d %B %Y %H:%M",
    "%B %d, %Y %H:%M",
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%Y%m%d",
)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _plausible(value: datetime, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return MIN_PLAUSIBLE <= value <= (now + MAX_FUTURE_SKEW)


def _try_iso(text: str) -> datetime | None:
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _try_rfc2822(text: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, datetime) else None


def _try_formats(text: str, formats: tuple[str, ...]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_published(value, *, now: datetime | None = None) -> tuple[datetime | None, str]:
    """Return `(utc_datetime | None, precision)` for a raw publish-date value.

    precision is `exact` when the source carried a time, `day` when it carried
    only a calendar date, and `unknown` when nothing usable could be recovered.
    """
    if value is None:
        return None, PRECISION_UNKNOWN

    if isinstance(value, datetime):
        parsed = _as_utc(value)
        return (parsed, PRECISION_EXACT) if _plausible(parsed, now=now) else (None, PRECISION_UNKNOWN)

    if isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return (parsed, PRECISION_DAY) if _plausible(parsed, now=now) else (None, PRECISION_UNKNOWN)

    text = str(value).strip()
    if not text:
        return None, PRECISION_UNKNOWN

    for parser in (_try_iso, _try_rfc2822):
        parsed = parser(text)
        if parsed is not None:
            parsed = _as_utc(parsed)
            if not _plausible(parsed, now=now):
                return None, PRECISION_UNKNOWN
            # A bare "2026-07-15" (or "20260715") round-trips through
            # fromisoformat as midnight; that is a date, not a timestamp, and
            # calling it `exact` would claim precision the source never gave.
            # The presence of a time separator is the tell — "2026-07-15T00:00:00Z"
            # really does assert midnight, so it stays exact.
            stated_a_time = ":" in text
            precision = (
                PRECISION_EXACT
                if stated_a_time or parsed.time() != datetime.min.time()
                else PRECISION_DAY
            )
            return parsed, precision

    parsed = _try_formats(text, _DATETIME_FORMATS)
    if parsed is not None:
        parsed = _as_utc(parsed)
        return (parsed, PRECISION_EXACT) if _plausible(parsed, now=now) else (None, PRECISION_UNKNOWN)

    parsed = _try_formats(text, _DATE_FORMATS)
    if parsed is not None:
        parsed = _as_utc(parsed)
        return (parsed, PRECISION_DAY) if _plausible(parsed, now=now) else (None, PRECISION_UNKNOWN)

    # Last resort: a leading ISO date inside a longer string, e.g. a URL slug or
    # "2026-07-15 — updated later". Anything less structured is left unknown.
    head = text[:10]
    if len(head) == 10 and head[4] == "-" and head[7] == "-":
        parsed = _try_formats(head, ("%Y-%m-%d",))
        if parsed is not None:
            parsed = _as_utc(parsed)
            if _plausible(parsed, now=now):
                return parsed, PRECISION_DAY

    return None, PRECISION_UNKNOWN


def is_trendable(precision: str | None) -> bool:
    """True when a row's date is good enough to place on a time axis."""
    return str(precision or "") in (PRECISION_EXACT, PRECISION_DAY)
