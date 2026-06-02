"""
save_login.py — CHẠY TAY MỘT LẦN để tạo phiên đăng nhập cho test.
"""
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BASE_URL = os.getenv("VNEDU_BASE_URL")
AUTH_STATE_PATH = "auth_state.json"


def main():
    if not BASE_URL:
        raise SystemExit("Thiếu VNEDU_BASE_URL trong .env")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL)

        print("\n=== Đăng nhập thủ công trong cửa sổ trình duyệt (gõ cả captcha) ===")
        input(">>> Đăng nhập xong rồi nhấn Enter ở đây để lưu phiên...")

        # Lưu toàn bộ cookie + localStorage hiện tại ra file.
        context.storage_state(path=AUTH_STATE_PATH)
        print(f"Đã lưu phiên vào {AUTH_STATE_PATH}. Giờ có thể chạy test.")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
