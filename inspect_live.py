from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as pw:
        print("Connecting to live browser...")
        browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        
        # Find the search page
        search_page = None
        for context in browser.contexts:
            for page in context.pages:
                if "ireps.gov.in" in page.url:
                    search_page = page
                    break
            if search_page:
                break
                
        if not search_page:
            print("Could not find IREPS page! Available pages:")
            for context in browser.contexts:
                for page in context.pages:
                    print(" -", page.url)
            return
            
        print("Found page:", search_page.url)
        
        print("Trying to click Custom Search tab...")
        try:
            clicked = False
            for locator_str in [
                "text='Custom Search'",
                "input[value='Custom Search']",
                "input[value='customSearch']",
                "a:has-text('Custom Search')",
                "td:has-text('Custom Search')",
            ]:
                el = search_page.locator(locator_str).first
                if el.is_visible(timeout=2000):
                    print(f"Found tab using {locator_str}, clicking...")
                    el.click()
                    clicked = True
                    break
            if not clicked:
                print("Warning: Could not find the Custom Search tab to click!")
        except Exception as e:
            print("Click error:", e)
            
        print("Waiting 5 seconds for form to load...")
        search_page.wait_for_timeout(5000)
        
        print("Taking screenshot...")
        search_page.screenshot(path="live_debug.png", full_page=True)
        
        print("Dumping HTML...")
        with open("live_debug.html", "w", encoding="utf-8") as f:
            f.write(search_page.content())
            
        print("Done!")
        browser.close()

if __name__ == "__main__":
    main()
