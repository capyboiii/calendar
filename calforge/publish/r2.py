"""Đẩy file của từng cuốn lên Cloudflare R2 (API tương thích S3) để CSV sản phẩm trỏ tới.

Mỗi cuốn đẩy:
- preview/*.jpg                         5 ảnh quảng cáo           -> Image Src / Variant Image
- in_tai_nha_<khổ>.pdf                  PDF in tại nhà            -> Variant File (biến thể Printable)   } mỗi khổ
- <khổ>/<trang>.png                     26 trang PNG cho Printify in -> Variant Design (biến thể Spiral,  } 11x8.5, 14x11.5
                                        nối bằng "|" theo thứ tự cuốn)

Khoá R2 nằm trong calforge.json (đã gitignore) mục "r2". Trạng thái đã đẩy lưu ở _he_thong/r2.json của cuốn
(URL + cỡ + mtime từng file): chạy lại chỉ đẩy file mới/đổi.
"""
from __future__ import annotations

import json
import mimetypes
import re
import time
from pathlib import Path


from .. import layout

STATE = "r2.json"
REQUIRED = ("account_id", "access_key_id", "secret_access_key", "bucket", "public_url")


class R2Error(RuntimeError):
    pass


def settings(cfg: dict) -> dict:
    r2 = dict(cfg.get("r2") or {})
    missing = [k for k in REQUIRED if not str(r2.get(k) or "").strip()]
    if missing:
        raise R2Error("Chưa nhập khoá R2: " + ", ".join(missing))
    r2.setdefault("prefix", "calendars")
    return r2


def client(r2: dict):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=f"https://{r2['account_id'].strip()}.r2.cloudflarestorage.com",
        aws_access_key_id=r2["access_key_id"].strip(), aws_secret_access_key=r2["secret_access_key"].strip(),
        region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"},
                                         max_pool_connections=128,   # nhiều cuốn x nhiều file đẩy cùng lúc
                                         connect_timeout=30, read_timeout=180))   # mạng chậm: chờ lâu, đừng vội lỗi


# Mỗi file chỉ 2 luồng con (mặc định boto3 là 10/file: 60 file x 10 làm nghẽn đường upload nhỏ)
TRANSFER = dict(multipart_threshold=16 * 1024 * 1024, multipart_chunksize=8 * 1024 * 1024, max_concurrency=2)
# Lỗi khoá / bucket: thử lại vô ích -> báo ngay. Còn lại (mạng, hết giờ, 5xx, bị bóp) -> giảm luồng + thử lại.
FATAL_CODES = {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "NoSuchBucket", "InvalidBucketName"}


class Throttle:
    """Cổng chung cho mọi file đang tải lên (mọi cuốn): mạng không đủ (lỗi / hết giờ) thì hạ một nửa số file chạy
    cùng lúc; tải thành công liên tiếp thì mở thêm dần tới `maximum`. Bắt đầu thấp rồi tăng (khởi động chậm)."""

    def __init__(self, maximum: int, start: int = 4):
        import threading
        self.maximum = max(1, int(maximum))
        self.limit = min(self.maximum, max(1, int(start)))
        self.active = 0
        self.streak = 0
        self.cv = threading.Condition()

    def acquire(self) -> None:
        with self.cv:
            while self.active >= self.limit:
                self.cv.wait(1.0)
            self.active += 1

    def release(self, ok: bool) -> int:
        """Trả số luồng mới (để báo lên log khi bị hạ)."""
        with self.cv:
            self.active -= 1
            if ok:
                self.streak += 1
                if self.streak >= self.limit and self.limit < self.maximum:
                    self.limit += 1
                    self.streak = 0
            else:
                self.limit = max(1, self.limit // 2)
                self.streak = 0
            self.cv.notify_all()
            return self.limit


def _fatal(e: Exception) -> bool:
    code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
    return code in FATAL_CODES


def slug(text: str, max_len: int = 80) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len].rstrip("-") or "calendar"


def state_file(cdir: Path) -> Path:
    return layout.system(cdir) / STATE


def read_state(cdir: Path) -> dict:
    try:
        return json.loads(state_file(cdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(cdir: Path, st: dict) -> None:
    import os
    import tempfile
    target = state_file(cdir)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="r2-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(st, ensure_ascii=False, indent=2))
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


PAGE_ORDER = ["front_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")] + ["back_cover"]


def print_pages(cdir: Path, format_id: str) -> list[Path]:
    """Trang PNG upload Printify của một khổ, đúng thứ tự cuốn lịch. Lịch grid in sẵn chỉ 14 trang tranh: trang
    grid của nó chỉ để ghép PDF bản digital, không đưa lên in."""
    d = layout.print_dir(cdir, format_id)
    names = PAGE_ORDER if ai_grid_book(cdir) else [n for n in PAGE_ORDER if not n.endswith("_grid")]
    return [d / f"{n}.png" for n in names if (d / f"{n}.png").exists()]


def ai_grid_book(cdir: Path) -> bool:
    """Cuốn có trang grid riêng để in (Wall Calendar (Blank)); grid in sẵn (Wall Calendar) thì không."""
    import json
    from .. import products
    try:
        return products.ai_grid(json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return True


SIZES = ["printify_wall_11x8_5", "printify_wall_14x11_5"]   # thư mục 11x8.5/ 14x11.5/ (loại grid in sẵn dùng chung)


def book_files(cdir: Path, sizes: list[str] | None = None) -> dict[str, Path]:
    """Tên trên R2 -> file cục bộ: 5 preview + mỗi khổ PDF in tại nhà (bản digital) và các trang PNG
    cho Printify in (<khổ>/<trang>.png)."""
    files = {p.name: p for p in sorted(layout.listing(cdir).glob("*.jpg"))}
    for fid in sizes or SIZES:
        pages = print_pages(cdir, fid)
        if not pages:
            continue                               # khổ chưa render: CSV không có biến thể khổ đó
        label = layout.SIZE_LABEL[fid]
        printable = layout.printable_file(cdir, fid)
        if printable.exists():
            files[printable.name] = printable
        for pg in pages:
            files[f"{label}/{pg.name}"] = pg
    return files


def _group(cdir: Path) -> str:
    """"wall-calendar-blank/" | "wall-calendar/" theo thư mục loại lịch (projects/<loại>/<chủ đề>/<cuốn>)."""
    from .. import products
    top = cdir.parent.parent.name
    return f"{slug(top, 40)}/" if top in {v["folder"] for v in products.PRODUCTS.values()} else ""


def push_books(books: list[Path], cfg: dict, on_event=print, s3=None) -> tuple[list[str], list[str], list[Path]]:
    """Đẩy nhiều cuốn SONG SONG (mặc định 6 cuốn cùng lúc x 10 luồng file mỗi cuốn; cấu hình r2.book_workers).
    Một cuốn lỗi không chặn cuốn khác. Trả (tên cuốn vừa đẩy mới, lỗi, cuốn đẩy trọn vẹn) - giữ thứ tự `books`."""
    from concurrent.futures import ThreadPoolExecutor

    s3 = s3 or client(settings(cfg))
    r2 = settings(cfg)
    workers = max(1, int(r2.get("book_workers", 6)))
    # một cổng chung cho mọi cuốn: tổng số file tải cùng lúc tự co giãn theo băng thông thật
    gate = Throttle(int(r2.get("max_uploads", workers * int(r2.get("upload_workers", 10)))))

    def one(b):
        try:
            before = read_state(b).get("pushed_at")
            st = push_book(b, cfg, on_event, s3=s3, gate=gate)   # boto3 client dùng chung giữa các luồng được
            return b, st.get("pushed_at") != before, None
        except Exception as e:  # noqa: BLE001 - một cuốn lỗi không chặn các cuốn khác
            on_event(f"  ✘ {b.name}: {e}")
            return b, False, f"{b.name}: {e}"
    pushed, failed, successful = [], [], []
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(books)))) as pool:
        for b, fresh, err in pool.map(one, books):
            if err:
                failed.append(err)
                continue
            successful.append(b)
            if fresh:
                pushed.append(b.name)
    return pushed, failed, successful


def push_book(cdir: Path, cfg: dict, on_event=print, s3=None, gate: Throttle | None = None,
              sleep=time.sleep) -> dict:
    """Đẩy file của một cuốn lên R2 (bỏ qua file đã đẩy và chưa đổi). Trả về trạng thái r2.json.
    Mạng không đủ: KHÔNG bỏ file - giảm số file tải cùng lúc, nghỉ tăng dần rồi thử lại file đó (r2.upload_retries
    lần, mặc định 8). File nào đã lên được ghi nhận ngay; hết lượt thử mà vẫn thiếu thì báo lỗi cuốn, lần đẩy sau
    chỉ đẩy nốt phần thiếu."""
    import random

    r2 = settings(cfg)
    s3 = s3 or client(r2)
    gate = gate or Throttle(int(r2.get("upload_workers", 10)))
    tries = max(1, int(r2.get("upload_retries", 8)))
    st = read_state(cdir)
    destination = {k: r2.get(k, "") for k in ("account_id", "bucket", "prefix", "public_url")}
    if st.get("destination") != destination:
        st = {"destination": destination}
    key_base = st.get("key_base") or f"{r2['prefix'].strip('/')}/{_group(cdir)}{slug(cdir.parent.name, 40)}/{slug(cdir.name)}"
    files = st.get("files", {})
    base_url = r2["public_url"].rstrip("/")
    todo = []
    for name, path in book_files(cdir).items():
        stat = path.stat()
        old = files.get(name) or {}
        if old.get("size") == stat.st_size and old.get("mtime") == int(stat.st_mtime):
            continue
        todo.append((name, path, stat))
    if todo:
        on_event(f"  ↑ {cdir.name}: {len(todo)} file ({sum(t[2].st_size for t in todo) / 1e6:.0f} MB)")

    try:
        from boto3.s3.transfer import TransferConfig
        transfer = {"Config": TransferConfig(**TRANSFER)}
    except ImportError:                                 # test dùng S3 giả, không có boto3
        transfer = {}

    def upload(item):
        name, path, stat = item
        key = f"{key_base}/{name}"
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        for attempt in range(1, tries + 1):
            gate.acquire()
            try:
                s3.upload_file(str(path), r2["bucket"], key, ExtraArgs={"ContentType": ctype}, **transfer)
            except Exception as e:  # noqa: BLE001
                now = gate.release(False)
                if _fatal(e) or attempt == tries:
                    raise
                wait = min(120, 5 * 2 ** (attempt - 1)) * random.uniform(.8, 1.2)
                on_event(f"  ⏳ {cdir.name}/{name}: mạng chậm / lỗi ({str(e)[:70]}) - giảm còn {now} file cùng lúc, "
                         f"thử lại sau {wait:.0f}s ({attempt}/{tries})")
                sleep(wait)
                continue
            gate.release(True)
            return name, {"key": key, "url": f"{base_url}/{key}", "size": stat.st_size, "mtime": int(stat.st_mtime)}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    errors = []
    lock = __import__("threading").Lock()
    try:
        with ThreadPoolExecutor(max_workers=int(r2.get("upload_workers", 10))) as pool:
            jobs = {pool.submit(upload, item): item[0] for item in todo}
            for fut in as_completed(jobs):              # file nào xong ghi nhận ngay, file lỗi không làm mất file khác
                try:
                    name, info = fut.result()
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{jobs[fut]}: {str(e)[:120]}")
                    continue
                with lock:
                    files[name] = info
                    st.update(key_base=key_base, files=files)
                    write_state(cdir, st)
                on_event(f"  ↑ {cdir.name}/{name}")
    finally:                                            # file đã lên thì ghi nhận, lần sau khỏi đẩy lại
        st.update(key_base=key_base, files=files)
        write_state(cdir, st)
    if errors:
        raise R2Error(f"còn {len(errors)} file chưa lên sau {tries} lần thử (lần đẩy sau làm nốt): {errors[0]}")
    st.update(key_base=key_base, files=files)
    if todo or not st.get("pushed_at"):
        st["pushed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_state(cdir, st)
    from .listing import clean_listing_txt
    if clean_listing_txt(cdir):
        on_event(f"  ✔ {cdir.name}: đã gọn listing.txt (bỏ SKU Printable và DESIGN URLS)")
    return st
