"""Lớp vẽ chung: gom "nét vẽ" (ops) theo toạ độ px của file upload (gốc góc trên-trái),
rồi xuất PDF vector (ReportLab) -> PNG đúng pixel (PyMuPDF).

Giữ danh sách ops thay vì vẽ thẳng để preflight kiểm tra được chính những gì sẽ in
(vị trí chữ, cỡ chữ) trước khi xuất.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from reportlab import rl_config
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

# Nhúng ảnh dạng nhị phân thay vì mã hoá ASCII85: máy không có bản C (_rl_accel) nên ASCII85 chạy bằng
# Python thuần, tốn ~2 phút mỗi cuốn. PDF ra y hệt về nội dung, chỉ khác cách đóng gói (và nhỏ hơn ~20%).
rl_config.useA85 = 0

PX_TO_PT = 72 / 300


@dataclass
class Text:
    x: float
    y: float            # baseline
    text: str
    font: str           # tên font đã đăng ký
    size: float         # px
    color: str
    anchor: str = "start"   # start | middle | end
    tracking: float = 0.0   # px giữa các ký tự
    role: str = ""

    @property
    def width(self) -> float:
        return text_width(self.text, self.font, self.size, self.tracking)

    def bbox(self) -> tuple[float, float, float, float]:
        """Khung mực thật: chiều ngang theo độ rộng chữ, chiều dọc theo nét của đúng các ký tự
        có trong chuỗi (chữ in hoa không có phần thò xuống thì không tính descent của font)."""
        w = self.width
        left = {"start": self.x, "middle": self.x - w / 2, "end": self.x - w}[self.anchor]
        top, bottom = ink_extent(self.font, self.text)
        return left, self.y - top * self.size, left + w, self.y - bottom * self.size


@dataclass
class Page:
    width: int
    height: int
    kind: str                     # month | grid | front_cover | back_cover
    label: str = ""
    ops: list = field(default_factory=list)
    grid_box: tuple | None = None   # khung lưới ngày, để preflight cấm họa tiết lấn vào
    calendar: dict | None = None   # year/month/week_start/rows cho kiểm tra ngày độc lập
    cell_texts: list = field(default_factory=list)  # (Text, row, col): kiểm tra chữ trong đúng ô

    def rect(self, x, y, w, h, fill=None, stroke=None, stroke_w=0.0):
        self.ops.append(("rect", x, y, w, h, fill, stroke, stroke_w))

    def round_rect(self, x, y, w, h, radius, fill=None, stroke=None, stroke_w=0.0):
        self.ops.append(("round_rect", x, y, w, h, radius, fill, stroke, stroke_w))

    def circle(self, cx, cy, r, fill=None, stroke=None, stroke_w=0.0):
        self.ops.append(("circle", cx, cy, r, fill, stroke, stroke_w))

    def line(self, x1, y1, x2, y2, color, width):
        self.ops.append(("line", x1, y1, x2, y2, color, width))

    def image(self, path: Path, x, y, w, h, role: str = ""):
        self.ops.append(("image", str(path), x, y, w, h, role))

    def text(self, *args, **kwargs) -> Text:
        t = Text(*args, **kwargs)
        self.ops.append(("text", t))
        return t

    def texts(self) -> list[Text]:
        return [op[1] for op in self.ops if op[0] == "text"]


@lru_cache(maxsize=None)
def _glyph_bounds(font: str) -> tuple[dict, float, float]:
    """(ký tự -> (yMin, yMax) theo em, ascent, descent) đọc từ file TTF của font đã đăng ký."""
    from fontTools.ttLib import TTFont as FTFont

    path = pdfmetrics.getFont(font).face.filename
    ft = FTFont(path, lazy=True)
    upm = ft["head"].unitsPerEm
    glyf, cmap = ft["glyf"], ft.getBestCmap()
    bounds = {}
    for code, gname in cmap.items():
        g = glyf[gname]
        if getattr(g, "numberOfContours", 0):
            g.recalcBounds(glyf)
            bounds[chr(code)] = (g.yMin / upm, g.yMax / upm)
    asc, desc = pdfmetrics.getAscentDescent(font, 1)
    return bounds, asc, desc


def ink_extent(font: str, text: str) -> tuple[float, float]:
    """(đỉnh, đáy) của nét chữ theo đơn vị em, so với baseline (đáy âm = thò xuống dưới)."""
    bounds, asc, desc = _glyph_bounds(font)
    ys = [bounds[ch] for ch in text if ch in bounds]
    if not ys:
        return asc, desc
    return max(y[1] for y in ys), min(y[0] for y in ys)


def text_width(text: str, font: str, size: float, tracking: float = 0.0) -> float:
    return pdfmetrics.stringWidth(text, font, size) + tracking * max(0, len(text) - 1)


def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if not line or text_width(trial, font, size) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def blend_hex(c1: str, c2: str, t: float) -> str:
    """Hòa sắc 2 mã màu hex: (1 - t)*c1 + t*c2 với t thuộc [0.0, 1.0]."""
    c1 = c1.lstrip("#")
    c2 = c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = round(r1 * (1.0 - t) + r2 * t)
    g = round(g1 * (1.0 - t) + g2 * t)
    b = round(b1 * (1.0 - t) + b2 * t)
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def write_pdf(pages: list[Page], path: Path) -> None:
    c = canvas.Canvas(str(path))
    for page in pages:
        W, H = page.width, page.height
        c.setPageSize((W * PX_TO_PT, H * PX_TO_PT))
        c.saveState()
        c.scale(PX_TO_PT, PX_TO_PT)
        flip = lambda y: H - y  # noqa: E731 - px (gốc trên-trái) -> PDF (gốc dưới-trái)
        for op in page.ops:
            kind = op[0]
            if kind == "rect":
                _, x, y, w, h, fill, stroke, sw = op
                if fill:
                    c.setFillColor(HexColor(fill))
                if stroke:
                    c.setStrokeColor(HexColor(stroke))
                    c.setLineWidth(sw)
                c.rect(x, flip(y + h), w, h, fill=int(bool(fill)), stroke=int(bool(stroke)))
            elif kind == "round_rect":
                _, x, y, w, h, radius, fill, stroke, sw = op
                if fill:
                    c.setFillColor(HexColor(fill))
                if stroke:
                    c.setStrokeColor(HexColor(stroke))
                    c.setLineWidth(sw)
                c.roundRect(x, flip(y + h), w, h, radius,
                            fill=int(bool(fill)), stroke=int(bool(stroke)))
            elif kind == "circle":
                _, cx, cy, r, fill, stroke, sw = op
                if fill:
                    c.setFillColor(HexColor(fill))
                if stroke:
                    c.setStrokeColor(HexColor(stroke))
                    c.setLineWidth(sw)
                c.circle(cx, flip(cy), r, fill=int(bool(fill)), stroke=int(bool(stroke)))
            elif kind == "line":
                _, x1, y1, x2, y2, color, width = op
                c.setStrokeColor(HexColor(color))
                c.setLineWidth(width)
                c.line(x1, flip(y1), x2, flip(y2))
            elif kind == "image":
                _, src, x, y, w, h, _role = op
                c.drawImage(src, x, flip(y + h), w, h, mask="auto")
            elif kind == "text":
                t: Text = op[1]
                left = t.bbox()[0]
                c.saveState()  # giãn chữ (Tc) là trạng thái dùng chung -> phải bọc lại
                obj = c.beginText(left, flip(t.y))
                obj.setFont(t.font, t.size)
                obj.setCharSpace(t.tracking)
                obj.setFillColor(HexColor(t.color))
                obj.textOut(t.text)
                c.drawText(obj)
                c.restoreState()
        c.restoreState()
        c.showPage()
    c.save()


def pdf_to_pngs(pdf: Path, outs: list[Path], dpi: int = 300) -> None:
    """Rasterize từng trang rồi nén PNG song song: nén PNG (zlib) là phần chậm nhất, cv2 nhả GIL nên
    chạy nhiều luồng được. Ảnh ra y hệt (PNG không mất dữ liệu), DPI ghi vào file như trước."""
    from concurrent.futures import ThreadPoolExecutor

    import cv2
    import numpy as np
    import pymupdf

    def save(pixels: np.ndarray, out: Path) -> None:
        ok, buf = cv2.imencode(".png", pixels[:, :, ::-1], [cv2.IMWRITE_PNG_COMPRESSION, 3])
        if not ok:
            raise RuntimeError(f"không nén được {out.name}")
        out.write_bytes(_png_with_dpi(buf.tobytes(), dpi))

    with pymupdf.open(pdf) as doc, ThreadPoolExecutor(max_workers=RENDER_THREADS) as pool:
        jobs = []
        for page, out in zip(doc, outs):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
            jobs.append(pool.submit(save, arr, out))
        for j in jobs:
            j.result()


# nén PNG trang in: tối đa 4 luồng (trước 8) - batch còn Chrome, OCR, upscale chạy song song, 8 luồng làm máy giật
RENDER_THREADS = max(1, min(4, (os.cpu_count() or 4) // 2))


def _png_with_dpi(data: bytes, dpi: int) -> bytes:
    """Chèn chunk pHYs (DPI) ngay sau IHDR - Printify và phần mềm in đọc DPI từ đây."""
    import struct
    import zlib

    ppm = round(dpi / 0.0254)
    body = b"pHYs" + struct.pack(">IIB", ppm, ppm, 1)
    chunk = struct.pack(">I", 9) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    ihdr_end = 8 + 4 + 4 + 13 + 4
    return data[:ihdr_end] + chunk + data[ihdr_end:]
