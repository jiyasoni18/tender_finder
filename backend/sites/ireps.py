"""
IREPS (Indian Railways e-Procurement) scraper.

Strategy: Use Playwright (real Chrome) to bypass the WAF and OTP login.
- `main.py` calls `login()` in the main thread, opening Chrome and waiting for OTP.
- We leave that browser open.
- The background thread calls `find_new_tenders()`, which uses the already-open Chrome
  page to click the tabs, select the dropdowns, and scrape the HTML.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

from config import STATE_DIR
from sites.base import BaseScraper, Listing

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None

BASE = "https://www.ireps.gov.in"
SEARCH_URL = f"{BASE}/epsn/anonymSearch.do"


class IrepsScraper(BaseScraper):
    name = "ireps"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._auth_cookies = []
        self._bg_pw = None
        self._bg_browser = None
        self._bg_context = None
        self._bg_page = None

    # ------------------------------------------------------------------ #
    def login(self) -> None:
        """
        Open Chrome, let the user complete OTP manually.
        We save the cookies so the background worker can start its own browser.
        """
        if sync_playwright is None:
            raise RuntimeError(
                "playwright is required. Install: pip install playwright && playwright install chromium"
            )

        self.log.info("Opening browser for IREPS OTP login...")
        auth_file = STATE_DIR / "ireps_auth.json"
        
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            
            if auth_file.exists():
                context = browser.new_context(storage_state=str(auth_file))
                self.log.info("Loaded previous session state.")
            else:
                context = browser.new_context()
                
            page = context.new_page()

            self.log.info("Navigating to guest search...")
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_timeout(3000)
            
            # Check if we're already logged in by looking for the Custom Search tab
            is_logged_in = False
            for loc in ["input[value='Custom Search']", "text='Custom Search'"]:
                if page.locator(loc).first.is_visible(timeout=1000):
                    is_logged_in = True
                    break
                    
            if is_logged_in:
                self.log.info("Already logged in via saved session! Skipping manual OTP.")
            else:
                self.log.info("=" * 60)
                self.log.info("IREPS LOGIN: Browser is open.")
                self.log.info("1. Enter mobile number, solve CAPTCHA, enter OTP.")
                self.log.info("2. Click Proceed. Wait for 'Search Tender' page.")
                self.log.info("3. Press ENTER here once you see the Search form.")
                self.log.info("=" * 60)
    
                input("Press ENTER after you see the 'Search Tender' page...")

            context.storage_state(path=str(auth_file))
            self._auth_cookies = context.cookies()
            self.log.info("Saved session state and captured %d cookies. Closing auth browser.", len(self._auth_cookies))
            browser.close()

        self._logged_in = True

    def find_new_tenders(self) -> list[Listing]:
        """Start a new Playwright context in this thread (if not open), use the saved cookies to scrape."""
        listings: list[Listing] = []

        if self._bg_pw is None:
            self.log.info("Initializing background browser for scraping and downloading...")
            self._bg_pw = sync_playwright().start()
            self._bg_browser = self._bg_pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            auth_file = STATE_DIR / "ireps_auth.json"
            if auth_file.exists():
                self._bg_context = self._bg_browser.new_context(accept_downloads=True, storage_state=str(auth_file))
            else:
                self._bg_context = self._bg_browser.new_context(accept_downloads=True)
                self._bg_context.add_cookies(self._auth_cookies)
                
            self._bg_page = self._bg_context.new_page()

        page = self._bg_page

        try:
            self.log.info("Navigating to search page...")
            page.goto(SEARCH_URL, timeout=60000)
            page.wait_for_timeout(3000)

            # ── Step 1: Click the "Custom Search" tab
            self.log.info("Clicking 'Custom Search' tab...")
            try:
                clicked = False
                for locator_str in [
                    "input[value='Custom Search']",
                    "input[value='customSearch']",
                    "text='Custom Search'",
                    "a:has-text('Custom Search')",
                    "td:has-text('Custom Search')",
                ]:
                    el = page.locator(locator_str).first
                    if el.is_visible(timeout=2000):
                        self.log.info("Found tab using %s, clicking...", locator_str)
                        el.click()
                        clicked = True
                        break
                
                if not clicked:
                    self.log.warning("Could not find the Custom Search tab using any locator!")
                
                page.wait_for_timeout(5000)
            except Exception as e:
                self.log.warning("Could not click Custom Search (maybe already on it?): %s", e)

            # ── Step 2: Set Filters (using robust extracted field names)
            if page.locator("select[name='railwayZone']").count() > 0:
                self.log.info("Setting form filters...")
                
                try:
                    page.locator("select[name='railwayZone']").first.select_option(value="-1", timeout=15000)
                except Exception as e:
                    self.log.warning("Failed to set railwayZone dropdown: %s", e)

                try:
                    page.locator("select[name='division']").first.select_option(value="18", timeout=15000)
                except Exception as e:
                    self.log.warning("Failed to set division dropdown: %s", e)

                try:
                    self.log.info("Setting custom dates (Today+5 to Today+26)...")
                    page.locator("input[name='radioDuration'][value='0']").first.click(timeout=15000)

                    from datetime import datetime, timedelta
                    today = datetime.today()
                    from_date = (today + timedelta(days=5)).strftime("%d/%m/%Y")
                    to_date = (today + timedelta(days=26)).strftime("%d/%m/%Y")
                    
                    # Fill dates by injecting the value directly (bypasses readonly attribute)
                    page.locator("input[name='dateFrom']").first.evaluate(f"el => el.value = '{from_date}'")
                    page.locator("input[name='dateTo']").first.evaluate(f"el => el.value = '{to_date}'")
                    
                    page.wait_for_timeout(1000)
                except Exception as e:
                    self.log.warning("Failed to set dates: %s", e)

            # ── Step 3: Click 'Show Results'
            self.log.info("Clicking Show Results...")
            try:
                page.locator("input[value='Show Results'], button:has-text('Show results'), input[value='Show results']").first.click()
                page.wait_for_timeout(5000)
            except Exception as e:
                self.log.error("Could not click Show Results: %s", e)
                return listings

            # ── Step 4: Extract Tenders
            self.log.info("Extracting table rows...")
            rows = page.locator("table tr").all()
            self.log.info("Found %d rows in tables.", len(rows))
            
            for row in rows:
                text = row.inner_text().strip()
                if not text:
                    continue
                
                if "Due Date" not in text and "/" not in text:
                    continue

                cells = row.locator("td").all_inner_texts()
                if len(cells) < 6:
                    continue
                    
                tender_no = cells[1].strip()
                due_date_raw = cells[5].strip()
                
                if not tender_no or "Tender Number" in tender_no or tender_no.lower() in ["tender no", "tender", "sn"]:
                    continue
                    
                if "/" not in due_date_raw or ":" not in due_date_raw:
                    self.log.warning(f"Rejected row {tender_no} because due_date_raw '{due_date_raw}' missing / or :")
                    continue
                
                try:
                    from config import parse_date
                    dt = parse_date(due_date_raw)
                    if dt:
                        # Extract the tenderAnonymsOid from the onclick of the viewNIT link
                        nit_oid = ""
                        nit_link = row.locator("a[onclick*='viewNIT']").first
                        if nit_link.count() > 0:
                            onclick_val = nit_link.get_attribute("onclick") or ""
                            # onclick looks like: postRequestNewWindow('/epsn/nitViewAnonyms/rfq/nitPublish.do?tenderAnonymsOid=XXX&activity=viewNIT', ...)
                            import re as _re
                            m = _re.search(r"tenderAnonymsOid=([^&']+)", onclick_val)
                            if m:
                                nit_oid = m.group(1)

                        link_loc = row.locator("a")
                        if link_loc.count() > 0:
                            href = link_loc.first.get_attribute("href")
                            detail_url = urljoin(BASE, href) if href else SEARCH_URL
                        else:
                            detail_url = SEARCH_URL

                        listings.append(
                            Listing(
                                doc_id=tender_no,
                                title=cells[2].strip() if len(cells) > 2 else "Unknown",
                                detail_url=detail_url,
                                closing_date=dt,
                                published_date=None,
                                value=None,
                                extra={"raw_row": " | ".join(cells), "nit_oid": nit_oid}
                            )
                        )
                    else:
                        self.log.warning(f"parse_date returned None for '{due_date_raw}'")
                except Exception as e:
                    self.log.warning("Skipped row due to date parsing exception for '%s': %s", due_date_raw, e)

        except Exception as e:
            self.log.error("Scraping error: %s", e)

        self.log.info("Found %d tenders.", len(listings))
        return listings

    def download(self, listing: Listing) -> TenderDoc:
        """Override to save files in the exact folder structure requested by the user."""
        from core.models import TenderDoc
        
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in listing.doc_id)[:100]
        
        # Exact folder requested: C:\Users\DELL\Downloads\IREPS_Tenders\[tender_id]\
        base_dir = Path(r"C:\Users\DELL\Downloads\IREPS_Tenders")
        dest_dir = base_dir / safe_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # fetch_pdf now returns a list of all downloaded paths
        paths = self.fetch_pdf(listing, dest_dir)
        first_path = paths[0] if paths else (dest_dir / f"{safe_id}.pdf")
        
        return TenderDoc(
            doc_id=listing.doc_id,
            source=self.name,
            title=listing.title,
            detail_url=listing.detail_url,
            pdf_path=first_path,
            value=listing.value,
            closing_date=listing.closing_date,
            published_date=listing.published_date,
            metadata=dict(listing.extra),
        )

    def fetch_pdf(self, listing: Listing, dest_dir: Path) -> list:
        """
        Navigate to the NIT page, find ALL download buttons/links, and download
        every document into dest_dir.  Returns a list of Path objects for every
        file that was successfully saved.
        """
        page = self._bg_page
        if not page:
            raise RuntimeError("Browser page not open. Did scraping fail?")

        self.log.info("Downloading ALL docs for %s...", listing.doc_id)
        nit_oid = listing.extra.get("nit_oid", "")
        downloaded_paths: list = []

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)

            if not nit_oid:
                # Try to get it from the live page row as fallback
                import re as _re
                row = page.locator("table tr").filter(
                    has=page.locator(f"td:has-text('{listing.doc_id}')")
                ).first
                if row.count() > 0:
                    nit_link = row.locator("a[onclick*='viewNIT']").first
                    if nit_link.count() > 0:
                        onclick_val = nit_link.get_attribute("onclick") or ""
                        m = _re.search(r"tenderAnonymsOid=([^&']+)", onclick_val)
                        if m:
                            nit_oid = m.group(1)

            if not nit_oid:
                self.log.warning("No tenderAnonymsOid for %s – cannot download.", listing.doc_id)
                return downloaded_paths

            nit_url = (
                f"{BASE}/epsn/nitViewAnonyms/rfq/nitPublish.do"
                f"?tenderAnonymsOid={nit_oid}&activity=viewNIT"
            )
            self.log.info("Opening NIT page: %s", nit_url)

            import re, requests as _requests

            nit_page = self._bg_context.new_page()
            try:
                nit_page.goto(nit_url, timeout=30000, wait_until="networkidle")

                # ── Collect all download candidates ──────────────────────────
                # Strategy A: onclick="window.open('/ireps/upload/files/…/doc.pdf')"
                pdf_urls_from_onclick: list[str] = []
                for el in nit_page.locator("a[onclick*='window.open'], input[onclick*='window.open'], button[onclick*='window.open']").all():
                    try:
                        oc = el.get_attribute("onclick") or ""
                        # grab every path inside window.open('…')
                        for m in re.finditer(r"window\.open\('([^']+)'", oc, re.I):
                            url = urljoin(BASE, m.group(1))
                            if url not in pdf_urls_from_onclick:
                                pdf_urls_from_onclick.append(url)
                    except Exception:
                        pass

                if pdf_urls_from_onclick:
                    self.log.info("Found %d window.open PDF URL(s) via onclick.", len(pdf_urls_from_onclick))
                    cookies_list = self._bg_context.cookies()
                    session_cookies = {c["name"]: c["value"] for c in cookies_list}
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                        "Referer": nit_url,
                    }
                    for idx, pdf_url in enumerate(pdf_urls_from_onclick):
                        try:
                            fname = Path(pdf_url.split("?")[0]).name or f"doc_{idx+1}.pdf"
                            file_dest = dest_dir / fname
                            if file_dest.exists():
                                file_dest = dest_dir / f"{idx+1}_{fname}"
                            r = _requests.get(pdf_url, cookies=session_cookies, headers=headers, timeout=60, stream=True)
                            r.raise_for_status()
                            with open(file_dest, "wb") as f:
                                for chunk in r.iter_content(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                            self.log.info("✓ Saved (%d/%d): %s (%d bytes)", idx+1, len(pdf_urls_from_onclick), file_dest, file_dest.stat().st_size)
                            downloaded_paths.append(file_dest)
                        except Exception as e:
                            self.log.warning("Failed to download %s: %s", pdf_url, e)

                # Strategy B: click every download-looking button and capture
                # the resulting file / new tab.  We look for buttons NOT already
                # handled by Strategy A.
                download_btns = []
                for el in nit_page.locator("input[type='button'], input[type='submit'], input[type='image'], button, a").all():
                    try:
                        val = (el.get_attribute("value") or "").strip()
                        txt = ""
                        try:
                            txt = (el.inner_text() or "").strip()
                        except Exception:
                            pass
                        oc  = (el.get_attribute("onclick") or "").lower()
                        combined = f"{val} {txt} {oc}"
                        if re.search(r"download|tender\s*doc|pdf", combined, re.I):
                            # Skip elements whose onclick we already handled via window.open
                            if "window.open" in oc:
                                continue
                            download_btns.append(el)
                    except Exception:
                        pass

                self.log.info("Found %d clickable download button(s) on NIT page.", len(download_btns))

                for idx, btn in enumerate(download_btns):
                    extra_tabs: list = []
                    try:
                        # Try to expect a new page (popup) first
                        try:
                            with self._bg_context.expect_page(timeout=8000) as pi:
                                btn.click(force=True)
                            tab2 = pi.value
                            tab2.wait_for_load_state("domcontentloaded", timeout=15000)
                            tab2_url = tab2.url
                            extra_tabs.append(tab2)
                            self.log.info("Button %d opened new tab: %s", idx+1, tab2_url)
                        except Exception:
                            tab2 = None
                            tab2_url = None

                        if tab2_url and (
                            ".pdf" in tab2_url.lower()
                            or "/pdfdocs/" in tab2_url
                            or "/upload/files/" in tab2_url
                        ):
                            # Tab is a direct PDF link
                            cookies_list = self._bg_context.cookies()
                            session_cookies = {c["name"]: c["value"] for c in cookies_list}
                            headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                                "Referer": nit_url,
                            }
                            fname = Path(tab2_url.split("?")[0]).name or f"doc_{idx+1}.pdf"
                            file_dest = dest_dir / fname
                            if file_dest.exists():
                                file_dest = dest_dir / f"{idx+1}_{fname}"
                            r = _requests.get(tab2_url, cookies=session_cookies, headers=headers, timeout=60, stream=True)
                            r.raise_for_status()
                            with open(file_dest, "wb") as f:
                                for chunk in r.iter_content(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                            self.log.info("✓ Tab-PDF saved: %s", file_dest)
                            downloaded_paths.append(file_dest)

                        elif tab2_url:
                            # Tab opened but is not a direct PDF — scan for download links inside
                            for b in tab2.locator("input[type='button'], input[type='submit'], button, a, input[type='image']").all():
                                try:
                                    combined2 = " ".join(filter(None, [
                                        b.get_attribute("value") or "",
                                        b.get_attribute("src") or "",
                                        b.get_attribute("title") or "",
                                        b.get_attribute("onclick") or "",
                                        (b.inner_text() or ""),
                                    ])).lower()
                                    if any(kw in combined2 for kw in ["download", "pdf", "nit"]):
                                        with tab2.expect_download(timeout=60000) as dli:
                                            b.click(force=True)
                                        dl = dli.value
                                        fname = dl.suggested_filename or f"doc_{idx+1}_{len(downloaded_paths)}.pdf"
                                        file_dest = dest_dir / fname
                                        if file_dest.exists():
                                            file_dest = dest_dir / f"{len(downloaded_paths)}_{fname}"
                                        dl.save_as(file_dest)
                                        self.log.info("✓ Tab2-inner download saved: %s", file_dest)
                                        downloaded_paths.append(file_dest)
                                except Exception:
                                    pass

                        else:
                            # No new tab — try direct download from the button
                            try:
                                with nit_page.expect_download(timeout=30000) as dli:
                                    btn.click(force=True)
                                dl = dli.value
                                fname = dl.suggested_filename or f"doc_{idx+1}.pdf"
                                file_dest = dest_dir / fname
                                if file_dest.exists():
                                    file_dest = dest_dir / f"{idx+1}_{fname}"
                                dl.save_as(file_dest)
                                self.log.info("✓ Direct download saved: %s", file_dest)
                                downloaded_paths.append(file_dest)
                            except Exception as e:
                                self.log.warning("Direct download failed for button %d: %s", idx+1, e)

                    except Exception as e:
                        self.log.warning("Error processing download button %d for %s: %s", idx+1, listing.doc_id, e)
                    finally:
                        for t in extra_tabs:
                            try:
                                t.close()
                            except Exception:
                                pass

                if not downloaded_paths:
                    self.log.error(
                        "No documents downloaded for %s. Dumping all clickable elements:",
                        listing.doc_id,
                    )
                    for el in nit_page.locator("input, button, a, img").all():
                        try:
                            tag = el.evaluate("el => el.tagName")
                            val = el.get_attribute("value") or ""
                            txt = ""
                            try:
                                txt = el.inner_text().strip() if tag in ["BUTTON", "A", "SPAN"] else ""
                            except Exception:
                                pass
                            oc = el.get_attribute("onclick") or ""
                            src = el.get_attribute("src") or ""
                            self.log.info("[EL] %s | val: %s | txt: %s | oc: %s | src: %s", tag, val, txt, oc, src)
                        except Exception:
                            pass

            finally:
                try:
                    nit_page.close()
                except Exception:
                    pass

        except Exception as e:
            self.log.error("Failed to download docs for %s: %s", listing.doc_id, e)

        self.log.info("Finished: %d file(s) downloaded for %s", len(downloaded_paths), listing.doc_id)
        return downloaded_paths

    def close(self) -> None:
        try:
            if self._bg_context:
                self._bg_context.close()
            if self._bg_browser:
                self._bg_browser.close()
            if self._bg_pw:
                self._bg_pw.stop()
        except Exception as e:
            self.log.warning("Error closing background browser: %s", e)
        finally:
            self._bg_page = self._bg_context = self._bg_browser = self._bg_pw = None
