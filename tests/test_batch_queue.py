import tempfile
import unittest
from pathlib import Path

from calforge.ui.batch_queue import BatchQueue


class FakeTask:
    def __init__(self, action):
        self.status, self.action = "running", action


class FakeTasks:
    def __init__(self):
        self.tasks, self.started, self.stopped = {}, [], []

    def running(self):
        return next((t for t in self.tasks.values() if t.status == "running"), None)

    def start_task(self, args, desc, action, params):
        tid = f"t{len(self.started) + 1}"
        self.tasks[tid] = FakeTask(action)
        self.started.append(params["keyword"])
        return tid

    def stop_task(self, tid):
        self.stopped.append(tid)
        self.tasks[tid].status = "stopped"
        return True


def args(params):
    if not params.get("keyword"):
        raise ValueError("Nhập chủ đề trước đã.")
    return ["run", params["keyword"]], "d"


class BatchQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / ".hang_doi.json"
        self.tasks = FakeTasks()
        self.q = BatchQueue(self.tasks, self.file, args, lambda p: (2, 2))

    def tearDown(self):
        self.tmp.cleanup()

    def status(self):
        return [(i["params"]["keyword"], i["status"]) for i in self.q.snapshot()["items"]]

    def test_runs_one_batch_at_a_time_in_order(self):
        for kw in ("a", "b", "c"):
            self.q.add({"keyword": kw})
        self.assertEqual(self.tasks.started, ["a"])                  # chỉ chạy 1 batch
        self.tasks.tasks["t1"].status = "success"
        self.q.tick()
        self.assertEqual(self.tasks.started, ["a", "b"])
        self.assertEqual(self.status()[0], ("a", "done"))
        self.assertEqual(self.q.snapshot()["items"][0]["ok"], 2)

    def test_bad_params_rejected(self):
        with self.assertRaises(ValueError):
            self.q.add({"keyword": ""})
        self.assertEqual(self.q.snapshot()["items"], [])

    def test_pause_requeues_current_at_front_and_resume_continues(self):
        self.q.add({"keyword": "a"})
        self.q.add({"keyword": "b"})
        self.q.pause()
        self.assertEqual(self.tasks.stopped, ["t1"])
        self.q.tick()
        self.assertEqual(self.status(), [("a", "queued"), ("b", "queued")])
        self.assertEqual(self.tasks.started, ["a"])                  # tạm dừng: không chạy gì thêm
        self.q.resume()
        self.assertEqual(self.tasks.started, ["a", "a"])             # làm nốt batch a trước

    def test_user_stop_goes_to_done_list_and_queue_continues(self):
        self.q.add({"keyword": "a"})
        self.q.add({"keyword": "b"})
        self.q.stopped_by_user("t1")
        self.tasks.stop_task("t1")
        self.q.tick()
        self.assertEqual(self.status(), [("a", "stopped"), ("b", "running")])

    def test_waits_for_other_main_task(self):
        self.tasks.tasks["x"] = FakeTask("produce")                  # vd đang "Làm tiếp" một cuốn
        self.q.add({"keyword": "a"})
        self.assertEqual(self.tasks.started, [])
        self.tasks.tasks["x"].status = "success"
        self.q.tick()
        self.assertEqual(self.tasks.started, ["a"])

    def test_survives_restart_and_reorders(self):
        for kw in ("a", "b", "c"):
            self.q.add({"keyword": kw})
        ids = [i["id"] for i in self.q.snapshot()["items"]]
        self.assertTrue(self.q.move(ids[2], -1))                     # c lên trước b
        q2 = BatchQueue(FakeTasks(), self.file, args, lambda p: (0, 0))   # tool mở lại
        self.assertEqual([(i["params"]["keyword"], i["status"]) for i in q2.snapshot()["items"]],
                         [("a", "queued"), ("c", "queued"), ("b", "queued")])
        self.assertTrue(q2.remove(ids[1]))


class QueueResultTest(unittest.TestCase):
    def _run(self, ok, total, status="success", retryable=None):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            result = (ok, total) if retryable is None else (ok, total, retryable)
            q = BatchQueue(tasks, Path(tmp) / "q.json", args, lambda p: result)
            q.add({"keyword": "a"})
            tasks.tasks["t1"].status = status
            q.tick()
            return q.snapshot()["items"][0]

    def test_status_follows_books_made(self):
        self.assertEqual(self._run(3, 3)["status"], "done")
        self.assertEqual(self._run(1, 3)["status"], "partial")
        self.assertEqual(self._run(0, 1)["status"], "failed")       # chạy hết mà 0 cuốn đạt: không được ghi "Xong"
        self.assertEqual(self._run(0, 0, "failed")["status"], "failed")

    def test_terminal_only_partial_has_no_retry(self):
        item = self._run(2, 3, retryable=False)
        self.assertEqual(item["status"], "partial")
        self.assertFalse(item["retryable"])


class SameBookTest(unittest.TestCase):
    def test_repeat_presses_merge_and_different_books_queue_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            tasks.tasks["x"] = FakeTask("run")                       # một batch đang chạy: các việc sau phải chờ
            q = BatchQueue(tasks, Path(tmp) / "q.json", lambda p: (["redo"], "d"), lambda p: (1, 1))
            q.add({"action": "redo", "concept": "A", "pages": ["m03"]})
            q.add({"action": "redo", "concept": "A", "pages": ["m03", "m07"]})   # bấm lại cùng cuốn
            q.add({"action": "redo", "concept": "B", "pages": ["cover"]})        # cuốn khác
            q.add({"action": "finish", "concept": "A"})
            q.add({"action": "finish", "concept": "A", "redo_previews": True})
            items = q.snapshot()["items"]
            self.assertEqual([(i["params"]["action"], i["params"]["concept"]) for i in items],
                             [("redo", "A"), ("redo", "B"), ("finish", "A")])
            self.assertEqual(items[0]["params"]["pages"], ["m03", "m07"])    # gộp trang, không vẽ trùng
            self.assertTrue(items[2]["params"]["redo_previews"])
            self.assertEqual(tasks.started, [])                      # chưa chạy gì khi batch khác đang chạy


class StaleWaitingItemTest(unittest.TestCase):
    def test_item_that_becomes_invalid_does_not_block_queue_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = FakeTasks()
            blocked = {"bad": False}

            def build(params):
                if params["keyword"] == "bad" and blocked["bad"]:
                    raise ValueError("Cuốn đã bị loại vì TM")
                return ["run", params["keyword"]], "d"

            q = BatchQueue(tasks, Path(tmp) / "q.json", build, lambda p: (1, 1, False))
            tasks.tasks["x"] = FakeTask("run")
            q.add({"keyword": "bad"})
            q.add({"keyword": "good"})
            blocked["bad"] = True
            tasks.tasks["x"].status = "success"
            q.tick()
            self.assertEqual(q.snapshot()["items"][0]["status"], "failed")
            q.tick()
            self.assertEqual(tasks.started, ["good"])


class OverlapNextTopicTest(unittest.TestCase):
    """Batch đang chạy đã lên đủ ý (chỉ còn vẽ nốt): chủ đề kế tiếp bắt đầu lên ý luôn - tối đa 2 batch cùng lúc."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tasks = FakeTasks()
        self.done = set()                                             # chủ đề đã lên đủ ý
        self.q = BatchQueue(self.tasks, Path(self.tmp.name) / ".hang_doi.json", args, lambda p: (2, 2),
                            ideas_done=lambda p: p["keyword"] in self.done)

    def status(self):
        return [(i["params"]["keyword"], i["status"]) for i in self.q.snapshot()["items"]]

    def test_next_topic_waits_even_after_ideas_done(self):
        for kw in ('a','b','c'):self.q.add({'keyword':kw})
        self.done.add('a')
        self.q.tick()
        self.assertEqual(self.tasks.started,['a'])
        self.tasks.tasks['t1'].status='success'
        self.q.tick()
        self.assertEqual(self.tasks.started,['a','b'])

    def test_no_overlap_while_still_ideating_or_for_book_fixes(self):
        self.q.add({"keyword": "a"})
        self.q.add({"keyword": "x", "action": "produce", "concept": "/p/x"})   # việc sửa sách lẻ
        self.done.add("a")
        self.q.tick()
        self.assertEqual(self.tasks.started, ["a"])                  # việc sửa sách không chồng lượt

    def test_same_topic_never_overlaps(self):
        self.q.add({"keyword": "a"})
        self.q.add({"keyword": "a"})                                 # cùng chủ đề (vd thêm 2 lần)
        self.done.add("a")
        self.q.tick()
        self.assertEqual(self.tasks.started, ["a"])

    def test_pause_stops_both_and_requeues_in_order(self):
        for kw in ("a", "b", "c"):
            self.q.add({"keyword": kw})
        self.done.add("a")
        self.q.tick()
        self.q.pause()
        self.assertEqual(sorted(self.tasks.stopped), ["t1"])
        self.assertEqual(self.status(), [("a", "queued"), ("b", "queued"), ("c", "queued")])
        self.assertTrue(all(i["params"].get("resume") for i in self.q.snapshot()["items"][:1]))

    def test_no_overlap_when_ram_is_low(self):
        ram = {"gb": 3.0}
        q = BatchQueue(self.tasks, Path(self.tmp.name) / "q3.json", args, lambda p: (2, 2),
                       ideas_done=lambda p: True, free_ram=lambda: ram["gb"], overlap_min_gb=6)
        q.add({"keyword": "a"})
        q.add({"keyword": "b"})
        q.tick()
        self.assertEqual(self.tasks.started, ["a"])                  # thiếu RAM: không chồng
        ram["gb"] = 9.0
        q.tick()
        self.assertEqual(self.tasks.started, ["a"])                   # strict FIFO even with spare RAM

    def test_broken_state_falls_back_to_one_at_a_time(self):
        q = BatchQueue(self.tasks, Path(self.tmp.name) / "q2.json", args, lambda p: (2, 2),
                       ideas_done=lambda p: 1 / 0)
        q.add({"keyword": "a"})
        q.add({"keyword": "b"})
        q.tick()
        self.assertEqual(self.tasks.started, ["a"])


if __name__ == "__main__":
    unittest.main()
