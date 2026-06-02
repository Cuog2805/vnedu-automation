## Cài đặt (làm 1 lần)

```bash
pip install -r requirements.txt
playwright install chromium
```

## Thiết lập thông tin đăng nhập

1. Sao chép `.env.example` thành `.env`
2. Mở `.env`, điền URL / user / mật khẩu thật

## Tạo phiên đăng nhập (làm lại khi phiên hết hạn)

```bash
python scripts/save_login.py
```

Trình duyệt mở ra → đăng nhập thủ công (gõ cả captcha) → quay lại terminal
nhấn Enter. Phiên được lưu vào `auth_state.json`.

## Chạy test

```bash
pytest                       # chạy tất cả
pytest tests/test_tai_so_do.py   # chạy 1 file
pytest -k so_do              # chạy test có tên khớp "so_do"
```