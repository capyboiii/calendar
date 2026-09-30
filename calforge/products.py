"""Các loại lịch treo tường tool làm được. Mỗi cuốn ghi loại của nó trong concept.json ("product").

- wall_grid:     26 trang - máy tự vẽ nền grid AI + dựng lịch ngày chính xác cho 12 tháng.
- wall_premade:  lịch có trang grid thiết kế sẵn - máy KHÔNG gen nền grid. Mỗi cuốn gồm bìa trước,
                 12 trang tranh, bìa sau (14 trang). Trang grid 12 tháng do người dùng thêm sau vào
                 formats/<khổ>/grids/m01.png..m12.png (đúng cỡ trang); có đủ thì tự chèn thành 26 trang.
"""
from __future__ import annotations

PRODUCTS = {
    "wall_grid": {
        "name": "Lịch treo tường - máy tự thiết kế grid",
        "folder": "Wall Calendar (Blank)",   # projects/<folder>/<chủ đề>/<cuốn>
        "formats": ["printify_wall_11x8_5", "printify_wall_14x11_5"],
        "ai_grid": True,
        "mockups": True,
        "printify": True,
    },
    "wall_premade": {
        "name": "Lịch treo tường - grid in sẵn (máy chỉ làm tranh)",
        "folder": "Wall Calendar",
        "formats": ["premade_wall_11x8_5", "premade_wall_14x11_5"],
        "ai_grid": False,
        "mockups": True,         # 5 ảnh: bìa (dùng chung) + 4 mockup grid in sẵn (render/mockups.PREMADE_PREVIEWS)
        "printify": False,       # blueprint Printify của loại này chưa cấu hình
    },
}
DEFAULT = "wall_grid"


def product_id(concept: dict | None) -> str:
    pid = (concept or {}).get("product")
    return pid if pid in PRODUCTS else DEFAULT


def get(concept_or_id: dict | str | None) -> dict:
    pid = concept_or_id if isinstance(concept_or_id, str) else product_id(concept_or_id)
    return PRODUCTS.get(pid, PRODUCTS[DEFAULT])


def root(projects_root, concept_or_id: dict | str | None = None):
    """Thư mục gốc của một loại lịch: projects/Wall Calendar (Blank) | projects/Wall Calendar."""
    from pathlib import Path
    return Path(projects_root) / get(concept_or_id)["folder"]


def formats(concept_or_id: dict | str | None) -> list[str]:
    return list(get(concept_or_id)["formats"])


def ai_grid(concept: dict | None) -> bool:
    return get(concept)["ai_grid"]


# Cách làm trang lịch của Wall Calendar (Blank):
#   "ai_page"    - AI vẽ NGUYÊN 12 trang lịch (tên tháng, thứ, ngày, ngày lễ); OCR soát ngày, sai thì vẽ lại.
#   "background" - AI vẽ 1 nền dùng chung, code in lưới + chữ (cách cũ; cuốn cũ không có khoá grid_mode).
DEFAULT_GRID_MODE = "ai_page"
GRID_MODES = ("ai_page", "background")


def ai_page(concept: dict | None) -> bool:
    """Cuốn này có 12 trang lịch do AI vẽ nguyên trang (g01..g12)."""
    return ai_grid(concept) and ((concept or {}).get("style") or {}).get("grid_mode") == "ai_page"


MOCKUP_MODES = ("template", "ai")     # ảnh quảng cáo: code ghép khung có sẵn | AI gen bối cảnh (chỉ "AI vẽ cả trang")


def ai_mockups(concept: dict | None) -> bool:
    """Cuốn "AI vẽ cả trang" chọn "AI gen mockup": 4 ảnh quảng cáo do AI dựng bối cảnh."""
    return ai_page(concept) and ((concept or {}).get("style") or {}).get("mockup_mode") == "ai"


def art_jobs(concept: dict | None) -> list[str]:
    """Ảnh AI một cuốn cần để in (không tính ảnh neo): bìa, 12 tranh tháng, rồi trang lịch / nền grid."""
    jobs = ["cover"] + [f"m{m:02d}" for m in range(1, 13)]
    if ai_page(concept):
        return jobs + [f"g{m:02d}" for m in range(1, 13)]
    return jobs + (["grid"] if ai_grid(concept) else [])
