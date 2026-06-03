## Cài đặt (làm 1 lần)

```bash
pip install -r requirements.txt
playwright install chromium
```

## Thiết lập thông tin đăng nhập

1. Sao chép `.env.example` thành `.env`
2. Mở `.env`, điền URL / user / mật khẩu thật

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