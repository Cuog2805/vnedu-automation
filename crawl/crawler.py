import time
import logging
from typing import Any

import httpx
from playwright.sync_api import sync_playwright, Browser, BrowserContext

from .config import (
    BASE_URL,
    LOGIN_PATH,
    FORWARD_API_PATH,
    DATA_PATH,
    DATA_METHOD,
    PAGE_LIMIT,
    REQUEST_DELAY_SECONDS,
    DEFAULT_PAYLOAD_DATA,
)

logger = logging.getLogger(__name__)


class SessionExpiredError(Exception):
    """Raise khi server trả về response không hợp lệ do session hết hạn."""
    pass


class CSDLCrawler:
    """
    Crawler cho hệ thống CSDL Giáo dục.

    Usage:
        crawler = CSDLCrawler()
        rows = crawler.fetch_all()

        # Override filter nếu cần
        crawler = CSDLCrawler(payload_overrides={"maDoiTac": "VNPT_HAN"})
        rows = crawler.fetch_all()
    """

    def __init__(
        self,
        payload_overrides: dict | None = None,
        headless: bool = True,
        page_limit: int = PAGE_LIMIT,
        delay: float = REQUEST_DELAY_SECONDS,
    ):
        self.payload_data = {**DEFAULT_PAYLOAD_DATA, **(payload_overrides or {})}
        self.headless = headless
        self.page_limit = page_limit
        self.delay = delay
        self._session_cookie: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_all(self) -> list[dict]:
        """
        Lấy toàn bộ bản ghi. Tự động refresh session nếu cần.

        Returns:
            list[dict]: Danh sách bản ghi (mỗi dict là 1 trường học).
        """
        self._refresh_session()
        rows = self._paginate()
        logger.info(f"Done. Total rows fetched: {len(rows)}")
        return rows

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def _refresh_session(self) -> None:
        """Dùng Playwright load trang chủ để lấy laravel_session mới."""
        logger.info("Refreshing session via Playwright...")
        with sync_playwright() as p:
            browser: Browser = p.chromium.launch(headless=self.headless)
            context: BrowserContext = browser.new_context()
            page = context.new_page()

            page.goto(BASE_URL + LOGIN_PATH, wait_until="domcontentloaded", timeout=30_000)

            cookies = context.cookies()
            browser.close()

        session = next(
            (c["value"] for c in cookies if c["name"] == "laravel_session"),
            None,
        )
        bigsession = next(
            (c["value"] for c in cookies if "BIGip" in c["name"]),
            None,
        )

        if not session:
            raise SessionExpiredError("Không lấy được laravel_session từ trang chủ.")

        # Ghép cookie string như browser gửi lên
        parts = [f"laravel_session={session}"]
        if bigsession:
            # Lấy tên key BIGip từ cookies
            bigip_key = next(c["name"] for c in cookies if "BIGip" in c["name"])
            parts.insert(0, f"{bigip_key}={bigsession}")

        self._session_cookie = "; ".join(parts)
        logger.info("Session acquired.")

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _paginate(self) -> list[dict]:
        """Gọi API theo từng trang, gom toàn bộ rows."""
        all_rows: list[dict] = []

        with httpx.Client(timeout=30) as client:
            # Trang đầu: lấy tổng số bản ghi
            first_page = self._fetch_page(client, start=0)
            total: int = first_page.get("total", 0)
            all_rows.extend(first_page.get("rows", []))
            logger.info(f"Total records: {total}. Fetched: {len(all_rows)}")

            start = self.page_limit
            while start < total:
                page_data = self._fetch_page(client, start=start)
                rows = page_data.get("rows", [])
                if not rows:
                    logger.warning(f"Empty page at start={start}, stopping early.")
                    break
                all_rows.extend(rows)
                logger.info(f"Fetched {len(all_rows)}/{total}")
                start += self.page_limit
                time.sleep(self.delay)

        return all_rows

    # ------------------------------------------------------------------
    # Single page request
    # ------------------------------------------------------------------

    def _fetch_page(self, client: httpx.Client, start: int) -> dict[str, Any]:
        """Gọi 1 trang API, trả về dict raw từ JSON response."""
        if not self._session_cookie:
            raise SessionExpiredError("Session chưa được khởi tạo. Gọi _refresh_session() trước.")

        headers = self._build_headers()
        payload = self._build_payload(start)

        response = client.post(
            BASE_URL + FORWARD_API_PATH,
            json=payload,
            headers=headers,
        )

        if response.status_code == 401 or response.status_code == 403:
            raise SessionExpiredError(
                f"Session từ chối (HTTP {response.status_code}). Cần refresh session."
            )

        response.raise_for_status()

        data = response.json()

        # Kiểm tra response hợp lệ
        if data.get("rc") != 0:
            raise RuntimeError(
                f"API trả lỗi: rc={data.get('rc')}, rd={data.get('rd')}"
            )

        return data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "vi,en-US;q=0.9",
            "Cookie": self._session_cookie,
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/",
        }

    def _build_payload(self, start: int) -> dict:
        return {
            "path": DATA_PATH,
            "method": DATA_METHOD,
            "data": {
                "start": start,
                "limit": str(self.page_limit),
                **self.payload_data,
            },
        }
