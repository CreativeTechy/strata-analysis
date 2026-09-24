"""services/reports/pdf_renderer.py smoke tests. The deep PyMuPDF/Arabic/RTL/
pagination verification lives in that module's own docstring (done via real
rendered PDFs during development, not re-derived here) - these tests just
guard the contract: valid PDF bytes out, no crash on missing/empty sections,
and that document-derived content is escaped rather than interpreted."""

import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.reports.pdf_renderer import _executive_summary_html, render_summary_pdf

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
    "status": "unavailable", "reason": "No analysis history recorded before 2026-03-04.",
    "today_date": "2026-03-05", "yesterday_date": "2026-03-04", "timezone": "UTC",
    "today_scope_label": "Last 30 days", "yesterday_scope_label": "As of 2026-03-04",
    "metrics": {"today": None, "yesterday": None, "deltas": None, "coverage": None},
    "narrative": None, "evidence": [],
}


class RenderSummaryPdfTests(unittest.TestCase):
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
                "today": {"total": 10, "positive": 6, "negative": 2, "neutral": 2, "mixed": 0, "net_sentiment": 40},
                "yesterday": {"total": 8, "positive": 3, "negative": 3, "neutral": 2, "mixed": 0, "net_sentiment": 0},
                "deltas": {"total": 2, "positive": 3, "negative": -1, "neutral": 0, "mixed": 0, "net_sentiment": 40},
                "coverage": {"today_ids": 10, "yesterday_ids": 8, "common": 6, "added": 4, "removed": 2, "sampled": False},
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


if __name__ == "__main__":
    unittest.main()
