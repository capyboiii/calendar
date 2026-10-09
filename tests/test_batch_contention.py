"""Batch chạy nhiều đầu việc cùng lúc (theo ý tưởng / clone): mockup AI không giành tài khoản Plus của việc vẽ,
render + upscale không dồn hết CPU / GPU."""
import tempfile
import unittest
from pathlib import Path

from calforge.imagegen import ai_mockups, upscale
from calforge.llm import plan
from calforge.render import draw


class ContentionTest(unittest.TestCase):
    def test_mockups_take_free_accounts_before_plus(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            plans = {"acc1": "free", "acc2": "plus", "acc3": "free", "acc4": "plus", "acc5": None}
            for n, kind in plans.items():
                (pdir / n).mkdir()
                if kind:
                    plan.save(pdir / n, {"plan": kind, "label": kind, "active": True,
                                         "expires": "2030-01-01T00:00:00+00:00"})
            order = ai_mockups.plus_last(pdir, ["acc2", "acc1", "acc4", "acc5", "acc3"])
            self.assertEqual(order, ["acc1", "acc5", "acc3", "acc2", "acc4"])   # Free giữ thứ tự xoay vòng, Plus cuối

    def test_render_and_upscale_leave_room(self):
        self.assertLessEqual(draw.RENDER_THREADS, 4)
        self.assertGreater(upscale.TILE_YIELD_S, 0)


if __name__ == "__main__":
    unittest.main()
