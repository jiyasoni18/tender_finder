import json
import re
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.ireps.gov.in/epsn/anonymSearch.do", timeout=60000)
        
        # Click custom search tab
        page.locator("input[value='Custom Search']").click()
        page.wait_for_timeout(3000)
        
        # Enter tender number
        tender_no = "C-SG-C-36-5-242-2026-27"
        page.locator("input[name='tenderNo']").fill(tender_no)
        
        # Search
        page.locator("input[value='Show Results']").click()
        page.wait_for_timeout(3000)
        
        # Click view NIT icon - it usually has onclick="viewNIT(...)"
        # But we can just find the link with 'viewNIT'
        nit_link = page.locator("a[onclick*='viewNIT']").first
        if nit_link.count() > 0:
            onclick_val = nit_link.get_attribute("onclick")
            m = re.search(r"tenderAnonymsOid=([^&']+)", onclick_val)
            if m:
                nit_oid = m.group(1)
                nit_url = f"https://www.ireps.gov.in/epsn/nitViewAnonyms/rfq/nitPublish.do?tenderAnonymsOid={nit_oid}&activity=viewNIT"
                print(f"Found NIT URL: {nit_url}")
                
                nit_page = browser.new_page()
                nit_page.goto(nit_url, timeout=30000)
                
                # Find the Download Tender Doc button
                btns = nit_page.locator("*:has-text('Download Tender Doc')").all()
                for btn in btns:
                    try:
                        print("-------------")
                        print("TAG:", btn.evaluate("el => el.tagName"))
                        print("HTML:", btn.evaluate("el => el.outerHTML"))
                    except Exception as e:
                        pass
                
                nit_page.close()
            else:
                print("Could not extract OID from onclick:", onclick_val)
        else:
            print("Could not find viewNIT link in results")
            print("Page text:", page.locator("body").inner_text()[:1000])
            
        browser.close()

if __name__ == "__main__":
    run()
