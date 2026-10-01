from playwright.sync_api import sync_playwright
import time
import json
from datetime import datetime, timedelta

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://ireps.gov.in/epsn/anonymSearch.do")
        page.wait_for_timeout(2000)
        
        # Click custom search
        for locator_str in [
            "input[value='Custom Search']",
            "input[value='customSearch']",
            "text='Custom Search'"
        ]:
            el = page.locator(locator_str).first
            if el.is_visible(timeout=2000):
                el.click()
                break
        
        page.wait_for_timeout(2000)
        
        # Set dates to avoid timeout
        today = datetime.today()
        from_date = (today + timedelta(days=5)).strftime("%d/%m/%Y")
        to_date = (today + timedelta(days=26)).strftime("%d/%m/%Y")
        page.locator("input[name='dateFrom']").first.evaluate(f"el => el.value = '{from_date}'")
        page.locator("input[name='dateTo']").first.evaluate(f"el => el.value = '{to_date}'")
        
        # Click show results
        page.locator("input[value='Show Results'], button:has-text('Show results'), input[value='Show results']").first.click()
        page.wait_for_timeout(5000)
        
        rows = page.locator("table tr").all()
        out = []
        for r in rows[:10]:
            cells = r.locator("td").all_inner_texts()
            if cells:
                out.append(cells)
                
        with open("ireps_table_dump.json", "w") as f:
            json.dump(out, f, indent=2)
            
        browser.close()

if __name__ == "__main__":
    run()
