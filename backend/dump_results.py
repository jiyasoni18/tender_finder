from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp("http://localhost:9222")
        
        search_page = None
        for context in browser.contexts:
            for page in context.pages:
                if "ireps.gov.in" in page.url:
                    search_page = page
                    break
            if search_page:
                break
                
        if not search_page:
            print("Could not find IREPS page")
            return
            
        print("Clicking Show Results...")
        search_page.locator("input[value='Show Results'], button:has-text('Show results'), input[value='Show results']").first.click()
        search_page.wait_for_timeout(5000)
        
        print("Dumping results HTML...")
        with open("ireps_real_results.html", "w", encoding="utf-8") as f:
            f.write(search_page.content())
            
        print("Done!")
        browser.close()

if __name__ == "__main__":
    main()
