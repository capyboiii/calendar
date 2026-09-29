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
                self.assertEqual(len(s3.keys), 59 + 35)   # 5 preview + (PDF + 26 PNG) × 2 khổ; grid in sẵn: 14 PNG (không grid)
                rows = list(csv.DictReader(open(res["csv"], encoding="utf-8")))
                with open(res["csv"], encoding="utf-8") as f:
                    head = next(csv.reader(f))
                self.assertEqual(len(shop_csv.TEMPLATE), 23)
                self.assertEqual(head, shop_csv.TEMPLATE + shop_csv.PAGE_COLS + shop_csv.PREVIEW_COLS)
                self.assertEqual((head[23], head[48], head[-1]), ("Page 01 front_cover", "Page 26 back_cover", "Preview 5"))
                for r in rows:
                    size = "14x11.5" if "-14" in r["External ID"] else "11x8.5"
                    premade = r["External ID"].startswith("WCP")
                    for c in shop_csv.PAGE_COLS:
                        if premade and c.endswith("_grid"):
                            self.assertEqual(r[c], "")              # grid in sẵn: trang grid chỉ cho digital
                        else:
                            self.assertTrue(r[c].endswith(f"/{size}/{c[8:]}.png"))
                cat = [r for r in rows if r["Label"].startswith("Cat Days")]
                dog = [r for r in rows if r["Label"].startswith("Dog Days")]
                # chỉ bản Spiral: blank 11 Matte, 14 Matte+Glossy; in sẵn 11 Matte, 14 Glossy
                self.assertEqual([r["External ID"][-4:] for r in cat], ["11SM", "14SM", "14SG"])
                self.assertEqual([r["External ID"][-4:] for r in dog], ["11SM", "14SG"])
                self.assertTrue(cat[0]["External ID"].startswith("WCB-") and dog[0]["External ID"].startswith("WCP-"))
                self.assertTrue(cat[0]["Print area front"].endswith("/11x8.5/front_cover.png"))
                self.assertTrue(cat[1]["Print area front"].endswith("/14x11.5/front_cover.png"))
                self.assertTrue(all(r["Quantity"] == "1" for r in rows))
                self.assertTrue(all([r[c].rsplit("/", 1)[-1][:3] for c in shop_csv.PREVIEW_COLS]
                                    == ["01_", "02_", "03_", "04_", "05_"] for r in rows))
                self.assertTrue(all("/cats/" in r["Preview 1"] for r in cat))
                filled = {"External ID", "Label", "Quantity", "Print area front"}
                self.assertTrue(all(not r[k] for r in rows for k in shop_csv.TEMPLATE if k not in filled))

                again = shop_csv.publish_all(cfg, on_event=lambda *_: None)   # chạy lại: không đẩy, không xuất lại
                self.assertEqual((again["exported"], again["csv"], len(s3.keys)), ([], None, 59 + 35))

    def test_only_selected_books_and_reexport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cat = make_book(root, "cats", "Cat Days")
            dog = make_book(root, "dogs", "Dog Days")
            cfg = {"projects_dir": str(root), "r2": {"account_id": "a", "access_key_id": "k",
                                                     "secret_access_key": "s", "bucket": "b",
                                                     "public_url": "https://cdn.x.com/"}}
            s3 = FakeS3()
            with mock.patch.object(r2, "client", lambda _r2: s3):
                res = shop_csv.publish_all(cfg, on_event=lambda *_: None, only=[cat])
                self.assertEqual(res["exported"], ["Cat Days"])                  # chỉ cuốn được chọn
                self.assertIsNone(r2.read_state(dog).get("pushed_at"))
                again = shop_csv.publish_all(cfg, on_event=lambda *_: None, only=[cat])
                self.assertEqual(again["exported"], ["Cat Days"])                # chọn lại = xuất lại
                rows = list(csv.DictReader(open(again["csv"], encoding="utf-8")))
                self.assertTrue(rows and all(r["Label"].startswith("Cat Days") for r in rows))

    def test_design_column_empty_by_default(self):
        self.assertFalse(shop_csv.DEFAULT_SHOP["include_design"])

    def test_missing_keys_is_clear_error(self):
        with self.assertRaises(r2.R2Error):
            r2.settings({"r2": {"bucket": "b"}})


if __name__ == "__main__":
    unittest.main()
