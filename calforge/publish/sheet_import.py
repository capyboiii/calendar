"""Nút "Import xlsx": file dạng Sheet Crayonahub (SKU | Description | Tags | Title | Sizes | Paper | Design | Mockup)
-> mỗi SKU gốc thành một cuốn trong dự án "TM".

Tải về ảnh mockup (preview/), 26 trang in mỗi khổ (11x8.5/, 14x11.5/) và listing. Mọi file ghi vào _he_thong/r2.json
kèm cỡ + giờ sửa nên bấm R2+ / xuất CSV / đồng bộ Sheet không đẩy lại gì. Một cuốn đủ 2 khổ ~650 MB: ổ còn dưới
import_min_free_gb (mặc định 15 GB) thì dừng tải trang in, cuốn vẫn tạo với link R2; giải phóng ổ rồi bấm Import lại
là tải nốt. SKU đã có cuốn trên máy thì không tạo lại; cuốn do Import tạo mà còn thiếu trang in thì tải nốt.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from .. import layout, products, projects as workspaces

PROJECT_NAME = "TM"
HEADER = ["SKU", "Description", "Tags", "Title", "Sizes", "Paper", "Design", "Mockup"]
SIZE_DIRS = {"11 x 8.5": "11x8.5", "14 x 11.5": "14x11.5"}
URL_OK = re.compile(r"https://[A-Za-z0-9.-]+/[^\s]+\Z")
SKU_OK = re.compile(r"[A-Z0-9][A-Z0-9-]{3,40}\Z")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_XLSX = 50_000_000
MAX_IMAGE = 40_000_000


class ImportError_(ValueError):
    pass


# ---------------------------------------------------------------------------
# Đọc xlsx (không cần openpyxl - Python nhúng của bộ cài không có)
# ---------------------------------------------------------------------------
def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path: Path) -> list[list[str]]:
    """Trang tính đầu tiên -> danh sách hàng (chuỗi)."""
    path = Path(path)
    if path.stat().st_size > MAX_XLSX:
        raise ImportError_("File xlsx quá lớn (tối đa 50 MB).")
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ImportError_("File không phải xlsx hợp lệ.") from None
    with z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", NS)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == first.get(REL))
        target = target.lstrip("/")
        sheet = ET.fromstring(z.read(target if target.startswith("xl/") else f"xl/{target}"))
    rows = []
    for row in sheet.iter(f"{{{NS['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", NS):
            kind, v = c.get("t"), c.find("m:v", NS)
            if kind == "s" and v is not None:
                val = shared[int(v.text)]
            elif kind == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            else:
                val = v.text if v is not None and v.text is not None else ""
            cells[_col(c.get("r"))] = val
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def _lines(cell: str) -> list[str]:
    return [u.strip() for u in re.split(r"[\r\n|]+", cell or "") if u.strip()]


def parse_books(rows: list[list[str]]) -> list[dict]:
    """Hàng Sheet -> [{sku, title, description, tags, mockups, designs{"11x8.5": [...], "14x11.5": [...]}}]."""
    if not rows:
        raise ImportError_("File trống.")
    head = [str(h).strip() for h in rows[0]]
    if head[:len(HEADER)] != HEADER:
        raise ImportError_("Cột phải đúng thứ tự: " + " | ".join(HEADER))
    books, by_sku = [], {}
    for raw in rows[1:]:
        r = dict(zip(HEADER, [str(x or "").strip() for x in raw] + [""] * len(HEADER)))
        sku = r["SKU"].upper()
        if not sku:
            continue
        if not SKU_OK.fullmatch(sku):
            raise ImportError_(f"SKU không hợp lệ: {sku[:50]}")
        if r["Title"]:
            if sku in by_sku:
                raise ImportError_(f"SKU gốc bị lặp trong file: {sku}")
            b = {"sku": sku, "title": r["Title"], "description": r["Description"],
                 "tags": [t.strip() for t in r["Tags"].split(",") if t.strip()],
                 "mockups": _lines(r["Mockup"]), "designs": {}}
            by_sku[sku] = b
            books.append(b)
            continue
        base = sku.rsplit("-", 1)[0]
        b = by_sku.get(base)
        size = SIZE_DIRS.get(r["Sizes"].replace('"', "").strip())
        if b is None or size is None:
            continue                                     # dòng biến thể lạc / khổ lạ: bỏ qua
        urls = _lines(r["Design"])
        if urls and size not in b["designs"]:            # Matte / Glossy cùng khổ dùng chung trang in
            b["designs"][size] = urls
    for b in books:
        for u in b["mockups"] + [u for us in b["designs"].values() for u in us]:
            if not URL_OK.fullmatch(u):
                raise ImportError_(f"{b['sku']}: link không hợp lệ: {u[:80]}")
    return books


# ---------------------------------------------------------------------------
# Tạo cuốn
# ---------------------------------------------------------------------------
def existing_skus(projects_root: Path) -> set[str]:
    out = set()
    for b in layout.books(projects_root):
        out.add((layout.book_sku(b) or b.name).upper())
    return out


def tm_project(projects_root: Path) -> Path:
    for p in workspaces.entries(projects_root):
        if p["name"].strip().casefold() == PROJECT_NAME.casefold():
            return workspaces.require(projects_root, p["id"])
    return workspaces.require(projects_root, workspaces.create(projects_root, PROJECT_NAME)["id"])


def _location(book: dict) -> tuple[str, str, str]:
    """(product, thư mục chủ đề, key_base trên R2) suy từ link trang in .../calendars/<loại>/<chủ đề>/<cuốn>/11x8.5/x.png
    (cuốn cũ có thư mục R2 đặt theo tên cuốn chứ không theo SKU, nên lấy phần đứng trước thư mục khổ)."""
    parts = []
    for urls in book["designs"].values():
        p = urlsplit(urls[0]).path.strip("/").split("/")
        if len(p) >= 3 and p[-2] in SIZE_DIRS.values():
            parts = p[:-2]
            break
    if not parts and book["mockups"]:
        parts = urlsplit(book["mockups"][0]).path.strip("/").split("/")[:-1]
    key_base = "/".join(parts)
    topic = parts[-2] if len(parts) >= 2 else "tm"
    group = parts[-3] if len(parts) >= 3 else ""
    product = "wall_premade" if group == "wall-calendar" else "wall_grid"
    return product, re.sub(r"[^a-z0-9-]", "", topic.lower()) or "tm", key_base


def _download(url: str, dest: Path, opener=None) -> int:
    opener = opener or urllib.request.urlopen
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CalForge/1.0"})
            with opener(req, timeout=60) as resp:
                data = resp.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE:
                raise ImportError_(f"ảnh quá lớn: {url[-60:]}")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return len(data)
        except ImportError_:
            raise
        except Exception:  # noqa: BLE001 - mạng chập chờn: thử lại 3 lần
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
        finally:
            tmp.unlink(missing_ok=True)
    return 0


def _html(text: str) -> str:
    import html
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        para = [l for l in lines if not l.lstrip().startswith("- ")]
        bullets = [l.lstrip()[2:] for l in lines if l.lstrip().startswith("- ")]
        if para:
            out.append("<p>" + "<br>".join(html.escape(p) for p in para) + "</p>")
        if bullets:
            out.append("<ul>" + "".join(f"<li>{html.escape(b)}</li>" for b in bullets) + "</ul>")
    return "".join(out)


class DiskFull(RuntimeError):
    pass


def _free_gb(path: Path) -> float:
    import shutil
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free / 2**30


def fetch_designs(cdir: Path, min_free_gb: float, opener=None, workers: int = 8) -> int:
    """Tải các trang in còn thiếu của cuốn (link trong r2.json) vào 11x8.5/ 14x11.5/, ghi cỡ + giờ sửa vào r2.json
    để lần đẩy R2 sau coi là đã có, không đẩy lại. Ổ sắp đầy thì dừng (DiskFull); trang đã tải vẫn giữ."""
    import threading
    from . import r2
    st = r2.read_state(cdir)
    files = st.get("files", {})
    todo = []
    for name, info in files.items():
        if "/" not in name or not name.endswith(".png") or not info.get("url"):
            continue
        dest = cdir / name
        if dest.exists() and info.get("size") == dest.stat().st_size:
            continue
        todo.append((name, info, dest))
    if not todo:
        return 0
    if _free_gb(cdir) < min_free_gb + 0.7:              # một cuốn đủ 2 khổ ~0.65 GB
        raise DiskFull(f"ổ chỉ còn {_free_gb(cdir):.1f} GB trống (giữ lại {min_free_gb:.0f} GB)")
    lock = threading.Lock()

    def one(item):
        _name, info, dest = item
        dest.parent.mkdir(parents=True, exist_ok=True)
        _download(info["url"], dest, opener)
        stat = dest.stat()
        with lock:
            info.update(size=stat.st_size, mtime=int(stat.st_mtime))
    done, errors = 0, []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fut in [pool.submit(one, it) for it in todo]:
                try:
                    fut.result()
                    done += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e)[:120])
    finally:
        st["files"] = files
        r2.write_state(cdir, st)
    if errors:
        raise RuntimeError(f"còn {len(errors)} trang in chưa tải được (bấm Import lại để tải nốt): {errors[0]}")
    return done


def _imported(cdir: Path) -> bool:
    try:
        return json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")).get("source") == "sheet_import"
    except (OSError, ValueError):
        return False


def create_book(book: dict, project: Path, r2_settings: dict | None, opener=None) -> Path:
    product, topic, key_base = _location(book)
    cdir = products.root(project, product) / topic / book["sku"]
    if cdir.exists() and layout.is_book(cdir):
        return cdir
    # Ghi thẳng vào thư mục cuốn, concept.json ghi SAU CÙNG: chưa có concept thì tool chưa coi là cuốn (không hiện,
    # lần Import sau làm tiếp). Không dùng thư mục tạm rồi đổi tên: Windows hay từ chối đổi tên ([WinError 5]) khi
    # trình diệt virus / lập chỉ mục còn giữ ảnh vừa tải.
    work = cdir
    layout.ensure_system(work)
    files = {}
    preview = layout.listing(work)
    preview.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(book["mockups"], 1):
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", urlsplit(url).path.rsplit("/", 1)[-1]) or f"{i:02d}.jpg"
        if not name.lower().endswith(".jpg"):
            name = f"{i:02d}_{Path(name).stem}.jpg"
        dest = preview / name
        _download(url, dest, opener)
        st = dest.stat()
        files[name] = {"key": urlsplit(url).path.lstrip("/"), "url": url, "size": st.st_size, "mtime": int(st.st_mtime)}
    for size, urls in book["designs"].items():
        for url in urls:
            name = f"{size}/{urlsplit(url).path.rsplit('/', 1)[-1]}"
            files[name] = {"key": urlsplit(url).path.lstrip("/"), "url": url}      # link trước; tải xong ghi thêm cỡ
    concept = {"title": book["title"], "cover": {"title": book["title"], "subtitle": ""}, "year": 2027,
               "product": product, "source": "sheet_import", "trademark": True, "keyword": topic}
    listing = {"title": book["title"], "description": _html(book["description"]),
               "description_text": book["description"], "tags": book["tags"]}
    layout.listing_file(work).write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / layout.SYSTEM / layout.SKU_FILE).write_text(book["sku"], encoding="utf-8")
    from . import r2
    state = {"key_base": key_base, "files": files, "pushed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
             "imported": True}
    if r2_settings:
        state["destination"] = {k: r2_settings.get(k, "") for k in ("account_id", "bucket", "prefix", "public_url")}
    r2.write_state(work, state)
    layout.status_file(work).write_text(json.dumps({
        "stage": "listing", "ok": True, "updated": time.strftime("%Y-%m-%d %H:%M:%S"), "pages": 26,
        "note": "tạo từ file Sheet (Import xlsx)"}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp = layout.concept_file(cdir).with_suffix(".tmp")
    tmp.write_text(json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(layout.concept_file(cdir))                   # bước cuối: từ đây mới là một cuốn
    from .listing import write_listing_txt
    write_listing_txt(cdir, listing)
    import shutil                                            # thư mục tạm của bản Import cũ (đổi tên bị từ chối)
    shutil.rmtree(cdir.with_name(f".{book['sku']}.importing"), ignore_errors=True)
    return cdir


def import_file(path: Path, cfg: dict, on_event=print, opener=None, workers: int = 3) -> dict:
    root = Path(cfg["projects_dir"])
    books = parse_books(read_xlsx(path))
    have = existing_skus(root)
    todo = [b for b in books if b["sku"] not in have]
    skipped = [b["sku"] for b in books if b["sku"] in have]
    # cuốn do Import tạo trước đây mà chưa có trang in: tải nốt (không tạo lại)
    refill = {(layout.book_sku(b) or b.name).upper(): b for b in layout.books(root) if _imported(b)}
    min_free = float(cfg.get("import_min_free_gb", 15))
    incomplete = [b["sku"] for b in todo if set(b["designs"]) != set(SIZE_DIRS.values()) or not b["mockups"]]
    on_event(f"File có {len(books)} cuốn: {len(skipped)} SKU đã có trên máy, {len(todo)} cuốn mới "
             f"(ổ còn {_free_gb(root):.0f} GB trống)")
    for sku in incomplete:
        on_event(f"  ⚠ {sku}: thiếu link trang in một khổ hoặc thiếu mockup - vẫn tạo với phần có")
    project = tm_project(root) if todo else None
    try:
        from . import r2
        r2_settings = r2.settings(cfg)
    except Exception:  # noqa: BLE001 - chưa nhập khoá R2: vẫn tạo cuốn, lần đẩy R2 sau tự nhận nơi lưu
        r2_settings = None
    made, failed, filled, full = [], [], [], []

    def one(b):
        try:
            cdir = refill.get(b["sku"]) if b["sku"] in have else create_book(b, project, r2_settings, opener)
            if cdir is None or full:                   # SKU có sẵn không do Import tạo: không đụng
                return b["sku"], None, None if cdir is None else -1
            try:
                return b["sku"], None, fetch_designs(cdir, min_free, opener)
            except DiskFull as e:
                full.append(str(e))
                return b["sku"], None, -1
        except Exception as e:  # noqa: BLE001 - một cuốn lỗi không chặn cuốn khác
            return b["sku"], str(e)[:160], None
    pages = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, (sku, err, n) in enumerate(pool.map(one, books), 1):
            tag = f"[{i}/{len(books)}] {sku}"
            if err:
                failed.append(f"{sku}: {err}")
                on_event(f"  ✘ {tag}: {err}")
                continue
            new = sku not in have
            if new:
                made.append(sku)
            elif n and n > 0:
                filled.append(sku)
            if n and n > 0:
                pages += n
            if new or n:
                on_event(f"  ✔ {tag}" + (f": {n} trang in" if n and n > 0 else
                                         ": chưa tải trang in (ổ sắp đầy)" if n == -1 else ""))
    if full:
        on_event(f"  ⚠ Dừng tải trang in: {full[0]}. Giải phóng ổ rồi bấm Import lại để tải nốt.")
    on_event(f"Xong: tạo {len(made)} cuốn mới trong dự án {PROJECT_NAME}, tải nốt trang in {len(filled)} cuốn, "
             f"{pages} trang in, lỗi {len(failed)}")
    return {"created": made, "skipped": skipped, "failed": failed, "incomplete": incomplete,
            "filled": filled, "pages": pages, "disk_full": bool(full)}
