# crawl/session_store.py
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

CSDL_BASE_URL = "https://dongbo.csdl.edu.vn"

# File lưu storage_state (cookie + localStorage) sau khi đăng nhập thủ công.
# Cùng pattern với auth_state.json của VNEDU.
CSDL_AUTH_STATE_PATH = ROOT_DIR / "csdl_auth_state.json"


def load_session_cookie() -> str:
    """
    Đọc cookie từ file csdl_auth_state.json và trả về cookie string
    đúng format để gắn vào request header.

    Raises:
        FileNotFoundError: nếu chưa chạy save_csdl_login.py.
        ValueError: nếu file không chứa cookie hợp lệ.
    """
    import json

    if not CSDL_AUTH_STATE_PATH.exists():
        raise FileNotFoundError(
            f"Chưa có file phiên đăng nhập CSDL: {CSDL_AUTH_STATE_PATH}\n"
            "Hãy chạy: python scripts/save_csdl_login.py"
        )

    state = json.loads(CSDL_AUTH_STATE_PATH.read_text(encoding="utf-8"))
    cookies: list[dict] = state.get("cookies", [])

    # Lọc cookie thuộc domain csdl.edu.vn
    relevant = [
        c for c in cookies
        if "csdl.edu.vn" in c.get("domain", "")
        or "dongbo" in c.get("domain", "")
    ]

    if not relevant:
        raise ValueError(
            "File csdl_auth_state.json không chứa cookie hợp lệ cho dongbo.csdl.edu.vn.\n"
            "Hãy chạy lại: python scripts/save_csdl_login.py"
        )

    # Ưu tiên BIGip trước, laravel_session sau — đúng thứ tự browser gửi
    bigip = [c for c in relevant if "BIGip" in c.get("name", "")]
    session = [c for c in relevant if c.get("name") == "laravel_session"]
    others = [
        c for c in relevant
        if "BIGip" not in c.get("name", "") and c.get("name") != "laravel_session"
    ]

    ordered = bigip + others + session
    return "; ".join(f"{c['name']}={c['value']}" for c in ordered)


def is_session_available() -> bool:
    """Kiểm tra nhanh file session có tồn tại không (không validate nội dung)."""
    return CSDL_AUTH_STATE_PATH.exists()
