"""Gen ảnh neo, cover + 12 artwork, rồi một nền grid dùng chung cho cả bộ.

Ổ đĩa là sổ tiến độ: job nào đã có ảnh trong _he_thong/anh_ai/ thì bỏ qua. Sau khi gen, kiểm tra từng ảnh
(tỉ lệ, kích thước) ngay lúc nhận - ảnh không đạt coi như lỗi tạm và gen lại; và so màu với ảnh neo
để gắn cờ ảnh lệch style (ghi vào _he_thong/ky_thuat/qc.md cho người duyệt, không tự loại).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .driver import GenJob, run_jobs
from .. import layout
from .plan import ANCHOR, SWATCH, build_jobs, job_done
from .swatch import make_swatch

ASPECT_RANGE = (1.35, 1.65)   # yêu cầu 3:2 = 1.5
MIN_LONG_SIDE = 1024


def accept_grid_page(path: Path, year: int, month: int) -> str | None:
    """Trang lịch AI vẽ nguyên trang: ngang (4:3..3:2) rồi OCR soát từng ngày (grid_check)."""
    with Image.open(path) as im:
        w, h = im.size
    if max(w, h) < MIN_LONG_SIDE:
        return f"ảnh nhỏ quá ({w}x{h})"
    if not 1.2 <= w / h <= 1.65:
        return f"sai tỉ lệ ({w}x{h}, cần trang ngang 4:3)"
    from .grid_check import check_grid_page
    return check_grid_page(path, year, month)


def accept_landscape(path: Path) -> str | None:
    with Image.open(path) as im:
        w, h = im.size
    if max(w, h) < MIN_LONG_SIDE:
        return f"ảnh nhỏ quá ({w}x{h})"
    ratio = w / h
    if not ASPECT_RANGE[0] <= ratio <= ASPECT_RANGE[1]:
        return f"sai tỉ lệ ({w}x{h}, cần ngang 3:2)"
    return None


def _relative_luminance(rgb: np.ndarray) -> np.ndarray:
    srgb = rgb.astype(np.float32) / 255.0
    linear = np.where(srgb <= .04045, srgb / 12.92, ((srgb + .055) / 1.055) ** 2.4)
    return linear[..., 0] * .2126 + linear[..., 1] * .7152 + linear[..., 2] * .0722


def _hex_rgb(value: str) -> np.ndarray | None:
    value = str(value).strip()
    if len(value) != 7 or not value.startswith("#"):
        return None
    try:
        return np.array([int(value[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)
    except ValueError:
        return None


def accept_grid_background(path: Path, text_colors: list[str] | None = None) -> str | None:
    """Reject only visual noise or poor contrast in the software writing area."""
    problem = accept_landscape(path)
    if problem:
        return problem
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB").resize((600, 400)), dtype=np.float32)
    gray = _relative_luminance(rgb)
    center = gray[120:352, 48:552]  # x 8-92%, y 30-88%: calendar writing area
    gx = np.abs(np.diff(center, axis=1))
    gy = np.abs(np.diff(center, axis=0))
    gradient = (gx[:gy.shape[0], :] + gy[:, :gx.shape[1]]) / 2
    # High-frequency edges impair type regardless of whether the chosen surface is light or dark.
    # Global tonal variation is allowed: gradients, ink fields and textile/collage surfaces may vary slowly.
    if (gradient > .12).mean() > .03:
        return "vùng đặt lịch quá nhiều cạnh hoặc chi tiết; cần giảm nhiễu nhưng không cần đổi loại bề mặt"
    for value in text_colors or []:
        text_rgb = _hex_rgb(value)
        if text_rgb is None:
            continue
        text_lum = float(_relative_luminance(text_rgb))
        contrast = (np.maximum(center, text_lum) + .05) / (np.minimum(center, text_lum) + .05)
        if float(np.median(contrast)) < 4.5 or float((contrast < 3.0).mean()) > .08:
            return f"vùng đặt lịch thiếu tương phản với màu chữ {value}; giữ surface system nhưng chỉnh tone"
    valid_text_lums = [float(_relative_luminance(v)) for value in text_colors or []
                       if (v := _hex_rgb(value)) is not None]
    # Nền grid là tint pastel NHẬN RA ĐƯỢC của màu nền cả cuốn (khoảng 88–93% độ sáng, xem prompts._grid_tone_rule),
    # không còn là gần trắng; độ đọc chữ đã do kiểm tra tương phản ở trên lo. Chỉ chặn nền thật sự tối/trung tính.
    if valid_text_lums and max(valid_text_lums) < .35 and float(np.median(center)) < .64:   # ~L* 84
        return "vùng đặt lịch vẫn quá đậm; cần tint pastel sáng (khoảng 88–93% độ sáng) của shared base cho chữ tối"
    return None


def _color_signature(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        small = im.convert("RGB").resize((64, 43))
    hsv = np.asarray(small.convert("HSV"), dtype=np.float32).reshape(-1, 3)
    hist = [np.histogram(hsv[:, i], bins=12, range=(0, 255))[0] for i in range(3)]
    v = np.concatenate(hist).astype(np.float32)
    return v / v.sum()


def style_drift(anchor: Path, other: Path) -> float:
    """0 = cùng bảng màu với ảnh neo, càng lớn càng lệch (khoảng cách L1 trên histogram HSV)."""
    return float(np.abs(_color_signature(anchor) - _color_signature(other)).sum())


def available_profiles(profiles_dir: Path, wanted: list[str] | None) -> list[str]:
    names = wanted or sorted((p.name for p in profiles_dir.iterdir() if p.is_dir()), key=lambda n: (n == "acc1", n))
    return [n for n in names if (profiles_dir / n).is_dir()]


def rotate_profiles(names: list[str], state: Path) -> list[str]:
    """Mỗi cuốn bắt đầu từ tài khoản kế tiếp: ảnh neo và nền grid (việc 1 ảnh, chạy trên tài khoản đầu
    danh sách) không dồn mãi vào một tài khoản, cho hạn mức các tài khoản hao đều nhau."""
    if len(names) < 2:
        return names
    try:
        n = int(json.loads(state.read_text(encoding="utf-8")).get("next", 0))
    except (OSError, ValueError, AttributeError):
        n = 0
    i = n % len(names)
    try:
        state.write_text(json.dumps({"next": n + 1}), encoding="utf-8")
    except OSError:
        pass
    return names[i:] + names[:i]


QUOTA_MARK = "hết tài khoản còn lượt"      # driver.run_jobs ghi vào job.error khi mọi tài khoản đã nghỉ


def generate_concept(concept_dir: Path, profiles_dir: Path, profiles: list[str] | None = None, *,
                     headless=False, timeout_s=420, max_attempts=3, drift_warn=0.9, on_event=print) -> dict:
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    raw = layout.raw(concept_dir)
    raw.mkdir(parents=True, exist_ok=True)
    specs = {j["id"]: j for j in build_jobs(concept)}
    names = available_profiles(profiles_dir, profiles)
    if not names:
        raise RuntimeError(f"Không có Chrome profile nào trong {profiles_dir}")
    names = rotate_profiles(names, profiles_dir / ".image_rotation.json")

    def to_job(spec: dict, reference: Path | None) -> GenJob:
        if spec["kind"] == "grid_background":
            palette = (concept.get("style") or {}).get("palette") or {}
            text_colors = [palette.get("title", ""), palette.get("text", "")]
            accept = lambda path: accept_grid_background(path, text_colors)
        elif spec["kind"] == "grid_page":
            year, mo = int(concept["year"]), int(spec["month"])
            accept = lambda path, year=year, mo=mo: accept_grid_page(path, year, mo)
        else:
            accept = accept_landscape
        # "anchor.png" trong kế hoạch = ảnh neo thật (có thể là .jpg); còn lại là file trong concept.
        attach = [reference if a == ANCHOR else concept_dir / a
                  for a in spec["attach"]] if reference else []
        return GenJob(spec["id"], spec["prompt"], raw / spec["id"], attach, accept)

    failed = {}
    # 1) ảnh neo - mọi ảnh khác bám theo nó
    anchor = job_done(concept_dir, "anchor")
    if anchor is None:
        on_event("Gen ảnh neo style...")
        [job] = run_jobs([to_job(specs["anchor"], None)], profiles_dir, names[:1] if len(names) == 1 else names,
                         headless=headless, timeout_s=timeout_s, max_attempts=max_attempts, on_event=on_event)
        if job.result is None:
            raise RuntimeError(f"Không gen được ảnh neo: {job.error}")
        anchor = job.result

    # Dải màu + texture từ ảnh neo: cover và 12 tháng bám màu mà không chép bố cục ảnh neo.
    swatch = concept_dir / SWATCH
    if not swatch.exists():
        make_swatch(anchor, swatch)

    # 2) các job còn lại, song song, kèm dải màu của ảnh neo
    pending = [to_job(s, anchor) for jid, s in specs.items()
               if s["kind"] in {"cover", "month"} and not job_done(concept_dir, jid)]
    if pending:
        on_event(f"Gen {len(pending)} ảnh trên {len(names)} tài khoản: {', '.join(names)}")
        for job in run_jobs(pending, profiles_dir, names, headless=headless, timeout_s=timeout_s,
                            max_attempts=max_attempts, on_event=on_event):
            if job.result is None:
                failed[job.id] = job.error

    # 3) Một nền grid dùng chung tham chiếu ảnh neo của cả collection.
    grid_pending = []
    for spec in specs.values():
        if spec["kind"] not in ("grid_background", "grid_page") or job_done(concept_dir, spec["id"]):
            continue
        grid_pending.append(to_job(spec, anchor))
    if grid_pending:
        on_event(f"Gen {len(grid_pending)} trang lịch AI (OCR soát ngày, sai thì vẽ lại)..."
                 if grid_pending[0].id != "grid" else "Gen nền grid AI dùng chung cho 12 tháng...")
        for job in run_jobs(grid_pending, profiles_dir, names, headless=headless, timeout_s=timeout_s,
                            max_attempts=max_attempts, on_event=on_event):
            if job.result is None:
                failed[job.id] = job.error

    # 4) QC màu so với ảnh neo; trang grid có nhiều khoảng viết sáng nên không dùng ngưỡng lệch màu đó.
    qc = ["# QC ảnh", "", f"Ảnh neo: {anchor.name}", "", "| job | kích thước | lệch màu so với neo | ghi chú |",
          "|---|---|---|---|"]
    flags = []
    for jid in specs:
        p = job_done(concept_dir, jid)
        if p is None:
            qc.append(f"| {jid} | - | - | THIẾU: {failed.get(jid, 'chưa gen')} |")
            continue
        with Image.open(p) as im:
            size = f"{im.width}x{im.height}"
        if jid == "anchor":
            qc.append(f"| {jid} | {size} | - | |")
            continue
        if specs[jid]["kind"] == "grid_page":
            qc.append(f"| {jid} | {size} | - | trang lịch AI, OCR đã soát ngày |")
            continue
        if specs[jid]["kind"] == "grid_background":
            qc.append(f"| {jid} | {size} | - | thiết kế grid AI; duyệt cạnh artwork tháng |")
            continue
        d = style_drift(anchor, p)
        note = "⚠ lệch màu nhiều - xem lại" if d > drift_warn else ""
        if note:
            flags.append(jid)
        qc.append(f"| {jid} | {size} | {d:.2f} | {note} |")
    layout.tech(concept_dir).mkdir(parents=True, exist_ok=True)
    layout.tech(concept_dir, "qc.md").write_text("\n".join(qc), encoding="utf-8")
    missing = [jid for jid in specs if job_done(concept_dir, jid) is None]
    return {"missing": missing, "failed": failed, "drift_flags": flags}
