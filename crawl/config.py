# crawl/config.py

BASE_URL = "https://dongbo.csdl.edu.vn"
LOGIN_PATH = "/"                          # trang để lấy laravel_session
FORWARD_API_PATH = "/forward-api"

# Endpoint data
DATA_PATH = "/csdlgd-admin/heThongDoiTacTruong/danhSach"
DATA_METHOD = "POST"

# Pagination
PAGE_LIMIT = 25
REQUEST_DELAY_SECONDS = 0.3               # tránh hammer server

# Default filter — override khi gọi CSDLCrawler
DEFAULT_PAYLOAD_DATA = {
    "maDoiTac": "VNPT_NBH",
    "maDonVis": [],
    "maTruongs": [],
    "capHoc": [],
}

# Output
OUTPUT_DIR = "crawl/output"
CSV_FILENAME = "truong_hoc.csv"
TXT_FILENAME = "truong_hoc.txt"

# CSV columns (theo thứ tự)
CSV_COLUMNS = [
    "id",
    "maTruongHoc",
    "tenTruongHoc",
    "maDonVi",
    "tenDonVi",
    "maDoiTac",
    "tenDoiTac",
    "ngayCapNhat",
]
