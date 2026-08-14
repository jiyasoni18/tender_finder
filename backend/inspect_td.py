import time
from playwright.sync_api import sync_playwright

print("Starting Playwright...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome", args=["--disable-blink-features=AutomationControlled"])
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    
    print("Navigating to TenderDetail login...")
    page.goto("https://www.tenderdetail.com/Account/LogOn")
    
    input("\n[1] Please log in to the website. Navigate to the Search page, then press ENTER here...")
    
    with open("td_search_page.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print("Saved Search page HTML to td_search_page.html")
    
    input("\n[2] Please perform a search, open a tender's details page, then press ENTER here...")
    
    with open("td_tender_details.html", "w", encoding="utf-8") as f:
        f.write(page.content())
    print("Saved Tender Details page HTML to td_tender_details.html")
    
    print("\nAll done! Closing browser...")
    browser.close()
