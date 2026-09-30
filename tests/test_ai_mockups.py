"""AI gen mockup: chỉ "AI vẽ cả trang"; 4 ảnh (bỏ 04); ảnh kèm đúng thứ tự; hỏng thì giữ mockup code; gen lại khi đổi."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout, products
from calforge.imagegen import ai_mockups, driver
from calforge.imagegen.mockup_prompts import COVER_PROMPT, SCENE_PROMPT
from calforge.render import mockups
from calforge.ui import server

from tests import fixtures


def book(root: Path, mockup_mode="ai", grid_mode="ai_page") -> Path:
    c = root / "kw" / "Book"
    layout.ensure_system(c)
    concept = {**fixtures.concept(), "year": 2027, "market": "US", "product": "wall_grid"}
    concept["style"].update(grid_mode=grid_mode, mockup_mode=mockup_mode)
    layout.concept_file(c).write_text(json.dumps(concept), encoding="utf-8")
    layout.raw(c).mkdir(parents=True)
    Image.new("RGB", (1536, 1024), "red").save(layout.raw(c) / "cover.png")
    layout.listing(c).mkdir(parents=True)
    for name in ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads", "05_wall_page_turn"]:
        Image.new("RGB", (1600, 1067), "gray").save(layout.listing(c) / f"{name}.jpg")     # mockup code
    return c


class FakeRun:
    """Thay run_jobs: ghi lại việc được giao; `fail` = id các việc AI hỏng."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, jobs, pdir, names, **kw):
        self.calls.append(jobs)
        for j in jobs:
            if j.id in self.fail:
                j.error = "bỏ sau 3 lần"
                continue
            out = j.out.with_suffix(".png")
            Image.new("RGB", (1024, 1024), "blue").save(out)
            self.accept = j.accept(out)
            j.result = out
        return jobs


class AiMockupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {"projects_dir": str(self.root), "profiles_dir": str(self.root / "profiles"), "imagegen": {}}
        (self.root / "profiles" / "acc1").mkdir(parents=True)

    def run_ai(self, c, fake):
        with mock.patch.object(driver, "run_jobs", fake):
            return ai_mockups.ai_previews(c, self.cfg, on_event=lambda *_: None)

    def test_four_ai_previews_with_right_attachments_and_prompts(self):
        c = book(self.root)
        fake = FakeRun()
        res = self.run_ai(c, fake)
        self.assertEqual(sorted(res["ai"]), sorted(["01_front_cover_spiral", "02_open_spread_flat",
                                                   "03_three_open_spreads", "05_wall_page_turn"]))
        jobs = {j.id: j for j in fake.calls[0]}
        cover = jobs["01_front_cover_spiral"]
        self.assertTrue(cover.prompt.startswith(COVER_PROMPT) and "1:1" in cover.prompt)
        self.assertEqual([Path(a).name for a in cover.attach], ["front_cover_spiral.webp", "cover.png"])  # IMAGE 1, 2
        spread = jobs["02_open_spread_flat"]
        self.assertTrue(spread.prompt.startswith(SCENE_PROMPT) and "1:1" in spread.prompt)
        self.assertEqual([Path(a).parent.name for a in spread.attach], ["mockup_goc"])   # mockup code của cuốn
        self.assertIsNone(fake.accept)
        with Image.open(layout.listing(c) / "02_open_spread_flat.jpg") as im:
            self.assertEqual(im.getpixel((10, 10))[2] > 200, True)                    # đã thay bằng ảnh AI
        self.assertEqual(ai_mockups.pending(c), [])
        self.assertEqual(self.run_ai(c, FakeRun()), {"ai": [], "kept_code": []})   # đã mới: không gen lại

    def test_failed_ai_keeps_code_mockup_and_retries_later(self):
        c = book(self.root)
        before = (layout.listing(c) / "03_three_open_spreads.jpg").read_bytes()
        res = self.run_ai(c, FakeRun(fail={"03_three_open_spreads"}))
        self.assertEqual(res["kept_code"], ["03_three_open_spreads"])
        self.assertEqual((layout.listing(c) / "03_three_open_spreads.jpg").read_bytes(), before)
        self.assertEqual(ai_mockups.pending(c), ["03_three_open_spreads"])          # lần sau gen AI lại đúng ảnh đó

    def test_code_regenerated_preview_triggers_ai_again(self):
        c = book(self.root)
        self.run_ai(c, FakeRun())
        time.sleep(0.02)
        Image.new("RGB", (1600, 1067), "gray").save(layout.listing(c) / "05_wall_page_turn.jpg")   # trang in đổi
        self.assertEqual(ai_mockups.pending(c), ["05_wall_page_turn"])

    def test_only_ai_page_books_get_ai_mockups_and_drop_preview_4(self):
        with tempfile.TemporaryDirectory() as tmp:
            ai = book(Path(tmp))
            concept = json.loads(layout.concept_file(ai).read_text(encoding="utf-8"))
            self.assertTrue(products.ai_mockups(concept))
            self.assertEqual(mockups.skipped_previews(concept), {"wall_spread"})
            self.assertNotIn("04_wall_spread.jpg", mockups.missing_previews(ai))    # 4 ảnh là đủ
        for mode, grid in (("ai", "background"), ("template", "ai_page")):
            c = {**fixtures.concept(), "product": "wall_grid"}
            c["style"].update(grid_mode=grid, mockup_mode=mode)
            self.assertFalse(products.ai_mockups(c))

    def test_queue_args(self):
        ok = server.run_args({"keyword": "cats", "product": "wall_grid", "grid_mode": "ai_page", "mockup_mode": "ai"})[0]
        self.assertEqual(ok[-2:], ["--mockup-mode", "ai"])
        bg = server.run_args({"keyword": "cats", "product": "wall_grid", "grid_mode": "background",
                              "mockup_mode": "ai"})[0]
        self.assertNotIn("--mockup-mode", bg)                                         # chỉ áp dụng "AI vẽ cả trang"


if __name__ == "__main__":
    unittest.main()


class SquareCheckTest(unittest.TestCase):
    def test_non_square_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.png"
            Image.new("RGB", (1536, 1024)).save(f)
            self.assertIn("1:1", ai_mockups.accept_mockup(f))
            Image.new("RGB", (1254, 1254)).save(f)
            self.assertIsNone(ai_mockups.accept_mockup(f))
