import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from calforge.render import mockups


class MockupPreviewMapTest(unittest.TestCase):
    def test_open_spread_preserves_both_hanging_holes(self):
        sheet = mockups.MOCKUPS["open_spread_flat"]["sheets"][0]
        self.assertEqual(sheet["cutouts"], [(626, 130, 11), (626, 1120, 11)])

    def test_exactly_five_listing_previews_have_assets_and_valid_sources(self):
        self.assertEqual(
            mockups.PREVIEWS,
            ["front_cover_spiral", "open_spread_flat", "three_open_spreads", "wall_spread", "wall_page_turn"],
        )
        self.assertTrue(set(mockups.PREVIEWS) <= set(mockups.MOCKUPS))
        for name in mockups.PREVIEWS:
            cfg = mockups.MOCKUPS[name]
            self.assertTrue((mockups.HERE / cfg["file"]).is_file(), name)
            self.assertTrue(cfg["sheets"], name)
            for sheet in cfg["sheets"]:
                self.assertIn(sheet["kind"], {"page", "spread", "curl"})
                self.assertTrue(sheet.get("source") or sheet.get("month"), name)

    def test_cache_invalidates_when_a_mockup_or_map_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = root / "11x8.5"
            assets = root / "assets"
            pages.mkdir(parents=True)
            assets.mkdir()
            for cfg in mockups.MOCKUPS.values():
                (assets / cfg["file"]).write_bytes(b"mockup")
                for sheet in cfg["sheets"]:
                    for n in mockups.sheet_pages(sheet):
                        (pages / f"{n}.png").write_bytes(b"page")

            def fake_render(_name, _pages, out, debug=False):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"preview")

            with patch.object(mockups, "HERE", assets), patch.object(mockups, "render", fake_render):
                self.assertEqual(len(mockups.previews(root, lambda _msg: None)), 5)
                self.assertEqual(mockups.previews(root, lambda _msg: None), [])
                changed = assets / mockups.MOCKUPS["wall_spread"]["file"]
                future = time.time() + 5
                os.utime(changed, (future, future))
                remade = mockups.previews(root, lambda _msg: None)
                self.assertEqual([p.name for p in remade], ["04_wall_spread.jpg"])


    def test_premade_books_use_premade_mockups(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pages = root / "11x8.5"
            assets = root / "assets"
            pages.mkdir(parents=True)
            assets.mkdir()
            (root / "_he_thong").mkdir()
            (root / "_he_thong" / "concept.json").write_text(json.dumps({"product": "wall_premade"}), encoding="utf-8")
            for cfg in mockups.MOCKUPS.values():
                (assets / cfg["file"]).write_bytes(b"mockup")
                for sheet in cfg["sheets"]:
                    for n in mockups.sheet_pages(sheet):
                        (pages / f"{n}.png").write_bytes(b"page")

            def fake_render(_name, _pages, out, debug=False):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"preview")

            with patch.object(mockups, "HERE", assets), patch.object(mockups, "render", fake_render):
                made = mockups.previews(root, lambda _msg: None)
        self.assertEqual([p.name for p in made], [f"{i:02d}_{n}.jpg" for i, n in enumerate(mockups.PREMADE_PREVIEWS, 1)])
        self.assertIn("m01_grid", mockups.sheet_pages(mockups.MOCKUPS["premade_two_closed"]["sheets"][1]))


if __name__ == "__main__":
    unittest.main()
