"""Cấu hình dùng chung cho toàn bộ quy trình Khai phá dữ liệu (Giai đoạn 2: 2.1 - 2.5).

Vị trí file: `config.py` đặt tại thư mục gốc dự án.

Cách dùng trong Notebook tổng đặt tại thư mục gốc (vd: NhomXX_MiningPipeline.ipynb):
    import config

Cách dùng trong Notebook đặt tại `Giai Đoạn 2/` (vd: Step_2_1_Data_Cleaning.ipynb):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.cwd().parent))
    import config
"""

from pathlib import Path

# =============================================================================
# 1. THƯ MỤC GỐC DỰ ÁN (trỏ cố định về thư mục chứa config.py)
# =============================================================================
PROJECT_ROOT: Path = Path(__file__).resolve().parent

# =============================================================================
# 2. ĐƯỜNG DẪN TƯƠNG ĐỐI DUY NHẤT (tính từ PROJECT_ROOT)
# =============================================================================
RAW_DATA_REL_PATH: str = "Giai Đoạn 1/data/raw_jobs_data.csv"
SKILL_DICT_REL_PATH: str = "data/reference/skill_dictionary.csv"
CLEAN_DATA_REL_PATH: str = "data/clean/clean_data.csv"

# Đường dẫn đầy đủ dạng Path (tự động ánh xạ theo PROJECT_ROOT, tránh lỗi cwd)
RAW_DATA_PATH: Path = PROJECT_ROOT / RAW_DATA_REL_PATH
SKILL_DICT_PATH: Path = PROJECT_ROOT / SKILL_DICT_REL_PATH
CLEAN_DATA_PATH: Path = PROJECT_ROOT / CLEAN_DATA_REL_PATH

# Thư mục làm việc & đầu ra bổ trợ cho Giai đoạn 2 và Báo cáo
PHASE1_DIR: Path = PROJECT_ROOT / "Giai Đoạn 1"
PHASE2_DIR: Path = PROJECT_ROOT / "Giai Đoạn 2"
DATA_DIR: Path = PROJECT_ROOT / "data"
REFERENCE_DIR: Path = DATA_DIR / "reference"
CLEAN_DIR: Path = DATA_DIR / "clean"
OUTPUTS_DIR: Path = PROJECT_ROOT / "outputs"
FIGURES_DIR: Path = OUTPUTS_DIR / "figures"
TABLES_DIR: Path = OUTPUTS_DIR / "tables"

# =============================================================================
# 3. HẰNG SỐ QUY ĐỔI TỶ GIÁ USD -> VNĐ (CHỐT CỐ ĐỊNH CHO TOÀN BỘ PIPELINE)
# =============================================================================
# Ghi chú: Khớp ngày kết thúc thu thập dữ liệu thô (Timestamp: 2026-11-18 -> 2026-11-19).
USD_TO_VND: int = 25_646
USD_TO_MILLION_VND: float = USD_TO_VND / 1_000_000  # 0.025646 triệu VNĐ / 1 USD
USD_RATE_DATE: str = "2026-11-19"
USD_RATE_SOURCE: str = "Tỷ giá trung tâm — Ngân hàng Nhà nước Việt Nam (NHNN)"

# =============================================================================
# 4. QUY ƯỚC ĐỌC/GHI CSV DÙNG CHUNG
# =============================================================================
CSV_ENCODING: str = "utf-8-sig"


def ensure_directories() -> None:
    """Đảm bảo các thư mục dữ liệu và đầu ra của Giai đoạn 2 tồn tại."""
    for directory in (REFERENCE_DIR, CLEAN_DIR, PHASE2_DIR, FIGURES_DIR, TABLES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def usd_to_million_vnd(amount_usd: float) -> float:
    """Quy đổi mức lương từ USD sang đơn vị triệu VNĐ theo tỷ giá đã chốt."""
    return (amount_usd * USD_TO_VND) / 1_000_000


if __name__ == "__main__":
    ensure_directories()
    print(f"PROJECT_ROOT        : {PROJECT_ROOT}")
    print(f"RAW_DATA_REL_PATH   : {RAW_DATA_REL_PATH} (exists={RAW_DATA_PATH.exists()})")
    print(f"SKILL_DICT_REL_PATH : {SKILL_DICT_REL_PATH} (exists={SKILL_DICT_PATH.exists()})")
    print(f"CLEAN_DATA_REL_PATH : {CLEAN_DATA_REL_PATH} (exists={CLEAN_DATA_PATH.exists()})")
    print(
        f"USD_TO_VND          : {USD_TO_VND:,} VNĐ/USD "
        f"({USD_TO_MILLION_VND:.6f} triệu VNĐ/USD)"
    )
    print(f"USD_RATE_SOURCE     : {USD_RATE_SOURCE} (ngày {USD_RATE_DATE})")
