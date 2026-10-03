"""Prompt cho "AI gen mockup" (chỉ Wall Calendar (Blank) chế độ "AI vẽ cả trang"). Giữ NGUYÊN VĂN theo người dùng.

Preview 1: đính kèm IMAGE 1 = khung mockup bìa lò xo (data/mockups/front_cover_spiral.webp),
           IMAGE 2 = tranh bìa AI gốc của cuốn (_he_thong/anh_ai/cover.*).
Preview 2, 3: đính kèm mockup code đã ghép của cuốn (02_open_spread_flat, 03_three_open_spreads) - AI giữ nguyên
           cuốn lịch, thay bối cảnh.
Preview 4: IMAGE 1 = tranh tháng 1 AI gốc (_he_thong/anh_ai/m01.*), IMAGE 2 = mockup code 04_two_wall_spreads (2 tờ
           lịch mở treo tường: tháng 1, tháng 2) - AI chỉ thay nền theo tranh.
Preview 5: IMAGE 1 = tranh tháng 4 AI gốc (_he_thong/anh_ai/m04.*), IMAGE 2 = mockup code 06_three_books (bìa +
           trang lịch tháng 4 + tranh tháng 4) - AI chỉ thay nền theo tranh.
"""

COVER_PROMPT = """## BACKGROUND — FULL CREATIVE FREEDOM

Replace the original background from IMAGE 1 with a completely new environment.

Study IMAGE 2 carefully and independently create the most beautiful, visually compelling and contextually appropriate setting for that specific artwork.

The background must feel naturally connected to the artwork’s subject, theme, mood, colors, season, atmosphere and visual story.

You have FULL CREATIVE FREEDOM over the background.

Do not follow a predefined interior style, location, color palette, lighting setup, prop list, material, season, or environment type.

Do not default to a Scandinavian interior, generic room, white studio, wooden table, or any repeated product-mockup setting.

Instead, interpret IMAGE 2 first, then invent the scene from scratch.

The setting may be indoor, outdoor, architectural, natural, seasonal, lifestyle-based, atmospheric, minimal, elaborate, realistic, editorial, or something entirely different — whichever produces the strongest and most appropriate product preview for IMAGE 2.

Choose everything dynamically based on the artwork:

- environment and location
- surrounding objects and props
- surfaces and materials
- colors
- lighting
- atmosphere
- depth
- styling
- camera presentation

There are no fixed aesthetic restrictions for the environment.

The background does NOT need to literally reproduce the scene shown in the artwork. Instead, extend its visual world in a tasteful and believable way.

Make the calendar feel as though it was professionally photographed in an environment specifically art-directed for this exact cover.

The scene should enhance the artwork rather than merely sit behind it.

Avoid generic decoration added only to fill empty space. Every major environmental choice should make visual sense for IMAGE 2.

The calendar must remain clearly recognizable as the main product, but otherwise prioritize the strongest, most beautiful and commercially compelling scene possible.

IMPORTANT: Every time IMAGE 2 changes, reconsider the environment from scratch. Do not reuse the same background concept from previous images."""

SCENE_PROMPT = """Use the provided calendar image as the exact product reference.

Create a premium photorealistic product preview of this calendar while preserving the calendar itself exactly as shown.

## PRESERVE THE CALENDAR

Do not redesign or alter the calendar.

Keep unchanged:
- the exact calendar proportions and physical dimensions
- the page shape and orientation
- the spiral / wire-o binding
- all holes, binding loops and hardware
- the artwork, illustrations, typography, dates and calendar grid
- all text exactly as shown
- the original colors and printed design
- realistic paper thickness and page edges

The calendar design must remain visually identical to the source image.

## BACKGROUND — FULL CREATIVE FREEDOM

Replace the original background with a completely new environment.

First study the calendar artwork carefully and understand its:
- visual theme
- subject matter
- season
- mood
- artistic style
- color relationships
- atmosphere
- visual storytelling
- likely buyer aesthetic

Then independently invent the most beautiful, visually compelling and contextually appropriate background for THIS specific calendar.

You have FULL CREATIVE FREEDOM over the environment.

Do not follow any predefined interior style, location, palette, lighting setup, material, prop list, season or composition.

Do not automatically default to:
- a generic room
- Scandinavian interior
- beige wall
- white studio
- wooden desk
- shelf styling
- neutral home decor
- standard Etsy mockup scenes

Instead, let the calendar artwork determine the entire scene.

The background may be:
indoor, outdoor, architectural, natural, seasonal, atmospheric, editorial, lifestyle-based, surreal-but-photorealistic, minimalist, richly styled, intimate, expansive, bright, dramatic, warm, cool, rustic, elegant, modern, vintage, or something completely different.

Choose everything dynamically based on what makes the calendar look best:
- environment
- location
- surfaces
- surrounding objects
- decorative elements
- architecture
- materials
- lighting
- time of day
- season
- depth of field
- foreground and background layers
- camera angle
- framing
- composition
- visual density
- atmosphere

The environment should feel as though it was specifically art-directed around the calendar artwork rather than selected from a reusable mockup template.

## VISUAL INTEGRATION

Make the calendar feel naturally present in the environment.

Create physically believable:
- contact shadows
- ambient light
- reflected light
- perspective
- depth
- scale
- material interaction

Allow colors, textures, shapes or atmosphere from the calendar artwork to subtly inspire the environment, but do not literally duplicate the artwork into the background.

The setting should complement the product without competing with it.

The calendar must remain the clear focal point.

## CREATIVE GOAL

Produce the strongest possible commercial product preview for this exact calendar.

The final image should feel:
- highly art-directed
- premium
- visually memorable
- natural rather than staged
- emotionally consistent with the artwork
- suitable for an Etsy / Shopify hero image or advertisement

Avoid repetitive product-mockup conventions.

Make a fresh creative decision specifically for this calendar every time the prompt is used."""

# Preview 4 (04_two_wall_spreads): IMAGE 1 = tranh tháng 1 AI gốc, IMAGE 2 = mockup code 2 tờ treo tường. Đã duyệt 02/10/2026.
WALL_PROMPT = """## INPUTS

IMAGE 1 = the artwork. Use it ONLY as the style, theme and color reference for the new background.
IMAGE 2 = the photo to edit. It shows two open spiral-bound wall calendars hanging on a wall: the left one higher, the right one lower. Each calendar has an artwork page on top, a spiral binding in the middle and a monthly grid page below.

## TASK

Replace ONLY the background of IMAGE 2. The output is IMAGE 2 with a new background. Do not output IMAGE 1, and do not paste IMAGE 1 into the scene as a picture, poster, frame or extra page.

## PRESERVE THE CALENDARS — DO NOT REDESIGN

Keep both calendars exactly as they are in IMAGE 2:

- same position, size, angle, perspective and proportions (each open calendar is taller than it is wide)
- same printed artwork, month names, year, weekday names, grid lines, holiday labels and every date number, pixel-faithful; do not redraw, restyle, re-letter, translate, correct or "improve" anything printed on them
- do not replace what is printed on the calendars with IMAGE 1
- same spiral binding in the middle, same hanging holes at the top and bottom, same paper edges
- do not add, remove, move, rotate, resize, crop or cover any calendar

Nothing may overlap the calendars: no plants, leaves, objects, hands or decorations in front of them. Soft light and soft shadows falling across the pages are allowed, as long as every number and letter stays clearly readable.

## BACKGROUND — FULL CREATIVE FREEDOM

Replace the wall, the shelf and all objects around the calendars in IMAGE 2 with a completely new environment.

Study IMAGE 1 carefully and independently create the most beautiful, visually compelling and contextually appropriate setting for that specific artwork.

The background must feel naturally connected to the subject, theme, mood, colors, season, atmosphere and visual story of IMAGE 1.

Do not default to a Scandinavian interior, beige wall, white studio, wooden shelf with plants, or any repeated product-mockup setting. Interpret IMAGE 1 first, then invent the scene from scratch: the wall surface and material, surrounding objects and props, colors, lighting, time of day and atmosphere.

The calendars must still hang flat on a vertical surface, seen straight on, matching the camera angle of IMAGE 2. The background does NOT need to literally reproduce the scene shown in IMAGE 1; extend its visual world in a tasteful and believable way, as real photographed objects and surfaces, not as a drawn illustration.

Avoid generic decoration added only to fill empty space. Every environmental choice should make visual sense for IMAGE 1.

IMPORTANT: Every time IMAGE 1 changes, reconsider the environment from scratch. Do not reuse a background concept from previous images.

## PRODUCT EMPHASIS — THE CALENDARS MUST STAND OUT

- The two calendars are the heroes: the sharpest, brightest and most clearly lit elements in the frame.
- Keep the background calmer, slightly darker or softer, and lower in contrast and saturation than the printed artwork.
- Choose wall colors that separate clearly from the calendar edges; do not use colors or patterns that blend into the artwork.
- Keep props small, few and near the edges or the bottom of the frame.
- Add soft, realistic drop shadows behind each calendar on the wall, consistent with one light direction, so they hang naturally on the new surface.

## IMAGE FORMAT

Output a square 1:1 photo with the same framing as IMAGE 2. Photorealistic, professional product photography."""

# Preview 5 (06_three_books): IMAGE 1 = tranh tháng 4 AI gốc, IMAGE 2 = mockup code 3 cuốn đã ghép. Đã duyệt 02/10/2026.
BOOKS_PROMPT = """## INPUTS

IMAGE 1 = the artwork. Use it ONLY as the style, theme and color reference for the new background.
IMAGE 2 = the photo to edit. It shows three spiral-bound wall calendars lying on a plain dark green surface: a front cover (top left), a monthly grid page (top right) and a monthly artwork page (bottom).

## TASK

Replace ONLY the background of IMAGE 2. The output is IMAGE 2 with a new background. Do not output IMAGE 1, and do not paste IMAGE 1 into the scene as a picture, poster or extra page.

## PRESERVE THE CALENDARS — DO NOT REDESIGN

Keep all three calendars exactly as they are in IMAGE 2:

- same position, size, angle, perspective and proportions
- same printed artwork, title, lettering, month name, weekday names and every date number, pixel-faithful; do not redraw, restyle, re-letter, translate, correct or "improve" anything printed on them
- do not replace what is printed on the calendars with IMAGE 1
- same metal spiral binding, punched holes, hanging holes and paper thickness
- do not add, remove, move, rotate, crop or cover any calendar

Nothing may overlap the calendars. Props may only sit in the empty areas around and between them.

## BACKGROUND — FULL CREATIVE FREEDOM

Replace the plain green surface of IMAGE 2 with a completely new environment.

Study IMAGE 1 carefully and independently create the most beautiful, visually compelling and contextually appropriate setting for that specific artwork.

The background must feel naturally connected to the subject, theme, mood, colors, season, atmosphere and visual story of IMAGE 1.

Do not default to a generic wooden table, white studio or any repeated product-mockup setting. Interpret IMAGE 1 first, then invent the scene from scratch: the surface, materials, surrounding objects and props, colors, lighting and atmosphere.

The scene is a top-down flat lay, matching the camera angle of IMAGE 2. The background does NOT need to literally reproduce the scene shown in IMAGE 1; extend its visual world in a tasteful and believable way, as real photographed objects and surfaces, not as a drawn illustration.

Avoid generic decoration added only to fill empty space. Every environmental choice should make visual sense for IMAGE 1.

IMPORTANT: Every time IMAGE 1 changes, reconsider the environment from scratch. Do not reuse a background concept from previous images.

## PRODUCT EMPHASIS — THE CALENDARS MUST STAND OUT

- The three calendars are the heroes: the sharpest, brightest and most clearly lit elements in the frame.
- Keep the background calmer, slightly darker or softer, and lower in contrast and saturation than the printed artwork.
- Choose background colors that separate clearly from the calendar edges; do not use colors or patterns that blend into the artwork.
- Keep props small, few and near the edges of the frame.
- Add soft, realistic contact shadows under each calendar, consistent with one light direction, so they sit naturally on the new surface.

## IMAGE FORMAT

Output a square 1:1 photo with the same framing as IMAGE 2. Photorealistic, professional product photography."""

# Thêm vào cuối prompt: KHUNG ẢNH vuông 1:1 - chỉ khung ảnh, cuốn lịch giữ đúng tỉ lệ thật (không bị nắn thành vuông)
_SQUARE_HEAD = ("\n\n## IMAGE FORMAT\n\nThe OUTPUT IMAGE (the photo canvas) is square, 1:1. This applies ONLY to the "
                "photo canvas, NOT to the calendar. ")
_SQUARE_TAIL = (" Never make the calendar square, never stretch, squash or crop it. Fill the extra space of the square "
                "photo with the scene around the calendar.")
# bìa (preview 1): cuốn lịch đóng, khổ NGANG 11 x 8.5
SQUARE_COVER = (_SQUARE_HEAD + "The calendar is a closed LANDSCAPE wall calendar, wider than it is tall (11 x 8.5 inch, "
                "about 1.29:1), exactly like the calendar in IMAGE 1." + _SQUARE_TAIL)
# preview 2-4: giữ đúng dáng cuốn lịch trong ảnh đính kèm (lịch mở treo tường thì CAO hơn rộng)
SQUARE_SCENE = (_SQUARE_HEAD + "The calendar must keep exactly the same shape and proportions as in the provided image "
                "(an open wall calendar is taller than it is wide)." + _SQUARE_TAIL)

# preview đích -> (mockup code dùng làm ảnh kèm | None = preview bìa)
AI_PREVIEWS = {
    "01_front_cover_spiral": None,
    "02_open_spread_flat": "02_open_spread_flat",
    "03_three_open_spreads": "03_three_open_spreads",
    "04_two_wall_spreads": "04_two_wall_spreads",
    "06_three_books": "06_three_books",
}
# preview chỉ thay nền: IMAGE 1 = tranh AI gốc của tháng này, IMAGE 2 = mockup code của chính ảnh đó -> (tranh, prompt)
ART_PREVIEWS = {
    "04_two_wall_spreads": ("m01", WALL_PROMPT),
    "06_three_books": ("m04", BOOKS_PROMPT),
}
DROPPED = "05_wall_page_turn"         # chế độ AI mockup bỏ ảnh lật trang (04 = 2 tờ treo tường, 06 = 3 cuốn)
