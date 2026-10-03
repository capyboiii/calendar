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


def write_listing(concept_dir: Path) -> dict:
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    listing = build_listing(concept)
    layout.listing_file(concept_dir).write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    return listing
