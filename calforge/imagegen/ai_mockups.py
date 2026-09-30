"""AI gen mockup (Wall Calendar (Blank), "AI vẽ cả trang" + "AI gen mockup"): 4 ảnh quảng cáo do ChatGPT dựng bối cảnh.

Chạy SAU khi code đã ghép mockup (render/mockups.previews), vì ảnh 2/3/4 cần đúng mockup code làm ảnh kèm:
- 01_front_cover_spiral: kèm IMAGE 1 = data/mockups/front_cover_spiral.webp, IMAGE 2 = tranh bìa AI gốc (anh_ai/cover.*)
- 02_open_spread_flat / 03_three_open_spreads / 05_wall_page_turn: kèm mockup code của chính ảnh đó
Ảnh AI GHI ĐÈ đúng file preview (R2 / CSV dùng thẳng). Ảnh AI nào hỏng hẳn / hết lượt: GIỮ mockup code ở chỗ đó
(cuốn không bị kẹt), ghi lại để "Làm lại ảnh quảng cáo" gen lại sau.

Nhớ trạng thái ở _he_thong/ky_thuat/mockup_ai.json: {preview: {"mtime_ns": ...}} = mtime của ảnh AI đã ghi. File
preview có mtime khác (code vừa ghép lại vì trang in đổi / bấm Làm lại ảnh quảng cáo) -> gen AI lại ảnh đó.
Bản mockup code dùng làm ảnh kèm được giữ ở _he_thong/ky_thuat/mockup_goc/.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from .. import layout
from .mockup_prompts import AI_PREVIEWS, COVER_PROMPT, SCENE_PROMPT, SQUARE_COVER, SQUARE_SCENE

ROOT = Path(__file__).resolve().parents[2]
COVER_TEMPLATE = ROOT / "data" / "mockups" / "front_cover_spiral.webp"
MIN_SIDE = 1000


def _state_file(cdir: Path) -> Path:
    return layout.tech(cdir, "mockup_ai.json")


def _load(cdir: Path) -> dict:
    try:
        return json.loads(_state_file(cdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def accept_mockup(path: Path) -> str | None:
    with Image.open(path) as im:
        w, h = im.size
    if max(w, h) < MIN_SIDE:
        return f"ảnh nhỏ quá ({w}x{h})"
    if not 0.9 <= w / h <= 1.1:                         # yêu cầu vuông 1:1 (cho lệch chút)
        return f"không vuông 1:1 ({w}x{h})"
    return None


def pending(cdir: Path) -> list[str]:
    """Preview cần gen AI: có bản code mới (khác ảnh AI đã ghi) hoặc chưa từng gen AI."""
    st = _load(cdir)
    out = []
    for name in AI_PREVIEWS:
        f = layout.listing(cdir) / f"{name}.jpg"
        if not f.is_file():
            continue                                    # mockup code chưa có (lỗi ghép): không có gì để dựa vào
        rec = st.get(name) or {}
        if rec.get("mtime_ns") != f.stat().st_mtime_ns:
            out.append(name)
    return out


def ai_previews(cdir: Path, cfg: dict, on_event=print) -> dict:
    """Gen AI các preview còn cần. Trả về {"ai": [...], "kept_code": [...]}."""
    from ..config import get_profiles_dir
    from .driver import GenJob, run_jobs
    from .generate import available_profiles, rotate_profiles
    from .plan import job_done

    todo = pending(cdir)
    if not todo:
        return {"ai": [], "kept_code": []}
    cover = job_done(cdir, "cover")
    goc = layout.tech(cdir, "mockup_goc")
    work = layout.tech(cdir, "mockup_ai")
    goc.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    jobs = []
    for name in todo:
        src = layout.listing(cdir) / f"{name}.jpg"
        keep = goc / f"{name}.jpg"
        shutil.copy2(src, keep)                         # bản code: ảnh kèm cho AI + dự phòng nếu AI hỏng
        if AI_PREVIEWS[name] is None:
            if cover is None or not COVER_TEMPLATE.is_file():
                on_event(f"  ⚠ {name}: thiếu tranh bìa gốc hoặc khung bìa - giữ mockup code")
                continue
            attach, prompt = [COVER_TEMPLATE, cover], COVER_PROMPT + SQUARE_COVER   # IMAGE 1 = khung, IMAGE 2 = bìa gốc
        else:
            attach, prompt = [keep], SCENE_PROMPT + SQUARE_SCENE
        for old in work.glob(f"{name}.*"):
            old.unlink()
        jobs.append(GenJob(name, prompt, work / name, attach, accept_mockup))
    if not jobs:
        return {"ai": [], "kept_code": todo}
    ig = cfg.get("imagegen") or {}
    pdir = get_profiles_dir(cfg)
    names = rotate_profiles(available_profiles(pdir, ig.get("profiles")), pdir / ".image_rotation.json")
    on_event(f"▶ AI gen {len(jobs)} ảnh quảng cáo (mockup bối cảnh riêng cho cuốn này)")
    run_jobs(jobs, pdir, names, headless=ig.get("headless", "hidden"), timeout_s=ig.get("timeout_s", 420),
             max_attempts=ig.get("max_attempts", 3), on_event=on_event)
    st = _load(cdir)
    done, kept = [], []
    for j in jobs:
        dst = layout.listing(cdir) / f"{j.id}.jpg"
        if j.result is not None and Path(j.result).is_file():
            with Image.open(j.result) as im:
                im.convert("RGB").save(dst, quality=92)
            st[j.id] = {"mtime_ns": dst.stat().st_mtime_ns}
            done.append(j.id)
        else:
            kept.append(j.id)                           # giữ mockup code (file preview không đổi)
            st.pop(j.id, None)
            on_event(f"  ⚠ {j.id}: AI chưa gen được ({(j.error or '')[:100]}) - tạm dùng mockup code")
    layout.tech(cdir).mkdir(parents=True, exist_ok=True)
    _state_file(cdir).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ai": done, "kept_code": kept + [n for n in todo if n not in {j.id for j in jobs}]}
