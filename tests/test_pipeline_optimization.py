"""Fast-path guarantees for the production pipeline."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from calforge.pipeline import UPSCALE_JOBS, _listing_is_current, _render_is_current
from calforge.render.build import art_source


class PipelineOptimizationTest(unittest.TestCase):
    def test_only_final_page_artwork_uses_real_esrgan(self):
        self.assertEqual(len(UPSCALE_JOBS), 13)
        self.assertNotIn("anchor", UPSCALE_JOBS)
        self.assertNotIn("grid", UPSCALE_JOBS)
        self.assertEqual(UPSCALE_JOBS[0], "cover")

    def test_new_raw_asset_wins_over_stale_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "_he_thong" / "anh_ai" / "grid.png"
            final = root / "_he_thong" / "anh_upscale" / "grid.png"
            raw.parent.mkdir(parents=True)
            final.parent.mkdir(parents=True)
            final.write_bytes(b"old final")
            raw.write_bytes(b"new raw")
            now = time.time()
            os.utime(final, (now - 10, now - 10))
            os.utime(raw, (now, now))
            chosen, kind = art_source(root, "grid")
            self.assertEqual(chosen, raw)
            self.assertEqual(kind, "raw")

    def test_render_cache_invalidates_when_used_art_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_he_thong" / "anh_ai").mkdir(parents=True)
            (root / "11x8.5").mkdir(parents=True)
            (root / "_he_thong" / "ky_thuat").mkdir(parents=True)
            (root / "_he_thong" / "concept.json").write_text("{}", encoding="utf-8")
            for jid in ["cover", *[f"m{m:02d}" for m in range(1, 13)], "grid"]:
                (root / "_he_thong" / "anh_ai" / f"{jid}.png").write_bytes(b"art")
            time.sleep(.01)
            for i in range(26):
                (root / "11x8.5" / f"page{i:02d}.png").write_bytes(b"page")
            (root / "11x8.5" / "in_tai_nha_11x8.5.pdf").write_bytes(b"pdf")
            (root / "_he_thong" / "ky_thuat" / "render_11x8.5_validation.json").write_text(
                json.dumps({"complete": True, "issues": []}), encoding="utf-8")
            self.assertTrue(_render_is_current(root, "printify_wall_11x8_5"))
            future = time.time() + 2
            os.utime(root / "_he_thong" / "anh_ai" / "m06.png", (future, future))
            self.assertFalse(_render_is_current(root, "printify_wall_11x8_5"))

    def test_listing_cache_tracks_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_he_thong").mkdir()
            concept = root / "_he_thong" / "concept.json"
            listing = root / "_he_thong" / "listing.json"
            concept.write_text("{}", encoding="utf-8")
            time.sleep(.01)
            listing.write_text("{}", encoding="utf-8")
            self.assertTrue(_listing_is_current(root))
            future = time.time() + 2
            os.utime(concept, (future, future))
            self.assertFalse(_listing_is_current(root))


if __name__ == "__main__":
    unittest.main()
