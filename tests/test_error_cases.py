"""CÁC TRƯỜNG HỢP LỖI CÒN LẠI (ngoài những gì test_workflow_full / test_forty_accounts / test_dead_accounts đã phủ):

- file trạng thái hỏng / cụt (tắt máy lúc đang ghi), hết đĩa, không ghi được;
- ảnh tải về hỏng, không đính kèm được ảnh, lỗi lúc lưu ảnh;
- lỗi bất ngờ trong từng bước của một cuốn (vẽ, hậu kỳ) không được giết batch;
- hàng đợi: file hỏng, tác vụ sập, tham số xấu, đường dẫn ra ngoài thư mục projects;
- "BÃO LỖI": batch giả lập 40 tài khoản với MỌI loại lỗi cùng lúc (hết lượt, bị chặn 429, lỗi trang, Chrome sập,
  tài khoản bị đăng xuất / bị khoá, ChatGPT từ chối rồi qua, ảnh hỏng, hết đĩa thoáng qua, hậu kỳ sập).
"""
import json
import random
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import cli, layout, pipeline  # noqa: F401 - cli đặt stdout UTF-8 như lúc chạy thật
from calforge.imagegen import ai_mockups, driver, plan
from calforge.imagegen.driver import (GenJob, NavError, QuotaExceeded, Refused, TempError, ThirdPartyIPRefused,
                                      run_jobs)
from calforge.llm import pool as poolmod
from calforge.llm.pool import AccountPool
from calforge.ui import server
from calforge.ui.batch_queue import BatchQueue

from tests import fixtures
from tests import test_batch_simulation as tb
from tests import test_forty_accounts as t40
from tests import test_workflow_full as twf

REAL_WORKER = driver._Worker
ADULT = twf.ADULT


def make_book(root: Path, name="Book") -> Path:
    c = root / "Wall Calendar (Blank)" / "kw" / name
    layout.ensure_system(c)
    layout.concept_file(c).write_text(json.dumps({**fixtures.concept(), "product": "wall_grid"}), encoding="utf-8")
    return c


class BrokenStateFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_corrupt_status_is_treated_as_missing_and_can_be_rewritten(self):
        c = make_book(self.root)
        for junk in ('{"stage": "ima', "", "null", "[1, 2]", "\x00\x00\x00"):
            layout.status_file(c).write_text(junk, encoding="utf-8")
            self.assertFalse(pipeline._finished_ok(c), junk)
            self.assertFalse(pipeline.needs_finishing(c), junk)
            st = pipeline._status(c, stage="images", ok=False, reason="x")     # ghi đè được, không sập
            self.assertEqual(st["stage"], "images")
            self.assertEqual(json.loads(layout.status_file(c).read_text(encoding="utf-8"))["reason"], "x")

    def test_status_write_is_atomic(self):
        c = make_book(self.root)
        pipeline._status(c, stage="listing", ok=True)
        real = Path.write_text

        def half_write(self, data, *a, **k):
            if self.name.endswith(".tmp"):
                real(self, data[: len(data) // 2], *a, **k)
                raise OSError(28, "No space left on device")
            return real(self, data, *a, **k)

        with mock.patch.object(Path, "write_text", half_write):
            with self.assertRaises(OSError):
                pipeline._status(c, stage="crash", ok=False, reason="y")
        st = json.loads(layout.status_file(c).read_text(encoding="utf-8"))     # file cũ còn nguyên, không bị cụt
        self.assertEqual((st["stage"], st["ok"]), ("listing", True))
        self.assertEqual(list(layout.status_file(c).parent.glob("*.tmp")), [])  # không để lại file tạm

    def test_crash_with_unwritable_status_does_not_kill_batch(self):
        c = make_book(self.root)

        def boom(cdir, cfg, on_event=print, **kw):
            raise RuntimeError("render crashed")
        logs = []
        with mock.patch.object(pipeline, "_write_json", mock.Mock(side_effect=OSError(28, "No space left on device"))):
            st = pipeline._safe_call(boom, c, {}, logs.append)
        self.assertEqual((st["stage"], st["ok"]), ("crash", False))
        self.assertIn("render crashed", st["reason"])
        self.assertTrue(any("không ghi được trạng thái" in l for l in logs))

    def test_corrupt_concept_only_breaks_that_book(self):
        c = make_book(self.root)
        layout.concept_file(c).write_text('{"title": "cụt', encoding="utf-8")
        st = pipeline._safe_call(pipeline.finish_book, c, {"imagegen": {}}, lambda *_: None)
        self.assertEqual((st["stage"], st["ok"]), ("crash", False))
        self.assertTrue(st.get("traceback"))
        self.assertFalse(pipeline.needs_finishing(c))

    def test_corrupt_batch_file_and_atomic_batch_save(self):
        kdir = self.root / "Wall Calendar (Blank)" / "kw"
        batch = {"target": 2, "product": "wall_grid", "concepts": ["a"], "failed_ideas": [], "errors": [],
                 "started": "x", "finished": ""}
        pipeline._save_batch(kdir, batch)
        self.assertEqual(pipeline._load_batch(kdir)["concepts"], ["a"])
        real = Path.write_text

        def half_write(self, data, *a, **k):
            if self.name.endswith(".tmp"):
                real(self, data[:10], *a, **k)
                raise OSError(28, "No space left on device")
            return real(self, data, *a, **k)
        with mock.patch.object(Path, "write_text", half_write):
            with self.assertRaises(OSError):
                pipeline._save_batch(kdir, {**batch, "concepts": ["a", "b"]})
        self.assertEqual(pipeline._load_batch(kdir)["concepts"], ["a"])        # batch cũ còn nguyên -> không sinh cuốn trùng
        pipeline._batch_file(kdir).write_text("{cụt", encoding="utf-8")
        self.assertIsNone(pipeline._load_batch(kdir))
        self.assertEqual(server._read_batch(kdir), {})

    def test_corrupt_queue_file_starts_empty_and_keeps_working(self):
        f = self.root / ".hang_doi.json"
        f.write_text('{"items": [{"id": "q1", "par', encoding="utf-8")
        tasks = mock.Mock()
        tasks.running.return_value = None
        tasks.tasks = {}
        tasks.start_task.return_value = "t1"
        q = BatchQueue(tasks, f, lambda p: (["run"], "x"), lambda p: (1, 1))
        self.assertEqual(q.snapshot()["items"], [])
        q.add({"keyword": "cats"})
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["items"][0]["status"], "running")

    def test_queue_survives_task_table_losing_the_task(self):
        """Tác vụ biến mất khỏi bảng (tool khởi động lại giữa chừng): việc đó tính là lỗi, hàng đợi đi tiếp."""
        tasks = mock.Mock()
        tasks.running.return_value = None
        tasks.tasks = {}
        tasks.start_task.side_effect = ["t1", "t2"]
        q = BatchQueue(tasks, self.root / ".q.json", lambda p: (["run"], "x"), lambda p: (0, 1))
        q.add({"keyword": "a"})
        q.add({"keyword": "b"})                                               # lần bấm này cũng chạy 1 vòng hàng đợi
        st = [i["status"] for i in q.snapshot()["items"]]
        self.assertEqual(st, ["failed", "running"])

    def test_queue_loop_survives_report_crash(self):
        tasks = mock.Mock()
        tasks.running.return_value = None
        done = mock.Mock(status="success")
        tasks.tasks = {"t1": done}
        tasks.start_task.return_value = "t1"
        q = BatchQueue(tasks, self.root / ".q2.json", lambda p: (["run"], "x"),
                       mock.Mock(side_effect=RuntimeError("báo cáo hỏng")))
        q.add({"keyword": "a"})
        with self.assertRaises(RuntimeError):
            q.tick()                                                        # tick lỗi...
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()
        self.assertEqual(q.snapshot()["items"][0]["status"], "running")      # ...nhưng trạng thái không bị hỏng

    def test_corrupt_mockup_state_and_dead_marker(self):
        c = make_book(self.root)
        layout.tech(c).mkdir(parents=True, exist_ok=True)
        layout.tech(c, "mockup_ai.json").write_text("{cụt", encoding="utf-8")
        self.assertEqual(ai_mockups._load(c), {})
        d = self.root / "acc1"
        d.mkdir()
        (d / poolmod.DEAD_MARKER).write_text("{cụt", encoding="utf-8")
        self.assertIsNone(poolmod.read_dead(d))
        (d / poolmod.DEAD_MARKER).write_text("[]", encoding="utf-8")
        self.assertIsNone(poolmod.read_dead(d))
        self.assertEqual(AccountPool(self.root, ["acc1"], cap=1, notify=lambda m: None).dead, {})

    def test_pool_state_file_unwritable_is_harmless(self):
        p = AccountPool(self.root, ["acc1", "acc2"], cap=2, state_file=self.root / "no" / "such" / "dir" / "s.json",
                        notify=lambda m: None)
        self.assertEqual(p.acquire(poolmod.IMAGE), "acc1")
        p.rest("acc2", poolmod.IMAGE, 5, "x")
        p.release("acc1")
        self.assertEqual(p.use, {})


class ServerInputTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()
        self.book = make_book(self.root / "projects")
        self.outside = make_book(self.root / "projects_evil")               # cùng tiền tố tên, nằm NGOÀI projects
        cfg = {"projects_dir": str(self.root / "projects")}
        p = mock.patch.object(server.config, "load", lambda: dict(cfg))
        p.start()
        self.addCleanup(p.stop)

    def test_only_books_inside_projects_are_accepted(self):
        self.assertEqual(server._book_arg({"concept": str(self.book)}), self.book.resolve())
        for bad in (str(self.outside), str(self.book / ".." / ".." / ".." / ".." / "projects_evil"), "", "C:/Windows",
                    str(self.book.parent), str(self.book) + "/../../nope"):
            with self.assertRaises(ValueError, msg=bad):
                server._book_arg({"concept": bad})

    def test_bad_queue_params_are_rejected_at_once(self):
        for params in ({}, {"keyword": ""}, {"keyword": "   "}, {"action": "produce"}, {"action": "redo", "concept": str(self.book)},
                       {"action": "redo", "concept": str(self.book), "pages": ["m99"]},
                       {"action": "finish", "concept": "nope"}, {"keyword": "x", "family": "khong_co"}):
            with self.assertRaises((ValueError, OSError), msg=params):
                server.run_args(params)


class ImageDataErrorsTest(unittest.TestCase):
    """run_job thật: dữ liệu ảnh tải về hỏng / QC loại / không đính kèm được."""

    def run_job(self, data: bytes, accept=None, attach=None):
        import base64
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raw = Path(tmp.name) / "_he_thong" / "anh_ai"
        raw.mkdir(parents=True)
        job = GenJob("m03", "PROMPT", raw / "m03", attach or [], accept)
        w = REAL_WORKER(Path("acc1"), "hidden", 30)
        page = mock.Mock()
        with mock.patch.object(driver, "open_home"), mock.patch.object(w, "_find"), \
                mock.patch.object(w, "_send", return_value=dict(twf.BEFORE)), \
                mock.patch.object(w, "_wait_image", return_value="blob:x"), \
                mock.patch.object(driver, "_eval", return_value=base64.b64encode(data).decode()), \
                mock.patch.object(driver, "RateWatch"):
            try:
                return w.run_job(page, job), raw, None
            except Exception as e:  # noqa: BLE001
                return None, raw, e

    def png(self, size=(1536, 1024)):
        import io
        buf = io.BytesIO()
        Image.new("RGB", size, "red").save(buf, "PNG")
        return buf.getvalue()

    def test_good_image_is_saved(self):
        out, raw, err = self.run_job(self.png(), accept=lambda p: None)
        self.assertIsNone(err)
        self.assertEqual(out.name, "m03.png")
        self.assertEqual(plan.job_done(raw.parent.parent, "m03"), out)

    def test_rejected_image_is_kept_aside_not_used(self):
        out, raw, err = self.run_job(self.png(), accept=lambda p: "lịch sai: thiếu ngày 15")
        self.assertIsInstance(err, TempError)
        self.assertIsNone(plan.job_done(raw.parent.parent, "m03"))            # cuốn không dùng ảnh bị loại
        self.assertEqual([p.name for p in (raw.parent / "ky_thuat" / "anh_bi_loai").iterdir()], ["m03-attempt0.png"])

    def test_garbage_download_is_not_accepted_as_an_image(self):
        from calforge.imagegen.generate import accept_landscape
        out, raw, err = self.run_job(b"<html>error 502</html>", accept=accept_landscape)
        self.assertIsNotNone(err)                                              # lỗi -> run_jobs sẽ vẽ lại
        self.assertIsNone(plan.job_done(raw.parent.parent, "m03"))            # không có file ảnh rác nào được tính là xong

    def test_empty_download(self):
        from calforge.imagegen.generate import accept_landscape
        out, raw, err = self.run_job(b"", accept=accept_landscape)
        self.assertIsNotNone(err)
        self.assertIsNone(plan.job_done(raw.parent.parent, "m03"))

    def test_attach_failure_is_retryable(self):
        w = REAL_WORKER(Path("acc1"), "hidden", 30)
        page = mock.MagicMock()
        page.locator.return_value.all.return_value = []                       # không có ô chọn file nào dùng được
        with self.assertRaises(TempError):
            w._attach(page, [Path("anchor_swatch.png")])


@contextmanager
def opener(profile):
    yield object()


class RunJobsOddErrorsTest(unittest.TestCase):
    def run_script(self, script, n=3, max_attempts=3, jobs=None):
        calls = []

        class W:
            def __init__(self, profile_dir, *a, **k):
                self.name = Path(profile_dir).name

            def run_job(self, page, job):
                calls.append((job.id, self.name))
                step = script(job, sum(1 for c in calls if c[0] == job.id), self.name)
                if isinstance(step, BaseException):
                    raise step
                return job.out.with_suffix(".png")

        pool = AccountPool(Path("."), [f"acc{i}" for i in range(1, n + 1)], cap=n, launch_gap_s=0,
                           notify=lambda m: None)
        pool.rest_s = 0.2
        jobs = jobs or [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 7)]
        events = []
        with mock.patch.object(driver, "_Worker", W), mock.patch.object(driver, "NAV_REST_S", 0):
            out = run_jobs(jobs, Path("."), pool.names, max_attempts=max_attempts, on_event=events.append, pool=pool,
                           open_page=opener)
        self.assertEqual(pool.use, {}, "chưa trả hết tài khoản")
        return out, calls, events, pool

    def test_disk_full_while_saving_is_retried_then_reported(self):
        out, calls, events, _ = self.run_script(lambda j, k, a: OSError(28, "No space left on device"))
        self.assertTrue(all(j.result is None and "No space left" in j.error for j in out))
        self.assertTrue(all(j.attempts == 3 for j in out))
        out, _, _, _ = self.run_script(lambda j, k, a: OSError(28, "No space left on device") if k == 1 else None)
        self.assertTrue(all(j.result is not None for j in out))               # hết đĩa thoáng qua: lần sau xong

    def test_every_kind_of_error_on_one_page_never_hangs(self):
        errors = [QuotaExceeded("limit"), NavError("net::ERR"), TempError("ảnh không đạt"), RuntimeError("Target closed"),
                  ThirdPartyIPRefused(ADULT), OSError(13, "Permission denied"), KeyError("src"), ValueError("bad"),
                  NavError("net::ERR"), TempError("quá 420s chưa ra ảnh")]

        def script(job, k, acc):
            return errors[(k - 1) % len(errors)] if job.id == "m01" and k <= 9 else None
        t0 = time.monotonic()
        out, calls, events, _ = self.run_script(script, n=4, max_attempts=6)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertTrue(all(j.result is not None or j.error for j in out))
        self.assertTrue(all(j.result is not None for j in out if j.id != "m01"))

    def test_worker_thread_dying_does_not_lose_jobs(self):
        """Mở Chrome nổ ngay sau khi nhận việc đầu: việc đó không được mất, tài khoản khác làm nốt."""
        state = {"n": 0}

        @contextmanager
        def flaky_open(profile):
            state["n"] += 1
            if state["n"] <= 2:
                raise RuntimeError("Chrome crashed on launch")
            yield object()

        class W:
            def __init__(self, *a, **k):
                pass

            def run_job(self, page, job):
                return job.out.with_suffix(".png")

        pool = AccountPool(Path("."), [f"acc{i}" for i in range(1, 6)], cap=5, launch_gap_s=0, notify=lambda m: None)
        jobs = [GenJob(f"m{i:02d}", "p", Path(f"m{i:02d}")) for i in range(1, 9)]
        with mock.patch.object(driver, "_Worker", W):
            out = run_jobs(jobs, Path("."), pool.names, on_event=lambda *_: None, pool=pool, open_page=flaky_open)
        self.assertTrue(all(j.result is not None for j in out))
        self.assertEqual(pool.use, {})

    def test_refusal_mixed_with_other_errors_counts_separately(self):
        seq = [ThirdPartyIPRefused(ADULT), TempError("ảnh không đạt"), ThirdPartyIPRefused(ADULT), None]
        out, calls, events, _ = self.run_script(lambda j, k, a: seq[k - 1] if j.id == "m02" else None, max_attempts=2)
        by = {j.id: j for j in out}
        self.assertIsNotNone(by["m02"].result)                               # 2 lần từ chối + 1 lần QC loại vẫn chưa hết lượt
        self.assertEqual(by["m02"].refusals, 2)
        self.assertFalse(any("BỎ CUỐN" in e for e in events))


class BookStepErrorsTest(unittest.TestCase):
    """Lỗi bất ngờ ở từng bước của một cuốn: ghi lý do vào status, không ném ra ngoài."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = make_book(Path(self.tmp.name))
        self.cfg = {"imagegen": {}, "projects_dir": self.tmp.name, "quota_wait_s": 0, "quota_max_wait_h": 0}

    def produce(self, gen):
        with mock.patch.object(pipeline, "generate_concept", gen), \
                mock.patch.object(pipeline.plan, "write_plan", lambda d: None), \
                mock.patch.object(pipeline, "upscale_concept", lambda *a, **k: []), \
                mock.patch.object(pipeline, "_BackgroundUpscaler", tb._NoUpscale):
            return pipeline._safe_call(lambda c, g, on_event: pipeline.produce_images(c, g, on_event=on_event) or {"ok": True},
                                       self.c, self.cfg, lambda *_: None)

    def test_missing_pages_are_reported_with_reason(self):
        st = self.produce(lambda *a, **k: {"missing": ["m03", "g07"], "failed": {"m03": "bị từ chối: content policy",
                                                                               "g07": "quá 420s chưa ra ảnh"},
                                           "drift_flags": []})
        self.assertEqual((st["stage"], st["ok"]), ("images", False))
        self.assertIn("m03", st["reason"])
        self.assertNotIn("terminal", st)

    def test_unexpected_exception_in_image_step(self):
        def gen(*a, **k):
            raise MemoryError("out of memory")
        st = self.produce(gen)
        self.assertEqual((st["stage"], st["ok"]), ("crash", False))
        self.assertIn("MemoryError", st["reason"])

    def test_upscale_failure_is_a_crash_of_that_book_only(self):
        with mock.patch.object(pipeline, "generate_concept", lambda *a, **k: {"missing": [], "failed": {}, "drift_flags": []}), \
                mock.patch.object(pipeline.plan, "write_plan", lambda d: None), \
                mock.patch.object(pipeline, "_BackgroundUpscaler", tb._NoUpscale), \
                mock.patch.object(pipeline, "upscale_concept", mock.Mock(side_effect=RuntimeError("CUDA out of memory"))):
            st = pipeline._safe_call(lambda c, g, on_event: pipeline.produce_images(c, g, on_event=on_event) or {"ok": True},
                                     self.c, self.cfg, lambda *_: None)
        self.assertEqual(st["stage"], "crash")
        self.assertIn("CUDA", st["reason"])

    def test_quota_wait_gives_up_cleanly(self):
        from calforge.imagegen.generate import QUOTA_MARK
        st = self.produce(lambda *a, **k: {"missing": ["m01"], "failed": {"m01": QUOTA_MARK}, "drift_flags": []})
        self.assertEqual((st["stage"], st["ok"]), ("images", False))


# ------------------------------------------------------------------ BÃO LỖI: mọi loại lỗi cùng lúc
class ChaosBatchTest(unittest.TestCase):
    def chaos_worker(self, s, rng, counts, logged_out, banned):
        base, lock = driver._Worker, threading.Lock()
        refused_once = set()

        class Chaos(base):
            def run_job(self, page, job):
                with lock:
                    r = rng.random()
                    key = (str(job.out), job.id)
                    first_refusal = r < .05 and key not in refused_once
                    if first_refusal:
                        refused_once.add(key)
                if self.name in logged_out:
                    counts["logged_out"] += 1
                    raise NavError(f"{driver.LOGGED_OUT}: trang ChatGPT đòi đăng nhập lại")
                if self.name in banned:
                    counts["banned"] += 1
                    raise NavError(f"{driver.BANNED}: Your account has been deactivated")
                if first_refusal:
                    counts["refusal"] += 1
                    raise ThirdPartyIPRefused(ADULT)                       # bắt nhầm: gửi lại thì qua
                if r < .09:
                    counts["429"] += 1
                    raise QuotaExceeded("HTTP 429 too many requests")
                if r < .12:
                    counts["disk"] += 1
                    raise OSError(28, "No space left on device")
                if r < .15:
                    counts["garbage"] += 1
                    raise TempError("ảnh không đạt: không đọc được ảnh")
                if r < .17:
                    counts["crash"] += 1
                    raise RuntimeError("Target page, context or browser has been closed")
                return super().run_job(page, job)
        return mock.patch.object(driver, "_Worker", Chaos)

    def test_everything_goes_wrong_at_once(self):
        """40 tài khoản, 3 chủ đề, mọi loại lỗi dày đặc: không treo, không dùng chung tài khoản, cuốn hỏng có lý do,
        bấm "Làm nốt" vài lần là đủ cuốn, không sinh cuốn trùng."""
        for seed in range(2):
            with self.subTest(seed=seed):
                s = t40.sim(self, 900 + seed, fault=1.5, chat_budget={"acc3": 1, "acc8": 2, "acc19": 0},
                            image_budget={"acc5": 3, "acc16": 0, "acc27": 8}, broken={"acc12", "acc31"})
                from collections import Counter
                counts = Counter()
                rng = random.Random(seed)
                with self.chaos_worker(s, rng, counts, {"acc2", "acc22", "acc38"}, {"acc9", "acc33"}):
                    for kw, n, prod, mode in [("chaos1", 8, "wall_grid", "ai_page"), ("chaos2", 4, "wall_premade", None),
                                              ("chaos3", 5, "wall_grid", "background")]:
                        tb.run_until_done(self, s, kw, n, prod, mode, max_reruns=6)
                        books = s.books(kw, prod)
                        self.assertEqual(len(books), n)                    # không thiếu, không thừa, không trùng
                        self.assertEqual(len({layout.book_angle_id(b) for b in books}), n)
                        self.assertTrue(all(pipeline._finished_ok(b) for b in books))
                tb.check_invariants(self, s)
                self.assertLessEqual(s.world.tracker.peak, 40)
                self.assertTrue(set(s.pool.dead) <= {"acc2", "acc22", "acc38", "acc9", "acc33"})
                for n in s.pool.dead:                                       # tài khoản chết chỉ bị thử đúng 1 lần
                    self.assertFalse(s.pool.acquire(poolmod.IMAGE, only=n))
                self.assertLessEqual(counts["logged_out"] + counts["banned"], 5)
                for kind in ("refusal", "429", "disk", "garbage", "crash"):
                    self.assertGreater(counts[kind], 0, f"kịch bản chưa chạm lỗi {kind}")

    def test_chaos_with_ai_mockups_and_crashing_finisher(self):
        s = t40.sim(self, 950, fault=2.0, image_budget={"acc4": 5}, broken={"acc30"})
        from collections import Counter
        counts = Counter()
        with self.chaos_worker(s, random.Random(5), counts, {"acc6"}, {"acc17"}):
            reruns = 0
            for _ in range(7):
                rows = s.run("koi", 5, "wall_grid", "ai_page", resume=reruns > 0, mockup_mode="ai")
                for r in rows:
                    if not r["ok"]:
                        self.assertTrue(r.get("reason"), r)
                if sum(r["ok"] for r in rows) == 5:
                    break
                reruns += 1
        self.assertEqual(sum(r["ok"] for r in rows), 5)
        for b in s.books("koi"):
            names = sorted(p.stem for p in layout.listing(b).glob("*.jpg"))
            self.assertEqual(names, ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads",
                                     "04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"])   # ảnh AI hỏng thì vẫn còn ảnh code ghép
        tb.check_invariants(self, s)


if __name__ == "__main__":
    unittest.main()
