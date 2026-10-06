"""Listing chuẩn Etsy (tuỳ chọn "Listing: Etsy" lúc tạo batch): ChatGPT viết title / mô tả / 13 tag, code soát
luật Etsy rồi mới nhận; sai thì nhờ ChatGPT sửa (tối đa 2 lần); vẫn sai / ChatGPT lỗi thì dùng listing thường (cuốn
không bị kẹt).

Luật Etsy được soát (help.etsy.com + tài liệu listing của Etsy):
- Title: tối đa 140 ký tự; %, :, &, + mỗi ký tự tối đa 1 lần; cấm $ ^ ` °; tối đa 3 từ VIẾT HOA toàn bộ.
- Tag: đúng 13 tag, mỗi tag tối đa 20 ký tự, chỉ chữ / số / khoảng trắng, không trùng.
- Mô tả: chữ thường (Etsy không hiện HTML), đoạn mở đầu nói rõ sản phẩm; phần Details cố định do code nối vào cuối.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .. import layout

TITLE_MAX = 140
TAG_MAX = 20
TAG_COUNT = 13
ONCE_CHARS = "%:&+"
BANNED_CHARS = "$^`°"

DETAILS_TEXT = ("Details\n"
                "- Sizes:\n"
                "  - 11 x 8.5 in (opens to 11 x 17 in)\n"
                "  - 14 x 11.5 in (opens to 14 x 23 in)\n"
                "- Binding: wire-bound, with a hanging hole\n"
                "- Printing: printed on demand and shipped to you")
DETAILS_HTML = ("<p><strong>Details</strong></p><ul><li>Sizes:<ul><li>11 x 8.5 in (opens to 11 x 17 in)</li>"
                "<li>14 x 11.5 in (opens to 14 x 23 in)</li></ul></li>"
                "<li>Binding: wire-bound, with a hanging hole</li>"
                "<li>Printing: printed on demand and shipped to you</li></ul>")


def prompt(concept: dict) -> str:
    from ..core import dates
    cov = concept.get("cover") or {}
    months = "\n".join(f"- {dates.MONTH_NAMES[i]}: {m.get('subtitle', '')}"
                       for i, m in enumerate(concept.get("months") or []))
    style = (concept.get("style") or {}).get("name", "")
    old = concept.get("listing") or {}
    return f"""You are an experienced Etsy SEO copywriter. Write the Etsy listing for this printed wall calendar.

PRODUCT
- Calendar title: {cov.get('title', concept.get('title', ''))}
- Subtitle: {cov.get('subtitle', '')}
- Year: {concept.get('year', '')}
- Shop keyword (what buyers search): {concept.get('keyword', '')}
- Buyer: {concept.get('buyer', '')}
- Art style: {style}
- Months:
{months}
- Current SEO title (for reference only): {old.get('seo_title', '')}

ETSY RULES (must all be met)
1. "title": at most 140 characters, natural and readable. Put the most important search phrase first
   (e.g. "2027 ... Wall Calendar"), then 1-2 short descriptive phrases. Do not repeat the same word more than twice.
   Use each of these characters at most once: % : & +. Never use $ ^ ` or °. No more than 3 words in ALL CAPS.
   No emojis, no "free shipping", no prices, no shop name.
2. "description": plain text (no HTML, no markdown, no emojis). Start with 1-2 sentences that say exactly what the
   product is, using the main search phrase naturally. Then a short paragraph on the artwork and who it is for
   (gift ideas). Then a line "What's inside" followed by 3-4 lines starting with "- ". 600 to 1500 characters.
   Do NOT include sizes, binding, printing or shipping details (they are added automatically).
3. "tags": exactly 13 different tags, each at most 20 characters, lowercase, only letters, numbers and spaces.
   Mix broad and specific long-tail phrases buyers actually type; include the year in 1-2 tags; do not repeat the
   exact title phrase in every tag.
4. Only describe this original artwork. Do not mention or imply any brand, celebrity, trademark, team, film,
   franchise or other company's characters.

Return ONLY this JSON in a ```json code block:
{{"title": "", "description": "", "tags": []}}"""


def validate(d: dict) -> list[str]:
    """Lỗi so với luật Etsy (rỗng = đạt)."""
    errors = []
    if not isinstance(d, dict):
        return ["the answer must be a JSON object with title, description and tags"]
    title = d.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is missing")
    else:
        t = title.strip()
        if len(t) > TITLE_MAX:
            errors.append(f"title has {len(t)} characters, the maximum is {TITLE_MAX}")
        if len(t) < 30:
            errors.append("title is too short (under 30 characters)")
        for ch in ONCE_CHARS:
            if t.count(ch) > 1:
                errors.append(f'title uses "{ch}" {t.count(ch)} times, Etsy allows it once')
        bad = sorted({ch for ch in t if ch in BANNED_CHARS})
        if bad:
            errors.append(f"title contains characters Etsy does not allow: {' '.join(bad)}")
        caps = [w for w in re.findall(r"[A-Za-z]{2,}", t) if w.isupper()]
        if len(caps) > 3:
            errors.append(f"title has {len(caps)} words in ALL CAPS, Etsy allows at most 3")
        words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", t)]
        rep = sorted({w for w in words if words.count(w) > 2})
        if rep:
            errors.append(f"title repeats these words more than twice: {', '.join(rep)}")
        if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", t):
            errors.append("title must not contain emojis")
    desc = d.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("description is missing")
    else:
        if re.search(r"<\s*/?\s*[a-zA-Z][^>]*>", desc):
            errors.append("description must be plain text, without HTML tags")
        if not 300 <= len(desc.strip()) <= 4000:
            errors.append(f"description has {len(desc.strip())} characters, write 600 to 1500")
    tags = d.get("tags")
    if not isinstance(tags, list):
        errors.append("tags must be a list of 13 strings")
    else:
        clean = [str(t).strip().lower() for t in tags if str(t).strip()]
        if len(clean) != TAG_COUNT:
            errors.append(f"there are {len(clean)} tags, Etsy needs exactly {TAG_COUNT}")
        long = [t for t in clean if len(t) > TAG_MAX]
        if long:
            errors.append(f"these tags are longer than {TAG_MAX} characters: {'; '.join(long)}")
        odd = [t for t in clean if not re.fullmatch(r"[a-z0-9 ]+", t)]
        if odd:
            errors.append(f"tags may only contain letters, numbers and spaces: {'; '.join(odd)}")
        if len(set(clean)) != len(clean):
            errors.append("tags must all be different")
    return errors


def to_html(text: str) -> str:
    """Mô tả chữ thường -> HTML cho CSV (đoạn văn + danh sách "- ")."""
    out, items = [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>")
            items.clear()
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        para = []
        for l in lines:
            if l.startswith(("- ", "• ", "* ")):
                if para:
                    out.append("<p>" + html.escape(" ".join(para)) + "</p>")
                    para = []
                items.append(l[2:].strip())
            else:
                flush()
                para.append(l)
        if para:
            out.append("<p>" + html.escape(" ".join(para)) + "</p>")
        flush()
    return "".join(out)


def generate(concept: dict, cfg: dict, workdir: Path, on_event=print, max_repairs: int = 2) -> dict | None:
    """Nhờ ChatGPT viết listing chuẩn Etsy. None = không được (dùng listing thường)."""
    from .. import config
    from ..ideation.extract import extract_json
    try:
        backend = config.make_backend(cfg)
        with backend.session(workdir) as chat:
            ask = prompt(concept)
            for attempt in range(max_repairs + 1):
                answer = chat.ask(ask, f"etsy_listing{'_repair' + str(attempt) if attempt else ''}")
                try:
                    data = extract_json(answer)
                except Exception:  # noqa: BLE001
                    data = None
                errors = validate(data) if data is not None else ["the answer did not contain the JSON block"]
                if not errors:
                    text = data["description"].strip()
                    return {"title": data["title"].strip(),
                            "description": to_html(text) + DETAILS_HTML,
                            "description_text": text + "\n\n" + DETAILS_TEXT,
                            "tags": [str(t).strip().lower() for t in data["tags"]],
                            "style": "etsy"}
                on_event(f"  ⚠ Listing Etsy chưa đạt luật ({'; '.join(errors)[:160]}) - nhờ ChatGPT sửa")
                prev = json.dumps(data, ensure_ascii=False) if data is not None else (answer or "")[-1500:]
                ask = ("Your previous Etsy listing broke these Etsy rules:\n- " + "\n- ".join(errors)
                       + "\n\nHere is your previous answer:\n" + prev
                       + "\n\nFix every problem and return the full corrected JSON "
                         '{"title": "", "description": "", "tags": []} in a ```json code block.')
    except Exception as e:  # noqa: BLE001 - ChatGPT / tài khoản lỗi: không chặn cuốn
        on_event(f"  ⚠ Không viết được listing Etsy ({type(e).__name__}: {str(e)[:120]}) - dùng listing thường")
        return None
    on_event("  ⚠ Listing Etsy vẫn chưa đạt luật sau khi sửa - dùng listing thường")
    return None


def write(concept_dir: Path, concept: dict, cfg: dict, on_event=print) -> dict | None:
    listing = generate(concept, cfg, layout.tech(concept_dir, "listing_etsy"), on_event)
    if listing:
        layout.listing_file(concept_dir).write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
        on_event(f"  ✔ Listing chuẩn Etsy: {listing['title'][:90]}")
    return listing
