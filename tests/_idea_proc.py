"""Tiến trình con cho test_two_modes: một batch "theo ý tưởng" giả lập - bộ điều phối tài khoản THẬT (khoá giữa các
tiến trình), vòng vẽ ảnh THẬT (driver.run_jobs), Chrome/ChatGPT giả có lỗi: tab đứng treo, không thấy ô chat / nút,
hết lượt. Mỗi lần mượn / trả tài khoản ghi vào file log chung: "<pid> <tài khoản> start|end <thời điểm>".

Chạy: python -m tests._idea_proc <thư mục profiles> <thư mục projects> <file log> <số ảnh> <seed>
"""
import os
import json
import random
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


SIDE = ""


def main():
    pdir, projects, log, n_jobs, seed = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
    from calforge.imagegen import driver
    from calforge.imagegen.driver import GenJob, NavError, QuotaExceeded, TempError, run_jobs
    from calforge.llm import pool as poolmod
    from calforge.llm.pool import AccountPool

    names = sorted(p.name for p in pdir.iterdir() if p.is_dir())
    cfg = {"projects_dir": projects, "profiles_dir": str(pdir)}
    cap = int(sys.argv[6]) if len(sys.argv) > 6 else 6
    global SIDE
    SIDE = sys.argv[7] if len(sys.argv) > 7 else ""      # tên tiến trình trong log (2 batch ý tưởng chạy chồng)
    pool = AccountPool(pdir, names, cap=cap, launch_gap_s=0, leases=True, later=poolmod._plus_saved_for_clone(cfg),
                       global_cap=int(os.environ["CALFORGE_TEST_GLOBAL_CAP"]) if os.environ.get("CALFORGE_TEST_GLOBAL_CAP") else None)
    pool.rest_s = 0.3
    rnd = random.Random(seed)
    lock = threading.Lock()

    def write(line):
        with lock, log.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @contextmanager
    def fake_open(profile):
        write(f"idea{SIDE} {profile} start {time.time():.4f}")
        try:
            idea_barrier = os.environ.get('CALFORGE_TEST_IDEA_PAIR_BARRIER')
            if idea_barrier:
                marker = Path(idea_barrier)
                marker.with_suffix(f'.idea{SIDE}').touch()
                other = '2' if SIDE == '1' else '1'
                deadline = time.monotonic() + 30
                while not marker.with_suffix(f'.idea{other}').exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError('other idea process did not reach overlap barrier')
                    time.sleep(.01)
            barrier = os.environ.get('CALFORGE_TEST_OVERLAP_BARRIER')
            if barrier and profile == os.environ.get('CALFORGE_TEST_OVERLAP_PROFILE'):
                marker = Path(barrier)
                marker.with_suffix('.idea-ready').touch()
                deadline = time.monotonic() + 15
                while not marker.with_suffix('.clone-ready').exists():
                    if time.monotonic() > deadline:
                        raise RuntimeError('clone did not reach overlap barrier')
                    time.sleep(.01)
            yield object()
        finally:
            write(f"idea{SIDE} {profile} end {time.time():.4f}")

    class W:
        def __init__(self, profile_dir, *a, **k):
            self.name = Path(profile_dir).name

        def run_job(self, page, job):
            time.sleep(rnd.uniform(0.02, 0.08))
            with lock:
                r = rnd.random()
            if r < 0.08:
                raise NavError("không thấy ô chat #prompt-textarea (trang chưa tải xong / bị che)")
            if r < 0.14:
                raise TempError("tab kẹt: ChatGPT chưa phản hồi sau 240s")
            if r < 0.18:
                raise QuotaExceeded("You've hit the plus plan limit")
            out = job.out.with_suffix(".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"png")
            return out

    tag = sys.argv[7] if len(sys.argv) > 7 else ""        # 2 batch chạy chồng: mỗi batch một thư mục ảnh riêng
    jobs = [GenJob(f"j{i:02d}", "p", Path(projects) / f"_idea_out{tag}" / f"j{i:02d}") for i in range(n_jobs)]
    todo = jobs
    with mock.patch.object(driver, "_Worker", W), mock.patch.object(driver, "NAV_REST_S", 0.2):
        for _ in range(40):                              # như batch thật: hết tài khoản rảnh thì chờ rồi làm tiếp
            for j in todo:
                j.attempts, j.error = 0, None
            run_jobs(todo, pdir, names, pool=pool, open_page=fake_open, on_event=lambda *_: None, max_attempts=6)
            todo = [j for j in jobs if not j.result]
            if not todo:
                break
            time.sleep(0.3)
    print(json.dumps({"ok": sum(1 for j in jobs if j.result), "total": len(jobs)}))


if __name__ == "__main__":
    main()
