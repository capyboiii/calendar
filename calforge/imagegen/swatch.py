"""Dải màu + texture rút từ ảnh neo, dùng làm ảnh tham chiếu cho cover và 12 tháng.

Đính nguyên ảnh neo thì model chép luôn bố cục của nó (cùng góc máy, cùng khung cảnh) dù prompt
có dặn đừng. Ảnh swatch chỉ giữ thứ cần đồng bộ giữa các tháng: màu theo đúng tỉ lệ (dải trên)
và chất liệu/nét vẽ (các mảnh cắt nhỏ ở dưới), không còn bố cục nào để bắt chước.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SIZE = (1536, 1024)
BANDS_H = 620       # phần dải màu phía trên
PATCHES = 4         # số mảnh texture phía dưới


def make_swatch(anchor: Path, out: Path) -> Path:
    with Image.open(anchor) as im:
        src = im.convert("RGB")
    W, H = SIZE
    sheet = Image.new("RGB", SIZE, (255, 255, 255))

    # 1) Dải màu: 8 màu chủ đạo, bề ngang mỗi dải tỉ lệ với diện tích màu đó trong ảnh neo.
    small = src.resize((160, 107))
    quant = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
    pal = quant.getpalette()
    counts = sorted(quant.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    x = 0
    for i, (count, idx) in enumerate(counts):
        w = W - x if i == len(counts) - 1 else round(W * count / total)
        sheet.paste(tuple(pal[idx * 3: idx * 3 + 3]), (x, 0, x + w, BANDS_H))
        x += w

    # 2) Mảnh texture: cắt ô rất nhỏ (~4,5% bề ngang) rồi phóng lên, để thấy nét vẽ / hạt ảnh mà không
    #    nhận ra được vật hay cảnh nào. Chọn những ô NHIỀU CHI TIẾT nhất (vị trí cố định hay rơi vào
    #    vùng trời trơn, khi đó swatch không truyền được chất liệu - vd giấy cắt ra thành tranh phẳng).
    gap = 16
    pw = (W - gap * (PATCHES + 1)) // PATCHES
    ph = H - BANDS_H - 2 * gap
    side = max(24, int(src.width * .045))
    side_h = max(24, side * ph // pw)
    for i, (x0, y0) in enumerate(_detail_spots(src, side, side_h, PATCHES)):
        crop = src.crop((x0, y0, x0 + side, y0 + side_h))
        sheet.paste(crop.resize((pw, ph), Image.LANCZOS), (gap + i * (pw + gap), BANDS_H + gap))

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def _detail_spots(src: Image.Image, w: int, h: int, n: int) -> list[tuple[int, int]]:
    """n ô w x h nhiều chi tiết nhất, không chồng lên nhau, bỏ 10% mép ảnh (mép hay dính khung/viền)."""
    gray = np.asarray(src.convert("L"), dtype=np.float32)
    edges = np.abs(np.diff(gray, axis=0))[:, :-1] + np.abs(np.diff(gray, axis=1))[:-1, :]
    H, W = edges.shape
    step_x, step_y = max(1, w // 2), max(1, h // 2)
    cands = []
    for y in range(int(H * .1), int(H * .9) - h, step_y):
        for x in range(int(W * .1), int(W * .9) - w, step_x):
            cands.append((float(edges[y:y + h, x:x + w].mean()), x, y))
    cands.sort(reverse=True)
    picked: list[tuple[int, int]] = []
    for _score, x, y in cands:
        if all(abs(x - px) >= w or abs(y - py) >= h for px, py in picked):
            picked.append((x, y))
            if len(picked) == n:
                break
    while len(picked) < n:  # ảnh quá nhỏ/quá trơn: lấp bằng ô giữa ảnh
        picked.append(((W - w) // 2, (H - h) // 2))
    return picked
