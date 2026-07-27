"""Syndication collapse via MinHash + LSH.

The problem: one wire story republished on 30 sites is 30 rows keyed by distinct
URLs. Counting "independent sources" by URL therefore inflates every prevalence
number by however aggressively a story was syndicated — and the first time a
client clicks through "14 sources" and reads the same AP copy 14 times, the
credibility of every number in the product is gone.

The fix: group near-identical bodies into a `story_group` and count *groups*.

Why MinHash and not SimHash
---------------------------
The obvious choice is a 64-bit SimHash with a Hamming threshold of 3, which is
what the canonical near-duplicate-web-page work uses. That threshold is
calibrated for long documents, where a few edited sentences are a negligible
fraction of the feature set. Our corpus is articles, and their length varies by
more than an order of magnitude, so a fixed *bit* threshold is not scale
invariant: measured on a real wire story and its reprint (a substituted verb
plus an added attribution line), the SimHash distance was 13 bits — four times
over threshold — purely because the document was short.

Jaccard similarity over shingle sets is scale invariant and the threshold is a
number a human can reason about: "these two bodies share 72% of their 4-word
sequences." MinHash estimates it in fixed space, and LSH banding turns candidate
lookup into a single indexed array-overlap query.

Determinism: shingles are hashed with blake2b and permuted by fixed integer
coefficients, never Python's `hash()`, which is salted per process and would
regroup the whole corpus on every restart.
"""

from __future__ import annotations

import hashlib
import re

SIGNATURE_SIZE = 128          # MinHash permutations
BAND_COUNT = 16               # LSH bands ...
BAND_ROWS = SIGNATURE_SIZE // BAND_COUNT   # ... of 8 rows each
SHINGLE_SIZE = 4              # word n-gram width

# Two bodies at or above this estimated Jaccard are the same story. Chosen from
# measured values (see test_signal_layer.py): a wire story and its reprint land
# around 0.8, while same-topic-different-story pairs sit near 0.0, so 0.70 has
# wide margin on both sides.
SIMILARITY_THRESHOLD = 0.70

# Below this many tokens a shingle profile is not meaningful; such rows stay
# ungrouped rather than collapsing onto each other.
MIN_TOKENS = 40

_TOKEN_RE = re.compile(r"[a-z0-9']+")

# Mersenne prime 2^61-1: permutations are (a*h + b) mod _PRIME.
_PRIME = (1 << 61) - 1
_MAX_INT32 = 0x7FFFFFFF        # keep signature values inside Postgres `integer`
_MAX_INT63 = (1 << 62) - 1     # keep band keys inside Postgres `bigint`


def _hash64(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _coefficients() -> list[tuple[int, int]]:
    """Fixed permutation coefficients, derived deterministically from a constant."""
    pairs = []
    for index in range(SIGNATURE_SIZE):
        a = _hash64(f"strata-minhash-a-{index}") % _PRIME
        b = _hash64(f"strata-minhash-b-{index}") % _PRIME
        pairs.append((a or 1, b))  # a must be non-zero to be a permutation
    return pairs


_COEFFS = _coefficients()


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(str(text or "").casefold())


def shingles(tokens: list[str], size: int = SHINGLE_SIZE) -> set[str]:
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def signature(text: str) -> list[int] | None:
    """Return a MinHash signature, or None when the text is too short to profile."""
    tokens = tokenize(text)
    if len(tokens) < MIN_TOKENS:
        return None

    hashed = [_hash64(shingle) % _PRIME for shingle in shingles(tokens)]
    if not hashed:
        return None

    # One pass per permutation over pre-hashed shingles: K*N cheap integer ops
    # rather than K*N cryptographic hashes.
    return [
        min(((a * value + b) % _PRIME) for value in hashed) & _MAX_INT32
        for a, b in _COEFFS
    ]


def estimated_jaccard(left: list[int], right: list[int]) -> float:
    """Fraction of agreeing signature positions — an unbiased Jaccard estimate."""
    if not left or not right or len(left) != len(right):
        return 0.0
    agree = sum(1 for a, b in zip(left, right) if a == b)
    return agree / len(left)


def band_keys(sig: list[int]) -> list[int]:
    """LSH band keys. Two signatures sharing any key are candidate duplicates."""
    keys = []
    for band in range(BAND_COUNT):
        chunk = sig[band * BAND_ROWS : (band + 1) * BAND_ROWS]
        payload = f"{band}:" + ",".join(str(value) for value in chunk)
        keys.append(_hash64(payload) & _MAX_INT63)
    return keys


def is_duplicate(left: list[int], right: list[int], threshold: float = SIMILARITY_THRESHOLD) -> bool:
    return estimated_jaccard(left, right) >= threshold


def fingerprint(title: str | None, text: str | None) -> list[int] | None:
    """Signature for an article. Title is included once; the body dominates."""
    body = str(text or "").strip()
    heading = str(title or "").strip()
    if not body and not heading:
        return None
    return signature(f"{heading}\n\n{body}" if heading else body)


# --------------------------------------------------------------------------- #
# Database side
# --------------------------------------------------------------------------- #
def find_matching_story(
    cur,
    project_id: int | None,
    sig: list[int],
    threshold: float = SIMILARITY_THRESHOLD,
) -> int | None:
    """Return the best-matching existing story group, or None.

    Candidates come from an indexed band overlap, so this stays a small lookup no
    matter how many stories a project accumulates. Among candidates the highest
    similarity wins, with `id` as a deterministic tie-break.
    """
    cur.execute(
        """
        select id, signature
        from public.story_groups
        where (project_id is not distinct from %s)
          and band_keys && %s
        order by id
        """,
        (project_id, band_keys(sig)),
    )

    best_id = None
    best_score = threshold
    for row in cur.fetchall():
        candidate = [int(value) for value in (row["signature"] or [])]
        score = estimated_jaccard(sig, candidate)
        if score >= best_score and (best_id is None or score > best_score):
            best_id, best_score = int(row["id"]), score
    return best_id


def assign_story(cur, article: dict, project_id: int | None = None) -> tuple[int | None, bool]:
    """Attach an article to a story group, creating one if it is the first sighting.

    Returns `(story_id, created)`. Every article gets a group: one too short to
    fingerprint becomes a *singleton* (null signature), because it is still an
    independent story — we just cannot prove it duplicates anything. Leaving such
    rows unassigned would also make any resumable backfill re-select them forever.
    """
    sig = fingerprint(article.get("title"), article.get("text"))
    if sig is None:
        return _create_group(cur, article, project_id, None), True

    existing = find_matching_story(cur, project_id, sig)
    if existing is not None:
        cur.execute(
            """
            update public.story_groups
               set member_count = member_count + 1,
                   last_seen_at = greatest(last_seen_at, coalesce(%s, now()))
             where id = %s
            """,
            (article.get("published_at"), existing),
        )
        return existing, False

    return _create_group(cur, article, project_id, sig), True


def _create_group(cur, article: dict, project_id: int | None, sig: list[int] | None) -> int | None:
    """Insert a new story group. `sig=None` creates a singleton that matches nothing."""
    cur.execute(
        """
        insert into public.story_groups
            (project_id, canonical_article_id, signature, band_keys,
             member_count, first_seen_at, last_seen_at)
        values (%s, %s, %s, %s, 1, coalesce(%s, now()), coalesce(%s, now()))
        returning id
        """,
        (
            project_id,
            article.get("id"),
            sig,
            band_keys(sig) if sig is not None else None,
            article.get("published_at"),
            article.get("published_at"),
        ),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None
