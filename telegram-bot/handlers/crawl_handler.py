import logging
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import json
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DOI_TAC = "VNPT_NBH"
DOI_TAC_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
ALLOWED_TEN_DON_VI = {
    "Xã Thanh Liêm",
    "Xã Trần Thương",
    "Phường Kim Thanh",
    "Xã Bắc Lý",
    "Xã Thanh Lâm",
    "Xã Bình Mỹ",
    "Xã Bình Sơn",
    "Xã Bình Giang",
    "Phường Duy Tân",
    "Xã Bình Lục",
    "Phường Lê Hồ",
    "Xã Thanh Bình",
    "Phường Hà Nam",
    "Phường Duy Hà",
    "Phường Kim Bảng",
    "Phường Tam Chúc",
    "Phường Liêm Tuyền",
    "Phường Phù Vân",
    "Phường Tiên Sơn",
    "Phường Duy Tiên",
    "Xã Tân Thanh",
    "Phường Đồng Văn",
    "Xã Bình An",
    "Xã Nhân Hà",
    "Xã Vĩnh Trụ",
    "Phường Lý Thường Kiệt",
    "Phường Phủ Lý",
    "Xã Nam Lý",
    "Phường Nguyễn Uý",
    "Xã Nam Xang",
    "Xã Liêm Hà",
    "Xã Lý Nhân",
    "Phường Châu Sơn",
}

ROOT_DIR = Path(__file__).resolve().parents[2]
SAVE_CSDL_LOGIN_SCRIPT = ROOT_DIR / "scripts" / "save_csdl_login.py"


class SessionExpiredError(Exception):
    """Session CSDL hết hạn hoặc chưa đăng nhập."""
    pass


class CrawlHandler:
    """
    Mixin tích hợp vào TelegramBot.
    Dùng các method send_message, reserve_chat_job, clear_chat_job,
    run_order_file_queue, schedule_order_file_job, format_datetime
    từ TelegramBot.
    """

    # ------------------------------------------------------------------
    # /crawl_login — đăng nhập thủ công, lưu session
    # ------------------------------------------------------------------

    def handle_crawl_login_request(self, chat_id: int):
        """Mở trình duyệt để đăng nhập thủ công vào CSDL."""
        with self.lock:
            process = self.active_jobs.get(chat_id)
            if chat_id in self.active_jobs and (process is None or process.poll() is None):
                self.send_message(
                    chat_id,
                    "Chat này đang có một tác vụ chạy. Chờ xong rồi chạy tiếp.",
                )
                return
            self.active_jobs[chat_id] = None
            self.active_job_kinds[chat_id] = "crawl_login"

        thread = threading.Thread(
            target=self._run_csdl_login_process,
            args=(chat_id,),
            daemon=True,
        )
        thread.start()

    def _run_csdl_login_process(self, chat_id: int):
        self.send_message(
            chat_id,
            "\n".join([
                "Đang mở trình duyệt tới dongbo.csdl.edu.vn.",
                "Hãy đăng nhập thủ công trên máy chạy bot.",
                "Sau khi đăng nhập xong, gửi /crawl_login_done để lưu phiên.",
            ]),
        )

        try:
            process = subprocess.Popen(
                [sys.executable, str(SAVE_CSDL_LOGIN_SCRIPT)],
                cwd=ROOT_DIR,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.build_subprocess_env(),
            )
        except Exception as exc:
            self.send_message(chat_id, f"Không chạy được script đăng nhập CSDL: {exc}")
            self.clear_chat_job(chat_id)
            return

        with self.lock:
            self.active_jobs[chat_id] = process

        # Chờ process kết thúc (script tự kết thúc sau khi lưu session)
        while process.poll() is None:
            time.sleep(1)

        if self.is_cancel_requested(chat_id):
            self.clear_chat_job(chat_id)
            return

        self._finish_csdl_login_process(chat_id, process)

    def handle_crawl_login_done(self, chat_id: int):
        """Nhận tín hiệu từ người dùng: đã đăng nhập xong, lưu session."""
        with self.lock:
            process = self.active_jobs.get(chat_id)
            kind = self.active_job_kinds.get(chat_id)

        if kind != "crawl_login" or process is None:
            self.send_message(chat_id, "Không có phiên đăng nhập CSDL nào đang chờ.")
            return

        if process.poll() is not None:
            # Process đã tự kết thúc (script tự nhận Enter từ terminal)
            self._finish_csdl_login_process(chat_id, process)
            return

        # Gửi Enter để script tiếp tục lưu session
        try:
            process.stdin.write("\n")
            process.stdin.flush()
            process.stdin.close()
        except OSError as exc:
            self.send_message(chat_id, f"Không gửi được tín hiệu lưu phiên: {exc}")
            return

        self.send_message(chat_id, "Đã nhận tín hiệu lưu phiên CSDL. Đang chờ script hoàn tất.")

    def _finish_csdl_login_process(self, chat_id: int, process: subprocess.Popen):
        output = process.stdout.read() if process.stdout else ""
        return_code = process.wait()

        self.clear_chat_job(chat_id)

        from crawl.session_store import CSDL_AUTH_STATE_PATH, is_session_available
        status = "PASS" if return_code == 0 else "FAIL"
        session_available = is_session_available()
        file_status = (
            f"✓ Đã lưu phiên vào {CSDL_AUTH_STATE_PATH.name}"
            if session_available
            else "✗ Chưa thấy file csdl_auth_state.json — đăng nhập có thành công không?"
        )
        lines = [
            f"Kết quả đăng nhập CSDL: {status}",
            file_status,
        ]
        if return_code == 0 and session_available:
            lines.append("Giờ có thể dùng /crawl để lấy danh sách trường.")
        else:
            lines.extend(
                [
                    "Gửi /log để xem log lỗi đăng nhập CSDL.",
                    "Sau khi sửa lỗi, chạy lại /login ở chế độ CSDL.",
                ]
            )
        self.save_last_log(chat_id, "Log đăng nhập CSDL gần nhất", output)
        self.send_message(chat_id, "\n".join(lines))

    # ------------------------------------------------------------------
    # /crawl [maDoiTac]
    # ------------------------------------------------------------------

    def handle_crawl_request(self, chat_id: int, raw_value: str):
        doi_tac = self._parse_doi_tac(raw_value) or DEFAULT_DOI_TAC

        if not self._check_session_or_notify(chat_id):
            return

        if not self.reserve_chat_job(chat_id, "crawl"):
            return

        thread = threading.Thread(
            target=self._run_crawl_and_export,
            args=(chat_id, doi_tac, False),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # /crawl_queue [maDoiTac]
    # ------------------------------------------------------------------

    def handle_crawl_queue_request(self, chat_id: int, raw_value: str):
        doi_tac = self._parse_doi_tac(raw_value) or DEFAULT_DOI_TAC

        if not self._check_session_or_notify(chat_id):
            return

        if not self.reserve_chat_job(chat_id, "crawl_queue"):
            return

        thread = threading.Thread(
            target=self._run_crawl_and_export,
            args=(chat_id, doi_tac, True),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # /crawl_schedule [maDoiTac] at YYYY-MM-DD HH:mm
    # ------------------------------------------------------------------

    def handle_crawl_schedule_request(self, chat_id: int, raw_value: str):
        doi_tac, run_at = self._parse_crawl_schedule(raw_value, chat_id)
        if doi_tac is None:
            return

        if not self._check_session_or_notify(chat_id):
            return

        if not self.reserve_chat_job(chat_id, "crawl_schedule"):
            return

        thread = threading.Thread(
            target=self._run_crawl_then_schedule,
            args=(chat_id, doi_tac, run_at),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Core crawl runner
    # ------------------------------------------------------------------

    def _run_crawl_and_export(
        self, chat_id: int, doi_tac: str, run_queue_after: bool
    ):
        try:
            self.send_message(
                chat_id,
                f"Đang crawl danh sách trường ({doi_tac})...",
            )

            rows = self._do_crawl(chat_id, doi_tac)
            if rows is None:
                return  # session hết hạn, đã thông báo

            if not rows:
                self.send_message(
                    chat_id,
                    f"Không có trường nào cho đối tác {doi_tac}. "
                    "Kiểm tra lại mã đối tác.",
                )
                return

            txt_content = _rows_to_txt(rows, doi_tac)
            filename = f"truong_{doi_tac}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            self._send_txt_document(chat_id, txt_content, filename)
            self.send_message(chat_id, f"✓ Crawl xong: {len(rows)} trường ({doi_tac}).")

            orders = _rows_to_orders(rows)
            if self.is_cancel_requested(chat_id):
                self.send_message(chat_id, "Da huy crawl.")
                return

            if run_queue_after:
                self.send_message(
                    chat_id,
                    f"Bắt đầu queue đồng bộ {len(orders)} trường...",
                )
                # run_order_file_queue tự gọi clear_chat_job khi xong
                self.run_order_file_queue(chat_id, orders, filename)
                return

            self.send_message(
                chat_id,
                "\n".join([
                    f"Đã crawl {len(orders)} trường.",
                    f"Gõ /crawl_queue {doi_tac} để chạy queue đồng bộ ngay,",
                    f"hoặc /crawl_schedule {doi_tac} at YYYY-MM-DD HH:mm để đặt lịch.",
                ]),
            )

        except Exception as exc:
            logger.error(f"[CrawlHandler] crawl error: {exc}", exc_info=True)
            self.send_message(chat_id, f"Lỗi khi crawl: {exc}")
            self.clear_chat_job(chat_id)
        finally:
            # Chỉ clear nếu không chạy queue (queue tự clear)
            if not run_queue_after:
                self.clear_chat_job(chat_id)

    def _run_crawl_then_schedule(
        self, chat_id: int, doi_tac: str, run_at: datetime
    ):
        try:
            self.send_message(
                chat_id,
                f"Đang crawl ({doi_tac}) để chuẩn bị lịch {self.format_datetime(run_at)}...",
            )

            rows = self._do_crawl(chat_id, doi_tac)
            if rows is None:
                return

            if not rows:
                self.send_message(chat_id, f"Không có trường nào cho {doi_tac}.")
                return

            txt_content = _rows_to_txt(rows, doi_tac)
            filename = f"truong_{doi_tac}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            self._send_txt_document(chat_id, txt_content, filename)

            orders = _rows_to_orders(rows)
            job = self.schedule_order_file_job(
                chat_id=chat_id,
                file_name=filename,
                orders=orders,
                run_at=run_at,
            )

            self.send_message(
                chat_id,
                "\n".join([
                    f"✓ Crawl xong: {len(orders)} trường.",
                    f"Job ID: {job['job_id']}",
                    f"Sẽ chạy queue đồng bộ lúc: {self.format_datetime(run_at)}.",
                    "Gõ /dongbo_schedule để xem danh sách lịch.",
                ]),
            )

        except Exception as exc:
            logger.error(f"[CrawlHandler] schedule error: {exc}", exc_info=True)
            self.send_message(chat_id, f"Lỗi khi crawl/đặt lịch: {exc}")
        finally:
            self.clear_chat_job(chat_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _do_crawl(self, chat_id: int, doi_tac: str) -> list[dict] | None:
        """
        Thực hiện crawl. Trả về list rows, hoặc None nếu session hết hạn.
        None = đã thông báo cho người dùng, caller chỉ cần return.
        """
        from crawl.session_store import load_session_cookie
        from crawl.csdl_client import CSDLClient, CSDLApiError

        try:
            session_cookie = load_session_cookie()
        except FileNotFoundError as exc:
            self.send_message(chat_id, str(exc))
            return None

        try:
            client = CSDLClient(session_cookie=session_cookie)
            rows = client.fetch_all(doi_tac=doi_tac)
            return _filter_rows_by_ten_don_vi(rows)
        except CSDLApiError as exc:
            error_msg = str(exc)
            if "401" in error_msg or "403" in error_msg or "redirect" in error_msg.lower():
                self.send_message(
                    chat_id,
                    "\n".join([
                        "Session CSDL đã hết hạn hoặc chưa đủ quyền.",
                        "Hãy chạy /login ở chế độ CSDL để đăng nhập lại.",
                    ]),
                )
                return None
            raise

    def _check_session_or_notify(self, chat_id: int) -> bool:
        """
        Kiểm tra file session tồn tại trước khi reserve job.
        Trả về True nếu OK, False nếu chưa có session (đã thông báo).
        """
        from crawl.session_store import is_session_available
        if not is_session_available():
            self.send_message(
                chat_id,
                "\n".join([
                    "Chưa có phiên đăng nhập CSDL.",
                    "Hãy chạy /crawl_login trước.",
                ]),
            )
            return False
        return True

    def _parse_doi_tac(self, raw_value: str) -> str | None:
        value = raw_value.strip()
        if not value:
            return None
        candidate = value.split()[0].upper()
        return candidate if DOI_TAC_RE.fullmatch(candidate) else None

    def _parse_crawl_schedule(
        self, raw_value: str, chat_id: int
    ) -> tuple[str | None, datetime | None]:
        match = re.fullmatch(
            r"([A-Za-z0-9_]{3,30})\s+at\s+(.+)",
            raw_value.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            self.send_message(
                chat_id,
                "Cú pháp: /crawl_schedule <maDoiTac> at YYYY-MM-DD HH:mm\n"
                "Ví dụ: /crawl_schedule VNPT_NBH at 2026-06-10 22:00",
            )
            return None, None

        doi_tac = match.group(1).upper()
        raw_dt = match.group(2).strip()
        run_at = None

        for fmt in ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
            try:
                run_at = datetime.strptime(raw_dt, fmt)
                break
            except ValueError:
                pass

        if run_at is None:
            self.send_message(chat_id, "Ngày giờ không hợp lệ. Dùng: YYYY-MM-DD HH:mm")
            return None, None

        if run_at <= datetime.now():
            self.send_message(chat_id, "Thời gian phải sau thời điểm hiện tại.")
            return None, None

        return doi_tac, run_at

    def _send_txt_document(self, chat_id: int, content: str, filename: str):
        """Gửi nội dung TXT về Telegram dưới dạng file đính kèm."""
        data_bytes = content.encode("utf-8-sig")
        boundary = f"----crawl-{int(time.time() * 1000)}"
        body = b"".join([
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="chat_id"\r\n\r\n',
            f"{chat_id}\r\n".encode(),
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="document"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
            data_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ])

        req = urllib.request.Request(
            f"{self.api_base}/sendDocument",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if not result.get("ok"):
            raise RuntimeError(f"Telegram sendDocument thất bại: {result}")


# ------------------------------------------------------------------
# Helpers thuần (không cần self)
# ------------------------------------------------------------------

def _rows_to_txt(rows: list[dict], doi_tac: str) -> str:
    """
    Chuyển rows thành TXT tương thích parse_order_file_content() của bot.
    Mỗi dòng: <maTruongHoc> | <tenDonVi> | <tenTruongHoc>
    Dòng bắt đầu bằng # là comment, bot bỏ qua.
    """
    lines = [
        f"# Crawl từ CSDL Giáo dục — đối tác: {doi_tac}",
        f"# Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"# Tổng số trường sau lọc đơn vị: {len(rows)}",
        "# Định dạng: <maTruongHoc> | <tenDonVi> | <tenTruongHoc>",
        "",
    ]
    for row in rows:
        ma = row.get("maTruongHoc", "").strip()
        ten_don_vi = row.get("tenDonVi", "").strip()
        ten = row.get("tenTruongHoc", "").strip()
        if ma:
            lines.append(" | ".join([ma, ten_don_vi, ten]))
    return "\n".join(lines)


def _rows_to_orders(rows: list[dict]) -> list[tuple[str, str]]:
    """Chuyển rows thành list (maTruong, tenTruong) cho run_order_file_queue."""
    return [
        (row.get("maTruongHoc", "").strip(), row.get("tenTruongHoc", "").strip())
        for row in rows
        if row.get("maTruongHoc", "").strip()
    ]


def _filter_rows_by_ten_don_vi(rows: list[dict]) -> list[dict]:
    return [
        row
        for row in rows
        if str(row.get("tenDonVi") or "").strip() in ALLOWED_TEN_DON_VI
    ]
