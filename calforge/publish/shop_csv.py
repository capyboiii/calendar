"""Xuất CSV theo mẫu Printify (printify-orders-template.csv, 23 cột) cho các cuốn đã đẩy lên R2.

Mỗi dòng = một bản Spiral của một cuốn (khổ × finish, lọc theo "spiral_finishes": mỗi khổ một loại giấy -> 2 biến thể/cuốn:
lịch tự thiết kế grid 11x8.5 Matte, 14x11.5 Matte; lịch grid in sẵn 11x8.5 Matte, 14x11.5 Glossy):
    External ID = SKU   Label = tên cuốn   Quantity = 1   Print area front = ảnh bìa PNG khổ đó (R2)
Sau 23 cột mẫu thêm 26 cột "Page NN <trang>" = link PNG từng trang của khổ đó (front_cover ... back_cover);
Wall Calendar (grid in sẵn) để trống 12 cột grid (trang grid chỉ dùng cho PDF digital).
Rồi 5 cột "Preview 1..5" = ảnh quảng cáo (dùng chung mọi khổ/finish của cuốn đó).
Cuối cùng 3 cột listing: "Title" (tiêu đề SEO), "Description (HTML)" (mô tả, có phần Details), "Tags".
Các cột mẫu tool không có (người nhận, địa chỉ, Print Provider/Blueprint/Variant ID, vùng in khác) để trống.
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from .. import layout
from . import r2

TEMPLATE = ["External ID", "Label", "Shipping method", "First name", "Last name", "Email", "Phone", "Country",
          "Region", "Address line 1", "Address line 2", "City", "Zip", "Quantity", "Print Provider ID",
          "Blueprint ID", "Variant ID", "Print area back", "Print area front", "Print area neck",
          "Print area left sleeve", "Print area right sleeve", "Print area neck outer"]
# ngoài mẫu Printify: 26 trang in của khổ đó, mỗi cột một trang, đúng thứ tự cuốn lịch
PAGE_COLS = [f"Page {i:02d} {n}" for i, n in enumerate(r2.PAGE_ORDER, 1)]
PREVIEW_COLS = [f"Preview {i}" for i in range(1, 9)]     # tối đa 8 ảnh quảng cáo (AI mockup 8, mockup sẵn 5)
# nội dung listing (giống CSV Calendaria): tiêu đề SEO, mô tả HTML (có phần Details), tag cách nhau dấu phẩy
LISTING_COLS = ["Title", "Description (HTML)", "Tags"]
HEADER = TEMPLATE + PAGE_COLS + PREVIEW_COLS + LISTING_COLS

DEFAULT_SHOP = {
    # theo tên sản phẩm Printify: lịch tự thiết kế grid in trên bản "Blank" (tự cung cấp trang lịch),
    # lịch grid in sẵn là bản "Wall Calendars" có sẵn trang lịch
    "product_category": {"wall_grid": "Wall Calendars (Blank)", "wall_premade": "Wall Calendars"},
    # tiền tố SKU theo loại: WCB = Wall Calendars (Blank), WCP = Wall Calendars có sẵn trang lịch (Premade)
    "sku_prefix": {"wall_grid": "WCB", "wall_premade": "WCP"},
    "type": "Wall Calendar",
    "size_option": "Size",
    "format_option": "Choose your format",
    "finish_option": "Finish",
    # khổ: nhãn hiện cho khách + tiền cộng thêm vào giá bản in (Spiral); bản Printable giá như nhau mọi khổ
    "sizes": [
        {"format_id": "printify_wall_11x8_5", "label": '11" x 8.5"', "sku": "11", "spiral_add": 0.0},
        {"format_id": "printify_wall_14x11_5", "label": '14" x 11.5"', "sku": "14", "spiral_add": 10.0},
    ],
    # giá USD; GBP/CAD = USD × tỉ giá bên dưới (hoặc ghi thẳng "gbp"/"cad" để đặt tay)
    "variants": [
        {"format": "Spiral", "finish": "Matte", "sku": "SM", "price": 29.95, "compare": 39.95},
        {"format": "Spiral", "finish": "Glossy", "sku": "SG", "price": 32.95, "compare": 42.95},
        {"format": "Printable", "finish": "Digital", "sku": "PD", "price": 7.95, "compare": 12.95},
    ],
    # finish bản Spiral được bán theo loại lịch + khổ (bản Printable luôn có ở mọi khổ). Mỗi khổ MỘT loại giấy
    # -> mỗi cuốn đúng 2 biến thể in: 11x8.5 và 14x11.5 (người dùng chốt 03/10/2026; giữ đuôi SKU cũ cho khớp shop)
    "spiral_finishes": {
        "wall_grid": {"11x8.5": ["Matte"], "14x11.5": ["Matte"]},
        "wall_premade": {"11x8.5": ["Matte"], "14x11.5": ["Glossy"]},
    },
    # hệ thống nhập CSV giới hạn 20 file design/biến thể (lịch có 26 trang) -> tạm bỏ trống cột Variant Design;
    # bật lại khi đã chốt cách gom trang
    "include_design": False,
    "gbp_rate": 0.74,
    "cad_rate": 1.40,
}


def shop_settings(cfg: dict) -> dict:
    return {**DEFAULT_SHOP, **(cfg.get("shop") or {})}


def _money(v) -> str:
    return f"{float(v):.2f}"


def _book_rows(cdir: Path, shop: dict) -> list[dict]:
    from .. import products

    listing = json.loads(layout.listing_file(cdir).read_text(encoding="utf-8"))
    try:
        product = products.product_id(json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        product = products.DEFAULT
    finishes = shop["spiral_finishes"].get(product, {})
    files = r2.read_state(cdir).get("files", {})
    pages = {pg.stem for pg in r2.print_pages(cdir, shop["sizes"][0]["format_id"])} or set(r2.PAGE_ORDER)
    previews = [files[n]["url"] for n in sorted(files) if "/" not in n and n.endswith(".jpg")]
    handle = r2.slug(listing["title"], 200)
    code = hashlib.sha1(handle.encode()).hexdigest()[:5].upper()
    initials = "".join(w[0] for w in handle.split("-")[:3]).upper()
    # cuốn mới: SKU gốc lưu sẵn (= tên thư mục); cuốn cũ: tính từ tên như trước để SKU đã đăng bán không đổi
    base_sku = layout.book_sku(cdir) or f"{shop['sku_prefix'].get(product, 'CAL')}-{initials}-{code}"
    rows = []
    for size in shop["sizes"]:
        label = layout.SIZE_LABEL[size["format_id"]]
        cover = (files.get(f"{label}/{r2.PAGE_ORDER[0]}.png") or {}).get("url", "")
        if not cover:
            continue                                 # khổ này chưa có file trên R2 -> bỏ khổ đó
        for v in shop["variants"]:
            if v["format"].lower() == "printable" or v["finish"] not in finishes.get(label, [v["finish"]]):
                continue                             # chỉ bản Spiral, finish được bán ở khổ này
            row = dict.fromkeys(HEADER, "")
            row.update({
                "External ID": f"{base_sku}-{size['sku']}{v['sku']}",
                "Label": listing["title"], "Quantity": "1", "Print area front": cover,
                **{col: (files.get(f"{label}/{n}.png") or {}).get("url", "")
                   for col, n in zip(PAGE_COLS, r2.PAGE_ORDER) if n in pages},
                **dict(zip(PREVIEW_COLS, previews)),
                "Title": listing["title"], "Description (HTML)": listing.get("description", ""),
                "Tags": ", ".join(listing.get("tags", [])),
            })
            rows.append(row)
    return rows


def ready_books(projects_root: Path) -> list[Path]:
    """Cuốn đã làm xong (listing có, trang in có)."""
    out = []
    for b in layout.books(projects_root):
        try:
            st = json.loads(layout.status_file(b).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if st.get("ok") and st.get("stage") in ("listing", "printify") and layout.listing_file(b).exists():
            out.append(b)
    return out


def publish_all(cfg: dict, on_event=print, only: list[Path] | None = None) -> dict:
    """Đẩy lên R2 rồi xuất CSV.

    only = None: mọi cuốn xong; đẩy cuốn chưa đẩy (hoặc có file đổi), CSV chỉ gồm cuốn CHƯA từng xuất.
    only = [cuốn...] (người dùng chọn trên UI): đúng các cuốn đó, CSV gồm tất cả chúng kể cả cuốn đã xuất trước."""
    root = Path(cfg["projects_dir"])
    shop = shop_settings(cfg)
    books = ready_books(root)
    if only is not None:
        chosen = {Path(b).resolve() for b in only}
        books = [b for b in books if b.resolve() in chosen]
    s3 = r2.client(r2.settings(cfg))
    pushed, failed, successful = [], [], []
    for b in books:
        try:
            before = r2.read_state(b).get("pushed_at")
            st = r2.push_book(b, cfg, on_event, s3=s3)
            successful.append(b)
            if st.get("pushed_at") != before:
                pushed.append(b.name)
        except Exception as e:  # noqa: BLE001 - một cuốn lỗi không chặn các cuốn khác
            failed.append(f"{b.name}: {e}")
            on_event(f"  ✘ {b.name}: {e}")
    # chỉ cuốn đẩy R2 TRỌN VẸN lần này mới vào CSV (đẩy dở thì link thiếu / cũ - lần sau đẩy xong mới xuất)
    todo = [b for b in successful if r2.read_state(b).get("files")
            and (only is not None or not r2.read_state(b).get("exported_at"))]
    rows_by_book = {}
    for b in list(todo):
        try:
            rows_by_book[b] = _book_rows(b, shop)
        except Exception as e:  # noqa: BLE001 - listing hỏng: bỏ cuốn đó, không làm hỏng cả file CSV
            todo.remove(b)
            failed.append(f"{b.name}: không dựng được dòng CSV ({type(e).__name__}: {e})")
            on_event(f"  ✘ {b.name}: không dựng được dòng CSV - {e}")
    csv_path = None
    if todo:
        out_dir = root / "_xuat_csv"
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"calendars_{time.strftime('%Y%m%d_%H%M%S')}_printify.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for b in todo:
                for row in rows_by_book[b]:
                    w.writerow(row)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        for b in todo:
            st = r2.read_state(b)
            st.update(exported_at=stamp, exported_csv=csv_path.name)
            r2.write_state(b, st)
    return {"books": len(books), "pushed": pushed, "exported": [b.name for b in todo],
            "csv": str(csv_path) if csv_path else None, "failed": failed}
