"""Nội dung listing (title, mô tả HTML, tag) dựng từ concept.json - không hỏi thêm ChatGPT."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .. import layout
from ..core import dates

GRID_FEATURE = {
    "prayer_list": "a Prayer List column on every month",
    "notes_column": "a Notes column on every month",
    "standard": "large date boxes for appointments and notes",
}


def build_listing(concept: dict) -> dict:
    title = concept["listing"]["seo_title"][:140]
    tags = [t.lower()[:20] for t in concept["listing"]["tags"]][:13]
    e = html.escape
    months = concept["months"]
    kjv = concept.get("content_type") == "bible_verse_kjv"
    from .. import products
    premade = not products.ai_grid(concept)   # grid in sẵn: không có câu Kinh Thánh / chức năng grid riêng
    kjv = kjv and not premade
    items = []
    for i, m in enumerate(months):
        extra = f" — {e(m['content']['value'])} (KJV)" if kjv else ""
        items.append(f"<li><strong>{dates.MONTH_NAMES[i]}</strong>: {e(m['subtitle'])}{extra}</li>")
    feature = GRID_FEATURE.get(concept.get("grid_function", "standard"), GRID_FEATURE["standard"])
    desc = "".join([
        f"<p>{e(concept['cover']['title'])} — {e(concept['cover'].get('subtitle', ''))}. "
        f"A {concept['year']} wall calendar with original {e(concept['style']['name'].lower())} artwork "
        f"for every month.</p>",
        "<p><strong>What's inside</strong></p><ul>",
        "<li>12 full-page original artworks, one for each month</li>",
        "<li>A monthly date grid for every month</li>" if premade else
        f"<li>Monthly grid with US holidays and {feature}</li>",
        "<li>King James Version scripture for each month</li>" if kjv else "",
        "<li>Front cover and a back cover with all 12 artworks</li></ul>",
        f"<p><strong>Months</strong></p><ul>{''.join(items)}</ul>",
        # phần Details CỐ ĐỊNH cho mọi cuốn (người dùng duyệt 03/10/2026)
        "<p><strong>Details</strong></p><ul><li>Sizes:<ul><li>11 x 8.5 in (opens to 11 x 17 in)</li>"
        "<li>14 x 11.5 in (opens to 14 x 23 in)</li></ul></li>"
        "<li>Binding: wire-bound, with a hanging hole</li>"
        "<li>Printing: printed on demand and shipped to you</li></ul>",
    ])
    return {"title": title, "description": desc, "tags": tags}


LISTING_STYLES = ("standard", "etsy")


def write_listing(concept_dir: Path, cfg: dict | None = None, on_event=print) -> dict:
    """listing.json của cuốn. Cuốn chọn "Listing: Etsy" (concept["listing_style"]) và có cfg: ChatGPT viết bản
    chuẩn Etsy (publish/etsy_listing.py); không được thì lùi về bản thường dựng từ concept."""
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    if cfg is not None and concept.get("listing_style") == "etsy":
        from .etsy_listing import write as write_etsy
        layout.tech(concept_dir, "listing_etsy").mkdir(parents=True, exist_ok=True)
        etsy = write_etsy(concept_dir, concept, cfg, on_event)
        if etsy:
            write_listing_txt(concept_dir, etsy)
            return etsy
    listing = build_listing(concept)
    layout.listing_file(concept_dir).write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    write_listing_txt(concept_dir, listing)
    return listing


LISTING_TXT = "listing.txt"
NL = "\n"


def html_to_text(desc: str) -> str:
    """Mô tả HTML -> chữ thường để dán lên shop: đoạn cách dòng, mục danh sách "- " (danh sách con thụt 2 dấu cách)."""
    import re
    t = re.sub(r"\s*<br\s*/?>\s*", NL, desc or "")
    depth, out, pos = 0, [], 0
    for m in re.finditer(r"<(/?)(ul|li|p|strong|em|b|i)[^>]*>", t):
        out.append(t[pos:m.start()])
        closing, tag = m.group(1), m.group(2)
        if tag == "ul":
            depth += -1 if closing else 1
            out.append(NL)
        elif tag == "li" and not closing:
            out.append(NL + "  " * max(0, depth - 1) + "- ")
        elif tag == "p":
            out.append(NL * 2)
        pos = m.end()
    out.append(t[pos:])
    text = html.unescape(re.sub(r"<[^>]+>", "", "".join(out)))
    text = re.sub(r"[ \t]+\n", NL, text)
    text = re.sub(r"\n{3,}", NL * 2, text)
    return re.sub(r"\n\n(?=\s*- )", NL, text).strip()   # mục danh sách liền ngay dưới tiêu đề, không dòng trống


def write_listing_txt(concept_dir: Path, listing: dict) -> Path:
    """listing.txt ngay trong thư mục cuốn (cạnh 11x8.5 / 14x11.5 / preview): title, tags, mô tả - mở ra chép thẳng
    lên shop, khỏi phải mở tool."""
    desc = listing.get("description_text") or html_to_text(listing.get("description", ""))
    text = NL.join(["TITLE", listing.get("title", ""), "", "TAGS", ", ".join(listing.get("tags", [])), "",
                    "DESCRIPTION", desc, ""])
    f = Path(concept_dir) / LISTING_TXT
    f.write_text(text, encoding="utf-8-sig")              # có BOM: Notepad mở đúng mọi ký tự
    return f
