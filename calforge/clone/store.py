"""Hàng đợi của trang "Làm theo ảnh mẫu": projects/.clone_queue/<id>/ (item.json + refs/ + work/).

Mỗi mục = một cuốn. Ảnh vẽ được trước khi có tên cuốn nằm ở work/anh_ai; có tên (ChatGPT đặt) thì chuyển sang thư
mục SKU thật của cuốn (projects/Wall Calendar (Blank)/<nhóm>/<SKU>/) và item.json ghi đường dẫn "book".
Trạng thái: pending | running | done | failed | rejected. Chạy lại chỉ làm phần còn thiếu.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

QUEUE_DIR = ".clone_queue"
MAX_REFS = 10
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_LOCK = threading.Lock()


def root(projects_dir) -> Path:
    return Path(projects_dir) / QUEUE_DIR


def item_dir(projects_dir, item_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{6,20}", item_id or ""):
        raise ValueError("mã mục không hợp lệ")
    return root(projects_dir) / item_id


def refs(d: Path) -> list[Path]:
    return sorted(p for p in (d / "refs").glob("*") if p.suffix.lower() in IMG_EXT)


def read(d: Path) -> dict:
    for i in range(3):
        try:
            data = json.loads((d / "item.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except PermissionError:                         # đang được đổi tên đè (Windows): đọc lại sau một chút
            time.sleep(0.05)
        except (OSError, ValueError):
            return {}
    return {}


def write(d: Path, **kw) -> dict:
    with _LOCK:
        data = {**read(d), **kw, "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
        tmp = d / "item.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        # Windows chặn đổi tên khi file đích đang được mở đọc (giao diện hỏi trạng thái 3 giây/lần, tiến trình
        # khác đang đọc): chờ một chút rồi thử lại, không để cuốn hỏng ngang vì chuyện này.
        for i in range(40):
            try:
                tmp.replace(d / "item.json")
                break
            except PermissionError:
                if i == 39:
                    raise
                time.sleep(0.05)
    return data


def _group(name: str) -> str:
    g = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(name or "")).strip(" .")
    return re.sub(r"\s+", "-", g)[:80].strip("-.").lower() or "lam-theo-mau"


def to_images(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """Mọi loại file ảnh -> ảnh PNG/JPG ChatGPT nhận được. PDF: mỗi trang một ảnh. Ảnh JPG/PNG/WEBP giữ nguyên;
    định dạng khác (TIFF, BMP, GIF, ICO...) đổi sang PNG (khung đầu). Không đọc được -> ValueError."""
    from PIL import Image
    import io
    if data[:5] == b"%PDF-" or name.lower().endswith(".pdf"):
        try:
            import pymupdf
        except ImportError:  # bản cũ của PyMuPDF
            import fitz as pymupdf
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
            out = [(f"{Path(name).stem}-p{i + 1}.png", page.get_pixmap(dpi=150).tobytes("png"))
                   for i, page in enumerate(doc)]
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"{name}: không đọc được file PDF") from e
        if not out:
            raise ValueError(f"{name}: file PDF không có trang nào")
        return out
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            if fmt in ("JPEG", "PNG", "WEBP"):
                im.verify()
                return [(name, data)]
            im.seek(0)
            rgb = im.convert("RGBA" if "A" in im.getbands() else "RGB")
            buf = io.BytesIO()
            rgb.save(buf, "PNG")
            return [(Path(name).stem + ".png", buf.getvalue())]
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{name}: không đọc được ảnh (định dạng này máy chưa hỗ trợ - lưu lại thành JPG/PNG rồi thử)") from e


def add(projects_dir, images: list[tuple[str, bytes]], *, group: str = "", year: int = 2027,
        mockup_mode: str = "ai", kind: str = "normal") -> dict:
    """Thêm một cuốn: 1-10 ảnh tham chiếu (giữ đúng thứ tự tải lên = artwork 1, 2, ...). Nhận mọi loại file ảnh
    (đổi sang PNG khi cần) và PDF (mỗi trang một ảnh)."""
    if not 2024 <= int(year) <= 2100:
        raise ValueError("năm không hợp lệ")
    if not images:
        raise ValueError(f"cần 1 đến {MAX_REFS} ảnh tham chiếu (đang có 0)")
    converted: list[tuple[str, bytes]] = []
    for name, data in images:
        converted += to_images(name, data)
    if not 1 <= len(converted) <= MAX_REFS:
        raise ValueError(f"cần 1 đến {MAX_REFS} ảnh tham chiếu (đang có {len(converted)}"
                         + (" - tính cả từng trang PDF" if len(converted) != len(images) else "") + ")")
    images = converted
    item_id = time.strftime("%y%m%d%H%M%S") + secrets.token_hex(2)
    d = root(projects_dir) / item_id
    (d / "refs").mkdir(parents=True)
    for i, (name, data) in enumerate(images, 1):
        ext = Path(name).suffix.lower()
        ext = ext if ext in IMG_EXT else ".png"
        (d / "refs" / f"ref{i:02d}{ext}").write_bytes(data)
    return write(d, id=item_id, created=time.strftime("%Y-%m-%d %H:%M:%S"), group=_group(group), year=int(year),
                 status="pending", stage="", reason="", book="", title="", names=[n for n, _ in images],
                 mockup_mode=mockup_mode if mockup_mode in ("ai", "template") else "ai", kind="normal")


def items(projects_dir) -> list[dict]:
    r = root(projects_dir)
    out = []
    for d in sorted(r.iterdir(), reverse=True) if r.is_dir() else []:
        if d.is_dir() and (d / "item.json").is_file():
            data = read(d)
            if not data.get("id"):                     # item.json hỏng (tắt máy lúc đang ghi): hiện ra để người dùng xoá
                data = {"id": d.name, "status": "failed", "group": "", "year": "", "stage": "",
                        "reason": "item.json hỏng - xoá cuốn này rồi thêm lại ảnh mẫu"}
            data["refs"] = len(refs(d))
            if data.get("status") in ("running", "failed") and _book_finished(data.get("book")):
                write(d, status="done", reason="")         # trang chính đã hoàn thiện cuốn (Làm tiếp / Hoàn thiện)
                data.update(status="done", reason="")
            out.append(data)
    return out


def _book_finished(book) -> bool:
    """Cuốn đã xong hẳn (status.json của cuốn: ok ở bước listing / printify) - trang chính có thể đã làm nốt."""
    if not book:
        return False
    try:
        st = json.loads((Path(book) / "_he_thong" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(st, dict) and st.get("ok") and st.get("stage") in ("listing", "printify"))


def pending(projects_dir) -> list[Path]:
    """Mục cần chạy (chưa xong, chưa bị loại), cũ trước."""
    r = root(projects_dir)
    return [d for d in sorted(r.iterdir()) if d.is_dir() and read(d).get("status") in ("pending", "failed", "running")] \
        if r.is_dir() else []


def remove(projects_dir, item_id: str, *, running_now: bool = True) -> None:
    """Bỏ một cuốn khỏi hàng đợi. running_now=False: không có lượt clone nào đang chạy thật, nên trạng thái
    "running" chỉ là dấu cũ (bị Dừng / tắt tool giữa chừng) - cho bỏ."""
    d = item_dir(projects_dir, item_id)
    if running_now and read(d).get("status") == "running":
        raise ValueError("cuốn đang chạy - bấm Dừng trước rồi mới bỏ")
    shutil.rmtree(d, ignore_errors=True)


STOPPED = "đã dừng giữa chừng - bấm Làm tiếp để làm phần còn thiếu"


def mark_stopped(projects_dir) -> int:
    """Lượt clone đã dừng (bấm Dừng / tắt tool / tiến trình chết): cuốn còn ghi "running" chuyển về "Bị dở".
    Ảnh đã vẽ giữ nguyên; Làm tiếp chỉ làm phần thiếu."""
    n = 0
    r = root(projects_dir)
    for d in sorted(r.iterdir()) if r.is_dir() else []:
        if d.is_dir() and read(d).get("status") == "running":
            write(d, status="failed", reason=STOPPED)
            n += 1
    return n


def retry(projects_dir, item_id: str) -> None:
    d = item_dir(projects_dir, item_id)
    if read(d).get("status") in ("failed", "rejected"):
        write(d, status="pending", reason="")
