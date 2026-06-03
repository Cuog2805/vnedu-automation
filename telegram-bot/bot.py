import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from bot_config import MAX_TELEGRAM_MESSAGE_LENGTH, ROOT_DIR, SCREENSHOT_DIR
from bot_state import BotState
from handlers.crawl_handler import CrawlHandler
from handlers.dongbo_handler import DongBoHandler
from handlers.login_handler import LoginHandler
from handlers.schedule_handler import ScheduleHandler

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

SYSTEM_VNEDU = "vnedu"
SYSTEM_CSDL = "csdl"
SYSTEM_COMMANDS = {"/vnedu", "/use_vnedu", "/csdl", "/use_csdl"}
PUBLIC_COMMANDS = {"/start", "/help", "/status", "/cancel", "/log", *SYSTEM_COMMANDS}
VNEDU_COMMANDS = {
    "/login", "/login_done", "/dongbo_ttlh", "/dongbo_ttyt", "/dongbo",
    "/dongbo_order_file", "/dongbo_schedule", "/dongbo_cancel",
}
CSDL_COMMANDS = {
    "/login", "/login_done", "/crawl_login", "/crawl_login_done",
    "/crawl", "/crawl_queue", "/crawl_schedule",
}
PARAMETER_PROMPTS = {
    "/dongbo_ttlh": "\n".join(
        [
            "Nhap ma truong hoac ten truong de chay /dongbo_ttlh.",
            "Vi du: 7900001 hoac Truong THCS A",
            "Gui /cancel de huy.",
        ]
    ),
    "/dongbo_ttyt": "\n".join(
        [
            "Nhap ma truong hoac ten truong, kem hoc ky neu can de chay /dongbo_ttyt.",
            "Vi du: 7900001 hoac Truong THCS A hk1",
            "Gui /cancel de huy.",
        ]
    ),
    "/dongbo": "\n".join(
        [
            "Nhap danh sach ma truong hoac ten truong de chay /dongbo.",
            "Vi du: 7900001, Truong THCS A hoac 7900001, Truong THCS A hk1",
            "Gui /cancel de huy.",
        ]
    ),
    "/dongbo_cancel": "\n".join(
        [
            "Nhap job_id can huy.",
            "Vi du: ord_20260603_223000_123_45678",
            "Gui /cancel de huy.",
        ]
    ),
    "/crawl_schedule": "\n".join(
        [
            "Nhap lich crawl.",
            "Vi du: VNPT_NBH at 2026-06-10 22:00",
            "Gui /cancel de huy.",
        ]
    ),
}


class TelegramApiError(RuntimeError):
    pass


class TelegramBot(LoginHandler, DongBoHandler, ScheduleHandler, CrawlHandler):
    def __init__(self, token: str, allowed_chat_ids: set[int] | None = None):
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.state = BotState()
        self.state.scheduled_order_jobs = self.load_scheduled_order_jobs()

    @property
    def lock(self):
        return self.state.lock

    @property
    def active_jobs(self):
        return self.state.active_jobs

    @property
    def active_job_kinds(self):
        return self.state.active_job_kinds

    @property
    def last_logs(self):
        return self.state.last_logs

    @property
    def last_log_titles(self):
        return self.state.last_log_titles

    @property
    def pending_order_file_requests(self):
        return self.state.pending_order_file_requests

    @property
    def pending_command_requests(self):
        return self.state.pending_command_requests

    @property
    def scheduled_order_jobs(self):
        return self.state.scheduled_order_jobs

    @property
    def selected_systems(self):
        return self.state.selected_systems

    @property
    def cancelled_jobs(self):
        return self.state.cancelled_jobs

    def run_forever(self):
        self.start_scheduler_thread()
        self.send_startup_hint()
        while True:
            try:
                for update in self.get_updates():
                    self.handle_update(update)
            except Exception as exc:
                print(f"Polling error: {exc}", file=sys.stderr)
                time.sleep(3)

    def send_startup_hint(self):
        print("Telegram bot is running. Press Ctrl+C to stop.")

    def get_updates(self):
        payload = {
            "timeout": 30,
            "offset": self.offset,
            "allowed_updates": json.dumps(["message", "callback_query"]),
        }
        response = self.request("getUpdates", payload)
        updates = response.get("result", [])
        for update in updates:
            self.offset = max(self.offset, update["update_id"] + 1)
        return updates

    def handle_update(self, update: dict):
        callback_query = update.get("callback_query")
        if callback_query:
            self.handle_callback_query(callback_query)
            return

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        document = message.get("document")

        if not chat_id:
            return

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            self.send_message(chat_id, "Chat này chưa được phép chạy bot.")
            return

        if document and self.is_waiting_order_file(chat_id):
            self.handle_order_file_document(chat_id, document)
            return

        if document and self.is_waiting_command_params(chat_id):
            self.send_message(chat_id, "Dang cho tham so dang text. Gui /cancel de huy.")
            return

        if not text:
            return

        command, argument = self.parse_command(text)
        if self.is_waiting_command_params(chat_id):
            if self.is_command_text(text):
                if command != "/cancel":
                    self.pop_pending_command_request(chat_id)
            else:
                pending_command = self.pop_pending_command_request(chat_id)
                if pending_command:
                    command = pending_command
                    argument = text

        if command in {"/vnedu", "/use_vnedu"}:
            self.select_system(chat_id, SYSTEM_VNEDU)
            return
        if command in {"/csdl", "/use_csdl"}:
            self.select_system(chat_id, SYSTEM_CSDL)
            return

        selected_system = self.get_selected_system(chat_id)
        if command not in PUBLIC_COMMANDS and selected_system is None:
            self.send_system_menu(chat_id, "Hãy chọn hệ thống trước khi chạy lệnh.")
            return

        if selected_system == SYSTEM_VNEDU and command in {
            "/crawl_login",
            "/crawl_login_done",
            "/crawl",
            "/crawl_queue",
            "/crawl_schedule",
        }:
            self.send_message(
                chat_id,
                "Bạn đang chọn http://giaoduc.ninhbinh.vnpt.vn/. Gõ /csdl để chuyển sang https://dongbo.csdl.edu.vn.",
            )
            return

        if selected_system == SYSTEM_CSDL and command in {
            "/dongbo_ttlh",
            "/dongbo_ttyt",
            "/dongbo",
            "/dongbo_order_file",
            "/dongbo_schedule",
            "/dongbo_cancel",
        }:
            self.send_message(
                chat_id,
                "Bạn đang chọn https://dongbo.csdl.edu.vn. Gõ /vnedu để chuyển sang http://giaoduc.ninhbinh.vnpt.vn/.",
            )
            return

        if self.is_waiting_order_file(chat_id) and command not in {
            "/cancel",
            "/help",
            "/start",
            "/status",
            "/dongbo_schedule",
            "/dongbo_cancel",
        }:
            self.send_message(chat_id, "Đang chờ file .txt. Hãy gửi file orders.txt hoặc /cancel để hủy.")
            return

        if self.should_prompt_for_argument(command, argument):
            self.prompt_for_command_argument(chat_id, command)
            return

        if command == "/start":
            self.send_start(chat_id)
        elif command == "/help":
            self.send_help(chat_id)
        elif command == "/cancel":
            self.handle_cancel_request(chat_id)
        elif command == "/dongbo_schedule":
            self.send_scheduled_jobs(chat_id)
        elif command == "/dongbo_cancel":
            self.handle_cancel_scheduled_job(chat_id, argument)
        elif command == "/status":
            self.send_status(chat_id)
        elif command == "/log":
            self.send_last_log(chat_id)
        elif command == "/login":
            if selected_system == SYSTEM_CSDL:
                self.handle_crawl_login_request(chat_id)
            else:
                self.handle_login_request(chat_id)
        elif command == "/login_done":
            if selected_system == SYSTEM_CSDL:
                self.handle_crawl_login_done(chat_id)
            else:
                self.handle_login_done(chat_id)
        elif command == "/dongbo_ttlh":
            self.handle_ttlh_request(chat_id, argument)
        elif command == "/dongbo_ttyt":
            self.handle_ttyt_request(chat_id, argument)
        elif command == "/dongbo":
            self.handle_queue_request(chat_id, argument)
        elif command == "/dongbo_order_file":
            self.handle_order_file_request(chat_id, argument)
        elif command == "/crawl_login":
            self.handle_crawl_login_request(chat_id)
        elif command == "/crawl_login_done":
            self.handle_crawl_login_done(chat_id)
        elif command == "/crawl":
            self.handle_crawl_request(chat_id, argument)
        elif command == "/crawl_queue":
            self.handle_crawl_queue_request(chat_id, argument)
        elif command == "/crawl_schedule":
            self.handle_crawl_schedule_request(chat_id, argument)
        else:
            self.send_message(chat_id, "Lệnh không hợp lệ. Gõ /help để xem cách dùng.")

    def parse_command(self, text: str):
        if text.startswith("@"):
            mention_parts = text.split(maxsplit=1)
            if len(mention_parts) == 2 and mention_parts[1].startswith("/"):
                text = mention_parts[1].strip()

        if not text.startswith("/"):
            return "/dongbo", text

        parts = text.split(maxsplit=1)
        command = parts[0].split("@", maxsplit=1)[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command, argument

    def handle_callback_query(self, callback_query: dict):
        query_id = callback_query.get("id")
        message = callback_query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        data = callback_query.get("data")

        if query_id:
            self.answer_callback_query(query_id)
        if not chat_id:
            return
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            self.send_message(chat_id, "Chat này chưa được phép chạy bot.")
            return

        if data == "select:vnedu":
            self.select_system(chat_id, SYSTEM_VNEDU)
        elif data == "select:csdl":
            self.select_system(chat_id, SYSTEM_CSDL)
        elif data and data.startswith("cmd:"):
            command_text = data.removeprefix("cmd:")
            self.handle_update({"message": {"chat": {"id": chat_id}, "text": command_text}})

    def get_selected_system(self, chat_id: int):
        with self.lock:
            return self.selected_systems.get(chat_id)

    def select_system(self, chat_id: int, system: str):
        with self.lock:
            self.selected_systems[chat_id] = system
            self.pending_order_file_requests.pop(chat_id, None)
            self.pending_command_requests.pop(chat_id, None)
            if self.active_job_kinds.get(chat_id) == "order_file_waiting":
                self.active_jobs.pop(chat_id, None)
                self.active_job_kinds.pop(chat_id, None)
            elif self.active_job_kinds.get(chat_id) == "command_param_waiting":
                self.active_jobs.pop(chat_id, None)
                self.active_job_kinds.pop(chat_id, None)

        if system == SYSTEM_VNEDU:
            self.send_message(
                chat_id,
                "\n".join(
                    [
                        "Đã chọn http://giaoduc.ninhbinh.vnpt.vn/.",
                        "Từ giờ /login sẽ mở đăng nhập cho hệ thống này.",
                        "Gõ /help để xem các lệnh đồng bộ.",
                    ]
                ),
            )
        else:
            self.send_message(
                chat_id,
                "\n".join(
                    [
                        "Đã chọn https://dongbo.csdl.edu.vn.",
                        "Từ giờ /login sẽ mở đăng nhập cho hệ thống này.",
                        "Gõ /help để xem các lệnh crawl.",
                    ]
                ),
            )

    def send_start(self, chat_id: int):
        self.send_system_menu(chat_id)

    def send_system_menu(self, chat_id: int, prefix: str | None = None):
        lines = []
        if prefix:
            lines.extend([prefix, ""])
        lines.extend(
            [
                "VNEDU Automation Bot",
                "",
                "Chọn hệ thống:",
                "/vnedu - http://giaoduc.ninhbinh.vnpt.vn/",
                "/csdl - https://dongbo.csdl.edu.vn",
                "",
                "Sau khi chọn, dùng /help để xem lệnh tương ứng.",
            ]
        )
        self.send_message(
            chat_id,
            "\n".join(lines),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "VNEDU",
                            "callback_data": "select:vnedu",
                        },
                        {
                            "text": "CSDL",
                            "callback_data": "select:csdl",
                        },
                    ]
                ],
            },
        )

    def command_button(self, command: str):
        return {"text": command, "callback_data": f"cmd:{command}"}

    def send_help(self, chat_id: int):
        selected_system = self.get_selected_system(chat_id)
        if selected_system is None:
            self.send_system_menu(chat_id, "Chưa chọn hệ thống.")
            return

        if selected_system == SYSTEM_CSDL:
            self.send_message(
                chat_id,
                "\n".join(
                    [
                        "Hệ thống: https://dongbo.csdl.edu.vn",
                        "",
                        "/login - mở trình duyệt để đăng nhập CSDL và lưu phiên",
                        "/login_done - sau khi đăng nhập CSDL xong, lưu phiên",
                        "/crawl [maDoiTac] - crawl danh sách trường, gửi file TXT",
                        "/crawl_queue [maDoiTac] - crawl rồi chạy luôn queue đồng bộ",
                        "/crawl_schedule [maDoiTac] at YYYY-MM-DD HH:mm - crawl rồi đặt lịch queue",
                        "",
                        "Lệnh chung:",
                        "/start - chọn lại hệ thống",
                        "/status - xem tiến trình đang chạy",
                        "/log - xem log cuối",
                        "/cancel - hủy tác vụ đang chạy",
                    ]
                ),
                reply_markup={
                    "inline_keyboard": [
                        [self.command_button("/login"), self.command_button("/login_done")],
                        [self.command_button("/crawl"), self.command_button("/crawl_queue")],
                        [self.command_button("/crawl_schedule")],
                        [
                            self.command_button("/status"),
                            self.command_button("/log"),
                            self.command_button("/cancel"),
                        ],
                        [self.command_button("/vnedu")],
                    ]
                },
            )
            return

        self.send_message(
            chat_id,
            "\n".join(
                [
                    "Hệ thống: http://giaoduc.ninhbinh.vnpt.vn/",
                    "",
                    "/login - mở trình duyệt để đăng nhập VNEDU và tạo auth_state.json",
                    "/login_done - sau khi đăng nhập VNEDU xong, lưu phiên",
                    "/dongbo_ttlh <ma_hoac_ten_truong> - đồng bộ CBGV, lớp, học sinh, trường học",
                    "/dongbo_ttyt <ma_hoac_ten_truong> [gk1|hk1|gk2|hk2|cn] - đồng bộ KQHT/Y tế",
                    "/dongbo <ma_hoac_ten_1>, <ma_hoac_ten_2> [gk1|hk1|gk2|hk2|cn] - queue TTLH rồi TTYT",
                    "/dongbo_order_file - gửi file .txt danh sách trường",
                    "/dongbo_order_file at YYYY-MM-DD HH:mm - đặt lịch chạy file order",
                    "/dongbo_schedule - xem danh sách lịch đang chờ",
                    "/dongbo_cancel <job_id> - hủy lịch order file",
                    "",
                    "Lệnh chung:",
                    "/start - chọn lại hệ thống",
                    "/status - xem tiến trình đang chạy",
                    "/log - xem log cuối",
                    "/cancel - hủy tác vụ đang chạy",
                ]
            ),
            reply_markup={
                "inline_keyboard": [
                    [self.command_button("/login"), self.command_button("/login_done")],
                    [self.command_button("/dongbo_ttlh"), self.command_button("/dongbo_ttyt")],
                    [self.command_button("/dongbo")],
                    [
                        self.command_button("/dongbo_order_file"),
                        self.command_button("/dongbo_schedule"),
                    ],
                    [self.command_button("/dongbo_cancel")],
                    [
                        self.command_button("/status"),
                        self.command_button("/log"),
                        self.command_button("/cancel"),
                    ],
                    [self.command_button("/csdl")],
                ]
            },
        )

    def send_status(self, chat_id: int):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            kind = self.active_job_kinds.get(chat_id)

        if chat_id in self.active_jobs and (process is None or process.poll() is None):
            # [CRAWL] kind crawl
            if kind == "crawl_login":
                self.send_message(chat_id, "Đang mở trình duyệt đăng nhập CSDL. Đăng nhập xong gửi /crawl_login_done.")
            elif kind == "crawl":
                self.send_message(chat_id, "Đang crawl danh sách trường từ CSDL Giáo dục.")
            elif kind == "crawl_queue":
                self.send_message(chat_id, "Đang crawl rồi chạy queue đồng bộ.")
            elif kind == "crawl_schedule":
                self.send_message(chat_id, "Đang crawl để chuẩn bị lịch đồng bộ.")
            elif kind == "login":
                self.send_message(
                    chat_id,
                    "Đang mở phiên đăng nhập. Đăng nhập trên trình duyệt, rồi gửi /login_done.",
                )
            elif kind == "queue":
                self.send_message(chat_id, "Đang chạy queue đồng bộ. Vui lòng chờ kết quả.")
            elif kind == "order_file_waiting":
                self.send_message(chat_id, "Đang chờ file .txt cho /dongbo_order_file.")
            elif kind == "order_file":
                self.send_message(chat_id, "Đang chạy queue đồng bộ từ file. Vui lòng chờ kết quả.")
            elif kind == "command_param_waiting":
                pending_command = self.get_pending_command_request(chat_id)
                if pending_command:
                    self.send_message(chat_id, f"Dang cho tham so cho {pending_command}.")
                else:
                    self.send_message(chat_id, "Dang cho tham so cho lenh vua chon.")
            elif kind == "ttyt":
                self.send_message(chat_id, "Đang chạy đồng bộ KQHT/Y tế. Vui lòng chờ kết quả.")
            else:
                self.send_message(chat_id, "Đang chạy đồng bộ TTLH. Vui lòng chờ kết quả.")
            return

        self.send_message(chat_id, "Không có tác vụ nào đang chạy.")

    def handle_cancel_request(self, chat_id: int):
        process_to_cancel = None
        with self.lock:
            process = self.active_jobs.get(chat_id)
            kind = self.active_job_kinds.get(chat_id)
            has_active_job = chat_id in self.active_jobs and (
                process is None or process.poll() is None
            )
            is_waiting_file = chat_id in self.pending_order_file_requests
            is_waiting_command = chat_id in self.pending_command_requests

            if not has_active_job and not is_waiting_file and not is_waiting_command:
                message = "Khong co tac vu nao dang chay de huy."
            else:
                self.cancelled_jobs.add(chat_id)
                self.pending_order_file_requests.pop(chat_id, None)
                self.pending_command_requests.pop(chat_id, None)
                if process is not None and process.poll() is None:
                    process_to_cancel = process
                elif kind in {"order_file_waiting", "command_param_waiting"}:
                    self.active_jobs.pop(chat_id, None)
                    self.active_job_kinds.pop(chat_id, None)
                message = "Da gui yeu cau huy tac vu dang chay."

        if process_to_cancel is not None:
            try:
                process_to_cancel.terminate()
            except OSError:
                pass

        self.send_message(chat_id, message)

    def reserve_chat_job(self, chat_id: int, kind: str):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            if chat_id in self.active_jobs and (process is None or process.poll() is None):
                self.send_message(
                    chat_id,
                    "Chat n?y ?ang c? m?t t?c v? ch?y. Ch? xong r?i ch?y ti?p.",
                )
                return False
            self.cancelled_jobs.discard(chat_id)
            self.active_jobs[chat_id] = None
            self.active_job_kinds[chat_id] = kind
        return True

    def clear_chat_job(self, chat_id: int):
        with self.lock:
            self.pending_order_file_requests.pop(chat_id, None)
            self.pending_command_requests.pop(chat_id, None)
            self.active_jobs.pop(chat_id, None)
            self.active_job_kinds.pop(chat_id, None)
            self.cancelled_jobs.discard(chat_id)

    def is_command_text(self, text: str):
        value = text.strip()
        if value.startswith("/"):
            return True
        if value.startswith("@"):
            mention_parts = value.split(maxsplit=1)
            return len(mention_parts) == 2 and mention_parts[1].startswith("/")
        return False

    def should_prompt_for_argument(self, command: str, argument: str):
        return command in PARAMETER_PROMPTS and not argument.strip()

    def prompt_for_command_argument(self, chat_id: int, command: str):
        if not self.reserve_chat_job(chat_id, "command_param_waiting"):
            return
        with self.lock:
            self.pending_command_requests[chat_id] = command
        self.send_message(chat_id, PARAMETER_PROMPTS[command])

    def is_waiting_command_params(self, chat_id: int):
        with self.lock:
            return chat_id in self.pending_command_requests

    def get_pending_command_request(self, chat_id: int):
        with self.lock:
            return self.pending_command_requests.get(chat_id)

    def pop_pending_command_request(self, chat_id: int):
        with self.lock:
            command = self.pending_command_requests.pop(chat_id, None)
            if self.active_job_kinds.get(chat_id) == "command_param_waiting":
                self.active_jobs.pop(chat_id, None)
                self.active_job_kinds.pop(chat_id, None)
            self.cancelled_jobs.discard(chat_id)
            return command

    def is_cancel_requested(self, chat_id: int):
        with self.lock:
            return chat_id in self.cancelled_jobs

    def clear_cancel_request(self, chat_id: int):
        with self.lock:
            self.cancelled_jobs.discard(chat_id)

    def build_screenshot_path(self, name: str | None = None):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "dongbo")
        timestamp = int(time.time() * 1000)
        return SCREENSHOT_DIR / f"{safe_name}_{timestamp}.png"

    def build_subprocess_env(self, screenshot_path: Path | None = None):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if screenshot_path is not None:
            env["VNEDU_SCREENSHOT_PATH"] = str(screenshot_path)
        return env

    def format_datetime(self, value: datetime):
        return value.strftime("%Y-%m-%d %H:%M")

    def save_last_log(self, chat_id: int, title: str, output: str):
        with self.lock:
            self.last_log_titles[chat_id] = title
            self.last_logs[chat_id] = self.tail_text(output, max_chars=3500)

    def send_last_log(self, chat_id: int):
        with self.lock:
            title = self.last_log_titles.get(chat_id)
            log = self.last_logs.get(chat_id)

        if not log:
            self.send_message(
                chat_id,
                "Chưa có log nào. Hãy chạy /login, /dongbo_ttlh, /dongbo_ttyt hoặc /dongbo trước.",
            )
            return

        self.send_message(
            chat_id,
            "\n".join(
                [
                    title or "Log cuối",
                    "",
                    log,
                ]
            ),
        )

    def tail_text(self, text: str, max_chars: int):
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return "...\n" + text[-max_chars:]

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None):
        chunks = self.split_message(text)
        for index, chunk in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if index == 0 and reply_markup is not None:
                payload["reply_markup"] = json.dumps(reply_markup)
            self.request(
                "sendMessage",
                payload,
            )

    def send_photo(self, chat_id: int, image_path: Path, caption: str):
        if len(caption) > 1000:
            caption = caption[:997] + "..."

        try:
            self.request_multipart(
                "sendPhoto",
                fields={
                    "chat_id": str(chat_id),
                    "caption": caption,
                },
                files={
                    "photo": image_path,
                },
            )
        except Exception as exc:
            self.send_message(
                chat_id,
                "\n".join(
                    [
                        caption,
                        f"Không gửi được ảnh screenshot: {exc}",
                        f"File ảnh: {image_path}",
                    ]
                ),
            )

    def split_message(self, text: str):
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            return [text]

        chunks = []
        current = text
        while len(current) > MAX_TELEGRAM_MESSAGE_LENGTH:
            split_at = current.rfind("\n", 0, MAX_TELEGRAM_MESSAGE_LENGTH)
            if split_at <= 0:
                split_at = MAX_TELEGRAM_MESSAGE_LENGTH
            chunks.append(current[:split_at])
            current = current[split_at:].lstrip()
        if current:
            chunks.append(current)
        return chunks

    def request(self, method: str, payload: dict):
        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base}/{method}",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            body = json.loads(response.read().decode("utf-8"))

        if not body.get("ok"):
            raise TelegramApiError(body)
        return body

    def answer_callback_query(self, query_id: str):
        self.request("answerCallbackQuery", {"callback_query_id": query_id})

    def request_multipart(self, method: str, fields: dict[str, str], files: dict[str, Path]):
        boundary = f"----vnedu-automation-{int(time.time() * 1000)}"
        body_parts = []

        for name, value in fields.items():
            body_parts.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    f"{value}\r\n".encode("utf-8"),
                ]
            )

        for name, path in files.items():
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body_parts.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    (
                        f'Content-Disposition: form-data; name="{name}"; '
                        f'filename="{path.name}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                    path.read_bytes(),
                    b"\r\n",
                ]
            )

        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        data = b"".join(body_parts)

        request = urllib.request.Request(
            f"{self.api_base}/{method}",
            data=data,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))

        if not body.get("ok"):
            raise TelegramApiError(body)
        return body


def parse_allowed_chat_ids(raw_value: str | None):
    if not raw_value:
        return set()

    chat_ids = set()
    for value in raw_value.split(","):
        value = value.strip()
        if value:
            chat_ids.add(int(value))
    return chat_ids


def main():
    parser = argparse.ArgumentParser(description="Telegram UI for VNEDU automation.")
    parser.add_argument(
        "--token",
        default=None,
        help="Telegram bot token. If omitted, TELEGRAM_BOT_TOKEN is read from .env.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")

    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN in .env or --token.")

    allowed_chat_ids = parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))
    bot = TelegramBot(token=token, allowed_chat_ids=allowed_chat_ids)
    bot.run_forever()


if __name__ == "__main__":
    main()
