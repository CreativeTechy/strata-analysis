"""services/reports/pdf_renderer.py smoke tests. The deep PyMuPDF/Arabic/RTL/
pagination verification lives in that module's own docstring (done via real
rendered PDFs during development, not re-derived here) - these tests just
guard the contract: valid PDF bytes out, no crash on missing/empty sections,
and that document-derived content is escaped rather than interpreted."""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.reports.pdf_renderer import (
    _build_html,
    _comparison_html,
    _executive_summary_html,
    _idea_comparisons_html,
    _top_articles_html,
    _trust_tag_html,
    render_summary_pdf,
)

MINIMAL_REPORT_DATA = {
    "project": {"id": 1, "name": "Acme"},
    "scope": {"type": "period", "period": "30d", "run_id": None, "analysis_date_label": "Last 30 days", "timezone": "UTC"},
    "generated_at": "2026-03-05T12:00:00+00:00",
    "counts": {"total": 0, "analyzed": 0, "pending": 0, "processing": 0, "failed": 0, "partial": 0},
    "sentiment": {
        "positive": {"count": 0, "pct": 0.0}, "negative": {"count": 0, "pct": 0.0},
        "neutral": {"count": 0, "pct": 0.0}, "mixed": {"count": 0, "pct": 0.0},
        "net_sentiment": 0, "analyzed_total": 0,
    },
    "executive_summary": {"text": None, "cached": False},
    "top_articles": [],
    "top_articles_fallback_used": False,
}

MINIMAL_COMPARISON = {
    "status": "unavailable", "reason": "No previous analysis run exists.",
    "current_date": "2026-03-05", "previous_date": "2026-03-04", "timezone": "UTC",
    "current_scope_label": "Analysis #2", "previous_scope_label": "Analysis #1",
    "metrics": {"current": None, "previous": None, "deltas": None, "coverage": None},
    "narrative": None, "evidence": [],
}


class RenderSummaryPdfTests(unittest.TestCase):
    def test_comparison_heading_refers_to_the_last_run(self):
        html = _comparison_html(MINIMAL_COMPARISON)
        self.assertIn("Variation from Last Run", html)
        self.assertNotIn("Variation from Yesterday", html)

    def test_renders_valid_pdf_bytes_for_an_empty_report(self):
        pdf_bytes = render_summary_pdf(MINIMAL_REPORT_DATA, MINIMAL_COMPARISON)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_handles_a_populated_report_with_a_comparison_narrative(self):
        report_data = {
            **MINIMAL_REPORT_DATA,
            "counts": {"total": 12, "analyzed": 10, "pending": 1, "processing": 0, "failed": 1, "partial": 0},
            "sentiment": {
                "positive": {"count": 6, "pct": 60.0}, "negative": {"count": 2, "pct": 20.0},
                "neutral": {"count": 2, "pct": 20.0}, "mixed": {"count": 0, "pct": 0.0},
                "net_sentiment": 40, "analyzed_total": 10,
            },
            "executive_summary": {"text": "Overall sentiment trended positive this period.", "cached": True},
            "top_articles": [
                {"rank": 1, "article_id": 5, "title": "مقال باللغة العربية - Mixed title", "short_summary": "s",
                 "sentiment": "positive", "source": "doc.pdf", "reference": "/articles/5",
                 "relevance_score": 0.9, "ranking_method": "relevance_score"},
            ],
            "top_articles_fallback_used": False,
        }
        comparison = {
            **MINIMAL_COMPARISON,
            "status": "ok", "reason": None,
            "metrics": {
                "current": {"total": 10, "positive": 6, "negative": 2, "neutral": 2, "mixed": 0, "net_sentiment": 40},
                "previous": {"total": 8, "positive": 3, "negative": 3, "neutral": 2, "mixed": 0, "net_sentiment": 0},
                "deltas": {"total": 2, "positive": 3, "negative": -1, "neutral": 0, "mixed": 0, "net_sentiment": 40},
                "coverage": {"current_ids": 10, "previous_ids": 8, "common": 6, "added": 4, "removed": 2, "sampled": False},
            },
            "narrative": "Ideas & Themes:\nSentiment strengthened around delivery speed.",
            "evidence": [{"point": "Delivery speed praised more often.", "article_ids": [5]}],
        }
        pdf_bytes = render_summary_pdf(report_data, comparison)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_llm_failed_comparison_still_renders(self):
        comparison = {**MINIMAL_COMPARISON, "status": "llm_failed", "reason": "Something went wrong while generating the AI narrative."}
        pdf_bytes = render_summary_pdf(MINIMAL_REPORT_DATA, comparison)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_document_derived_content_is_escaped_not_interpreted(self):
        """A malicious/odd title must render as literal text, never be
        interpreted as HTML markup by the Story engine."""
        report_data = {
            **MINIMAL_REPORT_DATA,
            "top_articles": [
                {"rank": 1, "article_id": 1, "title": "<script>alert(1)</script>", "short_summary": "<b>bold</b> & stuff",
                 "sentiment": "negative", "source": "doc.pdf", "reference": "/articles/1",
                 "relevance_score": None, "ranking_method": "fallback_recency"},
            ],
            "top_articles_fallback_used": True,
        }
        pdf_bytes = render_summary_pdf(report_data, MINIMAL_COMPARISON)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            text = "".join(page.get_text() for page in doc)
        finally:
            doc.close()
        self.assertIn("alert(1)", text)
        self.assertIn("bold", text)

    def test_missing_optional_keys_do_not_crash(self):
        pdf_bytes = render_summary_pdf({}, {})
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_an_executive_summary_llm_failure_still_renders_a_pdf(self):
        """report_data.build_report_data() degrades an LLM failure to
        executive_summary={"text": None, "error": ...} rather than raising -
        the PDF must still build, disclosing the failure instead of just
        going blank."""
        report_data = {
            **MINIMAL_REPORT_DATA,
            "executive_summary": {"text": None, "cached": False, "error": "The assistant hit an unexpected error."},
        }
        pdf_bytes = render_summary_pdf(report_data, MINIMAL_COMPARISON)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))


class ExecutiveSummaryHtmlTests(unittest.TestCase):
    def test_renders_the_text_when_present_even_alongside_a_stale_error(self):
        html = _executive_summary_html({"executive_summary": {"text": "All good.", "error": "stale error"}})
        self.assertIn("All good.", html)
        self.assertNotIn("stale error", html)

    def test_renders_the_failure_reason_when_no_text_is_available(self):
        html = _executive_summary_html({"executive_summary": {"text": None, "error": "Couldn't reach the model."}})
        self.assertIn("unavailable", html)
        self.assertIn("Couldn&#x27;t reach the model.", html)

    def test_renders_the_generic_placeholder_when_neither_text_nor_error_is_set(self):
        html = _executive_summary_html({"executive_summary": {"text": None, "cached": False}})
        self.assertIn("No executive summary available.", html)


IDEA_COMPARISONS = {
    "project_wide": True, "error": None,
    "items": [{
        "idea": "Petrol price", "type": "claim", "diverges": True, "summary": "EIA and the memo differ.",
        "claims": [
            {"source": "eia.gov", "source_tier": {"tier": "trusted", "is_default": False}, "claim": "$98",
             "article_id": 1, "title": "EIA weekly", "reference": "/articles/1"},
            {"source": "memo.pdf", "source_tier": {"tier": "unknown", "is_default": True}, "claim": None,
             "article_id": 2, "title": "<i>Memo</i>", "reference": "/articles/2"},
        ],
    }],
}


class TrustTierTests(unittest.TestCase):
    def test_labels_match_the_sources_tab_and_flag_seeded_defaults(self):
        self.assertIn(">Trusted<", _trust_tag_html({"tier": "trusted", "is_default": False}))
        self.assertIn("Trusted (default)", _trust_tag_html({"tier": "trusted", "is_default": True}))
        self.assertIn("Untrusted (default)", _trust_tag_html({"tier": "untrusted", "is_default": True}))
        # "Not yet assessed" is already a statement about the default - no suffix.
        self.assertIn(">Not yet assessed<", _trust_tag_html({"tier": "unknown", "is_default": True}))
        self.assertIn("Not yet assessed", _trust_tag_html(None))
        self.assertIn("Not yet assessed", _trust_tag_html({"tier": "bogus"}))

    def test_top_article_source_carries_its_tier(self):
        html = _top_articles_html({"top_articles": [{
            "rank": 1, "article_id": 1, "title": "t", "short_summary": "s", "sentiment": "neutral",
            "source": "bbc.co.uk", "reference": "/articles/1", "relevance_score": 0.5,
            "source_tier": {"tier": "mixed", "is_default": False},
        }]})
        self.assertIn("bbc.co.uk", html)
        self.assertIn(">Mixed<", html)


class IdeaComparisonsHtmlTests(unittest.TestCase):
    def test_is_the_last_pdf_section(self):
        html = _build_html(MINIMAL_REPORT_DATA, MINIMAL_COMPARISON)
        idea_heading = html.index("<h2>Idea Comparisons</h2>")
        self.assertGreater(idea_heading, html.index("<h2>Variation from Last Run</h2>"))
        self.assertNotIn("<h2>", html[idea_heading + 1:])

    def test_renders_each_claim_with_source_and_tier(self):
        html = _idea_comparisons_html({"idea_comparisons": IDEA_COMPARISONS})
        self.assertIn("Petrol price", html)
        self.assertIn("Sources disagree", html)
        self.assertIn("$98", html)
        self.assertIn("eia.gov", html)
        self.assertIn(">Trusted<", html)
        self.assertIn("No specific figure stated", html)
        self.assertIn("&lt;i&gt;Memo&lt;/i&gt;", html)
        self.assertIn("whole project", html)

    def test_empty_and_error_states(self):
        self.assertIn("No idea was discussed", _idea_comparisons_html({}))
        html = _idea_comparisons_html({"idea_comparisons": {"items": [], "error": "Model down.", "project_wide": False}})
        self.assertIn("Idea comparisons unavailable - Model down.", html)
        self.assertNotIn("No idea was discussed", html)
        self.assertIn("this analysis run", html)

    def test_full_pdf_renders_the_section(self):
        pdf_bytes = render_summary_pdf({**MINIMAL_REPORT_DATA, "idea_comparisons": IDEA_COMPARISONS}, MINIMAL_COMPARISON)
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            text = "".join(page.get_text() for page in doc)
        finally:
            doc.close()
        self.assertIn("Idea Comparisons", text)
        self.assertIn("$98", text)
        self.assertIn("Trusted", text)


if __name__ == "__main__":
    unittest.main()
