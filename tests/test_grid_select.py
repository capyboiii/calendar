import copy
import json
import unittest
from pathlib import Path

from calforge.render.grid_select import apply_grid_selection, recommend_grid
from calforge.render.pages import grid_page
from calforge.render.preflight import check_page
from tests import fixtures


ROOT = Path(__file__).resolve().parents[1]


class GridSelectionTest(unittest.TestCase):
    def test_prayer_calendar_gets_side_panel(self):
        c = fixtures.concept()
        c["style"]["family"] = "styled_photography"
        self.assertEqual(recommend_grid(c)["selected"], "bento_planner")

    def test_papercut_affirmation_gets_organic_capsules(self):
        c = fixtures.concept()
        c["style"]["family"] = "papercut_collage"
        c["grid_function"] = "standard"
        c["content_type"] = "affirmation"
        self.assertEqual(recommend_grid(c)["selected"], "organic_capsules")

    def test_mid_century_gets_retro_banner(self):
        c = fixtures.concept()
        c["style"]["family"] = "mid_century_retro"
        c["grid_function"] = "standard"
        c["content_type"] = "none"
        c["buyer"] = "young creative travelers"
        self.assertEqual(recommend_grid(c)["selected"], "playful_editorial")

    def test_manual_override_is_preserved(self):
        c = fixtures.concept()
        result = apply_grid_selection(c, requested="soft_tech")
        self.assertEqual(result["mode"], "manual")
        self.assertEqual(c["grid_preset"], "soft_tech")
        self.assertFalse(result["grid_uses_shared_artwork"])

    def test_ai_grid_defaults_to_editorial_shared_page(self):
        c = fixtures.concept()
        result = apply_grid_selection(c, requested="auto")
        self.assertTrue(result["grid_uses_shared_artwork"])
        self.assertEqual(c["style"]["grid_page_mode"], "editorial_illustration")

    def test_every_preset_renders_without_artwork_or_ornament(self):
        fmt = json.loads((ROOT / "formats" / "printify_wall_11x8_5" / "format.json").read_text(encoding="utf-8"))
        c = fixtures.concept()
        c.update(year=2027, market="US")
        for preset in ("bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome",
                       "organic_capsules", "playful_editorial"):
            concept = copy.deepcopy(c)
            apply_grid_selection(concept, requested=preset)
            page = grid_page(fmt, concept, 3, f"{preset} preview", "The LORD is my shepherd.")
            self.assertEqual(check_page(page, fmt), [], preset)
            self.assertFalse(any(op[0] == "image" for op in page.ops))


if __name__ == "__main__":
    unittest.main()
