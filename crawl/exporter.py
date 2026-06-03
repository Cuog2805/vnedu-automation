import csv
import os
import logging
from datetime import datetime

from .config import OUTPUT_DIR, CSV_FILENAME, TXT_FILENAME, CSV_COLUMNS

logger = logging.getLogger(__name__)


def _ensure_output_dir(directory: str) -> None:
    os.makedirs(directory, exist_ok=True)


def _timestamped(filename: str) -> str:
    """Thêm timestamp vào tên file để không bị overwrite: truong_hoc_20260603_1420.csv"""
    name, ext = os.path.splitext(filename)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    return f"{name}_{ts}{ext}"


def export_csv(
    rows: list[dict],
    filename: str = CSV_FILENAME,
    output_dir: str = OUTPUT_DIR,
    timestamped: bool = True,
) -> str:
    """
    Xuất list[dict] ra file CSV.

    Args:
        rows: Dữ liệu từ CSDLCrawler.fetch_all()
        filename: Tên file (mặc định từ config)
        output_dir: Thư mục output
        timestamped: Thêm timestamp vào tên file

    Returns:
        str: Đường dẫn file đã tạo
    """
    _ensure_output_dir(output_dir)

    if timestamped:
        filename = _timestamped(filename)

    filepath = os.path.join(output_dir, filename)

    # Lấy columns từ config, fallback sang keys của row đầu nếu config thiếu field
    columns = CSV_COLUMNS if rows and all(c in rows[0] for c in CSV_COLUMNS) else (
        list(rows[0].keys()) if rows else CSV_COLUMNS
    )

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        # utf-8-sig: Excel Windows mở đúng tiếng Việt không bị lỗi encoding
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"CSV exported: {filepath} ({len(rows)} rows)")
    return filepath


def export_txt(
    rows: list[dict],
    filename: str = TXT_FILENAME,
    output_dir: str = OUTPUT_DIR,
    timestamped: bool = True,
) -> str:
    """
    Xuất list[dict] ra file TXT dạng bảng dễ đọc.

    Format:
        ----------------------------------------
        ID          : 158139
        Mã trường   : 36356322
        Tên trường  : Trường mầm non Lộc Hạ
        Đơn vị      : Phường Thiên Trường (13684)
        Đối tác     : VNPT Ninh Bình
        Cập nhật    : 04/09/2025
        ----------------------------------------

    Args:
        rows: Dữ liệu từ CSDLCrawler.fetch_all()
        filename: Tên file
        output_dir: Thư mục output
        timestamped: Thêm timestamp vào tên file

    Returns:
        str: Đường dẫn file đã tạo
    """
    _ensure_output_dir(output_dir)

    if timestamped:
        filename = _timestamped(filename)

    filepath = os.path.join(output_dir, filename)

    separator = "-" * 56

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Dữ liệu hệ thống đối tác trường học - CSDL Giáo dục\n")
        f.write(f"Xuất lúc: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Tổng số bản ghi: {len(rows)}\n")
        f.write(separator + "\n\n")

        for i, row in enumerate(rows, start=1):
            f.write(f"{separator}\n")
            f.write(f"STT         : {i}\n")
            f.write(f"ID          : {row.get('id', '')}\n")
            f.write(f"Mã trường   : {row.get('maTruongHoc', '')}\n")
            f.write(f"Tên trường  : {row.get('tenTruongHoc', '')}\n")
            f.write(f"Đơn vị      : {row.get('tenDonVi', '').strip()} ({row.get('maDonVi', '')})\n")
            f.write(f"Đối tác     : {row.get('tenDoiTac', '')} ({row.get('maDoiTac', '')})\n")
            f.write(f"Cập nhật    : {row.get('ngayCapNhat', '')}\n")

        f.write(f"{separator}\n")
        f.write(f"EOF — {len(rows)} bản ghi\n")

    logger.info(f"TXT exported: {filepath} ({len(rows)} rows)")
    return filepath
