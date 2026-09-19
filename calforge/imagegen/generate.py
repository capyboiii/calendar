"""Gen toàn bộ ảnh của một concept: ảnh neo trước, rồi 12 tháng + họa tiết song song (đính ảnh neo).

Ổ đĩa là sổ tiến độ: job nào đã có ảnh trong art/raw/ thì bỏ qua. Sau khi gen, kiểm tra từng ảnh
(tỉ lệ, kích thước) ngay lúc nhận - ảnh không đạt coi như lỗi tạm và gen lại; và so màu với ảnh neo
để gắn cờ ảnh lệch style (ghi vào art/qc.md cho người duyệt, không tự loại).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from .driver import GenJob, run_jobs
from .plan import build_jobs, job_done

ASPECT_RANGE = (1.35, 1.65)   # yêu cầu 3:2 = 1.5
MIN_LONG_SIDE = 1024


def accept_landscape(path: Path) -> str | None:
    with Image.open(path) as im:
        w, h = im.size
    if max(w, h) < MIN_LONG_SIDE:
        return f"ảnh nhỏ quá ({w}x{h})"
    ratio = w / h
    if not ASPECT_RANGE[0] <= ratio <= ASPECT_RANGE[1]:
        return f"sai tỉ lệ ({w}x{h}, cần ngang 3:2)"
    return None


def accept_any(path: Path) -> str | None:
    with Image.open(path) as im:
        w, h = im.size
    return None if max(w, h) >= 512 else f"ảnh nhỏ quá ({w}x{h})"


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


def generate_concept(concept_dir: Path, profiles_dir: Path, profiles: list[str] | None = None, *,
                     headless=False, timeout_s=420, max_attempts=3, drift_warn=0.9, on_event=print) -> dict:
    concept = json.loads((concept_dir / "concept.json").read_text(encoding="utf-8"))
    raw = concept_dir / "art" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    specs = {j["id"]: j for j in build_jobs(concept)}
    names = available_profiles(profiles_dir, profiles)
    if not names:
        raise RuntimeError(f"Không có Chrome profile nào trong {profiles_dir}")

    def to_job(spec: dict, anchor: Path | None) -> GenJob:
        accept = accept_any if spec["kind"] == "ornament" else accept_landscape
        return GenJob(spec["id"], spec["prompt"], raw / spec["id"],
                      [anchor] if (anchor and spec["attach"]) else [], accept)

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

    # 2) các job còn lại, song song, kèm ảnh neo
    pending = [to_job(s, anchor) for jid, s in specs.items() if jid != "anchor" and not job_done(concept_dir, jid)]
    if pending:
        on_event(f"Gen {len(pending)} ảnh trên {len(names)} tài khoản: {', '.join(names)}")
        for job in run_jobs(pending, profiles_dir, names, headless=headless, timeout_s=timeout_s,
                            max_attempts=max_attempts, on_event=on_event):
            if job.result is None:
                failed[job.id] = job.error

    # 3) QC màu so với ảnh neo
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
        if jid in ("anchor", "ornament"):
            qc.append(f"| {jid} | {size} | - | |")
            continue
        d = style_drift(anchor, p)
        note = "⚠ lệch màu nhiều - xem lại" if d > drift_warn else ""
        if note:
            flags.append(jid)
        qc.append(f"| {jid} | {size} | {d:.2f} | {note} |")
    (concept_dir / "art" / "qc.md").write_text("\n".join(qc), encoding="utf-8")
    missing = [jid for jid in specs if job_done(concept_dir, jid) is None]
    return {"missing": missing, "failed": failed, "drift_flags": flags}
