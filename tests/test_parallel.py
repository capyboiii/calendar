"""Batch song song: bộ điều phối tài khoản + vẽ nhiều cuốn cùng lúc + chat tranh tài khoản với vẽ.

Giả lập áp lực: nhiều luồng, tài khoản ngẫu nhiên hết lượt, Chrome sập, ảnh bị loại, bị từ chối. Điều kiện bắt
buộc: KHÔNG BAO GIỜ 2 việc cùng dùng một tài khoản, không vượt trần Chrome, mọi việc đều kết thúc (không treo)."""
import random
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge.imagegen import driver
from calforge.imagegen.driver import GenJob, QuotaExceeded, Refused, TempError, run_jobs
from calforge.llm.pool import CHAT, IMAGE, AccountPool, browser_cap

REAL_WORKER = driver._Worker


class Tracker:
    """Ghi ai đang dùng tài khoản nào; phát hiện dùng chung / vượt trần."""

    def __init__(self, cap):
        self.cap, self.active, self.peak = cap, set(), 0
        self.lock = threading.Lock()
        self.violations = []

    @contextmanager
    def use(self, name):
        with self.lock:
            if name in self.active:
                self.violations.append(f"{name} bị dùng chung")
            self.active.add(name)
            self.peak = max(self.peak, len(self.active))
            if len(self.active) > self.cap:
                self.violations.append(f"vượt trần: {len(self.active)} > {self.cap}")
        try:
            yield
        finally:
            with self.lock:
                self.active.discard(name)


def make_pool(n=10, cap=6, gap=0.0):
    names = [f"acc{i}" for i in range(1, n + 1)]
    return AccountPool(Path("."), names, cap=cap, launch_gap_s=gap)


class PoolTest(unittest.TestCase):
    def test_cap_from_ram(self):
        self.assertEqual(browser_cap(15, free_gb=7.0), 6)       # ~1 Chrome / 1.1 GB
        self.assertEqual(browser_cap(15, free_gb=40.0), 15)      # trần cấu hình
        self.assertEqual(browser_cap(15, free_gb=0.5), 1)

    def test_rest_is_per_role_and_reserve_leaves_room_for_chat(self):
        pool = make_pool(n=3, cap=3)
        a = pool.acquire(IMAGE)
        pool.rest(a, IMAGE, 100)
        pool.release(a)
        self.assertEqual(pool.acquire(CHAT, only=a), a)         # hết lượt vẽ vẫn đi chat được
        pool.release(a)
        with pool.reserve_chat(1):
            got = [pool.acquire(IMAGE) for _ in range(3)]
            self.assertEqual(sum(g is not None for g in got), 2)  # chừa 1 chỗ cho chat
            self.assertIsNotNone(pool.acquire(CHAT))

    def test_image_worker_yields_to_waiting_chat(self):
        pool = make_pool(n=2, cap=4)                              # ít tài khoản hơn trần
        a, b = pool.acquire(IMAGE), pool.acquire(IMAGE)
        self.assertFalse(pool.should_yield(a))
        with pool.reserve_chat(1):
            self.assertTrue(pool.should_yield(a) or pool.should_yield(b))

    def test_launch_gate_spacing(self):
        t = {"now": 0.0}
        slept = []
        pool = AccountPool(Path("."), ["a"], cap=1, launch_gap_s=5, clock=lambda: t["now"],
                           sleep=lambda s: (slept.append(s), t.__setitem__("now", t["now"] + s)))
        for _ in range(3):
            with pool.launch_gate():
                pass
        self.assertEqual(slept, [5, 5])                           # mở Chrome cách nhau 5 giây


class FakeWorker:
    """Thay _Worker: chạy job ngẫu nhiên xong / QC loại / hết lượt / bị từ chối / lỗi lạ."""
    tracker: Tracker = None
    rng = random.Random(7)
    quota_left: dict = {}
    lock = threading.Lock()

    def __init__(self, profile_dir, headless, timeout_s, settle_s=8.0):
        self.name = Path(profile_dir).name

    def run_job(self, page, job):
        with FakeWorker.tracker.use(self.name):
            time.sleep(FakeWorker.rng.uniform(0.001, 0.01))
            with FakeWorker.lock:
                left = FakeWorker.quota_left.get(self.name, 10 ** 9)
                FakeWorker.quota_left[self.name] = left - 1
                r = FakeWorker.rng.random()
            if left <= 0:
                raise QuotaExceeded("limit reached")
            if r < .08:
                raise TempError("ảnh không đạt: lịch sai")
            if r < .10:
                raise Refused("policy")
            if r < .13:
                raise RuntimeError("Target page crashed")
            out = job.out.with_suffix(".png")
            return out


@contextmanager
def fake_open(profile):
    if profile == "acc9":                                         # một tài khoản không mở được Chrome
        raise RuntimeError("profile locked")
    yield object()


class RunJobsStressTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(driver, "_Worker", FakeWorker)
        self.p.start()
        self.addCleanup(self.p.stop)

    def _jobs(self, book, n):
        return [GenJob(f"{book}-{i}", "prompt", Path(f"{book}-{i}")) for i in range(n)]

    def test_many_books_and_chat_share_accounts_safely(self):
        pool = make_pool(n=10, cap=6)
        FakeWorker.tracker = Tracker(cap=6)
        FakeWorker.quota_left = {"acc2": 3, "acc5": 8}             # 2 tài khoản hết lượt vẽ giữa chừng
        results = {}

        def book(i):
            jobs = self._jobs(f"b{i}", 26)
            results[i] = run_jobs(jobs, Path("."), [f"acc{k}" for k in range(1, 11)], max_attempts=3,
                                  on_event=lambda *_: None, pool=pool, open_page=fake_open)

        chat_done = []

        def chatter():                                            # luồng lên ý tưởng liên tục cần 1 tài khoản
            with pool.reserve_chat(1):
                for _ in range(15):
                    name = None
                    deadline = time.monotonic() + 20
                    while name is None and time.monotonic() < deadline:
                        name = pool.acquire(CHAT)
                        if name is None:
                            pool.wait_change(0.05)
                    self.assertIsNotNone(name, "chat bị đói tài khoản")
                    with FakeWorker.tracker.use(name):
                        time.sleep(0.005)
                    pool.release(name)
                    chat_done.append(name)

        threads = [threading.Thread(target=book, args=(i,)) for i in range(4)] + [threading.Thread(target=chatter)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
            self.assertFalse(t.is_alive(), "có luồng bị treo")
        self.assertEqual(FakeWorker.tracker.violations, [])
        self.assertEqual(len(chat_done), 15)
        for jobs in results.values():                             # mọi việc đều kết thúc: có ảnh hoặc có lý do
            self.assertTrue(all(j.result is not None or j.error for j in jobs))
        self.assertEqual(pool.use, {})                            # trả hết tài khoản
        for acc in ("acc2", "acc5"):                              # tài khoản nào đã chạm hết lượt thì phải đang nghỉ vẽ
            if FakeWorker.quota_left.get(acc, 0) < 0:                 # (được giao ít việc thì có thể chưa chạm - tuỳ nhịp)
                self.assertTrue(pool._resting(acc, IMAGE), acc)
        self.assertFalse(pool._resting("acc2", CHAT))

    def test_all_accounts_out_of_quota_returns_promptly(self):
        pool = make_pool(n=3, cap=3)
        FakeWorker.tracker = Tracker(cap=3)
        FakeWorker.quota_left = {"acc1": 0, "acc2": 0, "acc3": 0}
        t0 = time.monotonic()
        jobs = run_jobs(self._jobs("b", 5), Path("."), ["acc1", "acc2", "acc3"], on_event=lambda *_: None,
                        pool=pool, open_page=fake_open)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertTrue(all(j.error == "hết tài khoản còn lượt" for j in jobs))   # batch sẽ chờ rồi thử lại
        self.assertTrue(all(j.attempts == 0 for j in jobs))                         # hết lượt không tính lần thử

    def test_third_party_refusal_cancels_queued_jobs_for_book(self):
        calls = []

        class IPWorker:
            def __init__(self, *a, **k):
                pass

            def run_job(self, page, job):
                calls.append(job.id)
                raise driver.ThirdPartyIPRefused("third-party intellectual property rights")

        pool = make_pool(n=1, cap=1)
        jobs = self._jobs("tm", 4)
        with mock.patch.object(driver, "_Worker", IPWorker):
            result = run_jobs(jobs, Path("."), ["acc1"], max_attempts=3, on_event=lambda *_: None,
                              pool=pool, open_page=fake_open)
        self.assertEqual(calls, ["tm-0"] * 3)                      # gửi lại đúng prompt đó 2 lần nữa rồi mới bỏ cuốn
        self.assertTrue(all((j.error or "").startswith("IP/TM_REJECTED:") for j in result))

    def test_ip_text_interrupts_wait_even_while_ui_is_busy(self):
        refusal = ("Rất tiếc, nhưng hình ảnh chúng ta tạo ra có thể vi phạm các quy định của chúng tôi về "
                   "sự tương đồng với nội dung của bên thứ ba.")
        state = {"assistant": 0, "user": 1, "busy": True, "pending": True,
                 "imgs": [], "pageImgs": [], "tail": refusal}

        class Page:
            def wait_for_timeout(self, _ms):
                raise AssertionError("IP refusal must be raised before waiting")

        worker = REAL_WORKER(Path("."), False, timeout_s=420)
        before = {"assistant": 0, "user": 0, "imgs": [], "pageImgs": []}
        with mock.patch.object(driver, "_eval", return_value=state):
            with self.assertRaises(driver.ThirdPartyIPRefused):
                worker._wait_image(Page(), before)


if __name__ == "__main__":
    unittest.main()


class FakePage:
    """Trang giả: mỗi lần goto lấy một kịch bản trong `script` ("ok" | "redirect" | "neterr" | "boom")."""

    def __init__(self, script):
        self.script, self.url, self.gotos = list(script), "about:blank", 0

    def goto(self, url, **kw):
        self.gotos += 1
        step = self.script.pop(0) if self.script else "ok"
        if step == "redirect":
            self.url = "https://chatgpt.com/"
            raise RuntimeError('Page.goto: Navigation to "https://chatgpt.com/" is interrupted by another '
                               'navigation to "https://chatgpt.com/"')
        if step == "neterr":
            self.url = "chrome-error://chromewebdata/"
            return
        if step == "boom":
            raise RuntimeError("something unrelated")
        self.url = url

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass


class OpenHomeTest(unittest.TestCase):
    def test_redirect_to_chatgpt_is_fine(self):
        p = FakePage(["redirect"])
        driver.open_home(p, "https://chatgpt.com/")
        self.assertEqual(p.gotos, 1)

    def test_network_error_page_retried(self):
        p = FakePage(["neterr", "neterr", "ok"])
        driver.open_home(p, "https://chatgpt.com/")
        self.assertEqual(p.gotos, 3)

    def test_persistent_network_error_raises_nav_error(self):
        with self.assertRaises(driver.NavError):
            driver.open_home(FakePage(["neterr"] * 10), "https://chatgpt.com/")

    def test_unrelated_error_is_not_swallowed(self):
        with self.assertRaises(RuntimeError) as err:
            driver.open_home(FakePage(["boom"]), "https://chatgpt.com/")
        self.assertNotIsInstance(err.exception, driver.NavError)


class NavErrorRunJobsTest(unittest.TestCase):
    def test_nav_errors_do_not_burn_attempts_and_move_to_other_accounts(self):
        class NavWorker:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                if self.name == "acc1":                       # acc1 mạng hỏng liên tục
                    raise driver.NavError("không mở được ChatGPT: chrome-error")
                return job.out.with_suffix(".png")

        pool = make_pool(n=3, cap=3)
        with mock.patch.object(driver, "_Worker", NavWorker):
            jobs = run_jobs([GenJob(f"j{i}", "p", Path(f"j{i}")) for i in range(9)], Path("."),
                            ["acc1", "acc2", "acc3"], max_attempts=1, on_event=lambda *_: None,
                            pool=pool, open_page=fake_open)
        self.assertTrue(all(j.result is not None for j in jobs))          # max_attempts=1 mà vẫn xong hết
        self.assertTrue(pool._resting("acc1", IMAGE))
        self.assertFalse(pool._resting("acc1", CHAT))


class PageNotReadyTest(unittest.TestCase):
    class Page:
        def __init__(self, login_btn):
            self.login_btn, self.url = login_btn, "https://chatgpt.com/"

        def locator(self, sel):
            class L:
                first = None

                def wait_for(self, **k):
                    raise RuntimeError("Timeout 30000ms exceeded")
            loc = L()
            loc.first = loc
            return loc

        def evaluate(self, js):
            return {"hasLoginBtn": self.login_btn, "appReady": False}

    def test_missing_prompt_box_is_a_page_error_not_a_bad_image(self):
        w = driver._Worker(Path("acc1"), "hidden", 5)
        with self.assertRaises(driver.NavError) as e:
            w._find(self.Page(False), ["#prompt-textarea"], 3000)
        self.assertNotIn(driver.LOGGED_OUT, str(e.exception))
        with self.assertRaises(driver.NavError) as e:
            w._find(self.Page(True), ["#prompt-textarea"], 3000)
        self.assertIn(driver.LOGGED_OUT, str(e.exception))           # bị đăng xuất: báo rõ, nghỉ lâu

    def test_endless_page_errors_eventually_count_and_finish(self):
        class Broken:
            def __init__(self, *a, **k):
                pass

            def run_job(self, page, job):
                raise driver.NavError("không thấy ô chat")

        pool = make_pool(n=3, cap=3)
        pool.rest_s = 0
        with mock.patch.object(driver, "_Worker", Broken), mock.patch.object(driver, "NAV_REST_S", 0):
            t0 = time.monotonic()
            [job] = run_jobs([GenJob("g01", "p", Path("g01"))], Path("."), ["acc1", "acc2", "acc3"],
                             max_attempts=2, on_event=lambda *_: None, pool=pool, open_page=fake_open)
        self.assertLess(time.monotonic() - t0, 20)                 # không lặp vô tận
        self.assertIn("lỗi trang ChatGPT lặp lại", job.error)
