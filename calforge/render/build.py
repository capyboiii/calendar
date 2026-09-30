"""Render đủ bộ trang Printify của một concept theo một khổ in + PDF in tại nhà (xem calforge/layout.py).

Đầu ra:
  <khổ>/front_cover.png, mXX_month.png, mXX_grid.png, back_cover.png   (300 DPI, kèm bleed)
  <khổ>/in_tai_nha_<khổ>.pdf               bản in tại nhà đúng khổ thành phẩm (không bleed, có lề)
  _he_thong/ky_thuat/render_<khổ>_report.md / _validation.json / _calendar_audit.json
  _he_thong/ky_thuat/proof_<khổ>/           (tuỳ chọn) đè template Printify để soát lò xo, lỗ treo, mã vạch
Ảnh cắt tạm và PDF vector trung gian nằm trong thư mục tạm và bị xoá khi render xong.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from PIL import Image
from reportlab.pdfgen import canvas

from .. import layout, products
from ..core import kjv
from ..imagegen.plan import IMG_EXT, job_done
from . import fonts
from .covers import back_cover, front_cover
from .draw import pdf_to_pngs, write_pdf
from .grid_select import apply_grid_selection
from .pages import PRESET_NAMES, grid_page, month_page, prepare_fullbleed, resolve_grid_preset
from .palette import palette_from_image
from .preflight import check_calendar, check_page

ROOT = Path(__file__).resolve().parents[2]
FORMAT_DIR = ROOT / "formats" / "printify_wall_11x8_5"
DEFAULT_FORMAT = "printify_wall_11x8_5"
# Khổ phụ render ra thư mục con của render/ (khổ mặc định giữ nguyên render/ như trước)
FORMATS = products.formats(products.DEFAULT)   # khổ in của lịch thường; mỗi cuốn: products.formats(concept)


def load_format(format_id: str = DEFAULT_FORMAT) -> dict:
    d = ROOT / "formats" / format_id
    fmt = json.loads((d / "format.json").read_text(encoding="utf-8"))
    fmt["_dir"] = str(d)
    return fmt


def render_dir(concept_dir: Path, format_id: str = DEFAULT_FORMAT) -> Path:
    """Thư mục 26 trang upload Printify của khổ format_id."""
    return layout.print_dir(concept_dir, format_id)


def art_source(concept_dir: Path, job_id: str) -> tuple[Path | None, str]:
    """Ảnh tốt nhất đang có cho một job: bản đã upscale > bản gốc."""
    raw = job_done(concept_dir, job_id)
    for f in sorted(layout.final(concept_dir).glob(f"{job_id}.*")):
        if f.suffix.lower() in IMG_EXT and (raw is None or f.stat().st_mtime >= raw.stat().st_mtime):
            return f, "upscaled"
    return (raw, "raw") if raw else (None, "")


def proof(png: Path, kind: str, fmt: dict, out: Path) -> None:
    page = Image.open(png).convert("RGBA")
    tpl = Image.open(Path(fmt.get("_dir", FORMAT_DIR)) / fmt["pages"][kind]["template"]).convert("RGBA")
    tpl.paste((0, 0, 0, 0), tuple(fmt["template_label_box"]))  # bỏ dòng chữ to giữa template
    Image.alpha_composite(page, tpl).convert("RGB").save(out)


def printable_pdfs(pngs: list[Path], fmt: dict, out_pdf: Path, dpi: int = 200) -> list[Path]:
    """PDF in tại nhà: cắt bleed, thu về `dpi`, phủ kín trang đúng khổ thành phẩm (11x8.5" = Letter ngang,
    14x11.5"...), không chừa lề - dùng chế độ in không viền (borderless) hoặc gửi tiệm in."""
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    bleed = round(fmt["bleed_px"])
    size = tuple((px - 2 * fmt["bleed_px"]) / fmt["dpi"] * 72 for px in fmt["size_px"])   # khổ thành phẩm (pt)
    tmp = out_pdf.parent / "_pages"
    tmp.mkdir(exist_ok=True)
    jpgs = []
    for p in pngs:
        j = tmp / (p.stem + ".jpg")
        with Image.open(p) as im:
            im = im.convert("RGB").crop((bleed, bleed, im.width - bleed, im.height - bleed))
            w_in, h_in = im.width / fmt["dpi"], im.height / fmt["dpi"]
            im.resize((round(w_in * dpi), round(h_in * dpi)), Image.LANCZOS).save(j, quality=86)
        jpgs.append((j, w_in / h_in))
    c = canvas.Canvas(str(out_pdf), pagesize=size)
    pw, ph = size
    for j, _ratio in jpgs:
        c.drawImage(str(j), 0, 0, pw, ph)   # trang đã cắt bleed = đúng khổ thành phẩm: tràn hết khổ
        c.showPage()
    c.save()
    # JPEG trung gian chỉ phục vụ ghép PDF, không phải artifact đầu ra.
    for j, _ratio in jpgs:
        j.unlink(missing_ok=True)
    if not any(tmp.iterdir()):
        tmp.rmdir()
    return [out_pdf]


def premade_grids(fmt: dict) -> dict[int, Path]:
    """Trang grid thiết kế sẵn của khổ này (formats/<khổ>/grids/m01..m12.*); chỉ dùng khi có đủ 12."""
    d = Path(fmt["_dir"]) / fmt.get("premade_grids_dir", "grids")
    found = {}
    for mo in range(1, 13):
        f = next((p for p in sorted(d.glob(f"m{mo:02d}.*")) if p.suffix.lower() in IMG_EXT), None) if d.is_dir() else None
        if f:
            found[mo] = f
    return found if len(found) == 12 else {}


def expected_pages(concept: dict, format_id: str) -> int:
    """Số trang PNG một cuốn phải có ở khổ này: 26, hoặc 14 với lịch grid in sẵn chưa có trang grid."""
    fmt = load_format(format_id)
    if "grid" in fmt["pages"] and products.ai_grid(concept):
        return 26
    return 26 if premade_grids(fmt) else 14


def render_concept(concept_dir: Path, months: list[int] | None = None, placeholder_art: Path | None = None,
                   covers: bool = True, digital: bool = True,
                   palette_source: str = "artwork", proofs: bool = False,
                   previews: bool = False, format_id: str = DEFAULT_FORMAT) -> dict:
    fmt = load_format(format_id)
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    out = render_dir(concept_dir, format_id)                 # chỉ chứa 26 trang PNG upload
    work = layout.tech(concept_dir, f"_tam_render_{layout.SIZE_LABEL[format_id]}")   # file trung gian, xoá cuối hàm
    rfile = lambda name: layout.render_file(concept_dir, name, format_id)
    for d in (out, work / "art"):
        d.mkdir(parents=True, exist_ok=True)
    months = months or list(range(1, 13))
    full = months == list(range(1, 13))
    pages, pngs, issues, warnings, art_notes = [], [], [], [], []

    # Màu trang = ý đồ của concept + sắc độ thật của ảnh neo (xem render/palette.py)
    pal_note = "bảng màu của concept (chưa có ảnh neo)"
    anchor_src, _ = art_source(concept_dir, "anchor")
    if palette_source == "artwork" and anchor_src is not None:
        derived = palette_from_image(anchor_src, concept["style"].get("palette"))
        pal_note = derived.pop("_note")
        derived.pop("_source", None)
        concept["style"]["palette"] = derived
        layout.tech(concept_dir, "palette.json").write_text(json.dumps({**derived, "note": pal_note}, ensure_ascii=False,
                                                              indent=2), encoding="utf-8")

    selection = apply_grid_selection(concept, requested=concept.get("grid_preset") or "auto")
    selection_file = layout.tech(concept_dir, "grid_selection.json")
    selection_file.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    def fitted_art(job_id: str, *, crop: bool = True) -> Path | None:
        src, kind = art_source(concept_dir, job_id)
        if src is None and placeholder_art:
            src, kind = placeholder_art, "ẢNH TẠM"
        if src is None:
            return None
        fitted = work / "art" / f"{job_id}.jpg"
        if crop:
            info = prepare_fullbleed(src, fitted, tuple(fmt["size_px"]))
        else:
            with Image.open(src) as im:
                source_size = im.size
                im.convert("RGB").resize(tuple(fmt["size_px"]), Image.Resampling.LANCZOS).save(fitted, quality=94)
            info = {"source_px": source_size,
                    "upscale": round(max(fmt["size_px"][0] / source_size[0],
                                         fmt["size_px"][1] / source_size[1]), 2)}
        note = f"{job_id}: {kind}, {info['source_px'][0]}x{info['source_px'][1]}, phóng x{info['upscale']}"
        if kind != "upscaled" and info["upscale"] > 1.5:
            note += " - cần upscale AI trước khi in"
        art_notes.append(note)
        return fitted

    if covers and full:
        cover_src, _ = art_source(concept_dir, "cover")
        if cover_src is not None:
            cover_art = fitted_art("cover")
            pages.append(front_cover(fmt, concept, cover_art, work / "art", ai_typeset=True))
        else:
            # Tương thích project cũ/manual render: chưa có job cover thì giữ cách ghép chữ cũ.
            cover_art = fitted_art("anchor")
            pages.append(front_cover(fmt, concept, cover_art, work / "art"))
            warnings.append("chưa có ảnh cover AI - đang dùng bìa legacy với title do code đặt")
        pngs.append((out / "front_cover.png", "front_cover"))

    month_arts = {}
    # Lịch grid in sẵn: không có trang grid do máy dựng; trang grid (nếu người dùng đã thêm) chép nguyên file.
    ai_grid = "grid" in fmt["pages"] and products.ai_grid(concept)
    premade = premade_grids(fmt) if not ai_grid else {}
    copies: list[tuple[Path, Path]] = []
    ai_page = ai_grid and products.ai_page(concept)          # AI vẽ nguyên 12 trang lịch
    art_matched = ai_grid and not ai_page and resolve_grid_preset(concept) == "art_matched"
    shared_grid = fitted_art("grid", crop=False) if art_matched else None
    if art_matched and shared_grid is None:
        # Project cũ: lấy nền tháng đầu tiên đang có làm master để vẫn render được.
        for old_id in (f"g{i:02d}" for i in range(1, 13)):
            if art_source(concept_dir, old_id)[0] is not None:
                shared_grid = fitted_art(old_id, crop=False)
                warnings.append(f"đang dùng {old_id} làm nền grid chung; nên lưu lại thành grid.png")
                break
    if art_matched and shared_grid is None:
        issues.append("[grid] chưa có nền grid dùng chung cho 12 tháng")
    for mo in months:
        tag = f"m{mo:02d}"
        fitted = fitted_art(tag)
        if fitted is None:
            issues.append(f"[{tag}] chưa có ảnh tháng - bỏ qua trang ảnh")
        else:
            month_arts[mo] = fitted
            pages.append(month_page(fmt, fitted, f"{tag} month"))
            pngs.append((out / f"{tag}_month.png", "month"))
        m = concept["months"][mo - 1]
        verse = m.get("content", {}).get("text")
        if concept.get("content_type") == "bible_verse_kjv" and not verse:
            verse = kjv.lookup(m["content"]["value"])
            if not verse:
                issues.append(f"[{tag}] không tra được lời câu {m['content']['value']} - chỉ in mã câu")
        if ai_page:
            g = fitted_art(f"g{mo:02d}")                 # cắt vừa tỉ lệ khổ (AI vẽ 4:3, lịch nằm trong x 8–92%)
            if g is None:
                issues.append(f"[g{mo:02d}] chưa có trang lịch AI")
            else:
                copies.append((g, out / f"{tag}_grid.png"))
                pngs.append((out / f"{tag}_grid.png", "premade_grid"))
        elif ai_grid:
            pages.append(grid_page(fmt, concept, mo, f"{tag} grid", verse, shared_grid))
            pngs.append((out / f"{tag}_grid.png", "grid"))
        elif mo in premade:
            copies.append((premade[mo], out / f"{tag}_grid.png"))
            pngs.append((out / f"{tag}_grid.png", "premade_grid"))
        else:
            (out / f"{tag}_grid.png").unlink(missing_ok=True)   # không để sót trang grid cũ

    if covers and full:
        pages.append(back_cover(fmt, concept, month_arts, work / "art"))
        pngs.append((out / "back_cover.png", "back_cover"))

    for page in pages:
        issues += check_page(page, fmt)

    calendar_audit = []
    for page in pages:
        if page.calendar:
            calendar_audit.append({**page.calendar, "label": page.label,
                                   "grid_box_px": page.grid_box,
                                   "date_count": sum(t.role == "date" for t in page.texts()),
                                   "issues": check_calendar(page),
                                   "source": "stored calendar_2027.WEEKS" if page.calendar["year"] == 2027
                                   else "Python Gregorian calendar"})
    rfile("calendar_audit.json").write_text(json.dumps(calendar_audit, ensure_ascii=False, indent=2),
                                            encoding="utf-8")

    if previews:
        preview_dir = layout.tech(concept_dir, "grid_options")
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_month = 3
        preview_m = concept["months"][preview_month - 1]
        preview_verse = preview_m.get("content", {}).get("text")
        if concept.get("content_type") == "bible_verse_kjv" and not preview_verse:
            preview_verse = kjv.lookup(preview_m.get("content", {}).get("value", ""))
        for option in selection.get("alternatives", [])[:2]:
            alt = copy.deepcopy(concept)
            apply_grid_selection(alt, requested=option["preset"])
            preview_page = grid_page(fmt, alt, preview_month, f"grid option {option['preset']}",
                                     preview_verse, shared_grid)
            pdf = preview_dir / f"{option['preset']}.pdf"
            png = preview_dir / f"{option['preset']}.png"
            write_pdf([preview_page], pdf)
            pdf_to_pngs(pdf, [png], 150)
            option["preview"] = str(png.relative_to(concept_dir)).replace("\\", "/")
            option["preflight_issues"] = check_page(preview_page, fmt)
    selection_file.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")

    write_pdf(pages, work / "pages.pdf")          # PDF vector chỉ để xuất PNG, xoá cùng thư mục tạm
    pdf_to_pngs(work / "pages.pdf", [p for p, k in pngs if k != "premade_grid"], fmt["dpi"])
    for src, dst in copies:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.size != tuple(fmt["size_px"]):
                if not ai_page:
                    warnings.append(f"{src.name}: {im.width}x{im.height} khác cỡ trang {fmt['size_px']} - đã co giãn")
                im = im.resize(tuple(fmt["size_px"]), Image.Resampling.LANCZOS)
            im.save(dst, dpi=(fmt["dpi"], fmt["dpi"]))
    if proofs:
        proof_dir = layout.tech(concept_dir, f"proof_{layout.SIZE_LABEL[format_id]}")
        proof_dir.mkdir(parents=True, exist_ok=True)
        for png, kind in pngs:
            proof(png, kind, fmt, proof_dir / png.name.replace(".png", "_proof.png"))

    digital_files = []
    complete = (full and covers and not issues and len(month_arts) == 12
                and (not art_matched or shared_grid is not None))
    if digital and complete:
        digital_files = printable_pdfs([p for p, _ in pngs], fmt, layout.printable_file(concept_dir, format_id))

    preset_key = resolve_grid_preset(concept)
    preset_name = PRESET_NAMES.get(preset_key, preset_key)
    lines = ["# Render report", "", f"Trang: {len(pages)}", f"Bố cục trang lưới: {preset_name}", ""]
    lines += ["## Chọn grid", f"- Chế độ: {selection['mode']}",
              f"- Đã chọn: {selection['selected_label']}",
              *[f"- Lý do: {r}" for r in selection.get("reasons", [])],
              "- AI vẽ nguyên 12 trang lịch; OCR đã soát thứ tự thứ, đủ ngày, đúng cột và đúng tuần từng trang."
              if ai_page else
              "- AI thiết kế một nền grid dùng chung cho 12 tháng; ô, thứ, ngày và nội dung do code dựng chính xác."
              if art_matched else "- Grid thủ công chỉ dùng typography và shape." if ai_grid else
              f"- Lịch grid in sẵn: không dựng trang grid; {'đã chèn 12 trang grid thiết kế sẵn' if premade else 'chưa có trang grid (14 trang)'}.",
              ""]
    lines += ["## Preflight", *([f"- {i}" for i in issues] or ["- Không có lỗi."]), ""]
    lines += ["## Kiểm tra ngày", f"- {len(calendar_audit)} tháng / "
              f"{sum(a['date_count'] for a in calendar_audit)} ngày đã kiểm tra vị trí ô, thứ, trùng và thiếu.",
              "- Chi tiết: calendar_audit.json", ""]
    lines += ["## Cảnh báo", *([f"- {w}" for w in warnings] or ["- Không có."]), ""]
    lines += ["## Ảnh", *[f"- {n}" for n in art_notes], ""]
    pal = concept["style"]["palette"]
    lines += ["## Bảng màu", f"- {pal_note}", "- " + ", ".join(f"{k} {v}" for k, v in pal.items()), ""]
    lines += ["## Font", *([f"- dự phòng: {f}" for f in sorted(fonts.fallbacks_used)] or ["- dùng font thật"]), ""]
    lines += ["## Printable", *([f"- {p.name}" for p in digital_files] or ["- chưa tạo (cần đủ 12 tháng + bìa)"])]
    rfile("report.md").write_text("\n".join(lines), encoding="utf-8")
    rfile("validation.json").write_text(json.dumps({"complete": complete, "issues": issues,
        "page_count": len(pages), "calendar_months": len(calendar_audit),
        "calendar_days": sum(a["date_count"] for a in calendar_audit)}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)   # xoá ảnh cắt tạm + PDF trung gian
    return {"pages": [str(p) for p, _ in pngs], "issues": issues, "warnings": warnings,
            "grid_selection": selection, "calendar_audit": calendar_audit,
            "art": art_notes, "complete": complete,
            "digital": [str(p) for p in digital_files], "font_fallbacks": sorted(fonts.fallbacks_used), "out": str(out)}
