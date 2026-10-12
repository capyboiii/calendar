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

        def push(b, cfg, on_event, s3=None):
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


if __name__ == "__main__":
    unittest.main()
