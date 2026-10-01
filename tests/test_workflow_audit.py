"""Cross-workflow regression checks found during the October workflow audit.

All books and uploads are temporary/fake; no live account or bucket is used.
"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import layout
from calforge.pipeline import redo_pages
from calforge.publish import calendaria_csv, r2
from tests.test_shop_csv import FakeS3, make_book


class WorkflowAuditTest(unittest.TestCase):
    def test_long_batch_keeps_delivering_new_logs(self):
        from calforge.ui.server import Task
        task = Task("test", [], "Long batch")
        for index in range(3000):
            task.append_log(f"line {index}")
        consumed = len(task.to_dict()["logs"])
        task.append_log("new progress after buffer fills")
        self.assertIn("new progress after buffer fills", task.to_dict(consumed)["logs"])

    def config(self, root):
        return {"projects_dir": str(root), "r2": {
            "account_id": "test", "access_key_id": "test", "secret_access_key": "test",
            "bucket": "test", "public_url": "https://example.invalid"}}

    def test_failed_upload_is_not_marked_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = make_book(root, "topic", "Book")
            cfg = self.config(root)
            r2.push_book(book, cfg, lambda *_: None, s3=FakeS3())
            with mock.patch.object(r2, "client", return_value=FakeS3()), mock.patch.object(
                    r2, "push_book", side_effect=RuntimeError("upload interrupted")):
                result = calendaria_csv.publish_all(cfg, lambda *_: None, only=[book])
            self.assertEqual(len(result["failed"]), 1)
            self.assertEqual(result["exported"], [], "Failed upload was still included in CSV")
            self.assertNotIn("calendaria_exported_at", r2.read_state(book))

    def test_redo_invalidates_calendaria_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = make_book(Path(tmp), "topic", "Book")
            layout.raw(book).mkdir(parents=True, exist_ok=True)
            (layout.raw(book) / "m05.png").write_bytes(b"old image")
            r2.write_state(book, {"files": {}, "calendaria_exported_at": "2026-09-30",
                                 "calendaria_exported_csv": "old.csv"})
            redo_pages(book, ["m05"], on_event=lambda *_: None)
            self.assertNotIn("calendaria_exported_at", r2.read_state(book))

    def test_missing_pdf_does_not_create_downloadless_printable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = make_book(root, "topic", "Book")
            for fid in r2.SIZES:
                layout.printable_file(book, fid).unlink()
            r2.push_book(book, self.config(root), lambda *_: None, s3=FakeS3())
            rows = calendaria_csv._book_rows(book, calendaria_csv.shop_settings({}))
            self.assertFalse([row for row in rows if row["Option2 Value"] == "Printable"
                              and not row["Variant File"]])

    def test_changed_r2_bucket_uploads_unchanged_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = make_book(root, "topic", "Book")
            cfg = self.config(root)
            r2.push_book(book, cfg, lambda *_: None, s3=FakeS3())
            cfg["r2"]["bucket"] = "another-bucket"
            cfg["r2"]["public_url"] = "https://new.example.invalid"
            target = FakeS3()
            state = r2.push_book(book, cfg, lambda *_: None, s3=target)
            self.assertGreater(len(target.keys), 0, "New bucket received no files")
            self.assertTrue(all(info["url"].startswith(cfg["r2"]["public_url"])
                                for info in state["files"].values()))

    def test_calendaria_rerun_selection_and_option_arity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = make_book(root, "topic", "Book")
            cfg = self.config(root)
            with mock.patch.object(r2, "client", return_value=FakeS3()):
                first = calendaria_csv.publish_all(cfg, lambda *_: None)
                again = calendaria_csv.publish_all(cfg, lambda *_: None)
                selected = calendaria_csv.publish_all(cfg, lambda *_: None, only=[book])
            self.assertEqual(again["exported"], [])
            self.assertEqual(first["exported"], selected["exported"])
            with open(selected["csv"], encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            variants = [row for row in rows if row["Variant SKU"]]
            self.assertEqual(len(variants), 5)
            self.assertTrue(all(all(row[f"Option{i} Value"] for i in range(1, 4)) for row in variants))


if __name__ == "__main__":
    unittest.main()
