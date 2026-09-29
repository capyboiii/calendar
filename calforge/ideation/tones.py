"""Tông màu nền chung của cả cuốn (shared_base_color), chia đều theo danh mục từ lúc lên ý tưởng (P2).

Tranh 12 tháng, bìa và nền grid đều lấy chung shared_base_color, nên giao tông ở P2 là cách duy nhất để grid luôn
khớp tranh mà các cuốn không cùng một màu kem. Code giao tông ít dùng nhất; AI chọn sắc độ cụ thể trong tông đó
(được đổi tông khác nếu tông giao thật sự không hợp chủ đề, phải ghi lý do). Đếm theo màu THẬT của cuốn (xếp hex
vào tông gần nhất), nên cuốn cũ chưa có nhãn tông vẫn được tính.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# key -> (tên hiện cho AI, mô tả, màu mốc để xếp loại)
BASE_TONES: dict[str, tuple[str, str, str]] = {
    "cream": ("warm cream", "warm cream, linen, oatmeal or parchment", "#ECE3D4"),
    "blush": ("soft blush", "pale blush, rose-dust or shell pink", "#F4E2DE"),
    "sage": ("sage green", "pale sage, eucalyptus or celadon green", "#DDE5D4"),
    "sky": ("pale sky blue", "pale sky, mist or powder blue", "#DAE5EE"),
    "grey": ("cool grey", "cool dove, pebble or fog grey", "#DFE1E3"),
    "butter": ("butter yellow", "butter, straw or soft sunlit yellow", "#F6E9C0"),
}
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _rgb(hex_color: str) -> tuple[int, int, int] | None:
    m = _HEX.match(str(hex_color or "").strip())
    if not m:
        return None
    v = m.group(1)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def classify(hex_color: str) -> str | None:
    """Tông gần nhất của một màu, bỏ qua độ sáng (so hướng màu: đỏ-lục, lục-lam)."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return None

    def chroma(c):
        r, g, b = c
        return r - g, g - b

    x = chroma(rgb)
    return min(BASE_TONES, key=lambda k: sum((a - b) ** 2 for a, b in zip(x, chroma(_rgb(BASE_TONES[k][2])))))


def book_tone(concept: dict) -> str | None:
    st = concept.get("style") or {}
    base = st.get("shared_base_color") or {}
    return classify(base.get("hex", "") if isinstance(base, dict) else "")


def usage(projects_root: Path) -> dict[str, int]:
    """Số cuốn Wall Calendar (Blank) theo tông (loại grid in sẵn không có trang grid AI, không tính)."""
    from .. import layout, products
    counts = dict.fromkeys(BASE_TONES, 0)
    for b in layout.books(projects_root):
        try:
            c = json.loads(layout.concept_file(b).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not products.ai_grid(c):
            continue
        tone = book_tone(c)
        if tone:
            counts[tone] += 1
    return counts


def next_tone(projects_root: Path) -> str:
    """Tông ít cuốn dùng nhất (hoà thì theo thứ tự BASE_TONES)."""
    counts = usage(projects_root)
    return min(counts, key=lambda k: counts[k])


def prompt_rule(tone: str, projects_root: Path | None = None) -> str:
    name, desc, anchor = BASE_TONES[tone]
    order = usage(projects_root) if projects_root else dict.fromkeys(BASE_TONES, 0)
    others = ", ".join(BASE_TONES[k][0] for k in sorted(order, key=lambda k: order[k]) if k != tone)
    return (f"ASSIGNED BASE TONE (software, spreads tones evenly across the portfolio): {name} — {desc}, "
            f"near {anchor}. Choose `shared_base_color` as a shade inside this tone family and build the color "
            "story, artworks and grid around it, so every page of the calendar shares one atmosphere. Only if this "
            "tone clearly clashes with the subject, use the next least-used tone instead, in this order: "
            f"{others}; then explain why in \"style\".\"base_tone_note\".")
