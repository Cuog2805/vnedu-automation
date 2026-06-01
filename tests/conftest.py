"""
conftest.py — pytest tự động nạp file này, không cần import.
Đây là nơi đặt các "fixture": những mảnh thiết lập dùng chung cho nhiều test.

Hai vấn đề lớn mà file này giải quyết:
  1. Đọc cấu hình (URL, user, mật khẩu) từ biến môi trường — KHÔNG hardcode.
  2. Đăng nhập MỘT LẦN rồi tái dùng phiên cho mọi test — thay cho input() thủ công.
"""
import os
import pytest
from dotenv import load_dotenv

# Nạp các biến trong file .env vào môi trường (chỉ cho máy local).
load_dotenv()


# ---------------------------------------------------------------------------
# Fixture cấu hình: gom thông tin từ .env vào một chỗ.
# scope="session" = chỉ chạy 1 lần cho cả phiên test, không lặp lại mỗi test.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def config():
    cfg = {
        "base_url": os.getenv("VNEDU_BASE_URL"),
        "username": os.getenv("VNEDU_USERNAME"),
        "password": os.getenv("VNEDU_PASSWORD"),
    }
    # Kiểm tra sớm: thiếu config thì báo lỗi rõ ràng thay vì để test chết khó hiểu.
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        pytest.fail(
            f"Thiếu biến môi trường: {missing}. "
            f"Hãy sao chép .env.example thành .env và điền thông tin."
        )
    return cfg


# ---------------------------------------------------------------------------
# Fixture đăng nhập tái dùng phiên — KỸ THUẬT QUAN TRỌNG NHẤT của file này.
#
# Ý tưởng: đăng nhập tốn thời gian (và có captcha). Ta KHÔNG muốn đăng nhập
# lại ở mỗi test. Giải pháp chuẩn của Playwright là "storage state":
#   - Lần đầu: đăng nhập, rồi LƯU cookie/session ra file auth_state.json.
#   - Các lần sau: nạp thẳng file đó -> vào hệ thống mà không cần đăng nhập lại.
#
# Vì hệ thống này có CAPTCHA (không tự vượt được, và cũng không nên),
# bước tạo auth_state.json ta làm THỦ CÔNG MỘT LẦN bằng script riêng
# (xem file scripts/save_login.py). Sau đó test cứ tái dùng file đó.
# ---------------------------------------------------------------------------
AUTH_STATE_PATH = "auth_state.json"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """
    Ghi đè fixture mặc định của pytest-playwright để mọi context
    tự nạp sẵn trạng thái đăng nhập (nếu file tồn tại).
    """
    if os.path.exists(AUTH_STATE_PATH):
        return {**browser_context_args, "storage_state": AUTH_STATE_PATH}
    return browser_context_args


@pytest.fixture
def logged_in_page(page, config):
    """
    Trả về một 'page' đã ở trạng thái đăng nhập, sẵn sàng để test.

    Nếu chưa có auth_state.json, fixture sẽ dừng test và nhắc bạn
    chạy script tạo phiên trước — thay vì âm thầm chạy rồi fail khó hiểu.
    """
    if not os.path.exists(AUTH_STATE_PATH):
        pytest.skip(
            "Chưa có auth_state.json. Hãy chạy: python scripts/save_login.py "
            "để đăng nhập 1 lần và lưu phiên, rồi chạy lại test."
        )
    page.goto(config["base_url"])
    return page
