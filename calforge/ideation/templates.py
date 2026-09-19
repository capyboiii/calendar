"""Nạp file prompt và điền placeholder {{name}}. Thiếu giá trị nào là báo lỗi ngay, không gửi
prompt còn sót {{...}} sang ChatGPT."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core import dates
from . import catalog

PROMPTS = Path(__file__).parent / "prompts"
FONTS = Path(__file__).resolve().parents[2] / "data" / "fonts.json"
MARKET_LABEL = {"US": "US", "UK": "UK"}

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def render(name: str, **values) -> str:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    missing = sorted({k for k in _PLACEHOLDER.findall(text) if k not in values})
    if missing:
        raise KeyError(f"Prompt {name} thiếu giá trị cho: {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def load_fonts() -> dict[str, list[str]]:
    data = json.loads(FONTS.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def min_families(n: int) -> int:
    """Số họ style tối thiểu trong một lượt P1 (5 góc -> ít nhất 4 họ)."""
    return min(n, 4)


def p1_angles(keyword: str, year: int, market: str, n: int, existing: list[str], projects_root: Path) -> str:
    fams, used = catalog.describe_for_prompt(projects_root)
    return render("p1_angles", keyword=keyword, year=year, market_label=MARKET_LABEL[market], n=n,
                  existing_angles="; ".join(existing) if existing else "(none yet)",
                  style_families=fams, family_usage=used, min_families=min_families(n))


def p2_concept(angle: dict, style: str, year: int, market: str) -> str:
    fonts = load_fonts()
    fam = catalog.family(angle.get("style_family", "")) or {"name": "as described in STYLE DIRECTION",
                                                            "description": style}
    return render("p2_concept", year=year, market_label=MARKET_LABEL[market],
                  calendar_facts=dates.calendar_facts(year, market),
                  fonts_title=", ".join(fonts["title"]), fonts_body=", ".join(fonts["body"]),
                  fonts_numbers=", ".join(fonts["numbers"]),
                  angle_json=json.dumps(angle, ensure_ascii=False, indent=2), style=style,
                  family_name=fam["name"], family_description=fam["description"])


def p3_repair(errors: list[str], previous: dict) -> str:
    # Kèm lại JSON cũ: phiên chat có thể là phiên mới (chạy lại sau khi dừng) nên
    # ChatGPT không còn thấy câu trả lời trước.
    return render("p3_repair", errors="\n".join(f"- {e}" for e in errors),
                  previous_json=json.dumps(previous, ensure_ascii=False, indent=2))
