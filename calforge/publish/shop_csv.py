"""Xuất CSV sản phẩm (định dạng batch_*_products.csv: kiểu Shopify, 25 cột) cho các cuốn đã đẩy lên R2.

Mỗi cuốn = 1 sản phẩm, các biến thể theo khổ + 4 dòng ảnh phụ. Finish bản Spiral lọc theo "spiral_finishes":
lịch tự thiết kế grid: 11x8.5 Matte, 14x11.5 Matte + Glossy; lịch grid in sẵn: 11x8.5 Matte, 14x11.5 Glossy. Với mỗi khổ (Size = 11" x 8.5" | 14" x 11.5"):
    Choose your format = Spiral    / Finish = Matte    -> Variant Design = các trang PNG khổ đó, nối bằng |
    Choose your format = Spiral    / Finish = Glossy   -> Variant Design = các trang PNG khổ đó, nối bằng |
    Choose your format = Printable / Finish = Digital  -> Variant File   = PDF in tại nhà khổ đó (R2)
Dòng đầu mang Title, Body (HTML), Tags...; ảnh preview 1 ở Image Src, ảnh 2-5 là các dòng chỉ có Handle + Image Src.
Giá, danh mục, loại chỉnh trong calforge.json mục "shop" (xem DEFAULT_SHOP).
"""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from .. import layout
from . import r2

HEADER = ["Handle", "Title", "Body (HTML)", "Product Category", "Type", "Tags", "Is Digital", "Is Trademark",
          "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value",
          "Variant SKU", "Variant Price", "Variant Compare At Price", "Variant Price GBP",
          "Variant Compare At Price GBP", "Variant Price CAD", "Variant Compare At Price CAD", "Image Src",
          "Variant Image", "Variant File", "Variant Design"]

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
    # finish bản Spiral được bán theo loại lịch + khổ (bản Printable luôn có ở mọi khổ)
    "spiral_finishes": {
        "wall_grid": {"11x8.5": ["Matte"], "14x11.5": ["Matte", "Glossy"]},
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
    st = r2.read_state(cdir)
    files = st.get("files", {})
    previews = [files[n]["url"] for n in sorted(files) if n.endswith(".jpg")]
    handle = r2.slug(listing["title"], 200)
    code = hashlib.sha1(handle.encode()).hexdigest()[:5].upper()
    initials = "".join(w[0] for w in handle.split("-")[:3]).upper()
    rows = []
    for size in shop["sizes"]:
        label = layout.SIZE_LABEL[size["format_id"]]
        design = "|".join(files[f"{label}/{n}.png"]["url"] for n in r2.PAGE_ORDER
                          if f"{label}/{n}.png" in files)          # trang PNG cho Printify, đúng thứ tự
        printable = (files.get(f"in_tai_nha_{label}.pdf") or {}).get("url", "")
        if not design:
            continue                                 # khổ này chưa có file trên R2 -> không bán khổ đó
        for v in shop["variants"]:
            spiral = v["format"].lower() != "printable"
            if spiral and v["finish"] not in finishes.get(label, [v["finish"]]):
                continue                             # finish này không bán ở khổ này (theo loại lịch)
            add = float(size.get("spiral_add", 0)) if spiral else float(size.get("printable_add", 0))
            price, compare = float(v["price"]) + add, float(v["compare"]) + add
            row = dict.fromkeys(HEADER, "")
            row.update({
                "Handle": handle,
                "Option1 Value": size["label"], "Option2 Value": v["format"], "Option3 Value": v["finish"],
                "Variant SKU": f"{shop['sku_prefix'].get(product, 'CAL')}-{initials}-{code}-{size['sku']}{v['sku']}",
                "Variant Price": _money(price), "Variant Compare At Price": _money(compare),
                "Variant Price GBP": _money(price * shop["gbp_rate"]),
                "Variant Compare At Price GBP": _money(compare * shop["gbp_rate"]),
                "Variant Price CAD": _money(price * shop["cad_rate"]),
                "Variant Compare At Price CAD": _money(compare * shop["cad_rate"]),
                "Variant Image": previews[0] if previews else "",
                "Variant File": "" if spiral else printable,
                "Variant Design": design if spiral and shop["include_design"] else "",
            })
            if not rows:                             # dòng đầu mang thông tin sản phẩm
                row.update({
                    "Title": listing["title"], "Body (HTML)": listing.get("description", ""),
                    "Product Category": (shop["product_category"].get(product, "Wall Calendars")
                                         if isinstance(shop["product_category"], dict) else shop["product_category"]),
                    "Type": shop["type"],
                    "Tags": ", ".join(listing.get("tags", [])), "Is Digital": "FALSE", "Is Trademark": "FALSE",
                    "Option1 Name": shop["size_option"], "Option2 Name": shop["format_option"],
                    "Option3 Name": shop["finish_option"], "Image Src": previews[0] if previews else "",
                })
            rows.append(row)
    for url in previews[1:]:                         # ảnh phụ: mỗi ảnh một dòng
        row = dict.fromkeys(HEADER, "")
        row.update({"Handle": handle, "Image Src": url})
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


def publish_all(cfg: dict, on_event=print) -> dict:
    """Đẩy lên R2 mọi cuốn xong mà chưa đẩy (hoặc có file đổi), rồi xuất CSV cho các cuốn CHƯA từng xuất."""
    root = Path(cfg["projects_dir"])
    shop = shop_settings(cfg)
    books = ready_books(root)
    s3 = r2.client(r2.settings(cfg))
    pushed, failed = [], []
    for b in books:
        try:
            before = r2.read_state(b).get("pushed_at")
            st = r2.push_book(b, cfg, on_event, s3=s3)
            if st.get("pushed_at") != before:
                pushed.append(b.name)
        except Exception as e:  # noqa: BLE001 - một cuốn lỗi không chặn các cuốn khác
            failed.append(f"{b.name}: {e}")
            on_event(f"  ✘ {b.name}: {e}")
    todo = [b for b in books if r2.read_state(b).get("files") and not r2.read_state(b).get("exported_at")]
    csv_path = None
    if todo:
        out_dir = root / "_xuat_csv"
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"calendars_{time.strftime('%Y%m%d_%H%M%S')}_products.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            for b in todo:
                for row in _book_rows(b, shop):
                    w.writerow(row)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        for b in todo:
            st = r2.read_state(b)
            st.update(exported_at=stamp, exported_csv=csv_path.name)
            r2.write_state(b, st)
    return {"books": len(books), "pushed": pushed, "exported": [b.name for b in todo],
            "csv": str(csv_path) if csv_path else None, "failed": failed}
