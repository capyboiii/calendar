"""CÁC NHÁNH XỬ LÝ LỖI CHƯA TỪNG ĐƯỢC TEST CHẠM TỚI (tìm bằng phép đo dòng code đã chạy).

Đính kèm ảnh, nút gửi, theo dõi 429, nhắc ChatGPT vẽ mới, mở Chrome thật (Playwright giả), hàng đợi (cũ / sắp xếp /
vòng chạy nền), ảnh quảng cáo AI, kiểm tra ảnh, khoá batch, lỗi ở bước lên ý tưởng của batch, hậu kỳ.
"""
import io
import json
import os
import tempfile
import threading
import time
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import cli, layout, pipeline  # noqa: F401 - cli đặt stdout UTF-8 như lúc chạy thật
from calforge.ideation import pipeline as ideation
from calforge.imagegen import ai_mockups, driver, generate
from calforge.imagegen.driver import GenJob, NavError, QuotaExceeded, TempError, run_jobs
from calforge.llm import limits
from calforge.llm import pool as poolmod
from calforge.llm.chatgpt_web import NoAccountLeft
from calforge.llm.pool import CHAT, IMAGE, AccountPool
from calforge.ui.batch_queue import BatchQueue

from tests import test_ai_mockups as tam
from tests import test_batch_simulation as tb
from tests import test_forty_accounts as t40
from tests import test_workflow_full as twf

REAL_WORKER = driver._Worker


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t


class AttachTest(unittest.TestCase):
    """_attach thật: chọn đúng ô file, ô đầu hỏng thì thử ô sau, chờ tải lên xong, hết giờ thì báo lỗi thử lại."""

    def page(self, inputs, states):
        clock = Clock()
        self.clock = clock

        class Inp:
            def __init__(self, ident, fail):
                self.ident, self.fail, self.files = ident, fail, None

            def get_attribute(self, name):
                return self.ident

            def set_input_files(self, files):
                if self.fail:
                    raise RuntimeError("element is not attached")
                self.files = files

        self.inputs = [Inp(i, f) for i, f in inputs]
        loc = mock.Mock()
        loc.first.wait_for = lambda **k: None
        loc.all = lambda: self.inputs
        page = mock.Mock()
        page.locator = lambda sel: loc
        page.wait_for_timeout = lambda ms: setattr(clock, "t", clock.t + ms / 1000)
        self.states = list(states)
        return page

    def attach(self, page, files=("a.png", "b.png")):
        seq = self.states
        with mock.patch.object(driver, "time", types.SimpleNamespace(monotonic=self.clock.monotonic)), \
                mock.patch.object(driver, "_eval", lambda p, js, *a: seq.pop(0) if len(seq) > 1 else seq[0]):
            REAL_WORKER(Path("acc1"), "hidden", 30)._attach(page, [Path(f) for f in files])

    def test_skips_camera_input_and_prefers_desktop_input(self):
        page = self.page([("upload-camera", False), ("mobile-upload", False), ("upload-files", False)],
                         [{"n": 0, "uploading": True}, {"n": 2, "uploading": True}, {"n": 2, "uploading": False}])
        self.attach(page)
        self.assertIsNone(self.inputs[0].files)                       # không đụng ô chụp ảnh
        self.assertIsNone(self.inputs[1].files)
        self.assertEqual(len(self.inputs[2].files), 2)                 # ô máy tính được dùng trước ô mobile

    def test_falls_back_to_next_input_when_first_fails(self):
        page = self.page([("upload-files", True), ("mobile-upload", False)], [{"n": 2, "uploading": False}])
        self.attach(page)
        self.assertEqual(len(self.inputs[1].files), 2)

    def test_upload_that_never_finishes_is_retryable(self):
        page = self.page([("upload-files", False)], [{"n": 1, "uploading": True}])
        with self.assertRaises(TempError):
            self.attach(page)
        self.assertGreaterEqual(self.clock.t, 40)                      # chờ 30s + 5s mỗi ảnh rồi mới bỏ

    def test_no_files_is_a_no_op(self):
        REAL_WORKER(Path("acc1"), "hidden", 30)._attach(mock.Mock(side_effect=AssertionError), [])


class SendButtonTest(unittest.TestCase):
    def send(self, button_click_error=""):
        clock = Clock()
        clicked, pressed = [], []

        class Loc:
            def __init__(self, sel):
                self.sel, self.first = sel, self

            def wait_for(self, **k):
                pass

            def click(self, **k):
                if self.sel in driver.SEL_SEND:
                    if button_click_error:
                        raise RuntimeError(button_click_error)
                    clicked.append(self.sel)

            def evaluate(self, js, *a):
                pass

            def is_visible(self):
                return self.sel in driver.SEL_SEND

            def is_enabled(self):
                return True

            def press(self, key, **k):
                pressed.append(key)

        page = types.SimpleNamespace(locator=lambda sel: Loc(sel), url="https://chatgpt.com/",
                                     wait_for_timeout=lambda ms: setattr(clock, "t", clock.t + ms / 1000))
        script = lambda: twf.state(user=0) if clock.t < 1 else twf.state(user=1, busy=True)
        with mock.patch.object(driver, "time", types.SimpleNamespace(monotonic=clock.monotonic)), \
                mock.patch.object(driver, "_eval", lambda p, js, *a: script()), \
                mock.patch.object(driver, "page_notice", lambda p: ""), \
                mock.patch("calforge.llm.pool.human_pause", lambda *a, **k: None):
            REAL_WORKER(Path("acc1"), "hidden", 30)._send(page, "PROMPT")
        return clicked, pressed

    def test_send_button_is_clicked_when_visible(self):
        clicked, pressed = self.send()
        self.assertEqual((len(clicked), pressed), (1, []))

    def test_broken_send_button_falls_back_to_enter(self):
        clicked, pressed = self.send("element intercepts pointer events")
        self.assertEqual((clicked, pressed), ([], ["Enter"]))


class RateWatchTest(unittest.TestCase):
    def resp(self, url, status, method="POST", body="", text_error=False):
        def text():
            if text_error:
                raise RuntimeError("body already consumed")
            return body
        return types.SimpleNamespace(url=url, status=status, text=text, request=types.SimpleNamespace(method=method))

    def watch(self):
        page = mock.Mock()
        w = limits.RateWatch(page)
        page.on.assert_called_once()
        return w

    def test_429_on_core_request_is_remembered(self):
        w = self.watch()
        t0 = time.monotonic()
        w._on_response(self.resp("https://chatgpt.com/backend-api/conversation", 429))
        self.assertIn("429", w.recent(t0 - 1) or "")
        self.assertIsNone(w.recent(time.monotonic() + 5))             # chỉ tính lỗi SAU mốc đang xét

    def test_error_body_with_limit_words(self):
        w = self.watch()
        w._on_response(self.resp("https://chatgpt.com/backend-api/conversation", 403,
                                 body='{"detail": {"code": "usage_limit_reached"}}'))
        self.assertIn("usage_limit", w.recent(0) or "")

    def test_noise_is_ignored_and_never_raises(self):
        w = self.watch()
        w._on_response(self.resp("https://example.com/api", 429))                         # máy chủ khác
        w._on_response(self.resp("https://chatgpt.com/backend-api/conversations", 429, method="GET"))   # không phải lõi
        w._on_response(self.resp("https://chatgpt.com/backend-api/conversation", 500, text_error=True))
        w._on_response(self.resp("https://chatgpt.com/backend-api/conversation", 404, body="not found"))
        w._on_response(object())                                                           # phản hồi lạ
        self.assertIsNone(w.recent(0))

    def test_page_notice_survives_closed_page(self):
        page = mock.Mock()
        page.evaluate.side_effect = RuntimeError("Target closed")
        self.assertEqual(limits.page_notice(page), "")

    def test_limited_uses_network_hit_before_banner(self):
        page = types.SimpleNamespace(_calforge_rate=types.SimpleNamespace(recent=lambda since: "HTTP 429 /conversation"))
        with mock.patch.object(driver, "page_notice", mock.Mock(side_effect=AssertionError)):
            self.assertEqual(REAL_WORKER(Path("acc1"), "hidden", 30)._limited(page, 0), "HTTP 429 /conversation")


class RunJobFlowTest(unittest.TestCase):
    def png(self):
        buf = io.BytesIO()
        Image.new("RGB", (1536, 1024), "red").save(buf, "PNG")
        return buf.getvalue()

    def test_chatgpt_asks_for_source_image_then_gets_nudged(self):
        import base64
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        job = GenJob("m03", "PROMPT", Path(tmp.name) / "m03")
        w = REAL_WORKER(Path("acc1"), "hidden", 30)
        sent, waits = [], iter([driver.WantsSourceImage("Please upload the image"), "blob:x"])

        def wait_image(page, before):
            r = next(waits)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(driver, "open_home"), mock.patch.object(w, "_find"), mock.patch.object(w, "_attach"), \
                mock.patch.object(w, "_send", lambda page, prompt: sent.append(prompt) or {}), \
                mock.patch.object(w, "_wait_image", wait_image), mock.patch.object(driver, "RateWatch"), \
                mock.patch.object(driver, "_eval", return_value=base64.b64encode(self.png()).decode()):
            out = w.run_job(mock.Mock(spec=[]), job)
        self.assertEqual(sent, ["PROMPT", driver.NUDGE_NEW])          # nhắc ngay trong chat đó, không gửi lại cả prompt
        self.assertTrue(out.is_file())

    def test_second_refusal_to_draw_is_a_retryable_error(self):
        job = GenJob("m03", "PROMPT", Path("m03"))
        w = REAL_WORKER(Path("acc1"), "hidden", 30)
        with mock.patch.object(driver, "open_home"), mock.patch.object(w, "_find"), mock.patch.object(w, "_attach"), \
                mock.patch.object(w, "_send", return_value={}), mock.patch.object(driver, "RateWatch"), \
                mock.patch.object(w, "_wait_image", mock.Mock(side_effect=driver.WantsSourceImage("upload the image"))):
            with self.assertRaises(TempError):
                w.run_job(mock.Mock(spec=[]), job)

    def test_grid_background_rejection_adds_its_own_correction(self):
        job = GenJob("grid", "PROMPT", Path("grid"), error="ảnh không đạt: vùng đặt lịch quá rối", attempts=1)
        driver._correct_prompt(job)
        self.assertIn("RETRY CORRECTION 1", job.prompt)
        self.assertIn("calendar writing area", job.prompt)
        plain = GenJob("m03", "PROMPT", Path("m03"), error="ảnh không đạt: sai tỉ lệ", attempts=1)
        driver._correct_prompt(plain)
        self.assertEqual(plain.prompt, "PROMPT")                       # lỗi khác không bị nhồi thêm câu

    def test_open_home_survives_load_state_error(self):
        class P:
            url = "about:blank"

            def goto(self, url, **k):
                self.url = "https://chatgpt.com/"
                raise RuntimeError("Navigation interrupted by another navigation")

            def wait_for_load_state(self, *a, **k):
                raise RuntimeError("Timeout 30000ms")

            def wait_for_timeout(self, ms):
                pass
        driver.open_home(P(), "https://chatgpt.com/")                 # đã ở trang ChatGPT: coi như mở được


class RealOpenerTest(unittest.TestCase):
    """default_open thật của run_jobs với Playwright giả: mở cách nhau qua cổng, luôn đóng Chrome, mở hỏng thì đổi acc."""

    def run_with(self, launch):
        closed, launched = [], []

        class Ctx:
            def __init__(self, name):
                self.name, self.pages = name, [object()]

            def close(self):
                closed.append(self.name)

        def launch_ctx(udir, **kw):
            name = Path(udir).name
            launched.append((name, kw.get("headless"), tuple(kw.get("args") or ())))
            launch(name)
            return Ctx(name)

        @contextmanager
        def fake_playwright():
            yield types.SimpleNamespace(chromium=types.SimpleNamespace(launch_persistent_context=launch_ctx))

        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                if job.id == "boom":
                    raise KeyboardInterrupt("tắt ngang")
                return job.out.with_suffix(".png")

        pool = AccountPool(Path("."), ["acc1", "acc2", "acc3"], cap=3, launch_gap_s=0, notify=lambda m: None)
        gates = []
        real_gate = pool.launch_gate

        @contextmanager
        def gate():
            gates.append(1)
            with real_gate():
                yield
        pool.launch_gate = gate
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 7)]
        events = []
        with mock.patch("playwright.sync_api.sync_playwright", fake_playwright), \
                mock.patch.object(driver, "_Worker", W), \
                mock.patch("calforge.llm.browser.hide_offscreen_from_taskbar", lambda: 0):
            out = run_jobs(jobs, Path("profiles"), pool.names, headless="hidden", on_event=events.append, pool=pool)
        return out, launched, closed, gates, events, pool

    def test_every_chrome_is_opened_through_gate_and_closed(self):
        out, launched, closed, gates, _, pool = self.run_with(lambda name: None)
        self.assertTrue(all(j.result is not None for j in out))
        self.assertEqual(len(gates), len(launched))                   # mọi lần mở đều qua cổng giãn cách
        self.assertEqual(sorted(closed), sorted(n for n, _, _ in launched))   # mở bao nhiêu đóng bấy nhiêu
        self.assertTrue(all(h is False and "--window-position=-32000,-32000" in a for _, h, a in launched))
        self.assertEqual(pool.use, {})

    def test_launch_failure_moves_work_to_other_accounts(self):
        def launch(name):
            if name == "acc1":
                raise RuntimeError("Failed to launch chrome: user data dir in use")
        out, launched, closed, _, events, pool = self.run_with(launch)
        self.assertTrue(all(j.result is not None for j in out))
        self.assertTrue(any("[acc1] không mở được Chrome" in e for e in events))
        self.assertNotIn("acc1", closed)
        self.assertTrue(pool._resting("acc1", IMAGE))
        self.assertEqual(sum(1 for n, _, _ in launched if n == "acc1"), 1)   # không mở đi mở lại tài khoản hỏng
        self.assertEqual(pool.use, {})


class QueueBranchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "q.json"
        self.tasks = mock.Mock()
        self.tasks.running.return_value = None
        self.tasks.tasks = {}
        self.tasks.start_task.side_effect = (f"t{i}" for i in range(1, 99))

    def q(self, report=lambda p: (1, 1), args=lambda p: (["run"], "x")):
        return BatchQueue(self.tasks, self.file, args, report)

    def test_old_finished_items_get_retry_flag_even_when_report_crashes(self):
        items = [{"id": "a", "params": {"keyword": "x"}, "status": "partial", "task_id": "t0"},
                 {"id": "b", "params": {"keyword": "y"}, "status": "failed", "task_id": "t0"},
                 {"id": "c", "params": {"keyword": "z"}, "status": "running", "task_id": "t9"}]
        self.file.write_text(json.dumps({"paused": True, "items": items}), encoding="utf-8")

        def report(p):
            if p["keyword"] == "y":
                raise RuntimeError("dữ liệu cũ hỏng")
            return 1, 2, False
        q = self.q(report)
        got = {i["id"]: i for i in q.snapshot()["items"]}
        self.assertFalse(got["a"]["retryable"])
        self.assertTrue(got["b"]["retryable"])                         # không đọc được: cứ cho thử lại
        self.assertEqual((got["c"]["status"], got["c"]["params"].get("resume")), ("queued", True))

    def test_remove_move_clear_edge_cases(self):
        q = self.q()
        q.pause()
        a, b, c = (q.add({"keyword": k})["id"] for k in "abc")
        self.assertFalse(q.remove("khong-co"))
        self.assertFalse(q.move("khong-co", 1))
        self.assertFalse(q.move(a, -1))                                # đã ở đầu
        self.assertFalse(q.move(c, 1))                                 # đã ở cuối
        self.assertTrue(q.move(c, -1))
        self.assertEqual([i["params"]["keyword"] for i in q.snapshot()["items"]], ["a", "c", "b"])
        q.resume()
        self.assertFalse(q.remove(a))                                  # đang chạy: phải Dừng trước
        q.clear_finished()
        self.assertEqual(len(q.snapshot()["items"]), 3)                # chưa xong thì không bị dọn
        self.tasks.tasks = {"t1": mock.Mock(status="success")}
        q.tick()
        q.clear_finished()
        self.assertEqual([i["params"]["keyword"] for i in q.snapshot()["items"]], ["c", "b"])

    def test_background_loop_survives_errors(self):
        q = self.q()
        calls = []

        def tick():
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("lỗi tạm")
        q.tick = tick
        q.start(every=0.01)
        deadline = time.monotonic() + 5
        while len(calls) < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertGreaterEqual(len(calls), 6)                         # lỗi 2 vòng đầu không giết vòng chạy nền


class AiMockupBranchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {"projects_dir": str(self.root), "profiles_dir": str(self.root / "profiles"), "imagegen": {}}
        (self.root / "profiles" / "acc1").mkdir(parents=True)

    def test_tiny_or_unreadable_ai_image_is_rejected(self):
        f = self.root / "a.png"
        Image.new("RGB", (512, 512)).save(f)
        self.assertIn("nhỏ quá", ai_mockups.accept_mockup(f))
        f.write_bytes(b"not an image")
        with self.assertRaises(Exception):
            ai_mockups.accept_mockup(f)                                # run_jobs coi là lỗi -> vẽ lại

    def test_missing_code_mockup_is_not_sent_to_ai(self):
        c = tam.book(self.root)
        (layout.listing(c) / "03_three_open_spreads.jpg").unlink()
        self.assertNotIn("03_three_open_spreads", ai_mockups.pending(c))
        fake = tam.FakeRun()
        with mock.patch.object(driver, "run_jobs", fake):
            res = ai_mockups.ai_previews(c, self.cfg, on_event=lambda *_: None)
        self.assertNotIn("03_three_open_spreads", [j.id for j in fake.calls[0]])
        self.assertEqual(len(res["ai"]), 6)

    def test_missing_cover_art_keeps_code_cover(self):
        c = tam.book(self.root)
        (layout.raw(c) / "cover.png").unlink()
        logs, fake = [], tam.FakeRun()
        with mock.patch.object(driver, "run_jobs", fake):
            res = ai_mockups.ai_previews(c, self.cfg, on_event=logs.append)
        self.assertIn("01_front_cover_spiral", res["kept_code"])
        self.assertTrue(any("thiếu tranh bìa" in l for l in logs))

    def test_nothing_can_be_sent_returns_without_opening_chrome(self):
        c = tam.book(self.root)
        for n in ("cover.png", "m02.png", "m05.png", "m07.png", "m09.png", "m12.png"):
            (layout.raw(c) / n).unlink()
        for n in ("02_open_spread_flat", "03_three_open_spreads"):
            (layout.listing(c) / f"{n}.jpg").unlink()
        with mock.patch.object(driver, "run_jobs", mock.Mock(side_effect=AssertionError("không được mở Chrome"))):
            res = ai_mockups.ai_previews(c, self.cfg, on_event=lambda *_: None)
        self.assertEqual((res["ai"], sorted(res["kept_code"])),
                         ([], ["01_front_cover_spiral", "04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"]))

    def test_ai_step_crash_keeps_finished_book(self):
        """Bước ảnh quảng cáo AI nổ lỗi bất ngờ: cuốn vẫn xong với ảnh code ghép (pipeline bắt lỗi)."""
        c = tam.book(self.root)
        src = Path(pipeline.__file__).read_text(encoding="utf-8")
        self.assertIn("Không gen được ảnh quảng cáo AI", src)
        with mock.patch.object(driver, "run_jobs", mock.Mock(side_effect=RuntimeError("Chrome nổ"))):
            with self.assertRaises(RuntimeError):
                ai_mockups.ai_previews(c, self.cfg, on_event=lambda *_: None)
        self.assertEqual(len(list(layout.listing(c).glob("*.jpg"))), 8)   # ảnh code ghép còn nguyên


class AcceptImageTest(unittest.TestCase):
    def img(self, size):
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        Image.new("RGB", size, "white").save(tmp.name)
        return Path(tmp.name)

    def test_size_and_ratio_checks(self):
        self.assertIn("nhỏ quá", generate.accept_landscape(self.img((600, 400))))
        self.assertIn("sai tỉ lệ", generate.accept_landscape(self.img((1024, 1024))))
        self.assertIn("sai tỉ lệ", generate.accept_landscape(self.img((1024, 1536))))
        self.assertIsNone(generate.accept_landscape(self.img((1536, 1024))))
        self.assertIn("nhỏ quá", generate.accept_grid_page(self.img((800, 600)), 2027, 4))
        self.assertIn("sai tỉ lệ", generate.accept_grid_page(self.img((1024, 1024)), 2027, 4))
        self.assertIn("nhỏ quá", generate.accept_grid_background(self.img((600, 400))))

    def test_rotation_state_problems_do_not_break_image_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ["acc2", "acc3", "acc4"]
            bad = Path(tmp) / "no" / "dir" / "rot.json"
            self.assertEqual(generate.rotate_profiles(names, bad), names)       # không ghi được: vẫn chạy
            f = Path(tmp) / "rot.json"
            for junk in ("{cụt", "[]", '{"next": "x"}', ""):
                f.write_text(junk, encoding="utf-8")
                self.assertEqual(sorted(generate.rotate_profiles(names, f)), names, junk)
            self.assertEqual(generate.rotate_profiles(["only"], f), ["only"])


class BatchLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kdir = Path(self.tmp.name) / "kw"
        layout.ensure_system(self.kdir)

    def test_pid_alive(self):
        self.assertTrue(pipeline._pid_alive(os.getpid()))
        self.assertFalse(pipeline._pid_alive(0))
        self.assertFalse(pipeline._pid_alive(-5))
        self.assertFalse(pipeline._pid_alive(2 ** 22 + 12345))         # tiến trình không tồn tại

    def test_stale_or_corrupt_lock_is_taken_over(self):
        lock = pipeline._BatchLock(self.kdir, lambda *_: None, poll=0.01)
        for content in (json.dumps({"pid": 2 ** 22 + 12345}), "{cụt", "", json.dumps({"pid": 0})):
            lock.file.write_text(content, encoding="utf-8")
            done = threading.Event()
            t = threading.Thread(target=lambda: (lock.acquire(), done.set()), daemon=True)
            t.start()
            self.assertTrue(done.wait(5), f"kẹt vì khoá cũ: {content!r}")
            self.assertEqual(json.loads(lock.file.read_text(encoding="utf-8"))["pid"], os.getpid())
            lock.release()
            self.assertFalse(lock.file.exists())

    def test_second_run_waits_for_first_then_goes(self):
        logs = []
        a = pipeline._BatchLock(self.kdir, logs.append, poll=0.02)
        b = pipeline._BatchLock(self.kdir, logs.append, poll=0.02)
        a.acquire()
        got = threading.Event()
        threading.Thread(target=lambda: (b.acquire(), got.set()), daemon=True).start()
        self.assertFalse(got.wait(0.3))                                # lượt 2 phải chờ
        self.assertEqual(sum("đang chạy ở nơi khác" in l for l in logs), 1)
        a.release()
        self.assertTrue(got.wait(5))
        b.release()
        b.release()                                                    # trả 2 lần cũng không sao

    def test_live_lock_of_another_process_blocks(self):
        lock = pipeline._BatchLock(self.kdir, lambda *_: None, poll=0.02)
        lock.file.write_text(json.dumps({"pid": os.getppid()}), encoding="utf-8")   # tiến trình cha: đang sống
        got = threading.Event()
        threading.Thread(target=lambda: (lock.acquire(), got.set()), daemon=True).start()
        self.assertFalse(got.wait(0.4))
        lock.file.unlink()                                             # tiến trình kia xong, nhả khoá
        self.assertTrue(got.wait(5))
        lock.release()


class IdeationFailuresInBatchTest(unittest.TestCase):
    """Bước lên ý tưởng của batch hỏng: batch vẫn kết thúc gọn, có báo cáo + lý do, không treo."""

    def run_with(self, fake_ideation, n=2, **cfg):
        s = t40.sim(self, 990, n=6, cap=6, fault=0)
        s.cfg.update(cfg)
        with mock.patch.object(ideation, "run_ideation", fake_ideation):
            rows = s.run("ideas", n, timeout=60)
        batch = pipeline._load_batch(s.kdir("ideas"))
        tb.check_invariants(self, s)
        return rows, batch, s

    def test_chat_quota_gone_too_long(self):
        def fake(*a, **k):
            raise NoAccountLeft("hết lượt chat")
        rows, batch, _ = self.run_with(fake, quota_wait_s=0.05, quota_max_wait_h=0.00005)
        self.assertEqual(sum(r["ok"] for r in rows), 0)
        self.assertIn("hết lượt chat ở mọi tài khoản quá lâu", batch["errors"])
        self.assertTrue(batch["finished"])
        self.assertTrue(all(r.get("reason") for r in rows))

    def test_ideation_crash_is_recorded(self):
        def fake(*a, **k):
            raise ConnectionError("mất mạng giữa lúc lên ý tưởng")
        rows, batch, _ = self.run_with(fake)
        self.assertTrue(any("ConnectionError" in e for e in batch["errors"]))
        self.assertTrue(rows and not any(r["ok"] for r in rows))
        self.assertIn("mất mạng", rows[-1]["reason"])

    def test_two_empty_rounds_stop_the_loop(self):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return types.SimpleNamespace(concepts=[], failed=[])
        rows, batch, _ = self.run_with(fake)
        self.assertEqual(len(calls), 2)                                 # không quay vô tận
        self.assertTrue(any("2 lượt lên ý liền không ra cuốn mới" in e for e in batch["errors"]))

    def test_too_many_failed_ideas_stop_the_loop(self):
        calls = []

        def fake(*a, **k):
            calls.append(1)
            return types.SimpleNamespace(concepts=[], failed=[f"r{len(calls)}a1", f"r{len(calls)}a2"])
        rows, batch, _ = self.run_with(fake)
        self.assertLessEqual(len(calls), 3)
        self.assertTrue(any("quá nhiều ý tưởng hỏng" in e for e in batch["errors"]))
        self.assertEqual(len(batch["failed_ideas"]), 2 * len(calls))

    def test_first_round_ok_then_crash_keeps_finished_books(self):
        real = ideation.run_ideation
        calls = []

        def fake(*a, **k):
            calls.append(1)
            if len(calls) > 1:
                raise RuntimeError("ChatGPT sập")
            return real(*a, **{**k, "auto_pick": 1})
        rows, batch, s = self.run_with(fake, n=3)
        self.assertEqual(sum(r["ok"] for r in rows), 1)                # cuốn đã có ý tưởng vẫn được làm xong
        self.assertTrue(any("ChatGPT sập" in e for e in batch["errors"]))
        rows = s.run("ideas", 3, resume=True)                          # "Làm nốt phần thiếu" sau khi ChatGPT ổn lại
        self.assertEqual(sum(r["ok"] for r in rows), 3)
        self.assertEqual(len(s.books("ideas")), 3)


class PipelineBranchesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Path(self.tmp.name) / "Wall Calendar (Blank)" / "kw" / "Book"
        layout.ensure_system(self.c)
        from tests import fixtures
        layout.concept_file(self.c).write_text(json.dumps({**fixtures.concept(), "product": "wall_grid"}),
                                               encoding="utf-8")
        self.cfg = {"imagegen": {}, "projects_dir": self.tmp.name}

    def test_terminal_book_is_skipped_without_touching_chatgpt(self):
        pipeline._status(self.c, stage="ip_rejected", ok=False, terminal=True, reason="TM")
        with mock.patch.object(pipeline, "generate_concept", mock.Mock(side_effect=AssertionError)):
            st = pipeline.produce_images(self.c, self.cfg, on_event=lambda *_: None)
        self.assertEqual(st["stage"], "ip_rejected")
        self.assertEqual(pipeline.finish_book(self.c, self.cfg, on_event=lambda *_: None)["stage"], "ip_rejected")

    def test_anchor_refusal_drops_book(self):
        def gen(*a, **k):
            raise RuntimeError(f"không gen được ảnh neo: {pipeline.IP_REJECTED_MARK} nudity guardrails")
        with mock.patch.object(pipeline, "generate_concept", gen), \
                mock.patch.object(pipeline.plan, "write_plan", lambda d: None), \
                mock.patch.object(pipeline, "_BackgroundUpscaler", tb._NoUpscale):
            st = pipeline.produce_images(self.c, self.cfg, on_event=lambda *_: None)
        self.assertEqual((st["stage"], st["terminal"]), ("ip_rejected", True))
        self.assertIn("nudity", st["reason"])

    def test_anchor_other_error_is_not_swallowed_as_terminal(self):
        def gen(*a, **k):
            raise RuntimeError("không gen được ảnh neo: quá 420s chưa ra ảnh")
        with mock.patch.object(pipeline, "generate_concept", gen), \
                mock.patch.object(pipeline.plan, "write_plan", lambda d: None), \
                mock.patch.object(pipeline, "_BackgroundUpscaler", tb._NoUpscale):
            st = pipeline._safe_produce(self.c, self.cfg, on_event=lambda *_: None)
        self.assertEqual(st["stage"], "crash")
        self.assertNotIn("terminal", st)
        self.assertIn("ảnh neo", st["reason"])

    def test_background_upscaler_error_does_not_stop_image_step(self):
        logs = []
        with mock.patch.object(pipeline, "upscale_concept", mock.Mock(side_effect=RuntimeError("CUDA lỗi"))):
            with pipeline._BackgroundUpscaler(self.c, logs.append, poll_s=0.01):
                time.sleep(0.1)
        self.assertTrue(any("upscale song song lỗi" in l for l in logs))

    def test_render_is_not_current_when_files_missing_or_corrupt(self):
        from calforge import products
        concept = json.loads(layout.concept_file(self.c).read_text(encoding="utf-8"))
        for fid in products.get(concept)["formats"]:
            self.assertFalse(pipeline._render_is_current(self.c, fid))
        self.assertFalse(pipeline._listing_is_current(self.c))

    def test_wait_for_quota_with_broken_pool_falls_back(self):
        broken = mock.Mock(names=["a"])
        broken.alive_names.return_value = ["a"]
        broken.next_wake.side_effect = RuntimeError("pool hỏng")
        slept = []
        with mock.patch.object(poolmod, "peek_pool", lambda: broken), \
                mock.patch.object(pipeline.time, "sleep", slept.append):
            self.assertEqual(pipeline._wait_for_quota({"quota_wait_s": 60}, 0.0, lambda *_: None, "gen ảnh"), 60)
        self.assertEqual(slept, [60])


class PoolSmallBranchesTest(unittest.TestCase):
    def test_all_resting_and_reset(self):
        p = AccountPool(Path("."), ["a", "b"], cap=2, notify=lambda m: None)
        self.assertFalse(p.all_resting(IMAGE))
        p.rest("a", IMAGE, 60)
        p.rest("b", IMAGE, 60)
        self.assertTrue(p.all_resting(IMAGE))
        self.assertFalse(p.all_resting(CHAT))
        self.assertGreater(p.next_wake(IMAGE), 0)
        self.assertEqual(p.next_wake(CHAT), 0)
        with mock.patch.object(poolmod, "_POOL", p):
            poolmod.reset_pool()
            self.assertIsNone(poolmod.peek_pool())

    def test_planned_cap_with_unreadable_profiles_dir(self):
        with mock.patch.object(poolmod, "free_ram_gb", lambda: 64.0), \
                mock.patch("calforge.config.get_profiles_dir", mock.Mock(side_effect=OSError("no access"))):
            self.assertEqual(poolmod.planned_cap({"max_browsers": 9}), 9)

    def test_free_ram_fallback(self):
        with mock.patch.object(poolmod.os, "name", "posix"):
            self.assertEqual(poolmod.free_ram_gb(), 8.0)

    def test_broken_account_handed_back(self):
        """Tài khoản không mở được Chrome ở lượt trước mà được mượn lại: trả ngay, không kẹt."""
        opened = []

        @contextmanager
        def opener(profile):
            opened.append(profile)
            if profile == "acc1":
                raise RuntimeError("profile locked")
            yield object()

        class W:
            def __init__(self, *a, **k):
                pass

            def run_job(self, page, job):
                time.sleep(0.01)
                return job.out.with_suffix(".png")

        p = AccountPool(Path("."), ["acc1", "acc2"], cap=2, launch_gap_s=0, notify=lambda m: None)
        real_rest = p.rest
        p.rest = lambda name, role, seconds, why="": real_rest(name, role, 0, why)   # hết nghỉ ngay -> được mượn lại
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 9)]
        with mock.patch.object(driver, "_Worker", W):
            out = run_jobs(jobs, Path("."), p.names, on_event=lambda *_: None, pool=p, open_page=opener)
        self.assertTrue(all(j.result is not None for j in out))
        self.assertEqual(opened.count("acc1"), 1)
        self.assertEqual(p.use, {})


class HiddenChromeFilterTest(unittest.TestCase):
    """Chỉ ẩn Chrome NGẦM của tool; cửa sổ người dùng đang thu nhỏ (Windows báo toạ độ -32000) không được đụng."""

    def check(self, exe, iconic, normal_left):
        from calforge.llm import browser
        with mock.patch.object(browser, "_window_info", lambda u, h: (exe, iconic, normal_left)):
            return browser._is_our_hidden_chrome(None, 1)

    def test_filter(self):
        self.assertTrue(self.check("chrome.exe", False, -26214))          # Chrome ngầm của tool (màn hình 125%)
        self.assertTrue(self.check("chrome.exe", False, -32000))
        self.assertFalse(self.check("chrome.exe", True, 120))             # Chrome người dùng đang thu nhỏ
        self.assertFalse(self.check("claude.exe", True, 0))               # Claude (Electron) đang thu nhỏ
        self.assertFalse(self.check("claude.exe", False, -26214))         # app khác nền Chrome: không bao giờ đụng
        self.assertFalse(self.check("msedge.exe", False, -26214))
        self.assertFalse(self.check("chrome.exe", False, -1200))          # màn hình phụ bên trái: vẫn là màn hình thật


if __name__ == "__main__":
    unittest.main()
