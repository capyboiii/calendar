"""Bảng màu trang lưới/bìa: Ý ĐỒ từ concept (ChatGPT) + SẮC ĐỘ THẬT từ ảnh neo (code).

- Concept (P2) nói trang nên mang màu gì (vd nền "xanh xô thơm nhạt"). Code tìm trong tranh đúng
  vùng màu gần ý đồ đó và dùng sắc độ của chính tranh -> nền vừa đúng ý đồ, vừa "ăn" với tranh.
- Concept chọn nền trung tính (kem/trắng) thì coi như không có ý đồ: code lấy màu mát nổi bật
  trong tranh (trời, lá, nước) nếu có đủ, để không cuốn nào cũng thành màu kem - vì tông vàng be
  của nắng/rơm/giấy có mặt trong gần như mọi tranh vẽ ấm.
- Màu nhấn: màu trong tranh gần màu nhấn của concept nhất (không có thì màu rực nhất tranh).
- Mọi màu chữ được làm tối dần tới khi đủ tương phản với nền (tiêu đề >= 7, chữ và màu nhấn >= 4.5).
"""
from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image

from ..ideation.validate import contrast_ratio

BINS = 36
WARM = (0.0, 0.17)        # đỏ cam -> vàng: ánh nắng, rơm, gỗ, giấy
NEUTRAL_CHROMA = 0.10     # màu nền "không có ý đồ" (kem, trắng ngà: #F8F1DF có chroma 0.098)


def _hex(rgb) -> str:
    r, g, b = (int(round(max(0, min(1, c)) * 255)) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb(hex_: str) -> tuple[float, float, float]:
    return tuple(int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _hls(h: float, l: float, s: float) -> str:
    return _hex(colorsys.hls_to_rgb(h % 1.0, l, s))


def _chroma(hex_: str) -> float:
    c = _rgb(hex_)
    return max(c) - min(c)


def _hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1 - d)


def _darken_until(h: float, s: float, l: float, bg: str, target: float) -> str:
    while l > 0.05 and contrast_ratio(_hls(h, l, s), bg) < target:
        l -= 0.02
    return _hls(h, l, s)


class _Art:
    """Phân bố sắc độ của ảnh: mỗi pixel đủ màu góp phiếu vào dải sắc độ, trọng số = độ đậm màu."""

    def __init__(self, path: Path):
        with Image.open(path) as im:
            px = np.asarray(im.convert("RGB").resize((160, 107)), dtype=np.float32).reshape(-1, 3) / 255
        ch = px.max(1) - px.min(1)
        keep = ch > 0.08
        self.px, self.w = px[keep], ch[keep]
        self.hue = np.array([colorsys.rgb_to_hls(*p)[0] for p in self.px])
        self.lum = np.array([colorsys.rgb_to_hls(*p)[1] for p in self.px])

    def share(self, mask) -> float:
        return float(self.w[mask].sum() / self.w.sum()) if self.w.sum() else 0.0

    def near(self, h: float, width: float = 0.07):
        return np.array([_hue_dist(x, h) <= width for x in self.hue])

    def mean_hue(self, mask) -> float:
        ang = self.hue[mask] * 2 * np.pi
        return float(np.arctan2((np.sin(ang) * self.w[mask]).sum(), (np.cos(ang) * self.w[mask]).sum()) / (2 * np.pi)) % 1.0

    def peak(self, mask) -> float:
        hist = np.bincount((self.hue[mask] * BINS).astype(int) % BINS, weights=self.w[mask], minlength=BINS)
        return (int(hist.argmax()) + 0.5) / BINS

    def vivid(self) -> tuple[float, float]:
        """(hue, chroma) của vùng màu rực nhất ở độ sáng vừa."""
        score = self.w * (1 - np.abs(self.lum - 0.5))
        i = int(score.argmax())
        return float(self.hue[i]), float(self.w[i])


def palette_from_image(path: Path, hint: dict | None = None) -> dict:
    art = _Art(path)
    hint = hint or {}
    note = []

    # ---- màu nền ----
    target = hint.get("paper")
    if target and _chroma(target) >= NEUTRAL_CHROMA:
        th = colorsys.rgb_to_hls(*_rgb(target))[0]
        mask = art.near(th)
        if art.share(mask) >= 0.02:
            h = art.mean_hue(mask)
            note.append(f"nền theo ý đồ concept {target}, lấy sắc độ thật trong tranh")
        else:
            h = th
            note.append(f"nền theo ý đồ concept {target} (tranh ít màu này)")
    else:
        warm = np.array([WARM[0] <= x <= WARM[1] for x in art.hue])
        cool = ~warm
        if art.share(cool) >= 0.08:
            h = art.peak(cool)
            note.append("nền lấy màu mát nổi bật trong tranh (concept để nền trung tính)")
        else:
            h = art.peak(np.ones_like(warm))
            note.append("nền lấy màu chủ đạo của tranh")
    tint = 0.42
    background = _hls(h, 0.93, tint)

    # ---- chữ: cùng họ màu với nền, hoặc theo sắc độ màu chữ của concept ----
    title_h = colorsys.rgb_to_hls(*_rgb(hint["title"]))[0] if hint.get("title") and _chroma(hint["title"]) > 0.08 else h
    title = _darken_until(title_h, 0.45, 0.26, background, 7.0)
    text = _darken_until(title_h, 0.18, 0.28, background, 4.5)

    # ---- màu nhấn: màu trong tranh gần màu nhấn của concept nhất ----
    if hint.get("accent") and _chroma(hint["accent"]) > 0.1:
        ah = colorsys.rgb_to_hls(*_rgb(hint["accent"]))[0]
        mask = art.near(ah, 0.08)
        ah = art.mean_hue(mask) if art.share(mask) >= 0.02 else ah
    else:
        ah, _ = art.vivid()
    accent = _darken_until(ah, 0.6, 0.42, background, 4.5)
    grid_line = _hls(h, 0.72, 0.22)
    return {"paper": background, "title": title, "text": text, "accent": accent, "grid_line": grid_line,
            "_source": f"ảnh neo {path.name}", "_note": "; ".join(note)}
