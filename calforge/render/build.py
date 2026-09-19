"""Render đủ bộ trang Printify của một concept + PDF printable.

Đầu ra trong <concept>/render/:
  printify/front_cover.png, mXX_month.png, mXX_grid.png, back_cover.png   (3375x2625, 300 DPI)
  pages.pdf                          bản vector để duyệt
  proof/*_proof.png                  đè template Printify để soát lò xo, lỗ treo, mã vạch
  digital/calendar_letter.pdf, calendar_a4.pdf   bản in tại nhà (không bleed, có lề)
  report.md                          preflight + font + ảnh
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape, letter
from reportlab.pdfgen import canvas

from ..core import kjv
from ..imagegen.cleanup import ensure_alpha
from ..imagegen.plan import IMG_EXT, job_done
from . import fonts
from .covers import back_cover, front_cover
from .draw import pdf_to_pngs, write_pdf
from .pages import grid_page, month_page, prepare_fullbleed
from .palette import palette_from_image
from .preflight import check_page

ROOT = Path(__file__).resolve().parents[2]
FORMAT_DIR = ROOT / "formats" / "printify_wall_11x8_5"


def load_format() -> dict:
    return json.loads((FORMAT_DIR / "format.json").read_text(encoding="utf-8"))


def art_source(concept_dir: Path, job_id: str) -> tuple[Path | None, str]:
    """Ảnh tốt nhất đang có cho một job: bản đã upscale > bản gốc."""
    for f in sorted((concept_dir / "art" / "final").glob(f"{job_id}.*")):
        if f.suffix.lower() in IMG_EXT:
            return f, "upscaled"
    raw = job_done(concept_dir, job_id)
    return (raw, "raw") if raw else (None, "")


def proof(png: Path, kind: str, fmt: dict, out: Path) -> None:
    page = Image.open(png).convert("RGBA")
    tpl = Image.open(FORMAT_DIR / fmt["pages"][kind]["template"]).convert("RGBA")
    tpl.paste((0, 0, 0, 0), tuple(fmt["template_label_box"]))  # bỏ dòng chữ to giữa template
    Image.alpha_composite(page, tpl).convert("RGB").save(out)


def prepare_ornament(src: Path, out_dir: Path) -> tuple[dict, str]:
    """Họa tiết -> PNG nền trong suốt đã cắt sát (+ bản lật gương). Tự tách nền nếu cần."""
    left, right = out_dir / "ornament.png", out_dir / "ornament_r.png"
    kind = ensure_alpha(src, left)
    with Image.open(left) as img:
        img.transpose(Image.FLIP_LEFT_RIGHT).save(right)
        aspect = img.height / img.width
    note = {"alpha": "nền trong suốt sẵn", "checker": "đã gỡ nền ô caro giả", "plain": "đã tách nền trơn"}[kind]
    return {"left": left, "right": right, "aspect": aspect}, note


def printable_pdfs(pngs: list[Path], fmt: dict, out_dir: Path, dpi: int = 200) -> list[Path]:
    """PDF in tại nhà: cắt bleed, thu về `dpi`, đặt giữa trang Letter/A4 ngang, lề 0.25"."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bleed = round(fmt["bleed_px"])
    jpgs = []
    for p in pngs:
        j = out_dir / "_pages" / (p.stem + ".jpg")
        j.parent.mkdir(exist_ok=True)
        with Image.open(p) as im:
            im = im.convert("RGB").crop((bleed, bleed, im.width - bleed, im.height - bleed))
            w_in, h_in = im.width / fmt["dpi"], im.height / fmt["dpi"]
            im.resize((round(w_in * dpi), round(h_in * dpi)), Image.LANCZOS).save(j, quality=86)
        jpgs.append((j, w_in / h_in))
    made = []
    for name, size in (("calendar_letter.pdf", landscape(letter)), ("calendar_a4.pdf", landscape(A4))):
        path = out_dir / name
        c = canvas.Canvas(str(path), pagesize=size)
        pw, ph = size
        margin = 0.25 * 72
        for j, ratio in jpgs:
            w = min(pw - 2 * margin, (ph - 2 * margin) * ratio)
            h = w / ratio
            c.drawImage(str(j), (pw - w) / 2, (ph - h) / 2, w, h)
            c.showPage()
        c.save()
        made.append(path)
    return made


def render_concept(concept_dir: Path, months: list[int] | None = None, placeholder_art: Path | None = None,
                   placeholder_ornament: Path | None = None, covers: bool = True, digital: bool = True,
                   palette_source: str = "artwork") -> dict:
    fmt = load_format()
    concept = json.loads((concept_dir / "concept.json").read_text(encoding="utf-8"))
    out = concept_dir / "render"
    for sub in ("printify", "proof", "art"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    months = months or list(range(1, 13))
    full = months == list(range(1, 13))
    pages, pngs, issues, art_notes = [], [], [], []

    # Màu trang = ý đồ của concept + sắc độ thật của ảnh neo (xem render/palette.py)
    pal_note = "bảng màu của concept (chưa có ảnh neo)"
    anchor_src, _ = art_source(concept_dir, "anchor")
    if palette_source == "artwork" and anchor_src is not None:
        derived = palette_from_image(anchor_src, concept["style"].get("palette"))
        pal_note = derived.pop("_note")
        derived.pop("_source", None)
        concept["style"]["palette"] = derived
        (concept_dir / "palette.json").write_text(json.dumps({**derived, "note": pal_note}, ensure_ascii=False,
                                                              indent=2), encoding="utf-8")

    orn_src = job_done(concept_dir, "ornament") or placeholder_ornament
    ornament = None
    if orn_src is None:
        issues.append("chưa có họa tiết (art/raw/ornament.png) - trang lưới không có lớp họa tiết")
    else:
        ornament, note = prepare_ornament(orn_src, out / "art")
        art_notes.append(f"ornament: {note}" + (" (ẢNH TẠM)" if orn_src == placeholder_ornament else ""))

    def fitted_art(job_id: str) -> Path | None:
        src, kind = art_source(concept_dir, job_id)
        if src is None and placeholder_art:
            src, kind = placeholder_art, "ẢNH TẠM"
        if src is None:
            return None
        fitted = out / "art" / f"{job_id}.jpg"
        info = prepare_fullbleed(src, fitted, tuple(fmt["size_px"]))
        note = f"{job_id}: {kind}, {info['source_px'][0]}x{info['source_px'][1]}, phóng x{info['upscale']}"
        if kind != "upscaled" and info["upscale"] > 1.5:
            note += " - cần upscale AI trước khi in"
        art_notes.append(note)
        return fitted

    if covers and full:
        cover_art = fitted_art("anchor")
        pages.append(front_cover(fmt, concept, cover_art, out / "art"))
        pngs.append((out / "printify" / "front_cover.png", "front_cover"))

    month_arts = {}
    for mo in months:
        tag = f"m{mo:02d}"
        fitted = fitted_art(tag)
        if fitted is None:
            issues.append(f"[{tag}] chưa có ảnh tháng - bỏ qua trang ảnh")
        else:
            month_arts[mo] = fitted
            pages.append(month_page(fmt, fitted, f"{tag} month"))
            pngs.append((out / "printify" / f"{tag}_month.png", "month"))
        m = concept["months"][mo - 1]
        verse = m.get("content", {}).get("text")
        if concept.get("content_type") == "bible_verse_kjv" and not verse:
            verse = kjv.lookup(m["content"]["value"])
            if not verse:
                issues.append(f"[{tag}] không tra được lời câu {m['content']['value']} - chỉ in mã câu")
        pages.append(grid_page(fmt, concept, mo, f"{tag} grid", verse, ornament))
        pngs.append((out / "printify" / f"{tag}_grid.png", "grid"))

    if covers and full:
        pages.append(back_cover(fmt, concept, month_arts, out / "art"))
        pngs.append((out / "printify" / "back_cover.png", "back_cover"))

    for page in pages:
        issues += check_page(page, fmt)

    write_pdf(pages, out / "pages.pdf")
    pdf_to_pngs(out / "pages.pdf", [p for p, _ in pngs], fmt["dpi"])
    for png, kind in pngs:
        proof(png, kind, fmt, out / "proof" / png.name.replace(".png", "_proof.png"))

    digital_files = []
    complete = full and covers and len(month_arts) == 12
    if digital and complete:
        digital_files = printable_pdfs([p for p, _ in pngs], fmt, out / "digital")

    lines = ["# Render report", "", f"Trang: {len(pages)}", ""]
    lines += ["## Preflight", *([f"- {i}" for i in issues] or ["- Không có lỗi."]), ""]
    lines += ["## Ảnh", *[f"- {n}" for n in art_notes], ""]
    pal = concept["style"]["palette"]
    lines += ["## Bảng màu", f"- {pal_note}", "- " + ", ".join(f"{k} {v}" for k, v in pal.items()), ""]
    lines += ["## Font", *([f"- dự phòng: {f}" for f in sorted(fonts.fallbacks_used)] or ["- dùng font thật"]), ""]
    lines += ["## Printable", *([f"- {p.name}" for p in digital_files] or ["- chưa tạo (cần đủ 12 tháng + bìa)"])]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"pages": [str(p) for p, _ in pngs], "issues": issues, "art": art_notes, "complete": complete,
            "digital": [str(p) for p in digital_files], "font_fallbacks": sorted(fonts.fallbacks_used), "out": str(out)}
