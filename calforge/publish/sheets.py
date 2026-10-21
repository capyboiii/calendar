"""SKU-based Google Sheets sync through the owner's Apps Script web app."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import layout
from . import r2

SPREADSHEET_ID = "1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg"
HEADER = ["SKU", "Description", "Tags", "Title", "Sizes", "Paper", "Design", "Mockup"]
ENDPOINT = re.compile(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec\Z")


class SheetError(RuntimeError):
    pass


def validate_settings(data: dict, *, required: bool = True) -> dict:
    endpoint = str(data.get("endpoint") or "").strip()
    secret = str(data.get("secret") or "").strip()
    if endpoint and not ENDPOINT.fullmatch(endpoint):
        raise SheetError("URL Sheet phải là Web app https://script.google.com/macros/s/.../exec")
    if secret and len(secret) < 32:
        raise SheetError("Khóa Sheet cần ít nhất 32 ký tự.")
    if required and (not endpoint or not secret):
        raise SheetError("Chưa kết nối Google Sheet. Nhập Web app URL và khóa trong Khoá R2 / Sheet.")
    return {"endpoint": endpoint, "secret": secret}


def description_text(listing: dict) -> str:
    from .listing import html_to_text
    from .etsy_listing import DETAILS_TEXT
    text = listing.get("description_text") or html_to_text(listing.get("description", ""))
    # Keep the listing's prose; normalize only the fixed Paper detail (including older listings).
    text = re.sub(r"(?im)^\s*-?\s*(?:Finish|Paper):[^\n]*\n?", "", text).strip()
    paper = "- Paper: Matte or Glossy"
    binding = re.search(r"(?m)^- Binding:", text)
    if binding:
        return text[:binding.start()] + paper + "\n" + text[binding.start():]
    if not re.search(r"(?m)^Details\s*$", text):
        return text + "\n\n" + DETAILS_TEXT.replace("- Finish:", "- Paper:")
    return text + "\n" + paper


def book_rows(cdir: Path, cfg: dict) -> list[list[str]]:
    """Use Crayonahub's actual variant SKUs, irrespective of the CSV button used."""
    from .calendaria_csv import _book_rows
    from .shop_csv import shop_settings
    variants = [r for r in _book_rows(cdir, shop_settings(cfg))
                if r["Variant SKU"] and r["Is Digital"] == "FALSE"]
    if not variants:
        raise SheetError("Không có biến thể in để cập nhật Sheet.")
    listing = json.loads(layout.listing_file(cdir).read_text(encoding="utf-8"))
    first = variants[0]
    base = first["Variant SKU"].rsplit("-", 1)[0]
    files = r2.read_state(cdir).get("files", {})
    mockups = [files[n]["url"] for n in sorted(files) if "/" not in n and n.lower().endswith(".jpg")]
    rows = [[base, description_text(listing), ", ".join(listing.get("tags", [])), listing["title"], "", "", "",
             "\n".join(mockups)]]                       # Mockup: ảnh preview trên R2, mỗi link một dòng
    expected = r2.PAGE_ORDER if r2.ai_grid_book(cdir) else [n for n in r2.PAGE_ORDER if not n.endswith("_grid")]
    for variant in variants:
        urls = variant["Variant Design"].split("|")
        if len(urls) != len(expected) or any(not u.startswith("https://") for u in urls):
            raise SheetError("Design chưa đủ trang; chưa cập nhật Sheet.")
        if [url.rsplit("/", 1)[-1] for url in urls] != [name + ".png" for name in expected]:
            raise SheetError("Design sai thứ tự trang in; chưa cập nhật Sheet.")
        rows.append([variant["Variant SKU"], "", "", "", variant["Option1 Value"].replace('"', ''),
                     variant["Option3 Value"], "\n".join(urls), ""])
    return rows


class _GoogleRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        url = urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in ("script.google.com", "script.googleusercontent.com"):
            raise SheetError("Google Sheet chuyển hướng tới địa chỉ không hợp lệ.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def send(rows: list[list[str]], settings: dict, *, sleep=time.sleep) -> None:
    payload = json.dumps({"version": 1, "spreadsheet_id": SPREADSHEET_ID, "sheet_id": 0,
                          "header": HEADER, "rows": rows, "timestamp": int(time.time())},
                         ensure_ascii=False, separators=(",", ":"))
    signature = hmac.new(settings["secret"].encode(), payload.encode(), hashlib.sha256).hexdigest()
    data = json.dumps({"payload": payload, "signature": signature}, ensure_ascii=False).encode()
    opener = urllib.request.build_opener(_GoogleRedirect())
    for attempt in range(3):
        try:
            request = urllib.request.Request(settings["endpoint"], data=data,
                                             headers={"Content-Type": "application/json"})
            with opener.open(request, timeout=60) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise SheetError("Phản hồi Google Sheet quá lớn.")
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise SheetError("Sheet không trả JSON; kiểm tra quyền truy cập Web app và URL /exec.") from None
            if not isinstance(result, dict) or result.get("ok") is not True:
                # Never include arbitrary remote text, credentials or signed payload in logs.
                code = result.get("code") if isinstance(result, dict) else ""
                if code in ("busy", "write") and attempt < 2:
                    sleep((2, 5)[attempt]); continue
                raise SheetError({"auth": "Sai khóa Sheet hoặc đồng hồ máy lệch quá 10 phút.",
                                  "schema": "Cột Sheet khác format đã chốt; không ghi dữ liệu.",
                                  "duplicate": "Sheet có SKU trùng; cần xử lý dòng trùng trước.",
                                  "busy": "Sheet đang bận; thử lại sau.",
                                  "config": "Apps Script chưa cấu hình đúng Sheet / khóa."}.get(code,
                                 "Google Sheet chưa xác nhận cập nhật; có thể bấm lại để đồng bộ."))
            if result.get("skus") != [row[0] for row in rows]:
                raise SheetError("Sheet chưa xác nhận đủ SKU; sẽ đồng bộ lại theo SKU.")
            return
        except urllib.error.HTTPError as exc:
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise SheetError(f"Google Sheet trả HTTP {exc.code}; dữ liệu chờ đồng bộ.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == 2:
                raise SheetError("Mất kết nối Google Sheet; dữ liệu chờ đồng bộ, không cần đẩy lại R2.") from None
        sleep((2, 5)[attempt])


def sync_books(books: list[Path], cfg: dict, on_event=print) -> dict:
    def emit(message):
        try:
            on_event(message)
        except UnicodeEncodeError:
            # A legacy Windows console must not turn a confirmed sheet write into a pending failure.
            on_event(message.encode("ascii", "backslashreplace").decode())

    result = {"synced": [], "failed": []}
    if not books:
        return result
    raw_settings = cfg.get("sheets") or {}
    for book in books:
        state = r2.read_state(book)
        try:
            settings = validate_settings(raw_settings)
            rows = book_rows(book, cfg)
            fingerprint = hashlib.sha256(json.dumps([settings["endpoint"], SPREADSHEET_ID, rows],
                                                     ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if state.get("sheet_synced_hash") == fingerprint and not state.get("sheet_pending"):
                continue
            state.update(sheet_pending=True, sheet_error="")
            r2.write_state(book, state)
            send(rows, settings)
            state.update(sheet_synced_hash=fingerprint, sheet_synced_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                         sheet_pending=False, sheet_error="")
            r2.write_state(book, state)
            result["synced"].append(book.name)
            emit(f"Sheet: ✔ {book.name}: đã cập nhật {len(rows)} dòng theo SKU")
        except (SheetError, OSError, ValueError, KeyError) as exc:
            reason = str(exc) if isinstance(exc, SheetError) else "Không đọc / lưu được dữ liệu đồng bộ Sheet."
            state.update(sheet_pending=True, sheet_error=reason)
            try:
                r2.write_state(book, state)
            except OSError:
                reason += " Không lưu được trạng thái; lần sau đối chiếu lại theo SKU."
            result["failed"].append(f"{book.name}: {reason}")
            emit(f"Sheet: ✘ {book.name}: {reason}")
    return result
