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
        kdir = kw.get("keyword_root", root) / keyword
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
        """Giả lập 2 nửa của produce(): gen ảnh (luồng chính) + hậu kỳ (luồng nền)."""
        seen = set()

        def produce_images(cdir, cfg, **kw):
            self.produced.append(cdir.name)
            first = cdir.name not in seen
            seen.add(cdir.name)
            if first and cdir.name in crash_once:
                raise RuntimeError("Chrome crashed")
            if first and cdir.name in missing_once:
                return pipeline._status(cdir, stage="images", ok=False, reason="còn thiếu ảnh: m03")
            return None

        def finish_book(cdir, cfg, **kw):
            return pipeline._status(cdir, stage="listing", ok=True)

        return produce_images, finish_book

    def patched(self, **kw):
        imgs, fin = self.fake_produce(**kw)
        return mock.patch.multiple(pipeline, produce_images=imgs, finish_book=fin)

    def test_crash_is_isolated_retried_and_reported(self):
        with self.patched(crash_once={"b1"}, missing_once={"b4"}):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=4, retry_wait_s=0)
        self.assertEqual(self.idea.calls, [3, 1])                     # lượt 3 + 1
        self.assertEqual(self.produced, ["b1", "b2", "b3", "b4", "b1", "b4"])   # b1 lỗi không chặn b2..b4; vét lại b1, b4
        self.assertTrue(all(r["ok"] for r in rows))
        report = layout.batch_report_file(self.root / "Wall Calendar (Blank)" / "kw").read_text(encoding="utf-8")
        self.assertIn("xong 4", report)
        batch = json.loads(layout.batch_file(self.root / "Wall Calendar (Blank)" / "kw").read_text(encoding="utf-8"))
        self.assertTrue(batch["finished"])
        self.assertEqual(len(batch["report"]), 4)

    def test_crash_writes_traceback_to_status(self):
        def always_crash(cdir, cfg, **kw):
            raise ValueError("boom")
        with mock.patch.object(pipeline, "produce_images", always_crash):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=1, retry_wait_s=0)
        st = json.loads(layout.status_file(self.root / "Wall Calendar (Blank)" / "kw" / "b1").read_text(encoding="utf-8"))
        self.assertEqual(st["stage"], "crash")
        self.assertIn("ValueError: boom", st["reason"])
        self.assertIn("Traceback", st["traceback"])
        self.assertFalse(rows[0]["ok"])

    def test_rerun_only_makes_what_is_missing(self):
        # Batch 5 cuốn chết giữa lượt 2 (sau 4 cuốn có ý tưởng, cuốn 4 chưa sản xuất xong).
        kdir = self.root / "Wall Calendar (Blank)" / "kw"
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
        with self.patched():
            rows = pipeline.run("kw", cfg(self.root), auto_pick=5, retry_wait_s=0)
        self.assertEqual(self.idea.calls, [1])                        # chỉ lên ý 1 cuốn còn thiếu
        self.assertEqual(self.produced, ["b4", "b5"])                 # làm nốt b4, rồi b5
        self.assertEqual(sum(r["ok"] for r in rows), 5)


    def test_finishing_overlaps_next_books_image_generation(self):
        import threading
        import time as _t
        events = []
        started_b2 = threading.Event()

        def produce_images(cdir, cfg, **kw):
            events.append(("img", cdir.name, _t.time()))
            if cdir.name == "b2":
                started_b2.set()
            return None

        def finish_book(cdir, cfg, **kw):
            if cdir.name == "b1":
                self.assertTrue(started_b2.wait(5))      # cuốn 2 đã bắt đầu gen ảnh trong lúc cuốn 1 còn hậu kỳ
            events.append(("fin", cdir.name, _t.time()))
            return pipeline._status(cdir, stage="listing", ok=True)

        with mock.patch.multiple(pipeline, produce_images=produce_images, finish_book=finish_book):
            rows = pipeline.run("kw", cfg(self.root), auto_pick=3, retry_wait_s=0)
        self.assertEqual(sum(r["ok"] for r in rows), 3)
        order = [(k, n) for k, n, _ in events]
        self.assertLess(order.index(("img", "b2")), order.index(("fin", "b1")))


    def test_waits_when_all_accounts_are_out_of_quota(self):
        from calforge.imagegen.generate import QUOTA_MARK
        calls = []

        def gen(cdir, *a, **kw):                 # lần 1: cả 5 tài khoản hết lượt; lần 2: có lượt, đủ ảnh
            calls.append(1)
            if len(calls) == 1:
                return {"missing": ["m03"], "failed": {"m03": QUOTA_MARK}, "drift_flags": []}
            return {"missing": [], "failed": {}, "drift_flags": []}

        c = cfg(self.root)
        c.update(quota_wait_s=0, quota_max_wait_h=1, imagegen={}, chatgpt_automation_dir=str(self.root))
        d = self.root / "Wall Calendar (Blank)" / "kw" / "b1"
        layout.ensure_system(d)
        layout.concept_file(d).write_text("{}", encoding="utf-8")
        logs = []
        with mock.patch.object(pipeline, "generate_concept", gen),                 mock.patch.object(pipeline.plan, "write_plan", lambda d: None),                 mock.patch.object(pipeline, "upscale_concept", lambda *a, **k: []):
            res = pipeline.produce_images(d, c, on_event=logs.append)
        self.assertIsNone(res)                                   # không hỏng cuốn: chờ rồi làm tiếp
        self.assertEqual(len(calls), 2)
        self.assertTrue(any(l.startswith("⏸ Tất cả tài khoản hết lượt") for l in logs))

    def test_ideation_waits_when_chat_quota_is_gone(self):
        from calforge.llm.chatgpt_web import NoAccountLeft
        real = self.idea
        state = {"n": 0}

        def flaky(*a, **kw):
            state["n"] += 1
            if state["n"] == 1:
                raise NoAccountLeft("hết lượt")
            return real(*a, **kw)

        c = cfg(self.root)
        c.update(quota_wait_s=0, quota_max_wait_h=1)
        with mock.patch.object(ideation, "run_ideation", flaky), self.patched():
            rows = pipeline.run("kw", c, auto_pick=2, retry_wait_s=0)
        self.assertEqual(sum(r["ok"] for r in rows), 2)          # chờ xong lên ý tiếp, đủ 2 cuốn


if __name__ == "__main__":
    unittest.main()
