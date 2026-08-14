from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        print("Navigating to guest search...")
        # Use wait_until="domcontentloaded" to avoid timeout if some resources hang
        try:
            page.goto("https://www.ireps.gov.in/epsn/anonymSearch.do", timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            print("Goto warning:", e)
            
        page.wait_for_timeout(5000)
        
        print("Clicking Custom Search tab...")
        try:
            # Let's try multiple ways to click it
            el = page.locator("td.tab, div.tab, li.tab").filter(has_text="Custom Search").first
            if el.count() > 0:
                print("Found tab by class, clicking...")
                el.click()
            else:
                print("Trying generic text click...")
                page.get_by_text("Custom Search", exact=True).first.click()
        except Exception as e:
            print("Click error:", e)
            
        page.wait_for_timeout(5000)
        
        print("Dumping HTML...")
        with open("ireps_custom_tab.html", "w", encoding="utf-8") as f:
            f.write(page.content())
            
        print("Done.")

if __name__ == "__main__":
    main()
