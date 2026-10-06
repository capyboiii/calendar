"""Nút "Gen lại" MỘT ảnh quảng cáo: chỉ đúng ảnh đó được làm lại (AI dựng lại bối cảnh hoặc ghép lại bản code),
4 ảnh còn lại giữ nguyên; bấm nhiều ảnh khi việc còn chờ thì gộp; tên ảnh sai bị từ chối ngay lúc bấm."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import cli, config, layout
from calforge.imagegen import ai_mockups, driver
from calforge.render import mockups
from calforge.ui import server
from calforge.ui.batch_queue import BatchQueue

from tests import test_ai_mockups as tam
from tests import test_recovery_simulation as tr
from tests import test_batch_simulation as tb

ALL = ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads", "04_two_wall_spreads",
       "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"]


def fake_render(name, pages, out):
    Image.new("RGB", (1600, 1600), "gray").save(out)


class RedoOnePreviewCliTest(unittest.TestCase):
    """cli finish --redo-preview <tên> trên một cuốn AI gen mockup đã xong."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.c = tam.book(self.root)
        pages = layout.print_dir(self.c)
        pages.mkdir(parents=True, exist_ok=True)
        for n in ["front_cover", "back_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")]:
            Image.new("RGB", (60, 40), "white").save(pages / f"{n}.png")
        old = time.time() - 3600
        import os
        for f in pages.iterdir():
            os.utime(f, (old, old))
        self.cfg = {"projects_dir": str(self.root), "profiles_dir": str(self.root / "profiles"), "imagegen": {}}
        (self.root / "profiles" / "acc1").mkdir(parents=True)
        self.fake = tam.FakeRun()
        with mock.patch.object(driver, "run_jobs", self.fake):
            ai_mockups.ai_previews(self.c, self.cfg, on_event=lambda *_: None)   # cả 5 ảnh đã là ảnh AI
        self.assertEqual(ai_mockups.pending(self.c), [])

    def finish(self, *names):
        fake = tam.FakeRun()
        args = ["finish", str(self.c)] + [x for n in names for x in ("--redo-preview", n)]
        with mock.patch.object(config, "load", lambda: json.loads(json.dumps(self.cfg))), \
                mock.patch.object(mockups, "render", fake_render), \
                mock.patch.object(driver, "run_jobs", fake), \
                mock.patch("calforge.pipeline.finish_book", side_effect=self.fake_finish(fake)), \
                mock.patch("calforge.pipeline.upscale_concept", lambda *a, **k: []):
            try:
                cli.main(args)
            except SystemExit as e:
                if e.code not in (None, 0):
                    raise
        return fake

    def fake_finish(self, fake):
        def run(cdir, cfg, printify=False, **kw):
            mockups.previews(cdir, on_event=lambda *_: None)                  # bước thật: ghép lại ảnh bị xoá
            ai_mockups.ai_previews(cdir, cfg, on_event=lambda *_: None)       # bước thật: AI chỉ gen ảnh cần
            return {"ok": True, "stage": "listing"}
        return run

    def test_only_the_chosen_preview_is_redone(self):
        before = {n: (layout.listing(self.c) / f"{n}.jpg").stat().st_mtime_ns for n in ALL}
        time.sleep(0.02)
        fake = self.finish("04_two_wall_spreads")
        self.assertEqual([j.id for j in fake.calls[0]], ["04_two_wall_spreads"])    # chỉ 1 lượt AI
        after = {n: (layout.listing(self.c) / f"{n}.jpg").stat().st_mtime_ns for n in ALL}
        self.assertNotEqual(before["04_two_wall_spreads"], after["04_two_wall_spreads"])
        for n in ALL:
            if n != "04_two_wall_spreads":
                self.assertEqual(before[n], after[n], n)                             # 4 ảnh còn lại không đụng
        self.assertEqual(ai_mockups.pending(self.c), [])
        self.assertEqual(sorted(p.stem for p in layout.listing(self.c).glob("*.jpg")), ALL + ["09_year_grid"])

    def test_two_previews_at_once(self):
        fake = self.finish("01_front_cover_spiral", "06_three_books")
        self.assertEqual(sorted(j.id for j in fake.calls[0]), ["01_front_cover_spiral", "06_three_books"])

    def test_ai_failure_keeps_a_code_mockup_in_place(self):
        fake = tam.FakeRun(fail={"02_open_spread_flat"})
        with mock.patch.object(config, "load", lambda: json.loads(json.dumps(self.cfg))), \
                mock.patch.object(mockups, "render", fake_render), mock.patch.object(driver, "run_jobs", fake), \
                mock.patch("calforge.pipeline.finish_book", side_effect=self.fake_finish(fake)), \
                mock.patch("calforge.pipeline.upscale_concept", lambda *a, **k: []):
            cli.main(["finish", str(self.c), "--redo-preview", "02_open_spread_flat"])
        self.assertTrue((layout.listing(self.c) / "02_open_spread_flat.jpg").is_file())   # không bị mất ảnh
        self.assertEqual(ai_mockups.pending(self.c), ["02_open_spread_flat"])            # lần sau gen lại tiếp

    def test_unknown_preview_name_stops_without_touching_anything(self):
        before = sorted((p.name, p.stat().st_mtime_ns) for p in layout.listing(self.c).glob("*.jpg"))
        for bad in ("05_wall_page_turn", "../concept", "99_x"):
            with self.assertRaises(SystemExit) as e:
                cli.main(["finish", str(self.c), "--redo-preview", bad])
            self.assertIn("Không có ảnh quảng cáo", str(e.exception.code))
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in layout.listing(self.c).glob("*.jpg")), before)


class RedoOnePreviewQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "projects"
        self.c = tam.book(root)
        p = mock.patch.object(server.config, "load", lambda: {"projects_dir": str(root)})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(server, "ROOT", Path(self.tmp.name))
        q.start()
        self.addCleanup(q.stop)

    def params(self, redo):
        return {"action": "finish", "concept": str(self.c), "title": "Book", "redo_previews": redo}

    def test_run_args(self):
        args, desc = server.run_args(self.params(["04_two_wall_spreads"]))
        self.assertEqual(args[-2:], ["--redo-preview", "04_two_wall_spreads"])
        self.assertNotIn("--redo-previews", args)
        self.assertIn("Gen lại 1 ảnh quảng cáo", desc)
        self.assertIn("--redo-previews", server.run_args(self.params(True))[0])     # nút cũ "làm lại cả 5" vẫn chạy
        for bad in ([], ["05_wall_page_turn"], ["../../x"], ["04_two_wall_spreads; rm"]):
            with self.assertRaises(ValueError, msg=bad):
                server.run_args(self.params(bad))

    def test_queue_merges_presses(self):
        tasks = mock.Mock()
        tasks.running.return_value = None
        tasks.tasks = {}
        q = BatchQueue(tasks, Path(self.tmp.name) / "q.json", server.run_args, lambda p: (1, 1))
        q.pause()
        q.add(self.params(["04_two_wall_spreads"]))
        q.add(self.params(["06_three_books"]))
        q.add(self.params(["04_two_wall_spreads"]))
        items = q.snapshot()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["params"]["redo_previews"], ["04_two_wall_spreads", "06_three_books"])
        q.add(self.params(True))                                                    # bấm "làm lại cả 5": thành cả 5
        self.assertIs(q.snapshot()["items"][0]["params"]["redo_previews"], True)


class RedoOnePreviewSimulationTest(unittest.TestCase):
    """Đi đúng đường thật: hàng đợi -> lệnh CLI -> finish_book THẬT (render mockup giả cho nhanh) -> AI gen."""

    def test_through_queue(self):
        rec = tr.Recovery("test_redo_previews_regenerates_ai_mockups")
        rec.setUp()
        self.addCleanup(rec.doCleanups)
        rec.sim.world.fault = 0.0
        q, _ = rec.queue()
        q.add({"keyword": "koi", "batch_size": 1, "product": "wall_grid", "grid_mode": "ai_page", "mockup_mode": "ai"})
        rec.drain(q)
        [b] = rec.sim.books("koi")
        first = json.loads(layout.tech(b, "mockup_ai.json").read_text(encoding="utf-8"))
        time.sleep(0.02)
        q.add(rec.book_params(b, "finish", redo_previews=["03_three_open_spreads"]))
        items = rec.drain(q)
        self.assertEqual(items[-1]["status"], "done")
        again = json.loads(layout.tech(b, "mockup_ai.json").read_text(encoding="utf-8"))
        changed = sorted(k for k in first if again.get(k, {}).get("mtime_ns") != first[k]["mtime_ns"])
        self.assertEqual(changed, ["03_three_open_spreads"])
        tb.check_invariants(self, rec.sim)


if __name__ == "__main__":
    unittest.main()
