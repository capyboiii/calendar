"""Prompt của luồng "Làm theo ảnh mẫu". Hai prompt artwork được duyệt lại ngày 08/10/2026.
Code điền phân công ảnh mẫu, số ảnh còn thiếu và dữ kiện lịch theo năm."""
from __future__ import annotations

import calendar
import datetime as dt

from ..core import dates

MONTHS = dates.MONTH_NAMES
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ------------------------------------------------------------------ 12 artwork (phiên 1, tài khoản A)
# Artwork prompts approved on 2026-10-08; reference assignments are filled dynamically.
ARTWORK_TEXT_RULES = """TEXT ON THE ARTWORK
UNDERSTAND THE REFERENCES BEFORE DECIDING ABOUT TEXT

Study all attached references together. Infer the intended visual language of the monthly artworks, distinguishing the artwork itself from the calendar, cover, packaging or promotional presentation around it.

Decide whether text is an essential part of each assigned artwork by its meaning, placement and role in the reference collection. Do not assume that every visible word should be reproduced, or that all artworks should contain text because one reference does.

If a reference is a cover or product mockup, extract its underlying artwork. Exclude text serving as the product title, cover headline, year, calendar label, branding or sales information. Do not turn that excluded text into a new phrase.

Preserve meaningful text that is genuinely part of the artwork's creative content, such as scripture, prayers, quotations or illustrated messages—even when that artwork is presented on a cover. When both artwork text and product text appear, retain only the artwork text.

Use the other references to resolve ambiguity. If the interior artworks are text-free and lettering appears only as a cover headline, keep the monthly artworks free of added text. If the collection incorporates meaningful lettering into its artworks, preserve that approach only where supported by the assigned reference.

For KEEP artworks, reproduce the integral artwork text exactly, preserving its spelling, punctuation, line breaks and scripture citation when present. Never borrow text from another reference. If two KEEP references contain the same integral text, preserve it but make their scenes clearly different.
For NEW-concept artworks, choose a different text of the same kind that fits the new concept. Do not repeat any text from the references or other artworks. Scripture and attributed quotations must be authentic and accurately cited; do not invent or misattribute them.
If no integral artwork text is supported by the reference, add none.

When integral artwork text is required, preserve its typography style, color and hierarchy, with highly legible placement. Exclude calendar dates, month names, weekdays and the calendar year used as product labels; scripture citation numbers are permitted.

Apply this interpretation consistently whenever a reference is reused, including Artworks 11 and 12. Before rendering each image, check that any proposed lettering belongs to the artwork rather than to the source product's presentation."""

ART_RULES_T = """I have attached reference images. These are visual references, NOT images to edit. Create new artworks from scratch. Do not retouch or make minor variations of the attached images.

REFERENCE FORMAT
Some references are plain artworks. Others are calendar pages or product mockups containing artwork.

Study ONLY the artwork area of each reference. Ignore date grids, numbers, month names, weekdays, year, spiral binding, hanging holes, paper edges, white margins, frames, walls, tables, hands and mockup backgrounds.

STUDY THE WHOLE SET BEFORE GENERATING
Silently examine ALL attached references first.

Identify:
- the overall theme and visual world
- the subjects and scenes already represented
- references that repeat the same subject or similar composition
- the distinctive artistic style, rendering technique, stroke quality, texture and color tone of each reference
- any text that belongs to the artwork itself

Then silently plan 12 distinct artwork ideas before generating any images. Do not output the plan or any written analysis.

REFERENCE ASSIGNMENT
Each artwork must follow its assigned reference for artistic style, rendering technique, stroke quality, texture and color tone.

Do not blend different reference styles into a hybrid style. If the references share one style, keep that style consistent throughout the collection.

{plan}

KEEP ARTWORKS
Preserve the recognizable identity, appearance, characteristic colors, materials and important details of the assigned reference's subject.

Create a genuinely different scene around that subject: a new action, interaction, narrative moment or meaningful arrangement, with a clearly different overall composition.

Do not copy the reference's pose and arrangement into a different background.

If two references depict the same subject, their KEEP artworks must show clearly different situations and visual stories. Preserve each reference's own style and only its integral artwork text, as determined by the TEXT ON THE ARTWORK rules below.

NEW-CONCEPT ARTWORKS
Use the assigned reference as a guide to style and theme, then invent a new central idea that is not already represented by the reference set or another planned artwork.

When the theme allows multiple subjects, introduce a different relevant subject, interaction or meaningful arrangement that naturally belongs in the same collection.

When the collection centers on one specific recurring figure or subject, keep that identity consistent, but invent a substantially different action, situation or narrative moment. Do not introduce unrelated subjects merely to create variety.

Limited reference material is not a reason to repeat an image. Develop additional ideas from the theme while preserving the assigned reference's artistic style and visual quality.

WHAT COUNTS AS A DISTINCT ARTWORK
Every artwork must have its own central visual idea and clearly different composition.

The following changes ALONE are NOT enough:
- changing only the background or location
- changing only the camera angle, crop or zoom
- mirroring the image
- changing only the lighting, color or time of day
- making a small change to the pose
- replacing a minor prop
- changing only the text

Do not reuse the same central arrangement or near-identical silhouette across the collection.

For static subjects, create meaningful variety through the main arrangement, relationships between elements and visual emphasis, rather than forcing an inappropriate action.

{artwork_text_rules}

COMPOSITION AND BACKGROUND
Choose the composition, camera angle and environment freely for each artwork, as appropriate to its subject and theme.

Vary the visual storytelling across the set. Each background must support that artwork's distinct idea, rather than serve as the only difference between repeated subjects and arrangements.

Do not impose a fixed season, location or mood unless it is essential to the reference's subject.

FINAL CHECK BEFORE EACH IMAGE
Silently compare the planned image with all references, the other planned concepts and the artworks already generated in this conversation.

If it repeats another artwork's central idea or composition, revise the idea before generating.
Check that its assigned reference's style and text rules are still respected."""

ART_OUTPUT = """OUTPUT FOR THIS TURN
- Generate ONLY Artwork 1 through Artwork 10, in that exact order.
- Keep Artwork 11 and Artwork 12 planned for the next request; do not generate them yet.
- Output 10 SEPARATE images, one finished artwork per image.
- No written reply, explanations, captions or artwork-number labels.
- Never combine artworks into a grid, collage, contact sheet or split-panel image.
- Each image must be landscape 4:3, full bleed, with one finished artwork filling the frame.
- No calendar elements, spiral binding, paper edges, borders, frames, mockup backgrounds, watermarks or logos.
- Required artwork text is allowed only under the TEXT ON THE ARTWORK rules above."""



def art_plan(n_refs: int) -> str:
    """Bảng phân công 12 artwork: artwork i theo ảnh mẫu ((i-1) mod n)+1. Lần đầu dùng một ảnh mẫu thì GIỮ chủ thể;
    các lần sau (ảnh mẫu ít hơn 12) ChatGPT phải tự nghĩ chủ thể MỚI cùng chủ đề - tránh 12 tranh lặp một thứ."""
    n = max(1, int(n_refs))
    lines = ["ARTWORK PLAN:"]
    for i in range(1, 13):
        kind = "KEEP its subject" if i <= n else "NEW concept within the same theme"
        lines.append(f"- Artwork {i}: reference {(i - 1) % n + 1} — {kind}")
    return "\n".join(lines)


def art_rules(n_refs: int) -> str:
    return ART_RULES_T.replace("{plan}", art_plan(n_refs)).replace("{artwork_text_rules}", ARTWORK_TEXT_RULES)


def art_prompt(n_refs: int) -> str:
    return art_rules(n_refs) + "\n\n" + ART_OUTPUT

# Artwork 11-12: không ép bố cục / mùa / không khí cố định (người dùng bỏ "snowy winter", "end-of-year" 08/10/2026) -
# ChatGPT tự chọn, chỉ cần khác hẳn 10 artwork trước và khác nhau.
ART_EXTRA = """  • Artwork 11 and Artwork 12: choose the composition, camera angle and background yourself, freely. Each must be clearly different from artworks 1–10 and from each other. No forced season, theme or mood."""

ART_CONTINUE = """Continue the same collection. Generate ONLY Artwork 11 and Artwork 12 from the 12-artwork plan established earlier.

Artworks 1–10 are already complete. Do not regenerate, replace or repeat any of them.

REFERENCE ASSIGNMENT
- Artwork 11: reference {ref11} — NEW concept within the same theme.
- Artwork 12: reference {ref12} — NEW concept within the same theme.

Follow ALL the original rules for reference interpretation, artistic style, distinct concepts, composition and artwork text.

COLLECTION COLOR AND MATERIAL LOCK
Treat the completed Artworks 1–10 as the visual color master for these two images. Silently compare them as a collection before generating: identify the established palette, saturation, warm/cool balance, brightness, contrast, highlight and shadow colors, and material finish. Match those properties in both new artworks.

Use the dominant, consistent treatment across the collection; do not copy an accidental color outlier. If the collection intentionally uses multiple palettes, follow the completed artworks based on the same assigned reference. The original reference guides subject and technique, but must not reintroduce colors absent from that established treatment.

If the completed collection is monochrome or near-monochrome, keep BOTH new images within that same restricted palette across the entire scene, including skin, clothing, foliage, flowers, sky, architecture and distant scenery. Do not restore the objects' natural colors. For example, an ivory/cream/sepia collection must keep leaves, skies and garments in those same ivory/cream/sepia tones, without new green foliage, blue skies, blue-gray clothing or pink skin. This example applies only when that is the actual collection palette; do not impose it on other collections.

Preserve the established material language as well: carved relief, stone, paper, paint or photography must retain the same finish and depth treatment. Do not turn a sculpted monochrome collection into naturally colored, lifelike scenes.

Create variety through subject, action, narrative and composition while keeping the palette and rendering consistent. A new concept, setting, time of day or mood is not permission to change the color grading, saturation or lighting contrast.

DEVELOP TWO DISTINCT IDEAS
Review the 10 artworks already generated and the original references before generating.

Use the two ideas reserved for Artwork 11 and Artwork 12. If either idea now resembles an artwork already generated, revise it into a clearly different concept.

Each new artwork must:
- preserve its assigned reference's artistic style, rendering technique, stroke quality and texture, with color tone and material finish governed by the COLLECTION COLOR AND MATERIAL LOCK above
- belong naturally to the same theme and visual world
- have a central visual idea and overall composition clearly different from Artworks 1–10
- be clearly different from the other new artwork

When the theme allows multiple subjects, introduce a different relevant subject, interaction or meaningful arrangement.

If the collection centers on one recurring figure or subject, preserve that identity but create a substantially different action, situation or narrative moment. Do not add unrelated subjects merely to create variety.

Changing only the background, camera angle, crop, lighting, color, a minor prop or a small pose detail is NOT enough.

COMPOSITION AND BACKGROUND
Choose the composition, camera angle, environment and mood freely to suit each new concept, within the locked collection palette, tonal range and material treatment.

Do not automatically make these images winter scenes or end-of-year scenes because they are Artwork 11 and Artwork 12. No forced season or mood.

{artwork_text_rules}

Artworks 11 and 12 are NEW-concept artworks. Apply the NEW-concept text rules above to each assigned reference; their integral messages, if any, must differ from each other and from Artworks 1–10. Do not perpetuate cover/product lettering accidentally generated in earlier artworks.

FINAL CHECK
Before generating, silently compare both concepts against the references, Artworks 1–10 and each other.

Revise any repeated central idea or near-identical composition. Keep the assigned artistic style consistent.

Also imagine Artworks 11 and 12 placed beside Artworks 1–10 at thumbnail size. If either stands out because of new hues, stronger saturation, a different white balance, harsher contrast or a different material finish, revise its planned treatment to match the collection before rendering. Check the background and small details as well as the main subject.

OUTPUT
- Output ONLY 2 SEPARATE images: Artwork 11 first, then Artwork 12.
- One finished artwork per image.
- No written reply, explanations, captions or artwork-number labels.
- No grid, collage, contact sheet or split panels.
- Landscape 4:3, full bleed.
- No calendar elements, spiral binding, paper edges, borders, frames, mockup backgrounds, watermarks or logos.
- Required artwork text is allowed only under the text rules above."""


def art_continue(missing: list[int], n_refs: int) -> str:
    """Nhắc tiếp trong cùng phiên. Đúng 2 ảnh 11-12 còn thiếu: prompt đã duyệt, điền số ảnh mẫu; còn lại (lượt trước
    ra thiếu ảnh) thì nói rõ số artwork cần vẽ - code biết chính xác ảnh nào đã về."""
    if missing == [11, 12]:
        return ART_CONTINUE.format(artwork_text_rules=ARTWORK_TEXT_RULES, ref11=10 % max(1, n_refs) + 1, ref12=11 % max(1, n_refs) + 1)
    nums = ", ".join(str(n) for n in missing)
    extra = ("\n" + ART_EXTRA) if any(n > 10 for n in missing) else ""
    return (f"Continue: generate ONLY artwork {nums} (still missing), following ALL the same rules as before.\n"
            "Use each artwork's assigned reference from the ARTWORK PLAN, with a composition and background of your own "
            f"choice.{extra}\n\n{ARTWORK_TEXT_RULES}\n\nOutput ONLY {len(missing)} separate image{'s' if len(missing) > 1 else ''}. "
            "No text reply, no grid, no collage.\nLandscape 4:3, full bleed, no calendar elements, no border, "
            "no watermark.")


def art_resume(missing: list[int], n_refs: int) -> str:
    """Phiên MỚI (tài khoản trước hết lượt / lỗi giữa chừng): gửi lại ảnh tham chiếu + toàn bộ luật, chỉ vẽ số còn
    thiếu. Ảnh đã vẽ được giữ nguyên, không vẽ lại."""
    nums = ", ".join(str(n) for n in missing)
    extra = ("\nArtworks 11 and 12 (if requested):\n" + ART_EXTRA) if any(n > 10 for n in missing) else ""
    return (art_rules(n_refs) + extra + f"\n\nTHIS TIME: generate ONLY artwork {nums} from the plan above (the others are "
            "already done). Use each one's assigned reference, with a composition and background of your own choice.\n\n"
            + f"OUTPUT FOR THIS TURN\n- Output {len(missing)} SEPARATE image outputs, one artwork per image, "
              f"in this exact order: {nums}.\n"
            + ART_OUTPUT[ART_OUTPUT.index("- No written reply"):])



# ------------------------------------------------------------------ tên cuốn + listing (cùng phiên, ChatGPT thấy ảnh)
META_PROMPT = """Now look at the 12 artworks you just generated (artwork 1 = January ... artwork 12 = December). They will become a {year} printed wall calendar for the US market.
Do NOT generate any image for this message. Reply with text only.

Return ONLY this JSON in a ```json code block:
{{"title": "", "subtitle": "", "style_name": "", "buyer": "", "keyword": "", "months": ["", "", "", "", "", "", "", "", "", "", "", ""], "etsy_title": "", "etsy_description": "", "tags": []}}

FIELDS
- "title": the calendar name printed on the front cover, 2-5 words, original and catchy, no year.
- "subtitle": a short cover subtitle, 3-8 words, no year.
- "style_name": the art style in 2-4 words (e.g. "Soft watercolor").
- "buyer": who buys this calendar, one short phrase.
- "keyword": the main search phrase buyers type, 2-4 words.
- "months": 12 short captions, one per artwork in order: a 2-5 word title for each artwork (e.g. "Rebel Heart"), no dash, no description sentence.
- "etsy_title", "etsy_description", "tags": the Etsy listing, following ALL the rules below.

ETSY RULES (must all be met)
1. "etsy_title": at most 140 characters, natural and readable. Put the most important search phrase first (e.g. "{year} ... Wall Calendar"), then 1-2 short descriptive phrases. Do not repeat the same word more than twice. Use each of these characters at most once: % : & +. Never use $ ^ ` or °. No more than 3 words in ALL CAPS. No emojis, no "free shipping", no prices, no shop name.
2. "etsy_description": plain text (no HTML, no markdown, no emojis). Start with 1-2 sentences that say exactly what the product is, using the main search phrase naturally. Then a short paragraph on the artwork and who it is for (gift ideas). Then a line "What's inside" followed by 3-4 lines starting with "- ". 600 to 1500 characters. Do NOT include sizes, binding, printing or shipping details (they are added automatically).
3. "tags": exactly 13 different tags, each at most 20 characters, lowercase, only letters, numbers and spaces. Mix broad and specific long-tail phrases buyers actually type; include the year in 1-2 tags.
4. Only describe this original artwork. Do not mention or imply any brand, celebrity, trademark, team, film, franchise or other company's characters."""


def meta_prompt(year: int) -> str:
    return META_PROMPT.format(year=year)


def meta_repair(errors: list[str]) -> str:
    return ("Your previous JSON broke these rules:\n- " + "\n- ".join(errors)
            + "\n\nFix every problem and return the full corrected JSON in a ```json code block. Text only, no image.")


# ------------------------------------------------------------------ bìa trước (cùng phiên)
def cover_prompt(title: str, subtitle: str, year: int, fresh: bool = False) -> str:
    """fresh: phiên mới (ChatGPT chưa thấy artwork) - code đính 4 artwork (tháng 1, 4, 7, 10) làm mẫu."""
    sub = f'\nRender this exact subtitle once, spelled exactly: "{subtitle}".' if subtitle else ""
    seen = ("the 4 attached artworks (they are NOT images to edit; only follow their style)" if fresh
            else "the 12 artworks above")
    return f"""Now create the FRONT COVER of this {year} wall calendar as ONE new image.
Use the same subject, drawing / photo style, stroke quality and color tone as {seen}, with a new composition and background that is different from all of them.
Render this exact title once, spelled exactly: "{title}".
Render this exact year once: "{year}".{sub}
Art-direct the lettering yourself so it feels native to the artwork, readable at thumbnail size, centered horizontally between 15% and 85% of the width. Do not put a box, banner, haze or blurred band behind the text.
No calendar grid, no dates, no month names, no spiral binding, no border, no frame, no mockup, no watermark, no logo.
Output ONLY 1 image. No text reply. Landscape 4:3, full bleed."""


# ------------------------------------------------------------------ 12 trang lịch (phiên 2, tài khoản B)
def _rule_date(year: int, rule, known: dict) -> dt.date:
    kind = rule[0]
    if kind == "fixed":
        return dt.date(year, rule[1], rule[2])
    if kind == "nth":
        return dates.nth_weekday(year, *rule[1:])
    if kind == "easter":
        return dates.easter(year) + dt.timedelta(days=rule[1])
    if kind == "after":                       # rule[1] ngày sau một ngày lễ khác
        return known[rule[2]] + dt.timedelta(days=rule[1])
    raise ValueError(rule)


# Danh sách ngày lễ của prompt grid người dùng duyệt (khác danh sách của trang chính: có April Fools', Tax Day,
# Patriot Day, Grandparents Day, Election Day...). Ngày tính theo năm.
HOLIDAYS = [
    ("New Year's Day", ("fixed", 1, 1)),
    ("Martin Luther King Jr. Day", ("nth", 1, dates.MON, 3)),
    ("Groundhog Day", ("fixed", 2, 2)),
    ("Valentine's Day", ("fixed", 2, 14)),
    ("Presidents' Day", ("nth", 2, dates.MON, 3)),
    ("Daylight Saving Time Begins", ("nth", 3, dates.SUN, 2)),
    ("St. Patrick's Day", ("fixed", 3, 17)),
    ("Good Friday", ("easter", -2)),
    ("Easter Sunday", ("easter", 0)),
    ("April Fools' Day", ("fixed", 4, 1)),
    ("Tax Day", ("fixed", 4, 15)),
    ("Earth Day", ("fixed", 4, 22)),
    ("Cinco de Mayo", ("fixed", 5, 5)),
    ("Mother's Day", ("nth", 5, dates.SUN, 2)),
    ("Memorial Day", ("nth", 5, dates.MON, -1)),
    ("Flag Day", ("fixed", 6, 14)),
    ("Juneteenth", ("fixed", 6, 19)),
    ("Father's Day", ("nth", 6, dates.SUN, 3)),
    ("Independence Day", ("fixed", 7, 4)),
    ("Labor Day", ("nth", 9, dates.MON, 1)),
    ("Patriot Day", ("fixed", 9, 11)),
    ("Grandparents Day", ("after", 6, "Labor Day")),          # Chủ nhật đầu tiên sau Labor Day
    ("Columbus Day / Indigenous Peoples' Day", ("nth", 10, dates.MON, 2)),
    ("Halloween", ("fixed", 10, 31)),
    ("Election Day", ("after", 1, "_first_monday_nov")),       # thứ Ba sau thứ Hai đầu tiên của tháng 11
    ("Daylight Saving Time Ends", ("nth", 11, dates.SUN, 1)),
    ("Veterans Day", ("fixed", 11, 11)),
    ("Thanksgiving", ("nth", 11, dates.THU, 4)),
    ("Christmas Eve", ("fixed", 12, 24)),
    ("Christmas Day", ("fixed", 12, 25)),
    ("New Year's Eve", ("fixed", 12, 31)),
]


def HOLIDAY_DATES(year: int) -> dict[str, dt.date]:  # noqa: N802 - dùng như hằng tính theo năm
    out = {"_first_monday_nov": dates.nth_weekday(year, 11, dates.MON, 1)}
    for name, rule in HOLIDAYS:
        out[name] = _rule_date(year, rule, out)
    return out


def holiday_notes(year: int, month: int) -> list[tuple[int, str]]:
    found = [(d.day, name) for name, d in HOLIDAY_DATES(year).items()
             if not name.startswith("_") and d.month == month]
    return sorted(found)


def month_facts(year: int, month: int) -> str:
    first = WEEKDAY[dt.date(year, month, 1).weekday()]
    ndays = calendar.monthrange(year, month)[1]
    notes = holiday_notes(year, month)
    abbr = MONTHS[month - 1][:3]
    hol = ("Notes: " + ", ".join(f"{abbr} {day} {name}" for day, name in notes) + ".") if notes else "No holidays."
    return f"{MONTHS[month - 1]} 1 falls on {first}, {ndays} days. {hol}"


def _call(year: int, month: int, image_no: int) -> str:
    return (f'CALL {month}: Page titled "{MONTHS[month - 1].upper()} {year}". Color tone and motifs from attached '
            f"image {image_no}. {month_facts(year, month)}")


SHARED_DESIGN = ("Shared design for every page: premium US wall calendar grid page, landscape 4:3, full bleed, flat "
                 "design. Week starts Sunday with headers Sunday Monday Tuesday Wednesday Thursday Friday Saturday. "
                 "Every date in the correct column, no missing or duplicated numbers. Holiday notes small inside their "
                 "date cell, never covering the number. All text spelled correctly and highly legible. You choose the "
                 "layout and typography, but use the SAME layout on all {n} pages; only colors and subtle motifs change "
                 "to match each artwork. No artwork image on the page, no mockup, no spiral, no watermark, no logo."
                 "\n\n" + "INTEGRATED DESIGN (VERY IMPORTANT): the grid must look painted INTO the page as one "
                 "continuous illustration, never pasted on top of a picture. Do NOT put an opaque white or cream "
                 "table, card, box or panel over a background photo, and do NOT draw a hard rectangular frame around "
                 "the grid. The page surface is a light tint of the artwork's palette with the same texture; scenery "
                 "and motifs from the artwork decorate the top and outer edges and fade softly toward the center. "
                 "Present the dates with soft, low-contrast dividers in the same colors and texture as the "
                 "decoration (thin brush-stroke week lines, gentle rounded tiles, or dates floating on a calm area); "
                 "avoid a harsh spreadsheet grid. Keep everything flat and printable, and keep the dates area light "
                 "and calm so every number reads clearly.")


def grid_prompt(year: int, months: list[int], layout_ref: bool = False) -> str:
    """Prompt grid lượt đầu (thường là 10 tháng 1-10) - nguyên văn của người dùng, số tháng tuỳ danh sách.
    layout_ref: phiên mới vẽ bù - ảnh 1 là một trang đã xong để giữ cùng bố cục, artwork bắt đầu từ ảnh 2."""
    n = len(months)
    off = 1 if layout_ref else 0
    order = ", ".join(f"image {i + 1 + off} = {MONTHS[m - 1]}" for i, m in enumerate(months[:2]))
    order += (f", … image {n + off} = {MONTHS[months[-1] - 1]}" if n > 2 else "")
    head = (f"I have attached {n} artwork images in order: {order}.\n"
            "These artworks are ONLY color and style references. Do NOT edit them, do NOT redraw them, do NOT place "
            "them on the pages.")
    if layout_ref:
        head = ("I have attached 1 finished calendar page (image 1) plus " + head[len("I have attached "):]
                + "\nImage 1 is an already finished page of this same calendar: copy its layout, typography and "
                  "structure EXACTLY on every new page; only the colors and subtle motifs follow each artwork.")
    calls = "\n\n".join(_call(year, m, i + 1 + off) for i, m in enumerate(months))
    return f"""{head}

TASK: Create {n} matching {year} calendar grid page{'s' if n > 1 else ''}, one for each attached artwork.

HOW TO GENERATE (IMPORTANT):
Do NOT generate multiple images from one prompt. Do NOT use a batch setting.
Call the image generation tool {n} SEPARATE TIMES, one call per month, using only the matching CALL prompt below.
Each call produces exactly 1 image. No text reply.

{SHARED_DESIGN.format(n=n)}

{calls}

Self-check: every page must show a DIFFERENT month. If a page shows the wrong month, regenerate it with its correct CALL."""


def grid_continue(year: int, months: list[int]) -> str:
    """Nhắc tiếp trong cùng phiên grid (thường 2 tháng 11-12) - nguyên văn của người dùng."""
    n = len(months)
    imgs = ", ".join(f"image {i + 1} = {MONTHS[m - 1]}" for i, m in enumerate(months))
    calls = "\n\n".join(_call(year, m, i + 1) for i, m in enumerate(months))
    return (f"Same rules as before. I have attached {n} more artwork{'s' if n > 1 else ''}: {imgs}.\n"
            f"Call the image tool {n} SEPARATE time{'s' if n > 1 else ''}. Use the SAME layout as the previous "
            f"{'10 ' if months == [11, 12] else ''}pages.\n\n{calls}")


def grid_redo(year: int, month: int, reason: str) -> str:
    """Một trang bị OCR loại: vẽ lại đúng CALL đó ngay trong phiên (không cần đính lại ảnh)."""
    return (f"The {MONTHS[month - 1]} page you just made has calendar errors found by an automatic check ({reason}). "
            f"Generate it again with 1 single image call, SAME layout as the other pages. Place EVERY date exactly in "
            "its correct weekday column, each number once.\n\n"
            + _call(year, month, month).replace(f"attached image {month}", f"the {MONTHS[month - 1]} artwork above"))
