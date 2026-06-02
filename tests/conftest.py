import os
import pytest
from dotenv import load_dotenv

# Nạp các biến trong file .env vào môi trường (chỉ cho máy local).
load_dotenv()


def pytest_addoption(parser):
    parser.addoption(
        "--school-code",
        action="store",
        default=None,
        help="Mã trường VNEDU dùng cho test chức năng đồng bộ.",
    )
    parser.addoption(
        "--semester",
        action="store",
        default=None,
        help="Học kỳ dùng cho đồng bộ KQHT/Y tế: gk1, hk1, gk2, hk2 hoặc cn.",
    )


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    screenshot_path = os.getenv("VNEDU_SCREENSHOT_PATH")
    page = item.funcargs.get("page")
    if not screenshot_path or page is None:
        return

    try:
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        page.screenshot(path=screenshot_path, full_page=False)
    except Exception as exc:
        report.sections.append(("screenshot", f"Không chụp được ảnh lỗi: {exc}"))


@pytest.fixture(scope="session")
def school_code(pytestconfig):
    """
    Mã trường cần test đồng bộ.

    Tester nhập thủ công khi chạy test bằng:
        pytest tests/test_dong_bo.py --school-code=4141437402

    Có thể dùng biến môi trường VNEDU_SCHOOL_CODE nếu muốn lưu sẵn trong .env.
    """
    value = pytestconfig.getoption("--school-code") or os.getenv("VNEDU_SCHOOL_CODE")
    if not value:
        pytest.fail(
            "Thiếu mã trường cần test. Hãy chạy: "
            "pytest tests/test_dong_bo.py --school-code=<ma_truong>"
        )
    return value.strip()


@pytest.fixture(scope="session")
def semester(pytestconfig):
    """
    Học kỳ/Giai đoạn dùng cho đồng bộ KQHT/Y tế.

    Giá trị hợp lệ:
        gk1 -> Giữa học kỳ 1
        hk1 -> Cuối học kỳ 1/Học kỳ 1
        gk2 -> Giữa học kỳ 2
        hk2 -> Cuối học kỳ 2/Học kỳ 2
        cn  -> Cả năm

    Nếu không truyền, test sẽ đọc và chạy tất cả option hiện có trong modal.
    """
    value = pytestconfig.getoption("--semester") or os.getenv("VNEDU_SEMESTER")
    if not value:
        return None

    value = value.strip().lower()
    if value not in {"gk1", "hk1", "gk2", "hk2", "cn"}:
        pytest.fail(
            "Học kỳ không hợp lệ. Dùng một trong các giá trị: gk1, hk1, gk2, hk2, cn."
        )
    return value
