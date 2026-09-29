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
        region_name="auto", config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"}))


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
    state_file(cdir).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


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


def push_book(cdir: Path, cfg: dict, on_event=print, s3=None) -> dict:
    """Đẩy file của một cuốn lên R2 (bỏ qua file đã đẩy và chưa đổi). Trả về trạng thái r2.json."""
    r2 = settings(cfg)
    s3 = s3 or client(r2)
    st = read_state(cdir)
    key_base = st.get("key_base") or f"{r2['prefix'].strip('/')}/{_group(cdir)}{slug(cdir.parent.name, 40)}/{slug(cdir.name)}"
    files = st.get("files", {})
    base_url = r2["public_url"].rstrip("/")
    todo = []
    todo = []
    for name, path in book_files(cdir).items():
        stat = path.stat()
        old = files.get(name) or {}
        if old.get("size") == stat.st_size and old.get("mtime") == int(stat.st_mtime):
            continue
        todo.append((name, path, stat))
    if todo:
        on_event(f"  ↑ {cdir.name}: {len(todo)} file ({sum(t[2].st_size for t in todo) / 1e6:.0f} MB)")

    def upload(item):
        name, path, stat = item
        key = f"{key_base}/{name}"
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        s3.upload_file(str(path), r2["bucket"], key, ExtraArgs={"ContentType": ctype})
        return name, {"key": key, "url": f"{base_url}/{key}", "size": stat.st_size, "mtime": int(stat.st_mtime)}

    from concurrent.futures import ThreadPoolExecutor

    try:
        with ThreadPoolExecutor(max_workers=int(r2.get("upload_workers", 8))) as pool:
            for name, info in pool.map(upload, todo):   # lỗi một file -> ném ra, cuốn này báo lỗi
                files[name] = info
                on_event(f"  ↑ {cdir.name}/{name}")
    finally:                                            # file đã lên thì ghi nhận, lần sau khỏi đẩy lại
        st.update(key_base=key_base, files=files)
        write_state(cdir, st)
    st.update(key_base=key_base, files=files, pushed_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    write_state(cdir, st)
    return st
