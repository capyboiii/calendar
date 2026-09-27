"""Focused preflight for the six approved modern grid layouts."""
import copy
import json
import unittest
from pathlib import Path

from calforge.render.pages import grid_page
from calforge.render.preflight import check_page
from tests import fixtures


PRESETS = ("bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome",
           "organic_capsules", "playful_editorial")
ROOT = Path(__file__).resolve().parents[1]


def load_format() -> dict:
    return json.loads((ROOT / "formats" / "printify_wall_11x8_5" / "format.json").read_text(encoding="utf-8"))


class ModernGridRenderTest(unittest.TestCase):
    def test_all_presets_and_representative_months_pass_preflight(self):
        fmt = load_format()
        base = fixtures.concept()
        base.update(year=2027, market="US")
        for preset in PRESETS:
            concept = copy.deepcopy(base)
            concept["grid_preset"] = preset
            for month in (1, 6, 12):
                page = grid_page(fmt, concept, month, f"{preset}-{month}", "Short verse.")
                self.assertEqual(check_page(page, fmt), [], f"{preset}, month {month}")

    def test_each_preset_contains_no_image_layer(self):
        fmt = load_format()
        base = fixtures.concept()
        base.update(year=2027, market="US")
        for preset in PRESETS:
            concept = copy.deepcopy(base)
            concept["grid_preset"] = preset
            page = grid_page(fmt, concept, 3, preset, "Short verse.")
            self.assertEqual(check_page(page, fmt), [], preset)
            self.assertFalse(any(op[0] == "image" for op in page.ops))

    def test_capsule_holiday_labels_stay_inside_week_rows(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US", grid_preset="organic_capsules")
        page = grid_page(fmt, concept, 3, "capsule-overflow", "Short verse.")
        rows = [(op[1], op[2], op[1] + op[3], op[2] + op[4]) for op in page.ops
                if op[0] == "round_rect" and op[3] > 2000 and op[2] > 500]
        holidays = [text.bbox() for text in page.texts() if text.role == "holiday"]
        self.assertTrue(holidays)
        for box in holidays:
            self.assertTrue(any(row[0] <= box[0] and box[2] <= row[2] and
                                row[1] <= box[1] and box[3] <= row[3] for row in rows), box)


if __name__ == "__main__":
    unittest.main()
