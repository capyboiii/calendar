"""Kiểm tra output của ChatGPT trước khi nhận.

Mỗi hàm trả về (errors, warnings):
- errors: lỗi khách quan có thể kiểm chắc bằng code -> phải sửa qua P3.
- warnings: đánh giá ngữ nghĩa/thẩm mỹ gần đúng -> ghi nhận, không chặn.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import dates, kjv
from ..render.grid_compositions import COMPOSITIONS
from . import catalog
from .templates import load_fonts

BANNED_FILE = Path(__file__).resolve().parents[2] / "data" / "banned_terms.txt"

FRAME_TYPES = {"seasonal", "collection", "journey", "one_scene_12_seasons", "word_of_month"}
CONTENT_TYPES = {"bible_verse_kjv", "practical_tip", "fun_fact", "affirmation", "public_domain_quote", "none"}
GRID_FUNCTIONS = {"standard", "notes_column", "family_columns", "prayer_list", "moon_phases", "tracker"}
IP_RISKS = {"none", "low", "high"}
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _relative_luminance(value: str) -> float:
    rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def banned_terms() -> list[str]:
    lines = BANNED_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#")]


def _strings(obj, path=""):
    """Duyệt mọi chuỗi trong JSON kèm đường dẫn, để báo lỗi chỉ đúng chỗ."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def _banned_hits(obj) -> list[str]:
    terms = banned_terms()
    hits = []
    for path, s in _strings(obj):
        low = s.lower()
        for t in terms:
            if re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", low):
                hits.append(f'{path} contains the banned term "{t}" (trademark/IP risk) — replace it')
    return hits


def _words(s: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", s or ""))


def _similar(a: str, b: str) -> float:
    """Độ giống thô giữa 2 câu mô tả (Jaccard trên tập từ có nghĩa)."""
    stop = {"a", "an", "the", "of", "in", "on", "with", "and", "at", "to", "by", "for", "under", "over"}
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if w not in stop}
    wb = {w for w in re.findall(r"[a-z]+", b.lower()) if w not in stop}
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


_STOP = {"a", "an", "the", "of", "in", "on", "with", "and", "at", "to", "by", "for", "under", "over", "its",
          "from", "into", "onto", "their", "his", "her", "while", "that", "this", "just", "some", "one", "two"}


def _stem(w: str) -> str:
    return w[:5]  # khớp thô: "chicks"~"chick", "blooming"~"bloom"


def _coverage(needle: str, hay: str) -> float:
    """Tỉ lệ từ có nghĩa của `needle` xuất hiện trong `hay` (so theo gốc từ thô)."""
    want = {_stem(w) for w in re.findall(r"[a-z]+", needle.lower()) if w not in _STOP and len(w) > 2}
    have = {_stem(w) for w in re.findall(r"[a-z]+", hay.lower())}
    return len(want & have) / len(want) if want else 1.0


def contrast_ratio(hex1: str, hex2: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    l1, l2 = sorted((lum(hex1), lum(hex2)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


# ---------------------------------------------------------------------------
# P1: danh sách góc tiếp cận
# ---------------------------------------------------------------------------
def validate_angles(data: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    angles = data.get("angles")
    if not isinstance(angles, list) or not angles:
        return ['"angles" must be a non-empty list'], warnings
    ids = set()
    for i, a in enumerate(angles):
        p = f"angles[{i}]"
        for key in ("id", "title", "hook", "buyer", "frame_type", "months_sketch", "recurring_motif",
                    "content_type", "grid_function", "ai_feasibility", "ip_risk"):
            if key not in a:
                errors.append(f"{p} is missing \"{key}\"")
        if a.get("id") in ids:
            errors.append(f'{p}.id "{a.get("id")}" is duplicated')
        ids.add(a.get("id"))
        if a.get("frame_type") not in FRAME_TYPES:
            errors.append(f"{p}.frame_type must be one of {sorted(FRAME_TYPES)}")
        if a.get("content_type") not in CONTENT_TYPES:
            errors.append(f"{p}.content_type must be one of {sorted(CONTENT_TYPES)}")
        if a.get("grid_function") not in GRID_FUNCTIONS:
            errors.append(f"{p}.grid_function must be one of {sorted(GRID_FUNCTIONS)}")
        if a.get("ip_risk") not in IP_RISKS:
            errors.append(f"{p}.ip_risk must be one of {sorted(IP_RISKS)}")
        sketch = a.get("months_sketch") or []
        if len(sketch) != 12:
            errors.append(f"{p}.months_sketch must have exactly 12 items (has {len(sketch)})")
        else:
            for m, item in enumerate(sketch):
                if not str(item).strip().lower().startswith(MONTH_ABBR[m].lower()):
                    warnings.append(f'{p}.months_sketch[{m}] should start with "{MONTH_ABBR[m]}:"')
        score = (a.get("ai_feasibility") or {}).get("score")
        if not isinstance(score, int) or not 1 <= score <= 5:
            errors.append(f"{p}.ai_feasibility.score must be an integer 1-5")
        # art_direction là schema mới; suggested_styles được giữ làm fallback để resume
        # các ledger/project cũ mà không bắt người dùng tạo lại từ đầu.
        direction = a.get("art_direction")
        legacy_direction = next(iter(a.get("suggested_styles") or []), "")
        if direction and _words(str(direction)) < 12:
            errors.append(f"{p}.art_direction must specifically describe medium, palette, composition and surface")
        elif not direction and not legacy_direction:
            errors.append(f"{p}.art_direction is required")
        if a.get("style_family") not in catalog.family_ids():
            errors.append(f'{p}.style_family must be one of: {", ".join(sorted(catalog.family_ids()))}')

    errors += _banned_hits(data)
    return errors, warnings


def usable_angles(data: dict, min_feasibility: int = 3) -> list[dict]:
    """Góc được phép sản xuất: bỏ rủi ro bản quyền cao và khó gen đồng bộ."""
    out = [a for a in data.get("angles", [])
           if a.get("ip_risk") != "high" and (a.get("ai_feasibility") or {}).get("score", 0) >= min_feasibility]
    return sorted(out, key=lambda a: -a["ai_feasibility"]["score"])


# ---------------------------------------------------------------------------
# P2: concept hoàn chỉnh
# ---------------------------------------------------------------------------
def validate_concept(c: dict, year: int, market: str = "US") -> tuple[list[str], list[str]]:
    errors, warnings = [], []

    for key in ("title", "style", "cover", "months", "back_cover", "listing", "content_type"):
        if key not in c:
            errors.append(f'missing top-level key "{key}"')
    fp = c.get("fingerprint")
    if not isinstance(fp, dict) or len(fp.get("months") or []) != 12:
        warnings.append('fingerprint missing or without 12 month labels - portfolio falls back to focal subjects')
    if errors:
        return errors, warnings

    # --- style ---
    st = c["style"]
    composition = st.get("grid_composition")
    if composition not in COMPOSITIONS:
        errors.append(f'style.grid_composition must be one of: {", ".join(COMPOSITIONS)}')
    pal = st.setdefault("palette", {})
    if "background" in pal and "paper" not in pal:  # prompt gọi là background, code phía sau dùng paper
        pal["paper"] = pal.pop("background")
    bible = st.get("style_bible", "")
    if not 50 <= _words(bible) <= 110:
        errors.append(f"style.style_bible must be 60-90 words (has {_words(bible)})")
    story = st.get("color_story", "")
    if _words(story) < 3:
        errors.append("style.color_story must name the 3-4 colors that define this calendar")
    elif _coverage(story, bible) < 0.4:
        warnings.append("style.style_bible may not clearly use the color_story colors by name")
    shared_base = st.get("shared_base_color") or {}
    if not isinstance(shared_base, dict):
        errors.append("style.shared_base_color must contain name and hex")
    else:
        if _words(str(shared_base.get("name", ""))) < 1:
            errors.append("style.shared_base_color.name is required")
        if not HEX.match(str(shared_base.get("hex", ""))):
            errors.append('style.shared_base_color.hex must be a hex color like "#2F6F68"')
    artwork_composition = str(st.get("artwork_composition_system", "")).strip()
    if artwork_composition and _words(artwork_composition) < 6:
        errors.append("style.artwork_composition_system must specifically describe the collection's visual grammar")
    elif not artwork_composition:
        errors.append("style.artwork_composition_system is required and must be chosen for this collection")
    paper = str(pal.get("paper", ""))
    if HEX.match(paper) and _relative_luminance(paper) < .75:
        errors.append("style.palette.background must be an extremely light grid surface; use dark title/text instead")
    for k in ("paper", "title", "text", "accent", "grid_line"):
        if not HEX.match(str(pal.get(k, ""))):
            name = "background" if k == "paper" else k
            errors.append(f'style.palette.{name} must be a hex color like "#1F3A68"')
    for k in ("title", "text"):
        if HEX.match(str(pal.get(k, ""))) and HEX.match(str(pal.get("paper", ""))):
            if _relative_luminance(str(pal[k])) > .30:
                errors.append(f"style.palette.{k} must be dark because the approved grid background is always light")
            r = contrast_ratio(pal[k], pal["paper"])
            if r < 4.5:
                errors.append(f"style.palette.{k} {pal[k]} vs background {pal['paper']}: contrast {r:.1f}, "
                              f"needs at least 4.5 — make it darker")
    fonts = load_fonts()
    for role in ("title", "body", "numbers"):
        f = (st.get("fonts") or {}).get(role)
        if f not in fonts[role]:
            errors.append(f'style.fonts.{role} "{f}" is not allowed; choose one of: {", ".join(fonts[role])}')

    # --- months ---
    months = c["months"]
    if not isinstance(months, list) or len(months) != 12:
        errors.append(f'"months" must contain exactly 12 items (has {len(months) if isinstance(months, list) else 0})')
        months = months if isinstance(months, list) else []
    ctype = c.get("content_type")
    if ctype not in CONTENT_TYPES:
        errors.append(f"content_type must be one of {sorted(CONTENT_TYPES)}")
    for i, m in enumerate(months):
        p = f"months[{i}]"
        if m.get("month") != i + 1:
            errors.append(f"{p}.month must be {i + 1} (months must be in order Jan..Dec)")
        n = _words(m.get("scene", ""))
        if n < 20 or n > 55:
            errors.append(f"{p}.scene must be 25-45 words (has {n})")
        elif not 25 <= n <= 45:
            warnings.append(f"{p}.scene has {n} words (target 25-45)")
        tie = (m.get("holiday_tie") or "none").strip()
        if tie.lower() != "none":
            found = dates.find_holiday_month(tie, year, market)
            if not found:
                errors.append(f'{p}.holiday_tie "{tie}" is not in FIXED FACTS — use the exact holiday name '
                              f'from FIXED FACTS or "none"')
            elif i + 1 not in found:
                where = ", ".join(dates.MONTH_NAMES[x - 1] for x in found)
                errors.append(f'{p}.holiday_tie "{tie}" falls in {where} {year}, not in '
                              f'{dates.MONTH_NAMES[i]} — move this scene to the correct month or change the tie')
        if not m.get("motif_placement"):
            errors.append(f"{p}.motif_placement is empty (the recurring motif must appear every month)")

        # ảnh phải NÓI được nội dung tháng: có chủ đề, có hình ảnh trọng tâm cụ thể, và cảnh vẽ đúng nó
        if _words(m.get("theme", "")) < 4:
            errors.append(f"{p}.theme must be one sentence saying what this month is about")
        focal = m.get("focal_subject", "")
        if not 3 <= _words(focal) <= 25:
            errors.append(f"{p}.focal_subject must be one concrete, recognizable subject or action (3-25 words)")
        elif _coverage(focal, m.get("scene", "")) < 0.5:
            warnings.append(f'{p}.scene may not clearly show its focal_subject "{focal}"')
        if tie.lower() != "none":
            sym = m.get("holiday_symbol", "")
            if not sym:
                errors.append(f'{p}.holiday_symbol is empty but holiday_tie is "{tie}" — add a recognizable symbol of it')
            elif _coverage(sym, m.get("scene", "")) < 0.5:
                warnings.append(f'{p}.scene may not clearly include its holiday_symbol "{sym}"')
        sub_n = _words(m.get("subtitle", ""))
        if not 2 <= sub_n <= 5:
            errors.append(f"{p}.subtitle must be 2-5 words (has {sub_n})")
        content = m.get("content") or {}
        value = str(content.get("value", "")).strip()
        if ctype == "bible_verse_kjv":
            problem = kjv.check_ref(value)
            if problem:
                errors.append(f"{p}.content.value: {problem}")
            if _words(value) > 6:
                errors.append(f"{p}.content.value must be the reference only, not the verse text")
        elif ctype in ("practical_tip", "fun_fact", "affirmation") and _words(value) > 20:
            errors.append(f"{p}.content.value must be at most 20 words (has {_words(value)})")
        elif ctype != "none" and not value:
            errors.append(f"{p}.content.value is empty")

    # cảnh / hình ảnh trọng tâm trùng nhau
    for i in range(len(months)):
        for j in range(i + 1, len(months)):
            s = _similar(months[i].get("scene", ""), months[j].get("scene", ""))
            if s > 0.55:
                warnings.append(f"months[{i}] and months[{j}] scenes may be too similar ({s:.0%})")
            f = _similar(months[i].get("focal_subject", ""), months[j].get("focal_subject", ""))
            if f > 0.6:
                warnings.append(f"months[{i}] and months[{j}] may have nearly the same focal_subject")

    # --- cover / listing ---
    cov = c["cover"]
    if not 1 <= _words(cov.get("title", "")) <= 5:
        errors.append(f"cover.title must be 1-5 words (has {_words(cov.get('title', ''))})")
    if _words(cov.get("subtitle", "")) > 8:
        errors.append("cover.subtitle must be at most 8 words")
    if not 20 <= _words(cov.get("scene", "")) <= 55:
        errors.append("cover.scene must be 25-45 words")
    lst = c["listing"]
    if len(lst.get("seo_title", "")) > 140:
        errors.append(f"listing.seo_title must be at most 140 characters (has {len(lst['seo_title'])})")
    tags = lst.get("tags") or []
    if len(tags) != 13:
        errors.append(f"listing.tags must have exactly 13 tags (has {len(tags)})")
    for t in tags:
        if len(t) > 20 or t != t.lower():
            errors.append(f'listing tag "{t}" must be lowercase and at most 20 characters')
    if len({t.lower() for t in tags}) != len(tags):
        errors.append("listing.tags contains duplicates")

    errors += _banned_hits(c)
    if ctype == "bible_verse_kjv" and not kjv.has_dataset():
        warnings.append("data/kjv.json chưa có: mới kiểm được tên sách và cú pháp mã câu, chưa kiểm được câu có tồn tại không")
    return errors, warnings
