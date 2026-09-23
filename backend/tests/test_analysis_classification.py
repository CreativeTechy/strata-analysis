import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from analysis import classification
from analysis import labels


class ClassificationStageTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.CLASSIFICATION_MODEL
        self._original_threshold = config.CLASSIFICATION_CONFIDENCE_THRESHOLD
        config.CLASSIFICATION_MODEL = "fake/model"
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.4
        classification._load_pipeline.cache_clear()

    def tearDown(self):
        config.CLASSIFICATION_MODEL = self._original_model
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = self._original_threshold
        classification._load_pipeline.cache_clear()

    def test_category_confident_result_maps_back_to_snake_case_key(self):
        fake_pipeline = lambda text, candidates, hypothesis_template, multi_label, **kwargs: {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"], labels.CATEGORY_HYPOTHESIS_LABELS["news"]],
            "scores": [0.8, 0.1],
        }
        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            result = classification.classify_category("This car review covers handling and comfort.")
        self.assertEqual(result["label"], "review")
        self.assertFalse(result["low_confidence"])

    def test_category_low_confidence_falls_back_to_general_article(self):
        fake_pipeline = lambda text, candidates, hypothesis_template, multi_label, **kwargs: {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"]],
            "scores": [0.1],
        }
        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            result = classification.classify_category("ambiguous text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])
        self.assertEqual(result["raw_label"], "review")

    def test_pipeline_unavailable_falls_back_to_defaults(self):
        with patch("analysis.classification._get_pipeline", return_value=None):
            category = classification.classify_category("text")
            writer_tone = classification.classify_writer_tone("text")
            article_tone = classification.classify_article_tone("text")
        self.assertEqual(category["label"], "general_article")
        self.assertEqual(writer_tone["label"], "neutral")
        self.assertEqual(article_tone["label"], "neutral")
        self.assertTrue(category["low_confidence"] and writer_tone["low_confidence"] and article_tone["low_confidence"])

    def test_writer_tone_and_article_tone_are_independent_calls(self):
        calls = []

        def fake_pipeline(text, candidates, hypothesis_template, multi_label, **kwargs):
            calls.append(hypothesis_template)
            if "writer" in hypothesis_template:
                return {"labels": ["enthusiastic"], "scores": [0.9]}
            return {"labels": ["critical"], "scores": [0.9]}

        with patch("analysis.classification._get_pipeline", return_value=fake_pipeline):
            writer_tone = classification.classify_writer_tone("text")
            article_tone = classification.classify_article_tone("text")
        self.assertEqual(writer_tone["label"], "enthusiastic")
        self.assertEqual(article_tone["label"], "critical")
        self.assertEqual(len(calls), 2)

    def test_inference_error_is_handled_gracefully(self):
        def boom(text, candidates, hypothesis_template, multi_label, **kwargs):
            raise RuntimeError("boom")

        with patch("analysis.classification._get_pipeline", return_value=boom):
            result = classification.classify_category("text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])


class ClassificationStageHfApiTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.CLASSIFICATION_MODEL
        self._original_threshold = config.CLASSIFICATION_CONFIDENCE_THRESHOLD
        self._original_provider = config.CLASSIFICATION_PROVIDER
        config.CLASSIFICATION_MODEL = "fake/model"
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.4
        config.CLASSIFICATION_PROVIDER = "hf_api"

    def tearDown(self):
        config.CLASSIFICATION_MODEL = self._original_model
        config.CLASSIFICATION_CONFIDENCE_THRESHOLD = self._original_threshold
        config.CLASSIFICATION_PROVIDER = self._original_provider

    def test_confident_result_maps_back_to_snake_case_key(self):
        fake_result = {
            "labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"], labels.CATEGORY_HYPOTHESIS_LABELS["news"]],
            "scores": [0.8, 0.1],
        }
        with patch("hf_inference_client.classify_zero_shot", return_value=fake_result):
            result = classification.classify_category("This car review covers handling and comfort.")
        self.assertEqual(result["label"], "review")
        self.assertFalse(result["low_confidence"])

    def test_low_confidence_falls_back_to_default(self):
        fake_result = {"labels": [labels.CATEGORY_HYPOTHESIS_LABELS["review"]], "scores": [0.1]}
        with patch("hf_inference_client.classify_zero_shot", return_value=fake_result):
            result = classification.classify_category("ambiguous text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])

    def test_api_error_propagates_instead_of_falling_back(self):
        """An HF Inference API failure (bad token, quota, rate limit,
        outage...) means every remaining chunk/article would fail the same
        way - it must propagate instead of quietly downgrading to
        general_article/low_confidence, so the pipeline can treat it as
        fatal and stop (see services/articles/analysis_defaults.py's
        FATAL_ANALYSIS_ERRORS)."""
        from hf_inference_client import HFInferenceError

        with patch("hf_inference_client.classify_zero_shot", side_effect=HFInferenceError("boom")):
            with self.assertRaises(HFInferenceError):
                classification.classify_category("text")

    def test_no_model_configured_falls_back_to_defaults(self):
        config.CLASSIFICATION_MODEL = ""
        result = classification.classify_category("text")
        self.assertEqual(result["label"], "general_article")
        self.assertTrue(result["low_confidence"])

    def test_400_error_retries_by_splitting_the_whole_chunk_into_byte_safe_pieces(self):
        """A 400 on the first call must not fall back to classifying only a
        short prefix and throwing the rest of the chunk away - every
        byte-safe piece of the original chunk should get classified, and the
        aggregated label/score should come from all of them."""
        from hf_inference_client import HFInferenceError

        # > _HF_API_RETRY_MAX_BYTES so the whole-chunk call 400s, and <=
        # _HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES so the fallback's
        # first split is a single piece identical to the chunk - which must
        # be recognized as already-failed and skipped straight to
        # floor-sized pieces, not retried unchanged.
        long_chunk = "x" * 900
        calls = []

        def fake_classify_zero_shot(model_name, text, candidate_labels, hypothesis_template):
            calls.append(text)
            if len(calls) == 1:
                raise HFInferenceError("too long", status=400)
            return {"labels": ["news"], "scores": [0.9]}

        with patch("hf_inference_client.classify_zero_shot", side_effect=fake_classify_zero_shot):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        self.assertEqual(result, {"label": "news", "score": 0.9})
        # 1 failed whole-chunk call + 1 call per floor-sized piece - and no
        # wasted retry of the identical whole-chunk text.
        self.assertGreater(len(calls), 2)
        self.assertNotIn(calls[0], calls[1:])
        for retried_call in calls[1:]:
            self.assertLessEqual(len(retried_call.encode("utf-8")), classification._HF_API_RETRY_MAX_BYTES)
        # No content from the original chunk should have been dropped.
        self.assertEqual("".join(calls[1:]), long_chunk)

    def test_400_error_retry_tries_optimistic_pieces_before_falling_back_to_the_floor(self):
        """A chunk bigger than the optimistic piece size should be tried at
        that size first - a piece that fits there shouldn't be needlessly
        subdivided down to the smaller, more expensive-in-call-count floor
        size."""
        from hf_inference_client import HFInferenceError

        optimistic = classification._HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES
        long_chunk = "x" * (2 * optimistic + 100)  # 3 pieces at the optimistic size
        calls = []

        def fake_classify_zero_shot(model_name, text, candidate_labels, hypothesis_template):
            calls.append(text)
            if len(calls) == 1:
                raise HFInferenceError("too long", status=400)
            return {"labels": ["news"], "scores": [0.9]}

        with patch("hf_inference_client.classify_zero_shot", side_effect=fake_classify_zero_shot):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        self.assertEqual(result, {"label": "news", "score": 0.9})
        # 1 failed whole-chunk call + exactly 3 optimistic-sized pieces - no
        # floor-level subdivision needed since every piece succeeded at the
        # optimistic size on the first attempt.
        self.assertEqual(len(calls), 4)
        for retried_call in calls[1:]:
            self.assertLessEqual(len(retried_call.encode("utf-8")), optimistic)
        self.assertEqual("".join(calls[1:]), long_chunk)

    def test_400_error_retry_falls_back_to_the_floor_only_for_pieces_that_still_400(self):
        """A piece that still 400s at the optimistic size should be
        subdivided down to the guaranteed-safe floor - not dropped, and not
        applied to every piece indiscriminately."""
        from hf_inference_client import HFInferenceError

        optimistic = classification._HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES
        floor = classification._HF_API_RETRY_MAX_BYTES
        long_chunk = "x" * (2 * optimistic + 100)
        calls = []

        def fake_classify_zero_shot(model_name, text, candidate_labels, hypothesis_template):
            calls.append(text)
            # Anything bigger than the floor 400s; only floor-sized-or-smaller
            # pieces succeed - forcing every optimistic-sized piece through
            # one extra level of subdivision.
            if len(text.encode("utf-8")) > floor:
                raise HFInferenceError("too long", status=400)
            return {"labels": ["news"], "scores": [0.9]}

        with patch("hf_inference_client.classify_zero_shot", side_effect=fake_classify_zero_shot):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        self.assertEqual(result["label"], "news")
        self.assertAlmostEqual(result["score"], 0.9)
        successes = [c for c in calls if len(c.encode("utf-8")) <= floor]
        failures = [c for c in calls if len(c.encode("utf-8")) > floor]
        # whole chunk + the 2 oversized (1500-byte) optimistic pieces must
        # have failed (the 3rd optimistic piece is only 100 bytes, already
        # within the floor, and succeeds without needing to be split).
        self.assertEqual(len(failures), 3)
        # every byte of the chunk should be covered by the successful,
        # floor-sized leaf calls - nothing dropped just because it needed a
        # second round of splitting.
        self.assertEqual("".join(successes), long_chunk)

    def test_400_error_retry_averages_scores_across_pieces(self):
        from hf_inference_client import HFInferenceError

        optimistic = classification._HF_API_OVERSIZED_CHUNK_OPTIMISTIC_PIECE_BYTES
        long_chunk = "x" * (2 * optimistic + 100)  # 3 pieces at the optimistic size
        piece_results = iter(
            [
                {"labels": ["news"], "scores": [0.6]},
                {"labels": ["news"], "scores": [0.8]},
                {"labels": ["review"], "scores": [0.9]},
            ]
        )
        call_count = {"n": 0}

        def side_effect(model_name, text, candidate_labels, hypothesis_template):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise HFInferenceError("too long", status=400)
            return next(piece_results, {"labels": ["news"], "scores": [0.6]})

        with patch("hf_inference_client.classify_zero_shot", side_effect=side_effect):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        # "news" got two votes (0.6, 0.8 -> avg 0.7) and beats "review"'s
        # single 0.9 vote by total score (1.4 > 0.9).
        self.assertEqual(result, {"label": "news", "score": 0.7})

    def test_400_error_on_split_piece_is_skipped_not_fatal(self):
        """A piece that still 400s even at the guaranteed-safe floor size
        (not a length problem any more at that point) is logged and dropped
        - the other pieces' votes still produce a result."""
        from hf_inference_client import HFInferenceError

        floor = classification._HF_API_RETRY_MAX_BYTES
        long_chunk = "x" * (floor + 100)  # 1 whole-chunk fail + 2 floor pieces
        call_count = {"n": 0}

        def side_effect(model_name, text, candidate_labels, hypothesis_template):
            call_count["n"] += 1
            if call_count["n"] in (1, 2):
                raise HFInferenceError("too long", status=400)
            return {"labels": ["news"], "scores": [0.9]}

        with patch("hf_inference_client.classify_zero_shot", side_effect=side_effect):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        self.assertEqual(result, {"label": "news", "score": 0.9})

    def test_400_error_when_every_split_piece_fails_propagates_original_error(self):
        from hf_inference_client import HFInferenceError

        long_chunk = "x" * 900

        with patch("hf_inference_client.classify_zero_shot", side_effect=HFInferenceError("too long", status=400)):
            with self.assertRaises(HFInferenceError):
                classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

    def test_non_400_error_from_a_split_piece_propagates_instead_of_being_dropped(self):
        """A split piece that fails with a fatal, non-400 error (bad token,
        quota, rate limit, outage) must still propagate out of the retry -
        exactly like it would from the un-split call - so the pipeline can
        still treat it as fatal (see
        services/articles/analysis_defaults.py's FATAL_ANALYSIS_ERRORS).
        Swallowing it here would silently downgrade a provider-wide failure
        into "this one chunk produced a degraded result"."""
        from hf_inference_client import HFAuthError, HFInferenceError

        long_chunk = "x" * 900
        call_count = {"n": 0}

        def side_effect(model_name, text, candidate_labels, hypothesis_template):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise HFInferenceError("too long", status=400)
            raise HFAuthError("bad token", status=401)

        with patch("hf_inference_client.classify_zero_shot", side_effect=side_effect):
            with self.assertRaises(HFAuthError):
                classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")
        # Should have started splitting (not just retried once) before
        # hitting the fatal error.
        self.assertGreater(call_count["n"], 1)

    def test_400_error_retry_stays_within_byte_budget_for_multibyte_chunk(self):
        """End-to-end regression for the multi-byte case the whole retry
        exists for: a CJK chunk that keeps 400ing past the optimistic piece
        size must converge on floor-sized pieces that are still whole
        characters (no continuation byte cut in half), and cover the chunk
        with no content dropped."""
        from hf_inference_client import HFInferenceError

        floor = classification._HF_API_RETRY_MAX_BYTES
        long_chunk = "中文测试内容" * 200  # 1200 CJK chars = 3600 bytes
        calls = []

        def fake_classify_zero_shot(model_name, text, candidate_labels, hypothesis_template):
            calls.append(text)
            # Simulate a real hosted model's token limit: anything bigger
            # than the guaranteed-safe floor keeps 400ing.
            if len(text.encode("utf-8")) > floor:
                raise HFInferenceError("too long", status=400)
            return {"labels": ["news"], "scores": [0.9]}

        with patch("hf_inference_client.classify_zero_shot", side_effect=fake_classify_zero_shot):
            result = classification._classify_one_via_hf_api(long_chunk, ["news", "review"], "This is {}.")

        self.assertEqual(result["label"], "news")
        self.assertAlmostEqual(result["score"], 0.9)
        successes = [c for c in calls if len(c.encode("utf-8")) <= floor]
        self.assertTrue(successes)
        for piece in successes:
            self.assertLessEqual(len(piece.encode("utf-8")), floor)
            # No partial multi-byte character leaked through as a decoding
            # artifact - every character in the piece is a real CJK char.
            self.assertTrue(set(piece) <= {"中", "文", "测", "试", "内", "容"})
        # Every byte of the original chunk is covered by the successful
        # (ultimately floor-sized) pieces - nothing dropped.
        self.assertEqual("".join(successes), long_chunk)

    def test_400_error_on_already_short_chunk_propagates(self):
        from hf_inference_client import HFInferenceError

        with patch("hf_inference_client.classify_zero_shot", side_effect=HFInferenceError("too long", status=400)):
            with self.assertRaises(HFInferenceError):
                classification._classify_one_via_hf_api("short", ["news", "review"], "This is {}.")

    def test_non_400_error_does_not_retry(self):
        from hf_inference_client import HFInferenceError

        calls = []

        def fake_classify_zero_shot(model_name, text, candidate_labels, hypothesis_template):
            calls.append(text)
            raise HFInferenceError("rate limited", status=429)

        with patch("hf_inference_client.classify_zero_shot", side_effect=fake_classify_zero_shot):
            with self.assertRaises(HFInferenceError):
                classification._classify_one_via_hf_api("x" * 500, ["news", "review"], "This is {}.")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
