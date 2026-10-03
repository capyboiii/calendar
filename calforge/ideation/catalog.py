"""Bốn style sản xuất được duyệt và độ phủ của chúng trong danh mục sản phẩm."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .. import layout

FAMILIES_FILE = Path(__file__).resolve().parents[2] / "data" / "style_families.json"


def families() -> list[dict]:
    return json.loads(FAMILIES_FILE.read_text(encoding="utf-8"))["families"]


def family_ids() -> set[str]:
    return {f["id"] for f in families()}


def family(fid: str) -> dict | None:
    return next((f for f in families() if f["id"] == fid), None)


def usage(projects_root: Path) -> Counter:
    """Số cuốn đã làm theo từng họ style (đọc concept.json trong mọi project)."""
    counts: Counter = Counter()
    for f in (layout.concept_file(b) for b in layout.books(projects_root)):
        try:
            fam = json.loads(f.read_text(encoding="utf-8")).get("style", {}).get("family")
        except (OSError, json.JSONDecodeError):
            continue
        if fam:
            counts[fam] += 1
    return counts


def family_quota(projects_root: Path, n: int) -> dict[str, int]:
    """Chia đều họ style TRONG batch: mỗi họ n // số họ cuốn; phần dư dành cho họ đang ít cuốn nhất
    trong cả danh mục (hoà thì theo thứ tự trong style_families.json). 3 cuốn = mỗi họ 1 cuốn."""
    ids = [f["id"] for f in families()]
    used = usage(projects_root)
    base, rest = divmod(max(0, n), len(ids))
    quota = {fid: base for fid in ids}
    for fid in sorted(ids, key=lambda k: used.get(k, 0))[:rest]:   # sorted giữ thứ tự khi hoà
        quota[fid] += 1
    return {fid: k for fid, k in quota.items() if k}


def recent_visual_systems(projects_root: Path, limit: int = 8) -> list[str]:
    """Dấu vân tay ngắn của các cuốn gần đây, đủ để P1 tránh đổi nhãn nhưng giữ nguyên gu."""
    found: list[str] = []
    paths = sorted(projects_root.rglob("concept.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            concept = json.loads(path.read_text(encoding="utf-8"))
            style = concept.get("style") or {}
        except (OSError, json.JSONDecodeError):
            continue
        parts = [
            f"family={style.get('family', 'unclassified')}",
            f"name={style.get('name', '')}",
            f"surface={style.get('surface_system', '')}",
            f"composition={style.get('artwork_composition_system', '')}",
            f"fingerprint={str(style.get('style_bible', ''))[:240]}",
        ]
        value = "; ".join(parts)
        if value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


def describe_for_prompt(projects_root: Path) -> tuple[str, str]:
    """(danh sách họ style, độ phủ danh mục) dạng chữ để bơm vào P1."""
    lines = [f'- "{f["id"]}": {f["name"]} — {f["description"]}' for f in families()]
    used = usage(projects_root)
    usage_line = ", ".join(f"{k} x{v}" for k, v in used.most_common()) or "(no calendars made yet)"
    return "\n".join(lines), usage_line


def rank_angles(angles: list[dict], projects_root: Path) -> list[dict]:
    """Giữ ngưỡng sản xuất, rồi ưu tiên họ style ít dùng trong nhóm chất lượng cao."""
    used = usage(projects_root)
    return sorted(
        angles,
        key=lambda a: (
            0 if a.get("ai_feasibility", {}).get("score", 0) >= 4 else 1,
            used.get(a.get("style_family", ""), 0),
            -a.get("ai_feasibility", {}).get("score", 0),
        ),
    )


def fingerprint(c: dict) -> dict:
    """Dấu vân tay ngắn của một cuốn (AI viết ở P2); cuốn cũ chưa có thì dựng tạm từ concept."""
    fp = c.get("fingerprint") if isinstance(c.get("fingerprint"), dict) else {}
    months = [str(m) for m in (fp.get("months") or [])]
    if len(months) != 12:
        months = [str(m.get("focal_subject", ""))[:60] for m in c.get("months", [])]   # cuốn cũ: dài hơn nhưng đủ nghĩa
    return {"promise": str(fp.get("promise", "")), "subject_world": str(fp.get("subject_world", "")),
            "months": months}


def portfolio_text(projects_root: Path, keyword: str = "", short_limit: int = 40, title_limit: int = 300) -> str:
    """Danh mục MỌI cuốn đã làm dạng dấu vân tay, để AI tự soi trùng - code không chấm điểm.

    Độ dài có trần: cuốn cùng keyword = 1 dòng đủ (lời hứa, thế giới cảnh, 12 cảnh 2-4 chữ); keyword khác,
    short_limit cuốn gần nhất = 1 dòng ngắn; phần còn lại chỉ còn tên, gộp theo keyword."""
    from .. import layout

    books = []
    for b in layout.books(projects_root):
        try:
            c = json.loads(layout.concept_file(b).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        books.append((layout.concept_file(b).stat().st_mtime, b.parent.name, c))
    if not books:
        return "(none yet)"
    books.sort(key=lambda t: -t[0])
    same = [c for _t, kw, c in books if kw == _slug(keyword)]
    other = [(kw, c) for _t, kw, c in books if kw != _slug(keyword)]

    def head(c: dict) -> str:
        st = c.get("style") or {}
        base = st.get("shared_base_color") or {}
        base = base.get("name", "") if isinstance(base, dict) else base
        return f'"{c.get("title", "")}" | {c.get("frame_type", "")} | {st.get("family", "")} | base {base}'

    lines = []
    if same:
        lines.append(f"Same keyword ({len(same)}):")
        for c in same:
            fp = fingerprint(c)
            extra = "".join(f" | {k}: {fp[f]}" for k, f in (("promise", "promise"), ("world", "subject_world")) if fp[f])
            lines.append(f"- {head(c)} | buyer: {str(c.get('buyer', ''))[:60]}{extra} | months: {'; '.join(fp['months'])}")
    if other:
        lines.append(f"Other keywords ({len(other)}):")
        for kw, c in other[:short_limit]:
            lines.append(f"- [{kw}] {head(c)} | world: {fingerprint(c)['subject_world'] or 'n/a'}")
        rest: dict[str, list[str]] = {}
        for kw, c in other[short_limit:short_limit + title_limit]:
            rest.setdefault(kw, []).append(str(c.get("title", "")))
        for kw, titles in rest.items():
            lines.append(f"- [{kw}] also: {'; '.join(titles)}")
        if len(other) > short_limit + title_limit:
            lines.append(f"- ...and {len(other) - short_limit - title_limit} older calendars")
    return "\n".join(lines)


def _slug(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
