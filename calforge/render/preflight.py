"""Kiểm tra trang trước khi xuất: chạy trên chính danh sách nét vẽ sẽ in."""
from __future__ import annotations

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
    # họa tiết: không đè chữ, không lấn vào ô lưới, không chạm lò xo / lỗ treo, không tràn mép cắt
    texts = page.texts()
    grid = getattr(page, "grid_box", None)
    trim = (fmt["bleed_px"], fmt["bleed_px"], W - fmt["bleed_px"], H - fmt["bleed_px"])
    for slot, box in page.ornaments():
        tag = f"[{page.label}] họa tiết {slot}"
        for t in texts:
            tb = t.bbox()
            if box[0] < tb[2] and box[2] > tb[0] and box[1] < tb[3] and box[3] > tb[1]:
                issues.append(f"{tag} đè lên chữ “{t.text[:20]}”")
        if grid and box[0] < grid[2] and box[2] > grid[0] and box[1] < grid[3] and box[3] > grid[1]:
            issues.append(f"{tag} lấn vào ô lưới")
        for zone in keep:
            if _hits(box, zone):
                issues.append(f"{tag} đè lên {zone['name']}")
        if box[0] < trim[0] or box[1] < trim[1] or box[2] > trim[2] or box[3] > trim[3]:
            issues.append(f"{tag} tràn ra ngoài mép cắt")
    # chữ đè chữ (vd tên lễ dài chạm số ngày)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i].bbox(), texts[j].bbox()
            if a[0] < b[2] - 1 and a[2] > b[0] + 1 and a[1] < b[3] - 1 and a[3] > b[1] + 1:
                issues.append(f"[{page.label}] chữ chồng nhau: “{texts[i].text[:20]}” và “{texts[j].text[:20]}”")
    return issues
