"""
test_tai_so_do.py — bài test thật cho chức năng "Tải sơ đồ tổ chức ra JPG".

pytest tự nhận file bắt đầu bằng "test_" và hàm bắt đầu bằng "test_".
Chạy:  pytest

ĐIỂM MẤU CHỐT — đây là điều phân biệt TEST với AUTOMATION:
  Automation chỉ LÀM (click, tải). Test thì LÀM rồi KHẲNG ĐỊNH kết quả
  đúng (assertion), và THẤT BẠI khi kết quả sai. Mỗi expect()/assert dưới đây
  trả lời câu hỏi: "sau bước này, điều gì PHẢI đúng?"
"""
import os
from playwright.sync_api import expect

from pages.so_do_page import SoDoToChucPage


def test_tai_so_do_to_chuc(logged_in_page, tmp_path):
    """
    Kịch bản: vào Sơ đồ tổ chức -> tương tác -> tải hình JPG.
    Khẳng định: nút tải hiện ra, tải được file, file không rỗng, đúng đuôi .jpg.

    tmp_path là fixture sẵn có của pytest: cấp 1 thư mục tạm sạch cho mỗi test,
    tự dọn sau khi xong -> test không để lại rác, không phụ thuộc lần chạy trước.
    """
    so_do = SoDoToChucPage(logged_in_page)

    # --- Hành động + khẳng định điều hướng ---
    so_do.di_toi_so_do()  # bên trong đã expect sơ đồ hiện ra

    # Khẳng định: nút tải phải hiện ra trước khi bấm.
    # expect() có auto-wait: tự chờ tới khi đúng (hoặc hết timeout) -> khỏi sleep.
    expect(so_do.btn_tai_jpg).to_be_visible()

    so_do.tuong_tac_so_do()

    # --- Hành động tải + bắt kết quả ---
    download = so_do.tai_hinh_jpg()

    # Lưu vào thư mục tạm của test này
    save_path = os.path.join(tmp_path, download.suggested_filename)
    download.save_as(save_path)

    # --- CÁC ASSERTION: trái tim của bài test ---
    # 1. File thật sự tồn tại trên đĩa
    assert os.path.exists(save_path), "File tải về không tồn tại"

    # 2. File không rỗng (tải hỏng thường ra file 0 byte)
    assert os.path.getsize(save_path) > 0, "File tải về bị rỗng (0 byte)"

    # 3. Đúng định dạng mong đợi
    assert download.suggested_filename.lower().endswith((".jpg", ".jpeg")), (
        f"Tên file không phải .jpg: {download.suggested_filename}"
    )
