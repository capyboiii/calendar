"""Tạo 12 trang grid thiết kế sẵn cho loại lịch "grid in sẵn" (dùng cho PDF in tại nhà).

Kiểu tối giản: nền trắng ngà, tên tháng in hoa đậm bên trái, năm bên phải, hàng thứ Sun..Sat có gạch
chân, luôn 6 hàng ngày; Chủ nhật màu xám, ngày của tháng trước/sau in mờ. Ghi ra
formats/premade_wall_<khổ>/grids/m01.png..m12.png (đúng cỡ trang, 300 DPI).

    python tools/make_premade_grids.py [năm]
"""
from __future__ import annotations

import calendar
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calforge.render import fonts  # noqa: E402
from calforge.render.build import load_format  # noqa: E402
from calforge.render.draw import Page, pdf_to_pngs, write_pdf  # noqa: E402

FORMATS = ["premade_wall_11x8_5", "premade_wall_14x11_5"]
WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

PAPER = "#F5F5F3"
INK = "#1E1E1E"
SUNDAY = "#8C8C8C"
HEADER = "#3C3C3C"
OTHER_MONTH = "#CDCDCD"
RULE = "#D4D4D4"


def month_weeks(year: int, month: int) -> list[list[dt.date]]:
    """Luôn 6 tuần, bắt đầu Chủ nhật (lịch Mỹ)."""
    weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    while len(weeks) < 6:
        start = weeks[-1][-1] + dt.timedelta(days=1)
        weeks.append([start + dt.timedelta(days=i) for i in range(7)])
    return weeks


def grid_page(fmt: dict, year: int, month: int) -> Page:
    W, H = fmt["size_px"]
    title_f = fonts.font("Nunito Sans", "bold")
    body_f = fonts.font("Nunito Sans", "regular")
    page = Page(W, H, "premade_grid", f"m{month:02d} premade grid")
    page.rect(0, 0, W, H, fill=PAPER)

    # Tỉ lệ đo từ mẫu: lề trái chữ tháng ~11.7%, 7 cột cách đều từ 13.5% đến 86.5% bề ngang.
    left, right = 0.117 * W, 0.884 * W
    col0, col_step = 0.135 * W, (0.865 - 0.135) / 6 * W
    page.text(left, 0.165 * H, calendar.month_name[month].upper(), title_f, 0.062 * H, INK, tracking=0.002 * W)
    page.text(right, 0.165 * H, str(year), body_f, 0.036 * H, INK, anchor="end")

    head_y = 0.285 * H
    for i, name in enumerate(WEEKDAYS):
        page.text(col0 + i * col_step, head_y, name, body_f, 0.029 * H,
                  SUNDAY if i == 0 else HEADER, anchor="middle")
    page.line(0.095 * W, 0.305 * H, 0.905 * W, 0.305 * H, RULE, max(2.0, 0.0012 * H))

    row0, row_step = 0.372 * H, 0.0975 * H
    for r, week in enumerate(month_weeks(year, month)):
        for c, day in enumerate(week):
            color = OTHER_MONTH if day.month != month else (SUNDAY if c == 0 else INK)
            page.text(col0 + c * col_step, row0 + r * row_step, str(day.day), body_f, 0.047 * H, color,
                      anchor="middle", role="date")
    return page


def main(year: int) -> None:
    for fid in FORMATS:
        fmt = load_format(fid)
        out_dir = Path(fmt["_dir"]) / fmt.get("premade_grids_dir", "grids")
        out_dir.mkdir(parents=True, exist_ok=True)
        pages = [grid_page(fmt, year, m) for m in range(1, 13)]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "grids.pdf"
            write_pdf(pages, pdf)
            pdf_to_pngs(pdf, [out_dir / f"m{m:02d}.png" for m in range(1, 13)], fmt["dpi"])
        print(f"{fid}: 12 trang grid {year} -> {out_dir}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2027)
