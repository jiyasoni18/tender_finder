"""
GeM (Government e-Marketplace / bidplus) scraper.
"""

from __future__ import annotations

from pathlib import Path
import re
import urllib.parse
from datetime import datetime

from sites.base import BaseScraper, Listing

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    sync_playwright = None
    PlaywrightTimeout = Exception


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
            self._page.set_default_timeout(30000)
        return self._page

    def login(self) -> None:
        # Public bid search does not need login
        pass

    def find_new_tenders(self) -> list[Listing]:
        page = self._ensure_browser()
        url = "https://bidplus.gem.gov.in/all-bids"
        self.log.info(f"Navigating to {url}")
        
        try:
            page.goto(url)
            page.wait_for_selector('div.border.block, div.card, div.bid_details', timeout=20000)
        except PlaywrightTimeout:
            self.log.error("Timeout waiting for GeM bids to load.")
            return []

        # Handle Keyword search if provided (could be list from env or string from user override)
        keywords = self.config.options.get("keywords", [])
        search_query = keywords if isinstance(keywords, str) else ", ".join(keywords)
        
        if search_query:
            self.log.info(f"Applying keyword search: {search_query}")
            try:
                # Typically there's a search box
                search_input = page.locator('input[type="search"], input[placeholder*="Search"], input[id*="searchBid"]').first
                if search_input.count() > 0:
                    search_input.fill(search_query)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(3000) # wait for refresh
                    page.wait_for_selector('div.border.block, div.card', timeout=20000)
                else:
                    self.log.warning("Could not find search input on GeM page.")
            except Exception as e:
                self.log.warning(f"Error applying keyword search: {e}")

        # Parse listings
        results = []
        try:
            cards = page.query_selector_all('div.border.block, div.card, div.bid_details')
            for card in cards:
                text = card.inner_text()
                
                # Extract Bid No
                bid_no_match = re.search(r"Bid No\.:?\s*(GEM/[^\s]+)", text, re.IGNORECASE)
                if not bid_no_match:
                    continue
                bid_no = bid_no_match.group(1).strip()
                
                # Extract End Date
                end_date = None
                date_match = re.search(r"End Date:\s*([\d-]+ [\d:]+ [APM]+)", text, re.IGNORECASE)
                if date_match:
                    try:
                        # 01-10-2026 11:39 AM
                        dt = datetime.strptime(date_match.group(1).strip(), "%d-%m-%Y %I:%M %p")
                        end_date = dt.date()
                    except ValueError:
                        pass
                
                # Financial filters
                # Often not explicitly stated on GeM public listings, so it defaults to None (needs manual review)
                val = None

                link_el = card.query_selector(f"a:has-text('{bid_no}')") or card.query_selector("a[href*='showbidDocument']")
                href = link_el.get_attribute("href") if link_el else ""
                
                if href and not href.startswith("http"):
                    href = urllib.parse.urljoin(url, href)

                results.append(Listing(
                    id=bid_no,
                    value=val,
                    closing_date=end_date,
                    raw_data={"url": href, "text": text[:200]}
                ))
                
        except Exception as e:
            self.log.error(f"Error parsing GeM bids: {e}")

        return results

    def fetch_pdf(self, listing: Listing, dest: Path) -> Path:
        href = listing.raw_data.get("url")
        if not href:
            raise ValueError(f"No document URL found for {listing.id}")
            
        page = self._ensure_browser()
        self.log.info(f"Downloading GeM doc for {listing.id} from {href}")
        
        try:
            # We first try to click it as a navigation which might download it
            with page.expect_download(timeout=15000) as download_info:
                page.goto(href)
            download = download_info.value
            download.save_as(str(dest))
            return dest
        except Exception as e:
            self.log.info(f"Did not trigger direct download, attempting raw request fallback... ({e})")
            import requests
            res = requests.get(href, verify=False, timeout=15)
            res.raise_for_status()
            dest.write_bytes(res.content)
            return dest

    def close(self) -> None:
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._page = self._browser = self._pw = None
