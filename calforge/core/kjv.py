"""Tra câu Kinh Thánh bản King James (phạm vi công cộng ở Mỹ).

ChatGPT chỉ được chọn MÃ câu (vd "Mark 4:39"); lời câu luôn lấy từ bộ dữ liệu ở đây, vì LLM
hay trích sai. Bộ dữ liệu đặt ở data/kjv.json dạng {"Mark": {"4": {"39": "text"}}}.
Chưa có file thì vẫn kiểm được tên sách và cú pháp, chỉ không kiểm được câu có tồn tại không.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "kjv.json"

BOOKS = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth",
    "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
    "Nehemiah", "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon",
    "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah",
    "Malachi", "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
    "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians", "1 Thessalonians",
    "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews", "James",
    "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation",
]
ALIASES = {"psalm": "Psalms", "song of songs": "Song of Solomon", "revelations": "Revelation"}

REF_RE = re.compile(r"^\s*((?:[123]\s)?[A-Za-z][A-Za-z ]*?)\s+(\d+):(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_ref(ref: str) -> tuple[str, int, int, int] | None:
    """'Mark 4:39' -> ('Mark', 4, 39, 39); 'Psalm 23:1-3' -> ('Psalms', 23, 1, 3)."""
    m = REF_RE.match(ref or "")
    if not m:
        return None
    raw, ch, v1, v2 = m.group(1).strip(), int(m.group(2)), int(m.group(3)), m.group(4)
    book = ALIASES.get(raw.lower()) or next((b for b in BOOKS if b.lower() == raw.lower()), None)
    if not book:
        return None
    return book, ch, v1, int(v2) if v2 else v1


@lru_cache(maxsize=1)
def _load() -> dict | None:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return None


def has_dataset() -> bool:
    return _load() is not None


def lookup(ref: str) -> str | None:
    """Lời câu theo KJV, hoặc None nếu mã sai / không có bộ dữ liệu."""
    parsed = parse_ref(ref)
    data = _load()
    if not parsed or data is None:
        return None
    book, ch, v1, v2 = parsed
    chapter = data.get(book, {}).get(str(ch))
    if not chapter or v2 < v1:
        return None
    verses = [chapter.get(str(v)) for v in range(v1, v2 + 1)]
    if any(v is None for v in verses):
        return None
    return " ".join(verses)


def check_ref(ref: str) -> str | None:
    """None nếu hợp lệ, ngược lại là câu mô tả lỗi (dùng cho prompt sửa lỗi)."""
    parsed = parse_ref(ref)
    if not parsed:
        return f'"{ref}" is not a valid KJV reference like "Mark 4:39" or "Psalms 23:1-3"'
    if has_dataset() and lookup(ref) is None:
        return f'"{ref}" does not exist in the King James Version'
    return None
