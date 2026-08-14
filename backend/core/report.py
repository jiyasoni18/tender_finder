import re
import time
from pathlib import Path
from typing import List

from config import REPORTS_DIR
from core.models import TenderDoc
from core.logging_setup import get_logger

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

log = get_logger("report")

# ─────────────────────────────────────────────────────────────────────────────
#  PDF CSS — matches the user's reference PDF format exactly
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 11pt;
    color: #1a1a2e;
    line-height: 1.5;
    background: #ffffff;
}

/* ── Page header ── */
.report-header {
    background: #1d3a6d;
    color: #ffffff;
    text-align: center;
    padding: 18px 24px;
    margin-bottom: 0;
}
.report-header .report-title {
    font-size: 14pt;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
}
.report-header .report-subtitle {
    font-size: 10pt;
    opacity: 0.85;
}

/* ── Meta box (2-line summary + link) ── */
.meta-box {
    background: #eaf1fb;
    border-left: 5px solid #1d3a6d;
    padding: 14px 20px;
    margin-bottom: 20px;
    font-size: 10.5pt;
}
.meta-box .meta-label  { font-weight: 700; color: #1d3a6d; }
.meta-box a { color: #1d3a6d; font-weight: 600; text-decoration: none; }

/* ── Section heading ── */
h2.section-heading {
    background: #1d3a6d;
    color: #ffffff;
    font-size: 10.5pt;
    font-weight: 700;
    letter-spacing: 0.6px;
    text-transform: uppercase;
    padding: 8px 14px;
    margin: 22px 0 10px;
    page-break-after: avoid;
}

/* ── Tables ── */
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 12px;
    font-size: 10pt;
    page-break-inside: avoid;
}
th {
    background: #dce8f5;
    color: #1d3a6d;
    font-weight: 600;
    padding: 7px 10px;
    border: 1px solid #b0c8e8;
    text-align: left;
    vertical-align: top;
}
td {
    padding: 6px 10px;
    border: 1px solid #c8d8ee;
    vertical-align: top;
}
tr:nth-child(even) td { background: #f4f8fd; }

/* ── Lists ── */
ul, ol {
    margin: 6px 0 10px 22px;
    font-size: 10pt;
}
li { margin-bottom: 4px; }

/* ── Paragraphs ── */
p { margin-bottom: 10px; font-size: 10pt; }

/* ── Risk / Strategy sub-headings ── */
.sub-heading {
    font-weight: 700;
    color: #1d3a6d;
    font-size: 10pt;
    margin: 10px 0 4px;
    text-decoration: underline;
}

/* ── Page break ── */
.page-break { page-break-before: always; }
"""

def _html_page(doc: TenderDoc, body_html: str) -> str:
    """Wrap the Gemini-generated body HTML in a complete, styled page."""
    meta_summary = doc.summary or "No summary available."
    detail_url   = getattr(doc, 'detail_url', '') or ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>{_CSS}</style>
</head>
<body>

<div class="report-header">
  <div class="report-title">STRATEGIC TENDER ANALYSIS &amp; BID ADVISORY REPORT</div>
  <div class="report-subtitle">Tender ID: {doc.doc_id}</div>
</div>

<div class="meta-box">
  <div><span class="meta-label">2-Line Summary:</span> {meta_summary}</div>
  <br>
  <div><span class="meta-label">Doc Link:</span> <a href="{detail_url}">{detail_url}</a></div>
</div>

{body_html}

</body>
</html>"""


def _apply_heading_styles(html: str) -> str:
    """
    Post-process Gemini's raw HTML to enforce consistent section heading styling.
    Replaces any <h1>, <h2>, <h3> tags that match section names with our styled version.
    """
    # Replace headings that contain section numbers with styled versions
    def replace_h(m):
        inner = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        return f'<h2 class="section-heading">{inner}</h2>'

    html = re.sub(r'(<h[123][^>]*>)(.*?)(</h[123]>)', replace_h, html, flags=re.IGNORECASE | re.DOTALL)
    return html


def generate_single_report(doc: TenderDoc) -> None:
    """Generate the PDF and TXT summary for a single tender."""
    if not sync_playwright or not doc.report_html:
        if not doc.report_html:
            log.warning("No report HTML for %s — skipping report generation.", doc.doc_id)
        return

    body = _apply_heading_styles(doc.report_html)
    full_html = _html_page(doc, body)

    # Save into the tender's own folder if we know it, else fall back to REPORTS_DIR
    if doc.pdf_path and doc.pdf_path.parent.is_dir():
        out_dir = doc.pdf_path.parent
    else:
        out_dir = REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(doc.doc_id))[:80]
    pdf_path = out_dir / f"Summary_{safe_id}.pdf"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(full_html, wait_until="domcontentloaded")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"},
            )
            browser.close()
        log.info("✓ Single PDF report saved to %s", pdf_path)
    except Exception as e:
        log.error("Failed to convert single HTML to PDF for %s: %s", doc.doc_id, e)

    # TXT generation removed — only PDF summary is produced.


def generate_final_report(docs: List[TenderDoc]) -> None:
    """Generate a combined PDF report for all passed tenders."""
    if not docs:
        log.info("No tenders passed, skipping final report generation.")
        return

    if not sync_playwright:
        log.warning("Playwright not installed, cannot generate PDF report.")
        return

    log.info("Generating final PDF report for %d tenders...", len(docs))

    pages_html = []
    for i, doc in enumerate(docs):
        body = _apply_heading_styles(doc.report_html or "<p><i>No report available.</i></p>")
        page_html = _html_page(doc, body)
        # Strip <html>/<body> tags for embedding except the first
        if i > 0:
            inner = re.search(r'<body[^>]*>(.*?)</body>', page_html, re.IGNORECASE | re.DOTALL)
            page_html = f'<div class="page-break">{inner.group(1) if inner else ""}</div>'
        pages_html.append(page_html)

    # Wrap all pages
    combined = "\n".join(pages_html)
    # Fix: close body/html for multi-page doc
    combined = combined.replace("</html>", "") + "\n</body></html>"

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    import config
    output_dir = config.DOWNLOADS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    html_path = output_dir / f"Tender_Report_{timestamp}.html"
    pdf_path  = output_dir / f"Tender_Report_{timestamp}.pdf"

    html_path.write_text(combined, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(combined, wait_until="domcontentloaded")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "15mm", "bottom": "15mm", "left": "15mm", "right": "15mm"},
            )
            browser.close()
        log.info("✓ Final PDF report saved to %s", pdf_path)
    except Exception as e:
        log.error("Failed to convert HTML to PDF: %s", e)
