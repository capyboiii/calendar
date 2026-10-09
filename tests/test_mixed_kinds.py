"""Chạy LẪN nhiều loại với hàng chục tài khoản: nhiều cuốn clone trong một lượt; và cùng lúc một
batch "theo ý tưởng" ở tiến trình khác. Lỗi gài ngẫu nhiên: hết lượt giữa chừng, tab đứng treo, không thấy ô chat /
nút gửi, lỗi server, lỗi mạng (Playwright hết giờ, đính ảnh lỗi), tài khoản bị đăng xuất / bị khoá, ChatGPT từ chối,
tiến trình bị tắt ngang. Code điều phối / xử lý lỗi là code thật; chỉ Chrome / ChatGPT là giả."""
import json
import random
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
from calforge.imagegen.driver import NavError, QuotaExceeded, TempError, ThirdPartyIPRefused
from calforge.llm import plan
from calforge.llm.pool import AccountPool

from tests.test_clone import META, png
from tests.test_clone_errors import FakeSession, Killed, World, complete, partial, setup

PLUS20 = [f"acc{i}" for i in range(1, 21)]


class MixedSession(FakeSession):
    """Phiên giả loại Thường + gài từ chối theo prompt."""
    refuse = None                                         # hàm (prompt) -> Exception | None, gài theo từng test

    def ask_text(self, prompt):
        err = self._fault("meta")
        if err:
            raise err
        return "```json\n" + json.dumps(META) + "\n```"

    def ask_images(self, prompt, want, attach=None):
        if MixedSession.refuse:
            err = MixedSession.refuse(prompt, attach)
            if err:
                raise err
        return super().ask_images(prompt, want, attach)



def random_faults(seed, dead=None):
    rnd, lock = random.Random(seed), threading.Lock()
    dead = dead or {}

    def faults(acc, kind, n):
        if dead.get(acc) == kind:
            return NavError("tài khoản bị đăng xuất: trang ChatGPT đòi đăng nhập lại") if kind == "open" else \
                NavError("tài khoản bị khoá: Your account has been deactivated")
        with lock:
            r = rnd.random()
        if r < 0.03:
            return partial(QuotaExceeded("You've hit the plus plan limit"))
        if r < 0.07:
            return TempError("tab kẹt: ChatGPT chưa phản hồi sau 240s")                      # đứng treo
        if r < 0.11:
            return NavError("không thấy ô chat #prompt-textarea (trang chưa tải xong / bị che)")   # mất nút
        if r < 0.13:
            return NavError("không bấm gửi được: Timeout 4000ms exceeded")
        if r < 0.15:
            return TimeoutError("Page.goto: Timeout 90000ms exceeded")                        # mạng
        if r < 0.18:
            return TempError("ChatGPT báo lỗi: 'Internal server error'")                     # server
        return None
    return faults


class MixedQueueTest(unittest.TestCase):
    def build(self, n_normal, faults, plus=PLUS20):
        cfg, ds, world, pool, go = setup(self, n_books=n_normal, faults=faults, plus=plus)
        p = mock.patch.object(run.session, "Session", lambda page, pdir: MixedSession(world, Path(pdir).name))
        p.start()
        self.addCleanup(p.stop)
        for q in (mock.patch.object(run, "GRID_POLL_S", 0.05), mock.patch.object(run, "MAX_SESSIONS", 12),
                  mock.patch.object(run.driver, "NAV_REST_S", 0.2)):
            q.start()
            self.addCleanup(q.stop)
        MixedSession.refuse = None
        self.addCleanup(lambda: setattr(MixedSession, "refuse", None))
        return cfg, ds, world, pool, go

    def test_many_books_on_20_accounts_with_random_faults(self):
        cfg, normals, world, pool, go = self.build(12, random_faults(3, dead={"acc7": "open", "acc12": "grid"}))
        bad_normal = normals[2].name

        def refuse(prompt, attach):
            if attach and any(bad_normal in str(a) for a in attach):           # một cuốn Thường dính bản quyền
                return ThirdPartyIPRefused("I can't create that: it may infringe third-party rights")
            return None
        MixedSession.refuse = refuse
        res = go()
        self.assertEqual(len(res), 12)
        self.assertEqual(store.read(normals[2])["status"], "rejected")       # chỉ đúng cuốn dính bản quyền bị bỏ
        for d in normals[:2] + normals[3:]:
            complete(self, d)
        self.assertEqual(world.peak_same, 1)                                   # không tài khoản nào làm 2 việc một lúc
        self.assertIn(("acc7", "logged_out"), pool.dropped)                 # tài khoản bị đăng xuất: bỏ hẳn
        self.assertTrue(set(pool.dropped) <= {("acc7", "logged_out"), ("acc12", "banned")})
        used_after = [a for a in world.used[world.used.index("acc7") + 1:] if a == "acc7"] if "acc7" in world.used else []
        self.assertEqual(used_after, [])                                       # tài khoản chết không được dùng lại
        self.assertGreaterEqual(len(set(world.used)), 12)                      # thật sự trải trên hàng chục tài khoản
        self.assertEqual(pool.use, {})

    def test_kill_mid_run_then_resume(self):
        state = {"n": 0, "killed": False}
        lock = threading.Lock()

        def faults(acc, kind, n):
            with lock:
                state["n"] += 1
                if state["n"] == 40 and not state["killed"]:
                    state["killed"] = True
                    raise Killed()                                             # tắt ngang tiến trình
            return None
        cfg, normals, world, pool, go = self.build(6, faults)
        with self.assertRaises(Killed):
            go()
        self.assertGreaterEqual(store.mark_stopped(cfg["projects_dir"]), 1)   # giao diện: "Đã dừng"
        for d in normals:
            if store.read(d)["status"] == "failed":
                store.retry(cfg["projects_dir"], d.name)
        go()
        for d in normals:
            complete(self, d)
        self.assertEqual(pool.use, {})

    def test_all_accounts_out_of_quota_then_recovers(self):
        state = {"broken": True}

        def faults(acc, kind, n):
            return QuotaExceeded("You've hit the plus plan limit") if state["broken"] and kind in ("art", "meta") else None
        cfg, normals, world, pool, go = self.build(4, faults, plus=[f"acc{i}" for i in range(1, 11)])
        with mock.patch.object(run, "MAX_SESSIONS", 2):
            go()
        for d in normals:
            self.assertEqual(store.read(d)["status"], "failed", store.read(d))
        state["broken"] = False
        pool.resting.clear()                                                   # hết giờ nghỉ: tài khoản hồi lượt
        for d in normals:
            store.retry(cfg["projects_dir"], d.name)
        go()
        for d in normals:
            complete(self, d)


class TwoProcessesMixedTest(unittest.TestCase):
    """Tiến trình con chạy batch theo ý tưởng (tests/_idea_proc.py) trên 24 tài khoản, tiến trình này chạy hàng
    đợi clone trên 16 tài khoản Plus - cùng thư mục tài khoản, khoá thật giữa hai tiến trình."""
    FREE = [f"free{i}" for i in range(1, 9)]
    PLUS = [f"plus{i:02d}" for i in range(1, 17)]
    K12 = set()                                       # tài khoản K12 (workspace): tính như Plus
    BOOKS, IDEA_JOBS, CLONE_CAP, IDEA_CAP, MIN_CLONE_ACCS = 8, 80, 24, 6, 8

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.pdir = self.root / "prof"
        for n in self.FREE + self.PLUS:
            (self.pdir / n).mkdir(parents=True)
            kind = "k12" if n in self.K12 else "plus" if n in self.PLUS else "free"
            plan.save(self.pdir / n, {"plan": kind, "label": "x", "active": True,
                                      "expires": "2030-01-01T00:00:00+00:00"})
        self.cfg = {"projects_dir": str(self.root / "projects"), "profiles_dir": str(self.pdir), "imagegen": {},
                    "quota_max_wait_h": 0.01}
        self.log = self.root / "use.log"
        self.log.write_text("", encoding="utf-8")

    def test_idea_batch_and_clone_never_share_accounts(self):
        lock = threading.Lock()
        normals = [store.root(self.cfg["projects_dir"]) / store.add(
            self.cfg["projects_dir"], [(f"r{i}.png", png((i * 40, 30, 60))) for i in range(3)], group="hai")["id"]
            for _ in range(self.BOOKS)]
        world = World(random_faults(5, dead={"plus05": "open"}))
        pool = AccountPool(self.pdir, self.FREE + self.PLUS, cap=self.CLONE_CAP, launch_gap_s=0, leases=True)
        pool.rest_s = 0.3

        @contextmanager
        def logged_open(name):
            with lock, self.log.open("a", encoding="utf-8") as f:
                f.write(f"clone {name} start {time.time():.4f}\n")
            try:
                yield name
            finally:
                with lock, self.log.open("a", encoding="utf-8") as f:
                    f.write(f"clone {name} end {time.time():.4f}\n")
        accts = run.Accounts(self.cfg, self.PLUS, on_event=lambda *_: None, pool=pool, open_page=logged_open)
        idea = subprocess.Popen([sys.executable, "-m", "tests._idea_proc", str(self.pdir), self.cfg["projects_dir"],
                                 str(self.log.with_name(self.log.name + ".idea")), str(self.IDEA_JOBS), "9",
                                 str(self.IDEA_CAP)], cwd=str(Path(__file__).resolve().parents[1]),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: idea.poll() is None and idea.kill())
        with mock.patch.object(run.session, "Session", lambda page, pdir: MixedSession(world, Path(pdir).name)), \
                mock.patch("calforge.imagegen.generate.accept_grid_page", world.accept), \
                mock.patch.object(run.Book, "finish", lambda self, plus: {"ok": True, "stage": "listing"}), \
                mock.patch.object(run, "GRID_POLL_S", 0.05), mock.patch.object(run.driver, "NAV_REST_S", 0.2), \
                mock.patch.object(run, "MAX_SESSIONS", 12):
            run.run_queue(self.cfg, on_event=lambda *_: None, accts=accts, plus=self.PLUS)
        out, err = idea.communicate(timeout=300)
        self.assertEqual(idea.returncode, 0, err[-800:])
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), {"ok": self.IDEA_JOBS, "total": self.IDEA_JOBS})
        for d in normals:
            complete(self, d)
        from tests.test_two_modes import intervals
        use = intervals(self.log)
        for acc, spans in use.items():
            spans.sort(key=lambda x: x[1])
            for (s1, a1, b1), (s2, a2, b2) in zip(spans, spans[1:]):
                self.assertLessEqual(b1, a2 + 1e-3, f"{acc}: {s1} chồng {s2}")
        clone_accs = {a for a, spans in use.items() for s, *_ in spans if s == "clone"}
        self.assertTrue(clone_accs <= set(self.PLUS))
        self.assertGreaterEqual(len(clone_accs), self.MIN_CLONE_ACCS)
        if self.K12:
            self.assertTrue(clone_accs & self.K12)                             # K12 vẽ clone như Plus
            self.assertTrue(all(plan.is_paid(plan.read(self.pdir / n)) for n in self.K12))
        idea_accs = {a for a, spans in use.items() for s, *_ in spans if s == "idea"}
        self.assertTrue(idea_accs & set(self.FREE))
        idea_spans = [(a, b) for spans in use.values() for s, a, b in spans if s == "idea"]
        clone_spans = [(a, b) for spans in use.values() for s, a, b in spans if s == "clone"]
        self.assertTrue(any(a1 < b2 and a2 < b1 for a1, b1 in idea_spans for a2, b2 in clone_spans))
        self.assertEqual(list(self.pdir.glob("*/.calforge_lease")), [])


class FortyAccountsTwoProcessesTest(TwoProcessesMixedTest):
    """40 tài khoản (20 Free + 10 Plus + 10 K12): batch theo ý tưởng mở tới 20 Chrome, hàng đợi clone 12 cuốn mở
    tới 20 Chrome - cùng lúc, cùng thư mục tài khoản, lỗi ngẫu nhiên; không tài khoản nào bị hai bên dùng chung,
    clone chỉ dùng Plus/K12 và dùng cả K12."""
    FREE = [f"free{i:02d}" for i in range(1, 21)]
    PLUS = [f"plus{i:02d}" for i in range(1, 21)]
    K12 = {f"plus{i:02d}" for i in range(11, 21)}
    BOOKS, IDEA_JOBS, CLONE_CAP, IDEA_CAP, MIN_CLONE_ACCS = 12, 160, 20, 20, 14


if __name__ == "__main__":
    unittest.main()
