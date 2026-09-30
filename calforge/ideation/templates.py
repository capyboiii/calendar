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


def p1_angles(keyword: str, year: int, market: str, n: int, existing: list[str], projects_root: Path,
              family: str | None = None, quota: dict[str, int] | None = None) -> str:
    # Chỉ đưa nhãn ngắn để phân loại sau khi AI đã nghĩ art direction; mô tả family
    # chi tiết từng khiến hai nhãn gần nhau kéo artwork về cùng một công thức thị giác.
    labels = ", ".join(f'"{f["id"]}" ({f["name"]})' for f in catalog.families())
    used = catalog.usage(projects_root)
    style_usage = ", ".join(f"{fid} x{count}" for fid, count in used.most_common()) or "none yet"
    systems = catalog.recent_visual_systems(projects_root)
    visual_system_usage = "\n".join(f"- {value}" for value in systems) or "- none yet"
    selected = catalog.family(family) if family else None
    required_style = (
        f'REQUIRED PRODUCTION STYLE: use exactly style_family "{family}" ({selected["name"]}) for EVERY angle. '
        "The art_direction must explicitly and visibly use this rendering method; do not return another family."
        if selected else
        ("REQUIRED STYLE SPLIT (fixed by the shop so styles stay balanced): return exactly these style_family "
         "counts - " + ", ".join(f'"{fid}" ({catalog.family(fid)["name"]}): {k} angle(s)' for fid, k in quota.items())
         + ". For each angle, build the art_direction inside its assigned family from the start."
         if quota else
         "STYLE SELECTION: choose exactly one family from the approved list for each angle.")
    )
    return render("p1_angles", keyword=keyword, year=year, market_label=MARKET_LABEL[market], n=n,
                  existing_angles="; ".join(existing) if existing else "(none yet)",
                  style_labels=labels, style_usage=style_usage,
                  recent_visual_systems=visual_system_usage, required_style=required_style,
                  portfolio=catalog.portfolio_text(projects_root, keyword))


def p1b_review(keyword: str, n: int, candidates: list[dict], projects_root: Path,
               quota: dict[str, int] | None = None) -> str:
    """Lượt chat RIÊNG làm người thẩm định: AI (không phải code) quyết định ý nào trùng danh mục."""
    keys = ("id", "title", "hook", "buyer", "frame_type", "why_different", "months_sketch", "art_direction",
            "style_family", "buyer_expectation")
    view = [{k: a.get(k) for k in keys} for a in candidates]
    split = ("STYLE SPLIT (fixed by the shop): \"selected\" must contain at most "
             + ", ".join(f'{k} with style_family "{fid}"' for fid, k in quota.items())
             + " - prioritize keyword fit and buyer appeal, then variety, within each style." if quota else "")
    return render("p1b_review", keyword=keyword, n=n, portfolio=catalog.portfolio_text(projects_root, keyword),
                  style_split=split,
                  candidates=json.dumps(view, ensure_ascii=False, indent=1))


def p2_concept(angle: dict, style: str, year: int, market: str,
               grid_composition_usage: str = "none yet", base_tone_rule: str = "") -> str:
    from ..imagegen import shots

    fonts = load_fonts()
    fam = catalog.family(angle.get("style_family", "")) or {"name": "unclassified"}
    return render("p2_concept", year=year, market_label=MARKET_LABEL[market],
                  calendar_facts=dates.calendar_facts(year, market),
                  fonts_title=", ".join(fonts["title"]), fonts_body=", ".join(fonts["body"]),
                  fonts_numbers=", ".join(fonts["numbers"]),
                  angle_json=json.dumps(angle, ensure_ascii=False, indent=2), style=style,
                  family_name=fam["name"], grid_composition_usage=grid_composition_usage,
                  base_tone_rule=base_tone_rule or "Choose the base tone that best suits the art.",
                  month_shots=shots.describe(str(angle.get("title", "")), str(angle.get("frame_type", ""))))


def p3_repair(errors: list[str], previous: dict, *, include_previous: bool = True) -> str:
    """Prompt sửa ngắn trong cùng phiên; kèm JSON gọn khi đang resume từ cache."""
    if include_previous:
        previous_block = ("Here is the JSON to correct (your previous answer):\n"
                          "```json\n"
                          + json.dumps(previous, ensure_ascii=False, separators=(",", ":"))
                          + "\n```")
    else:
        previous_block = "Use the JSON from your immediately previous answer; do not rewrite unrelated fields."
    return render("p3_repair", errors="\n".join(f"- {e}" for e in errors),
                  previous_block=previous_block)
