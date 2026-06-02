from playwright.sync_api import expect

from pages.dong_bo.kqht_y_te_page import DongBoKqhtYTePage
from pages.dong_bo.ttcb_lh_page import DongBoTtcbLhPage


def test_dong_bo_du_lieu_truong_hoc(logged_in_page, school_code):
    """
    Kịch bản:
    - Tìm trường theo mã VNEDU tester nhập khi chạy test.
    - Mở modal đồng bộ tổng hợp.
    - Chạy lần lượt 4 bước cho Học kỳ 1 và Học kỳ 2:
      cán bộ giáo viên, lớp học, học sinh, trường học.
    """
    dong_bo = DongBoTtcbLhPage(logged_in_page)

    row = dong_bo.search_school(school_code)
    expect(row).to_be_visible()

    dong_bo.open_sync_options()
    dong_bo.sync_all_steps()


def test_dong_bo_kqht_y_te(logged_in_page, school_code, semester):
    """
    Kịch bản:
    - Tìm trường theo mã tester nhập.
    - Mở chức năng Đồng bộ thông tin Y tế/Kết quả học tập.
    - Chọn năm học theo năm hiện tại, chọn học kỳ, chọn tất cả lớp.
    - Đồng bộ, kiểm tra modal log kết quả và chụp ảnh trước khi kết thúc.
    """
    dong_bo = DongBoKqhtYTePage(logged_in_page)

    row = dong_bo.search_school(school_code)
    expect(row).to_be_visible()

    dong_bo.open_kqht_y_te_options()
    dong_bo.sync_kqht_y_te(semester)
