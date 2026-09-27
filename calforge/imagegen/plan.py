"""Kế hoạch gen ảnh cho một concept: jobs.json + CSV cho chatgpt-automation.

Job: anchor (ảnh neo style sạch), cover (bìa AI gồm typography), m01..m12, rồi grid
(một nền trang dùng chung cho cả 12 tháng). Trang /csv của chatgpt-automation hiện CHƯA đính được ảnh,
nên CSV chỉ chứa 14 artwork cơ bản; nền grid chạy bằng driver có đính ảnh neo. CSV dùng
prompt đứng một mình (style_bible nhắc nguyên văn ở mọi prompt để giữ đồng bộ); khi driver
riêng có đính kèm ảnh neo thì dùng jobs.json.

Ảnh về lưu ở <cuốn>/_he_thong/anh_ai/<job>.png - có file rồi thì job coi như xong.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

from .. import layout
from . import prompts

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
# Cover và 12 tháng đính dải màu + texture rút từ ảnh neo (xem swatch.py), không đính nguyên
# ảnh neo: nguyên ảnh neo làm model chép luôn bố cục. Nền grid vẫn đính ảnh neo.
SWATCH = f"{layout.RAW}/anchor_swatch.png"
ANCHOR = f"{layout.RAW}/anchor.png"


def build_jobs(concept: dict, with_reference: bool = True) -> list[dict]:
    from ..render.pages import resolve_grid_preset

    jobs = [{"id": "anchor", "kind": "anchor", "prompt": prompts.anchor_prompt(concept), "attach": [],
             "expect": {"aspect": "3:2", "alpha": False}}]
    jobs.append({"id": "cover", "kind": "cover", "prompt": prompts.cover_prompt(concept, with_reference),
                 "attach": [SWATCH] if with_reference else [],
                 "expect": {"aspect": "3:2", "alpha": False}})
    for m in concept["months"]:
        jobs.append({"id": f"m{m['month']:02d}", "kind": "month", "month": m["month"],
                     "prompt": prompts.month_prompt(concept, m, with_reference),
                     "attach": [SWATCH] if with_reference else [],
                     "expect": {"aspect": "3:2", "alpha": False}})
    if resolve_grid_preset(concept) == "art_matched":
        jobs.append({"id": "grid", "kind": "grid_background",
                     "prompt": prompts.grid_background_prompt(concept, None, with_reference),
                     "attach": [ANCHOR] if with_reference else [],
                     "expect": {"aspect": "3:2", "alpha": False}})
    return jobs


def job_done(concept_dir: Path, job_id: str) -> Path | None:
    for f in sorted(layout.raw(concept_dir).glob(f"{job_id}.*")):
        if f.suffix.lower() in IMG_EXT and f.stat().st_size > 0:
            return f
    return None


def write_plan(concept_dir: Path) -> list[dict]:
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    jobs = build_jobs(concept)
    for j in jobs:
        done = job_done(concept_dir, j["id"])
        j["status"] = "done" if done else "pending"
        j["out"] = str(done.relative_to(concept_dir)) if done else f"{layout.RAW}/{j['id']}.png"
    layout.raw(concept_dir).mkdir(parents=True, exist_ok=True)
    layout.tech(concept_dir).mkdir(parents=True, exist_ok=True)
    layout.tech(concept_dir, "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    return jobs


# ---------------------------------------------------------------------------
# Cầu nối với chatgpt-automation (trang /csv: mỗi dòng = 1 chat, lưu vào designs/<Topic>__<Style>/)
# ---------------------------------------------------------------------------
def _name_part(value: str, fallback: str) -> str:
    """Giống hệt _name_part trong chatgpt-automation/server.py để đoán đúng tên thư mục ảnh về."""
    cleaned = re.sub(r'[\/*?:"<>|]', "", value or "").strip()
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-. ")[:40]
    return cleaned or fallback


def csv_keys(concept_dir: Path, job_id: str) -> tuple[str, str]:
    """(Topic, Style) ngắn và duy nhất: tên thư mục bên kia bị cắt còn 40 ký tự."""
    tag = hashlib.sha1(str(concept_dir.resolve()).encode()).hexdigest()[:6]
    return f"cal-{tag}-{job_id}", "calforge"


def export_csv(concept_dir: Path, only_pending: bool = True) -> Path:
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    jobs = build_jobs(concept, with_reference=False)
    layout.tech(concept_dir).mkdir(parents=True, exist_ok=True)
    out = layout.tech(concept_dir, "chatgpt_automation.csv")
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Topic", "Style", "Prompt"])
        for j in jobs:
            if j["kind"] == "grid_background":
                continue  # CSV không đính được mXX: không được sinh nền grid lệch artwork.
            if only_pending and job_done(concept_dir, j["id"]):
                continue
            topic, style = csv_keys(concept_dir, j["id"])
            w.writerow([topic, style, j["prompt"]])
    return out


def import_from_automation(concept_dir: Path, automation_dir: Path) -> list[str]:
    """Chép ảnh chatgpt-automation đã gen về _he_thong/anh_ai/<job>.<ext>. Trả về danh sách job vừa nhận."""
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    raw = layout.raw(concept_dir)
    raw.mkdir(parents=True, exist_ok=True)
    got = []
    for j in build_jobs(concept, with_reference=False):
        if j["kind"] == "grid_background":
            continue
        if job_done(concept_dir, j["id"]):
            continue
        topic, style = csv_keys(concept_dir, j["id"])
        folder = automation_dir / "designs" / f"{_name_part(topic, 'Topic')}__{_name_part(style, 'Design')}"
        if not folder.is_dir():
            continue
        imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXT and p.stat().st_size > 0)
        if imgs:
            shutil.copy2(imgs[0], raw / f"{j['id']}{imgs[0].suffix.lower()}")
            got.append(j["id"])
    return got
