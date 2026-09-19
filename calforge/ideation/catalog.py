"""Họ style và độ phủ của danh mục sản phẩm: để các cuốn lịch không cuốn nào cũng watercolor."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

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
    for f in projects_root.glob("*/*/concept.json"):
        try:
            fam = json.loads(f.read_text(encoding="utf-8")).get("style", {}).get("family")
        except (OSError, json.JSONDecodeError):
            continue
        if fam:
            counts[fam] += 1
    return counts


def describe_for_prompt(projects_root: Path) -> tuple[str, str]:
    """(danh sách họ style, độ phủ danh mục) dạng chữ để bơm vào P1."""
    lines = [f'- "{f["id"]}": {f["name"]} — {f["description"]}' for f in families()]
    used = usage(projects_root)
    usage_line = ", ".join(f"{k} x{v}" for k, v in used.most_common()) or "(no calendars made yet)"
    return "\n".join(lines), usage_line


def rank_angles(angles: list[dict], projects_root: Path) -> list[dict]:
    """Xếp góc tiếp cận: họ style ít dùng trong danh mục trước, rồi tới điểm AI vẽ được.

    Nhờ vậy chế độ tự chọn không còn luôn nghiêng về watercolor (họ ChatGPT hay chấm điểm cao)."""
    used = usage(projects_root)
    return sorted(angles, key=lambda a: (used.get(a.get("style_family"), 0),
                                         -a.get("ai_feasibility", {}).get("score", 0)))
