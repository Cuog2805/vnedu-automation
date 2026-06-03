import subprocess
import sys
import threading
import time

from bot_config import LOGIN_SCRIPT, ROOT_DIR


class LoginHandler:
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
        if self.is_cancel_requested(chat_id):
            self.clear_chat_job(chat_id)

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
