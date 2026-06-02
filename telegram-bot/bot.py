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
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_FILE = "tests/test_dong_bo.py"
LOGIN_SCRIPT = "scripts/save_login.py"
SCREENSHOT_DIR = ROOT_DIR / "artifacts" / "screenshots"
SCHEDULED_JOBS_PATH = ROOT_DIR / "telegram-bot" / "scheduled_jobs.json"
SCHOOL_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,30}$")
SEMESTERS = {"gk1", "hk1", "gk2", "hk2", "cn"}
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
MAX_ORDER_FILE_SIZE_BYTES = 1024 * 1024
SCHEDULER_POLL_SECONDS = 10


class TelegramApiError(RuntimeError):
    pass


class TelegramBot:
    def __init__(self, token: str, allowed_chat_ids: set[int] | None = None):
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.api_base = f"https://api.telegram.org/bot{token}"
        self.offset = 0
        self.active_jobs: dict[int, subprocess.Popen | None] = {}
        self.active_job_kinds: dict[int, str] = {}
        self.last_logs: dict[int, str] = {}
        self.last_log_titles: dict[int, str] = {}
        self.lock = threading.Lock()
        self.pending_order_file_requests: dict[int, datetime | None] = {}
        self.scheduled_order_jobs: dict[str, dict] = self.load_scheduled_order_jobs()

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
            "allowed_updates": json.dumps(["message"]),
        }
        response = self.request("getUpdates", payload)
        updates = response.get("result", [])
        for update in updates:
            self.offset = max(self.offset, update["update_id"] + 1)
        return updates

    def handle_update(self, update: dict):
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

        if not text:
            return

        command, argument = self.parse_command(text)
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
            self.handle_login_request(chat_id)
        elif command == "/login_done":
            self.handle_login_done(chat_id)
        elif command == "/dongbo_ttlh":
            self.handle_ttlh_request(chat_id, argument)
        elif command == "/dongbo_ttyt":
            self.handle_ttyt_request(chat_id, argument)
        elif command == "/dongbo":
            self.handle_queue_request(chat_id, argument)
        elif command == "/dongbo_order_file":
            self.handle_order_file_request(chat_id, argument)
        else:
            self.send_message(
                chat_id,
                "Lệnh không hợp lệ. Gõ /help để xem cách dùng.",
            )

    def parse_command(self, text: str):
        if not text.startswith("/"):
            return "/dongbo", text

        parts = text.split(maxsplit=1)
        command = parts[0].split("@", maxsplit=1)[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        return command, argument

    def send_start(self, chat_id: int):
        self.send_help(chat_id)

    def send_help(self, chat_id: int):
        self.send_message(
            chat_id,
            "\n".join(
                [
                    "VNEDU Automation Bot",
                    "",
                    "Lệnh:",
                    "/login - mở trình duyệt để đăng nhập và tạo auth_state.json",
                    "/login_done - sau khi đăng nhập xong, lưu phiên đăng nhập",
                    "/dongbo_ttlh <ma_truong> - đồng bộ CBGV, lớp, học sinh, trường học",
                    "/dongbo_ttyt <ma_truong> [gk1|hk1|gk2|hk2|cn] - đồng bộ KQHT/Y tế; bỏ học kỳ sẽ chạy mọi option trong modal",
                    "/dongbo <ma_1>, <ma_2> [gk1|hk1|gk2|hk2|cn] - queue TTLH rồi TTYT; bỏ học kỳ sẽ chạy mọi option trong modal",
                    "/dongbo_order_file - gửi file .txt danh sách trường, mỗi dòng bắt đầu bằng mã trường",
                    "/dongbo_order_file at YYYY-MM-DD HH:mm - đặt lịch chạy file order",
                    "/dongbo_schedule - xem danh sách lịch đang chờ",
                    "/dongbo_cancel <job_id> - hủy lịch order file",
                    "/cancel - hủy trạng thái đang chờ file",
                    "/status - xem tiến trình đang chạy",
                    "/log - xem log cuối của tác vụ gần nhất",
                    "/help - xem hướng dẫn",
                    "",
                    "Ví dụ:",
                    "/dongbo_ttlh 7900001",
                    "/dongbo_ttyt 7900001 hk1",
                    "/dongbo 7900001, 7900002 hk1",
                    "/dongbo_order_file",
                    "/dongbo_order_file at 2026-06-03 22:30",
                ]
            ),
        )

    def send_status(self, chat_id: int):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            kind = self.active_job_kinds.get(chat_id)

        if chat_id in self.active_jobs and (process is None or process.poll() is None):
            if kind == "login":
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
            elif kind == "ttyt":
                self.send_message(chat_id, "Đang chạy đồng bộ KQHT/Y tế. Vui lòng chờ kết quả.")
            else:
                self.send_message(
                    chat_id,
                    "Đang chạy đồng bộ TTLH. Vui lòng chờ kết quả.",
                )
            return

        self.send_message(chat_id, "Không có tác vụ nào đang chạy.")

    def handle_cancel_request(self, chat_id: int):
        with self.lock:
            if chat_id not in self.pending_order_file_requests:
                message = "Không có trạng thái chờ file nào để hủy."
            else:
                self.pending_order_file_requests.pop(chat_id, None)
                self.active_jobs.pop(chat_id, None)
                self.active_job_kinds.pop(chat_id, None)
                message = "Đã hủy trạng thái chờ file."

        self.send_message(chat_id, message)

    def handle_login_request(self, chat_id: int):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            if chat_id in self.active_jobs and (process is None or process.poll() is None):
                self.send_message(
                    chat_id,
                    "Chat này đang có một tác vụ chạy. Chờ xong rồi chạy tiếp.",
                )
                return
            self.active_jobs[chat_id] = None
            self.active_job_kinds[chat_id] = "login"

        thread = threading.Thread(
            target=self.start_login_process,
            args=(chat_id,),
            daemon=True,
        )
        thread.start()

    def start_login_process(self, chat_id: int):
        self.send_message(
            chat_id,
            "\n".join(
                [
                    "Đang mở trình duyệt đăng nhập.",
                    "Hãy đăng nhập thủ công trên máy chạy bot, gồm cả captcha.",
                    "Sau khi đăng nhập xong, gửi /login_done để lưu phiên.",
                ]
            ),
        )

        command = [sys.executable, LOGIN_SCRIPT]
        env = self.build_subprocess_env()

        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT_DIR,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except Exception as exc:
            with self.lock:
                self.active_jobs.pop(chat_id, None)
                self.active_job_kinds.pop(chat_id, None)
            self.send_message(chat_id, f"Không chạy được script login: {exc}")
            return

        with self.lock:
            self.active_jobs[chat_id] = process

        while process.poll() is None:
            time.sleep(1)

    def handle_login_done(self, chat_id: int):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            kind = self.active_job_kinds.get(chat_id)

        if kind != "login" or process is None:
            self.send_message(chat_id, "Không có phiên login nào đang chờ /login_done.")
            return

        if process.poll() is not None:
            self.finish_login_process(chat_id, process)
            return

        if process.stdin is None:
            self.send_message(chat_id, "Process login không nhận được tín hiệu lưu phiên.")
            return

        try:
            process.stdin.write("\n")
            process.stdin.flush()
            process.stdin.close()
        except OSError as exc:
            self.send_message(chat_id, f"Không gửi được tín hiệu lưu phiên: {exc}")
            return

        thread = threading.Thread(
            target=self.finish_login_process,
            args=(chat_id, process),
            daemon=True,
        )
        thread.start()

    def finish_login_process(self, chat_id: int, process: subprocess.Popen):
        output = ""
        if process.stdout is not None:
            output = process.stdout.read()
        return_code = process.wait()

        with self.lock:
            self.active_jobs.pop(chat_id, None)
            self.active_job_kinds.pop(chat_id, None)

        status = "PASS" if return_code == 0 else "FAIL"
        auth_state_path = ROOT_DIR / "auth_state.json"
        auth_state_status = (
            "Đã tạo auth_state.json"
            if auth_state_path.exists()
            else "Chưa thấy auth_state.json"
        )
        self.save_last_log(chat_id, "Log login gần nhất", output)
        self.send_message(
            chat_id,
            "\n".join(
                [
                    f"Kết quả login: {status}",
                    f"Exit code: {return_code}",
                    auth_state_status,
                    "Gửi /log để xem log cuối.",
                ]
            ),
        )

    def handle_ttlh_request(self, chat_id: int, raw_value: str):
        school_code = self.parse_single_school_code(raw_value)
        if school_code is None:
            self.send_message(chat_id, "Thiếu hoặc sai mã trường. Ví dụ: /dongbo_ttlh 7900001")
            return

        if not self.reserve_chat_job(chat_id, "ttlh"):
            return

        thread = threading.Thread(
            target=self.run_single_ttlh,
            args=(chat_id, school_code),
            daemon=True,
        )
        thread.start()

    def handle_ttyt_request(self, chat_id: int, raw_value: str):
        school_code, semesters = self.parse_school_and_semesters(raw_value)
        if school_code is None:
            self.send_message(
                chat_id,
                "Thiếu hoặc sai tham số. Ví dụ: /dongbo_ttyt 7900001 hoặc /dongbo_ttyt 7900001 hk1",
            )
            return

        if not self.reserve_chat_job(chat_id, "ttyt"):
            return

        thread = threading.Thread(
            target=self.run_single_ttyt,
            args=(chat_id, school_code, semesters),
            daemon=True,
        )
        thread.start()

    def handle_queue_request(self, chat_id: int, raw_value: str):
        school_codes, semesters = self.parse_queue_request(raw_value)
        if not school_codes:
            self.send_message(
                chat_id,
                "Thiếu hoặc sai mã trường. Ví dụ: /dongbo 7900001, 7900002 hoặc /dongbo 7900001, 7900002 hk1",
            )
            return

        if not self.reserve_chat_job(chat_id, "queue"):
            return

        thread = threading.Thread(
            target=self.run_sync_queue,
            args=(chat_id, school_codes, semesters),
            daemon=True,
        )
        thread.start()

    def handle_order_file_request(self, chat_id: int, raw_value: str = ""):
        try:
            run_at = self.parse_order_file_schedule(raw_value)
        except ValueError as exc:
            self.send_message(chat_id, str(exc))
            return

        if not self.reserve_chat_job(chat_id, "order_file_waiting"):
            return

        with self.lock:
            self.pending_order_file_requests[chat_id] = run_at

        if run_at is None:
            self.send_message(chat_id, "OK. Gửi file .txt để đồng bộ.")
        else:
            self.send_message(
                chat_id,
                f"OK. Gửi file .txt để đồng bộ. Lịch chạy: {self.format_datetime(run_at)}.",
            )

    def handle_order_file_document(self, chat_id: int, document: dict):
        with self.lock:
            run_at = self.pending_order_file_requests.pop(chat_id, None)
            self.active_job_kinds[chat_id] = "order_file"

        thread = threading.Thread(
            target=self.start_order_file_process,
            args=(chat_id, document, run_at),
            daemon=True,
        )
        thread.start()

    def is_waiting_order_file(self, chat_id: int):
        with self.lock:
            return chat_id in self.pending_order_file_requests

    def reserve_chat_job(self, chat_id: int, kind: str):
        with self.lock:
            process = self.active_jobs.get(chat_id)
            if chat_id in self.active_jobs and (process is None or process.poll() is None):
                self.send_message(
                    chat_id,
                    "Chat này đang có một tác vụ chạy. Chờ xong rồi chạy tiếp.",
                )
                return False
            self.active_jobs[chat_id] = None
            self.active_job_kinds[chat_id] = kind
        return True

    def run_single_ttlh(self, chat_id: int, school_code: str):
        try:
            self.send_message(chat_id, f"Bắt đầu TTLH cho mã trường: {school_code}")
            result = self.run_pytest_command(
                chat_id,
                self.build_ttlh_command(school_code),
            )
            self.send_command_result(
                chat_id=chat_id,
                title=f"Kết quả TTLH mã trường {school_code}",
                return_code=result[0],
                output=result[1],
                screenshot_path=result[2],
            )
        finally:
            self.clear_chat_job(chat_id)

    def run_single_ttyt(self, chat_id: int, school_code: str, semesters: list[str]):
        try:
            if not semesters:
                self.send_message(
                    chat_id,
                    f"Bắt đầu TTYT/KQHT cho mã trường: {school_code}, học kỳ: tất cả option trong modal",
                )
                result = self.run_pytest_command(
                    chat_id,
                    self.build_ttyt_command(school_code),
                    screenshot_name=f"ttyt_{school_code}_all",
                )
                self.send_command_result(
                    chat_id=chat_id,
                    title=f"Kết quả TTYT/KQHT mã trường {school_code} tất cả option",
                    return_code=result[0],
                    output=result[1],
                    screenshot_path=result[2],
                )
                return

            self.send_message(
                chat_id,
                f"Bắt đầu TTYT/KQHT cho mã trường: {school_code}, học kỳ: {', '.join(semesters)}",
            )
            all_logs = []
            summary_lines = []
            for semester in semesters:
                result = self.run_pytest_command(
                    chat_id,
                    self.build_ttyt_command(school_code, semester),
                    screenshot_name=f"ttyt_{school_code}_{semester}",
                )
                all_logs.append(f"===== TTYT/KQHT {school_code} {semester} =====\n{result[1]}")
                status = "SUCCESS" if result[0] == 0 else "FAIL"
                summary_lines.append(f"{school_code} {semester}: {status}")
                self.send_command_result(
                    chat_id=chat_id,
                    title=f"Kết quả TTYT/KQHT mã trường {school_code} {semester}",
                    return_code=result[0],
                    output=result[1],
                    screenshot_path=result[2],
                    save_log=False,
                )

            self.save_last_log(
                chat_id,
                f"Log TTYT/KQHT mã trường {school_code}",
                "\n\n".join(all_logs),
            )
            if len(semesters) > 1:
                self.send_message(
                    chat_id,
                    "\n".join(["Tổng kết TTYT/KQHT:"] + summary_lines + ["Gửi /log để xem log cuối."]),
                )
        finally:
            self.clear_chat_job(chat_id)

    def start_order_file_process(
        self, chat_id: int, document: dict, run_at: datetime | None
    ):
        file_name = document.get("file_name") or "orders.txt"
        try:
            content = self.download_telegram_text_file(document)
            orders = self.parse_order_file_content(content)
            if run_at is not None:
                job = self.schedule_order_file_job(
                    chat_id=chat_id,
                    file_name=file_name,
                    orders=orders,
                    run_at=run_at,
                )
                self.send_message(
                    chat_id,
                    "\n".join(
                        [
                            f"Đã nhận file {file_name}: {len(orders)} trường.",
                            f"Job ID: {job['job_id']}",
                            f"Sẽ chạy lúc: {self.format_datetime(run_at)}.",
                        ]
                    ),
                )
                self.clear_chat_job(chat_id)
                return

            self.send_message(
                chat_id,
                "\n".join(
                    [
                        f"Nhận file {file_name}: {len(orders)} trường.",
                        "Bắt đầu queue đồng bộ theo thứ tự trong file.",
                    ]
                ),
            )
            self.run_order_file_queue(chat_id, orders, file_name)
        except Exception as exc:
            self.send_message(chat_id, f"Không xử lý được file {file_name}: {exc}")
            self.clear_chat_job(chat_id)

    def run_order_file_queue(
        self, chat_id: int, orders: list[tuple[str, str]], file_name: str
    ):
        all_logs = []
        summary_lines = [f"Tổng kết order file {file_name}:"]

        try:
            for school_code, school_name in orders:
                school_label = self.format_order_school_label(school_code, school_name)
                self.send_message(chat_id, f"Queue TTLH: {school_label}")
                ttlh_code, ttlh_output, ttlh_screenshot = self.run_pytest_command(
                    chat_id,
                    self.build_ttlh_command(school_code),
                    screenshot_name=f"order_ttlh_{school_code}",
                )
                all_logs.append(f"===== TTLH {school_label} =====\n{ttlh_output}")
                ttlh_status = "SUCCESS" if ttlh_code == 0 else "FAIL"
                summary_lines.append(f"{school_label} TTLH: {ttlh_status}")
                self.send_command_result(
                    chat_id=chat_id,
                    title=f"Order TTLH {school_label}",
                    return_code=ttlh_code,
                    output=ttlh_output,
                    screenshot_path=ttlh_screenshot,
                    save_log=False,
                )

                if ttlh_code != 0:
                    summary_lines.append(f"{school_label} TTYT/KQHT: SKIP do TTLH fail")
                    continue

                self.send_message(
                    chat_id,
                    f"Queue TTYT/KQHT: {school_label} tất cả option trong modal",
                )
                ttyt_code, ttyt_output, ttyt_screenshot = self.run_pytest_command(
                    chat_id,
                    self.build_ttyt_command(school_code),
                    screenshot_name=f"order_ttyt_{school_code}_all",
                )
                all_logs.append(f"===== TTYT/KQHT {school_label} all =====\n{ttyt_output}")
                ttyt_status = "SUCCESS" if ttyt_code == 0 else "FAIL"
                summary_lines.append(f"{school_label} TTYT/KQHT all: {ttyt_status}")
                self.send_command_result(
                    chat_id=chat_id,
                    title=f"Order TTYT/KQHT {school_label} tất cả option",
                    return_code=ttyt_code,
                    output=ttyt_output,
                    screenshot_path=ttyt_screenshot,
                    save_log=False,
                )

            self.save_last_log(
                chat_id,
                f"Log order file {file_name}",
                "\n\n".join(all_logs),
            )
            self.send_message(chat_id, "\n".join(summary_lines + ["Gửi /log để xem log cuối."]))
        finally:
            self.clear_chat_job(chat_id)

    def start_scheduler_thread(self):
        thread = threading.Thread(target=self.scheduler_loop, daemon=True)
        thread.start()

    def scheduler_loop(self):
        while True:
            try:
                self.run_due_scheduled_jobs()
            except Exception as exc:
                print(f"Scheduler error: {exc}", file=sys.stderr)
            time.sleep(SCHEDULER_POLL_SECONDS)

    def run_due_scheduled_jobs(self):
        now = datetime.now()
        due_jobs = []

        with self.lock:
            for job in self.scheduled_order_jobs.values():
                run_at = datetime.fromisoformat(job["run_at"])
                if run_at <= now:
                    due_jobs.append(job)

            for job in due_jobs:
                self.scheduled_order_jobs.pop(job["job_id"], None)

            if due_jobs:
                self.save_scheduled_order_jobs_locked()

        for job in due_jobs:
            thread = threading.Thread(
                target=self.start_scheduled_order_file_job,
                args=(job,),
                daemon=True,
            )
            thread.start()

    def start_scheduled_order_file_job(self, job: dict):
        chat_id = int(job["chat_id"])
        file_name = job["file_name"]
        orders = self.deserialize_orders(job["orders"])

        with self.lock:
            process = self.active_jobs.get(chat_id)
            is_busy = chat_id in self.active_jobs and (
                process is None or process.poll() is None
            )
            if is_busy:
                next_run_at = datetime.now() + timedelta(minutes=1)
                job["run_at"] = next_run_at.isoformat(timespec="minutes")
                self.scheduled_order_jobs[job["job_id"]] = job
                self.save_scheduled_order_jobs_locked()
                busy_message = (
                    f"Job {job['job_id']} tới lịch nhưng chat đang bận. "
                    f"Dời sang {self.format_datetime(next_run_at)}."
                )
            else:
                busy_message = None
                self.active_jobs[chat_id] = None
                self.active_job_kinds[chat_id] = "order_file"

        if busy_message:
            self.send_message(chat_id, busy_message)
            return

        self.send_message(
            chat_id,
            f"Đến lịch chạy job {job['job_id']} từ file {file_name}: {len(orders)} trường.",
        )
        self.run_order_file_queue(chat_id, orders, file_name)

    def schedule_order_file_job(
        self, chat_id: int, file_name: str, orders: list[tuple[str, str]], run_at: datetime
    ):
        job = {
            "job_id": self.build_scheduled_job_id(chat_id),
            "chat_id": chat_id,
            "file_name": file_name,
            "orders": self.serialize_orders(orders),
            "run_at": run_at.isoformat(timespec="minutes"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self.lock:
            self.scheduled_order_jobs[job["job_id"]] = job
            self.save_scheduled_order_jobs_locked()
        return job

    def send_scheduled_jobs(self, chat_id: int):
        with self.lock:
            jobs = sorted(
                self.scheduled_order_jobs.values(),
                key=lambda item: item["run_at"],
            )

        if not jobs:
            self.send_message(chat_id, "Không có lịch order file nào đang chờ.")
            return

        lines = ["Lịch order file đang chờ:"]
        for job in jobs:
            run_at = datetime.fromisoformat(job["run_at"])
            order_count = len(job.get("orders") or [])
            lines.append(
                f"{job['job_id']} - {self.format_datetime(run_at)} - {job['file_name']} - {order_count} trường"
            )
        self.send_message(chat_id, "\n".join(lines))

    def handle_cancel_scheduled_job(self, chat_id: int, raw_value: str):
        job_id = raw_value.strip()
        if not job_id:
            self.send_message(chat_id, "Thiếu job_id. Ví dụ: /dongbo_cancel ord_...")
            return

        message = None
        with self.lock:
            job = self.scheduled_order_jobs.get(job_id)
            if job is None:
                message = f"Không tìm thấy lịch: {job_id}"
            elif int(job["chat_id"]) != chat_id:
                message = f"Không thể hủy lịch của chat khác: {job_id}"
            else:
                self.scheduled_order_jobs.pop(job_id, None)
                self.save_scheduled_order_jobs_locked()
                message = f"Đã hủy lịch: {job_id}"

        self.send_message(chat_id, message)

    def load_scheduled_order_jobs(self):
        if not SCHEDULED_JOBS_PATH.exists():
            return {}

        try:
            data = json.loads(SCHEDULED_JOBS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Cannot read scheduled jobs: {exc}", file=sys.stderr)
            return {}

        jobs = {}
        for job in data.get("jobs", []):
            try:
                job_id = str(job["job_id"])
                datetime.fromisoformat(str(job["run_at"]))
                jobs[job_id] = job
            except (KeyError, ValueError, TypeError):
                continue
        return jobs

    def save_scheduled_order_jobs_locked(self):
        SCHEDULED_JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "jobs": sorted(
                self.scheduled_order_jobs.values(),
                key=lambda item: item["run_at"],
            )
        }
        tmp_path = SCHEDULED_JOBS_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(SCHEDULED_JOBS_PATH)

    def build_scheduled_job_id(self, chat_id: int):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"ord_{timestamp}_{chat_id}_{int(time.time() * 1000) % 100000}"

    def serialize_orders(self, orders: list[tuple[str, str]]):
        return [{"code": code, "name": name} for code, name in orders]

    def deserialize_orders(self, orders: list[dict]):
        return [(str(item["code"]), str(item.get("name") or "")) for item in orders]

    def run_sync_queue(self, chat_id: int, school_codes: list[str], semesters: list[str]):
        all_logs = []
        semester_label = ", ".join(semesters) if semesters else "tất cả option trong modal"
        summary_lines = [
            f"Bắt đầu queue {len(school_codes)} trường, học kỳ: {semester_label}"
        ]
        self.send_message(chat_id, summary_lines[0])

        try:
            for school_code in school_codes:
                self.send_message(chat_id, f"Queue TTLH: {school_code}")
                ttlh_code, ttlh_output, ttlh_screenshot = self.run_pytest_command(
                    chat_id,
                    self.build_ttlh_command(school_code),
                    screenshot_name=f"queue_ttlh_{school_code}",
                )
                all_logs.append(f"===== TTLH {school_code} =====\n{ttlh_output}")
                ttlh_status = "SUCCESS" if ttlh_code == 0 else "FAIL"
                summary_lines.append(f"{school_code} TTLH: {ttlh_status}")
                self.send_command_result(
                    chat_id=chat_id,
                    title=f"Queue TTLH mã trường {school_code}",
                    return_code=ttlh_code,
                    output=ttlh_output,
                    screenshot_path=ttlh_screenshot,
                    save_log=False,
                )

                if ttlh_code != 0:
                    summary_lines.append(f"{school_code} TTYT/KQHT: SKIP do TTLH fail")
                    continue

                if not semesters:
                    self.send_message(
                        chat_id,
                        f"Queue TTYT/KQHT: {school_code} tất cả option trong modal",
                    )
                    ttyt_code, ttyt_output, ttyt_screenshot = self.run_pytest_command(
                        chat_id,
                        self.build_ttyt_command(school_code),
                        screenshot_name=f"queue_ttyt_{school_code}_all",
                    )
                    all_logs.append(
                        f"===== TTYT/KQHT {school_code} all =====\n{ttyt_output}"
                    )
                    ttyt_status = "SUCCESS" if ttyt_code == 0 else "FAIL"
                    summary_lines.append(f"{school_code} TTYT/KQHT all: {ttyt_status}")
                    self.send_command_result(
                        chat_id=chat_id,
                        title=f"Queue TTYT/KQHT mã trường {school_code} tất cả option",
                        return_code=ttyt_code,
                        output=ttyt_output,
                        screenshot_path=ttyt_screenshot,
                        save_log=False,
                    )
                    continue

                for semester in semesters:
                    self.send_message(chat_id, f"Queue TTYT/KQHT: {school_code} {semester}")
                    ttyt_code, ttyt_output, ttyt_screenshot = self.run_pytest_command(
                        chat_id,
                        self.build_ttyt_command(school_code, semester),
                        screenshot_name=f"queue_ttyt_{school_code}_{semester}",
                    )
                    all_logs.append(
                        f"===== TTYT/KQHT {school_code} {semester} =====\n{ttyt_output}"
                    )
                    ttyt_status = "SUCCESS" if ttyt_code == 0 else "FAIL"
                    summary_lines.append(f"{school_code} TTYT/KQHT {semester}: {ttyt_status}")
                    self.send_command_result(
                        chat_id=chat_id,
                        title=f"Queue TTYT/KQHT mã trường {school_code} {semester}",
                        return_code=ttyt_code,
                        output=ttyt_output,
                        screenshot_path=ttyt_screenshot,
                        save_log=False,
                    )

            self.save_last_log(chat_id, "Log queue đồng bộ gần nhất", "\n\n".join(all_logs))
            self.send_message(
                chat_id,
                "\n".join(summary_lines + ["Gửi /log để xem log cuối."]),
            )
        finally:
            self.clear_chat_job(chat_id)

    def build_ttlh_command(self, school_code: str):
        return self.build_pytest_command(
            school_code=school_code,
            test_name="test_dong_bo_du_lieu_truong_hoc",
        )

    def build_ttyt_command(self, school_code: str, semester: str | None = None):
        extra_args = [f"--semester={semester}"] if semester else None
        return self.build_pytest_command(
            school_code=school_code,
            test_name="test_dong_bo_kqht_y_te",
            extra_args=extra_args,
        )

    def build_pytest_command(
        self, school_code: str, test_name: str, extra_args: list[str] | None = None
    ):
        command = [
            sys.executable,
            "-m",
            "pytest",
            TEST_FILE,
            "-k",
            test_name,
            f"--school-code={school_code}",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=-v --browser chromium",
        ]
        if extra_args:
            command.extend(extra_args)
        return command

    def run_pytest_command(
        self, chat_id: int, command: list[str], screenshot_name: str | None = None
    ):
        screenshot_path = self.build_screenshot_path(screenshot_name)
        process = subprocess.Popen(
            command,
            cwd=ROOT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.build_subprocess_env(screenshot_path),
        )

        with self.lock:
            self.active_jobs[chat_id] = process

        output, _ = process.communicate()
        with self.lock:
            if chat_id in self.active_jobs:
                self.active_jobs[chat_id] = None
        return process.returncode, output, screenshot_path

    def clear_chat_job(self, chat_id: int):
        with self.lock:
            self.pending_order_file_requests.pop(chat_id, None)
            self.active_jobs.pop(chat_id, None)
            self.active_job_kinds.pop(chat_id, None)

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

    def parse_single_school_code(self, raw_value: str):
        tokens = self.tokenize_request(raw_value)
        if len(tokens) != 1 or not SCHOOL_CODE_RE.fullmatch(tokens[0]):
            return None
        return tokens[0]

    def parse_school_and_semesters(self, raw_value: str):
        tokens = self.tokenize_request(raw_value)
        school_codes = []
        semesters = []

        for token in tokens:
            lowered = token.lower()
            if lowered in SEMESTERS:
                semesters.append(lowered)
            elif SCHOOL_CODE_RE.fullmatch(token):
                school_codes.append(token)
            else:
                return None, []

        if len(school_codes) != 1:
            return None, []
        return school_codes[0], semesters

    def parse_queue_request(self, raw_value: str):
        tokens = self.tokenize_request(raw_value)
        school_codes = []
        semesters = []

        for token in tokens:
            lowered = token.lower()
            if lowered in SEMESTERS:
                semesters.append(lowered)
            elif SCHOOL_CODE_RE.fullmatch(token):
                school_codes.append(token)
            else:
                return [], []

        return school_codes, semesters

    def parse_order_file_schedule(self, raw_value: str):
        value = raw_value.strip()
        if not value:
            return None

        match = re.fullmatch(r"at\s+(.+)", value, flags=re.IGNORECASE)
        if not match:
            raise ValueError(
                "Tham số lịch không hợp lệ. Dùng: /dongbo_order_file at YYYY-MM-DD HH:mm"
            )

        raw_datetime = match.group(1).strip()
        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
            try:
                run_at = datetime.strptime(raw_datetime, fmt)
                break
            except ValueError:
                run_at = None
        if run_at is None:
            raise ValueError(
                "Ngày giờ không hợp lệ. Dùng một trong các dạng: "
                "YYYY-MM-DD HH:mm, DD/MM/YYYY HH:mm, DD-MM-YYYY HH:mm."
            )

        if run_at <= datetime.now():
            raise ValueError("Thời gian đặt lịch phải sau thời điểm hiện tại.")
        return run_at

    def format_datetime(self, value: datetime):
        return value.strftime("%Y-%m-%d %H:%M")

    def download_telegram_text_file(self, document: dict):
        file_name = document.get("file_name") or ""
        if not file_name.lower().endswith(".txt"):
            raise ValueError("File không hợp lệ. Hãy gửi file .txt.")

        file_size = int(document.get("file_size") or 0)
        if file_size > MAX_ORDER_FILE_SIZE_BYTES:
            raise ValueError("File quá lớn. Kích thước tối đa là 1 MB.")

        file_id = document.get("file_id")
        if not file_id:
            raise ValueError("File Telegram thiếu file_id.")

        file_response = self.request("getFile", {"file_id": file_id})
        file_path = (file_response.get("result") or {}).get("file_path")
        if not file_path:
            raise ValueError("Không lấy được đường dẫn file từ Telegram.")

        quoted_path = urllib.parse.quote(file_path, safe="/")
        file_url = f"https://api.telegram.org/file/bot{self.token}/{quoted_path}"
        with urllib.request.urlopen(file_url, timeout=60) as response:
            data = response.read(MAX_ORDER_FILE_SIZE_BYTES + 1)

        if len(data) > MAX_ORDER_FILE_SIZE_BYTES:
            raise ValueError("File quá lớn. Kích thước tối đa là 1 MB.")

        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    def parse_order_file_content(self, content: str):
        orders = []
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            school_code = parts[0].strip()
            school_name = parts[1].strip() if len(parts) > 1 else ""

            if not SCHOOL_CODE_RE.fullmatch(school_code):
                raise ValueError(f"Dòng {line_number}: mã trường không hợp lệ: {school_code}")

            orders.append((school_code, school_name))

        if not orders:
            raise ValueError("File không có dòng trường hợp lệ.")
        return orders

    def format_order_school_label(self, school_code: str, school_name: str):
        if school_name:
            return f"{school_code} - {school_name}"
        return school_code

    def tokenize_request(self, raw_value: str):
        return [item for item in re.split(r"[\s,]+", raw_value.strip()) if item]

    def send_command_result(
        self,
        chat_id: int,
        title: str,
        return_code: int,
        output: str,
        screenshot_path: Path | None,
        save_log: bool = True,
    ):
        status = "SUCCESS" if return_code == 0 else "FAIL"
        summary = self.extract_pytest_summary(output)
        if save_log:
            self.save_last_log(chat_id, title.replace("Kết quả", "Log"), output)

        message = "\n".join(
            [
                f"{title}: {status}",
                f"Exit code: {return_code}",
                f"Tóm tắt: {summary}",
                "Gửi /log để xem log cuối.",
            ]
        )
        if screenshot_path and screenshot_path.exists():
            self.send_photo(chat_id, screenshot_path, message)
        else:
            self.send_message(chat_id, message)

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

    def extract_pytest_summary(self, output: str):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        for line in reversed(lines):
            if " passed" in line or " failed" in line or " error" in line:
                return line.strip("= ")
        return "Không tìm thấy dòng tổng kết pytest."

    def tail_text(self, text: str, max_chars: int):
        text = text.strip()
        if len(text) <= max_chars:
            return text
        return "...\n" + text[-max_chars:]

    def send_message(self, chat_id: int, text: str):
        chunks = self.split_message(text)
        for chunk in chunks:
            self.request(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
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
        help="Telegram bot token. Nếu bỏ trống sẽ đọc TELEGRAM_BOT_TOKEN.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")

    token = args.token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Thiếu TELEGRAM_BOT_TOKEN trong .env hoặc tham số --token.")

    allowed_chat_ids = parse_allowed_chat_ids(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS"))
    bot = TelegramBot(token=token, allowed_chat_ids=allowed_chat_ids)
    bot.run_forever()


if __name__ == "__main__":
    main()
