import re
from pathlib import Path

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
