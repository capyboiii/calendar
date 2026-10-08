"""LUỒNG XỬ LÝ LỖI của trang "Làm theo ảnh mẫu" (giống bộ test lỗi của trang chính): chạy hàng đợi THẬT (run_queue,
Book, run_stage, Accounts) với ChatGPT / Chrome giả có lỗi cài sẵn - hết lượt giữa chừng, tài khoản bị đăng xuất /
bị khoá, lỗi server, ChatGPT từ chối, Chrome không mở được, mọi tài khoản hết lượt, dừng giữa chừng, dựng sách lỗi,
item.json hỏng, nhiều cuốn song song trên 4 tài khoản Plus, thêm cuốn khi đang chạy."""
import json
import re
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge import layout
from calforge.clone import run, session, store
from calforge.imagegen.driver import NavError, QuotaExceeded, TempError, ThirdPartyIPRefused

from tests.test_clone import META, FakePool, distinct, png

PLUS = ["acc3", "acc4", "acc5", "acc6"]


class World:
    """ChatGPT giả dùng chung cho mọi phiên: ảnh artwork / bìa ngẫu nhiên khác nhau, trang lịch đúng tháng (OCR giả
    nhận ra), lỗi bơm vào theo quy tắc `faults(account, kind, n)` -> Exception | None."""

    def __init__(self, faults=None):
        self.faults = faults or (lambda acc, kind, n: None)
        self.lock = threading.Lock()
        self.n = 0
        self.pages: dict[bytes, int] = {}
        self.in_use: dict[str, int] = {}
        self.peak_same = 0
        self.used: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def seq(self):
        with self.lock:
            self.n += 1
            return self.n

    def grid(self, months):
        out = []
        for m in months:
            k = self.seq()
            data = png((k * 7 % 256, m * 19 % 256, k * 3 % 256))
            with self.lock:
                self.pages[data] = m
            out.append(data)
        return out

    def accept(self, path, year, month):
        return None if self.pages.get(Path(path).read_bytes()) == month else "lịch sai"


class FakeSession:
    def __init__(self, world: World, account: str):
        self.world, self.account = world, account
        self.page = object()
        self.w = mock.Mock()
        self.on_sent = None

    def open(self):
        w = self.world
        with w.lock:
            w.used.append(self.account)
        err = w.faults(self.account, "open", w.seq())
        if err:
            raise err

    def _fault(self, kind):
        return self.world.faults(self.account, kind, self.world.seq())

    def ask_images(self, prompt, want, attach=None):
        w = self.world
        with w.lock:
            w.calls.append((self.account, prompt[:40]))
        time.sleep(0.002)
        if "calendar grid page" in prompt or "more artwork" in prompt or "page you just made" in prompt:
            err = self._fault("grid")
            if isinstance(err, Exception) and not isinstance(err, session.Turn):
                if getattr(err, "partial", False):          # vẽ được nửa rồi mới lỗi
                    months = [int(x) for x in re.findall(r"CALL (\d+):", prompt)]
                    return session.Turn(w.grid(months[:len(months) // 2]), problem=err)
                raise err
            months = [int(x) for x in re.findall(r"CALL (\d+):", prompt)]
            return session.Turn(w.grid(months))
        kind = "cover" if "FRONT COVER" in prompt else "art"
        err = self._fault(kind)
        if err:
            if getattr(err, "partial", False):
                return session.Turn(distinct(want // 2, w.seq() * 17), problem=err)
            raise err
        return session.Turn(distinct(want, w.seq() * 17))

    def ask_text(self, prompt):
        err = self._fault("meta")
        if err:
            raise err
        return "```json\n" + json.dumps(META) + "\n```"


class Killed(BaseException):
    """Tiến trình bị tắt ngang."""


def partial(err):
    err.partial = True
    return err


def setup(tc, n_books=1, faults=None, plus=PLUS, finish_ok=True):
    tmp = tempfile.TemporaryDirectory()
    tc.addCleanup(tmp.cleanup)
    root = Path(tmp.name)
    cfg = {"projects_dir": str(root / "projects"), "profiles_dir": str(root / "prof"), "imagegen": {},
           "quota_max_wait_h": 0.0005}
    items = [store.add(cfg["projects_dir"], [(f"r{i}.png", png((i * 30, 40, 50))) for i in range(3)], group="err")
             for _ in range(n_books)]
    world = World(faults)
    pool = FakePool(plus)
    resting_until = {}

    def rest(name, role, s, why=""):
        resting_until[name] = time.monotonic() + min(s, 0.2) if s < 1000 else time.monotonic() + 3600
    pool.rest = rest
    pool._resting = lambda n, role: resting_until.get(n, 0) > time.monotonic()
    pool.resting = resting_until
    real_acquire = pool.acquire

    def acquire(role, only=None, prefer=None):
        if pool._resting(only, role):
            return None
        got = real_acquire(role, only=only)
        if got:
            with world.lock:
                world.in_use[got] = world.in_use.get(got, 0) + 1
                world.peak_same = max(world.peak_same, world.in_use[got])
        return got
    pool.acquire = acquire
    real_release = pool.release

    def release(name):
        with world.lock:
            world.in_use[name] = max(0, world.in_use.get(name, 0) - 1)
        real_release(name)
    pool.release = release
    pool.wait_change = lambda t: time.sleep(0.01)

    accts = run.Accounts(cfg, plus, on_event=lambda *_: None, pool=pool,
                         open_page=contextmanager(lambda name: (yield name)))
    finish = (lambda self, plus: {"ok": True, "stage": "listing"}) if finish_ok is True else finish_ok
    patches = [mock.patch.object(run.session, "Session", lambda page, pdir: FakeSession(world, Path(pdir).name)),
               mock.patch("calforge.imagegen.generate.accept_grid_page", world.accept),
               mock.patch.object(run.Book, "finish", finish)]
    for p in patches:
        p.start()
        tc.addCleanup(p.stop)
    ds = [store.root(cfg["projects_dir"]) / it["id"] for it in items]

    def go(stop=None):
        return run.run_queue(cfg, on_event=lambda *_: None, accts=accts, plus=plus, stop=stop)
    return cfg, ds, world, pool, go


def complete(tc, d):
    it = store.read(d)
    tc.assertEqual(it["status"], "done", it.get("reason"))
    book = Path(it["book"])
    for job in ["cover"] + [f"m{m:02d}" for m in range(1, 13)] + [f"g{m:02d}" for m in range(1, 13)]:
        tc.assertTrue(list(layout.raw(book).glob(job + ".*")), job)
    return book


class CloneErrorFlowsTest(unittest.TestCase):
    def test_quota_mid_artwork_resumes_on_another_account_without_redrawing(self):
        def faults(acc, kind, n):
            return partial(QuotaExceeded("You've hit the plus plan limit")) if acc == "acc3" and kind == "art" else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        complete(self, d)
        art_calls = [p for a, p in world.calls if not p.startswith(("I have attached 10 artwork", "Same rules"))]
        self.assertTrue(any(a == "acc3" for a, _ in world.calls))
        self.assertTrue(any("THIS TIME" in p or "I have attached reference" in p for p in art_calls))

    def test_logged_out_and_banned_accounts_are_dropped_and_work_continues(self):
        def faults(acc, kind, n):
            if acc == "acc3" and kind == "open":
                return NavError("tài khoản bị đăng xuất: trang ChatGPT đòi đăng nhập lại")
            if acc == "acc5" and kind == "grid":           # acc4 vẽ artwork, trang lịch sang acc5 (tài khoản khác)
                return NavError("tài khoản bị khoá: Your account has been deactivated")
            return None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        complete(self, d)
        self.assertEqual(sorted(pool.dropped), [("acc3", "logged_out"), ("acc5", "banned")])

    def test_server_error_storm_then_recovers(self):
        def faults(acc, kind, n):
            return TempError("ChatGPT báo lỗi: 'Internal server error'") if n < 6 else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        complete(self, d)
        self.assertFalse(pool.dropped)                                      # lỗi server không phải lỗi tài khoản

    def test_refusals_reject_only_that_book(self):
        bad = {}

        def faults(acc, kind, n):
            return None
        cfg, ds, world, pool, go = setup(self, n_books=3, faults=faults)
        bad_id = ds[1].name

        class RefusingSession(FakeSession):
            def ask_images(self, prompt, want, attach=None):
                if attach and any(bad_id in str(a) for a in attach):
                    bad[self.account] = bad.get(self.account, 0) + 1
                    raise ThirdPartyIPRefused("I can't create that, it may violate our content policies")
                return super().ask_images(prompt, want, attach)
        with mock.patch.object(run.session, "Session", lambda page, pdir: RefusingSession(world, Path(pdir).name)):
            go()
        self.assertEqual(store.read(ds[1])["status"], "rejected")
        self.assertEqual(sum(bad.values()), 3)                              # gửi 3 lần rồi bỏ cuốn
        complete(self, ds[0])
        complete(self, ds[2])

    def test_chrome_fails_to_open_on_one_account(self):
        def faults(acc, kind, n):
            return RuntimeError("Target page, context or browser has been closed") if acc in ("acc3", "acc4") and kind == "open" else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        complete(self, d)

    def test_all_plus_accounts_out_of_quota_marks_failed_then_rerun_finishes(self):
        state = {"broken": True}

        def faults(acc, kind, n):
            return QuotaExceeded("You've hit the plus plan limit") if state["broken"] and kind == "art" else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        with mock.patch.object(run, "MAX_SESSIONS", 2):
            go()
        it = store.read(d)
        self.assertEqual(it["status"], "failed")
        self.assertIn("hết lượt", it["reason"])
        state["broken"] = False
        pool.resting.clear()                                                # hết giờ nghỉ: tài khoản hồi lượt
        store.retry(cfg["projects_dir"], d.name)
        go()
        complete(self, d)

    def test_quota_partway_through_grid_keeps_finished_pages(self):
        def faults(acc, kind, n):
            return partial(QuotaExceeded("limit")) if kind == "grid" and n < 40 and acc in ("acc4",) else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        book = complete(self, d)
        prompts_seen = [p for _, p in world.calls]
        self.assertTrue(any(p.startswith("I have attached 1 finished calendar page") for p in prompts_seen))

    def test_finish_crash_marks_failed_and_rerun_only_finishes(self):
        calls = []

        def boom(self, plus):
            calls.append(1)
            if len(calls) == 1:
                raise OSError("đĩa đầy")
            return {"ok": True, "stage": "listing"}
        cfg, [d], world, pool, go = setup(self, finish_ok=boom)
        go()
        self.assertEqual(store.read(d)["status"], "failed")
        self.assertIn("đĩa đầy", store.read(d)["reason"])
        before = len(world.calls)
        store.retry(cfg["projects_dir"], d.name)
        go()
        complete(self, d)
        self.assertEqual(len(world.calls), before)                         # không gọi ChatGPT lại lần nào

    def test_stop_midway_then_resume(self):
        """Bấm Dừng = tool tắt hẳn tiến trình (taskkill) lúc đang vẽ trang lịch: item.json kẹt ở "running"."""
        state = {"killed": False}

        def faults(acc, kind, n):
            if kind == "grid" and not state["killed"]:
                state["killed"] = True
                raise Killed()
            return None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        with self.assertRaises(Killed):
            go()
        it = store.read(d)
        self.assertEqual(it["status"], "running")
        self.assertNotEqual(it["status"], "done")
        self.assertTrue(it.get("book"))                                     # phần artwork + bìa đã giữ lại
        go()
        complete(self, d)

    def test_corrupt_item_json_does_not_break_queue(self):
        cfg, ds, world, pool, go = setup(self, n_books=2)
        (ds[0] / "item.json").write_text("{hỏng", encoding="utf-8")
        bad = [i for i in store.items(cfg["projects_dir"]) if i["id"] == ds[0].name][0]
        self.assertEqual(bad["status"], "failed")                          # hiện ra để người dùng xoá
        self.assertIn("item.json hỏng", bad["reason"])
        go()
        complete(self, ds[1])

    def test_many_books_on_four_plus_accounts_never_share_an_account(self):
        def faults(acc, kind, n):
            return TempError("Something went wrong") if n % 11 == 0 else None
        cfg, ds, world, pool, go = setup(self, n_books=6, faults=faults)
        with mock.patch.object(run, "MAX_SESSIONS", 8):
            go()
        for d in ds:
            complete(self, d)
        self.assertEqual(world.peak_same, 1)                                # một tài khoản chỉ một việc một lúc
        self.assertTrue(set(world.used) <= set(PLUS))
        self.assertEqual(pool.use, {})

    def test_book_added_while_running_is_done_in_same_run(self):
        cfg, [d1], world, pool, go = setup(self, faults=None, plus=["acc3"])
        added = []

        def faults(acc, kind, n):
            if not added:
                added.append(store.add(cfg["projects_dir"], [("x.png", png((9, 99, 9)))], group="err"))
            return None
        world.faults = faults
        res = go()
        self.assertEqual(len(res), 2)
        complete(self, d1)
        complete(self, store.root(cfg["projects_dir"]) / added[0]["id"])

    def test_meta_quota_then_new_session_names_book(self):
        def faults(acc, kind, n):
            return QuotaExceeded("chat limit") if kind == "meta" and acc == "acc3" else None
        cfg, [d], world, pool, go = setup(self, faults=faults)
        go()
        book = complete(self, d)
        self.assertTrue(book.name.startswith("WCB-GC-"))


if __name__ == "__main__":
    unittest.main()


class CloneRedoTest(unittest.TestCase):
    def redo_with(self, answers):
        from calforge.clone import redo as R
        cfg, [d], world, pool, go = setup(self)
        go()
        book = complete(self, d)
        old = next(layout.raw(book).glob("m05.*")).read_bytes()
        log = []

        class S(FakeSession):
            def __init__(self, *a):
                super().__init__(*a)
                self.w._attach = lambda page, files: log.append(("attach", [Path(f).read_bytes() for f in files]))

            def ask_text(self, prompt):
                log.append(("text", prompt))
                return answers.pop(0)

            def ask_images(self, prompt, want, attach=None):
                log.append(("image", prompt))
                return session.Turn(distinct(1, 900))
        accts = run.Accounts(cfg, PLUS, on_event=lambda *_: None, pool=pool,
                             open_page=contextmanager(lambda name: (yield name)))
        with mock.patch.object(run.session, "Session", lambda page, pdir: S(world, Path(pdir).name)),                 mock.patch("calforge.pipeline.upscale_concept", lambda *a, **k: []),                 mock.patch("calforge.pipeline.finish_book", lambda *a, **k: {"ok": True, "stage": "listing"}),                 mock.patch.object(R.driver, "open_home", lambda page, url: log.append(("new_chat", url))):
            res = R.redo(book, ["m05"], cfg, on_event=lambda *_: None, accts=accts, plus=PLUS)
        return R, book, old, log, res

    DESC = ("```text\nA smiling woman in a red polka-dot dress holds a cherry pie in a sunny vintage kitchen, warm cream "
            "and cherry red palette, soft window light, retro gouache illustration. No text. Landscape 4:3, full bleed, "
            "no border, no frame, no watermark.\n```")

    def test_redo_describes_then_redraws_from_text_in_new_chat(self):
        R, book, old, log, res = self.redo_with([self.DESC])
        self.assertTrue(res["ok"])
        self.assertEqual(log[0], ("attach", [old]))                            # đính đúng ảnh đang lỗi
        self.assertEqual(log[1], ("text", R.DESCRIBE_PROMPT))                   # bước 1: chỉ hỏi chữ, tả ảnh
        self.assertEqual(log[2][0], "new_chat")                                 # chat mới, không còn ảnh cũ
        log.pop(2)
        self.assertEqual(log[2][0], "image")                                    # bước 2: vẽ từ đúng bản mô tả
        self.assertTrue(log[2][1].startswith(R.DRAW_PREFIX + "A smiling woman"))
        self.assertNotIn("```", log[2][1])
        self.assertEqual(len([x for x in log if x[0] == "attach"]), 1)          # bước vẽ không đính ảnh nào
        self.assertNotEqual(next(layout.raw(book).glob("m05.*")).read_bytes(), old)
        self.assertTrue(list((layout.tech(book) / "anh_cu").glob("m05-*")))  # ảnh cũ được cất
        self.assertIn("cherry pie", (layout.tech(book) / "mo_ta_m05.txt").read_text(encoding="utf-8"))

    def test_empty_description_keeps_old_image(self):
        R, book, old, log, res = self.redo_with(["sorry"] * 10)
        self.assertFalse(res["ok"])
        self.assertEqual(next(layout.raw(book).glob("m05.*")).read_bytes(), old)

    def test_grid_redo_keeps_dates_and_is_ocr_checked(self):
        from calforge.clone import redo as R
        self.assertIn("Do not add, remove or move any date", R.fix_prompt("g03"))
        self.assertIn("do not mention the mistakes", R.DESCRIBE_PROMPT)
        self.assertEqual(R.description_from("x\n```json\nA cat\n```"), "A cat")

    def test_redo_fails_puts_old_image_back(self):
        from calforge.clone import redo as R
        cfg, [d], world, pool, go = setup(self)
        go()
        book = complete(self, d)
        old = next(layout.raw(book).glob("cover.*")).read_bytes()

        class S(FakeSession):
            def ask_images(self, prompt, want, attach=None):
                raise TempError("ảnh không đạt")
        accts = run.Accounts(cfg, PLUS, on_event=lambda *_: None, pool=pool,
                             open_page=contextmanager(lambda name: (yield name)))
        with mock.patch.object(run.session, "Session", lambda page, pdir: S(world, Path(pdir).name)):
            res = R.redo(book, ["cover"], cfg, on_event=lambda *_: None, accts=accts, plus=PLUS)
        self.assertFalse(res["ok"])
        self.assertEqual(next(layout.raw(book).glob("cover.*")).read_bytes(), old)   # cuốn vẫn đủ trang như cũ

    def test_main_produce_does_not_use_main_prompts_for_clone_book(self):
        from calforge import pipeline
        cfg, [d], world, pool, go = setup(self)
        go()
        book = complete(self, d)
        next(layout.raw(book).glob("g07.*")).unlink()
        st = pipeline.produce_images(book, {**cfg, "imagegen": {}}, on_event=lambda *_: None)
        self.assertEqual(st["stage"], "images")
        self.assertIn("g07", st["reason"])


class CloneManyAccountsTest(unittest.TestCase):
    def test_twenty_plus_accounts_twenty_four_books_random_faults(self):
        """Như bộ test 40 tài khoản của trang chính: nhiều tài khoản Plus chạy song song, lỗi ngẫu nhiên (hết lượt
        giữa chừng, lỗi server, tài khoản bị đăng xuất) - đủ cuốn, không tài khoản nào làm 2 việc một lúc."""
        import random
        rnd = random.Random(42)
        lock = threading.Lock()
        plus = [f"acc{i}" for i in range(1, 21)]

        def faults(acc, kind, n):
            with lock:
                r = rnd.random()
            if acc == "acc7" and kind == "open":
                return NavError("tài khoản bị đăng xuất: trang ChatGPT đòi đăng nhập lại")
            if r < 0.04:
                return partial(QuotaExceeded("You've hit the plus plan limit"))
            if r < 0.10:
                return TempError("ChatGPT báo lỗi: 'Internal server error'")
            return None
        cfg, ds, world, pool, go = setup(self, n_books=24, faults=faults, plus=plus)
        with mock.patch.object(run, "MAX_SESSIONS", 12):
            go()
        for d in ds:
            complete(self, d)
        self.assertEqual(world.peak_same, 1)                               # một tài khoản chỉ một việc một lúc
        self.assertGreater(len(set(world.used)), 10)                       # thật sự chạy trải trên nhiều tài khoản
        self.assertIn(("acc7", "logged_out"), pool.dropped)
        self.assertEqual(pool.use, {})
