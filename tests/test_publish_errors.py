"""LỖI KHI ĐẨY R2 + XUẤT CSV: thiếu khoá, mạng hỏng giữa chừng, một cuốn hỏng, file trạng thái hỏng, listing hỏng,
đổi bucket, hết đĩa lúc ghi CSV. Không cuốn nào được vào CSV với link thiếu, và không cuốn nào bị đánh dấu "đã xuất"
khi chưa thật sự nằm trong file."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli, layout  # noqa: F401
from calforge.publish import calendaria_csv, r2, shop_csv

from tests.test_shop_csv import make_book

CFG_R2 = {"account_id": "a", "access_key_id": "k", "secret_access_key": "s", "bucket": "b",
          "public_url": "https://cdn.x.com/"}


class FlakyS3:
    """S3 giả: hỏng khi tải file có tên chứa `fail_on` (hoặc hỏng hẳn sau `fail_after` file)."""

    def __init__(self, fail_on="", fail_after=None):
        self.keys, self.fail_on, self.fail_after = [], fail_on, fail_after

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        if (self.fail_on and self.fail_on in key) or (self.fail_after is not None and len(self.keys) >= self.fail_after):
            raise ConnectionError(f"mất mạng khi tải {key}")
        self.keys.append(key)


class PublishErrorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = {"projects_dir": str(self.root), "r2": dict(CFG_R2)}
        self.logs = []

    def run_shop(self, s3, module=shop_csv, **kw):
        with mock.patch.object(r2, "client", lambda _r2: s3):
            return module.publish_all(self.cfg, on_event=self.logs.append, **kw)

    def rows(self, res, enc="utf-8"):
        return list(csv.DictReader(open(res["csv"], encoding=enc)))

    def test_missing_keys_is_a_clear_error_before_anything_happens(self):
        make_book(self.root, "cats", "Cat Days")
        for missing in ("account_id", "secret_access_key", "public_url"):
            cfg = {"projects_dir": str(self.root), "r2": {k: v for k, v in CFG_R2.items() if k != missing}}
            with self.assertRaises(r2.R2Error) as e:
                shop_csv.publish_all(cfg, on_event=lambda *_: None)
            self.assertIn(missing, str(e.exception))
        with self.assertRaises(r2.R2Error):
            shop_csv.publish_all({"projects_dir": str(self.root)}, on_event=lambda *_: None)
        self.assertFalse((self.root / "_xuat_csv").exists())

    def test_network_dies_mid_book(self):
        """Cuốn đẩy dở: không vào CSV, không bị đánh dấu đã xuất; file đã lên được ghi nhận, lần sau chỉ đẩy phần thiếu."""
        good = make_book(self.root, "cats", "Cat Days")
        bad = make_book(self.root, "dogs", "Dog Days")
        for module in (shop_csv, calendaria_csv):
            with self.subTest(module=module.__name__):
                for b in (good, bad):
                    r2.state_file(b).unlink(missing_ok=True)
                s3 = FlakyS3(fail_on="dogs/dog-days/14x11.5/m07")
                res = self.run_shop(s3, module)
                self.assertEqual(res["exported"], ["Cat Days"])
                self.assertTrue(any("Dog Days" in f for f in res["failed"]))
                enc = "utf-8-sig" if module is calendaria_csv else "utf-8"
                labels = {r.get("Label") or r.get("Title") for r in self.rows(res, enc)}
                self.assertFalse(any("Dog" in (l or "") for l in labels))
                key = "calendaria_exported_at" if module is calendaria_csv else "exported_at"
                self.assertNotIn(key, r2.read_state(bad))
                done_before = len(r2.read_state(bad)["files"])
                self.assertGreater(done_before, 0)                       # phần đã lên vẫn được nhớ
                s3b = FlakyS3()
                res2 = self.run_shop(s3b, module)                        # mạng ổn lại: chỉ đẩy phần thiếu
                self.assertEqual(res2["exported"], ["Dog Days"])
                self.assertLess(len(s3b.keys), 59)
                self.assertTrue(all("/dogs/" in k for k in s3b.keys))

    def test_r2_completely_down(self):
        make_book(self.root, "cats", "Cat Days")
        res = self.run_shop(FlakyS3(fail_after=0))
        self.assertEqual((res["exported"], res["csv"]), ([], None))
        self.assertEqual(len(res["failed"]), 1)
        self.assertTrue(any("✘ Cat Days" in l for l in self.logs))

    def test_broken_listing_skips_only_that_book(self):
        make_book(self.root, "cats", "Cat Days")
        bad = make_book(self.root, "dogs", "Dog Days")
        for module, enc in ((shop_csv, "utf-8"), (calendaria_csv, "utf-8-sig")):
            with self.subTest(module=module.__name__):
                for b in layout.books(self.root):
                    st = r2.read_state(b)
                    for k in ("exported_at", "calendaria_exported_at"):
                        st.pop(k, None)
                    if st:
                        r2.write_state(b, st)
                real = module._book_rows

                def rows(cdir, shop, real=real):
                    if cdir.name == "Dog Days":
                        raise KeyError("title")
                    return real(cdir, shop)
                with mock.patch.object(module, "_book_rows", rows):
                    res = self.run_shop(FlakyS3(), module)
                self.assertEqual(res["exported"], ["Cat Days"])
                self.assertTrue(any("không dựng được dòng CSV" in f for f in res["failed"]))
                self.assertTrue(self.rows(res, enc))                     # file CSV vẫn hợp lệ, có cuốn tốt
                key = "calendaria_exported_at" if module is calendaria_csv else "exported_at"
                self.assertNotIn(key, r2.read_state(bad))

    def test_corrupt_r2_state_means_push_again(self):
        b = make_book(self.root, "cats", "Cat Days")
        self.run_shop(FlakyS3())
        r2.state_file(b).write_text("{cụt", encoding="utf-8")
        s3 = FlakyS3()
        res = self.run_shop(s3)
        self.assertEqual(len(s3.keys), 59)                               # không biết đã đẩy gì: đẩy lại đủ
        self.assertEqual(res["exported"], ["Cat Days"])

    def test_changed_bucket_reuploads_everything(self):
        b = make_book(self.root, "cats", "Cat Days")
        self.run_shop(FlakyS3())
        self.cfg["r2"]["bucket"] = "bucket-moi"
        s3 = FlakyS3()
        self.run_shop(s3, only=[b])
        self.assertEqual(len(s3.keys), 59)

    def test_disk_full_while_writing_csv(self):
        b = make_book(self.root, "cats", "Cat Days")
        real_open = Path.open

        def full_open(self, *a, **k):
            if self.suffix == ".csv":
                raise OSError(28, "No space left on device")
            return real_open(self, *a, **k)
        with mock.patch.object(Path, "open", full_open):
            with self.assertRaises(OSError):
                self.run_shop(FlakyS3())
        self.assertNotIn("exported_at", r2.read_state(b))                # chưa có file thì chưa tính là đã xuất
        res = self.run_shop(FlakyS3())
        self.assertEqual(res["exported"], ["Cat Days"])

    def test_unfinished_books_never_exported(self):
        b = make_book(self.root, "cats", "Cat Days")
        layout.status_file(b).write_text(json.dumps({"ok": False, "stage": "images"}), encoding="utf-8")
        c = make_book(self.root, "dogs", "Dog Days")
        layout.listing_file(c).unlink()
        res = self.run_shop(FlakyS3())
        self.assertEqual((res["books"], res["exported"], res["csv"]), (0, [], None))

    def test_shop_cli_reports_errors_cleanly(self):
        from calforge import cli as c
        with mock.patch.object(c, "_read_status", create=True), \
                mock.patch("calforge.publish.shop_csv.publish_all", side_effect=r2.R2Error("Chưa nhập khoá R2: bucket")):
            with self.assertRaises(SystemExit) as e:
                c.cmd_shop(type("A", (), {"format": "printify", "book": None})(), self.cfg)
        self.assertIn("Chưa nhập khoá R2", str(e.exception.code))


if __name__ == "__main__":
    unittest.main()
