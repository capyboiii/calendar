"""Grid tự động bám artwork tháng; sáu layout code cũ còn để chọn thủ công."""
from __future__ import annotations

from copy import deepcopy

from .grid_compositions import DEFAULT

PRESETS = ("bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome",
           "organic_capsules", "playful_editorial")
PRESET_LABELS = {
    "art_matched": "AI-designed Grid",
    "bento_planner": "02. Bento Planner",
    "quiet_luxury": "04. Quiet Luxury",
    "soft_tech": "14. Soft-Tech Planner",
    "fresh_monochrome": "18. Fresh Monochrome",
    "organic_capsules": "22. Organic Capsules",
    "playful_editorial": "24. Playful Editorial",
}
FAMILY_HINT = {
    "mid_century_retro": "playful_editorial",
    "papercut_collage": "organic_capsules",
    "styled_photography": "quiet_luxury",
    "anime_illustration": "playful_editorial",
}


def _add(scores: dict, reasons: dict, preset: str, points: int, reason: str) -> None:
    scores[preset] += points
    reasons[preset].append(reason)


def _words(value) -> set[str]:
    if isinstance(value, dict):
        value = " ".join(str(v) for v in value.values())
    return set(str(value or "").lower().replace("-", " ").split())


def recommend_grid(concept: dict) -> dict:
    scores = {p: 0 for p in PRESETS}
    reasons = {p: [] for p in PRESETS}
    style = concept.get("style") or {}
    family = style.get("family")
    content = concept.get("content_type", "none")
    function = concept.get("grid_function", "standard")
    buyer = _words(concept.get("buyer", ""))
    title = str((concept.get("cover") or {}).get("title") or concept.get("title") or "")

    if family in FAMILY_HINT:
        _add(scores, reasons, FAMILY_HINT[family], 4, f"hợp ngôn ngữ hình ảnh {family}")
    if function in {"prayer_list", "tracker", "family_columns"}:
        _add(scores, reasons, "bento_planner", 6, "các khối rõ ràng hợp nội dung cần tổ chức")
        _add(scores, reasons, "soft_tech", 4, "cấu trúc planner hiện đại, dễ quét")
    elif function == "notes_column":
        _add(scores, reasons, "soft_tech", 5, "khoảng viết thoáng và phân khu rõ")
        _add(scores, reasons, "bento_planner", 3, "khối nội dung phụ tách bạch")
    else:
        _add(scores, reasons, "quiet_luxury", 2, "grid tiêu chuẩn cho phép nhiều khoảng thở")
        _add(scores, reasons, "fresh_monochrome", 2, "cấu trúc trung tính, đọc nhanh")

    if content == "bible_verse_kjv":
        _add(scores, reasons, "quiet_luxury", 5, "phân cấp thanh lịch dành chỗ cho câu chữ")
        _add(scores, reasons, "fresh_monochrome", 2, "độ tương phản và nhịp đọc rõ")
    elif content in {"practical_tip", "fun_fact"}:
        _add(scores, reasons, "bento_planner", 4, "nội dung phụ phù hợp card thông tin")
        _add(scores, reasons, "soft_tech", 3, "giao diện thông tin trẻ, thực dụng")
    elif content == "affirmation":
        _add(scores, reasons, "organic_capsules", 4, "hình khối mềm tạo cảm giác thân thiện")
        _add(scores, reasons, "playful_editorial", 3, "headline có cá tính")
    elif content == "none":
        _add(scores, reasons, "fresh_monochrome", 3, "không cần khối nội dung phụ")

    if buyer & {"family", "families", "mother", "mothers", "parent", "parents", "planner"}:
        _add(scores, reasons, "bento_planner", 3, "dễ dùng cho kế hoạch gia đình")
    if buyer & {"young", "student", "students", "teen", "teens", "creative", "traveler", "travellers"}:
        _add(scores, reasons, "playful_editorial", 4, "nhịp editorial trẻ và giàu năng lượng")
        _add(scores, reasons, "soft_tech", 2, "thẩm mỹ giao diện đương đại")
    if buyer & {"designer", "designers", "decor", "premium", "luxury", "collector", "collectors"}:
        _add(scores, reasons, "quiet_luxury", 4, "hợp người mua thiên về decor cao cấp")
    if len(title.split()) >= 6:
        _add(scores, reasons, "quiet_luxury", 2, "tiêu đề dài cần khoảng thở")
        _add(scores, reasons, "playful_editorial", -2, "headline khối hợp tiêu đề ngắn hơn")
    ranked = sorted(PRESETS, key=lambda p: (-scores[p], PRESETS.index(p)))
    selected = ranked[0]
    return {
        "mode": "auto", "selected": selected, "selected_label": PRESET_LABELS[selected],
        "reasons": reasons[selected], "grid_uses_shared_artwork": False,
        "alternatives": [{"preset": p, "label": PRESET_LABELS[p], "score": scores[p],
                          "reasons": reasons[p]} for p in ranked[:2]],
    }


def apply_grid_selection(concept: dict, requested: str | None = None) -> dict:
    from .pages import PRESET_ALIASES
    requested = requested or concept.get("grid_preset")
    if requested and str(requested).lower() != "auto":
        key = str(requested).lower().strip().replace("-", "_").replace(" ", "_")
        selected = PRESET_ALIASES.get(key)
        if not selected:
            raise ValueError(f"Grid preset không hợp lệ: {requested}")
        selection = recommend_grid(concept)
        alternatives = [a for a in selection["alternatives"] if a["preset"] != selected]
        selection.update(mode="manual", selected=selected, selected_label=PRESET_LABELS[selected],
                         reasons=["người dùng chọn khi tạo dự án"],
                         grid_uses_shared_artwork=(selected == "art_matched"))
        selection["alternatives"] = [
            {"preset": selected, "label": PRESET_LABELS[selected], "score": "manual",
             "reasons": ["người dùng chọn khi tạo dự án"]}, *alternatives[:1]]
        concept["grid_preset"] = selected
    else:
        concept.pop("grid_preset", None)
        legacy = recommend_grid(concept)
        selection = {
            "mode": "auto", "selected": "art_matched", "selected_label": PRESET_LABELS["art_matched"],
            "reasons": ["AI thiết kế một nền grid theo art direction của cuốn; code giữ ô và ngày chính xác"],
            "grid_uses_shared_artwork": True,
            "alternatives": [
                {"preset": "art_matched", "label": PRESET_LABELS["art_matched"], "score": "default",
                 "reasons": ["giữ một hệ hình ảnh xuyên suốt 12 tháng"]},
                legacy["alternatives"][0],
            ],
        }
    concept["grid_selection"] = deepcopy(selection)
    style = concept.setdefault("style", {})
    style.pop("grid_decor", None)
    if selection["selected"] == "art_matched":
        style.setdefault("grid_page_mode", "editorial_illustration")
        style.setdefault("grid_composition", DEFAULT)
    return selection
