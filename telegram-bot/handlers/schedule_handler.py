import json
import sys
import threading
import time
from datetime import datetime, timedelta

from bot_config import SCHEDULED_JOBS_PATH, SCHEDULER_POLL_SECONDS


class ScheduleHandler:
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
