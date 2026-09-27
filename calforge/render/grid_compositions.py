"""Safe visual compositions for AI background + exact code-rendered calendar content."""
from __future__ import annotations


COMPOSITIONS = {
    "art_right_title_left": {
        "title_align": "start", "title_y": 235, "grid_top": .35, "quote_width": 1900,
        "prompt": ("Place one compact cluster of subordinate decorative motifs in the upper-right zone "
                   "(x=64–88%, y=3–25%). Keep the upper-left area open for a left-aligned title and copy."),
    },
    "art_left_title_right": {
        "title_align": "end", "title_y": 235, "grid_top": .35, "quote_width": 1900,
        "prompt": ("Place one compact cluster of subordinate decorative motifs in the upper-left zone "
                   "(x=12–36%, y=3–25%). Keep the upper-right area open for a right-aligned title and copy."),
    },
    "art_corner_pair_title_center": {
        "title_align": "middle", "title_y": 235, "grid_top": .35, "quote_width": 2200,
        "prompt": ("Use two restrained, related clusters of subordinate decorative motifs in the upper-left and upper-right "
                   "corners (each within the outer 22% width and above y=24%). Leave the upper center open "
                   "for a centered title and copy."),
    },
    "art_top_center_title_center": {
        "title_align": "middle", "title_y": 335, "grid_top": .39, "quote_width": 2200,
        "prompt": ("Place one small horizontal arrangement of subordinate decorative motifs at the top center "
                   "(x=38–62%, y=2–13%). Leave clear paper beneath it for a centered title and copy."),
    },
    "art_bottom_corners_title_center": {
        "title_align": "middle", "title_y": 235, "grid_top": .35, "quote_width": 2200,
        "prompt": ("Keep the entire header free of imagery. Place only two small related decorative motif accents at "
                   "the extreme bottom corners, below y=90% and outside x=8–92%. The title and copy are centered."),
    },
}

DEFAULT = "art_right_title_left"


def get_composition(style: dict) -> tuple[str, dict]:
    key = style.get("grid_composition", DEFAULT)
    if key not in COMPOSITIONS:
        key = DEFAULT
    return key, COMPOSITIONS[key]
