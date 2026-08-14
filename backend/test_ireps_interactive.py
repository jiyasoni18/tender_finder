import sys
from playwright.sync_api import sync_playwright

def test():
    print("Starting Playwright...")
    with sync_playwright() as p:
        # Launch Chrome visibly
        browser = p.chromium.launch(headless=False, channel='chrome', args=['--disable-blink-features=AutomationControlled'])
        page = browser.new_page()
        
        print("Navigating to IREPS...")
        page.goto('https://www.ireps.gov.in/epsn/anonymSearch.do')
        
        # Pause for the user
        print("="*60)
        print("BROWSER OPEN. Please interact with the browser.")
        print("Do your login or Custom Search manually right now.")
        print("Once the results table is visible, come back here and press ENTER.")
        print("="*60)
        
        input("Press ENTER to continue and scrape the table...")
        
        print("Scraping results...")
        try:
            rows = page.locator("table tr:has(td)").all()
            print(f"Found {len(rows)} table rows.")
            for row in rows[:5]: # just print first 5
                cells = row.locator("td").all()
                if len(cells) >= 5:
                    tender_no = cells[1].inner_text().strip()
                    title = cells[2].inner_text().strip()
                    print(f"Found Tender: {tender_no} - {title[:30]}...")
                    
                    # Try to find a PDF link in the row
                    links = row.locator("a").all()
                    for link in links:
                        href = link.get_attribute("href")
                        print(f"  Link found: {href}")
        except Exception as e:
            print("Error scraping:", e)
            
        print("Test complete.")

if __name__ == "__main__":
    test()
