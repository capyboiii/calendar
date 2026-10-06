"""Prompt cho "AI gen mockup" (chỉ Wall Calendar (Blank) chế độ "AI vẽ cả trang"). Giữ NGUYÊN VĂN theo người dùng.

Preview 1: đính kèm IMAGE 1 = khung mockup bìa lò xo (data/mockups/front_cover_spiral_v2.webp),
           IMAGE 2 = tranh bìa AI gốc của cuốn (_he_thong/anh_ai/cover.*).
Preview 2: đính kèm mockup code đã ghép của cuốn (02_open_spread_flat) - AI giữ nguyên cuốn lịch, thay bối cảnh.
Preview 3: IMAGE 1 = tranh tháng 2 AI gốc (anh_ai/m02.*), IMAGE 2 = mockup code 03_three_open_spreads (tháng 2, 3, 4).
Preview 4: IMAGE 1 = tranh tháng 5 AI gốc (_he_thong/anh_ai/m05.*), IMAGE 2 = mockup code 04_two_wall_spreads (2 tờ
           lịch mở treo tường: tháng 5, tháng 6) - AI chỉ thay nền theo tranh.
Preview 5: IMAGE 1 = tranh tháng 7 AI gốc (_he_thong/anh_ai/m07.*), IMAGE 2 = mockup code 06_three_books (tranh
           tháng 7 + trang lịch tháng 8 + tranh tháng 8) - AI chỉ thay nền theo tranh.
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

# Preview 3 (03_three_open_spreads): IMAGE 1 = tranh tháng 2 AI gốc, IMAGE 2 = mockup code 3 tờ lịch mở (tháng 2, 3, 4)
SPREADS_PROMPT = """## TASK: BACKGROUND REPLACEMENT EDIT (not a new picture)

Edit IMAGE 2. Keep the three open calendars in IMAGE 2 exactly as they are and repaint ONLY the area around them.
Work as if the three calendars were a locked, cut-out layer lying on top of the photo: you may change everything
underneath and around that layer, but nothing inside its outline.

IMAGE 1 = a monthly artwork of this calendar. Use it ONLY as inspiration for the mood, colors and theme of the new
background.
IMAGE 2 = the photo to edit: three open spiral-bound wall calendars lying at slight angles on a table, partly
overlapping. Each one shows a monthly artwork page on top, the spiral binding in the middle and that month's date
grid page below.

## LOCKED: THE THREE CALENDARS (highest priority - more important than the background)

Inside the outline of each calendar, everything must stay identical to IMAGE 2:
- the printed artwork, month names, year, weekday names, every date number and holiday label, with the same font,
  size, color and position; every number stays in the same grid cell
- the position, size, angle, perspective, overlap order and proportions of each calendar
- the metal spiral binding, punched holes, hanging holes, paper edges and paper thickness
Do NOT redraw, repaint, re-render, re-light, recolor, sharpen, blur, upscale, restyle, translate, correct or "improve"
anything printed on the calendars. Do not replace any calendar page with IMAGE 1. Do not add, remove, move, rotate,
crop or resize any calendar. Nothing may overlap the calendars: no props, hands, leaves, petals, light rays,
reflections, glare or shadows on top of them.
If you are unsure whether a detail inside a calendar would change, leave it exactly as in IMAGE 2.

## BACKGROUND (only outside the calendars)

Replace the table and everything around the calendars with a new, real photographed setting inspired by IMAGE 1:
choose the surface, materials, a few props, colors and lighting that fit its theme, mood and season. Keep the same
camera angle and the same framing as IMAGE 2. Real objects and surfaces, not a drawn illustration, and do not paste
IMAGE 1 into the scene as a print, poster or extra page. Do not default to a generic wooden table or white studio;
every time IMAGE 1 changes, invent a new setting.

## MAKE THE CALENDARS STAND OUT - BY CHANGING THE BACKGROUND ONLY

- Keep the background calmer, softer and a little darker or lower in contrast and saturation than the calendars,
  with colors that separate clearly from the calendar edges.
- Keep props few and small, only in the empty space around the calendars, near the edges of the frame.
- Only soft contact shadows on the new surface right at the calendar edges; never shade or tint the calendars.

## FINAL CHECK BEFORE YOU ANSWER

Compare each calendar in your result with IMAGE 2: same artwork, same month names and year, same date numbers in the
same grid cells, same spiral and holes. If anything inside a calendar changed, restore it from IMAGE 2.

## IMAGE FORMAT

Output a square 1:1 photo with the same framing as IMAGE 2. Photorealistic, professional product photography."""

# Preview 7 (08_wall_and_back): IMAGE 1 = tranh tháng 12 AI gốc, IMAGE 2 = mockup code tờ treo tường tháng 12 + bìa sau.
# Người dùng duyệt 06/10/2026.
WALL_BACK_PROMPT = """## TASK: BACKGROUND REPLACEMENT EDIT (not a new picture)

Edit IMAGE 2. Keep the two calendars in IMAGE 2 exactly as they are and repaint ONLY the area around them.
Work as if the two calendars were a locked, cut-out layer on top of the photo: you may change everything
behind and around that layer, but nothing inside its outline.

IMAGE 1 = the December artwork of this calendar. Use it ONLY as inspiration for the mood, colors and theme of
the new background.
IMAGE 2 = the photo to edit: an open spiral-bound wall calendar hanging on a wall from a small hook (December
artwork on top, spiral binding in the middle, December date grid below), and in front of it a closed
spiral-bound calendar leaning at an angle, showing its back cover with the title and 12 small monthly
pictures.

## LOCKED: THE TWO CALENDARS (highest priority - more important than the background)

Inside the outline of each calendar, everything must stay identical to IMAGE 2:
- the printed artwork, the title, year, month names, captions and every date number, with the same font,
  size, color and position; the 12 small pictures on the back cover stay the same 12 pictures in the same grid
- the position, size, angle, perspective, overlap and proportions of both calendars; the front calendar keeps
  covering the same part of the hanging one
- the metal spiral bindings, the hanging hook, the hanging hole of the front calendar, paper edges and paper
  thickness
Do NOT redraw, repaint, re-render, re-light, recolor, sharpen, blur, upscale, restyle, translate, correct or
"improve" anything printed on the calendars. Do not replace any page with IMAGE 1. Do not add, remove, move,
rotate, crop or resize any calendar. Nothing may overlap the calendars: no props, leaves, garlands, lights,
reflections, glare or shadows on top of them.
If you are unsure whether a detail inside a calendar would change, leave it exactly as in IMAGE 2.

## BACKGROUND (only outside the calendars)

Replace the wall, the floor and the plant with a new, real photographed setting inspired by IMAGE 1 and its
December mood: choose the wall surface, the surface the front calendar leans on, a few props, colors and
lighting that fit its theme and season. Keep the same straight-on camera and the same framing as IMAGE 2.
Real objects and surfaces, not a drawn illustration, and do not paste IMAGE 1 into the scene as a print,
poster or extra page. Do not default to a generic beige wall, white studio or wooden floor; every time
IMAGE 1 changes, invent a new setting.

## MAKE THE CALENDARS STAND OUT - BY CHANGING THE BACKGROUND ONLY

- Keep the background calmer, softer and a little darker or lower in contrast and saturation than the
  calendars, with colors that separate clearly from the calendar edges.
- Keep props few and small, only in the empty space around the calendars, near the edges of the frame.
- Only soft contact shadows behind the hanging calendar and under the leaning one; never shade or tint the
  calendars themselves.

## FINAL CHECK BEFORE YOU ANSWER

Compare both calendars in your result with IMAGE 2: same December artwork and date numbers, same title and
year on the back cover, same 12 small pictures and month names, same spirals, hook and hole. If anything inside a
calendar changed, restore it from IMAGE 2.

## IMAGE FORMAT

Output a square 1:1 photo with the same framing as IMAGE 2. Photorealistic, professional product photography."""

# Preview 4 (04_two_wall_spreads): IMAGE 1 = tranh tháng 5 AI gốc, IMAGE 2 = mockup code 2 tờ treo tường. Đã duyệt 02/10/2026.
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

# Preview 5 (06_three_books): IMAGE 1 = tranh tháng 7 AI gốc, IMAGE 2 = mockup code 3 cuốn đã ghép. Đã duyệt 02/10/2026.
BOOKS_PROMPT = """## TASK: BACKGROUND REPLACEMENT EDIT (not a new picture)

Edit IMAGE 2. Keep the three calendars in IMAGE 2 exactly as they are and repaint ONLY the area around them.
Work as if the three calendars were a locked, cut-out layer lying on top of the photo: you may change everything
underneath and around that layer, but nothing inside its outline.

IMAGE 1 = the monthly artwork. Use it ONLY as inspiration for the mood, colors and theme of the new background.
IMAGE 2 = the photo to edit: three spiral-bound wall calendars lying flat on a plain dark green surface - a monthly
artwork page (top left), a monthly date grid page (top right) and another monthly artwork page (bottom).

## LOCKED: THE THREE CALENDARS (highest priority - more important than the background)

Inside the outline of each calendar, everything must stay identical to IMAGE 2:
- the printed artwork, every title, word, letter, year, month name and caption, with the same font, size, color and
  position; every date number, weekday name and holiday label on the grid page stays in the same cell
- the position, size, angle, perspective and proportions of each calendar
- the metal spiral binding, punched holes, hanging holes, paper edges and paper thickness
Do NOT redraw, repaint, re-render, re-light, recolor, sharpen, blur, upscale, restyle, translate, correct or "improve"
anything printed on the calendars. Do not replace any calendar page with IMAGE 1. Do not add, remove, move, rotate,
crop or resize any calendar. Nothing may overlap the calendars: no props, hands, leaves, petals, light rays,
reflections, glare or shadows on top of them.
If you are unsure whether a detail inside a calendar would change, leave it exactly as in IMAGE 2.

## BACKGROUND (only outside the calendars)

Replace the plain green surface with a new, real photographed setting inspired by IMAGE 1: choose the surface,
materials, a few props, colors and lighting that fit its theme, mood and season. Keep the same top-down flat-lay
camera and the same framing as IMAGE 2. Real objects and surfaces, not a drawn illustration, and do not paste
IMAGE 1 into the scene as a print, poster or extra page. Do not default to a generic wooden table or white studio;
every time IMAGE 1 changes, invent a new setting.

## MAKE THE CALENDARS STAND OUT - BY CHANGING THE BACKGROUND ONLY

- Keep the background calmer, softer and a little darker or lower in contrast and saturation than the calendars,
  with colors that separate clearly from the calendar edges.
- Keep props few and small, only in the empty space between and around the calendars, near the edges of the frame.
- Only soft contact shadows on the new surface right at the calendar edges; never shade or tint the calendars.

## FINAL CHECK BEFORE YOU ANSWER

Compare each calendar in your result with IMAGE 2: same titles and spelling, same year, same month names, same
artwork, same date numbers in the same grid cells, same spiral and holes. If anything inside a calendar changed,
restore it from IMAGE 2.

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
    "07_three_open_spreads_fall": "07_three_open_spreads_fall",
    "08_wall_and_back": "08_wall_and_back",
}
# preview chỉ thay nền: IMAGE 1 = tranh AI gốc của tháng này, IMAGE 2 = mockup code của chính ảnh đó -> (tranh, prompt)
ART_PREVIEWS = {
    "03_three_open_spreads": ("m02", SPREADS_PROMPT),     # ghép tháng 2, 3, 4 - kèm tranh tháng 2
    "04_two_wall_spreads": ("m05", WALL_PROMPT),          # ghép tháng 5, 6 - kèm tranh tháng 5
    "07_three_open_spreads_fall": ("m09", SPREADS_PROMPT),   # preview 6: cơ chế preview 3, ghép tháng 9, 10, 11
    "08_wall_and_back": ("m12", WALL_BACK_PROMPT),           # preview 7: treo tường tháng 12 + bìa sau
    "06_three_books": ("m07", BOOKS_PROMPT),            # ghép tranh T7, lịch T8, tranh T8 - kèm tranh tháng 7
}
DROPPED = "05_wall_page_turn"         # chế độ AI mockup bỏ ảnh lật trang (04 = 2 tờ treo tường, 06 = 3 cuốn)
