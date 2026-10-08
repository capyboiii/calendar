"""Prompt của luồng "Làm theo ảnh mẫu". Câu chữ của 4 prompt chính giữ NGUYÊN VĂN như người dùng duyệt (07/10/2026);
code chỉ điền năm, thứ của ngày 1, số ngày và ngày lễ (tính theo năm, không ghi cứng 2027)."""
from __future__ import annotations

import calendar
import datetime as dt

from ..core import dates

MONTHS = dates.MONTH_NAMES
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ------------------------------------------------------------------ 12 artwork (phiên 1, tài khoản A)
ART_RULES_T = """I have attached reference images. These are NOT images to edit. Do NOT modify, retouch or recreate the attached images.

REFERENCE FORMAT
Some attached images are plain artworks. Others are calendar pages or product mockups that CONTAIN an artwork.
For every reference, use ONLY the artwork area. Completely IGNORE all calendar elements: date grids, numbers, month names, weekday names, year, spiral binding, hanging holes, paper edges, white margins, borders, frames, walls, tables, hands and mockup backgrounds.

TEXT ON THE ARTWORK
If the artwork area of a reference contains text (e.g. a quote, verse, title, phrase or reference line):
- Copy that EXACT text into the corresponding KEEP artwork, word for word, with the same spelling, punctuation and line breaks.
- Keep a similar font style, color and hierarchy (main text vs. smaller reference line).
- Place the text in a clean, calm area of the new composition so it stays highly legible.
- Each artwork only uses the text from ITS OWN reference. Never swap or mix text between artworks.
- If a reference has no text in its artwork area, the new artwork has NO text.
- NEW-subject artworks follow the NEW text rule below.
- Calendar text (dates, month names, weekdays, year) is NOT artwork text. Never include it.

INDIVIDUAL REFERENCES
Treat each attached image INDIVIDUALLY. Do NOT blend styles, colors or text across references.
Follow the ARTWORK PLAN below: it says which reference each artwork follows, and whether it KEEPS the reference's subject or needs a NEW subject.

{plan}

For each artwork, silently study ONLY its assigned reference (do not write any description).
- KEEP: keep the same subject (appearance, colors, materials, details), the same drawing / photo style and stroke quality, the same color tone and the same text (if any), as described above.
- NEW: keep the same drawing / photo style, stroke quality and color tone, and stay in the same theme and world as the reference, but INVENT a different main subject yourself (a different character, animal, object or scene that fits this theme and that a buyer of this calendar would love). Never redraw the reference's subject again. If the reference has text in its artwork area, write a NEW text of the same kind instead of copying it (e.g. a different Bible verse with its reference line, a different quote or phrase of similar length and tone), with the same font style, color, hierarchy and placement rules; spell it correctly and never repeat a text already used in another artwork. If the reference has no text, the NEW artwork has NO text.

VARIETY ACROSS THE SET
All 12 artworks must be clearly different from each other. Never show the same main subject twice in the same pose, action or arrangement. Vary the subject, pose, action, props and mood across the set, so the calendar does not feel repetitive.

Then generate a BRAND-NEW artwork from scratch with a completely different background, camera angle and composition.
Do NOT reuse or slightly modify the background of any reference. Invent a new environment for every artwork.

COMPOSITION AND BACKGROUND (your free choice):
Choose the composition, camera angle and background of every artwork yourself. Vary them widely across the set (for example wide shots, close-ups, low or high angles, indoor and outdoor scenes, different times of day), so that every artwork has a composition and background that is unique in the set and clearly different from its reference."""

ART_OUTPUT = """OUTPUT RULES (VERY IMPORTANT):
- Output ONLY images. No text reply, no descriptions, no captions.
- 10 SEPARATE image outputs, one artwork per image.
- NEVER combine artworks into one image: no grid, no collage, no split panels.
- Each image: landscape 4:3, full bleed, single finished artwork filling the whole frame.
- No calendar elements, no dates, no spiral binding, no paper edges, no border, no frame, no mockup, no watermark, no logo."""



def art_plan(n_refs: int) -> str:
    """Bảng phân công 12 artwork: artwork i theo ảnh mẫu ((i-1) mod n)+1. Lần đầu dùng một ảnh mẫu thì GIỮ chủ thể;
    các lần sau (ảnh mẫu ít hơn 12) ChatGPT phải tự nghĩ chủ thể MỚI cùng chủ đề - tránh 12 tranh lặp một thứ."""
    n = max(1, int(n_refs))
    lines = ["ARTWORK PLAN:"]
    for i in range(1, 13):
        kind = "KEEP its subject" if i <= n else "NEW subject (invent it, same style and theme)"
        lines.append(f"- Artwork {i}: reference {(i - 1) % n + 1} - {kind}")
    return "\n".join(lines)


def art_rules(n_refs: int) -> str:
    return ART_RULES_T.replace("{plan}", art_plan(n_refs))


def art_prompt(n_refs: int) -> str:
    return art_rules(n_refs) + "\n\n" + ART_OUTPUT

# Artwork 11-12: không ép bố cục / mùa / không khí cố định (người dùng bỏ "snowy winter", "end-of-year" 08/10/2026) -
# ChatGPT tự chọn, chỉ cần khác hẳn 10 artwork trước và khác nhau.
ART_EXTRA = """  • Artwork 11 and Artwork 12: choose the composition, camera angle and background yourself, freely. Each must be clearly different from artworks 1–10 and from each other. No forced season, theme or mood."""

ART_CONTINUE = """Continue: generate ONLY the 2 artworks that are still missing from the set, following ALL the same rules as before.

- Check which artwork numbers have not been generated yet, and create exactly those 2.
- Use each missing artwork's assigned reference from the ARTWORK PLAN, with a composition and background of your own choice.
- If artworks 1–10 are all done, generate artwork 11 and 12 instead:
""" + ART_EXTRA + """

For each artwork follow the ARTWORK PLAN (KEEP or NEW subject) and keep, from ITS OWN reference only:
- the subject (KEEP), or a NEW invented subject of the same theme (NEW) that is different from every artwork so far
- the same stroke style
- the same color tone
- for KEEP artworks only: the EXACT text from the artwork area (word for word, same line breaks), if any. NEW artworks: a new text of the same kind (only if the reference has text), never a copy. Never include calendar text (dates, month names, weekdays, year).

Background, camera angle and composition must be clearly different from the reference and from all previously generated artworks.

Output ONLY 2 separate images. No text reply, no grid, no collage.
Landscape 4:3, full bleed, no calendar elements, no border, no watermark."""


def art_continue(missing: list[int]) -> str:
    """Nhắc tiếp trong cùng phiên. Đúng 2 ảnh 11-12 còn thiếu: prompt nguyên văn của người dùng; còn lại (lượt trước
    ra thiếu ảnh) thì nói rõ số artwork cần vẽ - code biết chính xác ảnh nào đã về."""
    if missing == [11, 12]:
        return ART_CONTINUE
    nums = ", ".join(str(n) for n in missing)
    extra = ("\n" + ART_EXTRA) if any(n > 10 for n in missing) else ""
    return (f"Continue: generate ONLY artwork {nums} (still missing), following ALL the same rules as before.\n"
            "Use each artwork's assigned reference from the ARTWORK PLAN, with a composition and background of your own "
            f"choice.{extra}\n\nOutput ONLY {len(missing)} separate image{'s' if len(missing) > 1 else ''}. "
            "No text reply, no grid, no collage.\nLandscape 4:3, full bleed, no calendar elements, no border, "
            "no watermark.")


def art_resume(missing: list[int], n_refs: int) -> str:
    """Phiên MỚI (tài khoản trước hết lượt / lỗi giữa chừng): gửi lại ảnh tham chiếu + toàn bộ luật, chỉ vẽ số còn
    thiếu. Ảnh đã vẽ được giữ nguyên, không vẽ lại."""
    nums = ", ".join(str(n) for n in missing)
    extra = ("\nArtworks 11 and 12 (if requested):\n" + ART_EXTRA) if any(n > 10 for n in missing) else ""
    return (art_rules(n_refs) + extra + f"\n\nTHIS TIME: generate ONLY artwork {nums} from the plan above (the others are "
            "already done). Use each one's assigned reference, with a composition and background of your own choice.\n\n"
            + ART_OUTPUT.replace("- 10 SEPARATE image outputs, one artwork per image.",
                                 f"- {len(missing)} SEPARATE image output{'s' if len(missing) > 1 else ''}, "
                                 "one artwork per image."))


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
- "months": 12 short captions (3-8 words), one per artwork in order, describing what each artwork shows.
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
