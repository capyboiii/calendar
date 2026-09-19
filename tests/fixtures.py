"""Dữ liệu mẫu hợp lệ cho test: 1 góc tiếp cận và 1 concept "A Year with Jesus" 2027."""
import copy

SCENES = [
    "Jesus standing waist deep in the Jordan River at dawn, a white dove descending through soft golden light, reeds along the bank, gentle ripples, winter haze over distant hills",
    "A joyful wedding feast at Cana under a vine covered courtyard, stone water jars glowing, lanterns and flowers on long wooden tables, warm evening light and guests celebrating",
    "An empty rock tomb at sunrise with the great round stone rolled aside, spring lilies blooming at the entrance, first rays of light spilling across a quiet garden path",
    "Two travellers walking a winding country road toward Emmaus beside green spring fields, almond trees in blossom, soft afternoon clouds drifting over gentle rolling hills",
    "Jesus seated on a grassy slope blessing small children gathered around him, mothers smiling nearby, wildflowers covering the meadow, bright late spring morning sunshine",
    "A small fishing boat on the stormy Sea of Galilee suddenly calmed, dark clouds parting overhead, water turning glassy, a beam of summer light breaking through",
    "A vast crowd seated on a green hillside by the lake sharing baskets of bread and fish, midsummer evening glow, boats resting on the shore below",
    "Jesus walking on shimmering moonlit water toward a wooden boat, a disciple reaching out his hand, warm late summer night with scattered stars above",
    "A farmer scattering seed across a golden harvest field, birds circling, sheaves of wheat stacked nearby, early autumn sun low over a stone boundary wall",
    "The Good Shepherd carrying a lamb across autumn hills, a flock following along a rocky path, olive trees turning silver in crisp amber evening light",
    "A simple upper room table with broken bread and a clay cup, candlelight flickering, autumn leaves visible through an arched window, calm reverent atmosphere of thanksgiving",
    "A humble stable in Bethlehem under a bright star on a cold winter night, a manger with soft hay, shepherds approaching quietly across frosted fields",
]
FOCAL = [
    "Jesus standing in the Jordan River as a white dove descends",
    "a joyful wedding feast with glowing stone water jars",
    "an empty rock tomb with the great round stone rolled aside",
    "two travellers walking a country road toward Emmaus",
    "Jesus seated on a slope blessing small children",
    "a small fishing boat on the Sea of Galilee suddenly calmed",
    "a crowd sharing baskets of bread and fish",
    "Jesus walking on moonlit water toward a boat",
    "a farmer scattering seed across a harvest field",
    "the Good Shepherd carrying a lamb",
    "broken bread and a clay cup on an upper room table",
    "a manger in a Bethlehem stable under a bright star",
]
HOLIDAY_SYMBOL = {1: "flowers on long wooden tables", 2: "spring lilies at the entrance", 4: "mothers smiling nearby",
                  10: "candlelight flickering on the table", 11: "a bright star over the stable"}
REFS = ["Matthew 3:17", "John 2:11", "Matthew 28:6", "Luke 24:32", "Mark 10:14", "Mark 4:39",
        "John 6:35", "Matthew 14:27", "Mark 4:20", "John 10:11", "Luke 22:19", "Luke 2:11"]
TIES = ["none", "Valentine's Day", "Easter", "none", "Mother's Day", "none",
        "none", "none", "none", "none", "Thanksgiving", "Christmas Day"]

STYLE_BIBLE = (
    "Loose premium watercolor on cold-press paper with soft blooms, gentle granulation and "
    "delicate pencil underdrawing. Warm golden morning light, muted sage and olive greens, soft "
    "peach and apricot skies, warm ivory paper tones with small touches of antique gold. "
    "Transparent layered washes, lost and found edges, generous white space, calm reverent mood, "
    "hand painted feel with visible brush texture and a restrained, elegant palette throughout "
    "every illustration in the series."
)

ANGLE = {
    "id": "a1", "title": "A Year with Jesus", "hook": "Walk through the life of Jesus, one month at a time.",
    "buyer": "Christian mothers and grandmothers", "frame_type": "journey",
    "why_different": "Story order mapped to real seasons and holidays",
    "months_sketch": [f"{m}: scene" for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]],
    "recurring_motif": "a small olive sprig", "content_type": "bible_verse_kjv",
    "grid_function": "prayer_list", "style_family": "watercolor_gouache",
    "suggested_styles": ["soft watercolor", "loose gouache"],
    "ai_feasibility": {"score": 4, "risk": "faces may vary slightly"}, "ip_risk": "none",
}


def angles_payload():
    risky = copy.deepcopy(ANGLE)
    risky.update(id="a2", title="Risky one", ip_risk="high", style_family="linocut_print")
    weak = copy.deepcopy(ANGLE)
    weak.update(id="a3", title="Hard to draw", ai_feasibility={"score": 2, "risk": "breed details"},
                style_family="vintage_engraving")
    return {"keyword": "christian", "angles": [copy.deepcopy(ANGLE), risky, weak]}


def concept():
    return {
        "title": "A Year with Jesus", "angle_id": "a1", "frame_type": "journey",
        "buyer": "Christian mothers", "content_type": "bible_verse_kjv", "grid_function": "prayer_list",
        "style": {
            "name": "Soft Watercolor", "color_story": "sage green, apricot, warm ivory, antique gold",
            "style_bible": STYLE_BIBLE,
            "palette": {"paper": "#F7F1E4", "title": "#3B2F25", "text": "#2E2A26",
                        "accent": "#9B7253", "grid_line": "#CDBB9D"},
            "fonts": {"title": "Cormorant Garamond", "body": "Montserrat", "numbers": "Lora"},
            "recurring_motif": "a small olive sprig",
        },
        "cover": {"title": "A Year with Jesus", "subtitle": "Faith Hope Love",
                  "scene": "Jesus walking along a sunlit path through olive groves toward a quiet village, "
                           "golden morning light, soft hills, a lamb following closely, peaceful and warm atmosphere"},
        "months": [
            {"month": i + 1, "theme": f"A moment from the life of Jesus for month {i + 1}",
             "focal_subject": FOCAL[i], "holiday_symbol": HOLIDAY_SYMBOL.get(i, ""),
             "scene": SCENES[i], "season_cue": "season", "holiday_tie": TIES[i],
             "motif_placement": "olive sprig in a lower corner", "composition_note": "",
             "subtitle": "Walk in His light", "content": {"type": "bible_verse_kjv", "value": REFS[i]}}
            for i in range(12)
        ],
        "back_cover": {"line": "Twelve moments from the life of Jesus"},
        "ornament": {"description": "a watercolor olive branch with small dark olives"},
        "listing": {"seo_title": "2027 Christian Wall Calendar | A Year with Jesus | Watercolor Bible Verse Calendar",
                    "tags": ["christian calendar", "bible calendar", "2027 calendar", "jesus calendar",
                             "faith gift", "scripture calendar", "watercolor art", "wall calendar",
                             "church gift", "mom gift", "grandma gift", "prayer calendar", "kjv verses"]},
    }
