import calendar
import datetime as dt
import unittest

from calforge.core.calendar_2027 import WEEKS
from calforge.core.dates import MON, month_cells
from calforge.render.build import load_format
from calforge.render.pages import grid_page
from calforge.render.preflight import check_calendar
from tests.fixtures import concept


class CalendarIntegrityTest(unittest.TestCase):
    def test_stored_2027_has_365_unique_correctly_placed_days(self):
        seen = set()
        for month, weeks in WEEKS.items():
            days = []
            for row, week in enumerate(weeks):
                self.assertEqual(len(week), 7)
                for col, day in enumerate(week):
                    if not day:
                        continue
                    date = dt.date(2027, month, day)
                    self.assertEqual(date.weekday(), col)
                    self.assertEqual(row, (dt.date(2027, month, 1).weekday() + day - 1) // 7)
                    self.assertNotIn(date, seen)
                    seen.add(date)
                    days.append(day)
            self.assertEqual(days, list(range(1, calendar.monthrange(2027, month)[1] + 1)))
            rows, cells = month_cells(2027, month, MON, "natural")
            self.assertEqual(rows, len(weeks))
            self.assertEqual([c[0].day if c else 0 for c in cells], [d for w in weeks for d in w])
        self.assertEqual(len(seen), 365)

    def page(self):
        c = concept()
        c.update(year=2027, market="US", grid_preset="art_matched")
        return grid_page(load_format(), c, 5, "May", "A short verse.")

    def test_preflight_rejects_shifted_date_duplicate_and_wrong_weekday(self):
        p = self.page()
        self.assertEqual(check_calendar(p), [])
        t = next(t for t in p.texts() if t.role == "date" and t.text == "31")
        t.x += (p.grid_box[2] - p.grid_box[0]) / 7
        self.assertTrue(any("sai vị trí" in issue for issue in check_calendar(p)))
        t.text = "30"
        self.assertTrue(any("trùng" in issue for issue in check_calendar(p)))
        next(t for t in p.texts() if t.role == "weekday").text = "SUN"
        self.assertTrue(any("sai thứ" in issue for issue in check_calendar(p)))

    def test_preflight_rejects_holiday_leaving_cell(self):
        p = self.page()
        holiday = next(t for t, _, _ in p.cell_texts if t.role == "holiday")
        holiday.x += (p.grid_box[2] - p.grid_box[0]) / 7
        self.assertTrue(any("tràn khỏi ô" in issue for issue in check_calendar(p)))
