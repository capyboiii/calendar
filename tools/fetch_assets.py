"""Tải font (Google Fonts, giấy phép OFL) và bộ Kinh Thánh KJV (phạm vi công cộng).

Chạy:  python tools/fetch_assets.py            (bỏ qua file đã có)
       python tools/fetch_assets.py --force    (tải lại hết)

- Font: bản static TTF (subset latin) qua CDN Fontsource, lưu fonts/<Family>/<Family>-<Style>.ttf
  đúng quy ước calforge/render/fonts.py. Chỉ tải các family trong data/fonts.json.
- KJV: github.com/aruljohn/Bible-kjv (mỗi sách 1 file) -> data/kjv.json dạng {"Mark": {"4": {"39": "..."}}}.
  Không dùng thiagobodruk/bible: bộ đó lệch cách đánh số câu so với KJV ở vài chương (Mark 7,
  3 John 1, Revelation 12), tra mã câu có thể ra lời của câu bên cạnh.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calforge.core.kjv import BOOKS  # noqa: E402

FONT_URL = "https://cdn.jsdelivr.net/fontsource/fonts/{id}@latest/latin-{weight}-{style}.ttf"
STYLES = {"Regular": (400, "normal"), "SemiBold": (600, "normal"), "Bold": (700, "normal"),
          "Italic": (400, "italic")}
KJV_URL = "https://raw.githubusercontent.com/aruljohn/Bible-kjv/master/{book}.json"
KJV_TOTAL_VERSES = 31102  # tổng số câu chuẩn của KJV


def fetch(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fetch_fonts(force: bool) -> None:
    fonts = json.loads((ROOT / "data" / "fonts.json").read_text(encoding="utf-8"))
    families = sorted({f for k, v in fonts.items() if not k.startswith("_") for f in v})
    for family in families:
        folder = ROOT / "fonts" / family
        folder.mkdir(parents=True, exist_ok=True)
        got = []
        for style, (weight, kind) in STYLES.items():
            dst = folder / f"{family.replace(' ', '')}-{style}.ttf"
            if dst.exists() and not force:
                got.append(style)
                continue
            data = fetch(FONT_URL.format(id=family.lower().replace(" ", "-"), weight=weight, style=kind))
            if data and data[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                dst.write_bytes(data)
                got.append(style)
        print(f"{family:<20} {', '.join(got) or 'KHÔNG tải được'}")


def fetch_kjv(force: bool) -> None:
    dst = ROOT / "data" / "kjv.json"
    if dst.exists() and not force:
        print("KJV: đã có")
        return
    out, verses = {}, 0
    for name in BOOKS:
        book = json.loads(fetch(KJV_URL.format(book=name.replace(" ", ""))).decode("utf-8-sig"))
        out[name] = {}
        for ch in book["chapters"]:
            out[name][str(int(ch["chapter"]))] = {
                str(int(v["verse"])): re.sub(r"\s+", " ", v["text"]).strip() for v in ch["verses"]}
            verses += len(ch["verses"])
    if verses != KJV_TOTAL_VERSES:
        raise RuntimeError(f"Bộ KJV tải về có {verses} câu, chuẩn là {KJV_TOTAL_VERSES} - không ghi đè")
    dst.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"KJV: {len(out)} sách, {verses} câu -> {dst}")


def fetch_upscaler(force: bool) -> None:
    from calforge.imagegen.upscale import WEIGHTS, WEIGHTS_URL

    if WEIGHTS.exists() and not force:
        print("Real-ESRGAN: đã có")
        return
    WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    data = fetch(WEIGHTS_URL)
    if not data or len(data) < 10_000_000:
        raise RuntimeError("Tải trọng số Real-ESRGAN lỗi")
    WEIGHTS.write_bytes(data)
    print(f"Real-ESRGAN: {len(data) / 1e6:.0f} MB -> {WEIGHTS}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    fetch_fonts(force)
    fetch_kjv(force)
    fetch_upscaler(force)
