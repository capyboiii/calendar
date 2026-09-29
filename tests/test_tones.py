import json
import tempfile
import unittest
from pathlib import Path

from calforge import layout
from calforge.ideation import tones


def book(root: Path, name: str, hex_color: str, product: str = "wall_grid") -> None:
    c = root / "Wall Calendar (Blank)" / "kw" / name
    layout.ensure_system(c)
    layout.concept_file(c).write_text(json.dumps({
        "product": product, "style": {"shared_base_color": {"name": "x", "hex": hex_color}}}), encoding="utf-8")


class TonesTest(unittest.TestCase):
    def test_classify_real_colors(self):
        self.assertEqual(tones.classify("#F4ECE4"), "cream")
        self.assertEqual(tones.classify("#F2DDDA"), "blush")
        self.assertEqual(tones.classify("#DDE5D4"), "sage")
        self.assertEqual(tones.classify("#DAE6EE"), "sky")
        self.assertEqual(tones.classify("#E1E1DD"), "grey")
        self.assertEqual(tones.classify("#F5EAC8"), "butter")
        self.assertIsNone(tones.classify("not a color"))

    def test_next_tone_is_least_used_and_ignores_premade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(tones.next_tone(root), "cream")          # trống: theo thứ tự
            book(root, "a", "#F4ECE4")
            book(root, "b", "#F2DDDA")
            book(root, "p", "#DDE5D4", product="wall_premade")      # grid in sẵn: không tính
            self.assertEqual(tones.usage(root)["sage"], 0)
            self.assertEqual(tones.next_tone(root), "sage")

    def test_prompt_rule_names_tone_and_fallbacks(self):
        rule = tones.prompt_rule("sage")
        self.assertIn("ASSIGNED BASE TONE", rule)
        self.assertIn("sage green", rule)
        self.assertIn("base_tone_note", rule)


if __name__ == "__main__":
    unittest.main()
