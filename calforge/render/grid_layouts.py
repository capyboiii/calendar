"""Các bố cục trang lịch (grid) trên nền AI dùng chung - để 12 tháng của các cuốn không hao hao nhau.

Mọi bố cục: nền AI phủ toàn trang, chữ + ngày do code dựng (vector, chính xác), tuần bắt đầu Chủ nhật (lịch Mỹ),
có grid_box / calendar / cell_texts để preflight kiểm tra ngày độc lập.

    classic      tên tháng trên, lưới ô kẻ đủ (bố cục cũ, _grid_art_matched trong pages.py)
    side_column  cột trái: tên tháng + năm + câu trích xếp dọc; lưới bên phải chỉ kẻ ngang
    open_lines   tên tháng giữa, không kẻ ô, chỉ vạch mảnh giữa các tuần; số lớn căn giữa; ngày tháng kề in mờ
    big_numeral  số tháng rất lớn in mờ sau tên tháng; ngày trong ô bo góc tô nhạt, không kẻ đường
    notes_column lưới ô kẻ 72% bên trái + cột NOTES có dòng kẻ bên phải
    week_bands   mỗi tuần một dải bo tròn tô nhạt, ngày xếp trong dải
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PIL import Image, ImageStat

from ..core import dates
from .draw import Page, blend_hex, text_width, wrap

LAYOUTS = ["classic", "side_column", "open_lines", "big_numeral", "notes_column", "week_bands"]
ROTATION = ["side_column", "open_lines", "big_numeral", "notes_column", "week_bands"]   # cuốn mới chia đều 5 bố cục
# cặp không hợp: nền màu nước loang mảng lớn qua vùng ô -> bố cục nhiều ô tô/kẻ kín nhìn rối
AVOID = {"watercolor": {"big_numeral", "notes_column"}}


def next_grid_layout(projects_root, material: str | None = None) -> str:
    """Chia đều 5 bố cục mới: bố cục ít dùng nhất trên cả danh mục; hoà thì ít dùng nhất VỚI CÙNG chất liệu nền
    (để bố cục không khoá cặp với chất liệu), rồi theo thứ tự ROTATION; bỏ các cặp trong AVOID."""
    import json
    from .. import layout as lay
    same = {k: 0 for k in ROTATION}
    total = {k: 0 for k in ROTATION}
    for b in lay.books(projects_root):
        try:
            st = json.loads(lay.concept_file(b).read_text(encoding="utf-8")).get("style") or {}
        except (OSError, ValueError):
            continue
        key = st.get("grid_layout")
        if key in total:
            total[key] += 1
            if st.get("grid_material") == material:
                same[key] += 1
    allowed = [k for k in ROTATION if k not in AVOID.get(material or "", set())]
    return min(allowed, key=lambda k: (total[k], same[k], ROTATION.index(k)))
WEEK = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]


def _paper(pal: dict, background_art: Path | None) -> str:
    paper = blend_hex(pal["paper"], "#FFFFFF", .58)
    if background_art is not None and Path(background_art).is_file():
        with Image.open(background_art) as bg:
            iw, ih = bg.size
            rgb = ImageStat.Stat(bg.convert("RGB").crop((int(iw * .3), int(ih * .4), int(iw * .7), int(ih * .6)))).median
        if min(rgb) >= 170 and max(rgb) - min(rgb) <= 65:
            paper = blend_hex("#" + "".join(f"{int(v):02X}" for v in rgb), "#FFFFFF", .40)
    return paper


def _weeks(year: int, month: int) -> list[list[dt.date]]:
    """Các tuần (Chủ nhật đầu tuần) phủ trọn tháng; số tuần thật 4-6."""
    first = dt.date(year, month, 1)
    last = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    d = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    weeks = []
    while d <= last:
        weeks.append([d + dt.timedelta(days=i) for i in range(7)])
        d += dt.timedelta(days=7)
    return weeks


def grid_layout_page(fmt: dict, c: dict, layout: str, background_art: Path | None) -> Page:
    """c: ngữ cảnh từ pages._setup (page, layout, pal, name, year, body, ref, fonts...)."""
    p, L, pal = c["page"], c["layout"], c["pal"]
    W, H = fmt["size_px"]
    paper = _paper(pal, background_art)
    if background_art is not None:
        p.image(background_art, 0, 0, W, H, role="grid background")
    ctx = dict(c, paper=paper, ink=pal["title"], text=pal["text"], accent=pal["accent"],
               hair=blend_hex(paper, pal["title"], .42), W=W, H=H,
               weeks=_weeks(c["year"], c["month_no"]),
               holidays={d: n for d, n in dates.holidays_for(c["year"], c["market"]).items()
                         if d.month == c["month_no"]})
    {"side_column": _side_column, "open_lines": _open_lines, "big_numeral": _big_numeral,
     "notes_column": _notes_column, "week_bands": _week_bands}[layout](ctx)
    p.calendar = {"year": c["year"], "month": c["month_no"], "week_start": dates.SUN, "rows": len(ctx["weeks"])}
    return p


# ---------------------------------------------------------------------------- phần dùng chung
def _quote(ctx, x, y, width, align="start", size=32, max_lines=3) -> float:
    """Câu trích (nghiêng) + mã câu; trả về đáy khối chữ."""
    if not ctx["body"]:
        return y
    p = ctx["page"]
    value = f"“{ctx['body']}”" if ctx["ref"] else ctx["body"]
    lines = wrap(value, ctx["body_i"], size, width)
    while len(lines) > max_lines and size > 25:
        size -= 1
        lines = wrap(value, ctx["body_i"], size, width)
    for i, line in enumerate(lines[:max_lines]):
        p.text(x, y + i * size * 1.34, line, ctx["body_i"], size, ctx["text"], align, role="verse")
    bottom = y + min(len(lines), max_lines) * size * 1.34
    if ctx["ref"]:
        bottom += 40
        p.text(x, bottom, f"{ctx['ref'].upper()}   ·   KJV", ctx["body_b"], 25, ctx["accent"], align,
               tracking=6, role="verse ref")
    return bottom


def _header(ctx, gx0, cw, base, size=30, color=None):
    for col, wd in enumerate(WEEK):
        wc = ctx["accent"] if col in (0, 6) else (color or ctx["ink"])
        ctx["page"].text(gx0 + cw * (col + .5), base, wd, ctx["body_b"], size, wc, "middle", tracking=4,
                         role="weekday")


def _days(ctx, gx0, gy0, cw, ch, *, anchor="start", size=56, inset=26, other=False, top_pad=None):
    """Số ngày + ngày lễ trong từng ô; other=True: in mờ ngày của tháng trước/sau."""
    p, month = ctx["page"], ctx["month_no"]
    faded = blend_hex(ctx["paper"], ctx["text"], .28)
    for row, week in enumerate(ctx["weeks"]):
        for col, d in enumerate(week):
            left, top = gx0 + col * cw, gy0 + row * ch
            x = left + cw / 2 if anchor == "middle" else left + inset
            y = top + (top_pad if top_pad is not None else size + inset * .6)
            if d.month != month:
                if other:
                    p.text(x, y, str(d.day), ctx["num"], size, faded, anchor, role="date other")
                continue
            color = ctx["accent"] if col in (0, 6) else ctx["text"]
            t = p.text(x, y, str(d.day), ctx["num"], size, color, anchor, role="date")
            p.cell_texts.append((t, row, col))
            names = ctx["holidays"].get(d)
            if names:
                hsize = 25
                lines = wrap(" · ".join(names).upper(), ctx["body_font"], hsize, cw - 2 * inset)
                for i, line in enumerate(lines[:2]):
                    hy = top + ch - 22 - (min(len(lines), 2) - 1 - i) * 31
                    h = p.text(x if anchor == "middle" else left + inset, hy, line, ctx["body_font"], hsize,
                               ctx["accent"], anchor, role="holiday")
                    p.cell_texts.append((h, row, col))


def _fit(ctx, text, font, size, max_w, tracking=0):
    while size > 40 and text_width(text, font, size, tracking) > max_w:
        size -= 4
    return size


# ---------------------------------------------------------------------------- các bố cục
def _side_column(ctx):
    p, L, W = ctx["page"], ctx["layout"], ctx["W"]
    col_x0, col_x1 = L.x0 + 90, L.x0 + W * .27
    gx0, gx1 = L.x0 + W * .31, L.x1 - 70
    top, bottom = L.top + 90, L.grid_bottom - 70
    size = _fit(ctx, ctx["name"], ctx["title"], 150, col_x1 - col_x0, 6)
    p.text(col_x0, top + size, ctx["name"], ctx["title"], size, ctx["ink"], tracking=6, role="month title")
    yb = top + size + 70
    p.text(col_x0, yb, str(ctx["year"]), ctx["body_b"], 40, ctx["accent"], tracking=12, role="year")
    p.line(col_x0, yb + 36, col_x0 + 260, yb + 36, blend_hex(ctx["paper"], ctx["accent"], .6), 2)
    _quote(ctx, col_x0, yb + 120, col_x1 - col_x0, size=36, max_lines=10)
    p.line(col_x1 + (gx0 - col_x1) / 2, top, col_x1 + (gx0 - col_x1) / 2, bottom,
           blend_hex(ctx["paper"], ctx["accent"], .45), 2)
    cw = (gx1 - gx0) / 7
    head = top + 60
    _header(ctx, gx0, cw, head)
    gy0 = head + 40
    ch = (bottom - gy0) / len(ctx["weeks"])
    strong = blend_hex(ctx["paper"], ctx["ink"], .62)
    for r in range(len(ctx["weeks"]) + 1):
        p.line(gx0, gy0 + r * ch, gx1, gy0 + r * ch, strong if r in (0, len(ctx["weeks"])) else ctx["hair"],
               3.6 if r in (0, len(ctx["weeks"])) else 2.4)
    _days(ctx, gx0, gy0, cw, ch, size=54)
    p.grid_box = (gx0, gy0, gx1, gy0 + ch * len(ctx["weeks"]))


def _open_lines(ctx):
    p, L, W = ctx["page"], ctx["layout"], ctx["W"]
    mid = W / 2
    top = L.top + 60
    size = 170 if len(ctx["name"]) <= 7 else 140
    p.text(mid, top + size, ctx["name"], ctx["title"], size, ctx["ink"], "middle", tracking=24, role="month title")
    yb = top + size + 72
    p.text(mid, yb, str(ctx["year"]), ctx["body_b"], 36, ctx["accent"], "middle", tracking=16, role="year")
    qb = _quote(ctx, mid, yb + 80, W * .56, "middle", size=30, max_lines=2)
    gx0, gx1 = L.x0 + 170, L.x1 - 170
    cw = (gx1 - gx0) / 7
    head = max(qb + 100, yb + 150)
    _header(ctx, gx0, cw, head, size=29)
    p.line(gx0, head + 26, gx1, head + 26, blend_hex(ctx["paper"], ctx["ink"], .6), 3)
    gy0 = head + 40
    bottom = L.grid_bottom - 60
    ch = (bottom - gy0) / len(ctx["weeks"])
    for r in range(1, len(ctx["weeks"])):
        p.line(gx0 + 30, gy0 + r * ch, gx1 - 30, gy0 + r * ch, ctx["hair"], 2.2)
    _days(ctx, gx0, gy0, cw, ch, anchor="middle", size=62, other=True, top_pad=ch * .5 + 22)
    p.grid_box = (gx0, gy0, gx1, gy0 + ch * len(ctx["weeks"]))


def _big_numeral(ctx):
    p, L, W = ctx["page"], ctx["layout"], ctx["W"]
    x0 = L.x0 + 110
    top = L.top + 20
    num = f"{ctx['month_no']:02d}"
    nsize = 620
    p.text(x0 - 16, top + 500, num, ctx["title"], nsize, blend_hex(ctx["paper"], ctx["accent"], .42),
           tracking=-10, role="month numeral")
    tx = x0 + text_width(num, ctx["title"], nsize, -10) + 70
    size = _fit(ctx, ctx["name"], ctx["title"], 150, L.x1 - 110 - tx, 8)
    p.text(tx, top + 230, ctx["name"], ctx["title"], size, ctx["ink"], tracking=8, role="month title")
    p.text(tx + 4, top + 300, str(ctx["year"]), ctx["body_b"], 36, ctx["accent"], tracking=14, role="year")
    qb = _quote(ctx, tx + 4, top + 375, L.x1 - 110 - tx, size=29, max_lines=3)
    gx0, gx1 = L.x0 + 110, L.x1 - 110
    cw = (gx1 - gx0) / 7
    head = max(top + 600, qb + 90)
    _header(ctx, gx0, cw, head, size=28)
    gy0 = head + 34
    bottom = L.grid_bottom - 60
    ch = (bottom - gy0) / len(ctx["weeks"])
    fill = blend_hex(ctx["paper"], ctx["ink"], .10)
    gap = 12
    for r, week in enumerate(ctx["weeks"]):
        for col, d in enumerate(week):
            if d.month == ctx["month_no"]:
                p.round_rect(gx0 + col * cw + gap / 2, gy0 + r * ch + gap / 2, cw - gap, ch - gap, 22, fill=fill)
    _days(ctx, gx0, gy0, cw, ch, size=50, inset=30)
    p.grid_box = (gx0, gy0, gx1, gy0 + ch * len(ctx["weeks"]))


def _notes_column(ctx):
    p, L, W = ctx["page"], ctx["layout"], ctx["W"]
    x0, x1 = L.x0 + 110, L.x1 - 110
    top = L.top + 50
    p.text(x0, top + 160, ctx["name"], ctx["title"], 160 if len(ctx["name"]) <= 7 else 130, ctx["ink"], tracking=8,
           role="month title")
    p.text(x1, top + 160, str(ctx["year"]), ctx["title"], 96, blend_hex(ctx["paper"], ctx["accent"], .75), "end",
           role="year")
    qb = _quote(ctx, x0, top + 245, W * .7, size=29, max_lines=2)
    gx0, gx1 = x0, x0 + (x1 - x0) * .73
    cw = (gx1 - gx0) / 7
    head = max(qb + 90, top + 330)
    _header(ctx, gx0, cw, head, size=28)
    gy0 = head + 32
    bottom = L.grid_bottom - 60
    rows = len(ctx["weeks"])
    ch = (bottom - gy0) / rows
    strong = blend_hex(ctx["paper"], ctx["ink"], .62)
    for col in range(8):
        p.line(gx0 + col * cw, gy0, gx0 + col * cw, bottom, strong if col in (0, 7) else ctx["hair"], 2.4)
    for r in range(rows + 1):
        p.line(gx0, gy0 + r * ch, gx1, gy0 + r * ch, strong if r in (0, rows) else ctx["hair"], 2.4)
    _days(ctx, gx0, gy0, cw, ch, size=48, inset=22)
    nx0 = gx1 + 70
    p.text(nx0, head, ctx["panel"], ctx["body_b"], 30, ctx["accent"], tracking=8, role="panel title")
    y = gy0 + 70
    while y < bottom:
        p.line(nx0, y, x1, y, ctx["hair"], 2.2)
        y += 78
    p.grid_box = (gx0, gy0, gx1, bottom)


def _week_bands(ctx):
    p, L, W = ctx["page"], ctx["layout"], ctx["W"]
    mid = W / 2
    top = L.top + 50
    p.text(L.x0 + 120, top + 150, ctx["name"], ctx["title"], 150 if len(ctx["name"]) <= 7 else 124, ctx["ink"],
           tracking=8, role="month title")
    p.text(L.x0 + 124, top + 215, str(ctx["year"]), ctx["body_b"], 34, ctx["accent"], tracking=14, role="year")
    _quote(ctx, L.x1 - 120, top + 105, W * .44, "end", size=29, max_lines=4)
    gx0, gx1 = L.x0 + 120, L.x1 - 120
    cw = (gx1 - gx0) / 7
    head = top + 340
    _header(ctx, gx0, cw, head, size=28)
    gy0 = head + 34
    bottom = L.grid_bottom - 60
    ch = (bottom - gy0) / len(ctx["weeks"])
    fill = blend_hex(ctx["paper"], ctx["accent"], .14)
    for r in range(len(ctx["weeks"])):
        p.round_rect(gx0, gy0 + r * ch + 8, gx1 - gx0, ch - 16, (ch - 16) / 2.6, fill=fill)
    _days(ctx, gx0, gy0, cw, ch, anchor="middle", size=54, top_pad=ch * .5 + 4, inset=34)
    del mid
    p.grid_box = (gx0, gy0, gx1, gy0 + ch * len(ctx["weeks"]))
