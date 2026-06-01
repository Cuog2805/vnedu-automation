# Bộ test Playwright — chức năng Tải sơ đồ tổ chức

Khung test mẫu để học kiểm thử web bài bản với pytest + Playwright.

## Cấu trúc

```
vnedu-tests/
├── pytest.ini            # cấu hình pytest
├── requirements.txt      # thư viện cần cài
├── .env.example          # mẫu biến môi trường (KHÔNG chứa mật khẩu thật)
├── .gitignore            # chặn .env, auth_state.json... khỏi bị đẩy lên git
├── scripts/
│   └── save_login.py     # chạy TAY 1 lần: đăng nhập + lưu phiên
└── tests/
    ├── conftest.py       # fixture dùng chung (config, đăng nhập)
    ├── test_tai_so_do.py # bài test thật, có assertion
    └── pages/
        └── so_do_page.py # Page Object: gom selector của 1 trang
```

## Cài đặt (làm 1 lần)

```bash
pip install -r requirements.txt
playwright install chromium
```

## Thiết lập thông tin đăng nhập

1. Sao chép `.env.example` thành `.env`
2. Mở `.env`, điền URL / user / mật khẩu thật
   (file `.env` đã được `.gitignore` chặn, không lo lộ lên git)

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

## Vì sao thiết kế như vậy (phần để học)

- **conftest.py + fixture**: thiết lập dùng chung, không lặp ở mỗi test.
- **Đăng nhập 1 lần qua auth_state.json**: thay cho `input()` thủ công,
  để test chạy được không cần người canh. Captcha vẫn gõ tay 1 lần ở
  `save_login.py` — không tự vượt captcha.
- **Page Object (so_do_page.py)**: gom selector 1 chỗ; web đổi chỉ sửa 1 nơi.
- **Assertion trong test**: `expect()` và `assert` — thứ biến "automation"
  thành "test" thật, vì test PHẢI thất bại khi kết quả sai.
- **`.env` + `.gitignore`**: không bao giờ hardcode mật khẩu trong code.
```
