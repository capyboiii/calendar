"""Wall Calendar (Blank) chế độ "ai_page": AI vẽ nguyên 12 trang lịch, OCR soát ngày, render dùng thẳng ảnh đó."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from calforge import layout, products
from calforge.imagegen import plan
from calforge.imagegen.grid_check import check_grid_page, date_rows

from tests import fixtures

SAMPLE = Path(__file__).parent / "data" / "ai_grid_2027_01.webp"   # trang tháng 1/2027 ChatGPT vẽ đúng


def ai_concept():
    c = {**fixtures.concept(), "year": 2027, "market": "US", "product": "wall_grid"}
    c["style"]["grid_mode"] = "ai_page"
    return c


class AiPagePlanTest(unittest.TestCase):
    def test_twelve_page_jobs_with_exact_weeks(self):
        c = ai_concept()
        jobs = {j["id"]: j for j in plan.build_jobs(c)}
        self.assertNotIn("grid", jobs)
        self.assertEqual([f"g{m:02d}" for m in range(1, 13)], [k for k in jobs if k.startswith("g")])
        feb = jobs["g02"]["prompt"]
        self.assertIn("Week 1: empty, 1, 2, 3, 4, 5, 6", feb)          # 1/2/2027 là thứ Hai
        self.assertIn("NOT a photo of a calendar", feb)
        self.assertIn('"February"', feb)
        self.assertEqual(products.art_jobs(c)[-1], "g12")
        old = fixtures.concept()                                          # cuốn cũ: vẫn một nền grid chung
        self.assertIn("grid", products.art_jobs({**old, "product": "wall_grid"}))

    def test_date_rows_natural_weeks(self):
        self.assertEqual(date_rows(2027, 1)[0], ["", "", "", "", "", "1", "2"])
        self.assertEqual(date_rows(2027, 1)[-1][0], "31")


class GridCheckTest(unittest.TestCase):
    def test_correct_page_passes_and_wrong_month_fails(self):
        self.assertIsNone(check_grid_page(SAMPLE, 2027, 1))
        self.assertIn("lịch sai", check_grid_page(SAMPLE, 2027, 2))
        self.assertIn("lịch sai", check_grid_page(SAMPLE, 2026, 1))

    def test_missing_day_is_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            im = Image.open(SAMPLE).convert("RGB")
            # xoá số 15 (cột FRI, tuần 3): phủ màu nền giấy lên ô đó
            ImageDraw.Draw(im).rectangle((975, 575, 1050, 640), fill=im.getpixel((1060, 560)))
            bad = Path(tmp) / "bad.png"
            im.save(bad)
            self.assertIn("15", check_grid_page(bad, 2027, 1) or "")


class AiPageRenderTest(unittest.TestCase):
    def test_render_uses_ai_pages_for_all_twelve_grids(self):
        from calforge.render.build import load_format, render_concept
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "kw" / "Book"
            layout.ensure_system(c)
            layout.concept_file(c).write_text(json.dumps(ai_concept()), encoding="utf-8")
            raw = layout.raw(c)
            raw.mkdir(parents=True)
            for j in ["anchor", "cover"] + [f"m{m:02d}" for m in range(1, 13)]:
                Image.new("RGB", (1536, 1024), (180, 150, 120)).save(raw / f"{j}.png")
            for m in range(1, 13):
                shutil.copy(SAMPLE, raw / f"g{m:02d}.webp")
            r = render_concept(c, format_id="printify_wall_11x8_5", digital=False)
            fmt = load_format("printify_wall_11x8_5")
            grids = sorted(layout.print_dir(c).glob("m*_grid.png"))
            self.assertEqual(len(grids), 12)
            with Image.open(grids[0]) as im:
                self.assertEqual(im.size, tuple(fmt["size_px"]))
            self.assertFalse([i for i in r["issues"] if "[g" in i])


if __name__ == "__main__":
    unittest.main()


class TitleCheckTest(unittest.TestCase):
    def test_month_name_and_year(self):
        from calforge.imagegen.grid_check import title_problem
        self.assertIsNone(title_problem([("January", .99), ("2027", 1)], 1, 2027))
        self.assertIsNone(title_problem([("annary", .97), ("2027", 1)], 1, 2027))   # OCR rớt nét chữ thư pháp
        self.assertIn("chính tả", title_problem([("Febuary", .98)], 2, 2027))
        self.assertIn("March", title_problem([("March", .9)], 1, 2027))
        self.assertIn("2026", title_problem([("January", .9), ("2 0 2 6", .99)], 1, 2027))
