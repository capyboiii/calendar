"""Tự sửa lỗi dàn trang: trang không qua kiểm tra trước in (vd tên ngày lễ quá dài tràn khỏi ô) thì dựng lại với chữ
nhỏ dần cho tới khi qua - "Làm tiếp" trước đây dàn lại y hệt nên lỗi mãi (người dùng báo 14/10/2026)."""
import copy
import datetime as dt
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout
from calforge.core import dates
from calforge.render import build, draw, pages
from calforge.render.build import load_format
from calforge.render.preflight import check_page

from tests import fixtures

LONG = "INDEPENDENCEREMEMBRANCEDAY"         # một từ rất dài: không xuống dòng được, chỉ co chữ mới vừa


def long_holidays(year, market="US"):
    out = dict(dates.holidays_for.__wrapped__(year, market)) if hasattr(dates.holidays_for, "__wrapped__") \
        else dict(REAL(year, market))
    out[dt.date(year, 3, 18)] = [LONG, LONG]
    return out


REAL = dates.holidays_for


def concept_bg():
    c = fixtures.concept()
    c["year"] = 2027
    c["style"]["grid_mode"] = "background"
    c["grid_preset"] = c["style"]["grid_preset"] = "art_matched"      # kiểu duy nhất soát chữ trong ô ngày
    return c


class AutoFitTest(unittest.TestCase):
    def test_long_holiday_fits_cell_at_min_print_size(self):
        """Tên lễ quá dài (font rộng / 1 từ dài): giữ cỡ nhỏ nhất in được (6pt), cắt bớt + "…" cho nằm gọn trong ô."""
        fmt = load_format("printify_wall_11x8_5")
        with mock.patch.object(dates, "holidays_for", long_holidays):
            p = pages.grid_page(fmt, concept_bg(), 3, "m03 grid", None)
        self.assertEqual(check_page(p, fmt), [])
        hol = [t for t in p.texts() if t.role == "holiday" and t.text.startswith("INDEP")]
        self.assertTrue(hol and all(t.text.endswith("…") for t in hol), [t.text for t in hol])
        self.assertTrue(all(t.size >= draw.MIN_TEXT_PX - 0.01 for t in hol))

    def test_render_concept_fixes_page_and_passes_preflight(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(dates, "holidays_for", long_holidays):
            c = Path(tmp) / "kw" / "WCB-FIT-AAAAA"
            layout.ensure_system(c)
            layout.concept_file(c).write_text(json.dumps(concept_bg()), encoding="utf-8")
            raw = layout.raw(c)
            raw.mkdir(parents=True)
            for j in ["cover", "anchor", "grid"] + [f"m{m:02d}" for m in range(1, 13)]:
                Image.new("RGB", (1536, 1024), (180, 150, 120)).save(raw / f"{j}.png")
            r = build.render_concept(c, months=[3], format_id="printify_wall_11x8_5", digital=False)
            self.assertFalse([i for i in r["issues"] if "m03" in i], r["issues"])     # "Làm tiếp" giờ qua được

    def test_scale_is_per_thread(self):
        seen = {}

        def other():
            p = draw.Page(100, 100, "grid")
            seen["size"] = p.text(0, 0, "x", "Helvetica", 80, "#000").size
        with draw.text_scale(0.5):
            t = threading.Thread(target=other)
            t.start()
            t.join()
            here = draw.Page(100, 100, "grid").text(0, 0, "x", "Helvetica", 80, "#000").size
        self.assertEqual(seen["size"], 80)                            # luồng khác (cuốn khác) không bị co
        self.assertEqual(here, 40)
        self.assertEqual(draw.Page(100, 100, "grid").text(0, 0, "x", "Helvetica", 40, "#000").size, 40)

    def test_scale_never_goes_below_min_print_size(self):
        with draw.text_scale(0.5):
            big = draw.Page(100, 100, "grid").text(0, 0, "x", "Helvetica", 200, "#000").size
            small = draw.Page(100, 100, "grid").text(0, 0, "x", "Helvetica", 25, "#000").size
        self.assertEqual(big, 100)                                         # chữ to: co được
        self.assertEqual(small, 25)                                        # chữ đã ở 6pt: giữ nguyên



class CrashRetryTest(unittest.TestCase):
    """Lỗi bất ngờ TẠM THỜI (thiếu RAM, Chrome sập, mạng, file bị khoá) tự làm lại ngay; lỗi code thì không làm lại."""
    def call(self, errors):
        from calforge import pipeline
        calls = []

        def fn(cdir, cfg, on_event=print):
            calls.append(1)
            if errors:
                raise errors.pop(0)
            return {"ok": True}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline.time, "sleep", lambda s: None):
            c = Path(tmp) / "b"
            layout.ensure_system(c)
            res = pipeline._safe_call(fn, c, {"crash_retry_waits_s": [1, 2]}, lambda *_: None)
        return res, len(calls)

    def test_transient_errors_are_retried(self):
        for err in (MemoryError(), PermissionError("[WinError 32] being used by another process"),
                    RuntimeError("Target page, context or browser has been closed"), TimeoutError("timed out")):
            res, n = self.call([err])
            self.assertEqual((res.get("ok"), n), (True, 2), err)

    def test_gives_up_after_retries(self):
        res, n = self.call([MemoryError(), MemoryError(), MemoryError()])
        self.assertEqual((res.get("stage"), n), ("crash", 3))

    def test_code_bug_is_not_retried(self):
        res, n = self.call([KeyError("grid")])
        self.assertEqual((res.get("stage"), n), ("crash", 1))


if __name__ == "__main__":
    unittest.main()
