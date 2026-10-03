"""TÀI KHOẢN CHẾT: trang ChatGPT hiện màn hình đăng nhập (bị đăng xuất) hoặc báo bị khoá.

Phải: nhận ra đúng (không nhầm lúc trang đang tải), THÔNG BÁO (log batch + danh sách tài khoản trên UI), BỎ hẳn tài
khoản đó khỏi batch này và các batch sau, việc đang làm chuyển sang tài khoản khác không tính lượt; đăng nhập lại
thành công thì dùng lại được. Mọi tài khoản đều chết thì batch dừng ngay, không ngồi chờ.
"""
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge import cli, layout, pipeline  # noqa: F401 - cli đặt stdout UTF-8 như lúc chạy thật
from calforge.imagegen import driver
from calforge.imagegen.driver import GenJob, NavError, run_jobs
from calforge.llm import accounts, bulk_login
from calforge.llm import pool as poolmod
from calforge.llm.pool import CHAT, DEAD_MARKER, IMAGE, AccountPool

from tests import test_batch_simulation as tb
from tests import test_forty_accounts as t40

REAL_WORKER = driver._Worker


class LoginPage:
    """Trang giả: script = danh sách trạng thái đăng nhập trả về lần lượt cho LOGIN_STATE_JS."""
    url = "https://chatgpt.com/"

    def __init__(self, states, body="Log in\nSign up\nGet started"):
        self.states, self.body, self.waited = list(states), body, 0

    def evaluate(self, js):
        if js == driver.BODY_TEXT_JS:
            return self.body
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def wait_for_timeout(self, ms):
        self.waited += ms

    def locator(self, sel):
        class L:
            def wait_for(self, **k):
                raise RuntimeError("Timeout 30000ms exceeded")
        loc = L()
        loc.first = loc
        return loc


LOGIN = {"hasLoginBtn": True, "appReady": False}
READY = {"hasLoginBtn": False, "appReady": True}
LOADING = {"hasLoginBtn": False, "appReady": False}


class DetectTest(unittest.TestCase):
    def test_login_screen_is_logged_out(self):
        p = LoginPage([LOGIN])
        self.assertEqual(driver.account_state(p)[0], "logged_out")
        self.assertEqual(p.waited, 3000)                         # xem lại sau 3 giây rồi mới kết luận

    def test_login_button_that_disappears_is_not_dead(self):
        self.assertEqual(driver.account_state(LoginPage([LOGIN, READY]))[0], "")   # trang chỉ đang tải dở

    def test_loading_or_ready_page_is_not_dead(self):
        self.assertEqual(driver.account_state(LoginPage([LOADING], body=""))[0], "")
        self.assertEqual(driver.account_state(LoginPage([READY], body="ChatGPT"))[0], "")
        both = {"hasLoginBtn": True, "appReady": True}              # có ô chat thì vẫn dùng được
        self.assertEqual(driver.account_state(LoginPage([both]))[0], "")

    def test_auth_redirect_is_logged_out(self):
        p = LoginPage([LOADING], body="Welcome back")
        p.url = "https://auth.openai.com/log-in"
        self.assertEqual(driver.account_state(p)[0], "logged_out")

    def test_banned_text_wins(self):
        p = LoginPage([LOGIN], body="Your account has been deactivated.")
        self.assertEqual(driver.account_state(p)[0], "banned")

    def test_broken_page_is_not_dead(self):
        class Boom:
            url = ""

            def evaluate(self, js):
                raise RuntimeError("Target closed")
        self.assertEqual(driver.account_state(Boom()), ("", ""))

    def test_find_raises_logged_out(self):
        with self.assertRaises(NavError) as e:
            REAL_WORKER(Path("acc1"), "hidden", 5)._find(LoginPage([LOGIN]), ["#prompt-textarea"], 3000)
        self.assertIn(driver.LOGGED_OUT, str(e.exception))
        with self.assertRaises(NavError) as e:
            REAL_WORKER(Path("acc1"), "hidden", 5)._find(LoginPage([LOADING], body=""), ["#prompt-textarea"], 3000)
        self.assertNotIn(driver.LOGGED_OUT, str(e.exception))     # chỉ là trang chưa tải xong


@contextmanager
def opener(profile):
    yield object()


class DropTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdir = Path(self.tmp.name)
        self.names = [f"acc{i}" for i in range(1, 7)]
        for n in self.names:
            (self.pdir / n).mkdir()
        self.notes = []

    def pool(self):
        return AccountPool(self.pdir, self.names, cap=6, launch_gap_s=0, notify=self.notes.append)

    def run_with_dead(self, dead, pool, n_jobs=12, max_attempts=1):
        calls, events = [], []

        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                calls.append(self.name)
                if self.name in dead:
                    raise NavError(f"{driver.LOGGED_OUT}: trang ChatGPT đòi đăng nhập lại")
                return job.out.with_suffix(".png")

        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, n_jobs + 1)]
        with mock.patch.object(driver, "_Worker", W):
            out = run_jobs(jobs, self.pdir, pool.names, max_attempts=max_attempts, on_event=events.append, pool=pool,
                           open_page=opener)
        return out, calls, events

    def test_logged_out_account_is_announced_dropped_and_job_moves_on(self):
        pool = self.pool()
        out, calls, events = self.run_with_dead({"acc1", "acc2"}, pool)
        self.assertTrue(all(j.result is not None for j in out))           # max_attempts=1: không tính lượt
        self.assertTrue(all(j.nav_errors == 0 for j in out))
        self.assertEqual(sorted(pool.dead), ["acc1", "acc2"])
        self.assertEqual(pool.dead["acc1"]["kind"], "logged_out")
        for n in ("acc1", "acc2"):
            self.assertEqual(calls.count(n), 1)                           # chết rồi không được giao việc nữa
            self.assertTrue(pool._resting(n, IMAGE) and pool._resting(n, CHAT))
            self.assertIsNone(pool.acquire(CHAT, only=n))
            self.assertEqual(sum(f"[{n}] ✘ TÀI KHOẢN CHẾT" in e and "đăng nhập lại" in e for e in events), 1)
            self.assertEqual(sum("TÀI KHOẢN CHẾT" in m and n in m for m in self.notes), 1)
            self.assertEqual(json.loads((self.pdir / n / DEAD_MARKER).read_text(encoding="utf-8"))["kind"], "logged_out")
        self.assertEqual(pool.throttle_count, 0)                          # không tính là "nhiều tài khoản cùng lỗi mạng"
        self.assertEqual(pool.use, {})
        self.assertEqual(pool.alive_names(), ["acc3", "acc4", "acc5", "acc6"])

    def test_next_batch_skips_dead_account_until_relogin(self):
        self.pool().drop("acc3", "logged_out", "trang ChatGPT hiện màn hình đăng nhập")   # batch trước phát hiện
        pool2 = self.pool()                                               # batch sau (tiến trình mới): đọc dấu trong profile
        self.assertEqual(list(pool2.dead), ["acc3"])
        out, calls, _ = self.run_with_dead({"acc3"}, pool2)
        self.assertNotIn("acc3", calls)                                   # không mở Chrome tài khoản chết nữa
        self.assertTrue(all(j.result is not None for j in out))
        bulk_login.mark_logged_in(self.pdir / "acc3", "a@b.c")           # người dùng đăng nhập lại thành công
        self.assertFalse((self.pdir / "acc3" / DEAD_MARKER).exists())
        self.assertEqual(self.pool().dead, {})

    def test_account_list_for_ui_shows_dead(self):
        for n in self.names:
            bulk_login.mark_logged_in(self.pdir / n, f"{n}@x.y")
        pool = self.pool()
        pool.drop("acc2", "logged_out", "màn hình đăng nhập")
        pool.drop("acc5", "banned", "Your account has been deactivated")
        cfg = {"profiles_dir": str(self.pdir), "projects_dir": str(self.pdir)}
        rows = {a["name"]: a for a in accounts.list_accounts(cfg)}
        self.assertEqual(rows["acc2"]["dead"]["kind"], "logged_out")
        self.assertIn("đăng nhập lại", rows["acc2"]["dead"]["label"])
        self.assertIn("thay tài khoản", rows["acc5"]["dead"]["label"])
        self.assertFalse(rows["acc2"]["has_session"] or rows["acc5"]["has_session"])   # không còn tính là "sẵn sàng"
        self.assertTrue(rows["acc1"]["has_session"] and rows["acc1"]["dead"] is None)
        self.assertEqual(sorted(pool.snapshot()["dead"]), ["acc2", "acc5"])

    def test_all_accounts_dead_ends_at_once(self):
        pool = self.pool()
        t0 = time.monotonic()
        out, calls, _ = self.run_with_dead(set(self.names), pool, n_jobs=5, max_attempts=3)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(len(calls), 6)                                   # mỗi tài khoản đúng 1 lần
        self.assertTrue(all(j.result is None and j.error == "hết tài khoản còn lượt" for j in out))
        logs, slept = [], []
        with mock.patch.object(poolmod, "peek_pool", lambda: pool), mock.patch.object(pipeline.time, "sleep", slept.append):
            got = pipeline._wait_for_quota({"quota_wait_s": 1800}, 0.0, logs.append, "gen ảnh")
        self.assertEqual((got, slept), (0.0, []))                         # không ngồi chờ 30 phút vô ích
        self.assertTrue(any("MỌI TÀI KHOẢN ĐỀU CHẾT" in l for l in logs))


class DeadAccountsBatchTest(unittest.TestCase):
    def worker(self, s, dead, hits):
        base = driver._Worker

        class W(base):
            def run_job(self, page, job):
                if self.name in dead:
                    hits.append(self.name)
                    raise NavError(f"{driver.LOGGED_OUT}: trang ChatGPT đòi đăng nhập lại")
                return super().run_job(page, job)
        return mock.patch.object(driver, "_Worker", W)

    def test_batch_with_logged_out_accounts_then_second_batch(self):
        s = t40.sim(self, 800, fault=0.5)
        dead = {"acc2", "acc7", "acc13", "acc21", "acc34", "acc40"}
        hits = []
        with self.worker(s, dead, hits):
            tb.run_until_done(self, s, "dead", 8, "wall_grid", "ai_page")
            self.assertEqual(len(s.books("dead")), 8)
            found = set(s.pool.dead)
            self.assertTrue(found and found <= dead)
            for n in found:
                self.assertEqual(hits.count(n), 1)
                self.assertTrue((Path(s.cfg["profiles_dir"]) / n / DEAD_MARKER).exists())
            n_hits = len(hits)
            tb.run_until_done(self, s, "dead2", 4, "wall_grid", "background")   # batch kế trong hàng đợi
            self.assertTrue(all(hits.count(n) == 1 for n in found))             # tài khoản đã chết không bị gọi lại
            self.assertLessEqual(len(hits) - n_hits, len(dead - found))
        tb.check_invariants(self, s)

    def test_every_account_dead_stops_batch_without_hanging(self):
        s = t40.sim(self, 810, n=8, cap=8, fault=0)
        s.cfg.update(quota_wait_s=30, quota_max_wait_h=24)                      # nếu ngồi chờ thì test sẽ treo
        hits = []
        t0 = time.monotonic()
        with self.worker(s, set(s.pool.names), hits):
            rows = s.run("alldead", 2, "wall_grid", "background", timeout=60)
        self.assertLess(time.monotonic() - t0, 45)
        self.assertEqual(sum(r["ok"] for r in rows), 0)
        self.assertTrue(all(r.get("reason") for r in rows))
        self.assertEqual(len(s.pool.dead), 8)
        tb.check_invariants(self, s)


if __name__ == "__main__":
    unittest.main()
