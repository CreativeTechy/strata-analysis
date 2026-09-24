"""Zero-shot category + tone classification stage
(MoritzLaurer/mDeBERTa-v3-base-mnli-xnli by default).

Runs as a `transformers` zero-shot-classification pipeline, lazy-loaded and
reused across articles - or, when `config.CLASSIFICATION_PROVIDER` is
"hf_api" instead of the default "local", as calls to Hugging Face's hosted
Inference API (see hf_inference_client.py), trading the local torch/
transformers install for a network round trip per chunk. Category,
writer_tone, and article_tone are three independent zero-shot calls against
the same model/text, since each asks a different question of it
(writer_tone and article_tone are deliberately never conflated here - that
only happens later, deterministically, in aggregation.compute_overall_tone).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from functools import lru_cache

import config
from analysis import labels
from analysis.article_prep import chunk_text
from analysis.model_utils import resolve_device_index

logger = logging.getLogger(__name__)

_CATEGORY_TEMPLATE = "This text is {}."
_WRITER_TONE_TEMPLATE = "The writer's tone in this text is {}."
_ARTICLE_TONE_TEMPLATE = "The overall tone of the subject matter in this article is {}."


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str, device_setting: str):
    try:
        from transformers import pipeline
    except Exception:
        logger.warning("`transformers` isn't installed; classification will fall back to defaults.")
        return None
    try:
        return pipeline(
            "zero-shot-classification",
            model=model_name,
            device=resolve_device_index(device_setting),
        )
    except Exception:
        logger.exception(
            "Failed to load classification model '%s' on device '%s'", model_name, device_setting
        )
        return None


def _get_pipeline():
    model_name = (config.CLASSIFICATION_MODEL or "").strip()
    if not model_name:
        logger.warning("CLASSIFICATION_MODEL is empty; classification will fall back to defaults.")
        return None
    return _load_pipeline(model_name, config.CLASSIFICATION_DEVICE or "cpu")


def _classify_one_via_local_pipeline(chunk, candidate_labels, hypothesis_template):
    classifier = _get_pipeline()
    if classifier is None:
        return None
    try:
        # See sentiment_classifier.py's matching comment: chunks are sized in
        # characters (article_prep.chunk_text), which can still overflow the
        # model's max token length for scripts that tokenize more densely
        # than English (CJK, Thai, Arabic...) - truncation=True is the
        # backstop.
        result = classifier(
            chunk,
            candidate_labels,
            hypothesis_template=hypothesis_template,
            multi_label=False,
            tokenizer_kwargs={"truncation": True},
        )
    except Exception:
        logger.exception("Zero-shot classification inference failed")
        return None
    result_labels = result.get("labels") or []
    result_scores = result.get("scores") or []
    if not result_labels or not result_scores:
        return None
    return {"label": result_labels[0], "score": result_scores[0]}


# Smaller than sentiment_classifier's byte budget: here the model's token
# budget is shared with the hypothesis template + candidate label text, not
# just the premise, so leave more headroom (see
# hf_inference_client.split_into_byte_budget_pieces).
_HF_API_RETRY_MAX_BYTES = 400


def _classify_one_via_hf_api(chunk, candidate_labels, hypothesis_template):
    model_name = (config.CLASSIFICATION_MODEL or "").strip()
    if not model_name:
        logger.warning("CLASSIFICATION_MODEL is empty; classification will fall back to defaults.")
        return None
    try:
        from hf_inference_client import HFInferenceError, classify_zero_shot
    except Exception:
        logger.exception("hf_inference_client import failed")
        return None
    # HFInferenceError (bad token, insufficient quota, rate limit, outage...)
    # is deliberately NOT caught here - it means the provider call itself
    # never produced a usable answer. It propagates up through
    # analyze_article() to reanalyze.reanalyze_article(); only the
    # unrecoverable subset (bad/missing credentials, out of credit/quota -
    # see services/articles/analysis_defaults.py's FATAL_ANALYSIS_ERRORS)
    # stops the whole pipeline run there (services/pipeline/pipeline.py).
    # Anything else (rate limit, timeout, outage) just fails this one
    # chunk/article.
    #
    # The one exception: a 400 here usually means this chunk tokenized past
    # the model's max sequence length - character count isn't token count,
    # and unlike the local pipeline's `tokenizer_kwargs={"truncation":
    # True}` backstop above, the hosted API doesn't truncate for us. That's
    # a property of this one chunk's text, not the provider. Rather than
    # keep only a short prefix of the chunk (throwing most of it away), split
    # the whole chunk into byte-safe pieces and classify each before giving
    # up.
    try:
        result = classify_zero_shot(model_name, chunk, candidate_labels, hypothesis_template)
    except HFInferenceError as exc:
        if exc.status == 400 and len(chunk.encode("utf-8")) > _HF_API_RETRY_MAX_BYTES:
            result = _classify_oversized_chunk_via_hf_api(model_name, chunk, candidate_labels, hypothesis_template)
            if result is None:
                raise
        else:
            raise
    result_labels = result.get("labels") or []
    result_scores = result.get("scores") or []
    if not result_labels or not result_scores:
        return None
    return {"label": result_labels[0], "score": result_scores[0]}


# Optimistic starting piece size for the oversized-chunk fallback below -
# well above _HF_API_RETRY_MAX_BYTES, the worst-case-guaranteed floor, but
# realistic hosted-model tokenizers need nowhere near one token per byte for
# real article text (mDeBERTa's SentencePiece vocabulary covers CJK at
# roughly one token per 1-1.5 characters, for example), so most oversized
# chunks classify in a handful of calls at this size instead of the dozen-
# plus pieces the floor alone would force. A piece that still 400s here is
# re-split at the floor, which is guaranteed to fit - bounded to that one
# extra fallback level rather than open-ended recursion, so genuinely
# pathological content (content that really does need close to one token
# per byte) costs a fixed, small number of wasted calls instead of an
# unbounded amount.
_HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES = 1500


def _classify_oversized_chunk_via_hf_api(model_name, chunk, candidate_labels, hypothesis_template):
    """Fallback for a chunk whose hosted zero-shot call 400'd even though it
    was within chunk_text's character budget (dense scripts like CJK/Thai/
    Arabic can need close to one token per UTF-8 byte). Splits the whole
    chunk into pieces - optimistically sized first, falling back to the
    worst-case-safe floor only for a piece that still 400s - classifies each,
    and averages the score per label across the pieces that picked it, so
    the whole chunk still gets a say instead of only its first ~400 bytes."""
    from hf_inference_client import HFInferenceError, classify_zero_shot, split_into_byte_budget_pieces

    score_by_label = defaultdict(float)
    count_by_label = defaultdict(int)
    piece_count = 0
    dropped_count = 0

    def classify_piece(piece, *, is_floor_sized):
        nonlocal piece_count, dropped_count
        piece = piece.strip()
        if not piece:
            return
        piece_count += 1
        try:
            piece_result = classify_zero_shot(model_name, piece, candidate_labels, hypothesis_template)
        except HFInferenceError as piece_exc:
            # Anything other than a 400 (auth, quota, rate limit, outage) is
            # a provider-level failure and must propagate like it would from
            # the un-split call, not be silently dropped.
            if piece_exc.status != 400:
                raise
            if is_floor_sized:
                # Already at the worst-case-guaranteed-safe size and still
                # 400'd - not a length problem at this point, so retrying
                # smaller wouldn't help. Log and drop just this piece rather
                # than looping forever.
                logger.exception(
                    "Zero-shot classification 400'd for a %d-byte piece even at the safe floor; dropping it",
                    len(piece.encode("utf-8")),
                )
                dropped_count += 1
                return
            for sub_piece in split_into_byte_budget_pieces(piece, _HF_API_RETRY_MAX_BYTES):
                classify_piece(sub_piece, is_floor_sized=True)
            return
        piece_labels = piece_result.get("labels") or []
        piece_scores = piece_result.get("scores") or []
        if not piece_labels or not piece_scores:
            return
        score_by_label[piece_labels[0]] += piece_scores[0]
        count_by_label[piece_labels[0]] += 1

    initial_pieces = split_into_byte_budget_pieces(chunk, _HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES)
    if len(initial_pieces) == 1:
        # The whole chunk already fits within the optimistic size, so that
        # single "piece" is byte-for-byte identical to the chunk that just
        # 400'd in _classify_one_via_hf_api - retrying it unchanged would
        # just repeat the same failure. Go straight to floor-sized pieces.
        for sub_piece in split_into_byte_budget_pieces(chunk, _HF_API_RETRY_MAX_BYTES):
            classify_piece(sub_piece, is_floor_sized=True)
    else:
        for piece in initial_pieces:
            classify_piece(piece, is_floor_sized=False)

    if not score_by_label:
        return None

    best_label = max(score_by_label, key=lambda label: score_by_label[label])
    avg_score = score_by_label[best_label] / max(1, count_by_label[best_label])
    logger.warning(
        "Chunk of %d chars needed splitting into %d byte-safe piece(s) for hosted zero-shot "
        "classification (model=%s, dropped=%d); using their averaged vote instead of a "
        "truncated prefix",
        len(chunk),
        piece_count,
        model_name,
        dropped_count,
    )
    return {"labels": [best_label], "scores": [avg_score]}


def _classify_one(chunk, candidate_labels, hypothesis_template):
    provider = (config.CLASSIFICATION_PROVIDER or "local").strip().lower()
    logger.info("provider=%s model=%s", provider, config.CLASSIFICATION_MODEL)
    if provider == "hf_api":
        return _classify_one_via_hf_api(chunk, candidate_labels, hypothesis_template)
    return _classify_one_via_local_pipeline(chunk, candidate_labels, hypothesis_template)


def _classify_chunks(chunks, candidate_labels, hypothesis_template):
    score_by_label = defaultdict(float)
    count_by_label = defaultdict(int)
    for chunk in chunks:
        chunk = (chunk or "").strip()
        if not chunk:
            continue
        result = _classify_one(chunk, candidate_labels, hypothesis_template)
        if not result:
            continue
        score_by_label[result["label"]] += result["score"]
        count_by_label[result["label"]] += 1

    if not score_by_label:
        return None

    best_label = max(score_by_label, key=lambda label: score_by_label[label])
    avg_score = score_by_label[best_label] / max(1, count_by_label[best_label])
    return {"label": best_label, "score": avg_score}


def _classify(text: str, candidate_labels: list[str], hypothesis_template: str, default_label: str) -> dict:
    """Return {"label", "score", "low_confidence"[, "raw_label"]}.

    `label` is always a valid candidate (falls back to `default_label` when
    the model is unavailable or its top score is below
    config.CLASSIFICATION_CONFIDENCE_THRESHOLD) - callers never see None or
    an out-of-vocabulary label.
    """
    chunks = chunk_text(text) if text else []
    if not chunks and text:
        chunks = [text]
    result = _classify_chunks(chunks, candidate_labels, hypothesis_template)

    if result is None:
        return {"label": default_label, "score": 0.0, "low_confidence": True}
    if result["score"] < config.CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return {
            "label": default_label,
            "score": result["score"],
            "low_confidence": True,
            "raw_label": result["label"],
        }
    return {"label": result["label"], "score": result["score"], "low_confidence": False}


def classify_category(text: str) -> dict:
    hypothesis_labels = labels.CATEGORY_HYPOTHESIS_LABELS
    reverse = {phrase: key for key, phrase in hypothesis_labels.items()}
    default_phrase = hypothesis_labels[labels.DEFAULT_CATEGORY]

    result = _classify(text, list(hypothesis_labels.values()), _CATEGORY_TEMPLATE, default_phrase)
    result["label"] = reverse.get(result["label"], labels.DEFAULT_CATEGORY)
    if "raw_label" in result:
        result["raw_label"] = reverse.get(result["raw_label"], result["raw_label"])
    return result


def classify_writer_tone(text: str) -> dict:
    return _classify(text, list(labels.VALID_TONES), _WRITER_TONE_TEMPLATE, labels.DEFAULT_TONE)


def classify_article_tone(text: str) -> dict:
    return _classify(text, list(labels.VALID_TONES), _ARTICLE_TONE_TEMPLATE, labels.DEFAULT_TONE)
