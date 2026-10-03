"""40 CHROME CÙNG LÚC: phân luồng tự tính, trần co giãn (RAM, nhiều tài khoản cùng lỗi), tài khoản bị khoá.

Phần 1 - bộ điều phối với đồng hồ giả: RAM tụt thì không mở thêm / bớt Chrome, hồi thì mở lại; nhiều tài khoản khác
nhau cùng lỗi thì giảm một nửa rồi tăng dần; tài khoản bị khoá nghỉ hẳn.
Phần 2 - giả lập batch (code batch THẬT, ChatGPT/Chrome giả) với 40 và 80 tài khoản, trần 40, luồng tự tính:
lỗi ngẫu nhiên, bão lỗi trang, RAM tụt giữa chừng, tài khoản bị khoá, nửa số tài khoản hỏng, hết lượt toàn bộ.
"""
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge import cli, layout, pipeline  # noqa: F401 - cli đặt stdout UTF-8 như lúc chạy thật
from calforge.ideation import tones
from calforge.imagegen import driver
from calforge.imagegen.driver import GenJob, NavError, QuotaExceeded, run_jobs
from calforge.llm import pool as poolmod
from calforge.llm.limits import is_banned
from calforge.llm.pool import CHAT, IMAGE, AccountPool, auto_parallel, browser_cap

from tests import test_batch_simulation as tb

REAL_WORKER = driver._Worker


def names(n):
    return [f"acc{i}" for i in range(1, n + 1)]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def pool40(n=40, cap=40, ram=None, clock=None):
    notes = []
    p = AccountPool(Path("."), names(n), cap=cap, launch_gap_s=0, clock=clock or time.monotonic,
                    free_ram=ram, notify=notes.append)
    p.notes = notes
    return p


class AutoParallelTest(unittest.TestCase):
    def test_threads_scale_with_browsers(self):
        self.assertEqual(auto_parallel({}, 6), {"book_workers": 3, "idea_lookahead": 3, "p2_parallel": 3,
                                                "finish_workers": 1})
        self.assertEqual(auto_parallel({}, 15)["book_workers"], 3)
        self.assertEqual(auto_parallel({}, 24)["book_workers"], 3)
        self.assertEqual(auto_parallel({}, 40), {"book_workers": 5, "idea_lookahead": 5, "p2_parallel": 4,
                                                 "finish_workers": 2})
        self.assertEqual(auto_parallel({}, 80)["book_workers"], 8)             # không mở quá 8 cuốn dở cùng lúc
        self.assertEqual(auto_parallel({}, 80)["p2_parallel"], 5)

    def test_explicit_config_wins(self):
        got = auto_parallel({"book_workers": 2, "p2_parallel": 1, "finish_workers": 1, "idea_lookahead": None}, 40)
        self.assertEqual(got, {"book_workers": 2, "idea_lookahead": 2, "p2_parallel": 1, "finish_workers": 1})

    def test_default_cap_is_40_and_follows_ram(self):
        self.assertEqual(browser_cap(free_gb=64), 40)
        self.assertEqual(browser_cap(free_gb=22), 20)
        self.assertEqual(browser_cap(free_gb=7), 6)
        from calforge import config
        self.assertEqual(config.DEFAULTS["max_browsers"], 40)

    def test_planned_cap_counts_profiles(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for n in names(12) + [".cache"]:
                (Path(tmp) / n).mkdir()
            with mock.patch.object(poolmod, "free_ram_gb", lambda: 64.0):
                self.assertEqual(poolmod.planned_cap({"profiles_dir": tmp}), 12)   # ít tài khoản hơn trần
                self.assertEqual(poolmod.planned_cap({"profiles_dir": tmp, "max_browsers": 5}), 5)


class ElasticLimitTest(unittest.TestCase):
    def take(self, pool, n, role=IMAGE):
        got = []
        for _ in range(n):
            name = pool.acquire(role)
            if name is None:
                break
            got.append(name)
        return got

    def test_40_browsers_open_when_ram_is_fine(self):
        p = pool40(ram=lambda: 30.0)
        self.assertEqual(len(self.take(p, 60)), 40)
        self.assertEqual(p.limit(), 40)

    def test_low_ram_stops_opening_then_sheds_then_recovers(self):
        clock, ram = Clock(), {"gb": 30.0}
        p = pool40(ram=lambda: ram["gb"], clock=clock)
        held = self.take(p, 20)
        ram["gb"] = 1.2                                             # dưới 1.5 GB: không mở thêm
        clock.t += 20
        self.assertEqual(self.take(p, 5), [])
        self.assertEqual(p.limit(), 20)
        self.assertFalse(p.should_yield(held[0]))
        ram["gb"] = 0.5                                             # dưới 0.8 GB: bớt 1/4 số Chrome
        clock.t += 20
        self.assertEqual(p.limit(), 15)
        self.assertTrue(p.should_yield(held[0]))                    # luồng vẽ nhường sau ảnh đang vẽ
        for n in held[:5]:
            p.release(n)
        self.assertFalse(p.should_yield(held[10]))
        self.assertEqual(self.take(p, 3), [])
        ram["gb"] = 12.0                                            # RAM hồi: mở lại đủ trần
        clock.t += 20
        self.assertEqual(p.limit(), 40)
        self.assertEqual(len(self.take(p, 99)), 25)
        self.assertEqual(len(p.notes), 3, p.notes)                  # mỗi lần đổi trạng thái báo đúng 1 dòng

    def test_ram_never_shrinks_below_two(self):
        clock = Clock()
        p = pool40(ram=lambda: 0.1, clock=clock)
        self.assertEqual(p.limit(), 2)                              # vẫn còn 1 chat + 1 vẽ, batch không chết đứng
        with p.reserve_chat(1):
            self.assertIsNotNone(p.acquire(IMAGE))
            self.assertIsNone(p.acquire(IMAGE))
            self.assertIsNotNone(p.acquire(CHAT))

    def test_ram_probe_failure_is_harmless(self):
        def boom():
            raise OSError("no ram api")
        self.assertEqual(pool40(ram=boom).limit(), 40)

    def test_many_accounts_in_trouble_halve_then_grow_back(self):
        clock = Clock()
        p = pool40(clock=clock)
        held = self.take(p, 30)
        for n in names(11):
            p.trouble(n, "lỗi trang")
        self.assertEqual(p.limit(), 40)                             # 11 < 30% của 40: chưa giảm
        p.trouble("acc12", "lỗi trang")
        self.assertEqual((p.limit(), p.throttle_count), (20, 1))    # 12 tài khoản khác nhau: giảm một nửa
        self.assertTrue(p.should_yield(held[0]))
        self.assertIsNone(p.acquire(IMAGE))
        for n in names(6):                                          # vẫn lỗi tiếp ở mức 20: giảm nữa
            p.trouble(n, "429")
        self.assertEqual(p.limit(), 10)
        clock.t += 301
        self.assertEqual(p.limit(), 20)                             # yên ổn 5 phút: tăng gấp đôi
        clock.t += 301
        self.assertEqual(p.limit(), 40)                             # rồi về đủ trần
        self.assertTrue(any("giảm còn 20" in n for n in p.notes) and any("đủ 40" in n for n in p.notes), p.notes)

    def test_one_flaky_account_never_throttles(self):
        p = pool40()
        for _ in range(100):
            p.trouble("acc7", "lỗi trang")
        self.assertEqual((p.limit(), p.throttle_count), (40, 0))

    def test_old_trouble_expires(self):
        clock = Clock()
        p = pool40(clock=clock)
        for n in names(11):
            p.trouble(n)
        clock.t += 181                                              # quá 3 phút: lỗi cũ không cộng dồn
        for n in names(40)[20:30]:
            p.trouble(n)
        self.assertEqual(p.limit(), 40)

    def test_small_pool_is_not_throttled_below_floor(self):
        p = pool40(n=3, cap=3)
        for n in names(3) * 3:
            p.trouble(n)
        self.assertEqual(p.limit(), 3)                              # < 4 tài khoản khác nhau: không giảm

    def test_banned_account_rests_for_both_roles(self):
        p = pool40()
        p.ban("acc5", "Your account has been deactivated")
        p.ban("acc5", "again")
        self.assertTrue(p._resting("acc5", IMAGE) and p._resting("acc5", CHAT))
        self.assertIsNone(p.acquire(IMAGE, only="acc5"))
        self.assertEqual(list(p.snapshot()["banned"]), ["acc5"])
        self.assertEqual(sum("TÀI KHOẢN CHẾT" in n for n in p.notes), 1)   # báo một lần


class BannedDetectTest(unittest.TestCase):
    def test_messages(self):
        for text in ("Your account has been deactivated. Please contact support.",
                     "Account deactivated. If you believe this is an error...",
                     "Tài khoản của bạn đã bị vô hiệu hóa.", "TAI KHOAN CUA BAN DA BI DINH CHI",
                     "You do not have an account because it has been deleted or deactivated."):
            self.assertTrue(is_banned(text), text)
        for text in ("Log in to your account", "Create an account", "Something went wrong", ""):
            self.assertFalse(is_banned(text), text)

    def test_find_reports_banned_account(self):
        class Page:
            url = "https://chatgpt.com/"

            def locator(self, sel):
                class L:
                    def wait_for(self, **k):
                        raise RuntimeError("Timeout")
                loc = L()
                loc.first = loc
                return loc

            def evaluate(self, js):
                if js == driver.BODY_TEXT_JS:
                    return "Your account has been deactivated.\nHelp center"
                return {"hasLoginBtn": True}

        with self.assertRaises(NavError) as e:
            REAL_WORKER(Path("acc1"), "hidden", 5)._find(Page(), ["#prompt-textarea"], 3000)
        self.assertIn(driver.BANNED, str(e.exception))

    def test_run_jobs_drops_banned_account_and_finishes_elsewhere(self):
        calls = []

        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                calls.append(self.name)
                if self.name in ("acc1", "acc2"):
                    raise NavError(f"{driver.BANNED}: Your account has been deactivated")
                return job.out.with_suffix(".png")

        @contextmanager
        def opener(profile):
            yield object()

        p = pool40(n=5, cap=5)
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 13)]
        with mock.patch.object(driver, "_Worker", W):
            out = run_jobs(jobs, Path("."), p.names, max_attempts=1, on_event=lambda *_: None, pool=p,
                           open_page=opener)
        self.assertTrue(all(j.result is not None for j in out))     # max_attempts=1: bị khoá không tính lượt
        self.assertTrue(all(j.nav_errors == 0 for j in out))
        self.assertEqual(sorted(p.banned), ["acc1", "acc2"])
        self.assertLessEqual(calls.count("acc1"), 1)                # không quay lại tài khoản bị khoá
        self.assertEqual(p.use, {})

    def test_rate_limited_quota_counts_as_trouble_but_plan_limit_does_not(self):
        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                raise QuotaExceeded(self.text)

        @contextmanager
        def opener(profile):
            yield object()

        for text, throttled in (("HTTP 429 too many requests", True), ("You've hit the plus plan limit", False)):
            W.text = text
            p = pool40(n=12, cap=12)
            jobs = [GenJob(f"j{i}", "p", Path(f"j{i}")) for i in range(12)]
            with mock.patch.object(driver, "_Worker", W):
                run_jobs(jobs, Path("."), p.names, on_event=lambda *_: None, pool=p, open_page=opener)
            self.assertEqual(p.throttle_count > 0, throttled, text)
            self.assertTrue(all(j.attempts == 0 for j in jobs))


class QuotaWaitTest(unittest.TestCase):
    def test_short_rest_means_short_wait(self):
        """Mọi tài khoản nghỉ 2 phút vì lỗi trang: batch chờ ~2 phút, không chờ đủ 30 phút."""
        clock = Clock()
        p = pool40(n=3, cap=3, clock=clock)
        for n in p.names:
            p.rest(n, IMAGE, 120, "lỗi trang")
        slept, logs = [], []
        with mock.patch.object(poolmod, "peek_pool", lambda: p), mock.patch.object(pipeline.time, "sleep", slept.append):
            got = pipeline._wait_for_quota({"quota_wait_s": 1800}, 0.0, logs.append, "gen ảnh")
        self.assertEqual(slept, [122.0])
        self.assertEqual(got, 122.0)

    def test_long_rest_keeps_configured_wait_and_gives_up_after_max(self):
        clock = Clock()
        p = pool40(n=3, cap=3, clock=clock)
        for n in p.names:
            p.rest(n, IMAGE, 7200, "hết lượt")
        slept = []
        with mock.patch.object(poolmod, "peek_pool", lambda: p), mock.patch.object(pipeline.time, "sleep", slept.append):
            self.assertEqual(pipeline._wait_for_quota({"quota_wait_s": 1800}, 0.0, lambda *_: None, "gen ảnh"), 1800)
            self.assertEqual(pipeline._wait_for_quota({"quota_wait_s": 1800, "quota_max_wait_h": 1}, 3000.0,
                                                      lambda *_: None, "chat"), 0.0)
        self.assertEqual(slept, [1800])


# ------------------------------------------------------------------ giả lập batch 40 / 80 tài khoản
def sim(tc, seed, n=40, cap=40, auto=True, **kw):
    p = mock.patch.object(tb, "N_ACC", n)
    p.start()
    tc.addCleanup(p.stop)
    s = tb.Sim(tc, seed, cap=cap, **kw)
    tc.assertEqual(len(s.pool.names), n)
    if auto:                                                        # để tool TỰ TÍNH số luồng theo số Chrome
        for k in ("book_workers", "idea_lookahead", "p2_parallel"):
            s.cfg[k] = None
    return s


class FortyAccountsBatchTest(unittest.TestCase):
    def setUp(self):
        self.before = threading.active_count()

    def finish(self, s, cap=40):
        tb.check_invariants(self, s)
        self.assertLessEqual(s.world.tracker.peak, cap)
        deadline = time.monotonic() + 10
        while threading.active_count() > self.before + 2 and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertLessEqual(threading.active_count(), self.before + 2, "còn luồng chưa kết thúc")

    def test_auto_threads_are_used(self):
        s = sim(self, 700)
        self.assertEqual(pipeline._parallel(s.cfg), {"book_workers": 5, "idea_lookahead": 5, "p2_parallel": 4,
                                                     "finish_workers": 2})

    def test_queue_of_topics_with_faults(self):
        """40 tài khoản, trần 40, luồng tự tính: 3 chủ đề, 22 cuốn, lỗi ngẫu nhiên, tài khoản hết lượt / hỏng."""
        for seed in range(2):
            with self.subTest(seed=seed):
                s = sim(self, 710 + seed, chat_budget={"acc3": 2, "acc17": 4, "acc28": 0},
                        image_budget={"acc2": 4, "acc11": 10, "acc22": 0, "acc35": 6}, broken={"acc15", "acc39"})
                for kw, n, prod, mode in [("chickens", 10, "wall_grid", "ai_page"), ("bible", 4, "wall_premade", None),
                                          ("cats", 8, "wall_grid", "background")]:
                    tb.run_until_done(self, s, kw, n, prod, mode)
                    books = s.books(kw, prod)
                    self.assertEqual(len(books), n)
                    self.assertEqual(len({layout.book_angle_id(b) for b in books}), n)
                self.finish(s)
                self.assertGreaterEqual(s.world.tracker.peak, 12)       # chạy song song nhiều tài khoản (đỉnh tuỳ nhịp máy)
                counts = tb.assigned_tones(s)
                full = [counts.get(t, 0) for t in tones.BASE_TONES]
                self.assertLessEqual(max(full) - min(full), 1, counts)

    def test_storm_of_page_errors_throttles_and_batch_still_finishes(self):
        """Bão lỗi trang (mạng chập / bị chặn): trần tự giảm, hết bão tự tăng lại, batch vẫn đủ cuốn."""
        s = sim(self, 730, fault=0)
        base, state, lock = driver._Worker, {"n": 0}, threading.Lock()

        class Storm(base):
            def run_job(self, page, job):
                with lock:
                    state["n"] += 1
                    hit = 20 <= state["n"] < 110                         # 90 lượt liên tiếp đều lỗi trang
                if hit:
                    raise NavError("không mở được ChatGPT: net::ERR_CONNECTION_RESET")
                return super().run_job(page, job)

        with mock.patch.object(driver, "_Worker", Storm), mock.patch.object(driver, "NAV_REST_S", 0.2):
            tb.run_until_done(self, s, "storm", 6, "wall_grid", "ai_page")
        self.assertEqual(len(s.books("storm")), 6)
        self.assertGreater(s.pool.throttle_count, 0)                     # đã tự giảm tải
        deadline = time.monotonic() + 10                                 # tăng gấp đôi từng nấc: 2-4-8-16-32-40
        while s.pool.limit() < 40 and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(s.pool.limit(), 40)                             # và tự về lại đủ trần
        self.finish(s)

    def test_ram_drops_mid_batch(self):
        """RAM tụt giữa batch: không mở thêm / bớt Chrome, RAM hồi thì chạy lại; không treo, không hỏng cuốn."""
        s = sim(self, 740, fault=0.5)
        t0 = time.monotonic()

        def ram():
            dt = time.monotonic() - t0
            return 0.5 if 0.3 < dt < 1.5 else (1.2 if dt < 2.2 else 16.0)
        s.pool._free_ram = ram
        with mock.patch.object(poolmod, "RAM_CHECK_S", 0.05):
            tb.run_until_done(self, s, "ram", 8, "wall_grid", "ai_page")
        self.assertEqual(len(s.books("ram")), 8)
        self.finish(s)

    def test_ram_stays_low_whole_batch(self):
        s = sim(self, 745, fault=0)
        s.pool._free_ram = lambda: 0.3                                    # máy cạn RAM suốt: còn 2 Chrome vẫn xong
        with mock.patch.object(poolmod, "RAM_CHECK_S", 0.05):
            rows = s.run("lowram", 3, "wall_grid", "background")
        self.assertEqual(sum(r["ok"] for r in rows), 3)
        self.assertLessEqual(s.world.tracker.peak, 3)
        self.finish(s)

    def test_banned_accounts_are_dropped(self):
        s = sim(self, 750, fault=0)
        base = driver._Worker
        dead = {"acc4", "acc9", "acc21", "acc33", "acc40"}
        hits = []

        class Ban(base):
            def run_job(self, page, job):
                if self.name in dead:
                    hits.append(self.name)
                    raise NavError(f"{driver.BANNED}: Your account has been deactivated")
                return super().run_job(page, job)

        with mock.patch.object(driver, "_Worker", Ban):
            rows = s.run("ban", 6, "wall_grid", "ai_page")
        self.assertEqual(sum(r["ok"] for r in rows), 6)
        self.assertTrue(set(s.pool.banned) <= dead and s.pool.banned)
        for n in s.pool.banned:                                           # mỗi tài khoản bị khoá chỉ thử đúng 1 lần
            self.assertEqual(hits.count(n), 1)
        self.assertEqual(s.pool.throttle_count, 0)                        # bị khoá không làm giảm số Chrome
        self.finish(s)

    def test_half_of_accounts_broken(self):
        s = sim(self, 760, broken={f"acc{i}" for i in range(1, 21)})
        tb.run_until_done(self, s, "half", 6, "wall_grid", "ai_page")
        self.assertEqual(len(s.books("half")), 6)
        self.finish(s)

    def test_all_40_out_of_quota_then_recover(self):
        all_names = names(40)
        s = sim(self, 770, fault=0, chat_budget={n: 0 for n in all_names}, image_budget={n: 1 for n in all_names})
        rows = s.run("dogs", 6)
        self.assertEqual(sum(r["ok"] for r in rows), 6)
        self.finish(s)

    def test_ai_mockups_with_40_accounts(self):
        s = sim(self, 780, image_budget={"acc4": 6}, broken={"acc30"})
        reruns = 0
        for _ in range(4):
            rows = s.run("koi", 6, "wall_grid", "ai_page", resume=reruns > 0, mockup_mode="ai")
            if sum(r["ok"] for r in rows) == 6:
                break
            reruns += 1
        self.assertEqual(sum(r["ok"] for r in rows), 6)
        for b in s.books("koi"):
            self.assertEqual(sorted(p.stem for p in layout.listing(b).glob("*.jpg")),
                             ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads",
                              "04_two_wall_spreads", "06_three_books"])
        self.finish(s)

    def test_80_accounts_cap_40(self):
        """80 tài khoản nhưng chỉ 40 Chrome: 40 tài khoản còn lại thay phiên khi tài khoản khác hết lượt."""
        s = sim(self, 790, n=80, cap=40, image_budget={f"acc{i}": 3 for i in range(1, 41)})
        s.world.refill.update({f"acc{i}": 0 for i in range(1, 41)})      # 40 tài khoản đầu hết lượt hẳn
        tb.run_until_done(self, s, "big", 10, "wall_grid", "ai_page")
        self.assertEqual(len(s.books("big")), 10)
        self.finish(s)

    def test_launch_gap_with_40_accounts(self):
        s = sim(self, 795, fault=0.5)
        s.pool.launch_gap_s = 0.02
        tb.run_until_done(self, s, "gap", 6, "wall_grid", "ai_page")
        self.finish(s)


if __name__ == "__main__":
    unittest.main()
