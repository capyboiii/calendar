"""Đẩy R2 + xuất CSV sản phẩm: đúng 25 cột mẫu, 3 biến thể + ảnh phụ, chỉ xuất cuốn chưa xuất."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout
from calforge.publish import r2, shop_csv


class FakeS3:
    def __init__(self):
        self.keys = []

    def upload_file(self, path, bucket, key, ExtraArgs=None):
        self.keys.append(key)


def make_book(root: Path, kw: str, name: str) -> Path:
    c = root / kw / name
    layout.ensure_system(c)
    layout.concept_file(c).write_text("{}", encoding="utf-8")
    layout.status_file(c).write_text(json.dumps({"ok": True, "stage": "listing"}), encoding="utf-8")
    layout.listing_file(c).write_text(json.dumps({
        "title": f"{name} 2027 Wall Calendar | Gift", "description": "<p>Hi</p>", "tags": ["a", "b"]}),
        encoding="utf-8")
    prev = layout.listing(c)
    prev.mkdir(parents=True)
    for i in range(1, 6):
        Image.new("RGB", (20, 20), "white").save(prev / f"0{i}_m.jpg")
    names = ["front_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")] + ["back_cover"]
    for fid in r2.SIZES:
        pages = layout.print_dir(c, fid)
        pages.mkdir(parents=True)
        for n in names:
            Image.new("RGB", (60, 45), "white").save(pages / f"{n}.png")
        layout.printable_file(c, fid).write_bytes(b"%PDF-1.4 test")
    return c


class ShopCsvTest(unittest.TestCase):
    def test_push_and_export_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_book(root, "cats", "Cat Days")
            dog = make_book(root, "dogs", "Dog Days")
            layout.concept_file(dog).write_text(json.dumps({"product": "wall_premade"}), encoding="utf-8")
            cfg = {"projects_dir": str(root), "shop": {"include_design": True}, "r2": {"account_id": "a", "access_key_id": "k",
                                                     "secret_access_key": "s", "bucket": "b",
                                                     "public_url": "https://cdn.x.com/"}}
            s3 = FakeS3()
            with mock.patch.object(r2, "client", lambda _r2: s3):
                res = shop_csv.publish_all(cfg, on_event=lambda *_: None)
                self.assertEqual(len(res["exported"]), 2)
                self.assertEqual(len(s3.keys), 2 * (5 + 2 * (1 + 26)))   # 5 preview + (PDF tại nhà + 26 PNG) × 2 khổ
                rows = list(csv.DictReader(open(res["csv"], encoding="utf-8-sig")))
                with open(res["csv"], encoding="utf-8-sig") as f:
                    self.assertEqual(next(csv.reader(f)), shop_csv.HEADER)
                book = [r for r in rows if r["Handle"].startswith("cat-days")]
                self.assertEqual(len(book), 5 + 4)                       # 11x8.5: Matte+Printable; 14: M+G+P
                first, printable = book[:2]
                self.assertEqual((first["Option1 Name"], first["Option2 Name"], first["Option3 Name"]),
                                 ("Size", "Choose your format", "Finish"))
                self.assertEqual([(r["Option1 Value"], r["Option2 Value"], r["Option3 Value"]) for r in book[:5]],
                                 [('11" x 8.5"', "Spiral", "Matte"), ('11" x 8.5"', "Printable", "Digital"),
                                  ('14" x 11.5"', "Spiral", "Matte"), ('14" x 11.5"', "Spiral", "Glossy"),
                                  ('14" x 11.5"', "Printable", "Digital")])
                self.assertTrue(book[2]["Variant Design"].split("|")[0].endswith("/14x11.5/front_cover.png"))
                self.assertAlmostEqual(float(book[2]["Variant Price"]) - float(first["Variant Price"]), 10.0)
                self.assertEqual(book[4]["Variant Price"], printable["Variant Price"])
                design = first["Variant Design"].split("|")
                self.assertEqual(len(design), 26)                        # 26 trang PNG cho Printify, đúng thứ tự
                self.assertTrue(design[0].endswith("/11x8.5/front_cover.png"))
                self.assertTrue(design[1].endswith("/11x8.5/m01_month.png"))
                self.assertTrue(design[-1].endswith("/11x8.5/back_cover.png"))
                self.assertEqual(printable["Variant Design"], "")
                self.assertTrue(printable["Variant File"].endswith("/in_tai_nha_11x8.5.pdf"))
                self.assertTrue(first["Image Src"].startswith("https://cdn.x.com/calendars/cats/cat-days/01_"))
                self.assertEqual(first["Tags"], "a, b")
                self.assertEqual(first["Product Category"], "Wall Calendars (Blank)")
                dog_first = next(r for r in rows if r["Handle"].startswith("dog-days"))
                self.assertEqual(dog_first["Product Category"], "Wall Calendars")
                self.assertTrue(first["Variant SKU"].startswith("WCB-") and first["Variant SKU"].endswith("-11SM"))
                self.assertTrue(dog_first["Variant SKU"].startswith("WCP-"))
                self.assertEqual(printable["Title"], "")                 # chỉ dòng đầu mang Title
                self.assertTrue(all(r["Image Src"] for r in book[5:]))
                self.assertTrue(all("/01_" in r["Variant Image"] for r in book[:5]))   # preview 1 cho mọi biến thể
                self.assertEqual([r["Image Src"].rsplit("/", 1)[-1][:3] for r in book if r["Image Src"]],
                                 ["01_", "02_", "03_", "04_", "05_"])                  # ảnh đầu tiên = preview 1
                self.assertEqual(len({r["Variant SKU"] for r in book[:5]}), 5)
                dog = [r for r in rows if r["Handle"].startswith("dog-days") and r["Option1 Value"]]
                self.assertEqual([(r["Option1 Value"], r["Option2 Value"], r["Option3 Value"]) for r in dog],
                                 [('11" x 8.5"', "Spiral", "Matte"), ('11" x 8.5"', "Printable", "Digital"),
                                  ('14" x 11.5"', "Spiral", "Glossy"), ('14" x 11.5"', "Printable", "Digital")])

                again = shop_csv.publish_all(cfg, on_event=lambda *_: None)   # chạy lại: không đẩy, không xuất lại
                self.assertEqual((again["exported"], again["csv"], len(s3.keys)), ([], None, 2 * 59))

    def test_design_column_empty_by_default(self):
        self.assertFalse(shop_csv.DEFAULT_SHOP["include_design"])

    def test_missing_keys_is_clear_error(self):
        with self.assertRaises(r2.R2Error):
            r2.settings({"r2": {"bucket": "b"}})


if __name__ == "__main__":
    unittest.main()
