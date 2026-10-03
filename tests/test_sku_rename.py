"""Đổi tên cuốn cũ sang SKU: đúng SKU đã xuất, sửa kèm batch / hàng đợi / status / đường dẫn R2, chạy lại không sao."""
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli, config, layout, pipeline  # noqa: F401
from calforge.publish import r2, shop_csv
from calforge.sku_rename import legacy_sku, rename_all

from tests.test_shop_csv import FakeS3, make_book
from tests.test_sku_names import SKU_RE

CFG_R2 = {"account_id": "a", "access_key_id": "k", "secret_access_key": "s", "bucket": "b",
          "public_url": "https://cdn.x.com/", "prefix": "calendars"}


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "projects"
        self.kw = self.root / "Wall Calendar (Blank)" / "cats"
        self.logs = []

    def old_book(self, name, listing=True):
        b = make_book(self.kw.parent, "cats", name)
        layout.concept_file(b).write_text(json.dumps({"title": name, "product": "wall_grid", "angle_id": "r1a1"}),
                                          encoding="utf-8")
        if not listing:
            layout.listing_file(b).unlink()
        return b

    def export(self):
        cfg = {"projects_dir": str(self.root), "shop": {"include_design": True}, "r2": CFG_R2}
        with mock.patch.object(r2, "client", lambda _r2: FakeS3()):
            res = shop_csv.publish_all(cfg, on_event=lambda *_: None)
        return res, cfg

    def test_full_rename_keeps_exported_sku_and_every_reference(self):
        old = self.old_book("Cat Days")
        res, cfg = self.export()                                         # đã đẩy R2 + xuất CSV bằng tên cũ
        exported = {r["External ID"] for r in csv.DictReader(open(res["csv"], encoding="utf-8-sig"))}
        st_before = r2.read_state(old)
        st_before.pop("key_base", None)                                  # dữ liệu kiểu cũ: chưa chốt đường dẫn R2
        r2.write_state(old, st_before)
        first_key = next(iter(st_before["files"].values()))["url"]
        pipeline._save_batch(self.kw, {"target": 1, "product": "wall_grid", "concepts": ["Cat Days"],
                                       "failed_ideas": [], "errors": [], "started": "x", "finished": "y",
                                       "report": [{"concept": "Cat Days", "ok": True}]})
        pipeline._status(old, ok=True, stage="listing",
                         digital=[str(layout.printable_file(old, fid)) for fid in r2.SIZES])
        qfile = self.root / ".hang_doi.json"
        rel = os.path.relpath(old, config.ROOT).replace("\\", "/")
        qfile.write_text(json.dumps({"paused": False, "items": [
            {"id": "q1", "status": "done", "params": {"action": "finish", "concept": rel, "title": "Cat Days"}},
            {"id": "q2", "status": "queued", "params": {"keyword": "cats"}}]}), encoding="utf-8")

        done = rename_all(self.root, self.logs.append)
        self.assertEqual(len(done), 1)
        sku = done[0][1]
        new = self.kw / sku
        self.assertFalse(old.exists())
        self.assertTrue(layout.is_book(new))
        self.assertEqual(sku, legacy_sku(new))
        self.assertTrue(all(e.startswith(sku + "-") for e in exported))  # đúng SKU đã đăng bán
        self.assertEqual(layout.book_sku(new), sku)
        self.assertEqual(layout.book_angle_id(new), "r1a1")
        b = pipeline._load_batch(self.kw)
        self.assertEqual((b["concepts"], b["report"][0]["concept"]), ([sku], sku))
        self.assertTrue(pipeline._finished_ok(new))
        st = pipeline._read_status(new)
        self.assertTrue(all(Path(p).parent.parent == new for p in st["digital"]), st["digital"])
        self.assertTrue(all(Path(p).is_file() for p in st["digital"]))
        q = json.loads(qfile.read_text(encoding="utf-8"))
        self.assertEqual((config.ROOT / q["items"][0]["params"]["concept"]).resolve(), new.resolve())
        self.assertEqual(q["items"][1]["params"], {"keyword": "cats"})

        s3 = FakeS3()                                                    # đẩy R2 lần sau: không đẩy lại gì
        with mock.patch.object(r2, "client", lambda _r2: s3):
            res2 = shop_csv.publish_all(cfg, on_event=lambda *_: None)
        self.assertEqual(s3.keys, [])
        self.assertIn("/cat-days/", r2.read_state(new)["key_base"] + "/")
        self.assertEqual(next(iter(r2.read_state(new)["files"].values()))["url"], first_key)

        self.assertEqual(rename_all(self.root, self.logs.append), [])    # chạy lại: không làm gì
        self.assertEqual([p.name for p in self.kw.iterdir() if p.name != layout.SYSTEM], [sku])

    def test_unfinished_book_gets_new_sku_and_collisions_are_avoided(self):
        a = self.old_book("Moon Cats", listing=False)
        b = self.old_book("Moon Cats Two")
        clash = legacy_sku(b)
        (self.kw / clash).mkdir()                                        # thư mục lạ trùng đúng mã
        done = dict(rename_all(self.root, self.logs.append))
        self.assertRegex(done["Moon Cats"], SKU_RE)
        self.assertTrue(done["Moon Cats"].startswith("WCB-MC-"))
        self.assertNotEqual(done["Moon Cats Two"], clash)                # trùng thì nhận mã mới, không ghi đè
        self.assertRegex(done["Moon Cats Two"], SKU_RE)
        self.assertTrue((self.kw / clash).is_dir())
        self.assertFalse(a.exists() or b.exists())

    def test_busy_topic_and_locked_folder_are_skipped(self):
        b = self.old_book("Busy Cats")
        layout.ensure_system(self.kw)
        (self.kw / layout.SYSTEM / "batch.lock").write_text(json.dumps({"pid": os.getppid()}), encoding="utf-8")
        self.assertEqual(rename_all(self.root, self.logs.append), [])
        self.assertTrue(b.exists())
        self.assertTrue(any("đang có batch chạy" in l for l in self.logs))
        (self.kw / layout.SYSTEM / "batch.lock").unlink()
        with mock.patch.object(Path, "rename", mock.Mock(side_effect=PermissionError("đang mở trong Explorer"))):
            self.assertEqual(rename_all(self.root, self.logs.append), [])
        self.assertTrue(b.exists())
        self.assertFalse((b / layout.SYSTEM / layout.SKU_FILE).exists())  # chưa đổi được: lần sau làm lại
        self.assertEqual(len(rename_all(self.root, self.logs.append)), 1)

    def test_books_of_all_kinds_and_new_books_untouched(self):
        old = self.old_book("Old Cat")
        new = layout.new_book_dir(self.kw, "Fresh Cat", "r2a1", "wall_grid")
        layout.concept_file(new).write_text(json.dumps({"title": "Fresh Cat"}), encoding="utf-8")
        prem = make_book(self.root / "Wall Calendar", "bible", "Psalm Days")
        layout.concept_file(prem).write_text(json.dumps({"title": "Psalm Days", "product": "wall_premade"}),
                                             encoding="utf-8")
        done = dict(rename_all(self.root, self.logs.append))
        self.assertEqual(set(done), {"Old Cat", "Psalm Days"})
        self.assertTrue(done["Psalm Days"].startswith("WCP-"))
        self.assertTrue(new.exists())                                    # cuốn đã mang SKU: không đụng


class ServerStartRenameTest(unittest.TestCase):
    def test_ui_start_runs_rename_but_never_blocks(self):
        src = Path(cli.__file__).with_name("ui").joinpath("server.py").read_text(encoding="utf-8")
        i, j = src.index("from ..sku_rename import rename_all"), src.index("batch_queue().start()")
        self.assertLess(i, j)                                            # đổi tên TRƯỚC khi hàng đợi chạy
        self.assertIn("đổi tên lỗi không được chặn mở tool", src)


if __name__ == "__main__":
    unittest.main()
