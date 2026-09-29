"""Prompt ảnh do CODE ghép từ concept.json - ChatGPT không tự nghĩ phần này.

Phần giữ đồng bộ (style_bible) và phần ràng buộc in ấn giống hệt nhau ở mọi tháng.
Front cover là một job riêng: AI tự thiết kế typography hòa vào artwork.
"""
from __future__ import annotations

import re

from . import shots


# Ràng buộc kỹ thuật từ template Printify 11x8.5. Đây chỉ là vùng an toàn, không phải
# công thức bố cục: art direction của từng cuốn được phép lệch tâm, cắt gần, toàn cảnh...
PRINT_SAFETY = ("Print safety only: keep indispensable content inside the central 80% horizontal area "
                "and clear of the top and bottom binding hardware. Background and subordinate decoration "
                "may bleed and crop. Do not interpret this safety rule as a request to center the composition.")
# Bìa: chữ căn giữa theo luật riêng ở trên, nên bỏ câu "đừng hiểu là yêu cầu căn giữa".
COVER_PRINT_SAFETY = ("Print safety only: keep the artwork's indispensable content inside the central 80% horizontal "
                      "area and clear of the top and bottom binding hardware. Background and subordinate decoration "
                      "may bleed and crop.")
ARTWORK_FINISH = "No border, no frame, no signature, no watermark."
REFERENCE = ("The attached reference image is a COLOR AND TEXTURE SWATCH of this collection, not a scene: the top "
             "bands show the palette in its proportions, the bottom patches show the medium and mark-making. "
             "Match those colors, proportions and rendering exactly; take the composition only from this prompt.")
# Trang ảnh Printify in tràn kín cả trang -> tranh phải phủ kín khung, không viền giấy trắng
# Câu đầu tiên của mọi prompt ảnh: bảo thẳng là TẠO ẢNH MỚI. Thiếu câu này, prompt mở đầu bằng
# "Render as..." bị ChatGPT hiểu là việc sửa ảnh và hỏi lại "ảnh tham chiếu đâu" thay vì vẽ.
# Không nhắc tới "source image", "attached", "edit": các chữ đó làm công cụ vẽ của ChatGPT chuyển nhầm
# sang chế độ sửa ảnh rồi đòi ảnh gốc.
CREATE_NEW = "Generate a new image from this text description now, without asking any questions."
CREATE_WITH_SWATCH = ("Generate a new image from this text description now, without asking any questions. "
                      "Use the swatch in this message only as a color and texture guide.")


def _opener(with_reference: bool) -> str:
    return CREATE_WITH_SWATCH if with_reference else CREATE_NEW


PAPER = "Full-bleed artwork that fills the entire canvas edge to edge: no white margins, no vignette border."


def _scene_block(scene: str, motif: str = "", note: str = "") -> str:
    parts = [f"Scene: {scene.strip()}"]
    if motif:
        parts.append(f"Include subtly: {motif.strip()}")
    if note:
        parts.append(note.strip())
    return " ".join(parts)


def _single_motif(motif: str) -> str:
    """Motif cho ảnh đơn lẻ (anchor, cover): bỏ vế nói về "mỗi tháng" vốn viết cho cả bộ 12 ảnh.

    Vd "a tiny gold star, free to sit in a different place each month" -> "a tiny gold star (one small instance)".
    """
    text = (motif or "").strip().rstrip(".")
    # vế "mỗi tháng" bắt đầu sau dấu phẩy/chấm phẩy hoặc một từ nối/động từ đặt để, kéo tới hết câu
    starter = r"(?:[,;]|\b(?:and|while|but|placed|tucked|positioned|repositioned|moved|free|appearing|hidden)\b)"
    per_month = r"(?:\b(?:each|every)\s+month|\bmonthly\b|\bdifferent\s+(?:place|part|location|spot)\b)"
    cut = re.search(starter + r"[^,;]*?" + per_month, text, re.I)
    if cut:
        text = text[:cut.start()].rstrip(" ,;")
    elif re.search(per_month, text, re.I):
        return text
    return f"{text} (one small instance)" if text else text


def _composition_system(style: dict) -> str:
    return str(style.get("artwork_composition_system") or (
        "Keep the collection's color placement, light and edge handling consistent from image to image."
    )).strip()


def _shared_base(style: dict) -> tuple[str, str]:
    """One collection-wide ground color, chosen once during art direction."""
    value = style.get("shared_base_color") or {}
    if isinstance(value, dict):
        name = str(value.get("name") or "collection base").strip()
        color = str(value.get("hex") or "").strip()
    else:  # legacy concepts may carry a plain name
        name, color = str(value).strip() or "collection base", ""
    if not color:
        color = str((style.get("palette") or {}).get("paper") or "").strip()
    return name, color


def _artwork_base_rule(style: dict) -> str:
    name, color = _shared_base(style)
    swatch = f" ({color})" if color else ""
    return (
        f"COLLECTION COLOR ANCHOR: use {name}{swatch} as the shared ground/surface color across the cover "
        "and all 12 monthly artworks, covering roughly one third of each image, not the whole page; subjects in "
        "the other palette colors fill the rest. Do not rotate the background among palette colors."
    )


def _artwork_lightness_rule(style: dict) -> str:
    """Giữ không khí tích cực cho cả bộ; không bắt nền nhạt, medium vẫn do style family quyết định."""
    family = str(style.get("family") or "").strip()
    common = (
        "POSITIVE COLLECTION MOOD: every image should feel positive, warm and welcoming at thumbnail size, with "
        "clear, readable lighting. Mid-tones and rich color are welcome; the image does not need to be pale or "
        "high-key. Avoid gloomy, murky or somber results: no night scene as the main lighting, heavy vignette or "
        "dark cinematic grading."
    )
    if family == "styled_photography":
        return common + (
            " For styled photography, use natural daylight (morning, midday or golden afternoon); no night scene, "
            "dark room or candle-lit low-key setup."
        )
    if family == "papercut_collage":
        return common + " For layered papercut, keep cast shadows gentle so the layers never read heavy."
    if family == "mid_century_retro":
        return common + (" For mid-century poster, use crisp sunlit color blocking; deep inks suit outlines and "
                         "graphic accents.")
    return common


def _grid_tone_rule(palette: dict) -> str:
    return (
        "MANDATORY LIGHTNESS: the approved workflow always uses dark software title/body text. The grid surface "
        "must therefore be a LIGHT pastel tint of the shared base: about 15–25% base-color strength, roughly "
        "88–93% perceived lightness, with strong text contrast. The hue must stay clearly recognizable (a blush "
        "base reads as soft pink, sage as soft green, sky as soft blue), never bleached to near-white or a washed-out "
        "neutral, and never a midtone painted field. Do not "
        "output a medium, deep, dark, jewel-tone or near-original-strength version of the base color."
    )


def _grid_text_rule(palette: dict) -> str:
    """Concept mới luôn dùng chữ tối; concept cũ được mô tả theo hành vi normalize của renderer."""
    values = [str(palette.get(key, "#111111")) for key in ("title", "text")]
    try:
        luminances = []
        for value in values:
            rgb = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
            luminances.append(linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722)
    except (TypeError, ValueError):
        luminances = [1.0, 1.0]
    if max(luminances) <= .30:
        return (
            f"Software text colors are dark: title {values[0]} and body {values[1]}. Keep every software writing "
            "zone strongly readable against these colors."
        )
    return (
        "This legacy concept contains light title/body color values, but the renderer will replace them with dark "
        "collection-matched text before printing. Design only for dark software text on a very light surface; do "
        "not preserve or design around the obsolete light text values."
    )


def anchor_prompt(concept: dict) -> str:
    """Ảnh neo style sạch, không chữ; mọi ảnh tháng và cover riêng bám theo."""
    st = concept["style"]
    return "\n".join([
        CREATE_NEW,
        st["style_bible"].strip(),
        _artwork_base_rule(st),
        _artwork_lightness_rule(st),
        "",
        _scene_block(concept["cover"]["scene"], _single_motif(st.get("recurring_motif", ""))),
        f"Collection visual rhythm (shared look, not a fixed camera setup): {_composition_system(st)}",
        PRINT_SAFETY,
        PAPER,
        "The image you create will set the visual style for a 12-month calendar series: make the style "
        "distinctive, consistent and easy to repeat.",
        ARTWORK_FINISH,
        "Landscape orientation, 3:2.",
    ])


def _without_year(text: str, year: str) -> str:
    """Bỏ năm khỏi tên/phụ đề bìa: năm được yêu cầu in riêng một lần, để trong tên nữa là in hai lần."""
    cleaned = re.sub(rf"\s*(?:for|in)?\s*\b{re.escape(year)}\b", "", text.strip(), flags=re.IGNORECASE)
    return cleaned.strip(" -–—,:·|").strip() or text.strip()


def cover_prompt(concept: dict, with_reference: bool = True) -> str:
    """Bìa hoàn chỉnh do AI art-direct, gồm cả title/year/subtitle trong chính artwork."""
    st = concept["style"]
    cov = concept["cover"]
    year = str(concept["year"])
    title = _without_year(str(cov["title"]), year)
    subtitle = _without_year(str(cov.get("subtitle", "")), year)
    lines = [
        _opener(with_reference),
        st["style_bible"].strip(),
        _artwork_base_rule(st),
        _artwork_lightness_rule(st),
        "",
        "Create a complete premium wall-calendar FRONT COVER, not a plain illustration with text added later.",
        f'Render this exact title once, spelled exactly: "{title}".',
        f'Render this exact year once: "{year}".',
    ]
    if subtitle:
        lines.append(f'Render this exact subtitle once, spelled exactly: "{subtitle}".')
    lines += [
        "Art-direct the lettering yourself: choose typography, scale, hierarchy, color and placement that feel "
        "native to the artwork. Integrate the title into the composition using light, negative space, shapes or "
        "texture from the scene; it must not look like a software text overlay or a detached label.",
        "Make the lettering readable through composition and color alone: leave a naturally calm area of the scene "
        "(open sky, still water, plain ground) where the title sits, and choose letter colors with strong contrast "
        "against it. Do NOT add any haze, glow, fog, white wash, blurred band, gradient panel, box, banner, ribbon "
        "or shape behind the text - the scene must continue unaltered behind the letters.",
        "The required words must remain immediately readable at thumbnail size. CENTER the whole title block "
        "horizontally: the print crops about 10% off the left and right edges, so every letter must sit between "
        "15% and 85% of the canvas width, never pushed toward one side. Keep lettering away from the top binding "
        "strip and the bottom-center hanging hole.",
        _scene_block(cov["scene"], _single_motif(st.get("recurring_motif", ""))),
        f"Collection visual rhythm (shared look, not a fixed camera setup): {_composition_system(st)}",
        COVER_PRINT_SAFETY,
        PAPER,
    ]
    if with_reference:
        lines.append(REFERENCE)
    lines += [
        "No signature, no watermark, no mockup and no separate border.",
        "Landscape orientation, 3:2.",
    ]
    return "\n".join(lines)


def month_prompt(concept: dict, month: dict, with_reference: bool = True) -> str:
    """Hình ảnh trọng tâm đứng ĐẦU và được gọi tên rõ: ChatGPT ưu tiên thứ nói trước, và đây là
    thứ làm bức tranh "nói" được nội dung tháng. Thông điệp tháng đi kèm để chọn cảm xúc,
    dặn rõ không viết thành chữ."""
    st = concept["style"]
    lines = [_opener(with_reference), st["style_bible"].strip(), _artwork_base_rule(st),
             _artwork_lightness_rule(st), ""]
    if month.get("focal_subject"):
        lines.append(f"Focal point (clearly visible and the first thing a viewer notices; it may be off-center): "
                     f"{month['focal_subject'].strip()}.")
    lines.append(f'This calendar is "{str(concept.get("title", "")).strip()}": the picture must read as part of '
                 "that theme, not as a generic seasonal or holiday image.")
    lines += [
        f"Shot type for this month: {shots.SHOTS[shots.month_shot(concept, month)]}",
        _scene_block(month["scene"], month.get("motif_placement", ""), month.get("composition_note", "")),
    ]
    if month.get("theme"):
        lines.append(f"The picture should make a viewer feel this, without any written words: {month['theme'].strip()}")
    lines += [
        f"Collection visual rhythm (shared look, not a fixed camera setup): {_composition_system(st)}",
        PRINT_SAFETY,
        PAPER,
    ]
    if with_reference:
        lines.append(REFERENCE)
    lines += [ARTWORK_FINISH, "Landscape orientation, 3:2."]
    return "\n".join(lines)


# Chất liệu nền grid: code chia đều (cuốn mới lấy loại đang ít cuốn dùng nhất), AI chỉ vẽ đúng loại đó.
GRID_MATERIALS = {
    "watercolor": "fine cold-press watercolor paper with soft, pale watercolor blooms and gentle granulation",
    "handmade": "handmade cotton-rag paper with visible embedded fibers, soft uneven tooth and tiny natural flecks",
    "laid": "vintage laid writing paper with fine horizontal laid lines and faint vertical chain lines",
}


def grid_material(concept: dict) -> str:
    """Chất liệu đã khoá trong concept; cuốn cũ chưa có thì mặc định theo tên cuốn (cố định, không đổi qua lại)."""
    key = (concept.get("style") or {}).get("grid_material")
    if key in GRID_MATERIALS:
        return key
    import hashlib
    keys = list(GRID_MATERIALS)
    return keys[int(hashlib.sha1(str(concept.get("title", "")).encode("utf-8")).hexdigest(), 16) % len(keys)]


# Giấy không phải màu nước: AI hay tự thêm vệt loang/ố ở góc (theo thói quen + ảnh tham chiếu) -> cấm rõ.
_DRY_PAPER = ("This is DRY, UNPAINTED paper: absolutely no watercolor washes, paint blooms, stains, tide lines, "
              "splotches, cloudy patches or darker corners anywhere. The color is one flat, even tint across the "
              "whole sheet; only the paper's own structure ({what}) creates the texture, evenly from edge to edge.")


def _material_rule(key: str) -> str:
    rule = (f"PAPER MATERIAL (fixed for this collection, overrides any other material idea, surface system or "
            f"reference image): {GRID_MATERIALS[key]}. Make this material clearly visible and tactile but soft and "
            "low-contrast.")
    if key == "watercolor":
        return rule + (" Any washes stay pale, soft and mostly near the outer edges, never crossing the central "
                       "writing area.")
    what = {"handmade": "fibers, flecks and uneven tooth", "laid": "fine laid and chain lines"}[key]
    return rule + " " + _DRY_PAPER.format(what=what)


def next_grid_material(projects_root) -> str:
    """Chia đều: loại giấy đang ít cuốn dùng nhất trong cả danh mục (hoà thì theo thứ tự GRID_MATERIALS).
    Batch 3 cuốn liên tiếp vì thế ra đủ 3 loại khác nhau."""
    import json
    from .. import layout
    counts = {k: 0 for k in GRID_MATERIALS}
    for b in layout.books(projects_root):
        try:
            key = (json.loads(layout.concept_file(b).read_text(encoding="utf-8")).get("style") or {}).get("grid_material")
        except (OSError, ValueError):
            continue
        if key in counts:
            counts[key] += 1
    return min(counts, key=lambda k: counts[k])


def grid_background_prompt(concept: dict, month: dict | None = None, with_reference: bool = True) -> str:
    """AI thiết kế một nền grid dùng chung; code thay chữ và lịch cho 12 tháng."""
    st = concept["style"]
    palette = st.get("palette", {})
    surface_system = st.get("surface_system", "").strip().rstrip(".")
    base_name, base_hex = _shared_base(st)
    base_swatch = f" ({base_hex})" if base_hex else ""
    lines = [
        "Create ONE shared calendar-page BACKGROUND that will be reused unchanged behind all 12 monthly grids in this collection.",
        f"Collection: {str(concept['title']).strip().rstrip('.')}.",
        f"Buyer: {str(concept.get('buyer', '')).strip().rstrip('.')}.",
        (f"Chosen collection surface system: {surface_system}. Preserve its hue relationships and material language, "
         "but translate it into a quieter, lower-chroma calendar companion; do not copy the artwork's color intensity."
         if surface_system else
         "Infer and commit to one collection-specific surface system from the buyer and attached art direction."),
        _material_rule(grid_material(concept)),
        _grid_text_rule(palette),
        _grid_tone_rule(palette),
        (f"SHARED COLLECTION BASE: the artwork series uses {base_name}{base_swatch} as its single dominant ground. "
         "Use a lighter, softer tint of this exact hue family as the grid's dominant surface, keeping the hue "
         "recognizable. Do not "
         "choose another palette color merely because it appears strongly in the reference artwork."),
        ("The attached collection artwork is a STYLE REFERENCE. Make this background harmonize with the whole "
         "12-artwork collection through palette, graphic vocabulary, medium and surface character. Do not copy "
         "its subject, scene, objects, characters or composition. If the reference is representational, extract "
         "only its color relationships, edge language, mark texture and shape vocabulary."
         if with_reference else
         "Use the collection art direction below for palette, graphic vocabulary, medium and print texture."),
        ("GRID COLOR INTENSITY: use light, softened tints at roughly 15–25% of the "
         "facing artwork's perceived color intensity. Preserve the collection's hue identity: the page must read as "
         "the shared base hue, not as white or a washed-out neutral. Never fill the page with full-strength primary color, neon color, "
         "luminous yellow, vivid red, electric blue or another high-chroma field—even when the artwork or surface "
         "system is intentionally saturated. Do not introduce accent motifs or focal decorations. Use only light "
         "softened tones suitable for dark software text."),
        ("STRICT COLOR HIERARCHY: the shared collection base named above must occupy at least 85% of the page. Use only "
         "one or two companion hues, together occupying no more than 15%, and keep them close in value and low in "
         "chroma. Companion hues must appear only as " + ("faint blended undertones or very small peripheral traces"
         if grid_material(concept) == "watercolor" else "tiny colored fibers or flecks inside the paper") + "—not "
         "as large blocks, stripes, opposing corner fields or separate focal areas. No rainbow palette, patchwork, "
         "four-color perimeter, color wheel effect or equally weighted multicolor composition."),
        ("Build one restrained, continuous full-bleed surface that belongs to this collection and works equally "
         "well beside January through December artwork. Do not introduce a season, month, holiday, weather, time "
         "of day or narrative moment."),
        ("THIS IS A FLAT SURFACE DESIGN, NOT AN ARTWORK PAGE. No landscape, scenery, environment, horizon, sky, "
         "ground plane, room, foreground/background staging, perspective depth or view through an opening. Interpret "
         "any atmospheric or layered surface instruction abstractly, as subtle tonal fields or shallow graphic layers."),
        ("Keep the entire page quiet, low-detail and high-contrast for software text and rules. The title and copy "
         "placement is handled by software, so do not reserve or decorate a title corner."),
        ("NO DECORATIVE MOTIFS OR OBJECTS ANYWHERE. No leaves, flowers, produce, animals, icons, symbols, corner "
         "clusters, edge flourishes, spots, confetti, brush-mark accents or illustrative fragments. No concentric "
         "edge bands, mountain-like bands, faux mat, frame or border around the writing area."),
        ("TEXT-ZONE CONTRAST OVERRIDES THE SURFACE SYSTEM. Across the central calendar-writing region "
         "(x=8–92%, y=27–94%), use one near-uniform light tone that clearly contrasts with the dark software text "
         "described above. Do not let dark/light bands, layered collage shapes, gradients or texture clusters "
         "cross this region. Any stronger tonal treatment must remain subtle and outside it."),
        ("Let only the selected surface, restrained palette, the paper material above and negative space carry "
         "the design. The grid "
         "background must remain visibly subordinate to all 12 facing artworks and must not compete with them. "
         "No frame, inset card, boxed illustration, decorative border, panel or extra composition."),
        "Do not draw calendar geometry or content: no grid lines, table, boxes, checkerboard, rows, "
         "columns, weekday strip, month title, dates, letters, numerals, pseudo-text, or watermark. "
         "Software will overprint the exact 7-column grid, natural 4/5/6 rows, all dates and words.",
        "Flat landscape 3:2 page, full bleed, no mockup perspective. Generate the image directly.",
    ]
    lines.insert(0, CREATE_NEW)
    if not with_reference:
        lines.insert(5, f"Art direction to match: {st['style_bible'].strip()}")
        lines.insert(6, f"Collection palette: {st.get('color_story', '')}.")
    return "\n".join(lines)
