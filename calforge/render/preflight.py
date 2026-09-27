"""Kiểm tra trang trước khi xuất: chạy trên chính danh sách nét vẽ sẽ in."""
from __future__ import annotations

import calendar
import datetime as dt
from collections import Counter

from .draw import PX_TO_PT, Page


def _hits(box, zone) -> bool:
    x0, y0, x1, y1 = box
    if "rect" in zone:
        zx0, zy0, zx1, zy1 = zone["rect"]
        return x0 < zx1 and x1 > zx0 and y0 < zy1 and y1 > zy0
    cx, cy, r = zone["circle"]
    nx, ny = min(max(cx, x0), x1), min(max(cy, y0), y1)
    return (nx - cx) ** 2 + (ny - cy) ** 2 < r ** 2


def check_page(page: Page, fmt: dict) -> list[str]:
    W, H = fmt["size_px"]
    inset = fmt["bleed_px"] + fmt["text_margin_px"] - 1
    keep = fmt["pages"][page.kind]["keep_out"]
    issues = []
    for t in page.texts():
        box = t.bbox()
        tag = f"[{page.label}] {t.role or 'text'} “{t.text[:30]}”"
        if box[0] < inset or box[2] > W - inset:
            issues.append(f"{tag} ra ngoài lề chữ hai bên")
        for zone in keep:
            if _hits(box, zone):
                issues.append(f"{tag} đè lên {zone['name']}")
        pt = t.size * PX_TO_PT
        if pt < fmt["min_text_pt"] - 0.05:
            issues.append(f"{tag} cỡ {pt:.1f}pt < {fmt['min_text_pt']}pt")
    # chữ đè chữ (vd tên lễ dài chạm số ngày)
    texts = page.texts()
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i].bbox(), texts[j].bbox()
            if a[0] < b[2] - 1 and a[2] > b[0] + 1 and a[1] < b[3] - 1 and a[3] > b[1] + 1:
                issues.append(f"[{page.label}] chữ chồng nhau: “{texts[i].text[:20]}” và “{texts[j].text[:20]}”")
    issues += check_calendar(page)
    return issues


def check_calendar(page: Page) -> list[str]:
    """Verify the rendered numbers and their positions independently of the stored date table."""
    if not page.calendar:
        return []
    meta = page.calendar
    year, month, start, rows = (meta[k] for k in ("year", "month", "week_start", "rows"))
    issues = []
    tag = f"[{page.label}] lịch {month:02d}/{year}"
    ndays = calendar.monthrange(year, month)[1]
    lead = (dt.date(year, month, 1).weekday() - start) % 7
    if rows != (lead + ndays + 6) // 7:
        issues.append(f"{tag}: sai số hàng")
    date_texts = [t for t in page.texts() if t.role == "date"]
    if Counter(t.text for t in date_texts) != Counter(str(d) for d in range(1, ndays + 1)):
        issues.append(f"{tag}: ngày thiếu, trùng hoặc không hợp lệ")
    expected_weekdays = [calendar.day_abbr[(start + col) % 7].upper() for col in range(7)]
    weekdays = sorted((t for t in page.texts() if t.role == "weekday"), key=lambda t: t.x)
    if [t.text for t in weekdays] != expected_weekdays:
        issues.append(f"{tag}: sai thứ hoặc thứ tự cột")
    if not page.grid_box:
        return issues + [f"{tag}: thiếu khung lịch"]
    x0, y0, x1, y1 = page.grid_box
    cw, ch = (x1 - x0) / 7, (y1 - y0) / rows
    if ch <= 0:
        return issues + [f"{tag}: không còn diện tích ô lịch"]

    def inside(t, row, col):
        a, b, c, d = t.bbox()
        return (a >= x0 + col * cw and c <= x0 + (col + 1) * cw
                and b >= y0 + row * ch and d <= y0 + (row + 1) * ch)

    for t in date_texts:
        if not t.text.isdigit() or not 1 <= int(t.text) <= ndays:
            continue
        row, col = divmod(lead + int(t.text) - 1, 7)
        if not inside(t, row, col):
            issues.append(f"{tag}: ngày {t.text} sai vị trí ô/thứ")
    for t, row, col in page.cell_texts:
        if not inside(t, row, col):
            issues.append(f"{tag}: chữ '{t.text}' tràn khỏi ô")
    return issues
