"""Bìa trước và bìa sau cho Printify Wall Calendar 11x8.5.

- Bìa trước: ảnh neo (bìa) tràn kín trang; dải nền giấy mờ dần ở phía trên để tên lịch đọc rõ
  trên tranh; năm, tên lịch, phụ đề canh giữa, dưới vùng lò xo.
- Bìa sau: 12 ảnh thu nhỏ (4x3) kèm tên tháng + subtitle; chừa lỗ treo và ô mã vạch của nhà in.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from ..core import dates
from . import fonts
from .draw import Page, text_width


def _fade_overlay(path: Path, size: tuple[int, int], paper_hex: str, height: int, strength: float = 0.9) -> None:
    """PNG màu giấy, đậm ở mép trên rồi trong suốt dần xuống dưới."""
    W, H = size
    rgb = [int(paper_hex[i:i + 2], 16) for i in (1, 3, 5)]
    y = np.linspace(0, 1, height, dtype=np.float32)
    alpha = (strength * np.clip(1 - y, 0, 1) ** 1.6 * 255).astype(np.uint8)
    arr = np.zeros((height, W, 4), np.uint8)
    arr[..., :3] = rgb
    arr[..., 3] = alpha[:, None]
    Image.fromarray(arr, "RGBA").save(path)


def _fit_size(text: str, font: str, size: float, tracking: float, max_w: float, min_size: float) -> float:
    while size > min_size and text_width(text, font, size, tracking) > max_w:
        size -= 4
    return size


def front_cover(fmt: dict, concept: dict, art: Path | None, work: Path, label: str = "front cover") -> Page:
    W, H = fmt["size_px"]
    st, pal = concept["style"], concept["style"]["palette"]
    cov = concept["cover"]
    page = Page(W, H, "front_cover", label)
    page.rect(0, 0, W, H, fill=pal["paper"])
    if art:
        page.image(art, 0, 0, W, H, role="art")
    overlay = work / "front_fade.png"
    _fade_overlay(overlay, (W, H), pal["paper"], 1150)
    page.image(overlay, 0, 0, W, 1150, role="overlay")

    f_title = fonts.font(st["fonts"]["title"], "semibold")
    f_body_b = fonts.font(st["fonts"]["body"], "semibold")
    f_body_i = fonts.font(st["fonts"]["body"], "italic")
    cx = W / 2
    max_w = W - 2 * (fmt["bleed_px"] + fmt["text_margin_px"]) - 200
    title = cov["title"]
    size = _fit_size(title, f_title, 210, 4, max_w, 120)
    page.text(cx, 420, str(concept["year"]), f_body_b, 64, pal["accent"], "middle", tracking=30, role="year")
    page.text(cx, 420 + 60 + size * 0.8, title, f_title, size, pal["title"], "middle", tracking=4, role="cover title")
    if cov.get("subtitle"):
        page.text(cx, 420 + 60 + size * 0.8 + 110, cov["subtitle"], f_body_i, 60, pal["text"], "middle",
                  role="cover subtitle")
    return page


def back_cover(fmt: dict, concept: dict, month_arts: dict[int, Path], work: Path, label: str = "back cover") -> Page:
    W, H = fmt["size_px"]
    st, pal = concept["style"], concept["style"]["palette"]
    page = Page(W, H, "back_cover", label)
    page.rect(0, 0, W, H, fill=pal["paper"])
    f_title = fonts.font(st["fonts"]["title"], "semibold")
    f_body = fonts.font(st["fonts"]["body"], "regular")
    f_body_b = fonts.font(st["fonts"]["body"], "semibold")
    f_body_i = fonts.font(st["fonts"]["body"], "italic")

    keep = fmt["pages"]["back_cover"]["keep_out"]
    hole = next(k["circle"] for k in keep if "circle" in k)
    barcode = next(k["rect"] for k in keep if "rect" in k and k["rect"][1] > 0)
    top = max(k["rect"][3] for k in keep if "rect" in k and k["rect"][1] == 0) + 60

    cx = W / 2
    page.text(cx, top + 120, concept["cover"]["title"], f_title, 120, pal["title"], "middle", tracking=4, role="title")
    page.text(cx, top + 190, f"{concept['year']}  ·  TWELVE MONTHS", f_body_b, 34, pal["accent"], "middle",
              tracking=10, role="year")

    # lưới 4x3 ảnh thu nhỏ phải kết thúc trên ô mã vạch và lỗ treo
    grid_top, grid_bottom = top + 270, min(barcode[1], hole[1] - hole[2]) - 170
    cols, rows, gap_x, gap_y, label_h = 4, 3, 80, 40, 100
    cell_h = (grid_bottom - grid_top - gap_y * (rows - 1)) / rows
    thumb_h = cell_h - label_h
    thumb_w = thumb_h * W / H
    total_w = cols * thumb_w + (cols - 1) * gap_x
    x0 = cx - total_w / 2
    bleed = fmt["bleed_px"]
    for i in range(12):
        r, c = divmod(i, cols)
        x = x0 + c * (thumb_w + gap_x)
        y = grid_top + r * (cell_h + gap_y)
        src = month_arts.get(i + 1)
        if src:
            thumb = work / f"thumb_{i + 1:02d}.jpg"
            with Image.open(src) as im:
                im = im.convert("RGB").crop((bleed, bleed, im.width - bleed, im.height - bleed))
                im.resize((round(thumb_w), round(thumb_h)), Image.LANCZOS).save(thumb, quality=90)
            page.image(thumb, x, y, thumb_w, thumb_h, role="thumb")
        else:
            page.rect(x, y, thumb_w, thumb_h, fill=pal["grid_line"])
        page.rect(x, y, thumb_w, thumb_h, stroke=pal["grid_line"], stroke_w=2)
        month = concept["months"][i]
        page.text(x + thumb_w / 2, y + thumb_h + 44, dates.MONTH_NAMES[i].upper(), f_body_b, 28, pal["title"],
                  "middle", tracking=8, role="thumb month")
        page.text(x + thumb_w / 2, y + thumb_h + 84, month["subtitle"], f_body_i, 27, pal["text"], "middle",
                  role="thumb subtitle")

    line = (concept.get("back_cover") or {}).get("line", "")
    if line:
        size = _fit_size(line, f_body, 34, 0, hole[0] - hole[2] - 80 - (bleed + fmt["text_margin_px"]), 26)
        page.text(bleed + fmt["text_margin_px"], hole[1] - 20, line, f_body, size, pal["text"], role="back line")
    return page
