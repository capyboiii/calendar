"""Ngày tháng và ngày lễ — phần phải ĐÚNG tuyệt đối, nên chỉ tính bằng quy tắc, không nhờ AI.

Ngày lễ lưu dạng quy tắc (ngày cố định, thứ X lần thứ N, theo Phục Sinh) để năm nào cũng tự
tính ra. `calendar_facts()` sinh đoạn dữ kiện bơm vào prompt P2 để ChatGPT xếp chủ đề đúng
tháng (ví dụ Phục Sinh 2027 là 28/3, không phải tháng 4).
"""
from __future__ import annotations

import calendar
import datetime as dt

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
MONTH_NAMES = [calendar.month_name[i] for i in range(1, 13)]


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """Thứ `weekday` lần thứ n trong tháng; n = -1 là lần cuối cùng."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def easter(year: int) -> dt.date:
    """Chủ nhật Phục Sinh theo lịch Gregory (thuật toán Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


RULES: dict[str, list[tuple[str, tuple]]] = {
    "US": [
        ("New Year's Day", ("fixed", 1, 1)),
        ("MLK Jr. Day", ("nth", 1, MON, 3)),
        ("Groundhog Day", ("fixed", 2, 2)),
        ("Valentine's Day", ("fixed", 2, 14)),
        ("Presidents' Day", ("nth", 2, MON, 3)),
        ("Ash Wednesday", ("easter", -46)),
        ("Daylight Saving Begins", ("nth", 3, SUN, 2)),
        ("St. Patrick's Day", ("fixed", 3, 17)),
        ("Palm Sunday", ("easter", -7)),
        ("Good Friday", ("easter", -2)),
        ("Easter", ("easter", 0)),
        ("Earth Day", ("fixed", 4, 22)),
        ("Cinco de Mayo", ("fixed", 5, 5)),
        ("Mother's Day", ("nth", 5, SUN, 2)),
        ("Memorial Day", ("nth", 5, MON, -1)),
        ("Pentecost", ("easter", 49)),
        ("Flag Day", ("fixed", 6, 14)),
        ("Juneteenth", ("fixed", 6, 19)),
        ("Father's Day", ("nth", 6, SUN, 3)),
        ("Independence Day", ("fixed", 7, 4)),
        ("Labor Day", ("nth", 9, MON, 1)),
        ("Columbus Day", ("nth", 10, MON, 2)),
        ("Halloween", ("fixed", 10, 31)),
        ("All Saints' Day", ("fixed", 11, 1)),
        ("Daylight Saving Ends", ("nth", 11, SUN, 1)),
        ("Veterans Day", ("fixed", 11, 11)),
        ("Thanksgiving", ("nth", 11, THU, 4)),
        ("Christmas Eve", ("fixed", 12, 24)),
        ("Christmas Day", ("fixed", 12, 25)),
        ("New Year's Eve", ("fixed", 12, 31)),
    ],
    "UK": [
        ("New Year's Day", ("fixed", 1, 1)),
        ("Valentine's Day", ("fixed", 2, 14)),
        ("Mothering Sunday", ("easter", -21)),
        ("Good Friday", ("easter", -2)),
        ("Easter Sunday", ("easter", 0)),
        ("Easter Monday", ("easter", 1)),
        ("Early May Bank Holiday", ("nth", 5, MON, 1)),
        ("Spring Bank Holiday", ("nth", 5, MON, -1)),
        ("Father's Day", ("nth", 6, SUN, 3)),
        ("Summer Bank Holiday", ("nth", 8, MON, -1)),
        ("Halloween", ("fixed", 10, 31)),
        ("Bonfire Night", ("fixed", 11, 5)),
        ("Remembrance Sunday", ("nth", 11, SUN, 2)),
        ("Christmas Day", ("fixed", 12, 25)),
        ("Boxing Day", ("fixed", 12, 26)),
    ],
}

# Bắc bán cầu; tháng -> mùa (dùng để bơm vào prompt và kiểm tra "season_cue")
SEASONS = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
           6: "Summer", 7: "Summer", 8: "Summer", 9: "Autumn", 10: "Autumn", 11: "Autumn"}


def holidays_for(year: int, market: str = "US") -> dict[dt.date, list[str]]:
    out: dict[dt.date, list[str]] = {}
    for name, rule in RULES[market]:
        kind = rule[0]
        if kind == "fixed":
            d = dt.date(year, rule[1], rule[2])
        elif kind == "nth":
            d = nth_weekday(year, *rule[1:])
        elif kind == "easter":
            d = easter(year) + dt.timedelta(days=rule[1])
        else:
            raise ValueError(f"Quy tắc không hợp lệ: {rule}")
        out.setdefault(d, []).append(name)
    return out


def holidays_by_month(year: int, market: str = "US") -> dict[int, list[tuple[int, str]]]:
    by_month: dict[int, list[tuple[int, str]]] = {m: [] for m in range(1, 13)}
    for d, names in sorted(holidays_for(year, market).items()):
        for name in names:
            by_month[d.month].append((d.day, name))
    return by_month


def calendar_facts(year: int, market: str = "US") -> str:
    """Đoạn dữ kiện cố định bơm vào prompt P2."""
    lines = []
    for m, items in holidays_by_month(year, market).items():
        hol = ", ".join(f"{name} {day}" for day, name in items) or "(no major holidays)"
        lines.append(f"- {MONTH_NAMES[m - 1]} ({SEASONS[m]}): {hol}")
    return "\n".join(lines)


def month_cells(year: int, month: int, week_start: int = SUN, rows_mode: str = "split5"):
    """Chia ngày trong tháng vào lưới 7 cột.

    rows_mode "split5": luôn 5 hàng; ngày tràn sang hàng 6 ghép vào ô ngay trên (kiểu 24/31)
    để ô đủ cao cho người mua viết. "fixed6": luôn 6 hàng.
    Trả về (số hàng, danh sách ô); mỗi ô là list dt.date (rỗng = ô trống, 2 ngày = ô ghép).
    """
    first_weekday, ndays = calendar.monthrange(year, month)
    lead = (first_weekday - week_start) % 7
    rows = 5 if rows_mode == "split5" else 6
    cells: list[list[dt.date]] = [[] for _ in range(rows * 7)]
    for day in range(1, ndays + 1):
        idx = lead + day - 1
        if idx >= rows * 7:
            idx -= 7
        cells[idx].append(dt.date(year, month, day))
    return rows, cells


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").replace("  ", " ").strip()


def find_holiday_month(name: str, year: int, market: str = "US") -> list[int]:
    """Các tháng có ngày lễ khớp tên `name` (khớp mềm: chứa nhau sau khi chuẩn hoá)."""
    key = _norm(name)
    if not key:
        return []
    months = set()
    for d, names in holidays_for(year, market).items():
        for n in names:
            nn = _norm(n)
            if key == nn or key in nn or nn in key:
                months.add(d.month)
    return sorted(months)
