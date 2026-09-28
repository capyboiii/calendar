import tempfile
import unittest
from pathlib import Path

from PIL import Image

from calforge.core import dates
from calforge.render.build import load_format
from calforge.render.pages import grid_page
from calforge.render.preflight import check_page
from calforge.render.grid_compositions import COMPOSITIONS

from tests import fixtures


class MonthCellsTest(unittest.TestCase):
    def test_january_2027_needs_split_cell(self):
        rows, cells = dates.month_cells(2027, 1)
        self.assertEqual(rows, 5)
        split = [c for c in cells if len(c) == 2]
        self.assertEqual([[d.day for d in c] for c in split], [[24, 31]])

    def test_every_day_placed_once(self):
        for year in range(2025, 2036):
            for month in range(1, 13):
                _, cells = dates.month_cells(year, month)
                days = [d.day for c in cells for d in c]
                self.assertEqual(sorted(days), list(range(1, len(days) + 1)))
                for idx, c in enumerate(cells):  # cột đúng thứ trong tuần (tuần bắt đầu Chủ nhật)
                    for d in c:
                        self.assertEqual((d.weekday() + 1) % 7, idx % 7)

    def test_natural_rows_never_merge_dates(self):
        self.assertEqual(dates.month_cells(2027, 2, dates.MON, "natural")[0], 4)
        self.assertEqual(dates.month_cells(2027, 3, dates.MON, "natural")[0], 5)
        self.assertEqual(dates.month_cells(2027, 5, dates.MON, "natural")[0], 6)
        for month in range(1, 13):
            rows, cells = dates.month_cells(2027, month, dates.MON, "natural")
            self.assertEqual(len(cells), rows * 7)
            self.assertTrue(all(len(cell) <= 1 for cell in cells))
            for index, cell in enumerate(cells):
                for day in cell:
                    self.assertEqual(day.weekday(), index % 7)


class GridPageTest(unittest.TestCase):
    def test_all_months_pass_preflight(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        verse = "It is of the LORD'S mercies that we are not consumed, because his compassions fail not."
        for month in range(1, 13):
            page = grid_page(fmt, concept, month, f"m{month:02d} grid", verse)
            self.assertEqual(check_page(page, fmt), [], f"tháng {month}")
            roles = {t.role for t in page.texts()}
            self.assertTrue({"month title", "weekday", "date", "verse", "verse ref"} <= roles)

    def test_art_matched_grid_layers_background_under_exact_dates(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        with tempfile.TemporaryDirectory() as tmp:
            background = Path(tmp) / "sample-grid-background.png"
            Image.new("RGB", tuple(fmt["size_px"]), "#f4eddf").save(background)
            for month, expected_rows in ((2, 4), (3, 5), (5, 6)):
                page = grid_page(fmt, concept, month, "art matched", "Short verse.", background)
                self.assertEqual(check_page(page, fmt), [])
                self.assertEqual([op[0] for op in page.ops].count("image"), 1)
                self.assertFalse(any(op[0] == "round_rect" for op in page.ops))
                dates_drawn = [t.text for t in page.texts() if t.role == "date"]
                self.assertEqual(dates_drawn, [str(d) for d in range(1, dates.calendar.monthrange(2027, month)[1] + 1)])
                x0, y0, x1, y1 = page.grid_box
                horizontal = [op for op in page.ops if op[0] == "line" and op[2] == op[4]
                              and abs(op[1] - x0) < .1 and abs(op[3] - x1) < .1 and y0 <= op[2] <= y1]
                self.assertEqual(len(horizontal), expected_rows + 1)

    def test_editorial_illustration_keeps_six_row_calendar_on_open_paper(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        concept["style"]["grid_page_mode"] = "editorial_illustration"
        with tempfile.TemporaryDirectory() as tmp:
            background = Path(tmp) / "paper.png"
            Image.new("RGB", tuple(fmt["size_px"]), "#f4eddf").save(background)
            page = grid_page(fmt, concept, 5, "editorial May", "Short verse.", background)
            self.assertEqual(check_page(page, fmt), [])
            self.assertEqual(page.calendar["rows"], 6)
            self.assertEqual(len([t for t in page.texts() if t.role == "date"]), 31)
            self.assertFalse(any(op[0] == "round_rect" for op in page.ops))

    def test_all_shared_compositions_keep_exact_calendar_geometry(self):
        fmt = load_format()
        with tempfile.TemporaryDirectory() as tmp:
            background = Path(tmp) / "paper.png"
            Image.new("RGB", tuple(fmt["size_px"]), "#f4eddf").save(background)
            for composition in COMPOSITIONS:
                concept = fixtures.concept()
                concept.update(year=2027, market="US")
                concept["style"]["grid_composition"] = composition
                page = grid_page(fmt, concept, 5, composition, "Short verse.", background)
                self.assertEqual(check_page(page, fmt), [], composition)
                self.assertEqual(len([t for t in page.texts() if t.role == "date"]), 31)



class PaletteTest(unittest.TestCase):
    def _img(self, tmp, base, spot):
        img = Image.new("RGB", (300, 200), base)
        img.paste(spot, (0, 0, 300, 60))  # dải "bầu trời" màu khác
        p = Path(tmp) / "anchor.png"
        img.save(p)
        return p

    def test_hint_color_is_followed_using_art_hue(self):
        from calforge.ideation.validate import contrast_ratio
        from calforge.render.palette import palette_from_image

        with tempfile.TemporaryDirectory() as tmp:
            p = self._img(tmp, (200, 160, 90), (90, 150, 200))  # tranh vàng ấm, trời xanh
            pal = palette_from_image(p, {"paper": "#DDEBF5", "title": "#1F3A5F", "accent": "#C8742C"})
            r, g, b = (int(pal["paper"][i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreater(b, r)  # nền xanh theo ý đồ, không phải màu kem
            self.assertGreaterEqual(contrast_ratio(pal["title"], pal["paper"]), 7)
            self.assertGreaterEqual(contrast_ratio(pal["accent"], pal["paper"]), 4.5)

    def test_neutral_hint_falls_back_to_cool_color_in_art(self):
        from calforge.render.palette import palette_from_image

        with tempfile.TemporaryDirectory() as tmp:
            p = self._img(tmp, (200, 160, 90), (60, 140, 90))  # có mảng xanh lá đủ lớn
            pal = palette_from_image(p, {"paper": "#F8F1DF"})
            r, g, b = (int(pal["paper"][i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreater(g, r)


class ConceptColorTest(unittest.TestCase):
    def test_background_key_is_normalized(self):
        from calforge.ideation.validate import validate_concept

        c = fixtures.concept()
        c["style"]["palette"]["background"] = c["style"]["palette"].pop("paper")
        errors, _ = validate_concept(c, 2027)
        self.assertEqual(errors, [])
        self.assertIn("paper", c["style"]["palette"])


class PrintablePdfTest(unittest.TestCase):
    def test_printable_pdf_matches_each_trim_size(self):
        import fitz
        from calforge.render.build import printable_pdfs

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for fid, (w_in, h_in) in (("printify_wall_11x8_5", (11, 8.5)), ("printify_wall_14x11_5", (14, 11.5))):
                fmt = load_format(fid)
                png = tmp_path / "m01_month.png"
                Image.new("RGB", tuple(fmt["size_px"]), (200, 200, 200)).save(png)
                out = tmp_path / fid / "in_tai_nha.pdf"
                self.assertEqual(printable_pdfs([png], fmt, out), [out])
                self.assertFalse((out.parent / "_pages").exists())   # JPEG trung gian đã dọn
                doc = fitz.open(out)
                self.assertEqual(len(doc), 1)
                self.assertAlmostEqual(doc[0].rect.width, w_in * 72, places=1)
                self.assertAlmostEqual(doc[0].rect.height, h_in * 72, places=1)
                pix = doc[0].get_pixmap(dpi=20)
                self.assertLess(pix.pixel(1, 1)[0], 230)                # tràn hết khổ: mép không còn lề trắng
                self.assertLess(pix.pixel(pix.width - 2, pix.height - 2)[0], 230)
                doc.close()


class GridPresetTest(unittest.TestCase):
    def test_all_six_modern_presets_pass_preflight(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        verse = "The LORD is my shepherd; I shall not want."
        for preset_code in ("bento_planner", "quiet_luxury", "soft_tech", "fresh_monochrome",
                            "organic_capsules", "playful_editorial"):
            concept["grid_preset"] = preset_code
            for month in (1, 6, 12):
                page = grid_page(fmt, concept, month, f"m{month:02d} grid", verse)
                issues = check_page(page, fmt)
                self.assertEqual(issues, [], f"Preset {preset_code} tháng {month} gặp lỗi preflight: {issues}")
                roles = {t.role for t in page.texts()}
                self.assertTrue({"month title", "weekday", "date"} <= roles)


if __name__ == "__main__":
    unittest.main()


class PremadeProductTest(unittest.TestCase):
    """Lịch grid in sẵn: không gen nền grid, 14 trang khi chưa có trang grid thiết kế sẵn."""

    def test_no_grid_job_and_14_pages(self):
        from calforge import products
        from calforge.imagegen import plan
        from calforge.render.build import expected_pages, premade_grids
        c = {**fixtures.concept(), "year": 2027, "market": "US"}
        self.assertIn("grid", [j["id"] for j in plan.build_jobs(c)])
        c["product"] = "wall_premade"
        self.assertNotIn("grid", [j["id"] for j in plan.build_jobs(c)])
        for fid in products.formats(c):
            fmt = load_format(fid)
            self.assertNotIn("grid", fmt["pages"])
            self.assertEqual(expected_pages(c, fid), 26 if premade_grids(fmt) else 14)
        self.assertEqual(expected_pages(fixtures.concept(), "printify_wall_11x8_5"), 26)
        self.assertEqual(products.formats({}), ["printify_wall_11x8_5", "printify_wall_14x11_5"])


class PremadeGridPagesTest(unittest.TestCase):
    def test_weeks_start_sunday_six_rows_and_right_dates(self):
        import datetime as dt
        import importlib.util
        spec = importlib.util.spec_from_file_location("mpg", Path(__file__).resolve().parents[1] / "tools" / "make_premade_grids.py")
        mpg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mpg)
        for month in range(1, 13):
            weeks = mpg.month_weeks(2027, month)
            self.assertEqual(len(weeks), 6)
            days = [d for w in weeks for d in w]
            self.assertTrue(all(d.weekday() == 6 for d in (w[0] for w in weeks)))      # cột đầu = Chủ nhật
            self.assertEqual(days, [days[0] + dt.timedelta(days=i) for i in range(42)])  # liền mạch, không trùng
            inside = [d for d in days if d.month == month]
            self.assertEqual(inside[0].day, 1)
            self.assertEqual(len(inside), (dt.date(2027 + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)).day)
        self.assertEqual(mpg.month_weeks(2027, 1)[0][5], dt.date(2027, 1, 1))              # 1/1/2027 là thứ Sáu
