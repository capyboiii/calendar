"""Prompt ảnh do CODE ghép từ concept.json - ChatGPT không tự nghĩ phần này.

Phần giữ đồng bộ (style_bible) và phần ràng buộc in ấn (chủ thể ở giữa, chừa chỗ lỗ treo
và lò xo, không chữ, giấy trơn để tách nền) giống hệt nhau ở mọi tháng; chỉ dòng Scene đổi.
"""
from __future__ import annotations

# Ràng buộc từ template Printify 11x8.5: ảnh 3:2 bị cắt xuống ~1.29 nên chủ thể phải ở giữa;
# giữa mép trên có lỗ treo, mép dưới là lò xo.
COMPOSITION = ("Composition: main subject in the central area, keep the left and right edges simple "
               "(they may be cropped), calm open space at the top center, calm simple bottom edge.")
NO_TEXT = "No text, no letters, no numbers, no border, no frame, no signature, no watermark."
REFERENCE = "Match the art style, color palette and rendering technique of the attached reference image exactly."
# Trang ảnh Printify in tràn kín cả trang -> tranh phải phủ kín khung, không viền giấy trắng
PAPER = "Full-bleed artwork that fills the entire canvas edge to edge: no white margins, no vignette border."


def _scene_block(scene: str, motif: str = "", note: str = "") -> str:
    parts = [f"Scene: {scene.strip()}"]
    if motif:
        parts.append(f"Include subtly: {motif.strip()}")
    if note:
        parts.append(note.strip())
    return " ".join(parts)


def anchor_prompt(concept: dict) -> str:
    """Ảnh neo style: chốt trước, mọi ảnh khác bám theo (dùng luôn làm ảnh bìa nếu đẹp)."""
    st = concept["style"]
    return "\n".join([
        st["style_bible"].strip(),
        "",
        _scene_block(concept["cover"]["scene"], st.get("recurring_motif", "")),
        COMPOSITION,
        PAPER,
        "This image defines the visual style for a 12-month calendar series: make the style "
        "distinctive, consistent and easy to repeat.",
        NO_TEXT,
        "Landscape orientation, 3:2.",
    ])


def month_prompt(concept: dict, month: dict, with_reference: bool = True) -> str:
    """Hình ảnh trọng tâm đứng ĐẦU và được gọi tên rõ: ChatGPT ưu tiên thứ nói trước, và đây là
    thứ làm bức tranh "nói" được nội dung tháng. Thông điệp tháng đi kèm để chọn cảm xúc,
    dặn rõ không viết thành chữ."""
    st = concept["style"]
    lines = [st["style_bible"].strip(), ""]
    if month.get("focal_subject"):
        lines.append(f"Focal point (clearly visible, near the center, the first thing a viewer notices): "
                     f"{month['focal_subject'].strip()}.")
    if month.get("holiday_symbol"):
        lines.append(f"Must include this holiday symbol: {month['holiday_symbol'].strip()}.")
    lines += [
        _scene_block(month["scene"], month.get("motif_placement", ""), month.get("composition_note", "")),
    ]
    if month.get("theme"):
        lines.append(f"The picture should make a viewer feel this, without any written words: {month['theme'].strip()}")
    lines += [COMPOSITION, PAPER]
    if with_reference:
        lines.append(REFERENCE)
    lines += [NO_TEXT, "Landscape orientation, 3:2."]
    return "\n".join(lines)


def ornament_prompt(concept: dict, with_reference: bool = True) -> str:
    st = concept["style"]
    lines = [
        f"A single decorative element: {concept['ornament']['description'].strip()}",
        f"Style: {st['style_bible'].strip()}",
        "Isolated on a fully transparent background (PNG with alpha channel). No background color, "
        "no paper texture behind it, no shadow, no frame.",
    ]
    if with_reference:
        lines.append(REFERENCE)
    lines += ["No text, no letters, no numbers.", "Landscape orientation."]
    return "\n".join(lines)
