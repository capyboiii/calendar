"""Đổi tên thư mục các cuốn làm trước khi có SKU sang mã SKU của chính nó (cuốn mới đã mang tên SKU sẵn).

    python -m calforge rename-sku          (máy chủ giao diện cũng tự chạy một lần lúc mở tool)

- SKU giữ ĐÚNG mã đã xuất CSV trước giờ (tính từ tên listing như lúc xuất) -> không lệch với sản phẩm đã đăng bán;
  cuốn chưa có listing (chưa xong) thì nhận mã mới. Mã trùng thư mục khác thì nhận mã mới.
- Sửa kèm mọi chỗ trỏ tới tên cũ: batch.json (danh sách cuốn + báo cáo) của chủ đề, hàng đợi .hang_doi.json,
  đường dẫn PDF trong status.json; cuốn đã đẩy R2 thì chốt lại đường dẫn R2 cũ (key_base) để không phải đẩy lại.
- Ghi mã góc (angle_id.txt) trước khi đổi tên để vẫn tìm lại được cuốn.
- Chủ đề đang có batch chạy (khoá batch còn sống) thì bỏ qua, lần sau làm. Cuốn nào lỗi (thư mục đang bị mở...) thì
  bỏ qua cuốn đó, giữ nguyên tên cũ; chạy lại nhiều lần không sao.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import layout, products


def legacy_sku(cdir: Path, shop: dict | None = None) -> str:
    """SKU gốc đúng như CSV đã xuất cho cuốn cũ (tính từ tên listing); "" nếu cuốn chưa có listing."""
    import hashlib
    from .publish import r2
    from .publish.shop_csv import DEFAULT_SHOP
    try:
        listing = json.loads(layout.listing_file(cdir).read_text(encoding="utf-8"))
        title = listing["title"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    try:
        product = products.product_id(json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        product = products.DEFAULT
    handle = r2.slug(title, 200)
    code = hashlib.sha1(handle.encode()).hexdigest()[:5].upper()
    initials = "".join(w[0] for w in handle.split("-")[:3]).upper()
    return f"{(shop or DEFAULT_SHOP)['sku_prefix'].get(product, 'CAL')}-{initials}-{code}"


def _concept(cdir: Path) -> dict:
    try:
        c = json.loads(layout.concept_file(cdir).read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _topic_busy(kdir: Path) -> bool:
    from .pipeline import _BatchLock
    lock = _BatchLock(kdir)
    return lock.file.exists() and lock._owner_alive()


def _write_json(f: Path, data) -> None:
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def _fix_batch(kdir: Path, old: str, new: str) -> None:
    f = layout.batch_file(kdir)
    try:
        b = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    changed = False
    if isinstance(b.get("concepts"), list):
        fixed = [new if c == old else c for c in b["concepts"]]
        changed |= fixed != b["concepts"]
        b["concepts"] = fixed
    for row in b.get("report") or []:
        if isinstance(row, dict) and row.get("concept") == old:
            row["concept"] = new
            changed = True
    if changed:
        _write_json(f, b)


def _fix_status(new_dir: Path, old_dir: Path) -> None:
    f = layout.status_file(new_dir)
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return
    olds = {str(old_dir), str(old_dir).replace("\\", "/")}
    if not any(o in text or json.dumps(o)[1:-1] in text for o in olds):
        return
    try:
        st = json.loads(text)
    except ValueError:
        return

    def fix(v):
        if isinstance(v, str):
            for o in olds:
                if v.startswith(o):
                    return str(new_dir) + v[len(o):].replace("/", "\\") if "\\" in str(new_dir) else str(new_dir) + v[len(o):]
            return v
        if isinstance(v, list):
            return [fix(x) for x in v]
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        return v
    _write_json(f, fix(st))


def _pin_r2_path(cdir: Path) -> None:
    """Cuốn đã đẩy R2 mà chưa ghi key_base: chốt đường dẫn R2 tính theo tên CŨ (đổi tên không làm đẩy lại)."""
    from .publish import r2
    st = r2.read_state(cdir)
    if not st.get("files") or st.get("key_base"):
        return
    prefix = str((st.get("destination") or {}).get("prefix") or "calendars")
    st["key_base"] = f"{prefix.strip('/')}/{r2._group(cdir)}{r2.slug(cdir.parent.name, 40)}/{r2.slug(cdir.name)}"
    r2.write_state(cdir, st)


def _fix_queue(projects_root: Path, moved: dict[Path, Path]) -> None:
    f = projects_root / ".hang_doi.json"
    try:
        q = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    from . import config
    root = config.ROOT
    changed = False
    for it in q.get("items") or []:
        p = (it.get("params") or {})
        c = p.get("concept")
        if not isinstance(c, str) or not c:
            continue
        try:
            target = (root / c).resolve()
        except OSError:
            continue
        new = moved.get(target)
        if new is None:
            continue
        p["concept"] = str(new.relative_to(root)).replace("\\", "/") if new.is_relative_to(root) else str(new)
        if p.get("title") and p["title"] == target.name:
            p["title"] = new.name
        changed = True
    if changed:
        _write_json(f, q)


def rename_all(projects_root: Path, on_event=print, shop: dict | None = None) -> list[tuple[str, str]]:
    """Đổi tên mọi cuốn cũ sang SKU. Trả về [(tên cũ, tên mới)]."""
    projects_root = Path(projects_root)
    done: list[tuple[str, str]] = []
    moved: dict[Path, Path] = {}
    busy_topics: set[Path] = set()
    for b in layout.books(projects_root):
        if layout.book_sku(b) or b.name.startswith("_"):
            continue
        kdir = b.parent
        if kdir in busy_topics:
            continue
        if _topic_busy(kdir):
            busy_topics.add(kdir)
            on_event(f"  ↷ Bỏ qua chủ đề {kdir.name}: đang có batch chạy - lần sau đổi tên")
            continue
        concept = _concept(b)
        product = products.product_id(concept) if concept else products.DEFAULT
        sku = legacy_sku(b, shop)
        if not sku or (kdir / sku).exists():
            for _ in range(50):
                sku = layout.make_sku(product, concept.get("title") or b.name)
                if not (kdir / sku).exists():
                    break
        try:
            aid = layout.book_angle_id(b)
            if aid and not (b / layout.SYSTEM / layout.ANGLE_ID).is_file():
                (b / layout.SYSTEM / layout.ANGLE_ID).write_text(aid, encoding="utf-8")
            _pin_r2_path(b)
            new = kdir / sku
            b.rename(new)
        except OSError as e:
            on_event(f"  ✘ Không đổi tên được {b.name}: {e}")
            continue
        (new / layout.SYSTEM / layout.SKU_FILE).write_text(sku, encoding="utf-8")
        for step in (lambda: _fix_batch(kdir, b.name, sku), lambda: _fix_status(new, b)):
            try:
                step()
            except OSError as e:
                on_event(f"  ⚠ {sku}: chưa sửa hết chỗ trỏ tới tên cũ ({e})")
        moved[b.resolve()] = new.resolve()
        done.append((b.name, sku))
        on_event(f"  ✔ {b.name}  ->  {sku}")
    if moved:
        try:
            _fix_queue(projects_root, moved)
        except OSError as e:
            on_event(f"  ⚠ Chưa sửa được hàng đợi: {e}")
    return done
