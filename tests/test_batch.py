"""Batch trọn gói: cô lập lỗi từng cuốn, vòng vét, báo cáo tổng, chạy lại chỉ làm phần còn thiếu."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import layout
from calforge import pipeline
from calforge.ideation import pipeline as ideation
from calforge.ideation.pipeline import IdeationResult


class FakeIdeation:
    """Mỗi lượt tạo n cuốn mới b1, b2... (có concept.json) như run_ideation thật."""

    def __init__(self):
        self.calls, self.made = [], 0

    def __call__(self, keyword, backend, root, *, auto_pick, **kw):
        self.calls.append(auto_pick)
        kdir = root / keyword
        res = IdeationResult(kdir, [])
        for _ in range(auto_pick):
            self.made += 1
            c = kdir / f"b{self.made}"
            layout.ensure_system(c)
            layout.concept_file(c).write_text(json.dumps({"title": f"Book {self.made}"}), encoding="utf-8")
            res.concepts.append(c)
        return res


def cfg(root):
    return {"projects_dir": str(root), "auto_pick": 1, "year": 2027, "market": "US", "angles_per_keyword": 1,
            "max_repairs": 1, "llm": {"backend": "manual"}}


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.idea = FakeIdeation()
        self.produced = []
        patches = [mock.patch.object(ideation, "run_ideation", self.idea),
                   mock.patch.object(pipeline.config, "make_backend", lambda c: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_produce(self, crash_once=(), missing_once=()):
        seen = set()

        def produce(cdir, cfg, **kw):
            self.produced.append(cdir.name)
            first = cdir.name not in seen
            seen.add(cdir.name)
            if first and cdir.name in crash_once:
                raise RuntimeError("Chrome crashed")
            if first and cdir.name in missing_once:
                return pipeline._status(cdir, stage="images", ok=False, reason="còn thiếu ảnh: m03")
            return pipeline._status(cdir, stage="listing", ok=True)
        return produce

    def test_crash_is_isolated_retried_and_reported(self):
        with mock.patch.object(pipeline, "produce", self.fake_produce(crash_once={"b1"}, missing_once={"b4"})):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=4, retry_wait_s=0)
        self.assertEqual(self.idea.calls, [3, 1])                     # lượt 3 + 1
        self.assertEqual(self.produced, ["b1", "b2", "b3", "b4", "b1", "b4"])   # b1 lỗi không chặn b2..b4; vét lại b1, b4
        self.assertTrue(all(r["ok"] for r in rows))
        report = layout.batch_report_file(self.root / "kw").read_text(encoding="utf-8")
        self.assertIn("xong 4", report)
        batch = json.loads(layout.batch_file(self.root / "kw").read_text(encoding="utf-8"))
        self.assertTrue(batch["finished"])
        self.assertEqual(len(batch["report"]), 4)

    def test_crash_writes_traceback_to_status(self):
        def always_crash(cdir, cfg, **kw):
            raise ValueError("boom")
        with mock.patch.object(pipeline, "produce", always_crash):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=1, retry_wait_s=0)
        st = json.loads(layout.status_file(self.root / "kw" / "b1").read_text(encoding="utf-8"))
        self.assertEqual(st["stage"], "crash")
        self.assertIn("ValueError: boom", st["reason"])
        self.assertIn("Traceback", st["traceback"])
        self.assertFalse(rows[0]["ok"])

    def test_rerun_only_makes_what_is_missing(self):
        # Batch 5 cuốn chết giữa lượt 2 (sau 4 cuốn có ý tưởng, cuốn 4 chưa sản xuất xong).
        kdir = self.root / "kw"
        for i in range(1, 5):
            c = kdir / f"b{i}"
            layout.ensure_system(c)
            layout.concept_file(c).write_text("{}", encoding="utf-8")
            if i < 4:
                pipeline._status(c, stage="listing", ok=True)
        self.idea.made = 4
        layout.ensure_system(kdir)
        layout.batch_file(kdir).write_text(json.dumps(
            {"target": 5, "concepts": ["b1", "b2", "b3", "b4"], "failed_ideas": [], "errors": [],
             "started": "x", "finished": ""}), encoding="utf-8")
        with mock.patch.object(pipeline, "produce", self.fake_produce()):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=5, retry_wait_s=0)
        self.assertEqual(self.idea.calls, [1])                        # chỉ lên ý 1 cuốn còn thiếu
        self.assertEqual(self.produced, ["b4", "b5"])                 # làm nốt b4, rồi b5
        self.assertEqual(sum(r["ok"] for r in rows), 5)


if __name__ == "__main__":
    unittest.main()
