"""Cấu trúc thư mục - mọi module lấy đường dẫn ở đây, không tự ghép tên thư mục.

    projects/<chủ đề>/
      Plants of Scripture/          một cuốn = tên cuốn lịch (mã góc tiếp cận nằm trong _he_thong/angle_id.txt)
      Walk by Faith/
      Báo cáo batch.md              kết quả batch gần nhất: cuốn nào xong, dừng ở đâu, vì sao
      _he_thong/                    (ẩn) angles.json, ideation/ (sổ hỏi/đáp ChatGPT), batch.json

Mở một cuốn ra, người không rành kỹ thuật chỉ thấy 3 thứ:

    <cuốn>/
      preview/      5 ảnh quảng cáo (listing)
      11x8.5/       26 trang upload Printify + PDF in tại nhà
      14x11.5/      26 trang upload Printify + PDF in tại nhà
      _he_thong/    (ẩn) concept/listing/status, ảnh AI gốc, ảnh upscale, báo cáo kỹ thuật...

File trung gian (ảnh cắt tạm, PDF vector để xuất PNG) chỉ nằm trong thư mục tạm lúc render rồi xoá.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

SYSTEM = "_he_thong"
RAW = f"{SYSTEM}/anh_ai"                # ảnh ChatGPT gốc (+ anchor_swatch, nền grid)
FINAL = f"{SYSTEM}/anh_upscale"         # ảnh đã phóng to để in
TECH = f"{SYSTEM}/ky_thuat"             # jobs, báo cáo render, kiểm tra lịch, palette, QC, ảnh bị loại
LISTING = "preview"
PRINT = {"printify_wall_11x8_5": "11x8.5", "printify_wall_14x11_5": "14x11.5"}
SIZE_LABEL = dict(PRINT)


def system(c: Path) -> Path:
    return c / SYSTEM


def concept_file(c: Path) -> Path:
    return c / SYSTEM / "concept.json"


def listing_file(c: Path) -> Path:
    return c / SYSTEM / "listing.json"


def status_file(c: Path) -> Path:
    return c / SYSTEM / "status.json"


def is_book(c: Path) -> bool:
    return concept_file(c).is_file()


def books(projects_root: Path) -> list[Path]:
    """Mọi cuốn lịch: projects/<keyword>/<cuốn>/."""
    return sorted(f.parent.parent for f in projects_root.glob(f"*/*/{SYSTEM}/concept.json"))


def raw(c: Path) -> Path:
    return c / RAW


def final(c: Path) -> Path:
    return c / FINAL


def print_dir(c: Path, format_id: str = "printify_wall_11x8_5") -> Path:
    return c / PRINT[format_id]


def printable_file(c: Path, format_id: str = "printify_wall_11x8_5") -> Path:
    """PDF in tại nhà (không bleed, có lề) nằm cùng thư mục với trang in của khổ đó."""
    return print_dir(c, format_id) / f"in_tai_nha_{SIZE_LABEL[format_id]}.pdf"


def listing(c: Path) -> Path:
    return c / LISTING


def tech(c: Path, name: str = "") -> Path:
    return c / TECH / name if name else c / TECH


def render_file(c: Path, name: str, format_id: str = "printify_wall_11x8_5") -> Path:
    """Báo cáo của lần render theo khổ: _he_thong/ky_thuat/render_11x8.5_<name>."""
    return tech(c, f"render_{SIZE_LABEL[format_id]}_{name}")


def ensure_system(c: Path) -> Path:
    """Tạo _he_thong/ và đặt thuộc tính ẩn trên Windows (người xem thư mục chỉ thấy preview + 2 khổ in)."""
    d = system(c)
    d.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        try:
            subprocess.run(["attrib", "+h", str(d)], check=False, capture_output=True)
        except OSError:
            pass
    return d



# ---------------------------------------------------------------------------
# Cấp chủ đề (keyword) và tên thư mục cuốn
# ---------------------------------------------------------------------------
ANGLE_ID = "angle_id.txt"
BATCH_REPORT = "Báo cáo batch.md"


def angles_file(kdir: Path) -> Path:
    return kdir / SYSTEM / "angles.json"


def ideation_dir(kdir: Path) -> Path:
    return kdir / SYSTEM / "ideation"


def batch_file(kdir: Path) -> Path:
    return kdir / SYSTEM / "batch.json"


def batch_report_file(kdir: Path) -> Path:
    return kdir / BATCH_REPORT


def book_angle_id(c: Path) -> str:
    """Mã góc tiếp cận của một thư mục cuốn (kể cả cuốn hỏng chưa có concept.json)."""
    f = c / SYSTEM / ANGLE_ID
    if f.is_file():
        return f.read_text(encoding="utf-8").strip()
    try:
        aid = json.loads(concept_file(c).read_text(encoding="utf-8")).get("angle_id", "")
        if aid:
            return str(aid)
    except (OSError, ValueError):
        pass
    m = re.match(r"(r\d+a\d+)-", c.name)         # thư mục kiểu cũ "r1a2-ten-cuon"
    return m.group(1) if m else ""


def find_book(kdir: Path, angle_id: str) -> Path | None:
    if not kdir.is_dir():
        return None
    for d in sorted(kdir.iterdir()):
        if d.is_dir() and d.name != SYSTEM and (d / SYSTEM).is_dir() and book_angle_id(d) == angle_id:
            return d
    return None


def book_folder_name(title: str) -> str:
    """Tên thư mục đọc được từ tên cuốn: bỏ ký tự Windows cấm, gọn khoảng trắng, tối đa 60 ký tự."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(title or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:60].rstrip(" .") or "Lich chua dat ten"


def new_book_dir(kdir: Path, title: str, angle_id: str) -> Path:
    """Thư mục cho một cuốn mới, trùng tên thì thêm (2), (3)... Ghi mã góc để tìm lại được."""
    base = book_folder_name(title)
    d, i = kdir / base, 2
    while d.exists():
        d, i = kdir / f"{base} ({i})", i + 1
    ensure_system(d)
    (d / SYSTEM / ANGLE_ID).write_text(angle_id, encoding="utf-8")
    return d
