import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BotState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active_jobs: dict[int, subprocess.Popen | None] = field(default_factory=dict)
    active_job_kinds: dict[int, str] = field(default_factory=dict)
    last_logs: dict[int, str] = field(default_factory=dict)
    last_log_titles: dict[int, str] = field(default_factory=dict)
    pending_order_file_requests: dict[int, datetime | None] = field(default_factory=dict)
    pending_command_requests: dict[int, str] = field(default_factory=dict)
    scheduled_order_jobs: dict[str, dict] = field(default_factory=dict)
    selected_systems: dict[int, str] = field(default_factory=dict)
    cancelled_jobs: set[int] = field(default_factory=set)
