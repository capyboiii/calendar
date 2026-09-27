"""Verify actual PDF date glyph positions, independent of the renderer's date table.

Usage: python -m tools.verify_calendar_render <concept-dir>
"""
import argparse
import calendar
import datetime as dt
import json
from collections import Counter
from pathlib import Path

import pymupdf


def verify(root: Path) -> dict:
    audit = json.loads((root / "render/calendar_audit.json").read_text(encoding="utf-8"))
    results = []
    issues = []
    with pymupdf.open(root / "render/pages.pdf") as pdf:
        if len(pdf) != 26 or len(audit) != 12:
            raise ValueError("Full-book verification requires 26 pages and 12 month records")
        for record in audit:
            year, month, rows, start = (record[k] for k in ("year", "month", "rows", "week_start"))
            page = pdf[month * 2]
            x0, y0, x1, y1 = [v * 72 / 300 for v in record["grid_box_px"]]
            # Widely tracked year / scripture references can extract as separate digits.
            # They live above the calendar. A date misplaced above it is caught as missing.
            words = [w for w in page.get_text("words") if w[4].isdigit()
                     and 1 <= int(w[4]) <= 31 and (w[1] + w[3]) / 2 >= y0]
            ndays = calendar.monthrange(year, month)[1]
            errors = []
            if Counter(w[4] for w in words) != Counter(str(d) for d in range(1, ndays + 1)):
                errors.append("PDF contains missing or duplicate date numbers")
            cw, ch = (x1 - x0) / 7, (y1 - y0) / rows
            lead = (dt.date(year, month, 1).weekday() - start) % 7
            for w in words:
                day = int(w[4])
                row, col = divmod(lead + day - 1, 7)
                if not (w[0] >= x0 + cw * col and w[2] <= x0 + cw * (col + 1)
                        and w[1] >= y0 + ch * row and w[3] <= y0 + ch * (row + 1)):
                    errors.append(f"PDF date {day} is outside its correct cell")
            results.append({"month": month, "days": len(words), "issues": errors})
            issues.extend(f"month {month}: {error}" for error in errors)
    result = {"passed": not issues, "verified_days": sum(r["days"] for r in results),
              "months": results, "issues": issues}
    (root / "render/calendar_pdf_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("concept_dir", type=Path)
    args = parser.parse_args()
    result = verify(args.concept_dir)
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
