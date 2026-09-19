import datetime as dt
import unittest

from calforge.core import dates, kjv
from calforge.ideation.extract import extract_json


class DatesTest(unittest.TestCase):
    def test_easter_known_years(self):
        self.assertEqual(dates.easter(2024), dt.date(2024, 3, 31))
        self.assertEqual(dates.easter(2025), dt.date(2025, 4, 20))
        self.assertEqual(dates.easter(2026), dt.date(2026, 4, 5))
        self.assertEqual(dates.easter(2027), dt.date(2027, 3, 28))

    def test_us_holidays_2027(self):
        h = dates.holidays_for(2027, "US")
        self.assertIn("MLK Jr. Day", h[dt.date(2027, 1, 18)])
        self.assertIn("Memorial Day", h[dt.date(2027, 5, 31)])
        self.assertIn("Thanksgiving", h[dt.date(2027, 11, 25)])
        self.assertIn("Mother's Day", h[dt.date(2027, 5, 9)])

    def test_find_holiday_month_is_fuzzy(self):
        self.assertEqual(dates.find_holiday_month("Easter", 2027), [3])
        self.assertEqual(dates.find_holiday_month("easter sunday", 2027), [3])
        self.assertEqual(dates.find_holiday_month("Christmas", 2027), [12])
        self.assertEqual(dates.find_holiday_month("Diwali", 2027), [])

    def test_facts_text_mentions_easter_in_march(self):
        facts = dates.calendar_facts(2027)
        march = next(line for line in facts.splitlines() if "March" in line)
        self.assertIn("Easter 28", march)


class KjvTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(kjv.parse_ref("Mark 4:39"), ("Mark", 4, 39, 39))
        self.assertEqual(kjv.parse_ref("Psalm 23:1-3"), ("Psalms", 23, 1, 3))
        self.assertEqual(kjv.parse_ref("1 John 4:8"), ("1 John", 4, 8, 8))
        self.assertIsNone(kjv.parse_ref("Hezekiah 1:1"))
        self.assertIsNone(kjv.parse_ref("Peace be still"))

    def test_check_ref_rejects_bad_syntax(self):
        self.assertIsNone(kjv.check_ref("John 3:16"))
        self.assertIsNotNone(kjv.check_ref("And he arose, and rebuked the wind"))


class ExtractTest(unittest.TestCase):
    def test_last_fenced_block_wins(self):
        text = 'Schema:\n```json\n{"a": 1}\n```\nAnswer:\n```json\n{"a": 2}\n```'
        self.assertEqual(extract_json(text), {"a": 2})

    def test_bare_json(self):
        self.assertEqual(extract_json('Here you go {"x": [1, 2]} done'), {"x": [1, 2]})

    def test_invalid(self):
        with self.assertRaises(ValueError):
            extract_json("no json here")


if __name__ == "__main__":
    unittest.main()
