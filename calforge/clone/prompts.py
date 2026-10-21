"""Prompt của luồng "Làm theo ảnh mẫu". Hai prompt artwork được duyệt lại ngày 08/10/2026.
Code điền phân công ảnh mẫu, số ảnh còn thiếu và dữ kiện lịch theo năm."""
from __future__ import annotations

import calendar
import datetime as dt

from ..core import dates

MONTHS = dates.MONTH_NAMES
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


EXPANSION_RULES = """Study the attached source artworks before designing anything. Reference 1 is the primary style and identity reference. Preserve its rendering technique, palette, warmth, contrast, texture, lighting and emotional/visual appeal. Other references show scenes already used; do not repeat them.
Infer the subject type: people, characters, animals, landscapes, architecture, objects, devotional art or typography. Adapt variation to that subject; never impose human posing or fashion on unrelated subjects.
Preserve recognizable identity and the features that make the reference appealing. If appeal depends on a person's expressive face, physique or intimacy, keep those features prominent and readable. Do not hide the face, shrink the hero into scenery, cover the appealing silhouette with bulky clothing, or let machinery/props dominate. Maintain a comparable subject-to-frame ratio and emotional intensity without copying the pose.
Invent BOTH a clearly different meaningful action, interaction or arrangement AND a clearly different overall composition for every new artwork across ALL books. A different background alone is insufficient. Do not automatically preserve source companions, mounts, opponents, weapons or props as identity. For clothed people, characters and anthropomorphic animals, clothing must differ materially in cut, layers, material and styling from source outfits and other new artworks, not merely recolor them. Preserve indispensable canonical, ceremonial or identifying clothing; vary other applicable elements instead. For non-human subjects vary arrangements, viewpoints and narrative details appropriate to the source.
BACKGROUND VARIATION IS MANDATORY, independently of changes to action, pose, clothing or composition. Give EVERY new artwork a genuinely different location or environment from its source artwork AND every other new artwork across the entire group of books. For variants of the same source, assign a separate, clearly distinguishable setting to each book. Do not reuse the same room, balcony, rooftop, garden or landscape with only a different camera angle, crop, lighting, weather, time of day, props or color. Choose environments that naturally fit the subject and collection; preserve the shared artistic style and color tone, and keep the main subject prominent rather than letting the new background dominate. For subjects without a literal location, vary the meaningful surrounding arrangement or environmental motif to achieve equivalent background differentiation.
MATCH THE REFERENCE'S BACKGROUND COMPLEXITY. Change the setting without increasing its visual complexity. Match the assigned source artwork's amount of background detail, object density, depth layering, negative space, softness/blur and visual prominence. A simple or softly blurred source background must remain equally simple or softly blurred; a detailed source may retain comparable detail, but must not become more elaborate. Use only enough environmental cues to establish the new location. Do not automatically add ornate architecture, elaborate machinery, crowds, decorative clutter, extra scenery layers or cinematic spectacle. Preserve the source's balance between subject and background; the subject must remain the focus. A different background does not mean a busier background.
Keep the collection's original color tone; do not introduce a new color grade or contrasting style. References are artwork content, not product presentation: exclude calendar grids, binding, mockup edges, product titles, years, logos and sales copy. Preserve meaningful integral artwork lettering when supported by the reference collection, including authentic scripture/prayers; never borrow cover headings or invent illegible text. When there is no integral artwork text, add none.
ORIENTATION AND EXTRACTION: The source may be photographed at an angle, sideways, upside down, foreshortened or surrounded by a calendar mockup. Mentally rectify the artwork plane and understand the upright scene first. Render a NEW flat, front-facing, upright composition. Heads, bodies, architecture and integral lettering must read naturally upright; no copied page tilt, diagonal paper edges or perspective distortion from the product photo. Gravity stays coherent; intentionally reclining subjects may recline naturally. Remove ALL binding, date grids, paper, wall/table backgrounds, hands holding the product and margins. Reconstruct missing scene areas; never render a photographed calendar page.
Output finished landscape 4:3 artwork, full bleed, no calendar layout, borders or mockup. Before delivering, visually check upright orientation and clean artwork-only framing; correct any rotated scene, calendar remnants or copied source composition."""


SOURCE_VARIANT_PLAN = """You are a senior art director and image-prompt designer.

I have attached ONE source image. Plan exactly {count} distinct artwork concepts based on this reference, one for each assigned book. Each concept will later be rendered separately with this same reference attached.

Do not generate images now.

UNDERSTAND THE REFERENCE

Study the artwork itself. If the reference is a calendar page, cover, product photo or mockup, mentally extract and straighten the underlying artwork first.
Ignore calendar grids, dates, month labels, product titles, years, logos, binding, paper edges, borders, hands and the surrounding product presentation.
Identify the subject, artistic style, rendering technique, palette, texture, lighting, emotional appeal, subject prominence and background complexity.

SEPARATE IDENTITY FROM THE SOURCE SCENE

Preserve the subject's recognizable identity and the features responsible for the reference's appeal.
For people and characters, preserve recognizable facial features, hairstyle and other identifying characteristics. For animals, preserve the relevant species, markings and recognizable character features. For landscapes, architecture, objects, devotional art or typography, preserve the defining subject and visual language appropriate to that reference.
Do not automatically preserve the source's pose, action, companion, mount, opponent, weapon, main prop or narrative event. These belong to the source scene, not necessarily to the subject's identity.
Retain such an element only when it is indispensable to the subject's identity or meaning. Even then, create a different action and arrangement around it.

CREATE ALL N CONCEPTS TOGETHER

Develop the assigned concepts as one set so you can compare them before finalizing them.
Every concept must differ meaningfully from the source AND from every other concept in BOTH:
1. The main action, interaction, narrative event or meaningful arrangement.
2. The overall composition: pose or silhouette, subject placement, framing and relationships between the main visual elements.
A change of background, outfit, camera angle, lighting, weather or color alone does not qualify as a new concept.
Do not transplant the source's action and arrangement into another location. Do not repeat one visual formula across all books.
For example, if the source depicts a kitten knight riding a white wolf, do not make every concept another kitten riding the same wolf somewhere else. Preserve the kitten's identity and medieval visual world while developing different activities, interactions and compositions.
Adapt this principle to the actual subject. Do not force human activities, clothing or poses onto unrelated subjects.

WARDROBE AND APPEARANCE

For clothed people, characters and anthropomorphic animals, vary the outfit meaningfully where appropriate: cut, layers, materials, styling, armor design or accessories. Recoloring the same outfit is insufficient.
Preserve genuinely indispensable canonical, ceremonial or identifying garments. Do not treat every garment or accessory visible in the reference as mandatory.
Keep the subject's appealing features visible. Do not hide an expressive face, obscure an appealing physique or silhouette with bulky clothing, or replace the subject's visual importance with props.

BACKGROUND VARIATION

Give each concept a clearly different setting or surrounding arrangement from the source and the other assigned concepts.
Match the reference's background complexity, detail density, depth, negative space and softness. A simple or blurred background must remain comparably simple or blurred.
Use only enough environmental detail to establish the new setting. Do not automatically add ornate architecture, elaborate machinery, crowds, decorative clutter or cinematic spectacle.
For subjects without a literal location, vary the surrounding arrangement or environmental motif appropriately.

PRESERVE THE VISUAL APPEAL

Maintain the reference's artistic style, palette, warmth, contrast, rendering technique, texture and emotional intensity.
Keep a comparable subject-to-frame ratio and visual hierarchy. The main subject must remain prominent and readable.
Create novelty through the concept and composition, not through a different art style, excessive background complexity or a smaller, less engaging subject.

TEXT

Distinguish meaningful lettering within the artwork from text used to present or sell the product.
Exclude product titles, cover headlines, calendar labels, years, branding and sales copy.
Preserve meaningful integral artwork lettering when clearly supported by the reference, such as scripture, prayers or illustrated messages. Do not invent illegible text or borrow excluded product headings.
If meaningful text is essential, state the exact text to render. Scripture and attributed quotations must be authentic and accurately cited.
When the artwork has no integral text, add none.

ORIENTATION AND OUTPUT FRAMING

The source may be tilted, sideways, upside down, cropped or photographed in perspective. Understand its upright subject before planning.
Every concept must produce a new flat, upright, front-facing landscape artwork in a 4:3 aspect ratio, full bleed.
Exclude calendar layouts, grids, binding, paper edges, borders, mockups and photographed-page perspective.

CHECK THE SET BEFORE RETURNING

Silently compare every proposed concept with the source and the other assigned concepts.
Reject and replace any concept that mainly repeats an existing action and arrangement with cosmetic changes.
Confirm that all N concepts have:
- A different main action, interaction or meaningful arrangement.
- A clearly different overall composition.
- An appropriate distinct setting or surrounding arrangement.
- The reference's recognizable identity, visual appeal, style and color tone.
- Background complexity comparable to the reference.
Perform this comparison within this planning response. Do not output a separate review stage.

RETURN FORMAT

Return ONLY valid JSON in this structure:
{{"artworks":[{{"id":"exact assignment id","prompt":"complete English image-generation prompt"}}]}}
Return exactly one row per assignment, with no missing, duplicate or extra rows.
Each prompt must stand alone with the source supplied as attachment 1. Describe the chosen subject, specific action or arrangement, outfit where applicable, setting, framing and composition.
Make the new scene explicit. Do not merely say "make it different." Do not instruct the renderer to preserve the source's entire scene.
Keep each prompt concise, approximately 100–150 words. Shared style, orientation and quality rules will be appended by the renderer, so avoid repeating them at length.
Do not generate images or include commentary outside the JSON.

Previously finalized assignments from other source artworks (avoid repeating their concepts):
{previous}

Assignments:
{assignments}"""


def expansion_plan(jobs, previous, source_count, book_count, *, variants=False):
    import json
    if variants and source_count == 1:
        return SOURCE_VARIANT_PLAN.format(count=len(jobs), previous=json.dumps(previous, ensure_ascii=False),
                                          assignments=json.dumps(jobs))
    return ("You are a senior art director. Plan ONLY the assigned monthly artworks. Reference 1 means the first attachment of THIS message. "
            + (f"There are {source_count} source artworks and {book_count} books. Every book needs 12 NEW artworks. "
               "No source image will be copied into a book. For each assignment use its reference_index as the "
               "specific source artwork to reinterpret. For missing-source months, reference_index=1 supplies style "
               "and identity for an entirely new concept. Design different variants for every book, including when "
               "all 12 source artworks are available. Each final rendering receives ONLY its assigned reference, "
               "as attachment 1: describe the correct source identity and never refer to other attachment numbers.\n"
               if variants else f"There are {source_count} shared originals per book and {book_count} books. "
               "Originals stay unchanged; you are designing distinct completion images, not replacements.\n")
            + EXPANSION_RULES
            + "\nPreviously assigned prompts (avoid repeating their scenes, clothing and composition):\n"
            + json.dumps(previous, ensure_ascii=False)
            + "\nReturn ONLY JSON {\"artworks\":[{\"id\":\"assignment id\",\"prompt\":\"complete, detailed English image generation prompt\"}]}. "
            "Exactly one row per requested assignment, no extra rows. Every prompt must stand alone with reference 1 attached. "
            "Keep each prompt concise: 80–120 words describing its specific subject, action, setting, clothing and composition. "
            "Every prompt must explicitly name its unique location/environment with only enough background cues to identify it, "
            "and match the assigned reference's background simplicity or detail level. Do not embellish the environment beyond the source. "
            "A change of pose, camera angle or lighting does not satisfy the mandatory background variation. "
            "The renderer appends the shared identity/style/orientation/quality rules, so do not repeat those long rules in each prompt. "
            "Do not render images yet. Assignments:\n" + json.dumps(jobs))


def expansion_render(prompt):
    return ("Generate exactly ONE image for the following assigned artwork. Reference 1 means the first attachment "
            "of the CURRENT request, overriding earlier reference assignments in this chat. "
            "The assigned concept has already been planned centrally. Execute its subject, action, setting, clothing "
            "and composition faithfully; do not invent a replacement concept or redesign the assignment. "
            "The shared variation rules below guide execution of this assignment, not a new idea-planning step. "
            "Do not output a collage or a written explanation.\n"
            + EXPANSION_RULES
            + "\nThe attached image is a reference for identity, style, palette and visual appeal. "
            "Its depicted scene is not the composition to reproduce. "
            "Follow the assigned concept's action, outfit, setting and composition. "
            "When these differ from the reference, follow the assigned concept. "
            "Do not restore the source's pose, companions, mount, opponent or props unless the assigned concept explicitly requires them. "
            "Create a new scene from scratch, not a lightly edited version of the reference. "
            "Match its visual appeal and background complexity. "
            "Require BOTH a different main action/meaningful arrangement AND a different overall composition; "
            "a background change alone is insufficient. Wardrobe variation applies to anthropomorphic animals as well as people."
            + "\nASSIGNED ARTWORK:\n" + prompt)

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
Preserve the recognizable identity, appearance, characteristic colors, materials and important details of the assigned reference's subject. For people and characters, identity means face, hairstyle and identifying features, not the exact outfit: follow the WARDROBE rule below.

Create a genuinely different scene around that subject: a new action, interaction, narrative moment or meaningful arrangement, with a clearly different overall composition.

Do not copy the reference's pose and arrangement into a different background.

If two references depict the same subject, their KEEP artworks must show clearly different situations and visual stories. Preserve each reference's own style and only its integral artwork text, as determined by the TEXT ON THE ARTWORK rules below.

NEW-CONCEPT ARTWORKS
Use the assigned reference as a guide to style and theme, then invent a new central idea that is not already represented by the reference set or another planned artwork.

When the theme allows multiple subjects, introduce a different relevant subject, interaction or meaningful arrangement that naturally belongs in the same collection.

When the collection centers on one specific recurring figure or subject, keep that identity consistent, but invent a substantially different action, situation or narrative moment.

SUPPORTING CHARACTERS (REQUIRED)
If the collection centers on recurring people or characters, the main figure(s) must not appear alone in every artwork. Artworks 4, 6, 8 and 10 MUST each include at least one clearly visible supporting character who actively takes part in the scene (talking, playing, celebrating, helping, competing, sharing an activity with the main figure(s)). Background passers-by or tiny distant figures do not count.
Choose supporting characters that plausibly belong to the main figures' world — family members, friends, teammates, rivals, fans, coworkers, neighbors, children, pets or creatures from the same setting — and use a different supporting character or group in each of those artworks.
Supporting characters must:
- be drawn in the same artistic style, palette and visual world as the collection
- stay secondary: the main figure(s) remain the clear focal point
- be original, unnamed characters, never real people, celebrities or characters from other franchises
If the collection has no recurring people or characters (e.g. landscapes, still life, patterns), ignore this rule.
Do not introduce subjects that are unrelated to the collection's theme.

WARDROBE: When people or characters appear across the collection, keep each recurring figure's face, hairstyle and identifying features consistent, but give them a DIFFERENT outfit in every artwork, designed in the same style and color world as the collection and suited to that artwork's scene. Keep a garment only when it is part of the figure's identity (a uniform, signature costume, armor, religious or traditional dress); even then, vary accessories, layers or styling where it fits.

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
- changing only the outfit

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
For Artworks 4, 6, 8 and 10, confirm that a supporting character is clearly visible and interacting with the main figure(s) before generating.
Check that its assigned reference's style and text rules are still respected."""

ART_OUTPUT = """OUTPUT FOR THIS TURN
- Generate ONLY Artwork 1 through Artwork 10, in that exact order.
- Keep Artwork 11 and Artwork 12 planned for the next request; do not generate them yet.
- Output 10 SEPARATE images, one finished artwork per image.
- No written reply, explanations, captions or artwork-number labels.
- Never combine artworks into a grid, collage, contact sheet or split-panel image.
- If you notice an image contains more than one scene or panel, it is wrong: discard it and generate that artwork again as a single scene.
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


def output_first(n: int, nums: list[int] | None = None) -> str:
    """Đặt lên ĐẦU prompt: prompt dài thì ChatGPT hay bỏ qua phần OUTPUT ở cuối và gom mọi cảnh vào một ảnh lưới
    (người dùng test 12/10/2026). Nói trước + nhắc lại cuối thì ra đúng từng ảnh riêng."""
    nums = nums or list(range(1, n + 1))
    run = len(nums) > 2 and nums == list(range(nums[0], nums[-1] + 1))      # 1..10 liền nhau: viết gọn
    order = (f"Artwork {nums[0]}, then Artwork {nums[1]}, … then Artwork {nums[-1]}" if run
             else ", then ".join(f"Artwork {m}" for m in nums))
    many = f"{n} SEPARATE image generations, one after another: {order}" if n > 1 else f"exactly ONE image: {order}"
    return (f"OUTPUT FORMAT — MOST IMPORTANT RULE\nProduce {many}. Each generation contains exactly ONE artwork "
            "filling the whole frame.\nNEVER put several artworks, scenes or panels into one image. No grid, collage, "
            "contact sheet, storyboard, triptych or split-panel layout — even though you plan 12 ideas, you render them "
            "one per image.\n\n")


def reminder(n: int, first: int) -> str:
    return (f"\n\nREMINDER: {n} separate image{'s' if n > 1 else ''}, one artwork per image, generated one at a time. "
            f"Start with Artwork {first} now.")


def art_prompt(n_refs: int) -> str:
    return output_first(10) + art_rules(n_refs) + "\n\n" + ART_OUTPUT + reminder(10, 1)

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

SUPPORTING CHARACTERS: if the collection centers on recurring people or characters, at least one of Artworks 11 and 12 MUST include a clearly visible original supporting character (family, friend, teammate, rival, child, pet or creature from their world) who actively interacts with the main figure(s), drawn in the same style, secondary to the main figure(s), never a real person, celebrity or character from another franchise, and different from the supporting characters already used.

WARDROBE: recurring people or characters keep their face, hairstyle and identifying features, but each new artwork gives them an outfit different from every outfit already used in Artworks 1–10 and from each other, in the same style and color world (keep a garment only if it is part of the figure's identity).

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
- No grid, collage, contact sheet or split panels. If an image contains more than one scene or panel, it is wrong: generate that artwork again as a single scene.
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
            "One artwork per image, never several scenes or panels in one image. No text reply, no grid, no collage."
            "\nLandscape 4:3, full bleed, no calendar elements, no border, "
            "no watermark.")


def art_resume(missing: list[int], n_refs: int) -> str:
    """Phiên MỚI (tài khoản trước hết lượt / lỗi giữa chừng): gửi lại ảnh tham chiếu + toàn bộ luật, chỉ vẽ số còn
    thiếu. Ảnh đã vẽ được giữ nguyên, không vẽ lại."""
    nums = ", ".join(str(n) for n in missing)
    extra = ("\nArtworks 11 and 12 (if requested):\n" + ART_EXTRA) if any(n > 10 for n in missing) else ""
    return (output_first(len(missing), missing) + art_rules(n_refs) + extra + f"\n\nTHIS TIME: generate ONLY artwork {nums} from the plan above (the others are "
            "already done). Use each one's assigned reference, with a composition and background of your own choice.\n\n"
            + f"OUTPUT FOR THIS TURN\n- Output {len(missing)} SEPARATE image outputs, one artwork per image, "
              f"in this exact order: {nums}.\n"
            + ART_OUTPUT[ART_OUTPUT.index("- No written reply"):] + reminder(len(missing), missing[0]))



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
4. Only describe this original artwork."""


def meta_prompt(year: int) -> str:
    return META_PROMPT.format(year=year)


def meta_repair(errors: list[str]) -> str:
    return ("Your previous JSON broke these rules:\n- " + "\n- ".join(errors)
            + "\n\nFix every problem and return the full corrected JSON in a ```json code block. Text only, no image.")


# ------------------------------------------------------------------ bìa trước (cùng phiên)
def cover_prompt(title: str, subtitle: str, year: int, fresh: bool = False, reference_count: int = 4) -> str:
    """fresh: use the references attached to this cover request, including in an existing chat."""
    sub = f'\nRender this exact subtitle once, spelled exactly: "{subtitle}".' if subtitle else ""
    seen = (f"the {reference_count} attached artworks in THIS message (they are NOT images to edit; only follow their style)" if fresh
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


def grid_redo(year: int, month: int, reason: str, *, layout_ref: bool = False, attempt: int = 1) -> str:
    """Explicit references and deterministic date positions for a single repair."""
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    table = 'SUN | MON | TUE | WED | THU | FRI | SAT\n' + '\n'.join(
        ' | '.join(str(day) if day else 'BLANK' for day in week) for week in weeks)
    refs = ('Image 1 is a finished page: copy ONLY its layout and typography, never its dates. '
            'Image 2 is the target artwork: use ONLY its palette and subtle motifs.' if layout_ref else
            'Image 1 is the target artwork: use ONLY its palette and subtle motifs.')
    strict = ('Previous repair failed. Rebuild the date grid from the table below; do not copy date positions '
              'from any previous image. Check every row and column before returning the image.\n' if attempt > 1 else '')
    design = SHARED_DESIGN.format(n=1)
    if layout_ref:
        design = design.replace('You choose the layout and typography,',
                                'Use the layout and typography of attached image 1,')
    return (f'Render ONLY {MONTHS[month - 1].upper()} {year}, exactly ONE image. '
            f'Automatic check reported: {reason}.\n{refs}\n{strict}'
            + design + '\n\n' + month_facts(year, month)
            + '\nEXACT DATE TABLE: each line is one week, columns stay in the order shown. '
              'BLANK means an empty cell; never print the word BLANK. Do not wrap or shift dates.\n'
            + table + '\nUse the image generation tool. Return the rendered image, no text or download promise.')
