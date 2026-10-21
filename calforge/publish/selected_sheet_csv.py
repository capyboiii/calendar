"""Read the catalog Sheet and export complete products selected by base SKU."""
from __future__ import annotations

import csv
import io
import re
import time
import urllib.error
import urllib.request

from .sheets import SPREADSHEET_ID

SOURCE = f'https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0'
MAX_TXT = 200_000
MAX_CSV = 25_000_000
REQUIRED = ('SKU', 'Description', 'Tags', 'Title', 'Sizes', 'Paper', 'Design', 'Mockup')


class SelectionError(ValueError):
    pass


def parse_skus(text: str) -> list[str]:
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_TXT:
        raise SelectionError('File TXT quá lớn (tối đa 200 KB).')
    result = list(dict.fromkeys(line.strip().upper() for line in text.lstrip('\ufeff').splitlines() if line.strip()))
    if not result:
        raise SelectionError('File TXT chưa có SKU. Mỗi dòng cần một mã SKU chung.')
    invalid = [sku for sku in result if not re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)+', sku)]
    if invalid:
        raise SelectionError('TXT không đúng định dạng: mỗi dòng chỉ có một SKU chung, không kèm số thứ tự hay dấu phẩy.')
    return result


def read_sheet(*, sleep=time.sleep) -> str:
    for attempt in range(3):
        try:
            req = urllib.request.Request(SOURCE, headers={'Accept': 'text/csv'})
            with urllib.request.urlopen(req, timeout=25) as response:
                data = response.read(MAX_CSV + 1)
            if len(data) > MAX_CSV:
                raise SelectionError('Sheet quá lớn; chưa xuất CSV.')
            return data.decode('utf-8-sig')
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SelectionError('Chưa đọc được Sheet. Kiểm tra quyền xem của Sheet nguồn.') from None
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise SelectionError(f'Không đọc được Sheet (HTTP {exc.code}). Thử nhập TXT lại sau.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise SelectionError('Mất kết nối khi đọc Sheet. Thử nhập TXT lại sau.') from None
        except UnicodeError:
            raise SelectionError('Sheet không trả dữ liệu CSV UTF-8 hợp lệ.') from None
        sleep((1, 3)[attempt])
    raise SelectionError('Không đọc được Sheet.')  # defensive


def export_selected(text: str, *, sheet_csv: str | None = None) -> dict:
    requested = parse_skus(text)  # reject invalid input before any network request
    source = read_sheet() if sheet_csv is None else sheet_csv
    csv.field_size_limit(max(csv.field_size_limit(), MAX_CSV))
    try:
        table = list(csv.reader(io.StringIO(source.lstrip('\ufeff'), newline=''), strict=True))
    except csv.Error:
        raise SelectionError('Sheet trả CSV không hợp lệ; chưa xuất file.') from None
    if not table or len(set(table[0])) != len(table[0]) or any(c not in table[0] for c in REQUIRED):
        raise SelectionError('Sheet phải có các cột SKU, Description, Tags, Title, Sizes, Paper, Design, Mockup.')
    header, rows = table[0], table[1:]
    sku_col, title_col = header.index('SKU'), header.index('Title')
    rows = [r for r in rows if any(r)]
    if any(len(r) != len(header) for r in rows):
        raise SelectionError('Sheet có hàng thiếu hoặc thừa cột; chưa xuất file.')
    bases = {r[sku_col].strip().upper() for r in rows if r[title_col].strip() and r[sku_col].strip()}
    missing = [s for s in requested if s not in bases]
    if missing:
        shown = ', '.join(missing[:15]) + ('…' if len(missing) > 15 else '')
        raise SelectionError(f'Không tìm thấy {len(missing)} SKU chung trên Sheet: {shown}. Dùng SKU chung, không dùng mã biến thể.')
    chosen = set(requested)
    filtered = []
    seen = set()
    for row in rows:
        sku = row[sku_col].strip().upper()
        # Exact base or exact parent base; WCB-A does not match WCB-AB.
        parent = sku.rsplit('-', 1)[0]
        if sku not in chosen and not (sku not in bases and parent in chosen):
            continue
        if sku in seen:
            raise SelectionError(f'Sheet có SKU trùng: {sku}. Chưa xuất file để tránh nhầm dữ liệu.')
        seen.add(sku)
        filtered.append(row)
    output = io.StringIO(newline='')
    csv.writer(output).writerows([header, *filtered])
    return {'csv': '\ufeff' + output.getvalue(), 'products': len(requested), 'rows': len(filtered),
            'filename': f'calendars_da_chon_{time.strftime("%Y%m%d_%H%M%S")}.csv'}
