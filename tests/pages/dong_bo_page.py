from playwright.sync_api import Page

from pages.dong_bo.kqht_y_te_page import DongBoKqhtYTePage
from pages.dong_bo.ttcb_lh_page import DongBoTtcbLhPage


class DongBoPage(DongBoTtcbLhPage, DongBoKqhtYTePage):
    def __init__(self, page: Page):
        DongBoTtcbLhPage.__init__(self, page)
        DongBoKqhtYTePage.__init__(self, page)
