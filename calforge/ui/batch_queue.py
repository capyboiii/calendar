"""Hàng đợi batch: bấm Bắt đầu nhiều lần = xếp nhiều batch, máy chạy lần lượt từng batch một.

- Lưu ở projects/.hang_doi.json nên tắt/mở lại tool vẫn còn hàng đợi (batch đang chạy dở được xếp lại đầu hàng,
  chạy lại chỉ làm nốt phần thiếu nhờ _he_thong/batch.json của từng chủ đề).
- Tạm dừng: dừng batch đang chạy (phần đã làm giữ nguyên), đưa nó về đầu hàng, không chạy batch nào nữa tới khi
  bấm Tiếp tục.
- Danh sách xong: batch đã chạy xong / lỗi / bị dừng, kèm số cuốn đạt theo báo cáo batch.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

WAITING, RUNNING, DONE, FAILED, STOPPED = "queued", "running", "done", "failed", "stopped"
PARTIAL = "partial"          # chạy xong nhưng chỉ đạt một phần số cuốn


class BatchQueue:
    def __init__(self, tasks, state_file: Path, build_args, report, ideas_done=None):
        """tasks: TaskManager; report(params) -> (ok, total[, retryable]);
        ideas_done(params) -> True khi batch đó đã lên đủ ý, chỉ còn vẽ (thì chủ đề kế tiếp được bắt đầu lên ý)."""
        self.tasks, self.file, self.build_args, self.report = tasks, Path(state_file), build_args, report
        self.ideas_done = ideas_done or (lambda params: False)
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.paused = False
        self._load()
        for it in self.items:                     # tool vừa mở lại: batch "đang chạy" cũ đã chết theo tool
            if it["status"] == RUNNING:
                it.update(status=WAITING, task_id=None)
                if not it["params"].get("action"):      # batch: làm nốt đúng batch đó, không mở batch N cuốn mới
                    it["params"] = {**it["params"], "resume": True}
            elif it["status"] not in (WAITING, RUNNING) and "retryable" not in it:
                # Nâng cấp dữ liệu hàng đợi cũ: ẩn nút thử lại nếu giờ chỉ còn cuốn terminal/TM.
                try:
                    result = self.report(it["params"])
                    ok, total = result[:2]
                    it["retryable"] = bool(result[2]) if len(result) > 2 else (not total or ok < total)
                except Exception:  # noqa: BLE001 - dữ liệu lịch sử hỏng không được ngăn UI khởi động
                    it["retryable"] = True
        self._save()

    # ---- lưu trạng thái -------------------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            self.items, self.paused = list(data.get("items", [])), bool(data.get("paused"))
        except (OSError, ValueError):
            self.items, self.paused = [], False

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"paused": self.paused, "items": self.items}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.file)

    # ---- thao tác từ UI --------------------------------------------------------------------------------------
    def add(self, params: dict) -> dict:
        self.build_args(params)                  # kiểm tra tham số ngay (thiếu chủ đề -> báo lỗi lúc bấm)
        with self.lock:
            same = self._same_book_waiting(params)
            if same is not None:                 # bấm lại cho cùng một cuốn khi việc cũ còn đang chờ: gộp, không nhân đôi
                if params.get("action") == "redo":
                    pages = list(dict.fromkeys((same["params"].get("pages") or []) + (params.get("pages") or [])))
                    same["params"] = {**same["params"], "pages": pages}
                elif params.get("redo_previews"):
                    old, new = same["params"].get("redo_previews"), params["redo_previews"]
                    if isinstance(old, list) and isinstance(new, list):     # gen lại từng ảnh: gộp danh sách
                        merged = list(dict.fromkeys(old + new))
                    else:                                                   # có "làm lại cả 5" thì làm cả 5
                        merged = True
                    same["params"] = {**same["params"], "redo_previews": merged}
                self._save()
                return same
            item = {"id": f"q_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}", "params": params,
                    "status": WAITING, "task_id": None,
                    "added_at": time.strftime("%Y-%m-%d %H:%M:%S"), "started_at": "", "finished_at": ""}
            self.items.append(item)
            self._save()
        self.tick()
        return item

    def _same_book_waiting(self, params: dict) -> dict | None:
        """Việc ĐANG CHỜ cùng loại (vẽ lại / làm tiếp / hoàn thiện) cho đúng cuốn này, nếu có."""
        action, concept = params.get("action"), params.get("concept")
        if not action or not concept:
            return None
        return next((i for i in self.items if i["status"] == WAITING and i["params"].get("action") == action
                     and i["params"].get("concept") == concept), None)

    def remove(self, item_id: str) -> bool:
        """Bỏ một batch đang chờ, hoặc xoá một dòng khỏi danh sách xong (batch đang chạy thì phải Dừng trước)."""
        with self.lock:
            it = self._get(item_id)
            if not it or it["status"] == RUNNING:
                return False
            self.items.remove(it)
            self._save()
            return True

    def move(self, item_id: str, delta: int) -> bool:
        """Đổi thứ tự trong các batch đang chờ (-1 = lên trước, 1 = xuống sau)."""
        with self.lock:
            waiting = [i for i in self.items if i["status"] == WAITING]
            it = self._get(item_id)
            if it not in waiting:
                return False
            j = waiting.index(it) + delta
            if not 0 <= j < len(waiting):
                return False
            a, b = self.items.index(it), self.items.index(waiting[j])
            self.items[a], self.items[b] = self.items[b], self.items[a]
            self._save()
            return True

    def pause(self) -> None:
        with self.lock:
            self.paused = True
            task_ids = []
            # đưa MỌI batch đang chạy (có thể 2: batch đang vẽ nốt + chủ đề kế tiếp đang lên ý) về đầu hàng, giữ thứ tự
            for cur in reversed(self._runnings()):
                task_ids.append(cur["task_id"])
                cur.update(status=WAITING, task_id=None, paused_from=True)
                if not cur["params"].get("action"):     # Tiếp tục = làm nốt đúng batch đang dở
                    cur["params"] = {**cur["params"], "resume": True}
                self.items.remove(cur)
                first = next((k for k, i in enumerate(self.items) if i["status"] == WAITING), len(self.items))
                self.items.insert(first, cur)
            self._save()
        for task_id in task_ids:
            self.tasks.stop_task(task_id)

    def resume(self) -> None:
        with self.lock:
            self.paused = False
            self._save()
        self.tick()

    def clear_finished(self) -> None:
        with self.lock:
            self.items = [i for i in self.items if i["status"] in (WAITING, RUNNING)]
            self._save()

    def stopped_by_user(self, task_id: str) -> None:
        """Nút Dừng của batch đang chạy: batch này vào danh sách xong (Đã dừng), hàng đợi đi tiếp."""
        with self.lock:
            it = next((i for i in self.items if i.get("task_id") == task_id and i["status"] == RUNNING), None)
            if it:
                it["user_stopped"] = True
                self._save()

    # ---- vòng chạy -----------------------------------------------------------------------------------------
    def tick(self) -> None:
        """Cập nhật các batch đang chạy; rảnh (không tạm dừng, không việc chính nào chạy) thì chạy batch kế tiếp.
        CHỒNG LƯỢT: batch đang chạy đã lên đủ ý (chỉ còn vẽ nốt - phần lớn tài khoản rảnh) thì chủ đề kế tiếp được
        bắt đầu luôn để lên ý trước; tối đa 2 batch cùng lúc (hai tiến trình chia tài khoản bằng khoá trong profile)."""
        with self.lock:
            for cur in self._runnings():
                t = self.tasks.tasks.get(cur["task_id"])
                if t is None or t.status != "running":
                    self._finish(cur, t)
            running = self._runnings()
            if self.paused:
                return
            if running:
                if not self._can_overlap(running):
                    return
            elif self.tasks.running():                 # việc chính ngoài hàng đợi (người dùng tự bấm) đang chạy
                return
            nxt = next((i for i in self.items if i["status"] == WAITING), None)
            if not nxt or (running and not self._overlap_ok(nxt, running[0])):
                return
            try:
                # Trạng thái trên đĩa có thể đổi trong lúc chờ (ví dụ cuốn vừa bị loại vì TM).
                cmd_args, desc = self.build_args(nxt["params"])
            except (OSError, ValueError) as e:
                nxt.update(status=FAILED, task_id=None, ok=0, total=1, retryable=False,
                           error=str(e), finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
                self._save()
                return
            nxt.update(status=RUNNING, task_id=self.tasks.start_task(cmd_args, desc, "run", nxt["params"]),
                       started_at=time.strftime("%Y-%m-%d %H:%M:%S"), user_stopped=False, overlapped=bool(running))
            self._save()

    def _finish(self, cur: dict, t) -> None:
        """Batch vừa dừng chạy: ghi kết quả (xong / một phần / lỗi / đã dừng) theo báo cáo batch."""
        status = t.status if t is not None else "failed"
        result = self.report(cur["params"])
        ok, total = result[:2]
        retryable = bool(result[2]) if len(result) > 2 else (not total or ok < total)
        if status == "stopped" or cur.get("user_stopped"):
            final = STOPPED
        elif status != "success" or (total and ok == 0):
            final = FAILED                       # chạy hết mà không cuốn nào đạt = lỗi, không phải "xong"
        elif total and ok < total:
            final = PARTIAL
        else:
            final = DONE
        cur.update(finished_at=time.strftime("%Y-%m-%d %H:%M:%S"), ok=ok, total=total,
                   retryable=retryable, status=final)
        self._save()

    def _can_overlap(self, running: list[dict]) -> bool:
        """Đúng 1 batch đang chạy, là batch theo ý tưởng, và nó đã lên đủ ý (chỉ còn vẽ nốt)."""
        if len(running) != 1 or running[0]["params"].get("action"):
            return False
        try:
            return bool(self.ideas_done(running[0]["params"]))
        except Exception:  # noqa: BLE001 - đọc trạng thái lỗi: không chồng lượt, chạy tuần tự như cũ
            return False

    @staticmethod
    def _overlap_ok(nxt: dict, cur: dict) -> bool:
        """Chỉ chồng một batch theo ý tưởng KHÁC chủ đề (cùng chủ đề thì khoá batch.lock bắt chờ, vô ích); việc sửa
        sách lẻ (Làm tiếp / Vẽ lại / Hoàn thiện) vẫn chờ chạy sau như cũ."""
        p, q = nxt["params"], cur["params"]
        return not p.get("action") and (p.get("keyword"), p.get("product")) != (q.get("keyword"), q.get("product"))

    def start(self, every: float = 2.0) -> None:
        def loop():
            while True:
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 - vòng hàng đợi không được chết
                    print(f"Hàng đợi lỗi: {e}")
                time.sleep(every)
        threading.Thread(target=loop, daemon=True, name="batch-queue").start()

    def snapshot(self) -> dict:
        with self.lock:
            return {"paused": self.paused, "items": [dict(i) for i in self.items]}

    def _get(self, item_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == item_id), None)

    def _running(self) -> dict | None:
        return next((i for i in self.items if i["status"] == RUNNING), None)

    def _runnings(self) -> list[dict]:
        return [i for i in self.items if i["status"] == RUNNING]
