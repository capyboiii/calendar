"""Thư mục cuốn mới đặt tên bằng mã SKU; CSV dùng đúng mã đó; cuốn cũ giữ nguyên SKU đã đăng bán."""
import csv
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli, layout  # noqa: F401
from calforge.publish import calendaria_csv, r2, shop_csv

from tests import test_batch_simulation as tb
from tests.test_shop_csv import FakeS3, make_book

SKU_RE = re.compile(r"^(WCB|WCP)-[A-Z0-9]{1,3}-[A-HJ-NP-Z2-9]{5}$")
CFG_R2 = {"account_id": "a", "access_key_id": "k", "secret_access_key": "s", "bucket": "b",
          "public_url": "https://cdn.x.com/"}


class SkuFolderTest(unittest.TestCase):
    def test_new_book_folder_is_its_sku(self):
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "Wall Calendar (Blank)" / "cats"
            d = layout.new_book_dir(kdir, "The Garden Cat Club: Twelve Retro Flower Companions", "r1a1", "wall_grid")
            self.assertRegex(d.name, SKU_RE)
            self.assertTrue(d.name.startswith("WCB-TGC-"))
            self.assertEqual(layout.book_sku(d), d.name)
            self.assertEqual(layout.book_angle_id(d), "r1a1")
            self.assertEqual(layout.find_book(kdir, "r1a1"), d)              # vẫn tìm lại được theo mã góc
            p = layout.new_book_dir(Path(tmp) / "Wall Calendar" / "bible", "Psalms", "r1a2", "wall_premade")
            self.assertTrue(p.name.startswith("WCP-P-"))

    def test_odd_titles(self):
        for title in ("", None, "!!!", "Lịch Việt: Tết", "2027 Cats & Dogs / <Fun>"):
            sku = layout.make_sku("wall_grid", title)
            self.assertRegex(sku, SKU_RE, title)
            self.assertNotRegex(sku, r'[<>:"/\\|?*\s]')                       # luôn là tên thư mục hợp lệ

    def test_many_parallel_books_never_share_a_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "kw"
            made, lock = [], threading.Lock()

            def make(i):
                d = layout.new_book_dir(kdir, "Same Title Every Time", f"r1a{i}", "wall_grid")
                with lock:
                    made.append(d)
            with mock.patch("secrets.choice", lambda seq: seq[0]):            # ép mã ngẫu nhiên trùng nhau
                threads = [threading.Thread(target=make, args=(i,)) for i in range(1)]
                [t.start() for t in threads]
                [t.join() for t in threads]
                with self.assertRaises(RuntimeError):                         # hết cách tạo mã khác: báo lỗi rõ
                    layout.new_book_dir(kdir, "Same Title Every Time", "r1a9", "wall_grid")
            threads = [threading.Thread(target=make, args=(i,)) for i in range(2, 42)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(len({d.name for d in made}), 41)
            self.assertEqual(len(list(kdir.iterdir())), 41)

    def test_old_books_without_sku(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "kw" / "The Old Title"
            layout.ensure_system(old)
            self.assertEqual(layout.book_sku(old), "")


class SkuCsvTest(unittest.TestCase):
    def export(self, module, root):
        cfg = {"projects_dir": str(root), "shop": {"include_design": True}, "r2": CFG_R2}
        with mock.patch.object(r2, "client", lambda _r2: FakeS3()):
            res = module.publish_all(cfg, on_event=lambda *_: None)
        return list(csv.DictReader(open(res["csv"], encoding="utf-8-sig")))

    def test_csv_uses_folder_sku_and_old_books_keep_their_sku(self):
        for module, col in ((shop_csv, "External ID"), (calendaria_csv, "Variant SKU")):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                old = make_book(root, "cats", "Cat Days")                     # cuốn cũ: thư mục mang tên cuốn
                new = make_book(root, "dogs", "WCB-DDW-7K3QX")                # cuốn mới: thư mục = SKU
                (new / layout.SYSTEM / layout.SKU_FILE).write_text("WCB-DDW-7K3QX", encoding="utf-8")
                rows = self.export(module, root)
                skus = {r[col] for r in rows if r[col]}
                new_skus = {s for s in skus if s.startswith("WCB-DDW-7K3QX-")}
                self.assertTrue(new_skus)
                old_skus = skus - new_skus
                self.assertTrue(old_skus)
                self.assertTrue(all(s.startswith("CAL-") or s.startswith("WCB-") for s in old_skus))
                self.assertTrue(all("7K3QX" not in s for s in old_skus))
                from calforge.ui import server
                with mock.patch.object(server.config, "load", lambda: {"projects_dir": str(root)}):
                    self.assertEqual(server._sku_of(new), "WCB-DDW-7K3QX")
                    legacy = server._sku_of(old)
                self.assertTrue(legacy and any(s.startswith(legacy + "-") for s in old_skus))   # UI hiện đúng SKU đã xuất


class SkuInBatchTest(unittest.TestCase):
    def test_batch_books_are_named_by_sku(self):
        s = tb.Sim(self, 31, fault=0)
        rows = s.run("koi", 3, "wall_grid", "ai_page")
        self.assertEqual(sum(r["ok"] for r in rows), 3)
        books = s.books("koi")
        self.assertEqual(len(books), 3)
        for b in books:
            self.assertRegex(b.name, SKU_RE)
            self.assertEqual(layout.book_sku(b), b.name)
        prem = s.run("bible", 2, "wall_premade")
        self.assertEqual(sum(r["ok"] for r in prem), 2)
        self.assertTrue(all(b.name.startswith("WCP-") for b in s.books("bible", "wall_premade")))
        rows = s.run("koi", 3, "wall_grid", "ai_page", resume=True)          # làm nốt: không đổi tên, không thêm cuốn
        self.assertEqual(sorted(b.name for b in s.books("koi")), sorted(b.name for b in books))


if __name__ == "__main__":
    unittest.main()
