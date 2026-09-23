"""Renders the Reports page's Export Summary as a PDF, given the two dicts
built elsewhere: `report_data` (services/reports/report_data.py's
build_report_data) and `comparison` (yesterday_comparison.py's day-over-day
"variation from yesterday" result). This module owns layout only - it never
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


def _sentiment_tag_html(sentiment: str) -> str:
    key = str(sentiment or "neutral").lower()
    color = SENTIMENT_COLORS.get(key, "#757575")
    label = SENTIMENT_LABELS.get(key, key.title() or "Neutral")
    return f'<span class="sentiment-tag" style="background-color:{color};">{_esc(label)}</span>'


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
    body = _esc_multiline(text) if text else '<p class="muted">No executive summary available.</p>'
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
  <p class="article-meta">Source: {_esc(source)} &bull; {_esc(score_label)} &bull; {_esc(reference)}</p>
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
    today_metrics = metrics.get("today")
    yesterday_metrics = metrics.get("yesterday")
    deltas = metrics.get("deltas")
    coverage = metrics.get("coverage")

    today_date = comparison.get("today_date") or ""
    yesterday_date = comparison.get("yesterday_date") or ""
    today_label = comparison.get("today_scope_label") or ""
    yesterday_label = comparison.get("yesterday_scope_label") or ""
    tz = comparison.get("timezone") or "UTC"

    parts = ["<h2>Variation from Yesterday</h2>"]
    parts.append(
        f'<p class="subtitle">Today: {_esc(today_date)} ({_esc(today_label)}) vs. '
        f"Yesterday: {_esc(yesterday_date)} ({_esc(yesterday_label)}) &bull; {_esc(tz)}</p>"
    )

    if status != "ok":
        message = "AI narrative unavailable" if status == "llm_failed" else "Comparison unavailable"
        reason_html = f" - {_esc(reason)}" if reason else ""
        parts.append(f'<div class="unavailable">{_esc(message)}{reason_html}</div>')

    if today_metrics is not None or yesterday_metrics is not None:
        header = (
            "<tr><th>Scope</th><th>Total</th><th>Positive</th><th>Negative</th>"
            "<th>Neutral</th><th>Mixed</th><th>Net</th></tr>"
        )
        rows = _metrics_row_html("Today", today_metrics) + _metrics_row_html("Yesterday", yesterday_metrics)
        if deltas:
            rows += _metrics_row_html("Delta", deltas)
        parts.append(f"<table>{header}{rows}</table>")

    if coverage:
        parts.append(
            '<p class="muted">Coverage: '
            f"{_fmt_num(coverage.get('common'))} article(s) common to both days, "
            f"{_fmt_num(coverage.get('added'))} added, {_fmt_num(coverage.get('removed'))} removed "
            f"(today: {_fmt_num(coverage.get('today_ids'))} ids, yesterday: {_fmt_num(coverage.get('yesterday_ids'))} ids)"
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


def render_summary_pdf(report_data: dict, comparison: dict) -> bytes:
    """Renders the Export Summary PDF for one project/scope. Both arguments
    are plain dicts already assembled by callers (report_data.py's
    build_report_data / yesterday_comparison.py) - every string value inside
    them is treated as untrusted, document-derived content and is
    html.escape()'d before it reaches the HTML template. Returns the PDF as
    bytes; this function performs no filesystem writes itself."""
    html_doc = _build_html(report_data or {}, comparison or {})

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
