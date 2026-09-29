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
        self.q = BatchQueue(self.tasks, self.file, args, lambda p: (2, 3))

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


if __name__ == "__main__":
    unittest.main()
