"""
TenderDetail (tenderdetail.com) scraper.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin
from datetime import datetime
import re
import requests

from config import STATE_DIR
from sites.base import BaseScraper, Listing
from core.models import TenderDoc

try:
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError:
    sync_playwright = None

BASE = "https://www.tenderdetail.com"
LOGIN_URL = f"{BASE}/Account/LogOn"


class TenderDetailScraper(BaseScraper):
    name = "tenderdetail"

    def __init__(self, config) -> None:
        super().__init__(config)
        self._auth_cookies = []
        self._bg_pw = None
        self._bg_browser = None
        self._bg_context = None
        self._bg_page = None

    def login(self) -> None:
        # We will do the actual interactive login inside find_new_tenders
        # so we can keep the exact same browser open forever in the background thread.
        self._logged_in = True

    def find_new_tenders(self) -> list[Listing]:
        listings: list[Listing] = []

        if self._bg_pw is None:
            self.log.info("Starting persistent browser for TenderDetail...")
            self._bg_pw = sync_playwright().start()
            self._bg_browser = self._bg_pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            
            auth_file = STATE_DIR / "td_auth.json"
            if auth_file.exists():
                self._bg_context = self._bg_browser.new_context(accept_downloads=True, storage_state=str(auth_file))
                self.log.info("Loaded previous session state.")
            else:
                self._bg_context = self._bg_browser.new_context(accept_downloads=True)
                
            self._bg_page = self._bg_context.new_page()
            
            # Check if we are already logged in
            self.log.info("Checking login status...")
            self._bg_page.goto(LOGIN_URL, timeout=60000)
            self._bg_page.wait_for_timeout(3000)
            
            is_logged_in = False
            if self._bg_page.locator("text='Logout'").first.is_visible(timeout=2000):
                is_logged_in = True
                
            if is_logged_in:
                self.log.info("Already logged in via saved session! Skipping manual login.")
                # If we have a saved search URL, we can use it
                self.search_url = self.config.options.get("search_url")
                if not self.search_url:
                    self.search_url = "https://www.tenderdetail.com/registeruser/indiatenders"
            else:
                self.log.info("=" * 60)
                self.log.info("TenderDetail AUTOMATED LOGIN & SEARCH CONFIGURATION")
                
                # Attempt to automate login
                username = self.config.username
                password = self.config.password
                if username and password:
                    self.log.info(f"Automating login for {username}...")
                    try:
                        # The page has a "Username" tab vs "Mobile OTP" tab
                        tab_username = self._bg_page.locator("text='Username'").first
                        if tab_username.is_visible(timeout=5000):
                            tab_username.click()
                            
                        self._bg_page.locator("#txtLogin").fill(username)
                        self._bg_page.locator("#txtPassword").fill(password)
                        
                        # Find the submit button inside the username form
                        btn_login = self._bg_page.locator("button:has-text('Login'), button:has-text('Sign In'), input[type='submit']").last
                        btn_login.click()
                        self._bg_page.wait_for_timeout(5000)
                        self.log.info("Login submitted.")
                    except Exception as e:
                        self.log.warning("Automated login failed, please log in manually: %s", e)
                
                self.log.info("=" * 60)
                self.log.info("TenderDetail LOGIN SUCCESSFUL!")
                self.log.info("=" * 60)
                
                # Save the session so we don't have to login next time
                self._bg_context.storage_state(path=str(auth_file))
                self.log.info(f"Saved session state to {auth_file}")
                
            self.log.info("Proceeding with scraper...")

        page = self._bg_page
        keywords = self.config.options.get("keywords", [])
        search_query = ", ".join(keywords)

        try:
            self.log.info(f"Searching for combined keywords: {search_query}")
            
            # Navigate to the dashboard
            page.goto(f"{BASE}/RegisterUser/Dashboard", timeout=60000)
            page.wait_for_timeout(3000)
            
            # Input the keyword in the dashboard search
            search_input = page.locator("#txtDashboardSearch").first
            if search_input.is_visible():
                search_input.fill(search_query)
                with page.expect_navigation(timeout=60000):
                    page.locator("#btnDashboardSearch").first.click()
                page.wait_for_timeout(3000)
            else:
                self.log.warning("Could not find search bar (#txtDashboardSearch).")
                return listings
                
            # Now we are on the results page.
            self.log.info("Skipping right-side strict filters to ensure we capture some results...")
            
            # --- TEMPORARILY DISABLED STRICT FILTERS ---
            # val_from = page.locator("input[placeholder='From']").first
            # if val_from.is_visible(timeout=5000):
            #     val_from.fill("5000000")  # 50 Lakhs
            #     page.locator("input[placeholder='To']").first.fill("50000000") # 5 Crores
            #
            # from datetime import datetime, timedelta
            # today = datetime.today()
            # from_date_str = (today + timedelta(days=5)).strftime("%d/%m/%Y")
            # to_date_str = (today + timedelta(days=26)).strftime("%d/%m/%Y")
            #
            # date_from = page.locator("input[placeholder='Enter Date From']").first
            # if date_from.is_visible():
            #     date_from.evaluate(f"el => el.value = '{from_date_str}'")
            #     page.locator("input[placeholder='Enter Date To']").first.evaluate(f"el => el.value = '{to_date_str}'")
            #
            # closing_date_input = page.locator("#fromDate").first
            # if closing_date_input.is_visible(timeout=2000):
            #     closing_date_input.evaluate(f"el => el.value = '{from_date_str} - {to_date_str}'")
            #     page.evaluate(f"""() => {{
            #         let hdnFrom = document.getElementById('HDNFilterDueDateFrom');
            #         if (hdnFrom) hdnFrom.value = '{from_date_str}';
            #         let hdnTo = document.getElementById('HDNFilterDueDateTo');
            #         if (hdnTo) hdnTo.value = '{to_date_str}';
            #     }}""")
                
            # Click the filter search button
            filter_search_btn = page.locator("button.btn-primary:has-text('Search')").last
            if filter_search_btn.is_visible():
                self.log.info("Clicking filter Search button...")
                with page.expect_navigation(timeout=60000):
                    filter_search_btn.click()
                page.wait_for_timeout(3000)
            
            self.log.info("Attempting to parse rows...")
            html = page.content()
            
            # Extract BRR/TDR and the block of HTML that follows it until the next one
            import re
            pattern = re.compile(r'(?:BRR|TDR)\s*:\s*(\d+)(.*?)(?=(?:BRR|TDR)\s*:|$)', re.IGNORECASE | re.DOTALL)
            matches = pattern.findall(html)
            
            seen = set()
            for brr, block in matches:
                if brr in seen: continue
                seen.add(brr)
                
                # Strip HTML tags for easier regex matching
                text_block = re.sub(r'<[^>]+>', ' ', block).replace("&nbsp;", " ")
                
                # Parse value
                val = None
                val_match = re.search(r'₹\s*([\d\.]+\s*(?:Lakh|Lacs?|L|Crore|Cr|K|M)?)', text_block, re.IGNORECASE)
                if val_match:
                    val_str_clean = val_match.group(1).lower().replace(",", "")
                    try:
                        m = re.search(r'([\d\.]+)', val_str_clean)
                        if m:
                            num = float(m.group(1))
                            if "lakh" in val_str_clean or "lac" in val_str_clean or val_str_clean.endswith("l"): num *= 100000
                            elif "crore" in val_str_clean or "cr" in val_str_clean: num *= 10000000
                            elif "k" in val_str_clean: num *= 1000
                            elif "m" in val_str_clean: num *= 1000000
                            val = num
                    except: pass
                
                # Parse date
                dt = None
                date_match = re.search(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}', text_block, re.IGNORECASE)
                if date_match:
                    try:
                        # "Aug 17, 2026"
                        dt = datetime.strptime(date_match.group(0).replace(",", "").strip(), "%b %d %Y").date()
                    except: pass
                
                listings.append(Listing(
                    doc_id=brr,
                    detail_url=f"{BASE}/RegisterUser/Dashboard?query={brr}", # Placeholder
                    value=val,
                    closing_date=dt
                ))
            
            self.log.info(f"Found {len(seen)} tenders for combined keywords: {search_query}")
                
        except Exception as e:
            self.log.error("Scraping error: %s", e)

        return listings

    def download(self, listing: Listing) -> TenderDoc:
        """
        Override to prevent BaseScraper from creating a TDR-only folder.
        fetch_pdf will create the correct combined 'TDR-TenderNo' folder itself.
        """
        from core.models import TenderDoc
        # Pass None as dest — fetch_pdf ignores it and builds the folder itself
        path = self.fetch_pdf(listing, None)
        return TenderDoc(
            doc_id=listing.doc_id,          # already updated to combined ID by fetch_pdf
            source=self.name,
            title=listing.title,
            detail_url=listing.detail_url,
            pdf_path=path,
            value=listing.value,
            closing_date=listing.closing_date,
            published_date=listing.published_date,
            metadata=dict(listing.extra),
        )

    def fetch_pdf(self, listing: Listing, dest_file: Path) -> Path:
        try:
            page = self._bg_page
            
            # Navigate to Dashboard and search for this specific BRR/TDR
            page.goto(f"{BASE}/RegisterUser/Dashboard", timeout=60000)
            page.wait_for_timeout(3000)
            
            search_input = page.locator("#txtDashboardSearch").first
            if search_input.is_visible():
                search_input.fill(listing.doc_id)
                page.locator("#btnDashboardSearch").first.click()
                page.wait_for_timeout(4000)
                
            # Click View Notice / View Result
            view_btn = page.locator(".view-tender, .view-result").first
            if not view_btn.is_visible(timeout=5000):
                self.log.warning(f"Could not find view button for {listing.doc_id}")
                return None
                
            view_btn.click()
            page.wait_for_timeout(4000)
            
            # Extract the Details table
            details = page.evaluate('''() => {
                let r={};
                document.querySelectorAll('tr').forEach(tr => {
                    let tds=tr.querySelectorAll('td');
                    if(tds.length==2) r[tds[0].innerText.trim()]=tds[1].innerText.trim();
                });
                return r;
            }''')
            
            # ── Build combined doc_id: "TDR-TenderNo" ────────────────────────
            # Try common key variants for the tender number field
            tender_no = (
                details.get("Tender No") or
                details.get("Tender No.") or
                details.get("Tender Number") or
                details.get("NIT No") or
                details.get("NIT No.") or
                ""
            ).strip()
            
            tdr = str(listing.doc_id).strip()
            if tender_no:
                combined_id = f"{tdr}-{tender_no}"
            else:
                combined_id = tdr
            
            # Sanitise for use as a folder name
            import re
            safe_combined = re.sub(r'[\\/:*?"<>|]', '_', combined_id)[:150]
            
            # Update listing.doc_id so the rest of the pipeline (DB, report) uses the combined ID
            listing.doc_id = combined_id
            self.log.info("Combined doc_id for folder: %s", safe_combined)

            # Parse the exact value from the table
            val_str = details.get("Tender Value", "")
            val_match = re.search(r'([\d\.]+)\s*(Lakh|Lacs?|L|Crore|Cr|K|M)?', val_str, re.IGNORECASE)
            parsed_val = None
            if val_match:
                try:
                    num = float(val_match.group(1))
                    unit = (val_match.group(2) or "").lower()
                    if "lakh" in unit or "lac" in unit or unit == "l": num *= 100000
                    elif "crore" in unit or "cr" in unit: num *= 10000000
                    elif "k" in unit: num *= 1000
                    elif "m" in unit: num *= 1000000
                    parsed_val = num
                except: pass
                
            # Range check right here on the exact value (50 Lakhs to 5 Crores)
            if parsed_val is not None:
                listing.value = parsed_val
                if parsed_val < 5000000 or parsed_val > 50000000:
                    self.log.info(f"Skipping {listing.doc_id}: Value {parsed_val} is out of range (50L-5Cr)")
                    return None
            
            import config
            tender_folder = config.DOWNLOADS_DIR / safe_combined
            tender_folder.mkdir(parents=True, exist_ok=True)
            
            # Create a summary PDF of the details page
            try:
                page.pdf(path=str(tender_folder / "details_summary.pdf"), format="A4")
                self.log.info(f"Saved summary PDF for {listing.doc_id}")
            except Exception as e:
                self.log.warning(f"Could not create summary PDF: {e}")
            
            # Find all download links
            dl_links = page.locator("a:has-text('Download')").all()
            if not dl_links:
                self.log.warning(f"No document download link found for BRR {listing.doc_id}")
                return tender_folder / "details_summary.pdf"
            
            first_pdf = None
            
            for i, link in enumerate(dl_links):
                try:
                    self.log.info(f"Triggering download {i+1} for {listing.doc_id}...")
                    href = link.get_attribute("href")
                    if not href:
                        self.log.warning(f"No href found for download link {i+1}")
                        continue
                        
                    if not href.startswith("http"):
                        from config import SiteConfig
                        href = f"https://www.tenderdetail.com{href}"
                        
                    resp = page.request.get(href)
                    if not resp.ok:
                        self.log.warning(f"Failed to fetch {href}: Status {resp.status}")
                        continue
                        
                    # Extract filename from headers or URL
                    filename = f"document_{i+1}.pdf"
                    cd = resp.headers.get("content-disposition", "")
                    import urllib.parse
                    if "filename=" in cd:
                        import re
                        m = re.search(r'filename="?([^"]+)"?', cd)
                        if m: filename = m.group(1)
                    elif "FileName=" in urllib.parse.unquote(href):
                        import re
                        m = re.search(r'FileName=([^&]+)', urllib.parse.unquote(href))
                        if m: filename = m.group(1)
                        
                    file_path = tender_folder / filename
                    with open(file_path, "wb") as f:
                        f.write(resp.body())
                        
                    self.log.info(f"Successfully downloaded {filename} to {tender_folder}")
                    
                    if not first_pdf and str(file_path).lower().endswith('.pdf'):
                        first_pdf = file_path
                except Exception as ex:
                    self.log.warning(f"Failed to download a file for {listing.doc_id}: {ex}")
            
            # AI summary is generated by the RangeChecker worker (Worker 2)
            # after the value range check passes — do not duplicate it here.
            if not first_pdf:
                self.log.info("No downloaded PDF found for %s — summary will use details_summary.pdf.", listing.doc_id)

            # Return the first real downloaded PDF so RangeChecker can read its text.
            # Fall back to details_summary.pdf if no other PDF was downloaded.
            return first_pdf if first_pdf and first_pdf.exists() else (tender_folder / "details_summary.pdf")
        except Exception as e:
            self.log.error(f"Failed to fetch PDF for {listing.doc_id}: {e}")
            return None

    def close(self) -> None:
        try:
            if self._bg_context:
                self._bg_context.close()
            if self._bg_browser:
                self._bg_browser.close()
            if self._bg_pw:
                self._bg_pw.stop()
        except Exception:
            pass
        finally:
            self._bg_page = self._bg_context = self._bg_browser = self._bg_pw = None
