import os
from datetime import datetime

from playwright.sync_api import Locator, Page, expect


class DongBoPage:
    def __init__(self, page: Page):
        self.page = page

        self.school_table = page.locator("#tableSchool")
        self.school_rows = page.locator("#tableSchool tbody tr")
        self.search_input = page.locator('#tableSchool_filter input[type="search"]')

        self.sync_option_button = page.locator(
            '#tableSchool tbody tr button[onclick^="SyncOption"]'
        )
        self.sync_modal = page.locator(".modal.show").filter(
            has=page.locator("#GetSyncStaff")
        )
        self.loading_modal = page.locator(
            ".modal.show .modal-dialog", has_text="Hệ thống đang xử lý dữ liệu"
        )

        self.swal_popup = page.locator(".swal2-popup.swal2-show")
        self.swal_content = page.locator("#swal2-content")
        self.swal_confirm_button = page.locator(".swal2-confirm")

        self.btn_sync_staff = page.locator("#GetSyncStaff")
        self.btn_sync_class = page.locator("#GetSyncClass")
        self.btn_sync_student = page.locator("#GetSyncStudent")
        self.btn_sync_school = page.locator("#GetSyncSchool")

        self.sync_kqht_button = page.locator(
            '#tableSchool tbody tr button[onclick^="popSyncKQHT"]'
        )
        self.kqht_modal = page.locator(".modal.show").filter(
            has=page.locator("#YearSyncKQHT")
        )
        self.kqht_year_select = page.locator("#YearSyncKQHT")
        self.kqht_semester_select = page.locator("#HocKySyncKQHT")
        self.kqht_select_all_button = page.locator(".modal.show #select-all")
        self.kqht_class_select = page.locator("#ClassSyncKQHT")
        self.kqht_sync_button = page.locator(
            '.modal.show button[onclick="SyncKQHT()"]'
        )
        self.kqht_result_modal = page.locator(".modal.show").filter(
            has=page.locator("#tittleSyncKQHT_Respone")
        )
        self.kqht_result_rows = self.kqht_result_modal.locator(".modal-body p")
        self.kqht_result_close_button = self.kqht_result_modal.get_by_role(
            "button", name="Đóng"
        )

    def wait_until_ready(self):
        expect(self.school_table).to_be_visible()
        expect(self.search_input).to_be_visible()

    def search_school(self, school_code: str):
        self.wait_until_ready()
        self.search_input.fill(school_code)
        self.search_input.press("Enter")

        expect(self.school_rows).to_have_count(1)
        first_row = self.school_rows.first
        expect(first_row.locator("td").nth(2)).to_have_text(school_code)
        return first_row

    def open_sync_options(self):
        expect(self.sync_option_button).to_have_count(1)
        self.sync_option_button.first.click()
        self._wait_for_processing_to_finish(require_visible=True)
        self._wait_for_sync_modal_or_error()
        self._fail_if_error_alert_is_visible()
        expect(self.sync_modal).to_be_visible()

    def sync_all_steps(self):
        self.sync_staff()
        self.sync_class()
        self.sync_student()
        self.sync_school()

    def sync_staff(self):
        self._run_sync_step(
            button=self.btn_sync_staff,
            expected_message="Đồng bộ cán bộ giáo viên thành công",
        )
        expect(self.btn_sync_class).to_be_visible()

    def sync_class(self):
        self._run_sync_step(
            button=self.btn_sync_class,
            expected_message="Đồng bộ lớp học thành công",
        )
        expect(self.btn_sync_student).to_be_visible()

    def sync_student(self):
        self._run_sync_step(
            button=self.btn_sync_student,
            expected_message="Đồng bộ học sinh thành công",
        )
        expect(self.btn_sync_school).to_be_visible()

    def sync_school(self):
        self._run_sync_step(
            button=self.btn_sync_school,
            expected_message="Đồng bộ thông tin trường học thành công",
            capture_success=True,
        )

    def open_kqht_y_te_options(self):
        expect(self.sync_kqht_button).to_have_count(1)
        self.sync_kqht_button.first.click()
        self._wait_for_kqht_modal_or_error()
        self._fail_if_error_alert_is_visible()
        expect(self.kqht_modal).to_be_visible()

    def sync_kqht_y_te(self, semester: str):
        self.select_current_school_year()
        self.select_kqht_semester(semester)
        self.select_all_kqht_classes()
        self.submit_kqht_sync()

    def select_current_school_year(self):
        expect(self.kqht_year_select).to_be_visible()
        current_year = str(datetime.now().year)
        option_value = self.kqht_year_select.evaluate(
            """
            (select, currentYear) => {
                const option = Array.from(select.options)
                    .find((item) => item.textContent.includes(currentYear));
                return option ? option.value : null;
            }
            """,
            current_year,
        )
        if option_value is None:
            raise AssertionError(
                f"Không tìm thấy năm học chứa năm hiện tại {current_year} "
                "trong #YearSyncKQHT"
            )
        self.kqht_year_select.select_option(str(option_value))

    def select_kqht_semester(self, semester: str):
        semester_values = {
            "hk1": "1",
            "hk2": "2",
            "cn": "3",
        }
        value = semester_values.get(semester)
        if value is None:
            raise AssertionError("Học kỳ không hợp lệ. Dùng hk1, hk2 hoặc cn.")

        expect(self.kqht_semester_select).to_be_visible()
        self.kqht_semester_select.select_option(value)

    def select_all_kqht_classes(self):
        expect(self.kqht_select_all_button).to_be_visible()
        self.kqht_select_all_button.click()
        self.page.wait_for_function(
            """
            () => {
                const select = document.querySelector("#ClassSyncKQHT");
                return select && Array.from(select.selectedOptions).length > 0;
            }
            """
        )

    def submit_kqht_sync(self):
        expect(self.kqht_sync_button).to_be_visible()
        self.kqht_sync_button.click()
        self._wait_for_processing_to_finish(require_visible=True)
        self._wait_for_kqht_result_modal_or_error()
        self._fail_if_error_alert_is_visible()
        expect(self.kqht_result_modal).to_be_visible()
        expect(self.kqht_result_rows.first).to_be_visible()
        expect(self.kqht_result_modal).to_contain_text("Đã đồng bộ")
        self.capture_result_screenshot()

    def close_kqht_result_modal(self):
        expect(self.kqht_result_close_button).to_be_visible()
        self.kqht_result_close_button.click()
        expect(self.kqht_result_modal).to_be_hidden()

    def _run_sync_step(
        self, button: Locator, expected_message: str, capture_success: bool = False
    ):
        expect(button).to_be_visible()
        button.click()
        self._wait_for_processing_to_finish()
        self._expect_success_alert(expected_message)
        if capture_success:
            self.capture_result_screenshot()
        self._confirm_swal()

    def capture_result_screenshot(self):
        screenshot_path = os.getenv("VNEDU_SCREENSHOT_PATH")
        if not screenshot_path:
            return

        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        self.page.screenshot(path=screenshot_path, full_page=False)

    def _wait_for_processing_to_finish(
        self, timeout: int = 300_000, require_visible: bool = False
    ):
        if require_visible:
            expect(self.loading_modal).to_be_visible(timeout=30_000)
        else:
            try:
                expect(self.loading_modal).to_be_visible(timeout=3_000)
            except AssertionError:
                pass
        expect(self.loading_modal).to_be_hidden(timeout=timeout)

    def _expect_success_alert(self, expected_message: str, timeout: int = 300_000):
        expect(self.swal_popup).to_be_visible(timeout=timeout)
        message = self.swal_content.inner_text()
        popup_class = self.swal_popup.get_attribute("class") or ""

        if "swal2-icon-error" in popup_class:
            raise AssertionError(f"Hệ thống báo lỗi khi đồng bộ: {message}")

        assert "swal2-icon-success" in popup_class, (
            f"SweetAlert không phải thông báo thành công: {message}"
        )
        expect(self.swal_content).to_contain_text(expected_message)

    def _confirm_swal(self):
        expect(self.swal_confirm_button).to_be_visible()
        self.swal_confirm_button.click()
        expect(self.swal_popup).to_be_hidden()

    def _wait_for_sync_modal_or_error(self, timeout: int = 30_000):
        self.page.wait_for_function(
            """
            () => {
                const isVisible = (element) => {
                    if (!element) return false;
                    return !!(
                        element.offsetWidth ||
                        element.offsetHeight ||
                        element.getClientRects().length
                    );
                };
                const syncModal = Array.from(document.querySelectorAll(".modal.show"))
                    .some((element) => element.querySelector("#GetSyncStaff") && isVisible(element));
                return syncModal ||
                    isVisible(document.querySelector(".swal2-popup.swal2-icon-error.swal2-show"));
            }
            """,
            timeout=timeout,
        )

    def _wait_for_kqht_modal_or_error(self, timeout: int = 30_000):
        self.page.wait_for_function(
            """
            () => {
                const isVisible = (element) => {
                    if (!element) return false;
                    return !!(
                        element.offsetWidth ||
                        element.offsetHeight ||
                        element.getClientRects().length
                    );
                };
                const syncModal = Array.from(document.querySelectorAll(".modal.show"))
                    .some((element) => element.querySelector("#YearSyncKQHT") && isVisible(element));
                return syncModal ||
                    isVisible(document.querySelector(".swal2-popup.swal2-icon-error.swal2-show"));
            }
            """,
            timeout=timeout,
        )

    def _wait_for_kqht_result_modal_or_error(self, timeout: int = 300_000):
        self.page.wait_for_function(
            """
            () => {
                const isVisible = (element) => {
                    if (!element) return false;
                    return !!(
                        element.offsetWidth ||
                        element.offsetHeight ||
                        element.getClientRects().length
                    );
                };
                const resultModal = Array.from(document.querySelectorAll(".modal.show"))
                    .some((element) => element.querySelector("#tittleSyncKQHT_Respone") && isVisible(element));
                return resultModal ||
                    isVisible(document.querySelector(".swal2-popup.swal2-icon-error.swal2-show"));
            }
            """,
            timeout=timeout,
        )

    def _fail_if_error_alert_is_visible(self):
        if self.swal_popup.count() == 0 or not self.swal_popup.is_visible():
            return

        popup_class = self.swal_popup.get_attribute("class") or ""
        if "swal2-icon-error" in popup_class:
            message = self.swal_content.inner_text()
            raise AssertionError(f"Hệ thống báo lỗi khi mở modal đồng bộ: {message}")
