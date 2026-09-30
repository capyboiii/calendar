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
    def __init__(self, tasks, state_file: Path, build_args, report):
        """tasks: TaskManager; build_args(params) -> (cmd_args, desc); report(params) -> (ok, total)."""
        self.tasks, self.file, self.build_args, self.report = tasks, Path(state_file), build_args, report
        self.lock = threading.RLock()
        self.items: list[dict] = []
        self.paused = False
        self._load()
        for it in self.items:                     # tool vừa mở lại: batch "đang chạy" cũ đã chết theo tool
            if it["status"] == RUNNING:
                it.update(status=WAITING, task_id=None)
                if not it["params"].get("action"):      # batch: làm nốt đúng batch đó, không mở batch N cuốn mới
                    it["params"] = {**it["params"], "resume": True}
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
                    same["params"] = {**same["params"], "redo_previews": True}
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
            cur = self._running()
            if cur:                                   # đưa batch đang chạy về đầu hàng, làm nốt khi Tiếp tục
                task_id = cur["task_id"]
                cur.update(status=WAITING, task_id=None, paused_from=True)
                if not cur["params"].get("action"):     # Tiếp tục = làm nốt đúng batch đang dở
                    cur["params"] = {**cur["params"], "resume": True}
                self.items.remove(cur)
                first = next((k for k, i in enumerate(self.items) if i["status"] == WAITING), len(self.items))
                self.items.insert(first, cur)
            else:
                task_id = None
            self._save()
        if task_id:
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
        """Cập nhật batch đang chạy; nếu rảnh (không tạm dừng, không việc chính nào chạy) thì chạy batch kế tiếp."""
        with self.lock:
            cur = self._running()
            if cur:
                t = self.tasks.tasks.get(cur["task_id"])
                if t is not None and t.status == "running":
                    return
                status = t.status if t is not None else "failed"
                ok, total = self.report(cur["params"])
                if status == "stopped" or cur.get("user_stopped"):
                    final = STOPPED
                elif status != "success" or (total and ok == 0):
                    final = FAILED                       # chạy hết mà không cuốn nào đạt = lỗi, không phải "xong"
                elif total and ok < total:
                    final = PARTIAL
                else:
                    final = DONE
                cur.update(finished_at=time.strftime("%Y-%m-%d %H:%M:%S"), ok=ok, total=total, status=final)
                self._save()
            if self.paused or self.tasks.running():
                return
            nxt = next((i for i in self.items if i["status"] == WAITING), None)
            if not nxt:
                return
            cmd_args, desc = self.build_args(nxt["params"])
            nxt.update(status=RUNNING, task_id=self.tasks.start_task(cmd_args, desc, "run", nxt["params"]),
                       started_at=time.strftime("%Y-%m-%d %H:%M:%S"), user_stopped=False)
            self._save()

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
