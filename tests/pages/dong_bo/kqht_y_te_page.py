from datetime import datetime

from playwright.sync_api import Page, expect

from pages.dong_bo.base import DongBoBasePage


class DongBoKqhtYTePage(DongBoBasePage):
    SEMESTER_VALUES = {
        "gk1": "122",
        "hk1": "1",
        "gk2": "222",
        "hk2": "2",
        "cn": "3",
    }

    def __init__(self, page: Page):
        DongBoBasePage.__init__(self, page)

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
        ).last

    def open_kqht_y_te_options(self):
        expect(self.sync_kqht_button).to_have_count(1)
        self.sync_kqht_button.first.click()
        self._wait_for_kqht_modal_or_error()
        self._fail_if_error_alert_is_visible()
        expect(self.kqht_modal).to_be_visible()

    def sync_kqht_y_te(self, semester: str | None):
        self.select_current_school_year()
        if semester:
            self.sync_kqht_y_te_semester(semester)
            return

        semester_values = self.get_available_kqht_semester_values()
        for index, semester_value in enumerate(semester_values):
            self.sync_kqht_y_te_semester_value(semester_value)
            self.close_kqht_result_modal()
            if index < len(semester_values) - 1 and not self.kqht_modal.is_visible():
                self.open_kqht_y_te_options()
                self.select_current_school_year()

    def sync_kqht_y_te_semester(self, semester: str):
        semester_value = self.get_kqht_semester_value(semester)
        self.sync_kqht_y_te_semester_value(semester_value)

    def sync_kqht_y_te_semester_value(self, semester_value: str):
        self.select_kqht_semester_value(semester_value)
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
        value = self.get_kqht_semester_value(semester)
        self.select_kqht_semester_value(value)

    def get_kqht_semester_value(self, semester: str):
        value = self.SEMESTER_VALUES.get(semester)
        if value is None:
            raise AssertionError("Học kỳ không hợp lệ. Dùng gk1, hk1, gk2, hk2 hoặc cn.")

        available_values = self.get_available_kqht_semester_values()
        if value not in available_values:
            raise AssertionError(
                f"Modal không có option học kỳ {semester}. "
                f"Các option hiện có: {', '.join(available_values)}"
            )
        return value

    def select_kqht_semester_value(self, value: str):
        expect(self.kqht_semester_select).to_be_visible()
        self.kqht_semester_select.select_option(value)
        expect(self.kqht_semester_select).to_have_value(value)

    def get_available_kqht_semester_values(self):
        expect(self.kqht_semester_select).to_be_visible()
        values = self.kqht_semester_select.evaluate(
            """
            (select) => Array.from(select.options)
                .map((option) => option.value)
                .filter((value) => value)
            """
        )
        if not values:
            raise AssertionError("Không tìm thấy option học kỳ nào trong #HocKySyncKQHT.")
        return [str(value) for value in values]

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
