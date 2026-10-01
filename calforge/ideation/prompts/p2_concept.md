You are the art director turning an approved calendar angle into a production-ready concept.

FIXED FACTS (computed by software — treat as truth, do not change):
- Year: {{year}}
- Market: {{market_label}}
- Holidays and dates this year, by month (season in brackets):
{{calendar_facts}}
- Allowed fonts: title = {{fonts_title}}; body = {{fonts_body}}; numbers = {{fonts_numbers}}
- Shot type assigned to each month (use it, do not change it):
{{month_shots}}

APPROVED ANGLE:
{{angle_json}}

BUYER-LED ART DIRECTION (the creative source of truth): {{style}}
STYLE FAMILY: {{family_name}}. Preserve the buyer-led subject, palette and composition while visibly using this approved rendering method.

TASK
Expand the angle into a complete concept for 12 months (Jan..Dec), a front cover and a back cover.
Use buyer_expectation as the subject guide; for older angles without it, infer the expected subject from the approved angle's title, hook and buyer. Choose scenes freely around that subject, with style serving its portrayal. Before returning the JSON, check that the cover and all 12 scenes deliver what this buyer expects to see, and revise any drift within this same response. Keep this check internal: no extra report or output fields.

HOW TO DESIGN EACH MONTH (follow this order — the artwork must SAY what the month is about)
Step 1. "theme": one sentence — how THIS month expresses the calendar's central promise (the angle's title and hook) for THIS buyer. Every month is a new facet of that one idea, never just the season or the holiday.
Step 2. "subtitle" and "content": written for that theme.
Step 3. "focal_subject": the ONE concrete, recognizable subject or action that carries the theme — a specific thing a viewer can point at, specific to this niche (e.g. "a grandmother and granddaughter rolling cookie dough at a floured table", "a hen leading three fluffy chicks out of a red coop", "two hikers reaching a ridge at sunrise", "a wooden boat on water that has just gone calm under parting storm clouds", "a gardener's hands pressing tulip bulbs into dark soil"). Choose the subject TYPE that tells the theme best — people in a moment, animals, a place, or an object — and mix these types across the 12 months instead of making every month a still life of objects, unless the angle is literally about objects. Glance test: a stranger who sees only the artwork should be able to guess both the month's theme and the calendar's overall idea.
Step 4. "holiday_symbol": if the month has a "holiday_tie", one small, recognizable symbol of that holiday that fits this niche and buyer (for faith niches use the religious meaning of the holiday); otherwise "". It is a secondary detail only, never the focal subject.
Step 5. "scene": build the picture AROUND the focal subject. Start the scene with the focal subject, then setting, season cues, holiday symbol (small, secondary), time of day, lighting.

RULES
1. Every month is unique and fits its season. Tie a month to a holiday only when that holiday genuinely serves the calendar's central idea; the calendar is not a holiday calendar. If a month is tied to a holiday, place it in the month where that holiday ACTUALLY falls in {{year}} according to FIXED FACTS, and put the holiday name exactly as written in FIXED FACTS into "holiday_tie". Otherwise "holiday_tie" is "none".
2. Focal subjects must be specific to the niche and buyer expectation. When the buyer expects a central person, artist or performer, portray them visibly as the focal hero with authentic facial expression, gaze, styling, and presence across meaningful actions, outfits, and settings; do not degrade the subject into anonymous hands, cropped backs, or faceless accessories unless the concept is explicitly about inanimate objects. For a collection of different subjects, choose a specific, named example for each month.
3. "content" must be about the same thing the artwork shows: a tip about what is pictured, a fact about what is pictured, a verse/quote whose words or story match what is pictured.
4. Frame type guidance: seasonal = the same niche subject doing this month's seasonal activity; collection = this month's member of the set is the focal subject; journey = this month's moment of the story; one_scene_12_seasons = the same place, and the focal subject is what changes this month (a wreath on the door, a nest in the tree); word_of_month = a concrete visual metaphor of the word, never an abstract mood.
5. "scene" describes visual content, 25 to 45 words. When portraying people or performers, describe their facial expressions, gaze, charismatic styling, and emotional presence across varied camera angles (portraits, 3/4 profiles, performance moments); do not crop away their face, head, or eyes. Choose people, facial expressions, viewing angles, subject details and in-scene lettering to serve the approved concept.
6. Shot types are assigned by software (FIXED FACTS) so the 12 artworks clearly differ in camera and framing. Write each month's "scene" and "composition_note" for its assigned shot type: viewpoint, crop and arrangement must visibly match it. The assigned shot description is the maximum permitted amount of negative space: never intensify it in `scene` or `composition_note`, and never reduce the focal subject below the size specified by that shot. For calendars centered on a person, artist or performer, do not use phrases such as "small subject", "tiny figure", "abundant negative space", "vast empty field", "broad empty field" or "isolated in open space". For `minimal_space`, preserve the specified 40–55% focal-subject occupancy and 35–45% intentional open space; for `hero_subject`, keep the subject large and off-center without requiring the opposite side to be blank. Do not carry one framing device (window, porch, railing, sill, doorway, table edge) through the months unless the angle is built on that object (e.g. a calendar about doors); then show that signature object every month in a new form, and let the shot type change how it is seen. For one_scene_12_seasons the same place must stay recognizable every month: the shot type changes distance and angle within that place, never the place itself. `artwork_composition_system` describes only the collection's shared visual rhythm—how color, light and edges are handled—never a fixed viewpoint, camera setup or framing device. It must require balanced breathing room without large unused fields, and must not request generous, abundant or expansive negative space. Keep indispensable content inside the central 80% horizontal print-safe area and away from binding hardware; this does not mean centering.
7. The recurring motif from the angle appears small in every month ("motif_placement"), placed naturally for that month's shot: its position and the object or surface it sits on change from month to month, and it must never require the same object or setting each time. It is decoration, never the focal subject.
8. "color_story": the 3-4 named colors that define THIS calendar's look, chosen freely for what best fits this subject, buyer and art direction — only color names here, no hex codes or notes.
   {{base_tone_rule}}
   Choose one `shared_base_color` with a specific name and hex value. This is the SAME shared ground/surface hue across the cover and all 12 artworks. It covers roughly one third of every image, not the whole page; the rest belongs to subjects in the other palette colors. Monthly variety comes from subjects, crops, lighting and accent colors—not by rotating the entire background through different palette hues. Do not name conflicting full-page background colors in monthly scenes. The shared grid uses a quieter tint of this exact base hue.
9. "style_bible": one paragraph, 60 to 90 words that faithfully operationalizes the BUYER-LED ART DIRECTION: medium and rendering technique, mark-making, lighting, texture, the chosen artwork composition system, surface treatment, and the color story colors by name. Require a positive, welcoming result with clear, readable lighting; mid-tones and rich color are welcome, gloomy or murky results are not. For Styled photography explicitly require natural daylight and forbid night scenes, dark rooms and candle-lit low-key setups. Name the shared base color but describe it as covering about one third of the image, never as a dominant or full-bleed base. It must NOT mention any subject — it is reused verbatim in every image prompt.
   "surface_system" is one concise sentence naming the collection's distinctive full-bleed substrate/background logic. It must follow the buyer-led art direction. This system will also guide the shared grid background.
10. Palette: 5 hex colors taken from the color story. "background" is the page background of the date-grid pages: a light pastel tint of shared_base_color (about 88–93% lightness) whose hue is still clearly recognizable, so the grid matches the artwork (not plain white or a washed-out neutral). "title" and "text" must both be dark colors and contrast strongly with "background" (WCAG ratio at least 4.5:1). Never choose light text with a dark grid background.
11. Fonts: only from the allowed lists above.
12. Monthly content ("content"), following the angle's content_type:
   - bible_verse_kjv: "value" is the reference ONLY (e.g. "Mark 4:39" or "Psalms 23:1-2"), never the verse text; the verse must match both the focal subject and the calendar's central idea.
   - practical_tip / fun_fact / affirmation: one sentence, max 20 words, factually safe and general.
   - quote (legacy content_type public_domain_quote is also accepted): a short, accurately attributed quotation that fits the theme and available text space.
   - none: "value" is "".
   Always add "subtitle": 2 to 5 words in the spirit of the month.
13. Cover: title max 5 words, subtitle max 8 words, neither containing the year (software prints it once), plus one cover scene (same rules as months). Back cover: one short line.
14. Listing: seo_title max 140 characters; exactly 13 tags, each max 20 characters, lowercase.
15. Choose one `grid_composition`: where the month title and copy sit on the date-grid pages. The grid background has no decorative motifs; this only sets text placement, reused for all 12 grid pages (code supplies exact calendar geometry). Pick what suits the buyer and wall setting, and vary it across concepts. Current portfolio usage is: {{grid_composition_usage}}; when two options suit equally well, prefer the less-used one. Allowed values:
   - `art_right_title_left`: title and copy left-aligned.
   - `art_left_title_right`: title and copy right-aligned.
   - `art_corner_pair_title_center`: centered title and copy.
   - `art_top_center_title_center`: centered title and copy set a little lower.
   - `art_bottom_corners_title_center`: centered title and copy with a quiet header.
16. `fingerprint`: a very short summary the shop uses to avoid future duplicates. "promise" = the book's emotional promise in at most 8 words; "subject_world" = the kind of subjects/places it shows in at most 6 words (e.g. "shoreline edges, lakes and marshes"); "months" = exactly 12 labels of 2–4 words naming each month's focal subject (e.g. "tide pool shells").

OUTPUT
Return ONLY one ```json code block and no other text, following exactly this schema:
```json
{
  "title": "",
  "angle_id": "",
  "frame_type": "",
  "buyer": "",
  "fingerprint": {"promise": "", "subject_world": "", "months": ["", "", "", "", "", "", "", "", "", "", "", ""]},
  "content_type": "",
  "grid_function": "",
  "style": {
    "name": "",
    "color_story": "",
    "shared_base_color": {"name": "", "hex": "#000000"},
    "style_bible": "",
    "surface_system": "",
    "artwork_composition_system": "",
    "grid_composition": "",
    "palette": {"background": "#FFFFFF", "title": "#000000", "text": "#000000", "accent": "#000000", "grid_line": "#000000"},
    "fonts": {"title": "", "body": "", "numbers": ""},
    "recurring_motif": ""
  },
  "cover": {"title": "", "subtitle": "", "scene": ""},
  "months": [
    {
      "month": 1,
      "theme": "",
      "subtitle": "",
      "content": {"type": "", "value": ""},
      "focal_subject": "",
      "holiday_tie": "none",
      "holiday_symbol": "",
      "season_cue": "",
      "scene": "",
      "motif_placement": "",
      "composition_note": ""
    }
  ],
  "back_cover": {"line": ""},
  "listing": {"seo_title": "", "tags": []}
}
```
"months" must contain exactly 12 objects, month 1 to 12 in order.
