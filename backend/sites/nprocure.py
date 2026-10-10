import re
import urllib.parse
from pathlib import Path
from typing import Iterator

from playwright.sync_api import sync_playwright

from sites.base import BaseScraper, Listing
import app.core.config as config

class NprocureScraper(BaseScraper):
    name = "nprocure"

    def login(self) -> None:
        pass  # No explicit login required for public search

    def find_new_tenders(self) -> list[Listing]:
        listings = []
        with sync_playwright() as p:
            # Force headless=False so the user can see what's happening!
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()

            try:
                self.log.info("Navigating to nProcure homepage...")
                page.goto("https://tender.nprocure.com/", timeout=60000)
            except Exception as e:
                self.log.error("Failed to load nProcure homepage: %s", e)
                browser.close()
                return []

            client_name = self.config.options.get("client_name", "Surat Municipal Corporation")
            self.log.info("Selecting Client Name: %s", client_name)

            try:
                # Find the client dropdown
                client_select = page.locator("select").filter(has=page.locator("option", has_text=client_name)).first
                client_select.wait_for(timeout=10000)
                
                # The label on the website often has a count appended, e.g. "Surat Municipal Corporation (5)"
                # So we find the option by partial text and get its exact value to select it.
                opt = client_select.locator(f"option:has-text('{client_name}')").first
                val = opt.get_attribute("value")
                client_select.select_option(value=val)
            except Exception as e:
                self.log.warning("Failed to select client %s: %s", client_name, e)
                browser.close()
                return []

            try:
                self.log.info("Clicking GO TO SUBDOMAIN...")
                with context.expect_page(timeout=20000) as new_page_info:
                    # Click GO TO SUBDOMAIN button
                    page.locator("*:has-text('GO TO SUBDOMAIN'), input[value*='SUBDOMAIN'], a:has-text('SUBDOMAIN')").last.click()
                
                sub_page = new_page_info.value
                sub_page.wait_for_load_state("domcontentloaded")
            except Exception as e:
                self.log.error("Failed to open subdomain page: %s", e)
                browser.close()
                return []

            self.log.info("Opened subdomain page: %s", sub_page.url)

            # Look for Search / Advanced Search button to find tenders
            try:
                search_btn = sub_page.locator("a:has-text('Advanced Search'), a:has-text('Search'), button:has-text('Search'), input[value='Search']").first
                if search_btn.is_visible(timeout=5000):
                    self.log.info("Clicking Search button on subdomain...")
                    search_btn.click()
                    sub_page.wait_for_load_state("domcontentloaded")
            except Exception:
                self.log.info("No explicit Search button clicked; continuing to look for tables.")

            page_num = 1
            while page_num <= 5: # Limit to 5 pages
                self.log.info("Parsing page %d...", page_num)
                # Let's find the largest table on the page
                tables = sub_page.locator("table").all()
                target_table = None
                max_rows = 0
                for t in tables:
                    try:
                        rows = t.locator("tr").count()
                        if rows > max_rows:
                            max_rows = rows
                            target_table = t
                    except Exception:
                        pass

                if not target_table or max_rows < 2:
                    self.log.error("Could not find a tender table with enough rows on page %d.", page_num)
                    break

                self.log.info("Found tender table with %d rows.", max_rows)

                rows = target_table.locator("tr").all()
                
                for idx, row in enumerate(rows):
                    if idx == 0:
                        continue # header row

                    try:
                        cells = row.locator("td, th").all()
                        if len(cells) < 2:
                            continue

                        # Second column contains the "Tender Brief"
                        brief_text = cells[1].inner_text().strip()
                        
                        # Extract fields using regex based on user screenshot
                        tender_id_match = re.search(r"Tender Id\s*:\s*(\d+)", brief_text, re.I)
                        tender_id = tender_id_match.group(1) if tender_id_match else f"NPROCURE-{page_num}-{idx}"

                        name_match = re.search(r"Name Of Work\s*:(.*?)(?=\n|Estimated|$)", brief_text, re.S | re.I)
                        title = name_match.group(1).strip() if name_match else "Unknown Title"

                        value_match = re.search(r"Estimated Contract Value\s*:\s*([\d\.,]+)", brief_text, re.I)
                        val_float = None
                        if value_match:
                            try:
                                clean_val = value_match.group(1).replace(",", "")
                                val_float = float(clean_val)
                            except ValueError:
                                pass

                        date_match = re.search(r"Last Date & Time For Submission\s*:\s*(\d{2}-\d{2}-\d{4})", brief_text, re.I)
                        closing_date_obj = None
                        if date_match:
                            closing_date_obj = config.parse_date(date_match.group(1))
                        
                        # The user requested: "make a gap of 10 days from today .... for the closing date."
                        if closing_date_obj:
                            import datetime
                            delta = (closing_date_obj - datetime.date.today()).days
                            if delta > 10:
                                self.log.info("Skipping tender %s: closing date (%s) is > 10 days from today", tender_id, closing_date_obj)
                                continue

                        # Look for links in the row
                        links = row.locator("a").all()
                        url = sub_page.url
                        for link in links:
                            href = link.get_attribute("href")
                            if href and "javascript" not in href:
                                url = urllib.parse.urljoin(sub_page.url, href)
                                break
                        
                        listing = Listing(
                            doc_id=tender_id[:100],
                            title=title[:300],
                            detail_url=url,
                            value=val_float,
                            closing_date=closing_date_obj,
                            extra={"raw_text": brief_text}
                        )
                        
                        self.log.info("Found tender: %s | Value: %s | Closing: %s", listing.doc_id, listing.value, listing.closing_date)
                        listings.append(listing)
                    except Exception as e:
                        self.log.warning("Failed to parse row %d: %s", idx, e)

                # Try to go to next page
                try:
                    next_btn = sub_page.locator("a:has-text('Next'), a:has-text('>>')").first
                    if next_btn.is_visible(timeout=3000):
                        self.log.info("Clicking Next page...")
                        next_btn.click()
                        sub_page.wait_for_load_state("domcontentloaded")
                        sub_page.wait_for_timeout(3000)
                        page_num += 1
                    else:
                        break
                except Exception:
                    break

            # Stay open just a little bit so user can see it finish
            sub_page.wait_for_timeout(2000)
            browser.close()
            
        return listings

    def fetch_pdf(self, listing: Listing, dest: Path) -> Path:
        """
        NProcure specific document download logic.
        This opens a fresh headless browser, searches for the tender, clicks into it,
        and downloads both the Procurement Summary PDF and any attached tender documents.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = browser.new_context(ignore_https_errors=True, accept_downloads=True)
            page = context.new_page()
            
            try:
                self.log.info("fetch_pdf: Navigating to nProcure for %s", listing.doc_id)
                page.goto("https://tender.nprocure.com/", timeout=60000)
                client_name = self.config.options.get("client_name", "Surat Municipal Corporation")
                
                # Select client
                client_select = page.locator("select").filter(has=page.locator("option", has_text=client_name)).first
                client_select.wait_for(timeout=10000)
                opt = client_select.locator(f"option:has-text('{client_name}')").first
                client_select.select_option(value=opt.get_attribute("value"))
                
                # Go to subdomain
                with context.expect_page(timeout=20000) as new_page_info:
                    page.locator("*:has-text('GO TO SUBDOMAIN'), input[value*='SUBDOMAIN'], a:has-text('SUBDOMAIN')").last.click()
                sub_page = new_page_info.value
                sub_page.wait_for_load_state("domcontentloaded")
                
                # Click Search
                search_btn = sub_page.locator("a:has-text('Advanced Search'), a:has-text('Search'), button:has-text('Search'), input[value='Search']").first
                if search_btn.is_visible(timeout=5000):
                    search_btn.click()
                    sub_page.wait_for_load_state("domcontentloaded")

                # Loop pages until we find the tender row
                found_row = None
                for page_num in range(1, 11): # search up to 10 pages
                    rows = sub_page.locator("table tr").all()
                    for row in rows:
                        if listing.doc_id in row.inner_text():
                            found_row = row
                            break
                    
                    if found_row:
                        break
                        
                    try:
                        next_btn = sub_page.locator("a:has-text('Next'), a:has-text('>>')").first
                        if next_btn.is_visible(timeout=2000):
                            next_btn.click()
                            sub_page.wait_for_load_state("domcontentloaded")
                            sub_page.wait_for_timeout(2000)
                        else:
                            break
                    except Exception:
                        break
                        
                if not found_row:
                    self.log.error("Could not find tender %s to download docs.", listing.doc_id)
                    txt = dest.with_suffix(".txt")
                    txt.write_text(f"Could not find tender {listing.doc_id} on search pages.")
                    return txt

                self.log.info("Found tender %s on search page. Opening details popup...", listing.doc_id)

                # Click Name Of Work (usually the first link in the row)
                link = found_row.locator("a").first
                with context.expect_page(timeout=20000) as popup_info:
                    link.click()
                popup = popup_info.value
                popup.wait_for_load_state("domcontentloaded")
                
                summary_pdf = dest.parent / f"{listing.doc_id}_Summary.pdf"
                
                # 1. Download EXPORT TO PDF
                try:
                    export_btn = popup.locator("#btnPdfId, button:has-text('EXPORT TO PDF'), a:has-text('EXPORT TO PDF')").first
                    if export_btn.is_visible(timeout=5000):
                        self.log.info("Clicking EXPORT TO PDF...")
                        with popup.expect_download(timeout=60000) as dl_info:
                            export_btn.click()
                        dl = dl_info.value
                        dl.save_as(summary_pdf)
                        self.log.info("Downloaded Summary PDF: %s", summary_pdf.name)
                except Exception as e:
                    self.log.warning("Failed to download Summary PDF: %s", e)

                # 2. Download attached documents
                try:
                    docs = popup.locator("a[href*='/common/download']").all()
                    if docs:
                        self.log.info("Found %d attached documents.", len(docs))
                        for doc in docs:
                            with popup.expect_download(timeout=60000) as dl_info:
                                doc.click()
                            dl = dl_info.value
                            doc_path = dest.parent / dl.suggested_filename
                            dl.save_as(doc_path)
                            self.log.info("Downloaded attached doc: %s", dl.suggested_filename)
                except Exception as e:
                    self.log.warning("Failed to download attached docs: %s", e)

                if summary_pdf.exists():
                    return summary_pdf
                else:
                    txt = dest.with_suffix(".txt")
                    txt.write_text(f"Docs downloaded for {listing.doc_id}")
                    return txt
                    
            except Exception as e:
                self.log.error("fetch_pdf failed for %s: %s", listing.doc_id, e)
            finally:
                browser.close()
                
        txt = dest.with_suffix(".txt")
        txt.write_text(f"Fallback for {listing.doc_id}")
        return txt
