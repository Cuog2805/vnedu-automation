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

from bot_config import (
    MAX_ORDER_FILE_SIZE_BYTES,
    ROOT_DIR,
    SCHOOL_CODE_RE,
    SEMESTERS,
    TEST_FILE,
)


class DongBoHandler:
    def handle_ttlh_request(self, chat_id: int, raw_value: str):
        school_code = self.parse_single_school_query(raw_value)
        if school_code is None:
            self.send_message(chat_id, "Thiếu mã hoặc tên trường. Ví dụ: /dongbo_ttlh 7900001 hoặc /dongbo_ttlh Trường THCS A")
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
                "Thiếu hoặc sai tham số. Ví dụ: /dongbo_ttyt 7900001 hoặc /dongbo_ttyt Trường THCS A hk1",
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
                "Thiếu mã hoặc tên trường. Ví dụ: /dongbo 7900001, Trường THCS A hoặc /dongbo 7900001, Trường THCS A hk1",
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

    def run_single_ttlh(self, chat_id: int, school_code: str):
        try:
            self.send_message(chat_id, f"Bắt đầu TTLH cho mã trường: {school_code}")
            result = self.run_pytest_command(
                chat_id,
                self.build_ttlh_command(school_code),
            )
            if self.is_cancel_requested(chat_id):
                self.send_message(chat_id, f"Da huy TTLH ma truong {school_code}.")
                return
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
                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, f"Da huy TTYT/KQHT ma truong {school_code}.")
                    return
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
                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, f"Da huy TTYT/KQHT ma truong {school_code}.")
                    return
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
        summary_lines = [f"Tong ket order file {file_name}:"]

        try:
            for school_code, school_name in orders:
                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, "Da huy queue dong bo tu file.")
                    return

                school_label = self.format_order_school_label(school_code, school_name)
                self.send_message(chat_id, f"Dang dong bo: {school_label}")

                ttlh_code, ttlh_output, ttlh_screenshot = self.run_pytest_command(
                    chat_id,
                    self.build_ttlh_command(school_code),
                    screenshot_name=f"order_ttlh_{school_code}",
                )
                all_logs.append(f"===== TTLH {school_label} =====\n{ttlh_output}")
                ttlh_status = "SUCCESS" if ttlh_code == 0 else "FAIL"

                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, f"Da huy khi dang dong bo: {school_label}")
                    return

                ttyt_code = None
                ttyt_output = ""
                ttyt_screenshot = None
                ttyt_status = "SKIP do TTLH fail"

                if ttlh_code == 0:
                    ttyt_code, ttyt_output, ttyt_screenshot = self.run_pytest_command(
                        chat_id,
                        self.build_ttyt_command(school_code),
                        screenshot_name=f"order_ttyt_{school_code}_all",
                    )
                    all_logs.append(f"===== TTYT/KQHT {school_label} all =====\n{ttyt_output}")
                    ttyt_status = "SUCCESS" if ttyt_code == 0 else "FAIL"

                    if self.is_cancel_requested(chat_id):
                        self.send_message(chat_id, f"Da huy khi dang dong bo: {school_label}")
                        return

                final_status = "SUCCESS" if ttlh_code == 0 and (ttyt_code is None or ttyt_code == 0) else "FAIL"
                summary_lines.append(f"{school_label}: {final_status} (TTLH: {ttlh_status}, TTYT/KQHT: {ttyt_status})")
                self.send_order_school_result(
                    chat_id=chat_id,
                    school_label=school_label,
                    final_status=final_status,
                    ttlh_status=ttlh_status,
                    ttyt_status=ttyt_status,
                    ttlh_code=ttlh_code,
                    ttyt_code=ttyt_code,
                    screenshot_path=ttyt_screenshot or ttlh_screenshot,
                )

            self.save_last_log(
                chat_id,
                f"Log order file {file_name}",
                "\n\n".join(all_logs),
            )
            self.send_message(chat_id, "\n".join(summary_lines + ["Gui /log de xem log cuoi."]))
        finally:
            self.clear_chat_job(chat_id)

    def send_order_school_result(
        self,
        chat_id: int,
        school_label: str,
        final_status: str,
        ttlh_status: str,
        ttyt_status: str,
        ttlh_code: int,
        ttyt_code: int | None,
        screenshot_path: Path | None,
    ):
        lines = [
            f"Order {school_label}: {final_status}",
            f"TTLH: {ttlh_status} (exit {ttlh_code})",
            f"TTYT/KQHT: {ttyt_status}"
            + (f" (exit {ttyt_code})" if ttyt_code is not None else ""),
            "Gui /log de xem log chi tiet.",
        ]
        message = "\n".join(lines)
        if screenshot_path and screenshot_path.exists():
            self.send_photo(chat_id, screenshot_path, message)
        else:
            self.send_message(chat_id, message)

    def run_sync_queue(self, chat_id: int, school_codes: list[str], semesters: list[str]):
        all_logs = []
        semester_label = ", ".join(semesters) if semesters else "tất cả option trong modal"
        summary_lines = [
            f"Bắt đầu queue {len(school_codes)} trường, học kỳ: {semester_label}"
        ]
        self.send_message(chat_id, summary_lines[0])

        try:
            for school_code in school_codes:
                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, "Da huy queue dong bo.")
                    return

                self.send_message(chat_id, f"Queue TTLH: {school_code}")
                ttlh_code, ttlh_output, ttlh_screenshot = self.run_pytest_command(
                    chat_id,
                    self.build_ttlh_command(school_code),
                    screenshot_name=f"queue_ttlh_{school_code}",
                )
                all_logs.append(f"===== TTLH {school_code} =====\n{ttlh_output}")
                if self.is_cancel_requested(chat_id):
                    self.send_message(chat_id, f"Da huy khi dang queue: {school_code}")
                    return

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
                    if self.is_cancel_requested(chat_id):
                        self.send_message(chat_id, f"Da huy khi dang queue: {school_code}")
                        return

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
                    if self.is_cancel_requested(chat_id):
                        self.send_message(chat_id, "Da huy queue dong bo.")
                        return

                    self.send_message(chat_id, f"Queue TTYT/KQHT: {school_code} {semester}")
                    ttyt_code, ttyt_output, ttyt_screenshot = self.run_pytest_command(
                        chat_id,
                        self.build_ttyt_command(school_code, semester),
                        screenshot_name=f"queue_ttyt_{school_code}_{semester}",
                    )
                    all_logs.append(
                        f"===== TTYT/KQHT {school_code} {semester} =====\n{ttyt_output}"
                    )
                    if self.is_cancel_requested(chat_id):
                        self.send_message(chat_id, f"Da huy khi dang queue: {school_code} {semester}")
                        return

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

    def parse_single_school_query(self, raw_value: str):
        value = raw_value.strip()
        return value or None

    def parse_single_school_code(self, raw_value: str):
        return self.parse_single_school_query(raw_value)

    def parse_school_and_semesters(self, raw_value: str):
        tokens = raw_value.strip().split()
        if not tokens:
            return None, []

        semesters = []
        while tokens and tokens[-1].lower() in SEMESTERS:
            semesters.insert(0, tokens.pop().lower())

        school_query = " ".join(tokens).strip()
        if not school_query:
            return None, []
        return school_query, semesters

    def parse_queue_request(self, raw_value: str):
        value = raw_value.strip()
        if not value:
            return [], []

        semesters = []
        parts = [part.strip() for part in value.split(",")]
        while parts:
            last_tokens = parts[-1].split()
            moved = False
            while last_tokens and last_tokens[-1].lower() in SEMESTERS:
                semesters.insert(0, last_tokens.pop().lower())
                moved = True
            if moved:
                parts[-1] = " ".join(last_tokens).strip()
                if not parts[-1]:
                    parts.pop()
                continue
            break

        school_queries = [part for part in parts if part]
        return school_queries, semesters

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
            if not line or line.startswith("#"):  # [CRAWL] bỏ qua dòng comment
                continue

            if "|" in line:
                parts = [part.strip() for part in line.split("|")]
                school_code = parts[0]
                school_name = parts[2] if len(parts) > 2 else ""
            else:
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

    def extract_pytest_summary(self, output: str):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        for line in reversed(lines):
            if " passed" in line or " failed" in line or " error" in line:
                return line.strip("= ")
        return "Không tìm thấy dòng tổng kết pytest."
