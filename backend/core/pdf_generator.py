import os
from pathlib import Path
from playwright.sync_api import sync_playwright

def generate_pdf_from_html(html_content: str, output_path: str):
    """
    Renders HTML content to a PDF file using Playwright.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html_content)
        # Wait a bit for any layout shifts
        page.wait_for_timeout(500)
        page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={"top": "1cm", "bottom": "1cm", "left": "1cm", "right": "1cm"}
        )
        browser.close()
