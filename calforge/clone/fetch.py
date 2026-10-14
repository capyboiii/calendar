"""Lấy ảnh mẫu từ LINK sản phẩm (thay cho dán tay từng ảnh, người dùng yêu cầu 13/10/2026).

Gửi link cho ChatGPT (tài khoản Plus/K12, thinking cao như các bước clone khác) bằng đúng câu người dùng đã làm tay:
nó mở trang sản phẩm, cắt riêng phần artwork rồi gửi lại. Tool tự gom kết quả làm ảnh mẫu refs/ref01..: ảnh ChatGPT
hiện trong chat, hoặc file nó gửi kèm (ZIP / PNG - tải về, giải nén). Từ đây các bước clone (vẽ artwork, trang lịch,
bìa, hậu kỳ) giữ nguyên như khi dán ảnh tay.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from ..imagegen.driver import TempError
from . import session, store

MAX_LINK_REFS = 12            # tối đa 12 artwork (1 tháng 1 ảnh); dán tay vẫn 10
MIN_SIDE = 100                # ảnh nhỏ hơn: biểu tượng. Artwork cắt từ ảnh xem trước Etsy chỉ ~225x165 px

# NGUYÊN VĂN câu người dùng làm tay thành công (13/10/2026). Không đòi ZIP / tên file: bắt đóng gói ZIP thì máy xử lý
# của ChatGPT phải tự tải ảnh gốc từ Etsy (bị chặn). ChatGPT gửi ảnh nào trong chat thì tool tự lưu làm ảnh mẫu
# (gửi kèm file ZIP / PNG thì tải file về). Không cho lối thoát kiểu "không làm được thì trả lời X".
# Thêm (14/10/2026): lấy ẢNH GỐC từ network - lần thử đầu ChatGPT cắt từ ảnh thu nhỏ, artwork chỉ ~225x165 px.
FETCH_PROMPT = """Từ link sản phẩm này, hãy lấy ảnh của sản phẩm, cắt chỉ lấy mỗi artwork rồi gửi tôi: {url}

Tải TRỰC TIẾP từng ảnh gốc theo URL il_fullxfull: lấy link ảnh gallery trên i.etsystatic.com, đổi phần kích thước trong link (vd il_794xN, il_570xN, il_300x300) thành il_fullxfull rồi tải thẳng link đó - đây là file gốc độ phân giải lớn nhất. KHÔNG dùng ảnh thu nhỏ / ảnh preview hiển thị trong gallery. Cắt artwork từ ảnh gốc đó, giữ nguyên độ phân giải, không phóng to, không vẽ lại."""


def valid_url(url: str) -> str:
    """Link sản phẩm hợp lệ (http/https, có tên miền) -> link đã gọt; sai -> ValueError."""
    u = (url or "").strip()
    if not re.fullmatch(r"https?://[^\s/]+\.[^\s/]+(/\S*)?", u, re.I):
        raise ValueError(f"link không hợp lệ: {u[:80] or '(trống)'}")
    return u


def fetch_prompt(url: str) -> str:
    return FETCH_PROMPT.format(url=url)


# ChatGPT hay gửi kèm cả ảnh CHƯA cắt (ảnh gốc Etsy, mockup, ảnh thông tin sản phẩm) trong cùng ZIP - không phải
# artwork, bỏ đi. Tên thư mục / file khác nhau mỗi lần (vd "originals_fullxfull/", "product_information").
NOT_ARTWORK = re.compile(r"original|source|raw|fullxfull|mockup|uncropped|preview|contact|product.?info|information",
                         re.I)


def images_from_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Ảnh artwork đã cắt trong ZIP (bỏ ảnh chưa cắt, thư mục rác của macOS, file ẩn, ảnh quá nhỏ), xếp theo tên tự
    nhiên (2 trước 10). Lọc xong mà không còn ảnh nào (đặt tên lạ) thì lấy lại mọi ảnh."""
    from PIL import Image

    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n
                 and not Path(n).name.startswith(".")]
        cropped = [n for n in names if not NOT_ARTWORK.search(n)]
        names = cropped if any(Path(n).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") for n in cropped) else names
        key = lambda n: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", n)]   # noqa: E731
        for n in sorted(names, key=key):
            raw = z.read(n)
            try:
                for name, img in store.to_images(Path(n).name, raw):
                    with Image.open(io.BytesIO(img)) as im:
                        if min(im.size) >= MIN_SIDE:
                            out.append((name, img))
            except ValueError:
                continue                                     # file không phải ảnh (txt, json...) trong zip: bỏ
    return out


def save_refs(d: Path, images: list[tuple[str, bytes]]) -> int:
    """Ghi ảnh mẫu vào refs/ của mục (thay bộ cũ nếu có). Trả số ảnh đã lưu."""
    images = images[:MAX_LINK_REFS]
    ref_dir = d / "refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    for old in ref_dir.glob("*"):
        old.unlink()
    for i, (name, data) in enumerate(images, 1):
        ext = Path(name).suffix.lower()
        (ref_dir / f"ref{i:02d}{ext if ext in store.IMG_EXT else '.png'}").write_bytes(data)
    store.write(d, names=[n for n, _ in images])
    return len(images)


def fetch_work(b, s, name: str) -> None:
    """Bước "lấy ảnh mẫu từ link" (chạy trong run_stage: hết lượt / lỗi mạng / lỗi trang -> đổi tài khoản như
    các bước khác). ChatGPT không vào được trang -> lỗi tạm, phiên sau (tài khoản khác) thử lại."""
    url = b.item.get("source_url", "")
    b.status(stage="lấy ảnh mẫu từ link")
    mode = session.ensure_work_mode(s.page)
    b.on_event(f"[{name}] gửi link sản phẩm cho ChatGPT (chế độ Work{'' if mode != 'failed' else ' - KHÔNG chuyển được'})"
               f" tách artwork: {url}")
    reply, files = s.ask_files(fetch_prompt(url))
    images: list[tuple[str, bytes]] = []
    seen: set[bytes] = set()
    files = [f for f in files if f[1] and not (f[1] in seen or seen.add(f[1]))]   # cùng một file bấm tải 2 lần: 1
    for fname, data in files:
        if fname.lower().endswith(".zip") or data[:2] == b"PK":
            try:
                images += images_from_zip(data)
            except zipfile.BadZipFile:
                b.on_event(f"[{name}] file zip hỏng: {fname}")
        else:
            try:
                images += store.to_images(fname, data)
            except ValueError:
                pass
    if not images:                                       # không gửi file: lấy ảnh ChatGPT hiện thẳng trong chat
        images = [(f"{i:02d}.png", data) for i, data in enumerate(s.harvest(), 1)]
    if not images:
        raise TempError("ChatGPT chưa gửi artwork nào: " + (reply or "")[-160:].replace("\n", " "))
    n = save_refs(b.d, images)
    b.on_event(f"[{name}] đã lấy {n} artwork từ link làm ảnh mẫu")
