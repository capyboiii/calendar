"""Dựng 2 trang của một tháng theo template Printify Wall Calendar 11x8.5:

- trang "month": tranh AI tràn kín cả file (kể cả bleed), không chữ;
- trang "grid": tiêu đề tháng, subtitle, câu Kinh Thánh, lưới ngày 5 hàng (ô ghép 23/30, 24/31),
  ngày lễ, cột ghi chú/prayer list tuỳ grid_function.

Mọi vị trí suy ra từ format.json (vùng lò xo, lỗ treo, lề chữ) - không gõ cứng theo một tháng.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from ..core import dates
from . import fonts
from .draw import Page, blend_hex, text_width, wrap
from .grid_compositions import get_composition


def _seamless_grid_background(bg_path: Path, paper_hex: str) -> Path:
    """Blend the illustrated perimeter into one uninterrupted paper surface."""
    out = bg_path.with_name(bg_path.stem + "_seamless.jpg")
    with Image.open(bg_path) as src:
        art = src.convert("RGB")
    w, h = art.size
    mw, mh = 512, max(2, round(512 * h / w))
    mask = Image.new("L", (mw, mh))
    pixels = mask.load()

    def edge_strength(distance: float, full: float, empty: float) -> float:
        t = max(0.0, min(1.0, (empty - distance) / (empty - full)))
        return t * t * (3 - 2 * t)

    for y in range(mh):
        yn = y / (mh - 1)
        vertical = edge_strength(min(yn, 1 - yn), .035, .205)
        for x in range(mw):
            xn = x / (mw - 1)
            horizontal = edge_strength(min(xn, 1 - xn), .012, .060)
            pixels[x, y] = round(max(.035, vertical, horizontal) * 255)
    mask = mask.resize((w, h), Image.Resampling.BILINEAR)
    paper = Image.new("RGB", (w, h), paper_hex)
    Image.composite(art, paper, mask).save(out, quality=94, subsampling=0)
    return out


SIDE_PANEL = {"prayer_list": "PRAYER LIST", "notes_column": "NOTES", "tracker": "HABIT TRACKER"}

FAMILY_TO_PRESET = {
    "mid_century_retro": "playful_editorial",
    "papercut_collage": "organic_capsules",
    "styled_photography": "quiet_luxury",
}

PRESET_ALIASES = {
    "art_matched": "art_matched", "art_matched_minimal": "art_matched",
    "2": "bento_planner", "bento": "bento_planner", "bento_planner": "bento_planner",
    "4": "quiet_luxury", "quiet": "quiet_luxury", "quiet_luxury": "quiet_luxury",
    "14": "soft_tech", "soft_tech": "soft_tech", "softtech": "soft_tech",
    "18": "fresh_monochrome", "fresh_monochrome": "fresh_monochrome", "monochrome": "fresh_monochrome",
    "22": "organic_capsules", "organic_capsules": "organic_capsules", "capsules": "organic_capsules",
    "24": "playful_editorial", "playful_editorial": "playful_editorial", "playful": "playful_editorial",
}

PRESET_NAMES = {
    "art_matched": "AI-designed Grid",
    "bento_planner": "02. Bento Planner",
    "quiet_luxury": "04. Quiet Luxury",
    "soft_tech": "14. Soft-Tech Planner",
    "fresh_monochrome": "18. Fresh Monochrome",
    "organic_capsules": "22. Organic Capsules",
    "playful_editorial": "24. Playful Editorial",
}


def resolve_grid_preset(concept: dict) -> str:
    """Mặc định grid bám artwork; chỉ dùng sáu layout cũ khi người dùng chọn thủ công."""
    explicit = concept.get("grid_preset") or concept.get("style", {}).get("grid_preset")
    if explicit:
        key = str(explicit).lower().strip().replace("-", "_").replace(" ", "_")
        if key in PRESET_ALIASES:
            return PRESET_ALIASES[key]
    selection = concept.get("grid_selection") or {}
    selected = selection.get("selected")
    if selection.get("mode") == "manual" and selected in PRESET_NAMES:
        return selected
    return "art_matched"


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
              background_art: Path | None = None) -> Page:
    """Dispatcher lựa chọn hàm dựng trang lưới theo preset tương ứng."""
    preset = resolve_grid_preset(concept)
    if preset == "art_matched":
        return _grid_art_matched(fmt, concept, month_no, label, verse_text, background_art)
    return _grid_page_modern(fmt, concept, month_no, label, verse_text, preset)


def _grid_page_modern(fmt: dict, concept: dict, month_no: int, label: str, verse_text: str | None,
                      preset: str) -> Page:
    renderers = {
        "bento_planner": _grid_bento,
        "quiet_luxury": _grid_quiet,
        "soft_tech": _grid_soft_tech,
        "fresh_monochrome": _grid_monochrome,
        "organic_capsules": _grid_capsules,
        "playful_editorial": _grid_playful,
    }
    return renderers[preset](fmt, concept, month_no, label, verse_text)


def _setup(fmt: dict, concept: dict, month_no: int, label: str, verse_text: str | None) -> dict:
    W, H = fmt["size_px"]
    st, pal = concept["style"], concept["style"]["palette"]
    month = concept["months"][month_no - 1]
    content = month.get("content") or {}
    ref = content.get("value", "") if concept.get("content_type") == "bible_verse_kjv" else ""
    body = verse_text if ref else content.get("value", "")
    page = Page(W, H, "grid", label)
    page.rect(0, 0, W, H, fill=pal["paper"])
    return {
        "page": page, "layout": GridLayout(fmt, False), "pal": pal, "month": month,
        "year": concept["year"], "market": concept.get("market", "US"),
        "name": dates.MONTH_NAMES[month_no - 1].upper(), "month_no": month_no,
        "body": body, "ref": ref,
        "title": fonts.font(st["fonts"]["title"], "bold"),
        "body_font": fonts.font(st["fonts"]["body"], "regular"),
        "body_b": fonts.font(st["fonts"]["body"], "bold"),
        "body_i": fonts.font(st["fonts"]["body"], "italic"),
        "num": fonts.font(st["fonts"]["numbers"], "semibold"),
        "panel": SIDE_PANEL.get(concept.get("grid_function", "standard"), "NOTES"),
    }


def _draw_quote(c: dict, x: float, y: float, width: float, anchor: str = "start",
                color: str | None = None, max_lines: int = 3) -> None:
    if not c["body"]:
        return
    size = 27
    value = f"“{c['body']}”" if c["ref"] else c["body"]
    lines = wrap(value, c["body_i"], size, width)
    while len(lines) > max_lines and size > 25:
        size -= 1
        lines = wrap(value, c["body_i"], size, width)
    for i, line in enumerate(lines[:max_lines]):
        c["page"].text(x, y + i * size * 1.28, line, c["body_i"], size,
                       color or c["pal"]["text"], anchor, role="verse")
    if c["ref"]:
        c["page"].text(x, y + min(max_lines, len(lines)) * size * 1.28 + 12,
                       f"{c['ref'].upper()}  KJV", c["body_b"], 25,
                       color or c["pal"]["accent"], anchor, tracking=3, role="verse ref")


def _calendar(c: dict, month_no: int):
    rows, cells = dates.month_cells(c["year"], month_no, dates.SUN, "split5")
    holidays = {d: names for d, names in dates.holidays_for(c["year"], c["market"]).items()
                if d.month == month_no}
    return rows, cells, holidays


def _grid_art_matched(fmt: dict, concept: dict, month_no: int, label: str,
                      verse_text: str | None, background_art: Path | None) -> Page:
    """One continuous illustrated page with a calm center and exact vector dates."""
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    W, H = fmt["size_px"]
    editorial = concept["style"].get("grid_page_mode", "editorial_illustration") == "editorial_illustration"
    _composition_key, composition = get_composition(concept["style"])
    paper = blend_hex(pal["paper"], "#FFFFFF", .58)
    if background_art is not None and background_art.is_file():
        # Sample a color, never enlarge AI texture underneath readable calendar content.
        with Image.open(background_art) as bg:
            iw, ih = bg.size
            sample = bg.convert("RGB").crop((int(iw * .3), int(ih * .4), int(iw * .7), int(ih * .6)))
            rgb = ImageStat.Stat(sample).median
        if min(rgb) >= 170 and max(rgb) - min(rgb) <= 65:
            paper = blend_hex("#" + "".join(f"{int(v):02X}" for v in rgb), "#FFFFFF", .40)
    ink = pal["title"]
    accent = pal["accent"]
    hair = blend_hex(paper, ink, .27)
    if background_art is not None:
        bg = background_art if editorial else _seamless_grid_background(background_art, paper)
        p.image(bg, 0, 0, W, H,
                role="grid background")

    # The title, quotation and calendar are printed directly on the paper.
    ix0, ix1 = L.x0 + 140, L.x1 - 140
    mid = (ix0 + ix1) / 2
    name_base = L.top + (225 if not editorial else composition["title_y"])
    name_size = 200 if len(c["name"]) <= 7 else 160
    align = "middle" if not editorial else composition["title_align"]
    title_x = mid if align == "middle" else ix0 if align == "start" else ix1
    p.text(title_x, name_base, c["name"], c["title"], name_size, ink, align,
           tracking=8, role="month title")
    # dải năm: rule ngắn — chấm — chữ năm — chấm — rule ngắn
    # Chừa thêm khoảng thở dưới các chữ hoa có chân/đuôi lớn (đặc biệt J trong JANUARY).
    yb = name_base + 82
    yr = str(c["year"])
    yr_w = text_width(yr, c["body_b"], 38, 10)
    p.text(title_x, yb, yr, c["body_b"], 38, accent, align, tracking=10, role="year")
    if editorial and align == "start":
        p.line(ix0, yb + 30, ix0 + 720, yb + 30, blend_hex(paper, accent, .62), 2)
    elif editorial and align == "end":
        p.line(ix1 - 720, yb + 30, ix1, yb + 30, blend_hex(paper, accent, .62), 2)
    else:
        for sgn in (-1, 1):
            edge = mid + sgn * (yr_w / 2 + 40)
            far = mid + sgn * 300
            p.line(edge, yb - 10, far, yb - 10, blend_hex(paper, accent, .55), 1.4)
            p.circle(far, yb - 10, 4, fill=accent)

    # --- Câu Kinh Thánh (căn giữa, in nghiêng) ---
    block_bottom = yb + 8
    if c["body"]:
        value = f"“{c['body']}”" if c["ref"] else c["body"]
        vsize = 34
        quote_width = composition["quote_width"] if editorial else (ix1 - ix0) - 120
        vlines = wrap(value, c["body_i"], vsize, quote_width)
        while len(vlines) > 2 and vsize > 27:
            vsize -= 1
            vlines = wrap(value, c["body_i"], vsize, quote_width)
        vy = yb + (96 if editorial else 78)
        for i, line in enumerate(vlines):
            p.text(title_x, vy + i * vsize * 1.34, line, c["body_i"], vsize, pal["text"],
                   align, role="verse")
        block_bottom = vy + len(vlines) * vsize * 1.34
        if c["ref"]:
            block_bottom += 44
            p.text(title_x, block_bottom, f"{c['ref'].upper()}   ·   KJV", c["body_b"], 25,
                   accent, align, tracking=6, role="verse ref")

    # --- Lưới ngày ---
    gx0, gx1 = L.x0 + 110, L.x1 - 110
    width = gx1 - gx0
    cw = width / 7
    rows, cells = dates.month_cells(c["year"], month_no, dates.MON, "natural")
    grid_bottom = L.grid_bottom - 80
    week_base = max(name_base + 250, block_bottom + 96,
                    H * composition["grid_top"] if editorial else 0)
    grid_top = week_base + 34
    ch = (grid_bottom - grid_top) / rows

    # header thứ (editorial, không thanh đặc)
    for col, wd in enumerate(("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")):
        wc = accent if col >= 5 else ink
        p.text(gx0 + cw * (col + .5), week_base, wd, c["body_b"], 31, wc,
               "middle", tracking=4, role="weekday")
    for col in range(1, 7):
        x = gx0 + col * cw
        p.line(x, grid_top, x, grid_bottom, hair, 1.7)
    for row in range(rows + 1):
        y = grid_top + row * ch
        lw = 3.4 if row in (0, rows) else 1.7
        p.line(gx0, y, gx1, y, blend_hex(paper, ink, .5) if row in (0, rows) else hair, lw)

    holidays = {d: names for d, names in dates.holidays_for(c["year"], c["market"]).items()
                if d.month == month_no}
    for idx, days in enumerate(cells):
        if not days:
            continue
        day = days[0]
        row, col = divmod(idx, 7)
        left, top = gx0 + col * cw, grid_top + row * ch
        color = accent if col >= 5 else pal["text"]
        date_text = p.text(left + 28, top + 72, str(day.day), c["num"], 58, color, role="date")
        p.cell_texts.append((date_text, row, col))
        names = holidays.get(day)
        if names:
            holiday_lines = wrap(" · ".join(names).upper(), c["body_font"], 25, cw - 52)
            for i, line in enumerate(holiday_lines):
                t = p.text(left + 28, top + ch - 24 - (len(holiday_lines) - 1 - i) * 32,
                           line, c["body_font"], 25, accent, role="holiday")
                p.cell_texts.append((t, row, col))
    p.grid_box = (gx0, grid_top, gx1, grid_bottom)
    p.calendar = {"year": c["year"], "month": month_no, "week_start": dates.MON, "rows": rows}
    return p


def _weekdays(c: dict, x0: float, width: float, baseline: float, color_weekend: bool = True) -> None:
    cw = width / 7
    for col, wd in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]):
        color = c["pal"]["accent"] if color_weekend and col in (0, 6) else c["pal"]["title"]
        c["page"].text(x0 + cw * (col + .5), baseline, wd, c["body_b"], 27,
                       color, "middle", tracking=5, role="weekday")


def _date_text(c: dict, cells: list, holidays: dict, x0: float, y0: float,
               width: float, height: float, rows: int, number_anchor: str = "start",
               inset: float = 22, holiday_bottom: float | None = None,
               holiday_edge_inset: float | None = None) -> None:
    page, pal = c["page"], c["pal"]
    cw, ch = width / 7, height / rows
    for idx, days in enumerate(cells):
        if not days:
            continue
        row, col = divmod(idx, 7)
        left, top = x0 + col * cw, y0 + row * ch
        color = pal["accent"] if col in (0, 6) else pal["text"]
        if number_anchor == "middle":
            nx = left + cw / 2
        elif number_anchor == "end":
            nx = left + cw - inset
        else:
            nx = left + inset
        if len(days) == 1:
            _day(page, days[0], nx, top + inset + 38, c["num"], 42, color, number_anchor)
            holiday_y = top + ch - (holiday_bottom or inset)
            if holiday_edge_inset and col == 0:
                holiday_x, holiday_anchor = left + holiday_edge_inset, "start"
            elif holiday_edge_inset and col == 6:
                holiday_x, holiday_anchor = left + cw - holiday_edge_inset, "end"
            else:
                holiday_x, holiday_anchor = left + inset, "start"
            _holiday(page, holidays.get(days[0]), holiday_x, holiday_y,
                     cw - inset - (holiday_edge_inset or inset),
                     c["body_font"], pal["accent"], holiday_anchor)
        else:
            page.line(left + 4, top + ch - 4, left + cw - 4, top + 4, pal["grid_line"], 1)
            _day(page, days[0], left + inset, top + inset + 34, c["num"], 36, color, "start")
            _day(page, days[1], left + cw - inset, top + ch - inset, c["num"], 36, color, "end")
            _holiday(page, holidays.get(days[0]), left + inset, top + inset + 72,
                     cw * .42, c["body_font"], pal["accent"], "start", below=True)
            _holiday(page, holidays.get(days[1]), left + cw - inset,
                     top + ch - (holiday_bottom or inset) - 48,
                     cw * .42, c["body_font"], pal["accent"], "end")


def _grid_bento(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 8
    width = x1 - x0
    side_w, gap = 570, 34
    cal_w = width - side_w - gap
    cal_x1, side_x = x0 + cal_w, x0 + cal_w + gap
    tint = blend_hex(pal["paper"], pal["accent"], .14)
    tint2 = blend_hex(pal["paper"], pal["title"], .08)

    p.round_rect(x0, top, cal_w * .58, 265, 28, fill=tint)
    p.round_rect(x0 + cal_w * .60, top, cal_w * .40, 265, 28, fill=tint2)
    p.text(x0 + 44, top + 132, c["name"], c["title"], 106, pal["title"], tracking=3, role="month title")
    p.text(x0 + 48, top + 195, f"{c['year']}  ·  {c['month']['subtitle'].upper()}",
           c["body_b"], 28, pal["accent"], tracking=4, role="subtitle")
    _draw_quote(c, x0 + cal_w * .63, top + 82, cal_w * .33)

    grid_top, grid_bottom = top + 410, L.grid_bottom
    _weekdays(c, x0, cal_w, grid_top - 35)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = cal_w / 7, (grid_bottom - grid_top) / rows
    for idx in range(rows * 7):
        row, col = divmod(idx, 7)
        fill = tint if col in (0, 6) else blend_hex(pal["paper"], pal["title"], .025)
        p.round_rect(x0 + col * cw + 7, grid_top + row * ch + 7,
                     cw - 14, ch - 14, 18, fill=fill, stroke=pal["grid_line"], stroke_w=1.2)
    _date_text(c, cells, hol, x0, grid_top, cal_w, grid_bottom - grid_top, rows)

    p.round_rect(side_x, top + 125, side_w, 410, 30, fill=pal["title"])
    p.text(side_x + 34, top + 195, c["panel"], c["body_b"], 29, pal["paper"], tracking=5, role="panel title")
    y = top + 260
    while y < top + 495:
        p.line(side_x + 34, y, x1 - 34, y, blend_hex(pal["title"], pal["paper"], .35), 1)
        y += 64
    p.round_rect(side_x, top + 565, side_w, grid_bottom - (top + 565), 30, fill=tint2)
    p.text(side_x + 34, top + 625, "MONTH FOCUS", c["body_b"], 26, pal["accent"], tracking=4, role="panel title")
    p.text(side_x + 34, top + 700, c["month"]["subtitle"].upper(), c["body_font"], 27, pal["text"], role="panel text")
    p.grid_box = (x0, grid_top, cal_x1, grid_bottom)
    return p


def _grid_quiet(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 10
    width = x1 - x0
    p.text(x0, top + 145, c["name"], c["title"], 136, pal["title"], tracking=13, role="month title")
    p.text(x0 + 4, top + 214, f"{c['year']}  ·  {c['month']['subtitle'].upper()}",
           c["body_font"], 29, pal["accent"], tracking=8, role="subtitle")
    _draw_quote(c, x1, top + 92, width * .40, "end")
    p.line(x0, top + 286, x1, top + 286, pal["grid_line"], 1.4)

    grid_top, grid_bottom = top + 455, L.grid_bottom
    _weekdays(c, x0, width, grid_top - 42)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = width / 7, (grid_bottom - grid_top) / rows
    weekend = blend_hex(pal["paper"], pal["title"], .055)
    for row in range(rows):
        for col in (0, 6):
            p.rect(x0 + col * cw, grid_top + row * ch, cw, ch, fill=weekend)
    for col in range(1, 7):
        p.line(x0 + col * cw, grid_top, x0 + col * cw, grid_bottom, pal["grid_line"], .9)
    for row in range(rows + 1):
        p.line(x0, grid_top + row * ch, x1, grid_top + row * ch, pal["grid_line"], .9)
    _date_text(c, cells, hol, x0, grid_top, width, grid_bottom - grid_top, rows)
    p.grid_box = (x0, grid_top, x1, grid_bottom)
    return p


def _grid_soft_tech(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 10
    width = x1 - x0
    tint = blend_hex(pal["paper"], pal["accent"], .12)
    tint2 = blend_hex(pal["paper"], pal["title"], .07)
    p.round_rect(x0, top, 1040, 270, 38, fill=tint)
    p.round_rect(x0 + 25, top + 28, 18, 214, 9, fill=pal["accent"])
    p.text(x0 + 82, top + 137, c["name"], c["title"], 99, pal["title"], tracking=2, role="month title")
    p.text(x0 + 86, top + 202, f"{c['year']}  ·  {c['month']['subtitle'].upper()}",
           c["body_b"], 28, pal["accent"], tracking=3, role="subtitle")
    p.round_rect(x0 + 1080, top, width - 1080, 270, 38, fill=tint2)
    _draw_quote(c, x0 + 1130, top + 86, width - 1200)

    grid_top, grid_bottom = top + 430, L.grid_bottom - 205
    _weekdays(c, x0, width, grid_top - 38)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = width / 7, (grid_bottom - grid_top) / rows
    for idx in range(rows * 7):
        row, col = divmod(idx, 7)
        fill = tint if col in (0, 6) else pal["paper"]
        p.round_rect(x0 + col * cw + 6, grid_top + row * ch + 6,
                     cw - 12, ch - 12, 12, fill=fill, stroke=pal["grid_line"], stroke_w=1)
        p.round_rect(x0 + col * cw + 22, grid_top + row * ch + 20, 52, 8, 4, fill=pal["accent"])
    _date_text(c, cells, hol, x0, grid_top, width, grid_bottom - grid_top, rows, number_anchor="end", inset=24)

    strip_y = grid_bottom + 28
    p.round_rect(x0, strip_y, width * .62, 145, 26, fill=tint2)
    p.round_rect(x0 + width * .64, strip_y, width * .36, 145, 26, fill=tint)
    p.text(x0 + 34, strip_y + 58, c["panel"], c["body_b"], 26, pal["accent"], tracking=4, role="panel title")
    p.line(x0 + 230, strip_y + 54, x0 + width * .59, strip_y + 54, pal["grid_line"], 1)
    p.line(x0 + 230, strip_y + 102, x0 + width * .59, strip_y + 102, pal["grid_line"], 1)
    p.text(x0 + width * .67, strip_y + 84, "PLAN  ·  NOTE  ·  REMEMBER",
           c["body_b"], 25, pal["title"], tracking=3, role="panel text")
    p.grid_box = (x0, grid_top, x1, grid_bottom)
    return p


def _grid_monochrome(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 10
    side_w, gap = 510, 64
    grid_x, grid_w = x0 + side_w + gap, x1 - (x0 + side_w + gap)
    p.rect(x0, top, 18, L.grid_bottom - top, fill=pal["title"])
    p.text(x0 + 62, top + 100, f"{month_no:02d}", c["title"], 78, pal["accent"], role="month index")
    name_size = 86 if len(c["name"]) <= 5 else 66
    p.text(x0 + 62, top + 225, c["name"], c["title"], name_size, pal["title"], tracking=2, role="month title")
    p.text(x0 + 66, top + 285, str(c["year"]), c["body_b"], 27, pal["text"], tracking=5, role="subtitle")
    p.line(x0 + 62, top + 335, x0 + side_w - 20, top + 335, pal["title"], 2)
    _draw_quote(c, x0 + 62, top + 405, side_w - 105)

    grid_top, grid_bottom = top + 170, L.grid_bottom
    _weekdays(c, grid_x, grid_w, grid_top - 42, color_weekend=False)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = grid_w / 7, (grid_bottom - grid_top) / rows
    for col in range(1, 7):
        p.line(grid_x + col * cw, grid_top, grid_x + col * cw, grid_bottom, pal["grid_line"], .8)
    for row in range(rows + 1):
        line_w = 3 if row in (0, rows) else 1
        p.line(grid_x, grid_top + row * ch, x1, grid_top + row * ch, pal["title"] if line_w == 3 else pal["grid_line"], line_w)
    _date_text(c, cells, hol, grid_x, grid_top, grid_w, grid_bottom - grid_top, rows, number_anchor="middle")
    p.grid_box = (grid_x, grid_top, x1, grid_bottom)
    return p


def _grid_capsules(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 10
    width = x1 - x0
    tint = blend_hex(pal["paper"], pal["accent"], .14)
    tint2 = blend_hex(pal["paper"], pal["title"], .065)
    p.round_rect(x0, top, width, 285, 48, fill=tint)
    p.round_rect(x0 + 28, top + 30, 900, 225, 38, fill=pal["paper"])
    p.text(x0 + 74, top + 140, c["name"], c["title"], 99, pal["title"], tracking=2, role="month title")
    p.text(x0 + 78, top + 204, f"{c['year']}  ·  {c['month']['subtitle'].upper()}",
           c["body_b"], 28, pal["accent"], tracking=3, role="subtitle")
    _draw_quote(c, x0 + 1010, top + 88, width - 1120)

    grid_top, grid_bottom = top + 480, L.grid_bottom
    _weekdays(c, x0, width, grid_top - 45)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = width / 7, (grid_bottom - grid_top) / rows
    for row in range(rows):
        y = grid_top + row * ch + 10
        fill = tint if row % 2 == 0 else tint2
        p.round_rect(x0, y, width, ch - 20, (ch - 20) / 2, fill=fill)
        for col in range(1, 7):
            p.line(x0 + col * cw, y + 28, x0 + col * cw, y + ch - 48,
                   blend_hex(fill, pal["title"], .20), 1)
    _date_text(c, cells, hol, x0, grid_top, width, grid_bottom - grid_top, rows,
               number_anchor="middle", inset=28, holiday_bottom=62, holiday_edge_inset=72)
    p.grid_box = (x0, grid_top, x1, grid_bottom)
    return p


def _grid_playful(fmt, concept, month_no, label, verse_text):
    c = _setup(fmt, concept, month_no, label, verse_text)
    p, L, pal = c["page"], c["layout"], c["pal"]
    x0, x1, top = L.x0, L.x1, L.top + 10
    width = x1 - x0
    panel_w, gap = 660, 40
    grid_w = width - panel_w - gap
    grid_x1, panel_x = x0 + grid_w, x0 + grid_w + gap
    tint = blend_hex(pal["paper"], pal["accent"], .14)
    p.rect(x0, top, width * .66, 290, fill=pal["title"])
    p.rect(x0 + width * .66, top, width * .34, 290, fill=pal["accent"])
    p.text(x0 + 48, top + 150, c["name"], c["title"], 112, pal["paper"], tracking=2, role="month title")
    p.text(x0 + 52, top + 218, f"{c['year']}  ·  {c['month']['subtitle'].upper()}",
           c["body_b"], 28, blend_hex(pal["paper"], pal["accent"], .18), tracking=4, role="subtitle")
    p.text(x1 - 42, top + 180, f"{month_no:02d}", c["title"], 102, pal["paper"], "end", role="month index")

    grid_top, grid_bottom = top + 475, L.grid_bottom
    _weekdays(c, x0, grid_w, grid_top - 42)
    rows, cells, hol = _calendar(c, month_no)
    cw, ch = grid_w / 7, (grid_bottom - grid_top) / rows
    for idx in range(rows * 7):
        row, col = divmod(idx, 7)
        fill = tint if col in (0, 6) else (blend_hex(pal["paper"], pal["title"], .04) if row % 2 else pal["paper"])
        p.rect(x0 + col * cw + 4, grid_top + row * ch + 4,
               cw - 8, ch - 8, fill=fill, stroke=pal["grid_line"], stroke_w=1)
    _date_text(c, cells, hol, x0, grid_top, grid_w, grid_bottom - grid_top, rows)

    p.rect(panel_x, grid_top, panel_w, 420, fill=pal["accent"])
    p.text(panel_x + 34, grid_top + 66, "THIS MONTH", c["body_b"], 27, pal["paper"], tracking=4, role="panel title")
    _draw_quote(c, panel_x + 34, grid_top + 130, panel_w - 68, color=pal["paper"])
    p.rect(panel_x, grid_top + 450, panel_w, grid_bottom - (grid_top + 450), fill=pal["title"])
    p.text(panel_x + 34, grid_top + 515, c["panel"], c["body_b"], 27, pal["paper"], tracking=4, role="panel title")
    y = grid_top + 585
    while y < grid_bottom - 150:
        p.line(panel_x + 34, y, x1 - 34, y, blend_hex(pal["title"], pal["paper"], .32), 1)
        y += 68
    p.grid_box = (x0, grid_top, grid_x1, grid_bottom)
    return p


# ---------------------------------------------------------------------------
# Helpers ngày và ngày lễ
# ---------------------------------------------------------------------------
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
