"""
so_do_page.py — một "Page Object".

Ý tưởng Page Object Model (POM) — KHÁI NIỆM CHỐNG MONG MANH QUAN TRỌNG NHẤT:
  Thay vì rải selector ("#tree-svg", "Tải hình JPG"...) khắp các file test,
  ta gom TẤT CẢ selector và thao tác của MỘT trang vào MỘT class.

  Lợi ích: khi website đổi giao diện (đổi tên nút, đổi id), bạn chỉ sửa
  ở ĐÚNG MỘT CHỖ này, mọi test dùng nó tự động đúng theo. Nếu rải selector
  khắp nơi, mỗi lần web đổi bạn phải đi sửa hàng chục file -> đó là lý do
  số 1 khiến người ta bỏ test tự động.

Nguyên tắc đặt selector (từ bền nhất tới mong manh nhất):
  get_by_role / get_by_text / get_by_label  >  CSS class  >  id tự sinh / nth()
  -> Ưu tiên cái mà NGƯỜI DÙNG nhìn thấy, tránh chi tiết kỹ thuật dễ đổi.
"""
from playwright.sync_api import Page, expect


class SoDoToChucPage:
    def __init__(self, page: Page):
        self.page = page

        # --- Các bước điều hướng (dùng role+text: khá bền) ---
        self.link_quan_ly_don_vi = page.get_by_role("link", name=" Quản lý đơn vị ")
        self.link_danh_sach_don_vi = page.get_by_role("link", name=" Danh sách đơn vị")
        self.link_so_do_to_chuc = page.get_by_role("link", name=" Sơ đồ tổ chức")

        # --- Các phần tử trên sơ đồ ---
        # LƯU Ý: "circle".nth(1) và "#tree-svg" là selector MONG MANH.
        #   - nth(1) phụ thuộc thứ tự/số lượng node trên sơ đồ -> dễ vỡ.
        #   - #tree-svg là id, ổn hơn ext-gen* nhưng vẫn nên kiểm tra lại.
        # Giữ ở đây và đánh dấu để sau này thay bằng selector tốt hơn nếu có.
        self.so_do_svg = page.locator("#tree-svg")
        self.node_circle = page.locator("circle")

        # --- Nút tải (role+text: bền) ---
        self.btn_tai_jpg = page.get_by_role("button", name=" Tải hình JPG")

    def di_toi_so_do(self):
        """Điều hướng từ trang chủ tới Sơ đồ tổ chức."""
        self.link_quan_ly_don_vi.click()
        self.link_danh_sach_don_vi.click()
        self.link_so_do_to_chuc.click()
        # Khẳng định đã tới đúng nơi: sơ đồ phải hiện ra.
        expect(self.so_do_svg).to_be_visible()

    def tuong_tac_so_do(self):
        """Click vào node và vùng sơ đồ."""
        self.node_circle.nth(1).click()
        self.so_do_svg.click()

    def tai_hinh_jpg(self):
        """Bấm nút tải và trả về đối tượng download của Playwright."""
        with self.page.expect_download() as download_info:
            self.btn_tai_jpg.click()
        return download_info.value
