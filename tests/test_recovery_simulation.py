"""GIẢ LẬP CÁC ĐƯỜNG CỨU LỖI, đi đúng đường thật: nút trên UI -> hàng đợi (BatchQueue) -> lệnh CLI -> pipeline.

Dùng lại thế giới giả của test_batch_simulation (ChatGPT / Chrome / dàn trang giả, lỗi ngẫu nhiên, 15 tài khoản).
Tác vụ của hàng đợi chạy NGAY TRONG tiến trình (cli.main) thay vì tiến trình con, để đo được mọi thứ.

Kiểm tra: batch lỗi -> "Làm nốt phần thiếu"; cuốn dở -> "Làm tiếp"; "Vẽ lại" từng trang (kể cả trang lịch AI,
bìa; loại lịch in sẵn không có trang lịch); "Hoàn thiện" / "Làm lại ảnh quảng cáo"; bấm dồn dập nhiều cuốn lúc
batch đang chạy (chạy lần lượt, gộp việc trùng); tắt tool giữa hàng đợi rồi mở lại.
"""
import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli, config, layout, pipeline
from calforge.imagegen.plan import job_done
from calforge.ui import server
from calforge.ui.batch_queue import BatchQueue

from tests import test_batch_simulation as tb


class InProcessTasks:
    """Thay TaskManager: mỗi tác vụ chạy cli.main(args) trong một luồng; ghi lại để kiểm tra chạy chồng."""

    def __init__(self):
        self.tasks, self.lock, self.log = {}, threading.Lock(), []
        self.active, self.overlap, self.n = 0, False, 0

    class T:
        def __init__(self, action, params):
            self.status, self.action, self.params = "running", action, params

    def running(self, include_login=False):
        with self.lock:
            return next((t for t in self.tasks.values() if t.status == "running"), None)

    def start_task(self, args, desc, action, params):
        with self.lock:
            self.n += 1
            tid = f"t{self.n}"
            t = self.tasks[tid] = self.T(action, params)
            self.log.append(list(args))

        def go():
            with self.lock:
                self.active += 1
                self.overlap |= self.active > 1
            code = 0
            try:
                cli.main(list(args))
            except SystemExit as e:
                code = 0 if e.code in (None, 0) else 1
            except Exception:  # noqa: BLE001
                code = 1
            finally:
                with self.lock:
                    self.active -= 1
                    t.status = "success" if code == 0 else "failed"
        threading.Thread(target=go, daemon=True).start()
        return tid

    def stop_task(self, tid):
        return False


class Recovery(unittest.TestCase):
    def setUp(self):
        self.sim = tb.Sim(self, 42)
        cfg = self.sim.cfg
        p = mock.patch.object(config, "load", lambda: json.loads(json.dumps(cfg)))
        p.start()
        self.addCleanup(p.stop)
        self.root = Path(cfg["projects_dir"])

    # ---------- tiện ích ----------
    def queue(self, tasks=None):
        tasks = tasks or InProcessTasks()
        q = BatchQueue(tasks, self.root / ".hang_doi.json", server.run_args, server._batch_result)
        return q, tasks

    def drain(self, q, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            q.tick()
            items = q.snapshot()["items"]
            if items and all(i["status"] not in ("queued", "running") for i in items):
                return items
            time.sleep(0.05)
        self.fail(f"hàng đợi không xong sau {timeout}s: {q.snapshot()}")

    def rel(self, b):
        return str(b.relative_to(server.ROOT)) if str(b).startswith(str(server.ROOT)) else str(b)

    def book_params(self, b, action, **kw):
        return {"action": action, "concept": str(b), "title": b.name, **kw}

    def status(self, b):
        return json.loads(layout.status_file(b).read_text(encoding="utf-8"))

    # ---------- kịch bản ----------
    def test_failed_batch_then_make_up_missing_via_queue(self):
        w = self.sim.world
        w.fault = 3.0                                               # lỗi dày gấp 3: chắc chắn có cuốn hỏng
        q, tasks = self.queue()
        q.add({"keyword": "frogs", "batch_size": 6, "product": "wall_grid", "grid_mode": "ai_page"})
        items = self.drain(q)
        first = items[-1]
        self.assertIn(first["status"], ("done", "partial", "failed"))
        w.fault = 0.0                                               # người dùng bấm lại lúc tài khoản ổn
        for _ in range(3):
            if q.snapshot()["items"][-1].get("ok") == 6:
                break
            q.add({**first["params"], "resume": True})              # nút "Làm nốt phần thiếu"
            self.drain(q)
        last = q.snapshot()["items"][-1]
        self.assertEqual((last["ok"], last["total"], last["status"]), (6, 6, "done"),
                         json.dumps(q.snapshot()["items"], ensure_ascii=False)[:1500])
        self.assertEqual(len(self.sim.books("frogs")), 6)           # KHÔNG làm thêm 6 cuốn mới
        self.assertFalse(tasks.overlap)
        tb.check_invariants(self, self.sim)

    def test_continue_book_after_all_quota_gone(self):
        w = self.sim.world
        c = dict(self.sim.cfg, quota_max_wait_h=0.00001)           # chờ hồi lượt gần như 0: cuốn dừng "Bị dở"
        with mock.patch.object(config, "load", lambda: json.loads(json.dumps(c))):
            w.image_budget.update({f"acc{i}": 1 for i in range(1, 16)})
            w.refill = {k: 0 for k in w.refill}                     # hết lượt vẽ, không hồi
            q, _ = self.queue()
            q.add({"keyword": "toads", "batch_size": 2, "product": "wall_grid", "grid_mode": "background"})
            self.drain(q)
        stuck = [b for b in self.sim.books("toads") if not pipeline._finished_ok(b)]
        self.assertTrue(stuck, "phải có cuốn dừng vì hết lượt")
        for b in stuck:
            st = self.status(b)
            self.assertEqual((st["ok"], st["stage"]), (False, "images"))
            self.assertIn("thiếu ảnh", st["reason"])
        w.refill = {k: 10 ** 6 for k in w.refill}                   # tài khoản hồi lượt
        w.image_budget.clear()
        q, _ = self.queue()
        for press in range(3):                                      # nút "Làm tiếp" (lỗi ngẫu nhiên: có thể phải bấm lại)
            left = [b for b in stuck if not pipeline._finished_ok(b)]
            if not left:
                break
            n_before = len(q.snapshot()["items"])
            for b in left:
                q.add(self.book_params(b, "produce"))
            items = self.drain(q)[n_before:]
            for i in items:                                         # hàng đợi ghi đúng: cuốn chưa xong = "Lỗi"
                if i["params"].get("action") == "produce":
                    ok = pipeline._finished_ok(Path(i["params"]["concept"]))
                    self.assertEqual(i["status"], "done" if ok else "failed")
        self.assertTrue(all(pipeline._finished_ok(b) for b in self.sim.books("toads")))
        tb.check_invariants(self, self.sim)

    def test_redo_pages_only_touches_chosen_pages(self):
        self.sim.world.fault = 0.0
        q, _ = self.queue()
        q.add({"keyword": "bees", "batch_size": 1, "product": "wall_grid", "grid_mode": "ai_page"})
        self.drain(q)
        [b] = self.sim.books("bees")
        from calforge.publish import r2
        r2.write_state(b, {"files": {"x": {}}, "exported_at": "2026-09-30 10:00:00"})
        before = {j: job_done(b, j).stat().st_mtime_ns for j in ["cover", "m03", "m04", "g05", "g06"]}
        time.sleep(0.02)
        q.pause()                                                   # (như đang có việc khác chạy: các lần bấm phải chờ)
        q.add(self.book_params(b, "redo", pages=["m03", "g05"]))    # bấm "Vẽ lại" 2 lần cùng cuốn: gộp
        q.add(self.book_params(b, "redo", pages=["cover"]))
        q.resume()
        items = self.drain(q)
        self.assertEqual(sum(1 for i in items if i["params"].get("action") == "redo"), 1)
        self.assertEqual(items[-1]["status"], "done")
        after = {j: job_done(b, j).stat().st_mtime_ns for j in before}
        for j in ["cover", "m03", "g05"]:
            self.assertNotEqual(before[j], after[j], f"{j} phải được vẽ lại")
        for j in ["m04", "g06"]:
            self.assertEqual(before[j], after[j], f"{j} không được đụng tới")
        old = sorted(p.name for p in layout.tech(b, "anh_cu").iterdir())
        self.assertEqual(len(old), 3)                               # ảnh cũ được cất, không mất
        self.assertNotIn("exported_at", r2.read_state(b))           # lần xuất CSV sau có bản mới
        self.assertTrue(pipeline._finished_ok(b))

    def test_redo_grid_on_premade_is_refused_without_touching_files(self):
        self.sim.world.fault = 0.0
        q, _ = self.queue()
        q.add({"keyword": "cows", "batch_size": 1, "product": "wall_premade"})
        self.drain(q)
        [b] = self.sim.books("cows", "wall_premade")
        before = sorted(p.name for p in layout.raw(b).iterdir())
        with self.assertRaises(ValueError):
            server.run_args(self.book_params(b, "redo", pages=[]))   # chưa chọn trang: báo ngay lúc bấm
        q.add(self.book_params(b, "redo", pages=["grid"]))          # grid in sẵn: không có trang lịch để vẽ lại
        items = self.drain(q)
        self.assertEqual(items[-1]["status"], "failed")
        self.assertEqual(before, sorted(p.name for p in layout.raw(b).iterdir()))
        self.assertTrue(pipeline._finished_ok(b))                   # cuốn vẫn nguyên, vẫn "Xong"

    def test_finish_and_redo_previews(self):
        self.sim.world.fault = 0.0
        q, _ = self.queue()
        q.add({"keyword": "ducks", "batch_size": 1, "product": "wall_grid", "grid_mode": "background"})
        self.drain(q)
        [b] = self.sim.books("ducks")
        pipeline._status(b, stage="crash", ok=False, reason="RuntimeError: render crashed")   # hậu kỳ sập
        prev = layout.listing(b)
        prev.mkdir(parents=True, exist_ok=True)
        (prev / "01_old.jpg").write_bytes(b"x")
        calls = dict(self.sim.finish_calls)
        q.pause()
        q.add(self.book_params(b, "finish"))                       # "Hoàn thiện"
        q.add(self.book_params(b, "finish", redo_previews=True))   # bấm tiếp "Làm lại ảnh quảng cáo": gộp
        q.resume()
        items = self.drain(q)
        self.assertEqual(sum(1 for i in items if i["params"].get("action") == "finish"), 1)
        self.assertEqual(items[-1]["status"], "done")
        self.assertFalse((prev / "01_old.jpg").exists())            # ảnh quảng cáo cũ đã xoá để làm lại
        self.assertEqual(self.sim.finish_calls[b.name], calls[b.name] + 1)
        self.assertTrue(pipeline._finished_ok(b))

    def test_many_presses_while_batch_runs_are_sequential(self):
        self.sim.world.fault = 0.5
        q, tasks = self.queue()
        q.add({"keyword": "cats", "batch_size": 3, "product": "wall_grid", "grid_mode": "ai_page"})
        self.drain(q)
        books = self.sim.books("cats")
        q.add({"keyword": "dogs", "batch_size": 3, "product": "wall_premade"})    # batch mới đang chạy...
        q.tick()
        for b in books:                                             # ...trong lúc bấm dồn dập ở nhiều cuốn
            q.add(self.book_params(b, "redo", pages=["m02"]))
            q.add(self.book_params(b, "redo", pages=["m09"]))
            q.add(self.book_params(b, "finish", redo_previews=True))
        items = self.drain(q)
        self.assertFalse(tasks.overlap, "hai việc chạy chồng nhau")
        redo = [i for i in items if i["params"].get("action") == "redo"]
        self.assertEqual(len(redo), 3)                              # mỗi cuốn 1 việc vẽ lại (đã gộp m02 + m09)
        self.assertTrue(all(i["params"]["pages"] == ["m02", "m09"] for i in redo))
        self.assertTrue(all(pipeline._finished_ok(b) for b in books))
        tb.check_invariants(self, self.sim)

    def test_tool_restart_mid_queue(self):
        self.sim.world.fault = 0.0
        q1, _ = self.queue(tasks=InProcessTasks())
        q1.add({"keyword": "ants", "batch_size": 2, "product": "wall_grid", "grid_mode": "background"})
        q1.add({"keyword": "bats", "batch_size": 2, "product": "wall_premade"})
        q1.tick()                                                   # batch đầu bắt đầu chạy
        self.assertEqual(q1.snapshot()["items"][0]["status"], "running")
        q2, tasks2 = self.queue()                                   # "tắt tool, mở lại": đọc hàng đợi từ đĩa
        self.assertEqual([i["status"] for i in q2.snapshot()["items"]], ["queued", "queued"])
        time.sleep(0.5)                                             # batch cũ (tiến trình cũ) vẫn chạy nốt một lúc
        items = self.drain(q2)
        self.assertEqual([i["status"] for i in items], ["done", "done"])
        self.assertEqual(len(self.sim.books("ants")), 2)            # chạy lại không nhân đôi cuốn
        self.assertEqual(len(self.sim.books("bats", "wall_premade")), 2)

    def test_redo_previews_regenerates_ai_mockups(self):
        self.sim.world.fault = 0.0
        q, _ = self.queue()
        q.add({"keyword": "koi", "batch_size": 1, "product": "wall_grid", "grid_mode": "ai_page", "mockup_mode": "ai"})
        self.drain(q)
        [b] = self.sim.books("koi")
        first = json.loads(layout.tech(b, "mockup_ai.json").read_text(encoding="utf-8"))
        self.assertEqual(len(first), 5)
        time.sleep(0.02)
        q.add(self.book_params(b, "finish", redo_previews=True))   # "Làm lại ảnh quảng cáo"
        items = self.drain(q)
        self.assertEqual(items[-1]["status"], "done")
        again = json.loads(layout.tech(b, "mockup_ai.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(again), sorted(first))
        self.assertTrue(all(again[k]["mtime_ns"] != first[k]["mtime_ns"] for k in first))   # AI gen lại cả 5


if __name__ == "__main__":
    unittest.main()
