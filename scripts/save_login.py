"""
save_login.py — CHẠY TAY MỘT LẦN để tạo phiên đăng nhập cho test.

Vì sao cần file này:
  Hệ thống có captcha, không tự vượt được (và cũng không nên cố).
  Nên ta đăng nhập THỦ CÔNG một lần ở đây — bạn tự gõ captcha bằng mắt —
  rồi lưu cookie/session ra auth_state.json. Sau đó các test tái dùng file
  đó và KHÔNG cần đăng nhập lại, cũng không cần input() trong test.

Cách dùng:
  1. Đảm bảo đã tạo file .env (sao từ .env.example) và điền thông tin.
  2. Chạy:  python scripts/save_login.py
  3. Cửa sổ trình duyệt mở ra -> đăng nhập thủ công (gõ cả captcha).
  4. Quay lại terminal, nhấn Enter -> phiên được lưu vào auth_state.json.

Khi nào phiên hết hạn (test bị bắt đăng nhập lại), chỉ cần chạy lại file này.
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
