"""Shared label vocab for the analysis pipeline.

Single source of truth for the category/tone enums the zero-shot
classification stage classifies into and the rest of the pipeline validates
against - one definition rather than an enum copy-pasted per stage
and articles_query.py's VALID_TONES.
"""

VALID_CATEGORIES = (
    "review",
    "comparison",
    "complaint",
    "news",
    "ownership_experience",
    "buying_guide",
    "general_article",
)

# Human-readable hypothesis phrasing per category, fed to the zero-shot
# classifier as candidate labels (mDeBERTa-mnli scores label words directly,
# so plain nouns/phrases work better than snake_case tokens).
CATEGORY_HYPOTHESIS_LABELS = {
    "review": "a product or service review",
    "comparison": "a comparison between products or options",
    "complaint": "a complaint",
    "news": "a news report",
    "ownership_experience": "a personal ownership experience",
    "buying_guide": "a buying guide",
    "general_article": "a general article",
}

VALID_TONES = (
    "neutral",
    "positive",
    "enthusiastic",
    "optimistic",
    "critical",
    "skeptical",
    "negative",
    "concerned",
    "angry",
    "sarcastic",
    "humorous",
    "formal",
    "informal",
)

DEFAULT_CATEGORY = "general_article"
DEFAULT_TONE = "neutral"

# Demographics of the people quoted/mentioned in an article (see
# analysis/structured_extraction.py's people_opinions extraction and
# analysis/aggregation.py's compute_dominant_demographics rollup) - closed
# vocab for gender/age_range so dashboard breakdowns group cleanly; region
# stays free text (see normalize.normalize_region) since it's canonicalized
# against a country list but not restricted to one.
VALID_GENDERS = ("male", "female", "unknown")
DEFAULT_GENDER = "unknown"

# The extraction model is asked for exactly "male"/"female"/"unknown" (see
# structured_extraction_system_prompt.txt), but it doesn't always comply -
# raw synonyms/abbreviations/translations it sometimes emits instead, mapped
# onto the closed vocab above rather than falling through to "unknown" and
# losing a signal the model actually gave us. Keyed lowercase; matched after
# normalize.normalize_gender lowercases the raw value. Arabic/French entries
# cover this product's non-English sources (see CLAUDE.md on Arabic-project
# evidence generation) since the extraction prompt asks for English field
# *values* like "positive"/"neutral" but a local model doesn't always follow
# that for a bare word like this.
GENDER_ALIASES = {
    "m": "male", "man": "male", "men": "male", "male": "male",
    "he": "male", "him": "male", "his": "male", "boy": "male", "gentleman": "male",
    "mr": "male", "mr.": "male", "monsieur": "male", "homme": "male",
    "f": "female", "woman": "female", "women": "female", "female": "female",
    "she": "female", "her": "female", "hers": "female", "girl": "female", "lady": "female",
    "mrs": "female", "mrs.": "female", "ms": "female", "ms.": "female", "miss": "female",
    "madame": "female", "femme": "female",
    "ذكر": "male", "رجل": "male", "الرجل": "male",
    "أنثى": "female", "انثى": "female", "امرأة": "female", "المرأة": "female",
}

VALID_AGE_RANGES = ("under_18", "18-24", "25-34", "35-44", "45-54", "55-64", "65_plus", "unknown")
DEFAULT_AGE_RANGE = "unknown"

# Same problem as GENDER_ALIASES, and worse here: two of the eight buckets
# ("under_18", "65_plus") are the only ones with an underscore instead of a
# hyphen, so the natural way to write them ("65+", "under 18") never survives
# normalize.normalize_age_range's exact-match check even though the model
# gave a perfectly clear answer. Keyed after the same lower+space-stripped
# transform normalize_age_range applies, so e.g. "25 to 34" strips to
# "25to34" here. Deliberately excludes bare decade words ("30s", "thirties")
# - "30-39" straddles both 25-34 and 35-44 with no correct single bucket, so
# guessing one would be worse than "unknown".
AGE_RANGE_ALIASES = {
    "under18": "under_18", "under-18": "under_18", "below18": "under_18",
    "minor": "under_18", "minors": "under_18", "child": "under_18", "children": "under_18",
    "kid": "under_18", "kids": "under_18", "teen": "under_18", "teens": "under_18", "teenager": "under_18",
    "65+": "65_plus", "65plus": "65_plus", "over65": "65_plus", "above65": "65_plus",
    "senior": "65_plus", "seniors": "65_plus", "elderly": "65_plus", "seniorcitizen": "65_plus",
    "18to24": "18-24", "25to34": "25-34", "35to44": "35-44", "45to54": "45-54", "55to64": "55-64",
}

DEFAULT_REGION = "unknown"

# Open-vocab life-situation/occupation label (e.g. "unemployed", "small
# business owner") - no closed VALID_SEGMENTS list, same reasoning as region.
# Unlike region there's no fixed list to canonicalize against, so raw text
# is stored as-is here; embedding-similarity canonicalization into a shared
# vocabulary happens downstream at save time (see services/articles/store.py's
# _resolve_segment_label), not in this pure-normalization layer.
DEFAULT_SEGMENT = "unknown"
