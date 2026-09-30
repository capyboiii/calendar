"""Soát trang lịch do AI vẽ nguyên trang (grid_mode "ai_page") bằng OCR: đúng thứ tự thứ, mỗi ngày có đúng một lần,
đúng cột thứ và đúng tuần. Sai thì trả lý do để driver gen lại (kèm lời sửa); đúng thì None.

OCR: RapidOCR (onnxruntime, chạy CPU, không cần card đồ hoạ). Quét cả trang trước; ngày nào bị sót (chữ số đơn
mảnh hay bị bỏ qua) thì cắt riêng ô dự kiến của ngày đó ra đọc lại, tránh loại nhầm trang đúng.
Tên tháng thư pháp / năm / nhãn ngày lễ OCR đọc không chắc nên chỉ kiểm lịch - phần quyết định trang đúng hay sai.
"""
from __future__ import annotations

import calendar
import difflib
import re
import threading
from pathlib import Path

import numpy as np
from PIL import Image

WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
_OCR = None
_LOCK = threading.Lock()          # driver chạy nhiều tài khoản song song; một bộ OCR dùng chung


def _ocr(img: Image.Image) -> list[tuple[str, float, float, float]]:
    """[(chữ, tâm x, tâm y, cao)] trên ảnh RGB."""
    return [t[:4] for t in _ocr_scored(img)]


def _ocr_scored(img: Image.Image) -> list[tuple[str, float, float, float, float]]:
    """[(chữ, tâm x, tâm y, cao, độ tin cậy 0..1)]."""
    global _OCR
    with _LOCK:
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        # use_cls=False: bộ xoay chữ hay lật số đơn 180° (9 thành 6)
        res, _ = _OCR(np.asarray(img.convert("RGB"))[:, :, ::-1], use_cls=False)
    out = []
    for box, text, score in res or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append((str(text).strip(), sum(xs) / 4, sum(ys) / 4, max(ys) - min(ys), float(score or 0)))
    return out


MONTHS = [calendar.month_name[i] for i in range(1, 13)]


def title_problem(texts: list[tuple[str, float]], month: int, year: int) -> str | None:
    """Soát tên tháng + năm trên các chữ OCR đọc được phía trên hàng thứ [(chữ, độ tin cậy)].

    Chữ thư pháp OCR hay đọc rớt nét (vd "January" -> "annary"), nên chỉ báo sai khi chắc chắn:
    - thấy rõ tên của THÁNG KHÁC;
    - thấy năm 4 chữ số khác năm đúng;
    - một chữ đọc rất chắc (>=0.95), cùng chữ cái đầu, dài gần bằng tên tháng mà vẫn khác (vd "Febuary")."""
    want = MONTHS[month - 1].lower()
    words = [(re.sub(r"[^a-z]", "", t.lower()), sc) for t, sc in texts]
    words = [(w, sc) for w, sc in words if len(w) >= 3]
    if any(w == want for w, _ in words):
        pass
    else:
        for w, sc in words:
            other = [n for i, n in enumerate(MONTHS) if i != month - 1
                     and difflib.SequenceMatcher(None, w, n.lower()).ratio() >= .88]
            if other and difflib.SequenceMatcher(None, w, want).ratio() < .6:
                return f"sai tên tháng: trang ghi \"{other[0]}\", đúng phải là \"{MONTHS[month - 1]}\""
        for w, sc in words:
            if (sc >= .95 and w[0] == want[0] and abs(len(w) - len(want)) <= 1
                    and difflib.SequenceMatcher(None, w, want).ratio() >= .75):
                return f"sai chính tả tên tháng: \"{w}\", đúng phải là \"{MONTHS[month - 1]}\""
    years = {re.sub(r"\s", "", t) for t, _ in texts if re.fullmatch(r"\d(\s?\d){3}", t.strip())}
    if years and str(year) not in years:
        return f"sai năm: trang ghi {sorted(years)[0]}, đúng phải là {year}"
    return None


def weeks_of(year: int, month: int) -> dict[int, tuple[int, int]]:
    """ngày -> (tuần 0.., cột 0=SUN..6=SAT), tuần bắt đầu Chủ nhật, số hàng tự nhiên (4-6)."""
    cal = calendar.Calendar(firstweekday=6)
    out = {}
    for w, week in enumerate(cal.monthdayscalendar(year, month)):
        for c, d in enumerate(week):
            if d:
                out[d] = (w, c)
    return out


def date_rows(year: int, month: int) -> list[list[str]]:
    """Từng tuần dạng ["", "", "1", ...] - dùng cho prompt."""
    cal = calendar.Calendar(firstweekday=6)
    return [[str(d) if d else "" for d in week] for week in cal.monthdayscalendar(year, month)]


def _weekday_of(text: str) -> int | None:
    t = re.sub(r"[^A-Z]", "", text.upper())
    if not t or len(t) > 9:
        return None
    for i, name in enumerate(WEEKDAYS):
        if t.startswith(name) or difflib.SequenceMatcher(None, t[:3], name).ratio() >= .67:
            return i
    return None


def check_grid_page(path: Path, year: int, month: int) -> str | None:
    img = Image.open(path).convert("RGB")
    toks = _ocr(img)
    expect = weeks_of(year, month)

    # 1) hàng thứ: đủ (>=5/7) và đúng thứ tự trái -> phải
    heads: dict[int, tuple[float, float]] = {}
    for text, x, y, _h in toks:
        i = _weekday_of(text)
        if i is not None and i not in heads:
            heads[i] = (x, y)
    if len(heads) < 5:
        return "lịch sai: không thấy đủ hàng tên thứ SUN..SAT"
    idx = sorted(heads)
    xs = [heads[i][0] for i in idx]
    if xs != sorted(xs):
        return "lịch sai: các thứ không theo thứ tự SUN MON TUE WED THU FRI SAT từ trái sang phải"
    b, a = np.polyfit(idx, xs, 1)                       # x cột = a + b*i
    cols = [a + b * i for i in range(7)]
    header_y = float(np.median([heads[i][1] for i in idx]))

    # 2) các số ngày dưới hàng thứ
    found: dict[int, list[tuple[float, float, float]]] = {}
    for text, x, y, h in toks:
        if y <= header_y or not re.fullmatch(r"\d{1,2}", text):
            continue
        c = int(np.argmin([abs(x - cx) for cx in cols]))
        if abs(x - cols[c]) > .6 * abs(b):
            continue                                    # không nằm trong cột nào: bỏ qua
        found.setdefault(int(text), []).append((x, y, h))
    extra = sorted(n for n in found if n not in expect)
    if extra:
        return f"lịch sai: có số không thuộc tháng này ({', '.join(map(str, extra))})"
    dup = sorted(n for n, v in found.items() if len(v) > 1)
    if dup:
        return f"lịch sai: ngày bị lặp ({', '.join(map(str, dup))})"
    for n, [(x, _y, _h)] in found.items():
        c = int(np.argmin([abs(x - cx) for cx in cols]))
        if c != expect[n][1]:
            return f"lịch sai: ngày {n} nằm ở cột {WEEKDAYS[c]}, đúng phải là {WEEKDAYS[expect[n][1]]}"

    # 3) tuần: các số cùng tuần cùng một hàng, tuần sau nằm dưới tuần trước
    heights = [v[0][2] for v in found.values()] or [20.0]
    hmed = float(np.median(heights))
    week_y: dict[int, list[float]] = {}
    for n, [(_x, y, _h)] in found.items():
        week_y.setdefault(expect[n][0], []).append(y)
    for w, ys in week_y.items():
        if max(ys) - min(ys) > 1.2 * hmed:
            return f"lịch sai: các ngày của tuần {w + 1} không nằm cùng một hàng"
    rows = sorted((w, float(np.median(ys))) for w, ys in week_y.items())
    for (w1, y1), (w2, y2) in zip(rows, rows[1:]):
        if y2 <= y1 + .8 * hmed:
            return f"lịch sai: tuần {w2 + 1} không nằm dưới tuần {w1 + 1}"

    # 4) tên tháng + năm (vùng phía trên hàng thứ, đọc lại ở cỡ x2 cho chữ thư pháp)
    top = img.crop((0, 0, img.width, int(max(header_y - .5 * hmed, 1))))
    top = top.resize((top.width * 2, top.height * 2), Image.LANCZOS)
    texts = [(t, sc) for t, *_xyh, sc in _ocr_scored(top)]
    problem = title_problem(texts, month, year)
    if problem:
        return problem

    # 5) ngày OCR bỏ sót: đọc lại riêng ô dự kiến
    missing = [n for n in expect if n not in found]
    if missing:
        if len(rows) >= 2:
            k, m0 = np.polyfit([w for w, _ in rows], [y for _, y in rows], 1)
        else:
            k, m0 = 3 * hmed, (rows[0][1] if rows else header_y + 3 * hmed)
        for n in missing:
            w, c = expect[n]
            cy = dict(rows).get(w, m0 + k * w)
            half_w, half_h = .45 * abs(b), .55 * abs(k) if k else 1.5 * hmed
            box = (int(cols[c] - half_w), int(cy - half_h), int(cols[c] + half_w), int(cy + half_h))
            crop = img.crop(box)
            crop = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
            digits = [t for t, *_ in _ocr(crop) if re.fullmatch(r"\d{1,2}", t)]
            if str(n) not in digits:
                return f"lịch sai: thiếu ngày {n} (ô {WEEKDAYS[c]} tuần {w + 1})"
    return None
