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
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
TEST_FILE = "tests/test_dong_bo.py"
LOGIN_SCRIPT = "scripts/save_login.py"
SCREENSHOT_DIR = ROOT_DIR / "artifacts" / "screenshots"
SCHOOL_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,30}$")
SEMESTERS = {"hk1", "hk2", "cn"}
MAX_TELEGRAM_MESSAGE_LENGTH = 4096


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

    def run_forever(self):
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

        if not chat_id or not text:
            return

        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            self.send_message(chat_id, "Chat này chưa được phép chạy bot.")
            return

        command, argument = self.parse_command(text)
        if command == "/start":
            self.send_start(chat_id)
        elif command == "/help":
            self.send_help(chat_id)
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
                    "/dongbo_ttyt <ma_truong> [hk1|hk2|cn] - đồng bộ KQHT/Y tế; bỏ học kỳ sẽ chạy hk1, hk2, cn",
                    "/dongbo <ma_1>, <ma_2> [hk1|hk2|cn] - queue TTLH rồi TTYT; bỏ học kỳ sẽ chạy hk1, hk2, cn",
                    "/status - xem tiến trình đang chạy",
                    "/log - xem log cuối của tác vụ gần nhất",
                    "/help - xem hướng dẫn",
                    "",
                    "Ví dụ:",
                    "/dongbo_ttlh 7900001",
                    "/dongbo_ttyt 7900001 hk1",
                    "/dongbo 7900001, 7900002 hk1",
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
            elif kind == "ttyt":
                self.send_message(chat_id, "Đang chạy đồng bộ KQHT/Y tế. Vui lòng chờ kết quả.")
            else:
                self.send_message(
                    chat_id,
                    "Đang chạy đồng bộ TTLH. Vui lòng chờ kết quả.",
                )
            return

        self.send_message(chat_id, "Không có tác vụ nào đang chạy.")

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

    def run_sync_queue(self, chat_id: int, school_codes: list[str], semesters: list[str]):
        all_logs = []
        summary_lines = [
            f"Bắt đầu queue {len(school_codes)} trường, học kỳ: {', '.join(semesters)}"
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

    def build_ttyt_command(self, school_code: str, semester: str):
        return self.build_pytest_command(
            school_code=school_code,
            test_name="test_dong_bo_kqht_y_te",
            extra_args=[f"--semester={semester}"],
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
        if not semesters:
            semesters = ["hk1", "hk2", "cn"]
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

        if not semesters:
            semesters = ["hk1", "hk2", "cn"]
        return school_codes, semesters

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
