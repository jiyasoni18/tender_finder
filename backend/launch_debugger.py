import time
from playwright.sync_api import sync_playwright

def main():
    print("Starting Playwright with remote debugging on port 9222...")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--remote-debugging-port=9222",
                "--disable-blink-features=AutomationControlled"
            ]
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.ireps.gov.in/epsn/anonymSearch.do")
        
        print("\n" + "="*60)
        print("BROWSER IS READY!")
        print("1. Please login normally with OTP.")
        print("2. Wait until you see the Search page.")
        print("3. LEAVE THE BROWSER OPEN and LEAVE THIS TERMINAL RUNNING.")
        print("4. Tell me in the chat when you are logged in!")
        print("="*60 + "\n")
        
        # Keep the script running forever so the browser stays open
        while True:
            time.sleep(1)

if __name__ == "__main__":
    main()
