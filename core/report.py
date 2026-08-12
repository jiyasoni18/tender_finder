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

def _get_html_wrapper() -> str:
    return """
    <html>
    <head>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; color: #333; }
        .header { background-color: #1d3a6d; color: white; padding: 15px; text-align: center; margin-bottom: 20px; font-weight: bold; font-size: 24px;}
        .tender-section { page-break-after: always; margin-bottom: 40px; }
        h1, h2, h3 { color: #1d3a6d; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px; }
        th { background-color: #f2f2f2; color: #1d3a6d; padding: 8px; border: 1px solid #ddd; text-align: left; }
        td { padding: 8px; border: 1px solid #ddd; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .summary-box { background-color: #eaf1f8; border-left: 4px solid #1d3a6d; padding: 15px; margin-bottom: 20px; font-weight: 500;}
        a { color: #1d3a6d; text-decoration: none; font-weight: bold; }
    </style>
    </head>
    <body>
    """

def generate_single_report(doc: TenderDoc) -> None:
    if not sync_playwright or not doc.report_html or not doc.pdf_path:
        return
        
    html_parts = [_get_html_wrapper()]
    html_parts.append("<div class='tender-section'>")
    html_parts.append(f"""
    <div class="header">Tender Advisory Report: {doc.doc_id}</div>
    <div class="summary-box">
        <strong>2-Line Summary:</strong> {doc.summary if doc.summary else 'No summary available.'}<br><br>
        <strong>Doc Link:</strong> <a href="{doc.detail_url}">{doc.detail_url}</a>
    </div>
    """)
    html_parts.append(doc.report_html)
    html_parts.append("</div></body></html>")
    
    full_html = "\n".join(html_parts)
    
    pdf_path = doc.pdf_path.parent / f"Summary_{doc.doc_id}.pdf"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(full_html)
            page.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"})
            browser.close()
        log.info("✓ Single PDF report saved to %s", pdf_path)
    except Exception as e:
        log.error("Failed to convert single HTML to PDF for %s: %s", doc.doc_id, e)
        
    # Also save a plain text version for easy reading
    txt_path = doc.pdf_path.parent / f"Summary_{doc.doc_id}.txt"
    try:
        import re
        # Strip html tags from the report_html for the text version
        plain_text = re.sub(r'<[^>]+>', ' ', doc.report_html)
        # Clean up multiple spaces
        plain_text = re.sub(r' +', ' ', plain_text).replace('\n ', '\n').strip()
        
        txt_content = f"Tender Advisory Report: {doc.doc_id}\n\n"
        txt_content += f"2-Line Summary: {doc.summary}\n\n"
        txt_content += f"Doc Link: {doc.detail_url}\n\n"
        txt_content += plain_text
        
        txt_path.write_text(txt_content, encoding="utf-8")
        log.info("✓ Single TXT report saved to %s", txt_path)
    except Exception as e:
        log.error("Failed to save TXT report for %s: %s", doc.doc_id, e)

def generate_final_report(docs: List[TenderDoc]) -> None:
    if not docs:
        log.info("No tenders passed, skipping final report generation.")
        return
        
    if not sync_playwright:
        log.warning("Playwright not installed, cannot generate PDF report.")
        return
        
    log.info("Generating final PDF report for %d tenders...", len(docs))
    
    html_parts = []
    
    # HTML wrapper to give the layout some style
    html_parts.append(_get_html_wrapper())
    
    for doc in docs:
        html_parts.append("<div class='tender-section'>")
        
        # Meta table at the top if the LLM didn't include these clearly
        html_parts.append(f"""
        <div class="header">Tender Advisory Report: {doc.doc_id}</div>
        <div class="summary-box">
            <strong>2-Line Summary:</strong> {doc.summary if doc.summary else 'No summary available.'}<br><br>
            <strong>Doc Link:</strong> <a href="{doc.detail_url}">{doc.detail_url}</a>
        </div>
        """)
        
        if doc.report_html:
            import re
            short_match = re.search(r'<div id="short-report-content">(.*?)</div>\s*<div id="long-report-content">', doc.report_html, re.IGNORECASE | re.DOTALL)
            if short_match:
                html_parts.append(short_match.group(1))
            else:
                html_parts.append(doc.report_html)
        else:
            html_parts.append("<p><i>No detailed LLM report could be generated for this tender.</i></p>")
            
        html_parts.append("</div>")
        
    html_parts.append("</body></html>")
    
    full_html = "\n".join(html_parts)
    
    # Save the HTML for debugging
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    from config import DOWNLOADS_DIR
    output_dir = DOWNLOADS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / f"Tender_Report_{timestamp}.html"
    pdf_path = output_dir / f"Tender_Report_{timestamp}.pdf"
    
    html_path.write_text(full_html, encoding="utf-8")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(full_html)
            page.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"})
            browser.close()
            
        log.info("✓ Final PDF report successfully saved to %s", pdf_path)
    except Exception as e:
        log.error("Failed to convert HTML to PDF: %s", e)
