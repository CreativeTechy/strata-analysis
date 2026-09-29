"""Renders the Reports page's Export Summary as a PDF, given the two dicts
built elsewhere: `report_data` (services/reports/report_data.py's
build_report_data) and `comparison` (yesterday_comparison.py's run-over-run
"variation from last run" result). This module owns layout only - it never
queries the database or calls the LLM.

Uses PyMuPDF's Story engine (MuPDF's built-in HTML+CSS layout engine, via
fitz.Story) rather than the low-level page.insert_text/insert_textbox calls,
because Story is the layer that actually does bidi reordering and Arabic
glyph shaping (joined letterforms) and reflows content across pages. The
low-level text-insertion calls do neither and were ruled out during
verification.

No custom font is embedded. MuPDF ships its own internal Arabic-capable
fallback font and Story's automatic font-fallback reaches it whenever the
CSS leaves font-family unset (or generic, e.g. "sans-serif") and no
@font-face overrides it - confirmed against this project's actual mixed
Arabic/English content (see module docstring below for the verification
notes). That fallback is compiled into the MuPDF/PyMuPDF library itself, not
supplied by the OS, so it is expected to render identically on the Linux
backend container as it did in local verification on Windows - nothing here
references a Windows system font (e.g. C:\\Windows\\Fonts\\tahoma.ttf), which
would have been a licensing problem to ship in the repo.

Known extraction nuance (not a rendering defect): re-extracting Arabic text
from the produced PDF via page.get_text() yields Arabic in *presentation-form*
Unicode (the shaped, contextual glyph forms MuPDF's HarfBuzz-based shaper
actually drew - U+FB50-FDFF / U+FE70-FEFF) rather than the original
*logical-form* Arabic (U+0600-U+06FF) that was fed in. This is a known
characteristic of extracting text that engine shaped for RTL rendering, not
mojibake: the characters are still correct, readable Arabic (copy/paste
renders correctly), just not byte-identical to the input string. Exact
substring search against the original Arabic string will not reliably match
extracted PDF text as a result; if that ever matters, it needs an explicit
Unicode NFKC-style normalization step downstream, not a rendering fix here.
"""

from __future__ import annotations

import html
import io
from datetime import datetime, timezone

import fitz

import config

PAGE_SIZE = "a4"
MARGIN_LEFT = 36
MARGIN_RIGHT = 36
MARGIN_TOP = 40
MARGIN_BOTTOM = 46  # leaves room for the page-number footer stamped after layout
MAX_PAGES = 500  # sanity guard against a pathological infinite-layout loop

SENTIMENT_COLORS = {
    "positive": "#2e7d32",
    "negative": "#c62828",
    "neutral": "#757575",
    "mixed": "#b8860b",
}

SENTIMENT_LABELS = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
    "mixed": "Mixed",
}

# Same labels as the Sources tab (dashboard/src/components/SourcesPage.jsx's
# TRUST_TIER_META), so a tier reads identically on the page it's set on.
TRUST_TIER_COLORS = {
    "trusted": "#2e7d32",
    "mixed": "#b8860b",
    "untrusted": "#c62828",
    "unknown": "#757575",
}

TRUST_TIER_LABELS = {
    "trusted": "Trusted",
    "mixed": "Mixed",
    "untrusted": "Untrusted",
    "unknown": "Not yet assessed",
}

BASE_CSS = """
* { font-family: sans-serif; }
body { font-size: 10.5px; line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 18px; margin: 0 0 4px 0; }
h2 { font-size: 13.5px; margin: 16px 0 6px 0; padding-bottom: 3px;
     border-bottom: 1px solid #cccccc; }
h3 { font-size: 11.5px; margin: 10px 0 4px 0; }
p { margin: 4px 0; }
.subtitle { color: #444444; font-size: 10px; margin: 2px 0; }
.muted { color: #666666; font-size: 9.5px; }
.note { color: #7a5b00; background-color: #fff6e0; border: 1px solid #f0dca0;
        padding: 5px 8px; font-size: 9.5px; margin: 6px 0; }
.unavailable { color: #7a1f1f; background-color: #fdecea;
               border: 1px solid #f3c6c2; padding: 6px 8px; font-size: 10px;
               margin: 6px 0; }

table { width: 100%; border-collapse: collapse; margin: 4px 0 10px 0; }
th, td { border: 1px solid #dddddd; padding: 4px 6px; text-align: left;
         font-size: 9.5px; vertical-align: top; }
th { background-color: #f2f2f2; font-weight: bold; }

table.stats td { text-align: center; }
table.stats .stat-value { font-size: 14px; font-weight: bold; display: block; }
table.stats .stat-label { font-size: 8.5px; color: #555555; }

table.bars td { border: none; padding: 3px 4px; }
.bar-label { width: 70px; font-size: 9.5px; }
.bar-pct { width: 110px; text-align: right; font-size: 9.5px; white-space: nowrap; }
.bar-cell { background-color: #eeeeee; }
.bar-fill { height: 10px; }

.article-block { margin: 6px 0 10px 0; padding-bottom: 8px;
                  border-bottom: 1px solid #eeeeee; }
.article-title { font-size: 11px; font-weight: bold; margin: 0 0 2px 0; }
.article-meta { font-size: 9px; color: #555555; margin: 0 0 3px 0; }
/* display:inline (not inline-block, which the Story HTML/CSS engine
   expands to a full-width block instead of a compact badge - verified
   during throwaway testing) keeps this a small inline badge. */
.sentiment-tag { display: inline; padding: 1px 5px; border-radius: 3px;
                  font-size: 8.5px; color: #ffffff; }

.evidence-item { font-size: 9.5px; margin: 3px 0; }

.trust-tag { display: inline; padding: 1px 5px; border-radius: 3px;
             font-size: 8px; color: #ffffff; }
.comparison-block { margin: 6px 0 10px 0; padding-bottom: 8px;
                    border-bottom: 1px solid #eeeeee; }
.comparison-idea { font-size: 11px; font-weight: bold; margin: 0 0 3px 0; }
.divergence-tag { display: inline; padding: 1px 5px; border-radius: 3px;
                  font-size: 8.5px; color: #ffffff; }

.consolidated-section { page-break-before: always; }
.toc-item { font-size: 10px; margin: 3px 0; }
"""


def _esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _esc_multiline(value) -> str:
    """Escape then convert blank-line-separated paragraphs to <p> blocks, and
    single newlines within a paragraph to <br>, for free-text LLM narrative."""
    text = str(value or "").strip()
    if not text:
        return ""
    paragraphs = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]
    blocks = []
    for para in paragraphs:
        escaped = _esc(para).replace("\n", "<br/>")
        blocks.append(f'<p dir="auto">{escaped}</p>')
    return "".join(blocks)


def _fmt_iso(value: str | None) -> str:
    if not value:
        return "Unknown"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except (ValueError, TypeError):
        return _esc(text)


def _fmt_num(value, default="0") -> str:
    if value is None:
        return default
    return _esc(value)


def _esc_or(value, default="Unknown") -> str:
    if value is None or value == "":
        return default
    return _esc(value)


def _sentiment_tag_html(sentiment: str) -> str:
    key = str(sentiment or "neutral").lower()
    color = SENTIMENT_COLORS.get(key, "#757575")
    label = SENTIMENT_LABELS.get(key, key.title() or "Neutral")
    return f'<span class="sentiment-tag" style="background-color:{color};">{_esc(label)}</span>'


def _trust_tag_html(source_tier: dict | None) -> str:
    """Tier badge for a source. A tier that is only the seeded default (no
    operator has reviewed it) is marked as such, so "Trusted" from the
    curated allowlist doesn't read as a human's judgment."""
    source_tier = source_tier or {}
    key = str(source_tier.get("tier") or "unknown").lower()
    if key not in TRUST_TIER_LABELS:
        key = "unknown"
    label = TRUST_TIER_LABELS[key]
    if key != "unknown" and source_tier.get("is_default"):
        label += " (default)"
    return f'<span class="trust-tag" style="background-color:{TRUST_TIER_COLORS[key]};">{_esc(label)}</span>'


def _header_html(report_data: dict) -> str:
    project = report_data.get("project") or {}
    scope = report_data.get("scope") or {}
    project_name = project.get("name") or f"Project {project.get('id', '')}"
    analysis_label = scope.get("analysis_date_label") or "Unknown reporting scope"
    tz = scope.get("timezone") or "UTC"
    generated_at = _fmt_iso(report_data.get("generated_at"))

    return f"""
<h1 dir="auto">Export Summary - {_esc(project_name)}</h1>
<p class="subtitle" dir="auto">Reporting scope: {_esc(analysis_label)} ({_esc(tz)})</p>
<p class="subtitle">Exported: {generated_at} (export timestamp, distinct from the reporting scope's analysis date above)</p>
"""


def _counts_html(report_data: dict) -> str:
    counts = report_data.get("counts") or {}
    fields = [
        ("total", "Total in Scope"),
        ("analyzed", "Analyzed"),
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("failed", "Failed"),
        ("partial", "Partial"),
    ]
    cells = "".join(
        f'<td><span class="stat-value">{_fmt_num(counts.get(key))}</span>'
        f'<span class="stat-label">{_esc(label)}</span></td>'
        for key, label in fields
    )
    return f'<h2>Overview</h2><table class="stats"><tr>{cells}</tr></table>'


def _executive_summary_html(report_data: dict) -> str:
    summary = report_data.get("executive_summary") or {}
    text = summary.get("text")
    error = summary.get("error")
    if text:
        body = _esc_multiline(text)
    elif error:
        # Distinct from "nothing generated yet" - this is report_data.py's
        # own build_report_data() disclosing that generating it was actually
        # attempted and failed (an LLM outage, most commonly), the same way
        # _comparison_html discloses a failure in its own section rather than
        # silently rendering nothing.
        body = f'<div class="unavailable">AI executive summary unavailable - {_esc(error)}</div>'
    else:
        body = '<p class="muted">No executive summary available.</p>'
    return f'<h2>Executive Summary</h2>{body}'


def _top_articles_html(report_data: dict) -> str:
    articles = report_data.get("top_articles") or []
    fallback_note = ""
    if report_data.get("top_articles_fallback_used"):
        fallback_note = (
            '<div class="note">Relevance scores were not available for this scope - '
            "articles below are ordered by recency instead.</div>"
        )

    if not articles:
        return (
            "<h2>Top Articles</h2>"
            f"{fallback_note}"
            '<p class="muted">No articles available for this scope.</p>'
        )

    blocks = []
    for item in articles:
        rank = item.get("rank")
        title = item.get("title") or "(untitled)"
        summary = item.get("short_summary") or ""
        sentiment = item.get("sentiment") or "neutral"
        source = item.get("source") or "Unknown source"
        reference = item.get("reference") or ""
        score = item.get("relevance_score")
        score_label = f"relevance {score:.2f}" if isinstance(score, (int, float)) else "relevance n/a"

        blocks.append(f"""
<div class="article-block">
  <p class="article-title" dir="auto">{_esc(rank)}. {_esc(title)} {_sentiment_tag_html(sentiment)}</p>
  <p class="article-meta" dir="auto">Source: {_esc(source)} {_trust_tag_html(item.get("source_tier"))} &bull; {_esc(score_label)} &bull; {_esc(reference)}</p>
  <p dir="auto">{_esc(summary)}</p>
</div>
""")

    return f'<h2>Top Articles</h2>{fallback_note}{"".join(blocks)}'


def _sentiment_html(report_data: dict) -> str:
    sentiment = report_data.get("sentiment") or {}
    rows = []
    for key in ("positive", "negative", "neutral", "mixed"):
        bucket = sentiment.get(key) or {}
        count = bucket.get("count", 0)
        pct = bucket.get("pct", 0.0)
        width = max(0.0, min(100.0, float(pct or 0.0)))
        color = SENTIMENT_COLORS.get(key, "#757575")
        rows.append(f"""
<tr>
  <td class="bar-label">{_esc(SENTIMENT_LABELS[key])}</td>
  <td class="bar-cell"><div class="bar-fill" style="width:{width}%;background-color:{color};">&#160;</div></td>
  <td class="bar-pct">{_esc(pct)}% ({_fmt_num(count)})</td>
</tr>
""")
    net = sentiment.get("net_sentiment", 0)
    analyzed_total = sentiment.get("analyzed_total", 0)
    table = f'<table class="bars">{"".join(rows)}</table>'
    footer = (
        f'<p class="muted">Net sentiment: {_esc(net)} &bull; '
        f"based on {_fmt_num(analyzed_total)} analyzed article(s)</p>"
    )
    return f"<h2>Sentiment Breakdown</h2>{table}{footer}"


def _idea_comparisons_html(report_data: dict) -> str:
    section = report_data.get("idea_comparisons") or {}
    items = section.get("items") or []
    error = section.get("error")

    parts = ["<h2>Idea Comparisons</h2>"]
    if section.get("project_wide"):
        parts.append(
            '<p class="muted">Ideas more than one source discussed, across the whole project '
            "(not limited to the reporting period above).</p>"
        )
    else:
        parts.append('<p class="muted">Ideas more than one source discussed in this analysis run.</p>')
    if error:
        parts.append(f'<div class="unavailable">Idea comparisons unavailable - {_esc(error)}</div>')
    if not items:
        if not error:
            parts.append('<p class="muted">No idea was discussed by more than one source in this scope.</p>')
        return "".join(parts)

    header = "<tr><th>Source</th><th>Trust tier</th><th>Claim</th><th>Article</th></tr>"
    for item in items:
        if item.get("diverges"):
            tag = f'<span class="divergence-tag" style="background-color:{SENTIMENT_COLORS["negative"]};">Sources disagree</span>'
        else:
            tag = f'<span class="divergence-tag" style="background-color:{SENTIMENT_COLORS["positive"]};">Sources agree</span>'
        rows = []
        for claim in item.get("claims") or []:
            claim_text = claim.get("claim")
            claim_html = _esc(claim_text) if claim_text else '<span class="muted">No specific figure stated</span>'
            rows.append(
                f'<tr><td dir="auto">{_esc(claim.get("source") or "Unknown source")}</td>'
                f'<td>{_trust_tag_html(claim.get("source_tier"))}</td>'
                f'<td dir="auto">{claim_html}</td>'
                f'<td dir="auto">{_esc(claim.get("title"))} <span class="muted">{_esc(claim.get("reference"))}</span></td></tr>'
            )
        summary = item.get("summary")
        parts.append(f"""
<div class="comparison-block">
  <p class="comparison-idea" dir="auto">{_esc(item.get("idea"))} {tag}</p>
  {_esc_multiline(summary) if summary else ""}
  <table>{header}{"".join(rows)}</table>
</div>
""")
    return "".join(parts)


def _metrics_row_html(label: str, metrics: dict | None) -> str:
    if not metrics:
        return f'<tr><td>{_esc(label)}</td><td colspan="6" class="muted">No data</td></tr>'
    cells = "".join(
        f"<td>{_fmt_num(metrics.get(key))}</td>"
        for key in ("total", "positive", "negative", "neutral", "mixed", "net_sentiment")
    )
    return f"<tr><td>{_esc(label)}</td>{cells}</tr>"


def _comparison_html(comparison: dict | None) -> str:
    comparison = comparison or {}
    status = comparison.get("status") or "unavailable"
    reason = comparison.get("reason")
    metrics = comparison.get("metrics") or {}
    current_metrics = metrics.get("current")
    previous_metrics = metrics.get("previous")
    deltas = metrics.get("deltas")
    coverage = metrics.get("coverage")

    current_date = comparison.get("current_date") or ""
    previous_date = comparison.get("previous_date") or ""
    current_label = comparison.get("current_scope_label") or ""
    previous_label = comparison.get("previous_scope_label") or ""
    tz = comparison.get("timezone") or "UTC"

    parts = ["<h2>Variation from Last Run</h2>"]
    parts.append(
        f'<p class="subtitle">Selected run: {_esc(current_label)} ({_esc(current_date)}) vs. '
        f"Previous run: {_esc(previous_label)} ({_esc(previous_date)}) &bull; {_esc(tz)}</p>"
    )

    if status != "ok":
        message = "AI narrative unavailable" if status == "llm_failed" else "Comparison unavailable"
        reason_html = f" - {_esc(reason)}" if reason else ""
        parts.append(f'<div class="unavailable">{_esc(message)}{reason_html}</div>')

    if current_metrics is not None or previous_metrics is not None:
        header = (
            "<tr><th>Scope</th><th>Total</th><th>Positive</th><th>Negative</th>"
            "<th>Neutral</th><th>Mixed</th><th>Net</th></tr>"
        )
        rows = _metrics_row_html("Selected run", current_metrics) + _metrics_row_html("Previous run", previous_metrics)
        if deltas:
            rows += _metrics_row_html("Delta", deltas)
        parts.append(f"<table>{header}{rows}</table>")

    if coverage:
        parts.append(
            '<p class="muted">Coverage: '
            f"{_fmt_num(coverage.get('common'))} article(s) common to both runs, "
            f"{_fmt_num(coverage.get('added'))} added, {_fmt_num(coverage.get('removed'))} removed "
            f"(selected: {_fmt_num(coverage.get('current_ids'))} ids, previous: {_fmt_num(coverage.get('previous_ids'))} ids)"
            + (" - sampled" if coverage.get("sampled") else "")
            + "</p>"
        )

    if status == "ok":
        narrative = comparison.get("narrative")
        if narrative:
            parts.append(f'<h3>Narrative</h3>{_esc_multiline(narrative)}')
        else:
            parts.append('<p class="muted">No narrative available.</p>')

    evidence = comparison.get("evidence") or []
    if evidence:
        items = []
        for entry in evidence:
            point = entry.get("point") or ""
            article_ids = entry.get("article_ids") or []
            ids_label = ", ".join(str(i) for i in article_ids) if article_ids else "none"
            items.append(
                f'<p class="evidence-item" dir="auto">&bull; {_esc(point)} '
                f'<span class="muted">(articles: {_esc(ids_label)})</span></p>'
            )
        parts.append(f'<h3>Evidence</h3>{"".join(items)}')

    return "".join(parts)


def _build_html(report_data: dict, comparison: dict) -> str:
    report_data = report_data or {}
    comparison = comparison or {}
    sections = [
        _header_html(report_data),
        _counts_html(report_data),
        _executive_summary_html(report_data),
        _top_articles_html(report_data),
        _sentiment_html(report_data),
        _comparison_html(comparison),
        _idea_comparisons_html(report_data),
    ]
    body = "\n".join(sections)
    return f"<html><body>{body}</body></html>"


def _stamp_page_numbers(pdf_bytes: bytes) -> bytes:
    """Adds a centered "Page X of Y" footer to every page. Plain ASCII/digits
    only, so the low-level page.insert_text call (which does not shape
    Arabic) is fine here - nothing user-supplied ever reaches this text."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total = doc.page_count
    for index, page in enumerate(doc, start=1):
        label = f"Page {index} of {total}"
        rect = page.rect
        text_width = fitz.get_text_length(label, fontname="helv", fontsize=8)
        x = (rect.width - text_width) / 2
        y = rect.height - 20
        page.insert_text((x, y), label, fontsize=8, fontname="helv", color=(0.35, 0.35, 0.35))
    try:
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()


def _render_story_pdf(html_doc: str) -> bytes:
    """Lays out one already-built HTML document through fitz.Story and
    returns the finished PDF bytes. Shared by every renderer in this module
    so a new report type gets the same RTL/Arabic-safe pagination as the
    Export Summary PDF for free, rather than a second copy of this loop."""
    story = fitz.Story(html=html_doc, user_css=BASE_CSS)
    mediabox = fitz.paper_rect(PAGE_SIZE)
    where = mediabox + (MARGIN_LEFT, MARGIN_TOP, -MARGIN_RIGHT, -MARGIN_BOTTOM)

    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    more = 1
    pages = 0
    while more:
        device = writer.begin_page(mediabox)
        more, _filled = story.place(where)
        story.draw(device)
        writer.end_page()
        pages += 1
        if pages >= MAX_PAGES:
            break
    writer.close()

    return _stamp_page_numbers(buffer.getvalue())


def render_summary_pdf(report_data: dict, comparison: dict) -> bytes:
    """Renders the Export Summary PDF for one project/scope. Both arguments
    are plain dicts already assembled by callers (report_data.py's
    build_report_data / yesterday_comparison.py) - every string value inside
    them is treated as untrusted, document-derived content and is
    html.escape()'d before it reaches the HTML template. Returns the PDF as
    bytes; this function performs no filesystem writes itself."""
    html_doc = _build_html(report_data or {}, comparison or {})
    return _render_story_pdf(html_doc)


def _processing_location_label() -> str:
    """Where the analysis behind this report actually ran, for the evidence
    appendix - the same "nothing leaves the machine except the configured
    LLM" fact this fork is built around (see the project's CLAUDE.md), made
    legible to whoever the report is handed to. Read from the app's *current*
    configuration rather than a value captured at generation time (no such
    column exists on competitor_findings), so this describes the operator's
    present setup, not necessarily the exact run that produced this finding.
    """
    provider = config.COMPETITOR_ANALYSIS_LLM_PROVIDER
    if provider == "ollama":
        location = "This machine (self-hosted, via Ollama)"
    else:
        location = f"Hosted third-party API ({provider})"
    offloaded_stages = [
        label
        for label, provider_setting in (
            ("sentiment", config.SENTIMENT_CLASSIFIER_PROVIDER),
            ("classification", config.CLASSIFICATION_PROVIDER),
        )
        if provider_setting == "hf_api"
    ]
    if offloaded_stages:
        location += f"; {', '.join(offloaded_stages)} analysis via the Hugging Face Inference API"
    return location


def _competitor_header_html(finding: dict) -> str:
    competitor_name = finding.get("competitor_name") or "Unknown competitor"
    headline = finding.get("headline") or ""
    generated_at = _fmt_iso(finding.get("generated_at"))

    period_html = ""
    if finding.get("period_start"):
        period_html = (
            f'<p class="subtitle">Period: {_fmt_iso(finding.get("period_start"))} '
            f'to {_fmt_iso(finding.get("period_end"))}</p>'
        )

    return f"""
<h1 dir="auto">Competitor Report - {_esc(competitor_name)}</h1>
<p class="subtitle" dir="auto">{_esc(headline)}</p>
{period_html}
<p class="subtitle">Generated: {generated_at}</p>
"""


_NOT_AVAILABLE_HTML = '<p class="muted">Not available.</p>'


def _competitor_body_html(finding: dict) -> str:
    whats_up_html = _esc_multiline(finding.get("whats_up")) or _NOT_AVAILABLE_HTML
    impact_html = _esc_multiline(finding.get("impact")) or _NOT_AVAILABLE_HTML
    parts = [
        f'<h2>What They’re Up To</h2>{whats_up_html}',
        f'<h2>How It Affects Us</h2>{impact_html}',
    ]

    parts.append("<h2>Suggested Actions</h2>")
    actions = finding.get("actions") or []
    if actions:
        blocks = []
        for index, item in enumerate(actions, start=1):
            rationale = item.get("rationale")
            meta = " &bull; ".join(
                _esc(value) for value in (item.get("urgency"), item.get("effort")) if value
            )
            blocks.append(f"""
<div class="article-block">
  <p class="article-title" dir="auto">{index}. {_esc(item.get("action"))}</p>
  {f'<p class="article-meta" dir="auto">{_esc(rationale)}</p>' if rationale else ""}
  {f'<p class="muted">{meta}</p>' if meta else ""}
</div>
""")
        parts.append("".join(blocks))
    else:
        parts.append('<p class="muted">No actions proposed - the evidence did not support a specific recommendation.</p>')

    signals = finding.get("signals") or []
    if signals:
        badges = " ".join(
            f'<span class="trust-tag" style="background-color:#555555;">{_esc(signal)}</span>'
            for signal in signals
        )
        parts.append(f"<h2>Signals</h2><p>{badges}</p>")

    return "".join(parts)


def _competitor_appendix_html(finding: dict, rejected_evidence: list[dict]) -> str:
    """The evidence appendix: which documents/excerpts this report actually
    rests on, when it was generated, and where the analysis ran - so a
    hand-off doesn't lose the detail a screenshot of the page would drop."""
    evidence = finding.get("evidence") or []
    parts = ["<h2>Evidence Appendix</h2>"]
    parts.append(
        f'<p class="subtitle">Generated: {_fmt_iso(finding.get("generated_at"))} &bull; '
        f'Processing location: {_esc(_processing_location_label())}</p>'
    )

    if not evidence:
        parts.append('<p class="muted">No evidence attached to this report.</p>')
    else:
        # Grouped by source - a document's filename for evidence split out of
        # an uploaded file (see competitor_document_articles.py), or the
        # outlet name for anything else - so a reader sees which documents
        # this report is actually built from, not just a flat excerpt list.
        grouped: dict[str, list[dict]] = {}
        for item in evidence:
            key = item.get("source") or "Unknown source"
            grouped.setdefault(key, []).append(item)

        parts.append(f'<p class="muted">Documents cited ({len(grouped)}):</p>')
        for source, items in grouped.items():
            parts.append(f'<h3 dir="auto">{_esc(source)}</h3>')
            for item in items:
                title = item.get("title") or item.get("url") or "(untitled)"
                published = (
                    _fmt_iso(item.get("published_at")) if item.get("published_at") else "Unknown date"
                )
                excerpt = item.get("excerpt") or ""
                parts.append(f"""
<div class="article-block">
  <p class="article-title" dir="auto">{_esc(title)}</p>
  <p class="article-meta">{published}</p>
  {f'<p class="evidence-item" dir="auto">{_esc(excerpt)}</p>' if excerpt else ""}
</div>
""")

    if rejected_evidence:
        parts.append(f"<h3>Filtered out ({len(rejected_evidence)})</h3>")
        rows = "".join(
            f'<tr><td dir="auto">{_esc(item.get("title") or item.get("url"))}</td>'
            f'<td dir="auto">{_esc(item.get("source"))}</td>'
            f'<td>{_esc(str(item.get("rejected_reason") or "").replace("_", " "))}</td>'
            f'<td>{_fmt_iso(item.get("dated"))}</td></tr>'
            for item in rejected_evidence
        )
        parts.append(
            f'<table><tr><th>Title</th><th>Source</th><th>Reason excluded</th><th>Date</th></tr>{rows}</table>'
        )

    confidence = finding.get("confidence")
    confidence_label = f"{round(float(confidence) * 100)}%" if confidence is not None else "Not assessed"
    other_rows = [
        ("Validation status", _esc_or(finding.get("validation_status"))),
        ("Confidence", _esc(confidence_label)),
        ("Independent stories", _fmt_num(finding.get("story_count"))),
        ("Articles used", _fmt_num(finding.get("article_count"))),
        ("Analysis model", _esc_or(finding.get("analysis_model"))),
    ]
    other_html = "".join(
        f'<tr><td>{_esc(label)}</td><td dir="auto">{value}</td></tr>' for label, value in other_rows
    )
    parts.append(f"<h2>Other Information</h2><table>{other_html}</table>")

    return "".join(parts)


def _build_competitor_report_html(finding: dict, rejected_evidence: list[dict]) -> str:
    finding = finding or {}
    rejected_evidence = rejected_evidence or []
    sections = [
        _competitor_header_html(finding),
        _competitor_body_html(finding),
        _competitor_appendix_html(finding, rejected_evidence),
    ]
    return f"<html><body>{''.join(sections)}</body></html>"


def render_competitor_report_pdf(finding: dict, rejected_evidence: list[dict]) -> bytes:
    """Renders one competitor finding as a standalone PDF - the Competitor
    Report page's "Export report (PDF)" button. `finding` is the dict
    competitor_analysis.get_finding() returns (headline/whats_up/impact/
    actions/signals/evidence/...), `rejected_evidence` is
    competitor_analysis.rejected_evidence()'s filtered-out list. Every string
    value inside them is treated as untrusted, document-derived content and
    is html.escape()'d before it reaches the HTML template. Reuses the same
    fitz.Story pipeline as render_summary_pdf (via _render_story_pdf), so a
    hand-off from this page gets the same RTL/Arabic-safe layout as the
    Reports page's own export."""
    html_doc = _build_competitor_report_html(finding, rejected_evidence)
    return _render_story_pdf(html_doc)


def _consolidated_cover_html(run: dict, findings: list[dict]) -> str:
    """Cover page for the consolidated PDF: which run this covers and a table
    of contents naming every competitor whose report follows, so a reader
    handed a 30-page combined PDF can find one competitor without scrolling."""
    run = run or {}
    sequence = run.get("sequence_number")
    title = f"Analysis #{sequence}" if sequence is not None else "Competitor Analysis"
    generated_at = _fmt_iso(run.get("finished_at") or run.get("started_at"))

    toc_items = "".join(
        f'<p class="toc-item" dir="auto">&bull; {_esc(item.get("competitor_name") or "Unknown competitor")} '
        f'- {_esc(item.get("headline") or "")}</p>'
        for item in findings
    )
    if not toc_items:
        toc_items = '<p class="muted">No findings in this run.</p>'

    return f"""
<h1>Consolidated Competitor Report - {_esc(title)}</h1>
<p class="subtitle">Run finished: {generated_at}</p>
<p class="subtitle">Competitors covered: {_fmt_num(len(findings))}</p>
<h2>Contents</h2>
{toc_items}
"""


def _build_consolidated_competitor_report_html(
    run: dict, findings: list[dict], rejected_by_competitor: dict[int, list[dict]],
) -> str:
    findings = findings or []
    sections = [_consolidated_cover_html(run, findings)]
    for finding in findings:
        rejected = rejected_by_competitor.get(finding.get("competitor_id")) or []
        sections.append(
            '<div class="consolidated-section">'
            + _competitor_header_html(finding)
            + _competitor_body_html(finding)
            + _competitor_appendix_html(finding, rejected)
            + "</div>"
        )
    return f"<html><body>{''.join(sections)}</body></html>"


def render_consolidated_competitor_report_pdf(
    run: dict, findings: list[dict], rejected_by_competitor: dict[int, list[dict]],
) -> bytes:
    """Renders every competitor finding from one analysis run as a single
    combined PDF - a cover page/table of contents followed by one full
    competitor report per finding (each starting on its own page), reusing
    the same per-competitor sections as render_competitor_report_pdf so the
    consolidated PDF and the single-finding PDF never drift apart. `run` is
    analysis_runs_store.get_run()'s dict, `findings` is
    competitor_analysis.list_findings(..., analysis_run_id=run_id)'s list,
    and `rejected_by_competitor` maps competitor_id -> that competitor's
    competitor_analysis.rejected_evidence() list."""
    html_doc = _build_consolidated_competitor_report_html(run, findings, rejected_by_competitor)
    return _render_story_pdf(html_doc)
