from playwright.sync_api import Locator, Page, expect

from pages.dong_bo.base import DongBoBasePage


class DongBoTtcbLhPage(DongBoBasePage):
    SEMESTER_OPTIONS = (("1", "Học kỳ 1"), ("2", "Học kỳ 2"))

    def __init__(self, page: Page):
        DongBoBasePage.__init__(self, page)

        self.sync_option_button = page.locator(
            '#tableSchool tbody tr button[onclick^="SyncOption"][title*="Cán bộ Giáo viên"]'
        )
        self.sync_modal = page.locator(".modal.show").filter(
            has=page.locator("#GetSyncStaff")
        )
        self.semester_select = self.sync_modal.locator("#HocKy")
        self.semester_options = self.semester_select.locator("option")

        self.btn_sync_staff = page.locator("#GetSyncStaff")
        self.btn_sync_class = page.locator("#GetSyncClass")
        self.btn_sync_student = page.locator("#GetSyncStudent")
        self.btn_sync_school = page.locator("#GetSyncSchool")

    def open_sync_options(self):
        expect(self.sync_option_button).to_have_count(1)
        self.sync_option_button.first.click()
        self._wait_for_processing_to_finish()
        self._wait_for_sync_modal_or_error()
        self._fail_if_error_alert_is_visible()
        expect(self.sync_modal).to_be_visible()
        self._expect_semester_options()

    def sync_all_steps(self):
        for semester_value, _ in self.SEMESTER_OPTIONS:
            self._ensure_sync_modal_is_open()
            self.select_semester(semester_value)
            self.sync_current_semester()

    def sync_current_semester(self):
        self.sync_staff()
        self.sync_class()
        self.sync_student()
        self.sync_school()

    def select_semester(self, semester_value: str):
        valid_values = {value for value, _ in self.SEMESTER_OPTIONS}
        if semester_value not in valid_values:
            raise AssertionError("Học kỳ không hợp lệ. Dùng 1 hoặc 2.")

        expect(self.semester_select).to_be_visible()
        self.semester_select.select_option(semester_value)
        expect(self.semester_select).to_have_value(semester_value)

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

    def _expect_semester_options(self):
        expect(self.semester_select).to_be_visible()
        expect(self.semester_options).to_have_count(len(self.SEMESTER_OPTIONS))
        for index, (value, label) in enumerate(self.SEMESTER_OPTIONS):
            option = self.semester_options.nth(index)
            expect(option).to_have_attribute("value", value)
            expect(option).to_have_text(label)

    def _ensure_sync_modal_is_open(self):
        if self._is_sync_modal_ready():
            return
        self.open_sync_options()

    def _is_sync_modal_ready(self):
        try:
            return self.sync_modal.is_visible() and self.semester_select.is_visible()
        except AssertionError:
            return False

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
