import time
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://dongbo.csdl.edu.vn"
FORWARD_API_PATH = "/forward-api"
DATA_PATH = "/csdlgd-admin/heThongDoiTacTruong/danhSach"
PAGE_LIMIT = 25
REQUEST_DELAY_SECONDS = 0.3


class CSDLApiError(Exception):
    """API trả rc != 0 hoặc HTTP error."""
    pass


class CSDLClient:
    """
    Stateless HTTP client — nhận session_cookie từ ngoài.
    Bot gọi CSDLCrawler để lấy cookie, rồi truyền vào đây.
    """

    def __init__(
        self,
        session_cookie: str,
        page_limit: int = PAGE_LIMIT,
        delay: float = REQUEST_DELAY_SECONDS,
    ):
        self.session_cookie = session_cookie
        self.page_limit = page_limit
        self.delay = delay

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def fetch_all(self, doi_tac: str = "VNPT_NBH") -> list[dict]:
        """Lấy toàn bộ bản ghi cho mã đối tác."""
        all_rows: list[dict] = []

        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            first = self._fetch_page(client, start=0, doi_tac=doi_tac)
            total: int = first.get("total", 0)
            all_rows.extend(first.get("rows", []))
            logger.info(f"[CSDLClient] total={total}, fetched={len(all_rows)}")

            start = self.page_limit
            while start < total:
                page = self._fetch_page(client, start=start, doi_tac=doi_tac)
                rows = page.get("rows", [])
                if not rows:
                    logger.warning(f"[CSDLClient] Empty page at start={start}, stopping.")
                    break
                all_rows.extend(rows)
                logger.info(f"[CSDLClient] fetched={len(all_rows)}/{total}")
                start += self.page_limit
                time.sleep(self.delay)

        return all_rows

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_page(
        self, client: httpx.Client, start: int, doi_tac: str
    ) -> dict[str, Any]:
        payload = {
            "path": DATA_PATH,
            "method": "POST",
            "data": {
                "start": start,
                "limit": str(self.page_limit),
                "maDoiTac": doi_tac,
                "maDonVis": [],
                "maTruongs": [],
                "capHoc": [],
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Cookie": self.session_cookie,
            "Origin": BASE_URL,
            "Referer": BASE_URL + "/",
            "X-Requested-With": "XMLHttpRequest",
        }

        resp = client.post(
            BASE_URL + FORWARD_API_PATH,
            json=payload,
            headers=headers,
        )

        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location") or ""
            raise CSDLApiError(
                "Session CSDL không còn hợp lệ hoặc chưa đăng nhập đủ quyền "
                f"(HTTP {resp.status_code}, redirect: {location}). "
                "Hãy chạy /login ở chế độ CSDL rồi đăng nhập lại."
            )

        if resp.status_code in (401, 403):
            raise CSDLApiError(f"Session bị từ chối (HTTP {resp.status_code}).")

        resp.raise_for_status()
        data = resp.json()

        if data.get("rc") != 0:
            raise CSDLApiError(
                f"API báo lỗi: rc={data.get('rc')}, rd={data.get('rd')}"
            )

        return data
