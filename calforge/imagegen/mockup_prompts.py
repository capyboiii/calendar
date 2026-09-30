"""Prompt cho "AI gen mockup" (chỉ Wall Calendar (Blank) chế độ "AI vẽ cả trang"). Giữ NGUYÊN VĂN theo người dùng.

Preview 1: đính kèm IMAGE 1 = khung mockup bìa lò xo (data/mockups/front_cover_spiral.webp),
           IMAGE 2 = tranh bìa AI gốc của cuốn (_he_thong/anh_ai/cover.*).
Preview 2, 3, 4: đính kèm mockup code đã ghép của cuốn (02_open_spread_flat, 03_three_open_spreads,
           05_wall_page_turn) - AI giữ nguyên cuốn lịch, thay bối cảnh.
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
    "05_wall_page_turn": "05_wall_page_turn",
}
DROPPED = "04_wall_spread"            # chế độ AI mockup chỉ còn 4 ảnh
