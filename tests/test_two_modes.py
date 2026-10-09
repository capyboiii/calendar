"""Batch "theo ý tưởng" và "Clone sản phẩm" chạy SONG SONG trên 2 tiến trình thật, chung một thư mục tài khoản.

Tiến trình con (tests/_idea_proc.py): bộ điều phối tài khoản thật + vòng vẽ ảnh thật của trang chính.
Tiến trình này: hàng đợi clone thật (run_queue, Book, run_stage, Accounts) trên bộ điều phối thật có khoá tài khoản.
Cả hai có lỗi gài sẵn: tab đứng treo, không thấy ô chat / nút gửi, hết lượt, tài khoản bị đăng xuất.
Kiểm tra: không bao giờ hai bên dùng cùng một tài khoản cùng lúc; clone chỉ dùng tài khoản Plus; batch theo ý tưởng
lấy tài khoản Free trước khi clone còn việc; cả hai bên đều làm xong hết việc dù gặp lỗi.
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge.clone import run, store
from calforge.imagegen.driver import NavError, QuotaExceeded, TempError
from calforge.llm import plan
from calforge.llm.pool import AccountPool

from tests.test_clone import png
from tests.test_clone_errors import FakeSession, World, complete

ROOT = Path(__file__).resolve().parents[1]
PLUS = ["acc3", "acc4", "acc5", "acc6"]
FREE = ["acc1", "acc2"]


def intervals(log: Path) -> dict:
    """{tài khoản: [(bên, bắt đầu, kết thúc)]} từ log của hai tiến trình: mỗi tiến trình ghi file riêng (<log>.idea /
    <log>.clone) - hai tiến trình cùng ghi một file thì dòng có thể chen nhau."""
    open_at, out = {}, {}
    lines = []
    for f in (log, log.with_name(log.name + ".idea"), log.with_name(log.name + ".clone")):
        if f.is_file():
            lines += f.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if len(line.split()) != 4:
            continue
        side, acc, what, t = line.split()
        key = (side, acc)
        if what == "start":
            open_at.setdefault(key, []).append(float(t))
        else:
            out.setdefault(acc, []).append((side, open_at[key].pop(0), float(t)))
    return out


class TwoModesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.pdir = self.root / "prof"
        for n in FREE + PLUS:
            (self.pdir / n).mkdir(parents=True)
            plan.save(self.pdir / n, {"plan": "plus" if n in PLUS else "free", "label": "x", "active": True,
                                      "expires": "2030-01-01T00:00:00+00:00"})
        self.cfg = {"projects_dir": str(self.root / "projects"), "profiles_dir": str(self.pdir), "imagegen": {},
                    "quota_max_wait_h": 0.01}
        self.log = self.root / "use.log"
        self.log.write_text("", encoding="utf-8")
        self.lock = threading.Lock()

    def clone_accounts(self, faults):
        world = World(faults)
        pool = AccountPool(self.pdir, FREE + PLUS, cap=6, launch_gap_s=0, leases=True)
        pool.rest_s = 0.3

        @contextmanager
        def logged_open(name):
            with self.lock, self.log.open("a", encoding="utf-8") as f:
                f.write(f"clone {name} start {time.time():.4f}\n")
            try:
                yield name
            finally:
                with self.lock, self.log.open("a", encoding="utf-8") as f:
                    f.write(f"clone {name} end {time.time():.4f}\n")

        accts = run.Accounts(self.cfg, PLUS, on_event=lambda *_: None, pool=pool, open_page=logged_open)
        return world, accts

    def run_both(self, n_books, idea_jobs, faults, seed=7):
        ds = [store.root(self.cfg["projects_dir"]) / store.add(
            self.cfg["projects_dir"], [(f"r{i}.png", png((i * 40, 30, 60))) for i in range(3)], group="hai-luong")["id"]
              for _ in range(n_books)]
        world, accts = self.clone_accounts(faults)
        idea = subprocess.Popen([sys.executable, "-m", "tests._idea_proc", str(self.pdir), self.cfg["projects_dir"],
                                 str(self.log.with_name(self.log.name + ".idea")), str(idea_jobs), str(seed)], cwd=str(ROOT),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: idea.poll() is None and idea.kill())
        with mock.patch.object(run.session, "Session", lambda page, pdir: FakeSession(world, Path(pdir).name)), \
                mock.patch("calforge.imagegen.generate.accept_grid_page", world.accept), \
                mock.patch.object(run.Book, "finish", lambda self, plus: {"ok": True, "stage": "listing"}), \
                mock.patch.object(run, "GRID_POLL_S", 0.05), mock.patch.object(run.driver, "NAV_REST_S", 0.2), \
                mock.patch.object(run, "MAX_SESSIONS", 12):
            run.run_queue(self.cfg, on_event=lambda *_: None, accts=accts, plus=PLUS)
        out, err = idea.communicate(timeout=240)
        self.assertEqual(idea.returncode, 0, err[-800:])
        summary = json.loads(out.strip().splitlines()[-1])
        return ds, world, accts, summary

    def check_no_shared_account(self):
        use = intervals(self.log)
        for acc, spans in use.items():
            spans.sort(key=lambda x: x[1])
            for (s1, a1, b1), (s2, a2, b2) in zip(spans, spans[1:]):
                self.assertLessEqual(b1, a2 + 1e-3, f"{acc}: {s1} [{a1:.3f}-{b1:.3f}] chồng {s2} [{a2:.3f}-{b2:.3f}]")
        # hai tiến trình thật sự chạy CÙNG LÚC (trên tài khoản khác nhau), không phải lần lượt
        idea = [(a, b) for spans in use.values() for s, a, b in spans if s == "idea"]
        clone = [(a, b) for spans in use.values() for s, a, b in spans if s == "clone"]
        self.assertTrue(any(a1 < b2 and a2 < b1 for a1, b1 in idea for a2, b2 in clone), "hai bên không chạy song song")
        return use

    def test_both_modes_together_with_hangs_missing_buttons_and_quota(self):
        lock = threading.Lock()
        seen = {"n": 0}

        def faults(acc, kind, n):
            with lock:
                seen["n"] += 1
                k = seen["n"]
            if k % 9 == 0:
                return TempError("tab kẹt: ChatGPT chưa phản hồi sau 240s")                 # đứng treo
            if k % 13 == 0:
                return NavError("không thấy ô chat #prompt-textarea (trang chưa tải xong / bị che)")   # mất nút
            if k % 17 == 0:
                return NavError("không bấm gửi được: Timeout 4000ms exceeded")             # nút gửi không bấm được
            if k == 5:
                return QuotaExceeded("You've hit the plus plan limit")
            return None
        ds, world, accts, idea = self.run_both(3, 40, faults)
        for d in ds:
            complete(self, d)
        self.assertEqual(idea, {"ok": 40, "total": 40})                       # batch theo ý tưởng cũng xong hết
        use = self.check_no_shared_account()
        clone_accs = {a for a, spans in use.items() for s, *_ in spans if s == "clone"}
        self.assertTrue(clone_accs <= set(PLUS))                              # clone chỉ dùng Plus
        idea_free = sum(1 for a in FREE for s, *_ in use.get(a, []) if s == "idea")
        self.assertGreater(idea_free, 0)                                      # batch theo ý tưởng có dùng Free
        leases = list(self.pdir.glob("*/.calforge_lease"))
        self.assertEqual(leases, [])                                          # trả hết khoá khi xong

    def test_dead_account_in_clone_does_not_block_idea(self):
        def faults(acc, kind, n):
            if acc == "acc3" and kind == "open":
                return NavError("tài khoản bị đăng xuất: trang ChatGPT đòi đăng nhập lại")
            return None
        ds, world, accts, idea = self.run_both(2, 25, faults, seed=11)
        for d in ds:
            complete(self, d)
        self.assertEqual(idea["ok"], 25)
        self.check_no_shared_account()
        self.assertIn("acc3", accts.pool.dead)


if __name__ == "__main__":
    unittest.main()
