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
/dongbo_ttyt 7900001
/dongbo 7900001, 7900002 hk1
/dongbo_order_file
/dongbo_order_file at 2026-06-03 22:30
/dongbo_schedule
/dongbo_cancel ord_...
/log
```

Luồng tạo phiên đăng nhập:

1. Gửi `/login` cho bot.
2. Trên máy đang chạy bot, trình duyệt sẽ mở ra.
3. Đăng nhập thủ công, gồm cả captcha.
4. Khi đăng nhập xong, gửi `/login_done` để bot lưu `auth_state.json`.

Các lệnh đồng bộ:

- `/dongbo_ttlh <ma_truong>`: chạy chức năng đồng bộ CBGV, lớp học, học sinh, trường học.
- `/dongbo_ttyt <ma_truong> [gk1|hk1|gk2|hk2|cn]`: chạy chức năng đồng bộ KQHT/Y tế. Nếu không truyền học kỳ, bot đọc dropdown trên modal và chạy tất cả option hiện có.
- `/dongbo <ma_1>, <ma_2> [gk1|hk1|gk2|hk2|cn]`: chạy queue nhiều trường, mỗi trường chạy TTLH trước rồi TTYT/KQHT sau. Nếu không truyền học kỳ, bot đọc dropdown trên modal và chạy tất cả option hiện có. Nếu TTLH fail, TTYT/KQHT của trường đó sẽ bị skip.
- `/dongbo_order_file`: bot chờ file `.txt` danh sách trường rồi chạy queue theo đúng thứ tự trong file.
- `/dongbo_order_file at YYYY-MM-DD HH:mm`: đặt lịch chạy file order theo ngày, tháng, năm, giờ, phút. Bot cũng hỗ trợ `DD/MM/YYYY HH:mm` và `DD-MM-YYYY HH:mm`.
- `/dongbo_schedule`: xem các lịch order file đang chờ.
- `/dongbo_cancel <job_id>`: hủy một lịch order file.

File order có dạng mỗi trường một dòng, mã trường đứng đầu dòng:

```text
0000001 Trường Tiểu học Vĩnh Trụ
0000002 Trường Tiểu học Bắc Lý
```

Luồng chạy file order:

1. Gửi `/dongbo_order_file`.
2. Bot trả `OK. Gửi file .txt để đồng bộ.`
3. Gửi file `.txt`.
4. Bot chạy TTLH từng trường, nếu TTLH pass thì chạy TTYT/KQHT tất cả option trong modal của trường đó.

Luồng đặt lịch file order:

1. Gửi `/dongbo_order_file at 2026-06-03 22:30`.
2. Bot trả `OK. Gửi file .txt để đồng bộ. Lịch chạy: 2026-06-03 22:30.`
3. Gửi file `.txt`.
4. Bot parse file ngay, lưu lịch vào `telegram-bot/scheduled_jobs.json`, rồi chạy khi tới giờ.

Khi chạy TTLH, bot gọi:

```powershell
python -m pytest tests/test_dong_bo.py -k test_dong_bo_du_lieu_truong_hoc --school-code=<ma_truong> -p no:cacheprovider -o "addopts=-v --browser chromium"
```

Khi chạy TTYT/KQHT, bot gọi:

```powershell
python -m pytest tests/test_dong_bo.py -k test_dong_bo_kqht_y_te --school-code=<ma_truong> --semester=hk1 -p no:cacheprovider -o "addopts=-v --browser chromium"
```

Nếu bỏ `--semester`, test sẽ tự chạy tất cả option học kỳ đang có trong modal.

Các lệnh đồng bộ chạy Playwright ở chế độ ngầm, không mở cửa sổ browser.
Sau khi pytest kết thúc, bot gửi lại ảnh screenshot kèm trạng thái SUCCESS/FAIL, exit code và tóm tắt.
Gửi `/log` để xem log cuối của tác vụ gần nhất.
