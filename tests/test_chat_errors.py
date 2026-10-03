"""LỖI Ở LUỒNG CHAT LÊN Ý TƯỞNG (calforge/llm/chatgpt_web.py), với trang giả + đồng hồ giả.

_WebChat.ask: mọi kiểu ChatGPT trả lời / không trả lời. _RotatingChat: đổi tài khoản khi lỗi, giới hạn số tài khoản
đem một prompt đi thử, tài khoản chết giữa chừng, mở Chrome không được. Backend: file xoay vòng hỏng.
"""
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli  # noqa: F401 - đặt stdout UTF-8 như lúc chạy thật
from calforge.imagegen import driver
from calforge.llm import chatgpt_web as cw
from calforge.llm import limits
from calforge.llm import pool as poolmod
from calforge.llm.pool import CHAT, AccountPool


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


def st(**kw):
    return {"user": 1, "assistant": 0, "busy": False, "text": "", "codes": [], **kw}


class Box:
    first = None

    def __init__(self, page):
        self.page, self.first = page, self

    def wait_for(self, **k):
        if self.page.no_box:
            raise RuntimeError("Timeout")

    def click(self, **k):
        if self.page.click_error:
            raise RuntimeError(self.page.click_error)

    def evaluate(self, js, *a):
        self.page.typed = a[0]

    def is_visible(self):
        return False

    def is_enabled(self):
        return False

    def press(self, key, **k):
        self.page.presses += 1


class Page:
    no_box = False
    click_error = ""
    typed = None
    url = "https://chatgpt.com/"

    def __init__(self, clock):
        self.clock, self.presses = clock, 0

    def locator(self, sel):
        return Box(self)

    def wait_for_timeout(self, ms):
        self.clock.t += ms / 1000

    def wait_for_load_state(self, *a, **k):
        pass


class AskTest(unittest.TestCase):
    def ask(self, script, notice="", timeout_s=100, page=None, **kw):
        clock = Clock()
        page = page or Page(clock)
        page.clock = clock
        self.page, self.clock = page, clock
        note = notice if callable(notice) else (lambda t: notice)
        chat = cw._WebChat(page, timeout_s, **kw)
        with mock.patch.object(cw, "time", types.SimpleNamespace(monotonic=clock.monotonic)), \
                mock.patch.object(driver, "_eval",
                                  lambda p, js, *a: st(user=0) if clock.t < 0.3 else script(clock.t)), \
                mock.patch.object(limits, "page_notice", lambda p: note(clock.t)), \
                mock.patch("calforge.llm.pool.human_pause", lambda *a, **k: None):
            return chat.ask("PROMPT", "p2_x")

    def test_json_answer_is_returned_with_fenced_block(self):
        def script(t):
            if t < 0.5:
                return st(user=0)
            if t < 10:
                return st(assistant=1, busy=True, text="Working")
            return st(assistant=1, text="Here it is", codes=['{"a": 1}'])
        out = self.ask(script)
        self.assertIn("Here it is", out)
        self.assertIn('```json\n{"a": 1}\n```', out)
        self.assertEqual(self.page.typed, "PROMPT")
        self.assertGreaterEqual(self.clock.t, 14)                      # chữ đứng yên đủ 4 giây mới nhận

    def test_stale_stop_button_with_complete_json_is_accepted(self):
        out = self.ask(lambda t: st(user=0) if t < 0.5 else st(assistant=1, busy=True, text="x", codes=['{"a": 1}']))
        self.assertIn('{"a": 1}', out)

    def test_stale_stop_button_with_broken_json_times_out(self):
        with self.assertRaises(TimeoutError):
            self.ask(lambda t: st(assistant=1, busy=True, text="x", codes=['{"a":']), timeout_s=60)
        self.assertTrue(60 <= self.clock.t <= 62)

    def test_quota_text_and_banner(self):
        with self.assertRaises(cw.QuotaExceeded):
            self.ask(lambda t: st(assistant=1, text="You've reached your limit. Limit resets in 2 hours."))
        with self.assertRaises(cw.QuotaExceeded):
            self.ask(lambda t: st(user=1, busy=False), notice=lambda t: "Too many requests" if t > 2 else "")

    def test_blocked_at_send(self):
        with self.assertRaises(cw.QuotaExceeded) as e:
            self.ask(lambda t: st(user=0), notice="You've hit the plus plan limit")
        self.assertIn("chặn lúc gửi", str(e.exception))

    def test_message_never_leaves(self):
        with self.assertRaises(cw.SendFailed) as e:
            self.ask(lambda t: st(user=0))
        self.assertIn("Không gửi được", str(e.exception))
        self.assertEqual(self.page.presses, 2)                         # đã bấm gửi lại một lần
        self.assertTrue(30 <= self.clock.t <= 33)

    def test_refusals_and_errors_without_json_fail_fast(self):
        for text in ("I can't help with that request because it violates our content policy.",
                     "Sorry, I cannot create copyrighted characters; that may infringe third-party rights.",
                     "Something went wrong while generating the response."):
            with self.assertRaises(cw.SendFailed, msg=text):
                self.ask(lambda t, text=text: st(assistant=1, text=text))
            self.assertLess(self.clock.t, 5)

    def test_refusal_words_inside_a_json_answer_are_not_an_error(self):
        text = "The concept avoids anything that violates trademark or copyright."
        out = self.ask(lambda t: st(assistant=1, text=text, codes=['{"title": "ok"}']))
        self.assertIn("ok", out)

    def test_never_starts_answering(self):
        with self.assertRaises(cw.SendFailed) as e:
            self.ask(lambda t: st(user=1), timeout_s=600)
        self.assertIn("không bắt đầu trả lời", str(e.exception))
        self.assertTrue(90 <= self.clock.t <= 95)

    def test_stops_without_readable_answer(self):
        def script(t):
            return st(busy=True) if t < 20 else st(assistant=1, text="")
        with self.assertRaises(cw.SendFailed) as e:
            self.ask(script, timeout_s=600)
        self.assertIn("không có câu trả lời", str(e.exception))
        self.assertTrue(50 <= self.clock.t <= 55)                      # 30 giây ân hạn sau khi dừng

    def test_thinking_forever_times_out(self):
        with self.assertRaises(TimeoutError):
            self.ask(lambda t: st(busy=True), timeout_s=120)
        self.assertTrue(120 <= self.clock.t <= 122)

    def test_long_thinking_then_answer_is_fine(self):
        def script(t):
            return st(busy=True) if t < 400 else st(assistant=1, text="done", codes=['{"a": 1}'])
        self.assertIn("done", self.ask(script, timeout_s=600))

    def test_prompt_box_missing_or_covered(self):
        p = Page(Clock())
        p.no_box = True
        with self.assertRaises(RuntimeError):
            self.ask(lambda t: st(user=0), page=p)
        p = Page(Clock())
        p.click_error = "Locator.click: Timeout 30000ms exceeded"
        with self.assertRaises(RuntimeError):
            self.ask(lambda t: st(user=0), page=p)


class FakeChat:
    def __init__(self, behaviour, page=None):
        self.behaviour, self.page = behaviour, page

    def ask(self, prompt, label):
        if isinstance(self.behaviour, BaseException):
            raise self.behaviour
        return self.behaviour


class RotationErrorsTest(unittest.TestCase):
    def rot(self, behaviours, n=None, pages=None):
        rot = cw._RotatingChat.__new__(cw._RotatingChat)
        n = n or len(behaviours)
        rot.order, rot.ctx, rot.chat, rot.profile = [f"acc{i}" for i in range(1, n + 1)], None, None, None
        rot.failed = set()
        rot.max_request_accounts = min(n, cw.MAX_REQUEST_ACCOUNTS)
        opened = []

        def open_next(exclude=None):
            name = rot.order.pop(0)
            self.assertNotIn(name, exclude or set())
            i = len(opened)
            rot.profile = name
            rot.chat = FakeChat(behaviours[i] if i < len(behaviours) else behaviours[-1],
                                pages[i] if pages and i < len(pages) else None)
            opened.append(name)

        rot._open_next = open_next
        rot.close = lambda: (setattr(rot, "chat", None), setattr(rot, "profile", None))
        return rot, opened

    def test_browser_crash_mid_chat_moves_to_next_account(self):
        for err in (RuntimeError("Target page, context or browser has been closed"),
                    RuntimeError("Không thấy phần tử nào khớp ['#prompt-textarea']"),
                    KeyError("text"), OSError("pipe closed")):
            rot, opened = self.rot([err, "answer"])
            self.assertEqual(rot.ask("p", "p2"), "answer", err)
            self.assertEqual(opened, ["acc1", "acc2"])

    def test_every_account_broken_gives_clear_error(self):
        rot, opened = self.rot([RuntimeError("Target closed")] * 3)
        with self.assertRaisesRegex(RuntimeError, "Tất cả 3 tài khoản đều lỗi trang"):
            rot.ask("p", "p2")
        self.assertEqual(len(opened), 3)

    def test_bad_prompt_is_not_tried_on_all_40_accounts(self):
        rot, opened = self.rot([cw.SendFailed("ChatGPT trả refused")], n=40)
        with self.assertRaises(RuntimeError):
            rot.ask("p", "p2")
        self.assertEqual(len(opened), cw.MAX_REQUEST_ACCOUNTS)        # 5 tài khoản là đủ kết luận prompt hỏng

    def test_quota_does_not_count_toward_that_cap(self):
        rot, opened = self.rot([cw.QuotaExceeded("limit")] * 9 + ["answer"], n=40)
        with mock.patch.object(poolmod, "get_pool", lambda cfg=None: mock.Mock(rest_s=1)):
            self.assertEqual(rot.ask("p", "p1"), "answer")           # hết lượt thì cứ đổi tài khoản tới khi được
        self.assertEqual(len(opened), 10)

    def test_mixed_failures_then_success(self):
        rot, opened = self.rot([cw.SendFailed("popup"), TimeoutError("lost"), RuntimeError("Target closed"), "ok"])
        self.assertEqual(rot.ask("p", "p2"), "ok")
        self.assertEqual(len(opened), 4)

    def test_account_logged_out_mid_chat_is_dropped(self):
        login = types.SimpleNamespace(
            url="https://chatgpt.com/", wait_for_timeout=lambda ms: None,
            evaluate=lambda js: "Log in\nSign up" if js == driver.BODY_TEXT_JS else {"hasLoginBtn": True, "appReady": False})
        ok_page = types.SimpleNamespace(
            url="https://chatgpt.com/", wait_for_timeout=lambda ms: None,
            evaluate=lambda js: "ChatGPT" if js == driver.BODY_TEXT_JS else {"hasLoginBtn": False, "appReady": True})
        notes = []
        pool = AccountPool(Path("."), ["acc1", "acc2", "acc3"], cap=3, notify=notes.append)
        rot, opened = self.rot([cw.SendFailed("Không gửi được tin nhắn"), RuntimeError("Target closed"), "answer"],
                               pages=[login, ok_page, ok_page])
        with mock.patch.object(poolmod, "get_pool", lambda cfg=None: pool):
            self.assertEqual(rot.ask("p", "p2"), "answer")
        self.assertEqual(list(pool.dead), ["acc1"])                  # màn hình đăng nhập: chết; Chrome sập: không
        self.assertEqual(pool.dead["acc1"]["kind"], "logged_out")
        self.assertTrue(pool._resting("acc1", CHAT))
        self.assertEqual(sum("TÀI KHOẢN CHẾT" in n for n in notes), 1)


class OpenNextTest(unittest.TestCase):
    """_open_next thật với Chrome giả: mở không được, màn hình đăng nhập, mọi tài khoản đều nghỉ."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pdir = Path(self.tmp.name)
        self.names = ["acc1", "acc2", "acc3"]
        for n in self.names:
            (self.pdir / n).mkdir()
        self.notes = []
        self.pool = AccountPool(self.pdir, self.names, cap=3, launch_gap_s=0, notify=self.notes.append)
        self.launched = []

    def rot(self, launch, find_ok=lambda name: True, state=lambda name: {"hasLoginBtn": False, "appReady": True}):
        test = self

        class Ctx:
            def __init__(self, name):
                self.name = name
                self.pages = [types.SimpleNamespace(
                    url="https://chatgpt.com/", wait_for_timeout=lambda ms: None,
                    evaluate=lambda js, name=name: "" if js == driver.BODY_TEXT_JS else state(name))]

            def close(self):
                pass

        def launch_ctx(user_data_dir, **kw):
            name = Path(user_data_dir).name
            test.launched.append(name)
            launch(name)
            return Ctx(name)

        pw = types.SimpleNamespace(chromium=types.SimpleNamespace(launch_persistent_context=launch_ctx))
        backend = cw.ChatGPTWebBackend(str(self.pdir), None, headless=True, state_file=self.pdir / "rot.json")
        rot = cw._RotatingChat(backend, pw)

        def find(self_chat, selectors, timeout_ms=30000):
            if not find_ok(rot.profile):
                raise RuntimeError("Không thấy phần tử nào khớp ['#prompt-textarea']")
        patches = [mock.patch.object(poolmod, "get_pool", lambda cfg=None: self.pool),
                   mock.patch.object(driver, "open_home", lambda page, url: None),
                   mock.patch.object(limits, "RateWatch", lambda page: None),
                   mock.patch.object(cw._WebChat, "_find", find)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return rot

    def test_launch_failure_skips_to_next_account(self):
        def launch(name):
            if name == "acc2":
                raise RuntimeError("Failed to launch chrome: profile in use")
        rot = self.rot(launch)
        rot._open_next()
        self.assertEqual(rot.profile, "acc3")
        self.assertEqual(self.launched, ["acc2", "acc3"])              # acc1 xếp cuối theo thứ tự xoay vòng
        self.assertTrue(self.pool._resting("acc2", CHAT))
        self.assertNotIn("acc2", self.pool.dead)
        self.assertEqual(self.pool.use, {"acc3": CHAT})
        rot.close()
        self.assertEqual(self.pool.use, {})

    def test_login_screen_marks_account_dead(self):
        rot = self.rot(lambda name: None, find_ok=lambda name: name != "acc2",
                       state=lambda name: {"hasLoginBtn": name == "acc2", "appReady": name != "acc2"})
        rot._open_next()
        self.assertEqual(rot.profile, "acc3")
        self.assertEqual(list(self.pool.dead), ["acc2"])
        self.assertTrue((self.pdir / "acc2" / poolmod.DEAD_MARKER).exists())
        rot.close()

    def test_page_without_prompt_box_is_not_dead(self):
        """Như lúc bật headless thật: không có ô chat nhưng cũng không phải màn hình đăng nhập -> chỉ bỏ qua."""
        rot = self.rot(lambda name: None, find_ok=lambda name: False,
                       state=lambda name: {"hasLoginBtn": False, "appReady": False})
        with self.assertRaises(cw.NoAccountLeft):
            rot._open_next()
        self.assertEqual(self.pool.dead, {})
        self.assertEqual(sorted(self.launched), self.names)
        self.assertEqual(self.pool.use, {})

    def test_all_accounts_resting_raises_no_account_left(self):
        for n in self.names:
            self.pool.rest(n, CHAT, 60, "hết lượt")
        rot = self.rot(lambda name: None)
        with self.assertRaises(cw.NoAccountLeft):
            rot._open_next()
        self.assertEqual(self.launched, [])

    def test_exclude_all_raises_plain_error(self):
        rot = self.rot(lambda name: None)
        with self.assertRaisesRegex(RuntimeError, "Không còn tài khoản chưa thử"):
            rot._open_next(exclude=set(self.names))


class BackendStateTest(unittest.TestCase):
    def test_corrupt_or_unwritable_rotation_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            for n in ("acc1", "acc2", "acc3"):
                (pdir / n).mkdir()
            f = pdir / "rot.json"
            for junk in ('{"last": "ac', "", "null", "[1]", '{"last": "acc2", "count": 5}'):
                f.write_text(junk, encoding="utf-8")
                b = cw.ChatGPTWebBackend(str(pdir), None, state_file=f)
                self.assertEqual(len(b.rotation_order()), 3, junk)
                b.mark_used("acc2")
                self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["last"], "acc2")
            b = cw.ChatGPTWebBackend(str(pdir), None, state_file=pdir / "no" / "\0bad" / "rot.json")
            self.assertEqual(len(b.rotation_order()), 3)

    def test_no_profiles_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                cw.ChatGPTWebBackend(tmp, None)


if __name__ == "__main__":
    unittest.main()
