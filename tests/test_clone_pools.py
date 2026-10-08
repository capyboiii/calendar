"""Deterministic scheduling checks without opening Chrome or generating images."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from calforge.clone import run, store
from tests.test_clone import new_item


class ClonePoolsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg, self.first = new_item(self.root)

    def go(self, work, names, stop=None):
        with mock.patch.object(run, "run_book", side_effect=work):
            return run.run_queue(self.cfg, on_event=lambda *_: None, accts=object(), plus=names, stop=stop)

    def test_all_six_slots_work_and_each_book_keeps_stage_order(self):
        for _ in range(5):
            new_item(self.root)
        barrier = threading.Barrier(6)
        calls = {}
        lock = threading.Lock()

        def work(cfg, d, *args, step):
            with lock:
                calls.setdefault(d.name, []).append(step)
            if step == "art":
                barrier.wait(timeout=5)
            return {"next": {"art": "grid", "grid": "finish"}[step]} if step != "finish" else {"ok": True}

        result = self.go(work, [f"acc{i}" for i in range(6)])
        self.assertEqual(len(result), 6)
        self.assertTrue(all(r.get("ok") for r in result))
        self.assertEqual(list(calls.values()), [["art", "grid", "finish"]] * 6)

    def test_slow_finish_does_not_block_new_art_on_single_account(self):
        advanced = threading.Event()
        added = []

        def work(cfg, d, *args, step):
            if step == "finish" and d == self.first:
                _, second = new_item(self.root)
                added.append(second)
                self.assertTrue(advanced.wait(5), "hậu kỳ đang chặn artwork của cuốn mới")
            if step == "art" and d != self.first:
                advanced.set()
            return {"next": {"art": "grid", "grid": "finish"}[step]} if step != "finish" else {"ok": True}

        results = self.go(work, ["acc1"])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.get("ok") for r in results))
        self.assertTrue(advanced.is_set())

    def test_new_books_use_idle_slots_while_first_art_is_still_running(self):
        started = threading.Barrier(4)

        def work(cfg, d, *args, step):
            if step == "art":
                if d == self.first:
                    for _ in range(3):
                        new_item(self.root)
                started.wait(timeout=5)
            return {"next": {"art": "grid", "grid": "finish"}[step]} if step != "finish" else {"ok": True}

        results = self.go(work, ["acc1", "acc2", "acc3", "acc4"])
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.get("ok") for r in results))

    def test_stop_at_stage_boundary_does_not_start_grid_or_finish(self):
        stop = threading.Event()
        calls = []

        def work(cfg, d, *args, step):
            calls.append(step)
            stop.set()
            return {"next": "grid"}

        self.assertEqual(self.go(work, ["acc1"], stop), [{"ok": False}])
        self.assertEqual(calls, ["art"])
        self.assertEqual(store.read(self.first)["status"], "failed")

    def test_worker_exception_does_not_abort_other_books(self):
        new_item(self.root)

        def work(cfg, d, *args, step):
            if d == self.first:
                raise RuntimeError("broken book")
            return {"next": {"art": "grid", "grid": "finish"}[step]} if step != "finish" else {"ok": True}

        results = self.go(work, ["acc1", "acc2"])
        self.assertEqual(sorted(r["ok"] for r in results), [False, True])
        self.assertIn("broken book", store.read(self.first)["reason"])

    def test_rejected_books_not_admitted(self):
        store.write(self.first, status="rejected")
        work = mock.Mock()
        self.assertEqual(self.go(work, ["acc1"]), [])
        work.assert_not_called()
