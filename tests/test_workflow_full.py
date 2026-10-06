"""RÀ TOÀN BỘ WORKFLOW (trừ R2/CSV): từng trạng thái trang ChatGPT lúc chờ ảnh, thời gian chờ, lỗi lúc gửi,
vòng thử lại của run_jobs, cuốn bị ChatGPT từ chối (TM / khỏa thân) trong batch thật qua hàng đợi, nâng cấp cuốn
"AI gen mockup" cũ sang bộ ảnh mới.

Phần DOM dùng _Worker THẬT với trang giả + đồng hồ giả (không chờ thật): mỗi kịch bản là hàm t -> trạng thái trang.
"""
import json
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout, pipeline
from calforge.imagegen import ai_mockups, driver
from calforge.imagegen.driver import GenJob, NavError, QuotaExceeded, Refused, TempError, ThirdPartyIPRefused, run_jobs
from calforge.llm.pool import IMAGE, AccountPool
from calforge.render import mockups
from calforge.ui import server

from tests import test_ai_mockups as tam
from tests import test_batch_simulation as tb
from tests import test_recovery_simulation as tr

REAL_WORKER = driver._Worker
ADULT = ("Rất tiếc, nhưng hình ảnh chúng ta tạo ra có thể vi phạm các quy định của chúng tôi về ảnh khỏa thân, "
         "tình dục hoặc nội dung khiêu dâm. Nếu bạn cho rằng chúng tôi đã hiểu sai, vui lòng thử lại hoặc chỉnh sửa "
         "câu lệnh của bạn.")
BEFORE = {"user": 0, "assistant": 0, "imgs": [], "pageImgs": []}
IMG = {"src": "blob:new", "w": 1536, "h": 1024, "done": True}


def state(**kw):
    return {"user": 1, "assistant": 0, "busy": False, "pending": False, "imgs": [], "pageImgs": [], "tail": "", **kw}


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


class Page:
    url = "https://chatgpt.com/"

    def __init__(self, clock):
        self.clock, self.waits = clock, 0

    def wait_for_timeout(self, ms):
        self.waits += 1
        self.clock.t += ms / 1000

    def wait_for_load_state(self, *a, **k):
        pass


class DomCase(unittest.TestCase):
    def wait(self, script, timeout_s=100, settle_s=8, notice=""):
        """Chạy _wait_image thật trên trang giả; script(t) -> trạng thái trang ở giây t."""
        clock = Clock()
        page = Page(clock)
        self.clock = clock
        fake_time = types.SimpleNamespace(monotonic=clock.monotonic, sleep=lambda s: None)
        note = notice if callable(notice) else (lambda t: notice)
        with mock.patch.object(driver, "time", fake_time), \
                mock.patch.object(driver, "_eval", lambda p, js, *a: script(clock.t)), \
                mock.patch.object(driver, "page_notice", lambda p: note(clock.t)):
            return REAL_WORKER(Path("acc1"), "hidden", timeout_s, settle_s=settle_s)._wait_image(page, BEFORE)


class WaitImageDomTest(DomCase):
    def test_image_returned_only_after_it_settles(self):
        def script(t):
            if t < 20:
                return state(assistant=1, busy=True, tail="Creating image")
            return state(assistant=1, imgs=[IMG], tail="Here you go")
        self.assertEqual(self.wait(script), "blob:new")
        self.assertGreaterEqual(self.clock.t, 28)                 # ảnh hiện ở giây 20, đứng yên đủ 8 giây mới lấy

    def test_changing_image_restarts_settle(self):
        def script(t):                                            # ảnh xem trước mờ rồi mới tới ảnh thật
            src = "blob:preview" if t < 5 else "blob:final"
            return state(assistant=1, imgs=[{**IMG, "src": src}])
        self.assertEqual(self.wait(script), "blob:final")
        self.assertGreaterEqual(self.clock.t, 13)

    def test_small_or_unfinished_images_are_ignored(self):
        def script(t):
            if t < 30:
                return state(assistant=1, pending=True, imgs=[{**IMG, "w": 512, "h": 512}, {**IMG, "done": False}])
            return state(assistant=1, imgs=[IMG])
        self.assertEqual(self.wait(script), "blob:new")
        self.assertGreaterEqual(self.clock.t, 38)

    def test_image_outside_last_turn_is_still_found(self):
        old = {"src": "blob:old", "w": 1536, "h": 1024, "done": True}
        before = dict(BEFORE, pageImgs=[old])

        def script(t):                                            # giao diện không tăng số lượt trả lời
            return state(pageImgs=[old, IMG] if t > 5 else [old], busy=t <= 5)
        clock = Clock()
        fake_time = types.SimpleNamespace(monotonic=clock.monotonic)
        with mock.patch.object(driver, "time", fake_time), \
                mock.patch.object(driver, "_eval", lambda p, js, *a: script(clock.t)), \
                mock.patch.object(driver, "page_notice", lambda p: ""):
            src = REAL_WORKER(Path("acc1"), "hidden", 100)._wait_image(Page(clock), before)
        self.assertEqual(src, "blob:new")                         # không lấy nhầm ảnh cũ của trang

    def test_generating_text_keeps_waiting_instead_of_failing(self):
        def script(t):                                            # 60 giây chỉ có chữ "Adding details", không nút Stop
            if t < 60:
                return state(assistant=1, tail="Adding details")
            return state(assistant=1, imgs=[IMG])
        self.assertEqual(self.wait(script), "blob:new")

    def test_adult_refusal_drops_book_even_while_ui_busy(self):
        with self.assertRaises(ThirdPartyIPRefused) as e:
            self.wait(lambda t: state(busy=True, pending=True, tail=ADULT))
        self.assertIn("khỏa thân", str(e.exception))
        self.assertEqual(self.clock.t, 0)                         # bắt ngay, không chờ hết giờ

    def test_adult_refusal_after_turn_finished(self):
        def script(t):
            return state(assistant=1, busy=t < 10, tail="" if t < 10 else ADULT)
        with self.assertRaises(ThirdPartyIPRefused):
            self.wait(script)
        self.assertLess(self.clock.t, 15)

    def test_english_adult_refusal(self):
        text = ("Sorry, but the image we created may violate our guardrails around nudity, sexuality, or erotic "
                "content. If you think we got it wrong, please retry or edit your prompt.")
        with self.assertRaises(ThirdPartyIPRefused):
            self.wait(lambda t: state(assistant=1, tail=text))

    def test_quota_text_rests_account(self):
        with self.assertRaises(QuotaExceeded):
            self.wait(lambda t: state(assistant=1, tail="You've hit the plus plan limit for image generation."))

    def test_quota_banner_while_nothing_is_drawing(self):
        with self.assertRaises(QuotaExceeded):
            self.wait(lambda t: state(busy=True), notice=lambda t: "Too many requests. Please slow down." if t > 3 else "")

    def test_quota_banner_ignored_while_image_is_being_drawn(self):
        def script(t):
            return state(assistant=1, pending=True) if t < 20 else state(assistant=1, imgs=[IMG])
        self.assertEqual(self.wait(script, notice="rate limit"), "blob:new")

    def test_plain_policy_refusal_is_handled_like_tm(self):
        for text in ("I can't create that image because it violates our content policy.",
                     "We're so sorry, but the prompt may violate our content policies. If you think we got it "
                     "wrong, please retry or edit your prompt."):
            with self.assertRaises(ThirdPartyIPRefused, msg=text):   # gửi lại 2 lần rồi bỏ cuốn như TM
                self.wait(lambda t, text=text: state(assistant=1, tail=text))

    def test_asks_for_source_image(self):
        with self.assertRaises(driver.WantsSourceImage):
            self.wait(lambda t: state(assistant=1, tail="Please upload the image you want me to edit."))

    def test_error_text_is_temporary(self):
        with self.assertRaises(TempError) as e:
            self.wait(lambda t: state(assistant=1, tail="Something went wrong while generating."))
        self.assertNotIsInstance(e.exception, (Refused, QuotaExceeded))

    def test_server_errors_are_temporary_and_caught_at_once(self):
        from tests.test_chat_errors import SERVER_ERRORS
        for text in SERVER_ERRORS:
            with self.subTest(text=text), self.assertRaises(TempError) as e:
                self.wait(lambda t, text=text: state(assistant=1, tail=text), timeout_s=420)
            self.assertNotIsInstance(e.exception, (Refused, QuotaExceeded, ThirdPartyIPRefused))
            self.assertLess(self.clock.t, 5, text)                # nhận ngay, không chờ 45 giây im lặng

    def test_server_busy_rests_account_instead_of_burning_tries(self):
        from tests.test_chat_errors import SERVER_BUSY
        for text in SERVER_BUSY:
            with self.subTest(text=text), self.assertRaises(QuotaExceeded):
                self.wait(lambda t, text=text: state(assistant=1, tail=text))

    def test_plain_text_answer_without_image_gives_up_after_quiet_period(self):
        with self.assertRaises(TempError) as e:
            self.wait(lambda t: state(assistant=1, tail="Here is a description of the calendar."), timeout_s=420)
        self.assertIn("không có ảnh", str(e.exception))
        self.assertTrue(45 <= self.clock.t <= 50, self.clock.t)   # chờ 45 giây cho chắc rồi mới bỏ

    def test_stuck_tab_with_no_reaction(self):
        with self.assertRaises(TempError) as e:
            self.wait(lambda t: state(), timeout_s=420)
        self.assertIn("tab kẹt", str(e.exception))
        self.assertTrue(240 <= self.clock.t <= 245, self.clock.t)  # 240 giây không động tĩnh

    def test_timeout_when_busy_forever_without_drawing(self):
        with self.assertRaises(TempError) as e:
            self.wait(lambda t: state(assistant=1, busy=True), timeout_s=100)
        self.assertIn("quá 100s", str(e.exception))
        self.assertTrue(100 <= self.clock.t <= 102, self.clock.t)

    def test_still_drawing_at_deadline_gets_extra_time(self):
        def script(t):                                            # ảnh ra ở giây 130 > timeout 100 nhưng đang vẽ
            return state(assistant=1, pending=True) if t < 130 else state(assistant=1, imgs=[IMG])
        self.assertEqual(self.wait(script, timeout_s=100), "blob:new")

    def test_drawing_forever_stops_at_hard_deadline(self):
        with self.assertRaises(TempError):
            self.wait(lambda t: state(assistant=1, pending=True), timeout_s=100)
        self.assertTrue(150 <= self.clock.t <= 152, self.clock.t)  # tối đa gấp rưỡi thời gian chờ


class EvalRetryTest(unittest.TestCase):
    def page(self, errors):
        clock = Clock()
        p = Page(clock)
        p.calls = 0

        def evaluate(js, *a):
            p.calls += 1
            if errors:
                raise RuntimeError(errors.pop(0))
            return {"ok": True}
        p.evaluate = evaluate
        return p

    def test_navigation_during_read_is_retried(self):
        p = self.page(["Execution context was destroyed, most likely because of a navigation"] * 3)
        self.assertEqual(driver._eval(p, "js"), {"ok": True})
        self.assertEqual(p.calls, 4)

    def test_endless_navigation_error_finally_raises(self):
        p = self.page(["Execution context was destroyed"] * 20)
        with self.assertRaises(RuntimeError):
            driver._eval(p, "js")
        self.assertEqual(p.calls, 6)

    def test_other_errors_are_not_swallowed(self):
        p = self.page(["Target page, context or browser has been closed"])
        with self.assertRaises(RuntimeError):
            driver._eval(p, "js")
        self.assertEqual(p.calls, 1)


class SendDomTest(unittest.TestCase):
    """_send thật: ô chat bị che, bấm gửi không đi, bị chặn lúc gửi."""

    class Loc:
        def __init__(self, page, sel):
            self.page, self.sel, self.first = page, sel, self

        def wait_for(self, **k):
            if self.page.no_box:
                raise RuntimeError("Timeout 30000ms exceeded")

        def click(self, **k):
            if self.page.click_error:
                raise RuntimeError(self.page.click_error)

        def evaluate(self, js, *a):
            self.page.typed = a[0]

        def is_visible(self):
            return self.page.send_button

        def is_enabled(self):
            return self.page.send_button

        def press(self, key, **k):
            if self.page.press_error:
                raise RuntimeError(self.page.press_error)
            self.page.pressed = key

    class SendPage(Page):
        no_box = send_button = False
        click_error = press_error = ""
        typed = pressed = None

        def locator(self, sel):
            return SendDomTest.Loc(self, sel)

        def evaluate(self, js, *a):
            return {"hasLoginBtn": False}

    def send(self, page, script, notice=""):
        clock = page.clock
        fake_time = types.SimpleNamespace(monotonic=clock.monotonic)
        with mock.patch.object(driver, "time", fake_time), \
                mock.patch.object(driver, "_eval", lambda p, js, *a: script(clock.t)), \
                mock.patch.object(driver, "page_notice", lambda p: notice), \
                mock.patch("calforge.llm.pool.human_pause", lambda *a, **k: None):
            return REAL_WORKER(Path("acc1"), "hidden", 100)._send(page, "PROMPT")

    def test_sent_with_enter_when_no_send_button(self):
        p = self.SendPage(Clock())
        before = self.send(p, lambda t: state(user=0) if t < 1 else state(user=1, busy=True))
        self.assertEqual((p.typed, p.pressed, before["user"]), ("PROMPT", "Enter", 0))

    def test_covered_prompt_box_is_page_error(self):
        p = self.SendPage(Clock())
        p.click_error = "Locator.click: Timeout 15000ms exceeded.\n<div role=dialog> intercepts pointer events"
        with self.assertRaises(NavError) as e:
            self.send(p, lambda t: state(user=0))
        self.assertIn("không gõ được", str(e.exception))

    def test_press_timeout_is_page_error(self):
        p = self.SendPage(Clock())
        p.press_error = "Locator.press: Timeout 15000ms exceeded."
        with self.assertRaises(NavError) as e:
            self.send(p, lambda t: state(user=0))
        self.assertIn("không bấm gửi được", str(e.exception))

    def test_message_that_never_leaves_is_page_error_after_30s(self):
        p = self.SendPage(Clock())
        with self.assertRaises(NavError) as e:
            self.send(p, lambda t: state(user=0))
        self.assertIn("không đi", str(e.exception))
        self.assertTrue(30 <= p.clock.t <= 32, p.clock.t)

    def test_limit_dialog_at_send_is_quota(self):
        p = self.SendPage(Clock())
        with self.assertRaises(QuotaExceeded):
            self.send(p, lambda t: state(user=0), notice="You've reached your limit. Limit resets in 3 hours.")

    def test_missing_prompt_box_is_page_error(self):
        p = self.SendPage(Clock())
        p.no_box = True
        with self.assertRaises(NavError):
            self.send(p, lambda t: state(user=0))


@contextmanager
def open_ok(profile):
    yield object()


def make_pool(n=3):
    names = [f"acc{i}" for i in range(1, n + 1)]
    p = AccountPool(Path("."), names, cap=n, launch_gap_s=0, state_file=None) \
        if "state_file" in AccountPool.__init__.__code__.co_varnames else AccountPool(Path("."), names, cap=n, launch_gap_s=0)
    p.rest_s = 0.2
    return p


class RunJobsRetryTest(unittest.TestCase):
    """Vòng thử lại của run_jobs với từng loại lỗi (máy vẽ giả theo kịch bản cho từng lần gọi)."""

    def run_script(self, script, max_attempts=3, n=3, jobs=None):
        calls = []
        lock = threading.Lock()

        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                with lock:
                    calls.append((job.id, self.name, job.prompt))
                    k = sum(1 for c in calls if c[0] == job.id)
                step = script(job, k, self.name)
                if isinstance(step, Exception):
                    raise step
                return job.out.with_suffix(".png")

        pool = make_pool(n)
        events = []
        jobs = jobs or [GenJob("g03", "PROMPT", Path("g03"))]
        with mock.patch.object(driver, "_Worker", W), mock.patch.object(driver, "NAV_REST_S", 0):
            out = run_jobs(jobs, Path("."), pool.names, max_attempts=max_attempts, on_event=events.append,
                           pool=pool, open_page=open_ok)
        self.assertEqual(pool.use, {}, "chưa trả hết tài khoản")
        return out, calls, events, pool

    def test_timeout_is_retried_then_succeeds(self):
        [j], calls, _, _ = self.run_script(lambda job, k, acc: TempError("quá 420s chưa ra ảnh") if k < 3 else None)
        self.assertIsNotNone(j.result)
        self.assertEqual((len(calls), j.attempts), (3, 3))

    def test_timeout_every_time_gives_up_after_max_attempts(self):
        [j], calls, events, _ = self.run_script(lambda job, k, acc: TempError("quá 420s chưa ra ảnh"))
        self.assertIsNone(j.result)
        self.assertEqual(len(calls), 3)
        self.assertIn("quá 420s", j.error)
        self.assertTrue(any("bỏ sau 3 lần" in e for e in events))

    def test_calendar_error_adds_correction_to_next_prompt(self):
        [j], calls, _, _ = self.run_script(
            lambda job, k, acc: TempError("ảnh không đạt: lịch sai: thiếu ngày 15") if k == 1 else None)
        self.assertIsNotNone(j.result)
        self.assertEqual(calls[0][2], "PROMPT")
        self.assertIn("RETRY CORRECTION", calls[1][2])            # lần vẽ lại có lời nhắc sửa lịch

    def test_plain_refusal_fails_page_without_retry_and_keeps_other_pages(self):
        jobs = [GenJob("m01", "p", Path("m01")), GenJob("m02", "p", Path("m02")), GenJob("m03", "p", Path("m03"))]
        out, calls, _, _ = self.run_script(lambda job, k, acc: Refused("content policy") if job.id == "m02" else None,
                                           jobs=jobs)
        by = {j.id: j for j in out}
        self.assertEqual(sum(1 for c in calls if c[0] == "m02"), 1)
        self.assertTrue(by["m02"].error.startswith("bị từ chối"))
        self.assertTrue(by["m01"].result and by["m03"].result)

    def test_quota_does_not_count_and_moves_to_another_account(self):
        [j], calls, _, pool = self.run_script(
            lambda job, k, acc: QuotaExceeded("limit") if acc == "acc1" else None, max_attempts=1)
        self.assertIsNotNone(j.result)
        self.assertNotEqual(calls[-1][1], "acc1")
        if any(c[1] == "acc1" for c in calls):
            self.assertTrue(pool._resting("acc1", IMAGE))

    def test_browser_crash_is_retried(self):
        [j], calls, _, _ = self.run_script(
            lambda job, k, acc: RuntimeError("Target page, context or browser has been closed") if k == 1 else None)
        self.assertIsNotNone(j.result)
        self.assertEqual(len(calls), 2)

    def test_logged_out_account_is_skipped_without_burning_attempts(self):
        [j], calls, events, pool = self.run_script(
            lambda job, k, acc: NavError(f"{driver.LOGGED_OUT}: trang ChatGPT đòi đăng nhập lại") if acc == "acc1"
            else None, max_attempts=1)
        self.assertIsNotNone(j.result)
        if any(c[1] == "acc1" for c in calls):
            self.assertTrue(any("đăng nhập lại" in e for e in events))

    def test_refusal_that_passes_on_retry_keeps_the_book(self):
        """Bị từ chối 1-2 lần rồi lần gửi lại qua: ảnh xong bình thường, cuốn không bị bỏ, không tốn lượt vẽ lỗi."""
        for refuse_times in (1, 2):
            jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 5)]
            out, calls, events, _ = self.run_script(
                lambda job, k, acc: ThirdPartyIPRefused(ADULT) if job.id == "m02" and k <= refuse_times else None,
                max_attempts=1, jobs=jobs)
            self.assertTrue(all(j.result is not None and j.error is None for j in out), refuse_times)
            by = {j.id: j for j in out}
            self.assertEqual(by["m02"].refusals, refuse_times)
            self.assertEqual(sum(1 for c in calls if c[0] == "m02"), refuse_times + 1)
            self.assertEqual(sum("gửi lại prompt" in e for e in events), refuse_times)
            self.assertFalse(any("BỎ CUỐN" in e for e in events))

    def test_third_refusal_drops_book(self):
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 5)]
        out, calls, events, _ = self.run_script(
            lambda job, k, acc: ThirdPartyIPRefused(ADULT) if job.id == "m01" else None, n=1, jobs=jobs)
        self.assertEqual([c[0] for c in calls], ["m01"] * 3)      # đúng 3 lần gửi, rồi huỷ mọi trang còn lại
        self.assertTrue(all(j.error.startswith(pipeline.IP_REJECTED_MARK) for j in out))
        self.assertEqual(sum("BỎ CUỐN" in e for e in events), 1)

    def test_adult_refusal_from_real_dom_cancels_rest_of_book(self):
        """Câu từ chối khỏa thân đọc từ trang (qua _wait_image thật) -> huỷ mọi trang chưa gửi của cuốn."""
        sent = []

        class W(REAL_WORKER):
            def run_job(self, page, job):
                sent.append(job.id)
                clock = Clock()
                with mock.patch.object(driver, "_eval", lambda p, js, *a: state(busy=True, tail=ADULT)):
                    return self._wait_image(Page(clock), BEFORE)

        pool = make_pool(1)
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 7)]
        with mock.patch.object(driver, "_Worker", W):
            out = run_jobs(jobs, Path("."), pool.names, max_attempts=3, on_event=lambda *_: None, pool=pool,
                           open_page=open_ok)
        self.assertEqual(sent, ["m01"] * 3)                       # gửi lại 2 lần nữa, không gửi prompt nào khác
        self.assertEqual(out[0].refusals, 3)
        self.assertTrue(all(j.error.startswith(pipeline.IP_REJECTED_MARK) for j in out))
        self.assertIn("khỏa thân", out[0].error)
        self.assertEqual(pool.use, {})


class RefusedBookInBatchTest(unittest.TestCase):
    """Batch thật qua hàng đợi: 1 cuốn bị ChatGPT từ chối vì ảnh khỏa thân -> bỏ hẳn cuốn, cuốn khác vẫn xong;
    Làm nốt / Làm tiếp / Vẽ lại / Hoàn thiện đều không đụng lại cuốn đó."""

    queue, drain, book_params, status = (tr.Recovery.queue, tr.Recovery.drain, tr.Recovery.book_params,
                                         tr.Recovery.status)

    def setUp(self):
        tr.Recovery.setUp(self)
        self.sim.world.fault = 0.0
        base = driver._Worker                                     # máy vẽ giả của Sim
        doomed, calls, lock = [], [], threading.Lock()
        self.doomed, self.calls = doomed, calls

        class W(base):
            def run_job(self, page, job):
                book = job.out.parents[2]
                with lock:
                    calls.append((book.name, job.id, time.monotonic()))
                    if job.id == "m05" and not doomed:
                        doomed.append((book, time.monotonic()))
                    first = job.id == "m05" and doomed[0][0] == book      # prompt này lần nào cũng bị từ chối
                if first:
                    raise ThirdPartyIPRefused(ADULT)
                return super().run_job(page, job)

        p = mock.patch.object(driver, "_Worker", W)
        p.start()
        self.addCleanup(p.stop)

    def test_refused_book_is_dropped_and_never_touched_again(self):
        q, tasks = self.queue()
        params = {"keyword": "pandas", "batch_size": 3, "product": "wall_grid", "grid_mode": "ai_page"}
        q.add(params)
        [item] = self.drain(q)
        books = self.sim.books("pandas")
        self.assertEqual(len(books), 3)
        [(bad, _)] = self.doomed
        st = self.status(bad)
        self.assertEqual((st["stage"], st["ok"], st.get("terminal")), ("ip_rejected", False, True))
        self.assertIn("khỏa thân", st["reason"])
        good = [b for b in books if b != bad]
        self.assertTrue(all(pipeline._finished_ok(b) for b in good))         # cuốn khác không bị ảnh hưởng
        self.assertEqual((item["status"], item["ok"], item["total"]), ("partial", 2, 3))
        self.assertFalse(item["retryable"])                                   # không còn gì để "Làm nốt"
        self.assertFalse(pipeline.needs_finishing(bad))
        self.assertFalse((layout.listing(bad)).exists() and any(layout.listing(bad).glob("*.jpg")))

        n_calls = len(self.calls)
        q.add({**params, "resume": True})                                     # vẫn bấm "Làm nốt phần thiếu"
        self.drain(q)
        self.assertEqual(len(self.calls), n_calls)                            # không vẽ thêm ảnh nào
        self.assertEqual(len(self.sim.books("pandas")), 3)                    # không sinh cuốn mới

        for action, kw in (("produce", {}), ("finish", {}), ("redo", {"pages": ["m05"]})):
            with self.assertRaises(ValueError, msg=action):                   # nút nào cũng bị từ chối ngay lúc bấm
                server.run_args(self.book_params(bad, action, **kw))
        with self.assertRaises(ValueError):
            pipeline.redo_pages(bad, ["m05"])
        self.assertEqual(len(self.calls), n_calls)
        self.assertFalse(tasks.overlap)
        tb.check_invariants(self, self.sim)

    def test_new_batch_on_same_topic_still_works_after_a_dropped_book(self):
        q, _ = self.queue()
        params = {"keyword": "otters", "batch_size": 2, "product": "wall_grid", "grid_mode": "background"}
        q.add(params)
        self.drain(q)
        q.add(params)                                                         # batch MỚI (không phải làm nốt)
        items = self.drain(q)
        self.assertEqual(items[-1]["status"], "done")
        books = self.sim.books("otters")
        self.assertEqual(len(books), 4)
        self.assertEqual(sum(pipeline._finished_ok(b) for b in books), 3)     # 1 cuốn bị bỏ ở batch đầu
        tb.check_invariants(self, self.sim)


class OldAiMockupBookUpgradeTest(unittest.TestCase):
    """Cuốn "AI gen mockup" làm trước 02/10 (01 02 03 05): ghép lại -> 04 hai tờ treo tường + 06 ba cuốn, bỏ 05."""

    def test_previews_and_ai_step_only_do_the_new_images(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c = tam.book(root)
            pages = layout.print_dir(c)
            pages.mkdir(parents=True, exist_ok=True)
            for n in ["front_cover", "back_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")]:
                Image.new("RGB", (60, 40), "white").save(pages / f"{n}.png")
            old_time = time.time() - 3600
            import os
            for f in pages.iterdir():
                os.utime(f, (old_time, old_time))
            listing = layout.listing(c)
            for f in listing.glob("*.jpg"):
                f.unlink()
            old = ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads", "05_wall_page_turn"]
            for n in old + ["04_wall_spread"]:                    # 04 cũ còn sót từ thời chưa chọn AI mockup
                Image.new("RGB", (1024, 1024), "blue").save(listing / f"{n}.jpg")
            layout.tech(c).mkdir(parents=True, exist_ok=True)
            layout.tech(c, "mockup_ai.json").write_text(json.dumps(
                {n: {"mtime_ns": (listing / f"{n}.jpg").stat().st_mtime_ns} for n in old}), encoding="utf-8")
            self.assertEqual(mockups.missing_previews(c), ["04_two_wall_spreads.jpg", "06_three_books.jpg",
                                                           "07_three_open_spreads_fall.jpg", "08_wall_and_back.jpg", "09_year_grid.jpg"])

            def fake_render(name, pages_dir, out):
                Image.new("RGB", (1600, 1600), "gray").save(out)
            with mock.patch.object(mockups, "render", fake_render):
                made = mockups.previews(c, on_event=lambda *_: None)
            self.assertEqual([p.name for p in made], ["04_two_wall_spreads.jpg", "06_three_books.jpg",
                                                      "07_three_open_spreads_fall.jpg", "08_wall_and_back.jpg", "09_year_grid.jpg"])
            self.assertEqual(sorted(p.name for p in listing.glob("*.jpg")),
                             ["01_front_cover_spiral.jpg", "02_open_spread_flat.jpg", "03_three_open_spreads.jpg",
                              "04_two_wall_spreads.jpg", "06_three_books.jpg", "07_three_open_spreads_fall.jpg", "08_wall_and_back.jpg", "09_year_grid.jpg"])
            self.assertEqual(mockups.missing_previews(c), [])
            self.assertEqual(ai_mockups.pending(c), ["04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"])   # 3 ảnh AI cũ giữ nguyên

            cfg = {"projects_dir": str(root), "profiles_dir": str(root / "profiles"), "imagegen": {}}
            (root / "profiles" / "acc1").mkdir(parents=True)
            fake = tam.FakeRun()
            with mock.patch.object(driver, "run_jobs", fake):
                res = ai_mockups.ai_previews(c, cfg, on_event=lambda *_: None)
            self.assertEqual(sorted(res["ai"]), ["04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"])
            self.assertEqual(sorted(j.id for j in fake.calls[0]), ["04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"])
            self.assertEqual(ai_mockups.pending(c), [])

    def test_template_mode_books_keep_the_old_five_previews(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            c = tam.book(Path(tmp), mockup_mode="template")
            concept = json.loads(layout.concept_file(c).read_text(encoding="utf-8"))
            self.assertEqual(mockups.preview_names(concept), mockups.PREVIEWS)
            self.assertEqual(mockups.skipped_previews(concept), set())


if __name__ == "__main__":
    unittest.main()
