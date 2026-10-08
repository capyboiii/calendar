"""Phân luồng Clone sản phẩm khi có nhiều tài khoản + chạy song song với batch theo ý tưởng:
- một cuốn: trang lịch tháng 1-10 bắt đầu ngay khi đủ artwork 1-10, trên tài khoản KHÁC, trong lúc tài khoản kia vẽ
  artwork 11-12 / đặt tên / vẽ bìa;
- hai tiến trình (batch theo ý tưởng + clone) không bao giờ lấy trùng một tài khoản (file khoá trong profile);
- khi clone có việc, batch theo ý tưởng lấy tài khoản Free trước, để dành Plus cho clone;
- lượt clone không chặn hàng đợi batch theo ý tưởng và ngược lại."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge.clone import run, session, store
from calforge.llm.pool import LEASE, AccountPool

from tests.test_clone import distinct
from tests.test_clone_errors import FakeSession, World, complete, setup


class EarlyGridTest(unittest.TestCase):
    def test_grid_starts_on_second_account_while_first_still_draws(self):
        art_slow = threading.Event()
        timeline = []

        class Slow(FakeSession):
            def ask_images(self, prompt, want, attach=None):
                kind = "grid" if ("calendar grid page" in prompt or "more artwork" in prompt) else "art"
                timeline.append((time.monotonic(), self.account, kind, prompt[:30]))
                if kind == "art" and (prompt.startswith("Continue") or "FRONT COVER" in prompt):
                    art_slow.wait(3)                  # artwork 11-12 / bìa chậm: trang lịch phải chạy song song
                return super().ask_images(prompt, want, attach)

        cfg, [d], world, pool, go = setup(self, plus=["acc3", "acc4"])
        with mock.patch.object(run.session, "Session", lambda page, pdir: Slow(world, Path(pdir).name)), \
                mock.patch.object(run, "GRID_POLL_S", 0.05):
            t = threading.Thread(target=go)
            t.start()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not any(k == "grid" for _, _, k, _ in timeline):
                time.sleep(0.05)
            art_slow.set()
            t.join(30)
        grid_calls = [x for x in timeline if x[2] == "grid"]
        art_calls = [x for x in timeline if x[2] == "art"]
        self.assertTrue(grid_calls, "trang lịch không chạy")
        held = [x for x in art_calls if x[3].startswith("Continue")][0][0]   # lúc artwork 11-12 bắt đầu bị giữ
        # trang lịch bắt đầu trong lúc artwork 11-12 còn bị giữ (giữ tối đa 3 giây), không phải chờ artwork xong
        self.assertLess(grid_calls[0][0] - held, 2.5)
        self.assertNotEqual(grid_calls[0][1], art_calls[0][1])   # trên tài khoản khác
        book = complete(self, d)
        self.assertTrue(book.name.startswith("WCB-GC-"))  # ảnh của cả hai bước nằm đúng trong thư mục SKU
        self.assertFalse(list((d / "work").rglob("g*.png")))

    def test_grid_waits_in_session_for_art_11_12_then_continues(self):
        cfg, [d], world, pool, go = setup(self, plus=["acc3", "acc4"])
        with mock.patch.object(run, "GRID_POLL_S", 0.05):
            go()
        complete(self, d)

    def test_art_failure_while_grid_runs_marks_book_failed_once(self):
        def faults(acc, kind, n):
            return run.TempError("ảnh không đạt") if kind == "cover" else None
        cfg, [d], world, pool, go = setup(self, faults=faults, plus=["acc3", "acc4"])
        with mock.patch.object(run, "MAX_SESSIONS", 2), mock.patch.object(run, "GRID_POLL_S", 0.05):
            res = go()
        self.assertEqual(len(res), 1)
        it = store.read(d)
        self.assertEqual(it["status"], "failed")
        self.assertTrue(it["reason"])
        self.assertEqual(pool.use, {})

    def test_many_books_many_accounts_use_all_accounts(self):
        busy, peak, lock = set(), [0], threading.Lock()

        class Count(FakeSession):
            def ask_images(self, prompt, want, attach=None):
                with lock:
                    busy.add(self.account)
                    peak[0] = max(peak[0], len(busy))
                time.sleep(0.05)
                try:
                    return super().ask_images(prompt, want, attach)
                finally:
                    with lock:
                        busy.discard(self.account)

        plus = [f"acc{i}" for i in range(1, 9)]
        cfg, ds, world, pool, go = setup(self, n_books=4, plus=plus)
        with mock.patch.object(run.session, "Session", lambda page, pdir: Count(world, Path(pdir).name)), \
                mock.patch.object(run, "GRID_POLL_S", 0.05):
            go()
        for d in ds:
            complete(self, d)
        self.assertGreaterEqual(peak[0], 5)            # 4 cuốn x (artwork + trang lịch) chạy cùng lúc > 4 tài khoản


class LeaseTest(unittest.TestCase):
    def pools(self, tmp, names, **kw):
        for n in names:
            (Path(tmp) / n).mkdir(exist_ok=True)
        return AccountPool(Path(tmp), names, cap=10, leases=True, **kw)

    def test_two_processes_never_share_an_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            mine = self.pools(tmp, ["acc1", "acc2"])
            # tiến trình khác (còn sống) đang giữ acc1
            other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            self.addCleanup(other.kill)
            (Path(tmp) / "acc1" / LEASE).write_text(str(other.pid), encoding="utf-8")
            self.assertEqual(mine.acquire("image"), "acc2")
            self.assertIsNone(mine.acquire("image"))              # acc1 vẫn của tiến trình kia
            self.assertEqual((Path(tmp) / "acc2" / LEASE).read_text(encoding="utf-8"), str(os.getpid()))
            mine.release("acc2")
            self.assertFalse((Path(tmp) / "acc2" / LEASE).exists())
            other.kill()
            other.wait()
            self.assertEqual(mine.acquire("image", only="acc1"), "acc1")   # tiến trình kia tắt: khoá mồ côi được dọn

    def test_real_two_pools_race_for_one_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self.pools(tmp, ["acc1"])
            got = a.acquire("image")
            self.assertEqual(got, "acc1")
            # bộ điều phối của tiến trình khác: chạy bằng tiến trình con thật
            code = ("import sys; from pathlib import Path; from calforge.llm.pool import AccountPool;"
                    f"p = AccountPool(Path(r'{tmp}'), ['acc1'], cap=5, leases=True);"
                    "print(p.acquire('image'))")
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 cwd=str(Path(__file__).resolve().parents[1])).stdout.strip()
            self.assertEqual(out, "None")
            a.release("acc1")
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 cwd=str(Path(__file__).resolve().parents[1])).stdout.strip()
            self.assertEqual(out, "acc1")

    def test_free_accounts_first_when_clone_needs_plus(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.pools(tmp, ["acc1", "acc2", "acc3"], later=lambda: {"acc1", "acc2"})
            self.assertEqual(p.acquire("image"), "acc3")            # Free trước
            self.assertEqual(p.acquire("image"), "acc1")            # hết Free mới tới Plus
            self.assertEqual(p.acquire("image", only="acc2"), "acc2")   # clone hỏi đích danh: vẫn được

    def test_plus_saved_only_while_clone_queue_has_work(self):
        from calforge.llm import plan
        from calforge.llm.pool import _plus_saved_for_clone
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / "prof"
            for n, kind in (("acc1", "plus"), ("acc2", "free")):
                (pdir / n).mkdir(parents=True)
                plan.save(pdir / n, {"plan": kind, "label": kind, "active": True, "expires": "2030-01-01"})
            cfg = {"projects_dir": str(Path(tmp) / "projects"), "profiles_dir": str(pdir)}
            self.assertEqual(_plus_saved_for_clone(cfg)(), set())   # hàng đợi clone trống: không để dành
            store.add(cfg["projects_dir"], [("a.png", __import__("tests.test_clone", fromlist=["png"]).png())])
            with mock.patch.dict(os.environ, {"CALFORGE_CLONE_RUN": ""}):
                self.assertEqual(_plus_saved_for_clone(cfg)(), {"acc1"})
            with mock.patch.dict(os.environ, {"CALFORGE_CLONE_RUN": "1"}):
                self.assertEqual(_plus_saved_for_clone(cfg)(), set())   # chính tiến trình clone: không để dành


class TasksRunTogetherTest(unittest.TestCase):
    def test_clone_task_does_not_block_idea_batches_and_vice_versa(self):
        from calforge.ui.server import TaskManager
        tm = TaskManager()

        class T:
            def __init__(self, action):
                self.status, self.action, self.params = "running", action, {}
        tm.tasks = {"c": T("clone")}
        self.assertIsNone(tm.running())                            # hàng đợi theo ý tưởng vẫn chạy được
        self.assertIsNotNone(tm.running(include_clone=True))
        self.assertIsNotNone(tm.clone_running())                   # nhưng không mở lượt clone thứ hai
        tm.tasks = {"r": T("run")}
        self.assertIsNone(tm.clone_running())                      # batch theo ý tưởng đang chạy: clone vẫn mở được
        self.assertIsNotNone(tm.running())


if __name__ == "__main__":
    unittest.main()


class StoppedRunTest(unittest.TestCase):
    def test_stale_running_items_become_failed_and_removable(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tests.test_clone import png
            it = store.add(tmp, [("a.png", png())])
            d = store.root(tmp) / it["id"]
            store.write(d, status="running", stage="vẽ artwork (0/12)")
            with self.assertRaises(ValueError):                      # lượt clone còn chạy thật: không cho bỏ
                store.remove(tmp, it["id"], running_now=True)
            self.assertEqual(store.mark_stopped(tmp), 1)             # lượt clone đã dừng: về "Bị dở"
            self.assertEqual(store.read(d)["status"], "failed")
            self.assertIn("đã dừng", store.read(d)["reason"])
            store.write(d, status="running")
            store.remove(tmp, it["id"], running_now=False)           # dấu "running" cũ: bỏ được
            self.assertFalse(d.exists())


class NetworkErrorTest(unittest.TestCase):
    def test_light_copy_is_small_jpeg_and_cached(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "_he_thong" / "anh_ai"
            raw.mkdir(parents=True)
            src = raw / "m01.png"
            import random
            rnd = random.Random(1)
            im = Image.new("RGB", (1536, 1152))
            im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(1536 * 1152)])
            im.save(src)
            light = session.light_copy(src)
            self.assertEqual(light.suffix, ".jpg")
            self.assertEqual(light.parent, Path(tmp) / "_he_thong" / "ky_thuat" / "dinh_kem")
            self.assertLess(light.stat().st_size, src.stat().st_size)
            with Image.open(light) as j:
                self.assertEqual(max(j.size), 1536 if max(j.size) <= 1600 else 1600)
            self.assertEqual(session.light_copy(src), light)              # dùng lại bản đã có
            self.assertEqual(sorted(p.name for p in raw.iterdir()), ["m01.png"])   # không lẫn vào anh_ai

    def test_attach_retries_then_reports_network_error(self):
        from calforge.imagegen.driver import NavError, TempError
        s = session.Session(mock.Mock(), Path("p"))
        calls = []

        def flaky(page, files):
            calls.append(files)
            if len(calls) == 1:
                raise TempError("không đính kèm được ảnh neo")
        s.w._attach = flaky
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.jpg"
            f.write_bytes(b"x")
            s.attach([f])                                                  # lần 2 được: không báo lỗi
            self.assertEqual(len(calls), 2)
            s.w._attach = mock.Mock(side_effect=TempError("không đính kèm được ảnh neo"))
            with self.assertRaises(NavError):                              # vẫn không được: lỗi mạng, đổi tài khoản
                s.attach([f])

    def test_network_errors_switch_account_without_failing_book(self):
        from calforge.imagegen.driver import NavError
        n = []

        def faults(acc, kind, k):
            if kind == "grid" and len(n) < 5:
                n.append(acc)
                return NavError("không đính kèm được ảnh (mạng chậm / tải ảnh lên lỗi)")
            if kind == "art" and k == 2:
                return TimeoutError("Page.goto: Timeout 90000ms exceeded")
            return None
        cfg, [d], world, pool, go = setup(self, faults=faults, plus=["acc3", "acc4", "acc5"])
        with mock.patch.object(run, "GRID_POLL_S", 0.05):
            go()
        complete(self, d)                                                  # 5 lần lỗi mạng: vẫn xong cuốn
        self.assertTrue(run._network_error("TimeoutError: Page.goto: Timeout 90000ms exceeded"))
        self.assertTrue(run._network_error("Error: net::ERR_CONNECTION_RESET"))
        self.assertFalse(run._network_error("ảnh không đạt: sai tỉ lệ"))


class ProgressTest(unittest.TestCase):
    def test_long_turn_reports_progress_every_minute(self):
        from tests.test_clone import CollectTest, state
        c = CollectTest()
        seen = []
        orig = session.Session.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            self.progress = lambda got, want, busy, secs: seen.append((got, want, busy, secs))
        with mock.patch.object(session.Session, "__init__", init):
            turn = c.collect(lambda t: state(busy=t < 400, srcs=[f"blob:{i}" for i in range(min(10, int(t // 40)))]), 10)
        self.assertEqual(len(turn.images), 10)
        self.assertGreaterEqual(len(seen), 5)                   # ~7 phút chờ: báo ít nhất 5 lần
        self.assertTrue(any(0 < g < 10 for g, *_ in seen))      # thấy số ảnh tăng dần


class ChatModeTest(unittest.TestCase):
    def test_switches_from_work_back_to_chat(self):
        state = {"chat": False}
        page = mock.Mock()
        page.evaluate.side_effect = lambda js: {"has": True, "chat": state["chat"]}
        page.locator.return_value.first.click.side_effect = lambda **k: state.update(chat=True)
        self.assertEqual(session.ensure_chat_mode(page), "switched")
        self.assertEqual(session.ensure_chat_mode(page), "")                 # đã ở Chat: không bấm gì
        page.evaluate.side_effect = lambda js: {"has": False}
        self.assertEqual(session.ensure_chat_mode(page), "")                 # tài khoản không có công tắc
        page.evaluate.side_effect = RuntimeError("Target closed")
        self.assertEqual(session.ensure_chat_mode(page), "failed")           # lỗi: không chặn việc vẽ
        self.assertIn("aria-pressed", session.MODE_JS)

    def test_only_clone_code_switches_mode(self):
        from calforge.imagegen import driver
        from calforge.llm import chatgpt_web
        self.assertFalse(hasattr(driver, "ensure_chat_mode"))               # trang chính không đổi
        self.assertNotIn("Composer mode", Path(chatgpt_web.__file__).read_text(encoding="utf-8"))
