"""Đưa lịch lên Printify qua API: upload 26 trang -> tạo sản phẩm NHÁP. Publish chỉ khi được yêu cầu.

Token: biến môi trường PRINTIFY_API_TOKEN hoặc calforge.json -> printify.token (tự dán vào file,
không đưa token vào chat). Tool không tự đoán điều gì chưa chắc:
- blueprint/nhà in/biến thể tìm theo tên ("Wall Calendar", "District Photo", "11"), lưu lại vào
  formats/printify_wall_11x8_5/printify_catalog.json để lần sau khỏi tra;
- tên từng vùng in (position) do Printify đặt -> tool khớp theo tên tháng/cover/grid; không khớp
  chắc chắn được thì DỪNG và ghi danh sách vào printify_positions.json để người sửa tay.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from .. import layout
from ..core import dates

API = "https://api.printify.com/v1"
FORMAT_DIR = Path(__file__).resolve().parents[2] / "formats" / "printify_wall_11x8_5"
CATALOG_FILE = FORMAT_DIR / "printify_catalog.json"
POSITIONS_FILE = FORMAT_DIR / "printify_positions.json"
MAX_B64_BYTES = 4_500_000  # Printify giới hạn upload base64 ~5MB


class PrintifyError(RuntimeError): ...


class Client:
    def __init__(self, token: str):
        if not token:
            raise PrintifyError("Chưa có Printify API token (PRINTIFY_API_TOKEN hoặc calforge.json printify.token)")
        self.token = token

    def _req(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
            "User-Agent": "calforge/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise PrintifyError(f"{method} {path} -> {e.code}: {e.read()[:400]!r}") from e
        return json.loads(raw) if raw else {}

    def get(self, path):
        return self._req("GET", path)

    def post(self, path, body):
        return self._req("POST", path, body)


def token_from(cfg: dict) -> str:
    return os.environ.get("PRINTIFY_API_TOKEN") or (cfg.get("printify") or {}).get("token", "")


# ---------------------------------------------------------------------------
# Tra catalog
# ---------------------------------------------------------------------------
def discover(client: Client, pcfg: dict) -> dict:
    if CATALOG_FILE.exists():
        return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    bid = pcfg.get("blueprint_id")
    if not bid:
        bps = [b for b in client.get("/catalog/blueprints.json")
               if "calendar" in b["title"].lower() and "wall" in b["title"].lower()]
        blank = [b for b in bps if "blank" in b["title"].lower()] or bps
        if not blank:
            raise PrintifyError("Không tìm thấy blueprint lịch treo tường trong catalog")
        bid = blank[0]["id"]
    pid = pcfg.get("print_provider_id")
    if not pid:
        provs = client.get(f"/catalog/blueprints/{bid}/print_providers.json")
        want = pcfg.get("print_provider_name", "District Photo").lower()
        match = [p for p in provs if want in p["title"].lower()] or provs
        pid = match[0]["id"]
    variants = client.get(f"/catalog/blueprints/{bid}/print_providers/{pid}/variants.json")["variants"]
    size = pcfg.get("variant_title_contains", "11")
    chosen = [v for v in variants if size in v["title"]] or variants
    v = chosen[0]
    catalog = {"blueprint_id": bid, "print_provider_id": pid, "variant_id": v["id"], "variant_title": v["title"],
               "positions": [p["position"] for p in v.get("placeholders", [])]}
    CATALOG_FILE.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog


def map_positions(positions: list[str]) -> dict[str, str]:
    """position Printify -> tên trang của tool (front_cover, mXX_month, mXX_grid, back_cover)."""
    if POSITIONS_FILE.exists():
        manual = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
        if all(manual.get(p) for p in positions):
            return manual
    months = [m.lower() for m in dates.MONTH_NAMES]
    mapping, by_month = {}, {}
    for pos in positions:
        low = pos.lower()
        if "front" in low or low in ("cover", "front_cover"):
            mapping[pos] = "front_cover"
        elif "back" in low:
            mapping[pos] = "back_cover"
        else:
            idx = next((i for i, m in enumerate(months) if m in low or m[:3] == low[:3]), None)
            if idx is not None:
                by_month.setdefault(idx + 1, []).append(pos)
    for mo, poss in by_month.items():
        grid = [p for p in poss if re.search(r"grid|calendar|date|bottom", p.lower())]
        image = [p for p in poss if p not in grid]
        if len(grid) == 1:
            mapping[grid[0]] = f"m{mo:02d}_grid"
        if len(image) == 1:
            mapping[image[0]] = f"m{mo:02d}_month"
    if len(mapping) != len(positions) and len(positions) == 26:
        # position đặt theo số trang: bìa trước, (ảnh, lưới) x 12, bìa sau
        order = ["front_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")] + ["back_cover"]
        keyed = sorted(positions, key=lambda p: int(re.findall(r"\d+", p)[0]) if re.findall(r"\d+", p) else 0)
        if all(re.findall(r"\d+", p) for p in positions):
            mapping = dict(zip(keyed, order))
    missing = [p for p in positions if p not in mapping]
    if missing:
        POSITIONS_FILE.write_text(json.dumps({p: mapping.get(p, "") for p in positions}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        raise PrintifyError(f"Chưa khớp được {len(missing)} vùng in ({', '.join(missing[:6])}...). "
                            f"Điền tay tên trang vào {POSITIONS_FILE} rồi chạy lại.")
    return mapping


# ---------------------------------------------------------------------------
# Upload + tạo sản phẩm
# ---------------------------------------------------------------------------
def _jpeg_b64(png: Path) -> str:
    with Image.open(png) as im:
        im = im.convert("RGB")
        for q in (95, 92, 88, 84, 80):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, dpi=(300, 300))
            if buf.tell() <= MAX_B64_BYTES:
                return base64.b64encode(buf.getvalue()).decode()
    raise PrintifyError(f"{png.name} quá lớn để upload base64")


def create_product(concept_dir: Path, cfg: dict, publish: bool = False, on_event=print) -> dict:
    pcfg = cfg.get("printify") or {}
    client = Client(token_from(cfg))
    state_file = layout.tech(concept_dir, "printify.json")   # xem calforge/layout.py
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {"uploads": {}}
    if state.get("product_id") and (not publish or state.get("published")):
        on_event("Printify đã hoàn tất, bỏ qua upload/tạo sản phẩm")
        return state

    shop_id = pcfg.get("shop_id")
    if not shop_id:
        shops = client.get("/shops.json")
        if len(shops) != 1:
            raise PrintifyError(f"Có {len(shops)} shop - ghi printify.shop_id vào calforge.json: "
                                + ", ".join(f"{s['id']}={s['title']}" for s in shops))
        shop_id = shops[0]["id"]
    catalog = discover(client, pcfg)
    mapping = map_positions(catalog["positions"])

    pages_dir = layout.print_dir(concept_dir)
    pending = [(page, pages_dir / f"{page}.png") for page in mapping.values() if page not in state["uploads"]]
    for page, png in pending:
        if not png.exists():
            raise PrintifyError(f"Thiếu trang {png.name} - chạy render trước")

    def upload(item):
        page, png = item
        res = client.post("/uploads/images.json", {"file_name": f"{concept_dir.name}_{page}.jpg",
                                                   "contents": _jpeg_b64(png)})
        return page, res["id"]

    workers = max(1, min(4, int(pcfg.get("upload_workers", 4))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(upload, item) for item in pending]
        for future in as_completed(futures):
            page, upload_id = future.result()
            state["uploads"][page] = upload_id
            state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            on_event(f"upload {page} -> {upload_id}")

    if not state.get("product_id"):
        listing = json.loads(layout.listing_file(concept_dir).read_text(encoding="utf-8"))
        body = {
            "title": listing["title"], "description": listing["description"], "tags": listing["tags"],
            "blueprint_id": catalog["blueprint_id"], "print_provider_id": catalog["print_provider_id"],
            "variants": [{"id": catalog["variant_id"], "price": int(pcfg.get("price_cents", 2999)), "is_enabled": True}],
            "print_areas": [{"variant_ids": [catalog["variant_id"]], "placeholders": [
                {"position": pos, "images": [{"id": state["uploads"][page], "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}]}
                for pos, page in mapping.items()]}],
        }
        product = client.post(f"/shops/{shop_id}/products.json", body)
        state["product_id"] = product["id"]
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        on_event(f"Đã tạo sản phẩm NHÁP {product['id']} trên Printify")

    if publish and not state.get("published"):
        client.post(f"/shops/{shop_id}/products/{state['product_id']}/publish.json",
                    {k: True for k in ("title", "description", "images", "variants", "tags", "keyFeatures",
                                       "shipping_template")})
        state["published"] = True
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        on_event("Đã gửi lệnh publish sang cửa hàng")
    return state
