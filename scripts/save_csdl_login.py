import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from playwright.sync_api import sync_playwright
from crawl.session_store import CSDL_AUTH_STATE_PATH, CSDL_BASE_URL


def main():
    print(f"Opening browser: {CSDL_BASE_URL}")
    print("Log in manually in the browser window.")
    print("After the page has loaded, press Enter here or send /login_done in Telegram.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(CSDL_BASE_URL, wait_until="domcontentloaded", timeout=30_000)

        input("\n>>> Login complete. Press Enter to save session...")

        context.storage_state(path=str(CSDL_AUTH_STATE_PATH))
        print(f"\nSaved session to: {CSDL_AUTH_STATE_PATH}")
        print("You can now run crawl or use /crawl in Telegram.")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
