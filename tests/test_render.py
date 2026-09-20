import tempfile
import unittest
from pathlib import Path

from PIL import Image

from calforge.core import dates
from calforge.imagegen import cleanup
from calforge.render.build import load_format
from calforge.render.pages import grid_page
from calforge.render.preflight import check_page

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


def _fake_ornament(tmp: Path) -> dict:
    """Cành lá giả: PNG nền trong suốt tỉ lệ ~3:1."""
    img = Image.new("RGBA", (600, 200), (0, 0, 0, 0))
    img.paste((90, 120, 70, 255), (20, 80, 580, 120))
    left, right = tmp / "orn.png", tmp / "orn_r.png"
    img.save(left)
    img.save(right)
    return {"left": left, "right": right, "aspect": 200 / 600}


class OrnamentTest(unittest.TestCase):
    def test_ornament_layer_passes_preflight(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        concept["style"]["grid_decor"] = {"rule_center": True}
        with tempfile.TemporaryDirectory() as tmp:
            orn = _fake_ornament(Path(tmp))
            for month in (1, 9):  # tháng 9: tên tháng dài nhất
                page = grid_page(fmt, concept, month, f"m{month:02d} grid", "Short verse.", orn)
                slots = {slot for slot, _ in page.ornaments()}
                self.assertEqual(slots, {"ornament title_side", "ornament panel_bottom", "ornament rule_center"})
                self.assertEqual(check_page(page, fmt), [], f"tháng {month}")

    def test_preflight_catches_ornament_on_grid(self):
        fmt = load_format()
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        with tempfile.TemporaryDirectory() as tmp:
            orn = _fake_ornament(Path(tmp))
            page = grid_page(fmt, concept, 1, "m01 grid", None, orn)
            page.image(orn["left"], 800, 1200, 400, 130, role="ornament test")
            issues = check_page(page, fmt)
            self.assertTrue(any("lấn vào ô lưới" in i for i in issues), issues)

    def test_checkerboard_background_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Image.new("RGB", (400, 200), (254, 254, 254))
            for y in range(0, 200, 32):
                for x in range(0, 400, 32):
                    if (x // 32 + y // 32) % 2:
                        img.paste((209, 209, 209), (x, y, x + 32, y + 32))
            img.paste((80, 120, 60), (60, 80, 340, 120))
            src = Path(tmp) / "checker.png"
            img.save(src)
            self.assertEqual(cleanup.background_kind(src), "checker")
            out = Path(tmp) / "clean.png"
            self.assertEqual(cleanup.ensure_alpha(src, out), "checker")
            with Image.open(out) as clean:
                self.assertEqual(clean.mode, "RGBA")
                self.assertLess(clean.width, 300)  # đã cắt sát cành, bỏ hết caro


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
    def test_default_cream_background_rejected(self):
        from calforge.ideation.validate import validate_concept

        c = fixtures.concept()
        c["style"]["color_story"] = "barn red, sage green, sky blue"
        c["style"]["style_bible"] = c["style"]["style_bible"] + " Dominated by barn red, sage green and sky blue."
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("default cream" in e for e in errors), errors)

    def test_background_key_is_normalized(self):
        from calforge.ideation.validate import validate_concept

        c = fixtures.concept()
        c["style"]["palette"]["background"] = c["style"]["palette"].pop("paper")
        errors, _ = validate_concept(c, 2027)
        self.assertEqual(errors, [])
        self.assertIn("paper", c["style"]["palette"])


class PrintablePdfTest(unittest.TestCase):
    def test_printable_generates_only_11x8_5(self):
        import fitz
        from calforge.render.build import printable_pdfs

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fmt = load_format()
            png = tmp_path / "m01_month.png"
            Image.new("RGB", tuple(fmt["size_px"]), (200, 200, 200)).save(png)
            out_dir = tmp_path / "digital"
            out_dir.mkdir(parents=True, exist_ok=True)
            old_a4 = out_dir / "calendar_a4.pdf"
            old_a4.write_text("old", encoding="utf-8")

            res = printable_pdfs([png], fmt, out_dir)
            self.assertEqual(len(res), 1)
            pdf_path = res[0]
            self.assertEqual(pdf_path.name, "calendar_11x8_5.pdf")
            self.assertFalse(old_a4.exists())
            self.assertFalse((out_dir / "calendar_a4.pdf").exists())

            doc = fitz.open(pdf_path)
            self.assertEqual(len(doc), 1)
            page = doc[0]
            self.assertAlmostEqual(page.rect.width, 792.0, places=1)
            self.assertAlmostEqual(page.rect.height, 612.0, places=1)
            doc.close()


if __name__ == "__main__":
    unittest.main()
