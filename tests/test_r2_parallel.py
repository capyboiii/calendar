"""Đẩy R2 khi xuất CSV: nhiều cuốn chạy SONG SONG, một cuốn lỗi không chặn cuốn khác, kết quả giữ thứ tự cuốn."""
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge.publish import r2

CFG = {"r2": {"account_id": "a", "access_key_id": "k", "secret_access_key": "s", "bucket": "b",
              "public_url": "https://cdn.x.com", "book_workers": 3}}


class PushBooksTest(unittest.TestCase):
    def test_books_upload_in_parallel_and_keep_order(self):
        busy, peak, lock = set(), [0], threading.Lock()
        books = [Path(f"/x/book{i}") for i in range(7)]

        def push(b, cfg, on_event, s3=None, **kw):
            with lock:
                busy.add(b)
                peak[0] = max(peak[0], len(busy))
            time.sleep(0.1)
            with lock:
                busy.discard(b)
            if b.name == "book3":
                raise RuntimeError("mạng rớt")
            return {"pushed_at": "now"}
        with mock.patch.object(r2, "push_book", push), mock.patch.object(r2, "read_state", lambda b: {}):
            t0 = time.monotonic()
            pushed, failed, ok = r2.push_books(books, CFG, lambda *_: None, s3=object())
            took = time.monotonic() - t0
        self.assertEqual(peak[0], 3)                                         # đúng 3 cuốn cùng lúc
        self.assertLess(took, 0.5)                                            # 7 cuốn x 0.1s không chạy tuần tự
        self.assertEqual(ok, [b for b in books if b.name != "book3"])         # giữ thứ tự, bỏ cuốn lỗi
        self.assertEqual(pushed, [b.name for b in ok])
        self.assertEqual(len(failed), 1)
        self.assertIn("book3", failed[0])



class SlowNetworkTest(unittest.TestCase):
    """Băng thông không đủ: file lỗi mạng thì giảm số file cùng lúc + chờ rồi thử lại, KHÔNG bỏ file; khoá sai thì
    báo ngay; file đã lên được ghi nhận dù file khác hỏng hẳn."""
    def book(self, n=6):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "kw" / "WCB-TST-AAAAA"
        from calforge import layout
        layout.ensure_system(d)
        files = {}
        for i in range(n):
            f = d / "11x8.5" / f"p{i}.png"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x" * 10)
            files[f"11x8.5/p{i}.png"] = f
        return d, files

    def run_push(self, s3, files, cfg=CFG):
        logs, slept = [], []
        with mock.patch.object(r2, "book_files", lambda c, sizes=None: files):
            try:
                st = r2.push_book(next(iter(files.values())).parent.parent, cfg, logs.append, s3=s3, sleep=slept.append)
            except r2.R2Error as e:
                st = e
        return st, logs, slept

    def test_flaky_network_slows_down_but_uploads_every_file(self):
        d, files = self.book()
        fails = {}

        class S3:
            uploaded = []

            def upload_file(self, path, bucket, key, ExtraArgs=None, Config=None):
                n = fails.get(key, 0)
                if n < 2:                                                  # mỗi file hỏng 2 lần đầu (mạng nghẽn)
                    fails[key] = n + 1
                    raise TimeoutError("Read timeout on endpoint URL")
                S3.uploaded.append(key)
        st, logs, slept = self.run_push(S3(), files)
        self.assertIsInstance(st, dict, st)
        self.assertEqual(len(S3.uploaded), 6)                              # không mất file nào
        self.assertEqual(len(st["files"]), 6)
        self.assertTrue(slept and all(w > 0 for w in slept))               # có nghỉ trước khi thử lại
        self.assertTrue(any("giảm còn 1 file cùng lúc" in l for l in logs), logs)

    def test_wrong_key_fails_fast_without_retry(self):
        d, files = self.book(2)

        class Denied(Exception):
            response = {"Error": {"Code": "InvalidAccessKeyId"}}

        class S3:
            calls = 0

            def upload_file(self, *a, **k):
                S3.calls += 1
                raise Denied("bad key")
        st, logs, slept = self.run_push(S3(), files)
        self.assertIsInstance(st, r2.R2Error)
        self.assertEqual(slept, [])                                        # không chờ thử lại vô ích
        self.assertEqual(S3.calls, 2)

    def test_files_done_are_kept_when_one_file_keeps_failing(self):
        d, files = self.book(4)

        class S3:
            def upload_file(self, path, bucket, key, ExtraArgs=None, Config=None):
                if key.endswith("p2.png"):
                    raise ConnectionError("mất mạng")
        st, logs, slept = self.run_push(S3(), files, cfg={**CFG, "r2": {**CFG["r2"], "upload_retries": 3}})
        self.assertIsInstance(st, r2.R2Error)
        self.assertIn("còn 1 file", str(st))
        saved = r2.read_state(d)["files"]
        self.assertEqual(sorted(saved), ["11x8.5/p0.png", "11x8.5/p1.png", "11x8.5/p3.png"])   # lần sau chỉ đẩy p2

    def test_throttle_halves_on_error_and_grows_back(self):
        t = r2.Throttle(8, start=4)
        t.acquire()
        self.assertEqual(t.release(False), 2)
        t.acquire()
        self.assertEqual(t.release(False), 1)
        for _ in range(5):
            t.acquire()
            t.release(True)
        self.assertGreater(t.limit, 1)
        self.assertLessEqual(t.limit, 8)


class PushWhileBatchTest(unittest.TestCase):
    """Đang đẩy R2 + xuất CSV vẫn chạy batch theo ý tưởng / clone được (và ngược lại); chỉ chặn 2 lượt đẩy R2."""
    def tm(self, *actions):
        from calforge.ui.server import Task, TaskManager
        tm = TaskManager()
        for i, a in enumerate(actions):
            tm.tasks[str(i)] = Task(str(i), [], a, a)
        return tm

    def test_shop_does_not_block_batch(self):
        tm = self.tm("shop")
        self.assertIsNone(tm.running())                                   # batch / clone / sửa sách chạy được
        self.assertIsNone(tm.running(include_clone=True))
        self.assertIsNotNone(tm.shop_running())                           # lượt đẩy R2 thứ hai: bị chặn

    def test_batch_does_not_block_shop(self):
        tm = self.tm("batch")
        self.assertIsNone(tm.shop_running())                              # đẩy R2 được khi batch đang chạy
        self.assertIsNotNone(tm.running())                                # batch thứ hai vẫn bị chặn như cũ


if __name__ == "__main__":
    unittest.main()
