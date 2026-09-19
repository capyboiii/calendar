"""Dựng 2 trang của một tháng theo template Printify Wall Calendar 11x8.5:

- trang "month": tranh AI tràn kín cả file (kể cả bleed), không chữ;
- trang "grid": tiêu đề tháng, subtitle, câu Kinh Thánh, lưới ngày 5 hàng (ô ghép 23/30, 24/31),
  ngày lễ, cột ghi chú/prayer list tuỳ grid_function.

Mọi vị trí suy ra từ format.json (vùng lò xo, lỗ treo, lề chữ) - không gõ cứng theo một tháng.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageFilter

from ..core import dates
from . import fonts
from .draw import Page, wrap

SIDE_PANEL = {"prayer_list": "PRAYER LIST", "notes_column": "NOTES"}

# Lớp họa tiết trên trang lưới: slot nào bật. Concept có thể ghi đè bằng style.grid_decor.
#   title_side  : cạnh tên tháng
#   panel_bottom: cuối cột prayer list / notes (dòng kẻ tự ngắn lại nhường chỗ)
#   rule_center : giữa đường kẻ ngang dưới tiêu đề (cắt ngang đường kẻ)
DEFAULT_DECOR = {"title_side": True, "panel_bottom": True, "rule_center": False}


def _fit(aspect: float, max_w: float, max_h: float) -> tuple[float, float]:
    """Kích thước họa tiết (w, h) vừa khung max_w x max_h, giữ tỉ lệ (aspect = h / w)."""
    w = min(max_w, max_h / aspect)
    return w, w * aspect


# ---------------------------------------------------------------------------
# Trang ảnh
# ---------------------------------------------------------------------------
def prepare_fullbleed(src: Path, dst: Path, size: tuple[int, int], anchor_y: float = 0.5) -> dict:
    """Cắt ảnh cho vừa khổ file (cover, không méo), phóng đúng pixel. Trả về thông tin độ phóng."""
    W, H = size
    img = Image.open(src).convert("RGB")
    scale = max(W / img.width, H / img.height)
    rw, rh = round(img.width * scale), round(img.height * scale)
    big = img.resize((rw, rh), Image.LANCZOS)
    if scale > 1.05:  # phóng bằng Lanczos hay mềm; unsharp nhẹ - bản thật nên upscale bằng AI
        big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))
    left, top = (rw - W) // 2, round((rh - H) * anchor_y)
    big.crop((left, top, left + W, top + H)).save(dst, quality=93)
    return {"source_px": img.size, "upscale": round(scale, 2),
            "cropped_px": (round((rw - W) / scale), round((rh - H) / scale))}


def month_page(fmt: dict, art: Path, label: str) -> Page:
    W, H = fmt["size_px"]
    page = Page(W, H, "month", label)
    page.image(art, 0, 0, W, H)
    return page


# ---------------------------------------------------------------------------
# Trang lưới
# ---------------------------------------------------------------------------
class GridLayout:
    """Các mốc toạ độ (px) của trang lưới, tính từ format."""

    def __init__(self, fmt: dict, side_panel: bool):
        W, H = fmt["size_px"]
        bleed, margin = fmt["bleed_px"], fmt["text_margin_px"]
        keep = fmt["pages"]["grid"]["keep_out"]
        binding_bottom = max(k["rect"][3] for k in keep if "rect" in k and k["rect"][1] == 0)
        hole = next(k["circle"] for k in keep if "circle" in k)
        self.x0, self.x1 = bleed + margin, W - bleed - margin
        self.top = binding_bottom + 60                   # đầu vùng nội dung, dưới lò xo
        self.title_base = self.top + 150
        self.sub_base = self.title_base + 80
        self.rule_y = self.sub_base + 50
        self.week_top = self.rule_y + 30
        self.week_h = 70
        self.grid_top = self.week_top + self.week_h
        self.grid_bottom = hole[1] - hole[2] - 40        # lưới dừng phía trên lỗ treo
        self.panel_gap = 60
        self.grid_x1 = self.x1 - (620 + self.panel_gap if side_panel else 0)
        self.panel_x0 = self.grid_x1 + self.panel_gap


def grid_page(fmt: dict, concept: dict, month_no: int, label: str, verse_text: str | None,
              ornament: dict | None = None) -> Page:
    """ornament: {"left": Path, "right": Path (bản lật gương), "aspect": cao/rộng} hoặc None."""
    W, H = fmt["size_px"]
    year, market = concept["year"], concept.get("market", "US")
    st, pal = concept["style"], concept["style"]["palette"]
    m = concept["months"][month_no - 1]
    panel = SIDE_PANEL.get(concept.get("grid_function", "standard"))
    L = GridLayout(fmt, bool(panel))

    f_title = fonts.font(st["fonts"]["title"], "semibold")
    f_body = fonts.font(st["fonts"]["body"], "regular")
    f_body_b = fonts.font(st["fonts"]["body"], "semibold")
    f_body_i = fonts.font(st["fonts"]["body"], "italic")
    f_num = fonts.font(st["fonts"]["numbers"], "regular")

    page = Page(W, H, "grid", label)
    page.rect(0, 0, W, H, fill=pal["paper"])

    decor = {**DEFAULT_DECOR, **(st.get("grid_decor") or {})} if ornament else {}

    # ---- tiêu đề ----
    name = dates.MONTH_NAMES[month_no - 1].upper()
    title = page.text(L.x0, L.title_base, name, f_title, 150, pal["title"], tracking=8, role="month title")
    sub = f"{year}   ·   {m['subtitle'].upper()}"
    subtitle = page.text(L.x0, L.sub_base, sub, f_body, 38, pal["accent"], tracking=8, role="subtitle")
    header_end = max(title.bbox()[2], subtitle.bbox()[2])

    if decor.get("title_side"):
        w, h = _fit(ornament["aspect"], 480, 135)
        x = title.bbox()[2] + 50
        y = L.title_base - 150 * 0.36 - h / 2
        page.image(ornament["left"], x, y, w, h, role="ornament title_side")
        header_end = max(header_end, x + w)

    # ---- câu Kinh Thánh / nội dung tháng (khối bên phải tiêu đề) ----
    content = m.get("content") or {}
    block_x0 = header_end + 100
    block_w = L.x1 - block_x0
    ref = content.get("value", "") if concept.get("content_type") == "bible_verse_kjv" else ""
    body = verse_text if ref else content.get("value", "")
    if body:
        size, lines = 36, wrap(f"“{body}”" if ref else body, f_body_i, 36, block_w)
        while len(lines) > 3 and size > 27:
            size -= 2
            lines = wrap(f"“{body}”" if ref else body, f_body_i, size, block_w)
        first_base = L.top + 70
        for i, line in enumerate(lines):
            page.text(L.x1, first_base + i * size * 1.3, line, f_body_i, size, pal["text"], "end", role="verse")
        ref_base = first_base + len(lines) * size * 1.3 + 12
    else:
        ref_base = L.top + 90
    if ref:
        page.text(L.x1, ref_base, f"{ref.upper()}  KJV", f_body_b, 28, pal["accent"], "end", tracking=5, role="verse ref")

    page.line(L.x0, L.rule_y, L.x1, L.rule_y, pal["grid_line"], 2)
    if decor.get("rule_center"):
        w, h = _fit(ornament["aspect"], 360, 60)
        cx = (L.x0 + L.x1) / 2
        page.rect(cx - w / 2 - 30, L.rule_y - h / 2, w + 60, h, fill=pal["paper"])  # cắt đường kẻ
        page.image(ornament["left"], cx - w / 2, L.rule_y - h / 2, w, h, role="ornament rule_center")

    # ---- tên thứ ----
    cw = (L.grid_x1 - L.x0) / 7
    for col, wd in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]):
        page.text(L.x0 + cw * (col + 0.5), L.week_top + 48, wd, f_body_b, 30,
                  pal["accent"] if col == 0 else pal["title"], "middle", tracking=6, role="weekday")

    # ---- ô ngày ----
    rows, cells = dates.month_cells(year, month_no, dates.SUN, "split5")
    ch = (L.grid_bottom - L.grid_top) / rows
    hol = {d: names for d, names in dates.holidays_for(year, market).items() if d.month == month_no}
    pad = 22
    for idx, days in enumerate(cells):
        if not days:
            continue
        r, col = divmod(idx, 7)
        x0, y0 = L.x0 + col * cw, L.grid_top + r * ch
        color = pal["accent"] if col == 0 else pal["text"]
        if len(days) == 1:
            _day(page, days[0], x0 + pad, y0 + pad + 40, f_num, 46, color, "start")
            _holiday(page, hol.get(days[0]), x0 + pad, y0 + ch - pad, cw - 2 * pad, f_body, pal["accent"], "start")
        else:
            page.line(x0, y0 + ch, x0 + cw, y0, pal["grid_line"], 1.5)
            _day(page, days[0], x0 + pad, y0 + pad + 34, f_num, 38, color, "start")
            _day(page, days[1], x0 + cw - pad, y0 + ch - pad, f_num, 38, color, "end")
            _holiday(page, hol.get(days[0]), x0 + pad, y0 + pad + 34 + 38, cw * 0.5, f_body, pal["accent"], "start", below=True)
            _holiday(page, hol.get(days[1]), x0 + cw - pad, y0 + ch - pad - 52, cw * 0.5, f_body, pal["accent"], "end")

    for col in range(1, 7):
        x = L.x0 + col * cw
        page.line(x, L.grid_top, x, L.grid_bottom, pal["grid_line"], 2)
    for r in range(1, rows):
        y = L.grid_top + r * ch
        page.line(L.x0, y, L.grid_x1, y, pal["grid_line"], 2)
    page.rect(L.x0, L.grid_top, L.grid_x1 - L.x0, L.grid_bottom - L.grid_top, stroke=pal["grid_line"], stroke_w=3)
    page.grid_box = (L.x0, L.grid_top, L.grid_x1, L.grid_bottom)

    # ---- cột ghi chú / prayer list ----
    if panel:
        page.text(L.panel_x0, L.week_top + 48, panel, f_body_b, 30, pal["accent"], tracking=8, role="panel title")
        lines_end = L.grid_bottom
        if decor.get("panel_bottom"):
            w, h = _fit(ornament["aspect"], (L.x1 - L.panel_x0) * 0.9, 210)
            x = (L.panel_x0 + L.x1) / 2 - w / 2
            page.image(ornament["right"], x, L.grid_bottom - h, w, h, role="ornament panel_bottom")
            lines_end = L.grid_bottom - h - 40
        y = L.grid_top + 90
        while y <= lines_end:
            page.line(L.panel_x0, y, L.x1, y, pal["grid_line"], 2)
            y += 92
    return page


def _day(page: Page, d: dt.date, x, y, font, size, color, anchor):
    page.text(x, y, str(d.day), font, size, color, anchor, role="date")


def _holiday(page: Page, names, x, y, max_w, font, color, anchor, below=False):
    """Tên lễ: in hoa nhỏ, tự xuống dòng tối đa 2 dòng; `below` = viết xuống dưới từ y."""
    if not names:
        return
    size = 26
    lines = wrap(" · ".join(names).upper(), font, size, max_w)
    while len(lines) > 2 and size > 25:
        size -= 1
        lines = wrap(" · ".join(names).upper(), font, size, max_w)
    for i, line in enumerate(lines if below else reversed(lines)):
        yy = y + i * size * 1.25 if below else y - i * size * 1.25
        page.text(x, yy, line, font, size, color, anchor, tracking=2, role="holiday")
