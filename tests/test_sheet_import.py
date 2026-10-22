"""Import xlsx dạng Sheet -> cuốn trong dự án TM: tải mockup, trang in giữ link R2, SKU đã có thì bỏ qua,
cuốn tạo ra xuất CSV Crayonahub + đồng bộ Sheet đúng mà không đẩy lại file nào lên R2."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from calforge import layout, projects as workspaces
from calforge.publish import r2, sheet_import as si, sheets

BASE = "https://cdn.crayonahub.com/calendars/wall-calendar-blank/the-grinch/wcb-tga-hxqys"


def _xlsx(rows):
    """xlsx tối giản (chuỗi inline) giống file người dùng xuất từ Google Sheet."""
    def cell(ref, v):
        v = v.replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{v}</t></is></c>'
    body = "".join(f'<row r="{i}">' + "".join(cell(f"{chr(65 + j)}{i}", v) for j, v in enumerate(r) if v) + "</row>"
                   for i, r in enumerate(rows, 1))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="S" sheetId="1" r:id="rId1"/>'
                                      '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{body}</sheetData></worksheet>")
    return buf.getvalue()


def book_rows(sku="WCB-TGA-HXQYS", base=BASE):
    design = lambda size: "\n".join(f"{base}/{size}/{n}.png" for n in r2.PAGE_ORDER)
    mock = "\n".join(f"{base}/{n}.jpg" for n in ("01_front_cover_spiral", "02_open_spread_flat"))
    desc = "A year of mischief.\n\nWhat's inside\n- Twelve artworks\n\nDetails\n- Paper: Matte or Glossy"
    return [[sku, desc, "grinch calendar, 2027 wall calendar", "The Grinch 2027 Wall Calendar", "", "", "", mock],
            [f"{sku}-11SM", "", "", "", "11 x 8.5", "Matte", design("11x8.5"), ""],
            [f"{sku}-11SG", "", "", "", "11 x 8.5", "Glossy", design("11x8.5"), ""],
            [f"{sku}-14SM", "", "", "", "14 x 11.5", "Matte", design("14x11.5"), ""],
            [f"{sku}-14SG", "", "", "", "14 x 11.5", "Glossy", design("14x11.5"), ""]]


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "projects"
        self.root.mkdir()
        self.cfg = {"projects_dir": str(self.root),
                    "r2": {"account_id": "a", "access_key_id": "k", "secret_access_key": "s", "bucket": "crayonahub",
                           "public_url": "https://cdn.crayonahub.com"}}
        self.fetched = []

    def opener(self, req, timeout=0):
        self.fetched.append(req.full_url)
        return FakeResp(b"\xff\xd8jpeg" + req.full_url.encode())

    def run_import(self, rows):
        f = Path(self.tmp.name) / "in.xlsx"
        f.write_bytes(_xlsx([si.HEADER] + rows))
        return si.import_file(f, self.cfg, on_event=lambda *_: None, opener=self.opener)

    def book(self):
        return next(b for b in layout.books(self.root))

    def test_creates_book_in_tm_project_with_mockups_and_design_links(self):
        res = self.run_import(book_rows())
        self.assertEqual(res["created"], ["WCB-TGA-HXQYS"])
        b = self.book()
        tm = [p for p in workspaces.entries(self.root) if p["name"] == "TM"]
        self.assertEqual(len(tm), 1)
        self.assertTrue(b.is_relative_to(self.root / "_du_an" / tm[0]["id"] / "Wall Calendar (Blank)" / "the-grinch"))
        self.assertEqual(b.name, "WCB-TGA-HXQYS")
        self.assertEqual(sorted(p.name for p in layout.listing(b).glob("*.jpg")),
                         ["01_front_cover_spiral.jpg", "02_open_spread_flat.jpg"])
        self.assertEqual(len(self.fetched), 2 + 52)                   # 2 mockup + 26 trang in x 2 khổ
        self.assertEqual(sorted(p.name for p in (b / "11x8.5").glob("*.png")), sorted(f"{n}.png" for n in r2.PAGE_ORDER))
        self.assertEqual(len(list((b / "14x11.5").glob("*.png"))), 26)
        self.assertEqual(r2.read_state(b)["files"]["11x8.5/m01_month.png"]["size"],
                         (b / "11x8.5" / "m01_month.png").stat().st_size)
        st = r2.read_state(b)
        self.assertEqual(st["key_base"], "calendars/wall-calendar-blank/the-grinch/wcb-tga-hxqys")
        self.assertEqual(st["files"]["14x11.5/back_cover.png"]["url"], f"{BASE}/14x11.5/back_cover.png")
        lst = json.loads(layout.listing_file(b).read_text(encoding="utf-8"))
        self.assertEqual(lst["tags"], ["grinch calendar", "2027 wall calendar"])
        self.assertIn("<ul><li>Twelve artworks</li></ul>", lst["description"])
        self.assertTrue((b / "listing.txt").read_text(encoding="utf-8-sig").startswith("SKU\nWCB-TGA-HXQYS"))
        status = json.loads(layout.status_file(b).read_text(encoding="utf-8"))
        self.assertEqual((status["stage"], status["ok"]), ("listing", True))

    def test_existing_sku_anywhere_is_skipped(self):
        old = self.root / "Wall Calendar (Blank)" / "x" / "WCB-TGA-HXQYS"
        layout.ensure_system(old)
        layout.concept_file(old).write_text("{}", encoding="utf-8")
        (old / "_he_thong" / "sku.txt").write_text("WCB-TGA-HXQYS", encoding="utf-8")
        res = self.run_import(book_rows() + book_rows("WCB-NEW-AAAAA", BASE.replace("wcb-tga-hxqys", "wcb-new-aaaaa")))
        self.assertEqual((res["skipped"], res["created"]), (["WCB-TGA-HXQYS"], ["WCB-NEW-AAAAA"]))
        again = self.run_import(book_rows("WCB-NEW-AAAAA", BASE.replace("wcb-tga-hxqys", "wcb-new-aaaaa")))
        self.assertEqual((again["created"], again["skipped"]), ([], ["WCB-NEW-AAAAA"]))   # Import lại: không tạo trùng

    def test_old_import_without_pages_is_filled_and_disk_guard_stops(self):
        with mock.patch.object(si, "_free_gb", lambda p: 5.0):         # ổ gần đầy: tạo cuốn, chưa tải trang in
            res = self.run_import(book_rows())
        self.assertTrue(res["disk_full"])
        b = self.book()
        self.assertEqual(list((b / "11x8.5").glob("*.png")) if (b / "11x8.5").exists() else [], [])
        self.assertEqual(len(list(layout.listing(b).glob("*.jpg"))), 2)
        self.fetched.clear()
        again = self.run_import(book_rows())                            # đã giải phóng ổ: bấm Import lại
        self.assertEqual((again["created"], again["filled"], again["pages"]), ([], ["WCB-TGA-HXQYS"], 52))
        self.assertTrue(all(u.endswith(".png") for u in self.fetched))  # không tải lại mockup
        self.assertEqual(self.run_import(book_rows())["pages"], 0)      # lần ba: đủ rồi, không tải gì

    def test_leftover_folder_and_old_temp_dir_are_reused(self):
        """Máy người dùng 21/10: thư mục cuốn còn sót mỗi _he_thong/r2.json + thư mục .importing của bản cũ -> bản cũ
        đổi tên báo [WinError 5]. Giờ ghi thẳng vào thư mục cuốn và dọn thư mục tạm."""
        tm = self.root / "_du_an" / workspaces.create(self.root, "TM")["id"] / "Wall Calendar (Blank)" / "the-grinch"
        (tm / "WCB-TGA-HXQYS" / "_he_thong").mkdir(parents=True)
        (tm / "WCB-TGA-HXQYS" / "_he_thong" / "r2.json").write_text("{}", encoding="utf-8")
        (tm / ".WCB-TGA-HXQYS.importing" / "preview").mkdir(parents=True)
        res = self.run_import(book_rows())
        self.assertEqual((res["created"], res["failed"]), (["WCB-TGA-HXQYS"], []))
        self.assertEqual(self.book(), tm / "WCB-TGA-HXQYS")
        self.assertFalse((tm / ".WCB-TGA-HXQYS.importing").exists())
        self.assertEqual(len(list((tm / "WCB-TGA-HXQYS" / "14x11.5").glob("*.png"))), 26)

    def test_bad_header_and_bad_links_are_rejected(self):
        f = Path(self.tmp.name) / "bad.xlsx"
        f.write_bytes(_xlsx([["SKU", "Title"]]))
        with self.assertRaises(si.ImportError_):
            si.import_file(f, self.cfg, on_event=lambda *_: None, opener=self.opener)
        rows = book_rows()
        rows[0][7] = "javascript:alert(1)"
        with self.assertRaises(si.ImportError_):
            self.run_import(rows)
        self.assertEqual(layout.books(self.root), [])

    def test_failed_download_leaves_no_half_book(self):
        def broken(req, timeout=0):
            raise OSError("mạng rớt")
        f = Path(self.tmp.name) / "in.xlsx"
        f.write_bytes(_xlsx([si.HEADER] + book_rows()))
        with mock.patch.object(si.time, "sleep", lambda s: None):
            res = si.import_file(f, self.cfg, on_event=lambda *_: None, opener=broken)
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(layout.books(self.root), [])                # bấm Import lại sẽ làm nốt
        self.assertEqual(self.run_import(book_rows())["created"], ["WCB-TGA-HXQYS"])

    def test_imported_book_exports_csv_and_sheet_without_uploading(self):
        from calforge.publish import calendaria_csv
        self.run_import(book_rows())
        b = self.book()
        s3 = mock.MagicMock()
        with mock.patch.object(sheets, "send") as send, \
                mock.patch.object(sheets, "validate_settings", lambda d: {"endpoint": "e", "secret": "x" * 40}):
            res = calendaria_csv.publish_all(self.cfg, on_event=lambda *_: None, only=[b], s3=s3) \
                if "s3" in calendaria_csv.publish_all.__code__.co_varnames else None
            if res is None:
                with mock.patch.object(r2, "client", lambda *_: s3):
                    res = calendaria_csv.publish_all(self.cfg, on_event=lambda *_: None, only=[b])
        s3.upload_file.assert_not_called()                           # mọi file đã nằm sẵn trên R2
        rows = send.call_args.args[0]
        self.assertEqual([r[0] for r in rows], ["WCB-TGA-HXQYS"] + [f"WCB-TGA-HXQYS-{v}" for v in
                                                                     ("11SM", "11SG", "14SM", "14SG")])
        self.assertEqual(rows[1][6].splitlines()[0], f"{BASE}/11x8.5/front_cover.png")
        self.assertEqual(len(rows[3][6].splitlines()), 26)
        self.assertEqual(rows[0][7].splitlines(), [f"{BASE}/01_front_cover_spiral.jpg", f"{BASE}/02_open_spread_flat.jpg"])
        import csv
        with open(res["csv"], encoding="utf-8-sig") as fh:
            out = list(csv.DictReader(fh))
        self.assertEqual(out[0]["Is Trademark"], "TRUE")
        self.assertEqual(len(out[0]["Variant Design"].split("|")), 26)


class RealFileTest(unittest.TestCase):
    FILE = Path(r"C:\Users\Admin\Downloads\tm_296_wall_calendars_2027_4_print_variants.xlsx")

    @unittest.skipUnless(FILE.exists(), "file của người dùng không có trên máy này")
    def test_user_file_parses_296_complete_books(self):
        books = si.parse_books(si.read_xlsx(self.FILE))
        self.assertEqual(len(books), 296)
        self.assertTrue(all(set(b["designs"]) == {"11x8.5", "14x11.5"} for b in books))
        self.assertTrue(all(len(u) == 26 for b in books for u in b["designs"].values()))
        self.assertTrue(all(b["mockups"] and b["tags"] and b["description"] for b in books))
        for b in books:
            kb = si._location(b)[2]
            self.assertTrue(b["designs"]["11x8.5"][0].startswith(f"https://cdn.crayonahub.com/{kb}/11x8.5/"), b["sku"])


if __name__ == "__main__":
    unittest.main()
