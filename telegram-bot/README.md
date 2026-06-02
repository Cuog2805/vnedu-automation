# Telegram Bot UI
## Cấu hình

Thêm vào file `.env` ở thư mục gốc project:

```env
TELEGRAM_BOT_TOKEN=token_bot_cua_ban
TELEGRAM_ALLOWED_CHAT_IDS=
```

## Chạy bot

Từ thư mục gốc project:

```powershell
python telegram-bot\bot.py
```

## Lệnh Telegram

```text
/start
/help
/status
/login
/login_done
/dongbo_ttlh 7900001
/dongbo_ttyt 7900001 hk1
/dongbo 7900001, 7900002 hk1
/log
```

Luồng tạo phiên đăng nhập:

1. Gửi `/login` cho bot.
2. Trên máy đang chạy bot, trình duyệt sẽ mở ra.
3. Đăng nhập thủ công, gồm cả captcha.
4. Khi đăng nhập xong, gửi `/login_done` để bot lưu `auth_state.json`.

Các lệnh đồng bộ:

- `/dongbo_ttlh <ma_truong>`: chạy chức năng đồng bộ CBGV, lớp học, học sinh, trường học.
- `/dongbo_ttyt <ma_truong> [hk1|hk2|cn]`: chạy chức năng đồng bộ KQHT/Y tế. Nếu không truyền học kỳ, bot chạy lần lượt `hk1`, `hk2`, `cn`.
- `/dongbo <ma_1>, <ma_2> [hk1|hk2|cn]`: chạy queue nhiều trường, mỗi trường chạy TTLH trước rồi TTYT/KQHT sau. Nếu không truyền học kỳ, bot chạy lần lượt `hk1`, `hk2`, `cn`. Nếu TTLH fail, TTYT/KQHT của trường đó sẽ bị skip.

Khi chạy TTLH, bot gọi:

```powershell
python -m pytest tests/test_dong_bo.py -k test_dong_bo_du_lieu_truong_hoc --school-code=<ma_truong> -p no:cacheprovider -o "addopts=-v --browser chromium"
```

Khi chạy TTYT/KQHT, bot gọi:

```powershell
python -m pytest tests/test_dong_bo.py -k test_dong_bo_kqht_y_te --school-code=<ma_truong> --semester=hk1 -p no:cacheprovider -o "addopts=-v --browser chromium"
```

Các lệnh đồng bộ chạy Playwright ở chế độ ngầm, không mở cửa sổ browser.
Sau khi pytest kết thúc, bot gửi lại ảnh screenshot kèm trạng thái SUCCESS/FAIL, exit code và tóm tắt.
Gửi `/log` để xem log cuối của tác vụ gần nhất.
