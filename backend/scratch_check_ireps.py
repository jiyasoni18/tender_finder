import json
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.ireps.gov.in/epsn/anonymSearch.do", timeout=60000)
        
        # Click custom search tab - try multiple selectors just like the main scraper
        for locator_str in [
            "input[value='Custom Search']",
            "input[value='customSearch']",
            "text='Custom Search'",
            "a:has-text('Custom Search')",
            "td:has-text('Custom Search')",
        ]:
            try:
                el = page.locator(locator_str).first
                if el.is_visible(timeout=5000):
                    el.click()
                    break
            except:
                pass
                
        page.wait_for_timeout(5000)
        
        # Get all select elements and print their name and id
        selects = page.locator("select").all()
        print(f"Found {len(selects)} select elements:")
        for sel in selects:
            name = sel.get_attribute("name")
            id_attr = sel.get_attribute("id")
            
            # Print out the first few options to help identify it
            opts = sel.locator("option").all()
            opt_texts = [o.inner_text().strip() for o in opts[:5]]
            
            print(f"Select -> name: '{name}', id: '{id_attr}', options: {opt_texts}")
            
        browser.close()

if __name__ == "__main__":
    run()
