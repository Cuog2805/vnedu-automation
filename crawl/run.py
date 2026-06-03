# crawl/run.py
"""
Entry point để chạy crawler từ CLI:

    python -m crawl.run
    python -m crawl.run --doi-tac VNPT_HAN
    python -m crawl.run --no-timestamp --output-dir ./data

Hoặc import vào test:
    from crawl.run import run_crawl
    rows = run_crawl(doi_tac="VNPT_NBH")
"""

import argparse
import logging
import sys
from pathlib import Path

from .crawler import CSDLCrawler, SessionExpiredError
from .exporter import export_csv, export_txt
from .config import OUTPUT_DIR, CSV_FILENAME, TXT_FILENAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_crawl(
    doi_tac: str = "VNPT_NBH",
    output_dir: str = OUTPUT_DIR,
    timestamped: bool = True,
    headless: bool = True,
) -> list[dict]:
    """
    Hàm chính — có thể gọi từ test hoặc script khác.

    Returns:
        list[dict]: Toàn bộ rows đã crawl
    """
    crawler = CSDLCrawler(
        payload_overrides={"maDoiTac": doi_tac},
        headless=headless,
    )

    try:
        rows = crawler.fetch_all()
    except SessionExpiredError as e:
        logger.error(f"Session error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)

    if not rows:
        logger.warning("Không có dữ liệu nào được trả về.")
        return []

    csv_path = export_csv(rows, CSV_FILENAME, output_dir, timestamped)
    txt_path = export_txt(rows, TXT_FILENAME, output_dir, timestamped)

    print(f"\n✓ CSV : {csv_path}")
    print(f"✓ TXT : {txt_path}")
    print(f"✓ Total: {len(rows)} bản ghi\n")

    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl dữ liệu trường học từ CSDL Giáo dục"
    )
    parser.add_argument(
        "--doi-tac",
        default="VNPT_NBH",
        help="Mã đối tác (default: VNPT_NBH)",
    )
    parser.add_argument(
        "--output-dir",
        default=OUTPUT_DIR,
        help=f"Thư mục output (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Không thêm timestamp vào tên file",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Hiện browser Playwright (debug mode)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_crawl(
        doi_tac=args.doi_tac,
        output_dir=args.output_dir,
        timestamped=not args.no_timestamp,
        headless=not args.visible,
    )
