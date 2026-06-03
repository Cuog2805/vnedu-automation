import os

from playwright.sync_api import Page, expect


MAX_WAIT_TIMEOUT_MS = 48 * 60 * 60 * 1000
SEARCH_WAIT_TIMEOUT_MS = 10_000


class DongBoBasePage:
    def __init__(self, page: Page):
        self.page = page
        self.page.set_default_timeout(MAX_WAIT_TIMEOUT_MS)
        self.page.set_default_navigation_timeout(MAX_WAIT_TIMEOUT_MS)

        self.school_table = page.locator("#tableSchool")
        self.school_rows = page.locator("#tableSchool tbody tr")
        self.search_input = page.locator('#tableSchool_filter input[type="search"]')

        self.loading_modal = page.locator(
            ".modal.show .modal-dialog", has_text="Hệ thống đang xử lý dữ liệu"
        )

        self.swal_popup = page.locator(".swal2-popup.swal2-show")
        self.swal_content = page.locator("#swal2-content")
        self.swal_confirm_button = page.locator(".swal2-confirm")

    def wait_until_ready(self):
        expect(self.school_table).to_be_visible(timeout=MAX_WAIT_TIMEOUT_MS)
        expect(self.search_input).to_be_visible(timeout=MAX_WAIT_TIMEOUT_MS)

    def search_school(self, school_query: str):
        self.wait_until_ready()
        school_query = school_query.strip()
        self.search_input.fill(school_query)
        self.search_input.press("Enter")

        self._wait_for_school_search(school_query)
        matched_count = self._filtered_school_row_count()

        if matched_count != 1:
            raise AssertionError(
                f"Tìm trường '{school_query}' ra {matched_count} bản ghi. "
                "Cần đúng 1 bản ghi; hãy nhập mã trường hoặc tên trường cụ thể hơn."
            )

        expect(self.school_rows).to_have_count(1, timeout=SEARCH_WAIT_TIMEOUT_MS)
        return self.school_rows.first

    def _wait_for_school_search(self, school_query: str):
        self.page.wait_for_function(
            """
            (query) => {
                const input = document.querySelector('#tableSchool_filter input[type="search"]');
                if (!input || input.value !== query) {
                    return false;
                }

                const processing = document.querySelector('#tableSchool_processing');
                if (processing) {
                    const style = window.getComputedStyle(processing);
                    const isVisible = style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && style.opacity !== '0';
                    if (isVisible) {
                        return false;
                    }
                }

                const $ = window.jQuery;
                if ($ && $.fn && $.fn.dataTable && $.fn.dataTable.isDataTable('#tableSchool')) {
                    const table = $('#tableSchool').DataTable();
                    return table.search() === query;
                }

                return document.querySelector('#tableSchool tbody') !== null;
            }
            """,
            school_query,
            timeout=SEARCH_WAIT_TIMEOUT_MS,
        )

    def _filtered_school_row_count(self):
        return self.page.evaluate(
            """
            () => {
                const $ = window.jQuery;
                if ($ && $.fn && $.fn.dataTable && $.fn.dataTable.isDataTable('#tableSchool')) {
                    const table = $('#tableSchool').DataTable();
                    const info = table.page.info();
                    if (info && Number.isFinite(info.recordsDisplay)) {
                        return info.recordsDisplay;
                    }
                    return table.rows({ search: 'applied' }).count();
                }

                return Array
                    .from(document.querySelectorAll('#tableSchool tbody tr'))
                    .filter((row) => !row.querySelector('.dataTables_empty'))
                    .length;
            }
            """
        )

    def capture_result_screenshot(self):
        screenshot_path = os.getenv("VNEDU_SCREENSHOT_PATH")
        if not screenshot_path:
            return

        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        self.page.screenshot(path=screenshot_path, full_page=False)

    def _wait_for_processing_to_finish(
        self, timeout: int = MAX_WAIT_TIMEOUT_MS, require_visible: bool = False
    ):
        if require_visible:
            expect(self.loading_modal).to_be_visible(timeout=MAX_WAIT_TIMEOUT_MS)
        else:
            try:
                expect(self.loading_modal).to_be_visible(timeout=MAX_WAIT_TIMEOUT_MS)
            except AssertionError:
                pass
        expect(self.loading_modal).to_be_hidden(timeout=timeout)

    def _expect_success_alert(
        self, expected_message: str, timeout: int = MAX_WAIT_TIMEOUT_MS
    ):
        expect(self.swal_popup).to_be_visible(timeout=timeout)
        message = self.swal_content.inner_text()
        popup_class = self.swal_popup.get_attribute("class") or ""

        if "swal2-icon-error" in popup_class:
            raise AssertionError(f"Hệ thống báo lỗi khi đồng bộ: {message}")

        assert "swal2-icon-success" in popup_class, (
            f"SweetAlert không phải thông báo thành công: {message}"
        )
        expect(self.swal_content).to_contain_text(
            expected_message, timeout=MAX_WAIT_TIMEOUT_MS
        )

    def _confirm_swal(self):
        expect(self.swal_confirm_button).to_be_visible(timeout=MAX_WAIT_TIMEOUT_MS)
        self.swal_confirm_button.click()
        expect(self.swal_popup).to_be_hidden(timeout=MAX_WAIT_TIMEOUT_MS)

    def _fail_if_error_alert_is_visible(self):
        if self.swal_popup.count() == 0 or not self.swal_popup.is_visible():
            return

        popup_class = self.swal_popup.get_attribute("class") or ""
        if "swal2-icon-error" in popup_class:
            message = self.swal_content.inner_text()
            raise AssertionError(f"Hệ thống báo lỗi khi mở modal đồng bộ: {message}")
