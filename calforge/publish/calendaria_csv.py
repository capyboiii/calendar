"""Upload finished calendars to R2 and export the 25-column Calendaria product CSV."""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

from .. import layout, products
from . import r2
from .shop_csv import ready_books, shop_settings

HEADER = [
    "Handle", "Title", "Body (HTML)", "Product Category", "Type", "Tags", "Is Digital",
    "Is Trademark", "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value",
    "Option3 Name", "Option3 Value", "Variant SKU", "Variant Price", "Variant Compare At Price",
    "Variant Price GBP", "Variant Compare At Price GBP", "Variant Price CAD",
    "Variant Compare At Price CAD", "Image Src", "Variant Image", "Variant File", "Variant Design",
]


def _money(value: float) -> str:
    return f"{float(value):.2f}"


def _book_rows(cdir: Path, shop: dict) -> list[dict]:
    listing = json.loads(layout.listing_file(cdir).read_text(encoding="utf-8"))
    try:
        product = products.product_id(json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        product = products.DEFAULT
    files = r2.read_state(cdir).get("files", {})
    previews = [files[n]["url"] for n in sorted(files) if "/" not in n and n.lower().endswith(".jpg")]
    handle = r2.slug(listing["title"], 200)
    code = hashlib.sha1(handle.encode()).hexdigest()[:5].upper()
    initials = "".join(word[0] for word in handle.split("-")[:3]).upper()
    finishes = shop["spiral_finishes"].get(product, {})
    rows: list[dict] = []
    first = True

    for size in shop["sizes"]:
        label = layout.SIZE_LABEL[size["format_id"]]
        cover = (files.get(f"{label}/front_cover.png") or {}).get("url", "")
        if not cover:
            continue
        for variant in shop["variants"]:
            printable = variant["format"].lower() == "printable"
            if not printable and variant["finish"] not in finishes.get(label, [variant["finish"]]):
                continue
            usd = float(variant["price"]) + (0 if printable else float(size.get("spiral_add", 0)))
            compare = float(variant["compare"]) + (0 if printable else float(size.get("spiral_add", 0)))
            sku = f"{shop['sku_prefix'].get(product, 'CAL')}-{initials}-{code}-{size['sku']}{variant['sku']}"
            row = dict.fromkeys(HEADER, "")
            row.update({
                "Handle": handle, "Product Category": "Calendaria",
                "Option1 Value": size["label"], "Option2 Value": variant["format"],
                # Calendaria requires every variant to have the same number of option values.
                # The storefront can hide Paper when format=Printable, but the import still needs a placeholder.
                "Option3 Value": "N/A" if printable else variant["finish"], "Variant SKU": sku,
                "Variant Price": _money(usd), "Variant Compare At Price": _money(compare),
                "Variant Price GBP": _money(usd * float(shop["gbp_rate"])),
                "Variant Compare At Price GBP": _money(compare * float(shop["gbp_rate"])),
                "Variant Price CAD": _money(usd * float(shop["cad_rate"])),
                "Variant Compare At Price CAD": _money(compare * float(shop["cad_rate"])),
                "Variant Image": previews[0] if previews else cover,
                "Variant File": (files.get(layout.printable_file(cdir, size["format_id"]).name) or {}).get("url", "")
                    if printable else "",
            })
            if first:
                row.update({
                    "Title": listing["title"], "Body (HTML)": listing.get("description", ""),
                    "Type": shop["type"], "Tags": ", ".join(listing.get("tags", [])),
                    "Is Digital": "FALSE", "Is Trademark": "FALSE",
                    "Option1 Name": shop["size_option"], "Option2 Name": shop["format_option"],
                    "Option3 Name": "Paper", "Image Src": previews[0] if previews else cover,
                })
                first = False
            rows.append(row)

    for image_url in previews[1:]:
        row = dict.fromkeys(HEADER, "")
        row.update({"Handle": handle, "Product Category": "Calendaria", "Image Src": image_url})
        rows.append(row)
    return rows


def publish_all(cfg: dict, on_event=print, only: list[Path] | None = None) -> dict:
    root = Path(cfg["projects_dir"])
    books = ready_books(root)
    if only is not None:
        chosen = {Path(book).resolve() for book in only}
        books = [book for book in books if book.resolve() in chosen]
    s3 = r2.client(r2.settings(cfg))
    pushed, failed = [], []
    for book in books:
        try:
            before = r2.read_state(book).get("pushed_at")
            state = r2.push_book(book, cfg, on_event, s3=s3)
            if state.get("pushed_at") != before:
                pushed.append(book.name)
        except Exception as exc:  # one broken book must not block the others
            failed.append(f"{book.name}: {exc}")
            on_event(f"  ✘ {book.name}: {exc}")
    todo = [book for book in books if r2.read_state(book).get("files") and
            (only is not None or not r2.read_state(book).get("calendaria_exported_at"))]
    csv_path = None
    if todo:
        out_dir = root / "_xuat_csv"
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"calendars_{time.strftime('%Y%m%d_%H%M%S')}_products_no_design_product_category_calendaria.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADER)
            writer.writeheader()
            for book in todo:
                writer.writerows(_book_rows(book, shop_settings(cfg)))
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        for book in todo:
            state = r2.read_state(book)
            state.update(calendaria_exported_at=stamp, calendaria_exported_csv=csv_path.name)
            r2.write_state(book, state)
    return {"books": len(books), "pushed": pushed, "exported": [book.name for book in todo],
            "csv": str(csv_path) if csv_path else None, "failed": failed}
