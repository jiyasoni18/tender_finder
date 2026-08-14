import sys
from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel='chrome', args=['--disable-blink-features=AutomationControlled'])
        page = browser.new_page()
        print('Navigating to anonymSearch.do...')
        page.goto('https://www.ireps.gov.in/epsn/anonymSearch.do')
        page.wait_for_timeout(2000)
        
        print('Clicking Custom Search...')
        try:
            # First try the Custom Search tab
            page.click('text="Custom Search"')
        except Exception as e:
            print("Failed to click Custom Search by text:", e)
        
        page.wait_for_timeout(2000)
        
        print('Setting Railway/PU to All...')
        try:
            page.locator('select[name="organization"]').select_option(label='Indian Railway')
            page.locator('select[name="railway"]').select_option(label='All')
        except Exception as e:
            print("Failed to set railway:", e)
        
        print('Setting Department to S AND T...')
        try:
            page.locator('select[name="department"]').select_option(label='S AND T')
        except Exception as e:
            print("Failed to set department:", e)
        
        print('Submitting search...')
        try:
            page.click('input[type="button"][value="Show Results"], button:has-text("Show Results"), text="Show Results"')
        except Exception as e:
            print("Failed to click Show Results:", e)
            
        page.wait_for_timeout(5000)
        
        html = page.content()
        with open('ireps_search_results.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print('Saved to ireps_search_results.html')

if __name__ == "__main__":
    test()
