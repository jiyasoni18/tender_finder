"""
GeM (Government e-Marketplace / bidplus) scraper — SKELETON.

Same idea as ireps.py: fill in the three methods. GeM's bid search lives under
https://bidplus.gem.gov.in/all-bids and returns bid cards with a bid number,
value, and end date, plus a link to the bid document PDF.
"""

from __future__ import annotations

from pathlib import Path

from sites.base import BaseScraper, Listing

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None


class GemScraper(BaseScraper):
    name = "gem"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._pw = None
        self._browser = None
        self._page = None

    def _ensure_browser(self):
        if sync_playwright is None:
            raise RuntimeError(
                "playwright is required for the GeM scraper. "
                "Install it: pip install playwright && playwright install chromium"
            )
        if self._page is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._page = self._browser.new_page()
        return self._page

    def login(self) -> None:
        # Public bid search does not always need a login. If yours does, wire it
        # here the same way as ireps.py.
        self._ensure_browser()
        self.log.warning("GeM.login() is a stub (public search may not need auth).")

    def find_new_tenders(self) -> list[Listing]:
        page = self._ensure_browser()
        # TODO: page.goto(f"{self.config.base_url}/all-bids"); read the bid cards.
        self.log.warning("GeM.find_new_tenders() is a stub — returns nothing.")
        return []

    def fetch_pdf(self, listing: Listing, dest: Path) -> Path:
        # TODO: download the bid document PDF for `listing` into `dest`.
        raise NotImplementedError("Implement GeM.fetch_pdf()")

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._page = self._browser = self._pw = None
