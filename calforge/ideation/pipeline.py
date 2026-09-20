"""Keyword -> góc tiếp cận (P1) -> concept (P2) -> kiểm tra -> sửa lỗi (P3) -> concept.json.

Thư mục (ổ đĩa là sổ tiến độ, chạy lại thì đi tiếp từ chỗ dừng):

    projects/<keyword>/
      ideation/                 sổ hỏi/đáp với ChatGPT (*.prompt.md, *.response.md)
      angles.json               tất cả góc tiếp cận đã sinh cho keyword này
      <angle-id>-<slug>/
        concept.json            concept đã qua kiểm tra
        concept_report.md       cảnh báo cho người duyệt
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..core import kjv
from ..llm.base import Backend, LazyChat, Ledger
from . import catalog, templates
from .extract import extract_json
from .validate import usable_angles, validate_angles, validate_concept


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "untitled"


@dataclass
class IdeationResult:
    keyword_dir: Path
    angles: list[dict]
    concepts: list[Path] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _ask_validated(chat: LazyChat, label: str, prompt: str, validator, max_repairs: int):
    """Hỏi, bóc JSON, kiểm tra; sai thì gửi P3 kèm danh sách lỗi, tối đa max_repairs lần."""
    data, errors, warnings = None, [], []
    for attempt in range(max_repairs + 1):
        this_label = label if attempt == 0 else f"{label}_repair{attempt}"
        if attempt == 0:
            this_prompt = prompt
        elif data is None:
            this_prompt = ("Your previous answer did not contain valid JSON. Return ONLY the JSON "
                           "in one ```json code block, following the schema I gave.")
        else:
            this_prompt = templates.p3_repair(errors, data)
        answer = chat.ask(this_prompt, this_label)
        try:
            data = extract_json(answer)
        except ValueError as e:
            data, errors = None, [str(e)]
            continue
        errors, warnings = validator(data)
        if not errors:
            return data, [], warnings
        if attempt < max_repairs:
            print(f"  ⟳ Có {len(errors)} lỗi, bảo ChatGPT sửa (lần {attempt + 1}): "
                  f"{errors[0][:80]}...", flush=True)
    return data, errors, warnings


def run_ideation(keyword: str, backend: Backend, projects_root: Path, *, year: int, market: str = "US",
                 n_angles: int = 5, more: bool = False, pick: list[str] | None = None,
                 auto_pick: int = 1, style: str | None = None, max_repairs: int = 2,
                 family: str | None = None) -> IdeationResult:
    kdir = projects_root / slugify(keyword)
    kdir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(kdir / "ideation")
    angles_file = kdir / "angles.json"
    all_angles: list[dict] = json.loads(angles_file.read_text(encoding="utf-8")) if angles_file.exists() else []

    with LazyChat(backend, ledger) as chat:
        # ---- P1: góc tiếp cận ----
        last_run = max((a.get("run", 1) for a in all_angles), default=0)
        need_p1 = more or not all_angles
        # Lượt mới = số kế tiếp. Nếu lần trước đã có câu trả lời nhưng chưa kịp ghi angles.json
        # thì sổ hỏi/đáp vẫn giữ câu trả lời đó -> dùng lại, không hỏi lại.
        run_no = last_run + 1 if need_p1 else last_run
        if need_p1:
            print(f"▶ P1: ChatGPT nghĩ {n_angles} góc tiếp cận cho '{keyword}'...", flush=True)
            existing = [f'{a["title"]} ({a["frame_type"]})' for a in all_angles]
            prompt = templates.p1_angles(keyword, year, market, n_angles, existing, projects_root)
            data, errors, _ = _ask_validated(chat, f"p1_angles_run{run_no}", prompt, validate_angles, max_repairs)
            if errors:
                raise RuntimeError("P1 vẫn lỗi sau khi sửa:\n- " + "\n- ".join(errors))
            print(f"  ✔ P1: có {len(data['angles'])} góc: "
                  + ", ".join(f"{a['title']} [{a.get('style_family')}]" for a in data["angles"]), flush=True)
            for a in data["angles"]:  # đánh id duy nhất xuyên các lượt
                a["id"] = f"r{run_no}{a['id']}"
                a["run"] = run_no
            all_angles += data["angles"]
            angles_file.write_text(json.dumps(all_angles, ensure_ascii=False, indent=2), encoding="utf-8")

        # ---- chọn góc ----
        if pick:
            chosen = [a for a in all_angles if a["id"] in pick]
            unknown = set(pick) - {a["id"] for a in chosen}
            if unknown:
                raise ValueError(f"Không có góc: {', '.join(sorted(unknown))}")
        else:
            latest = {"angles": [a for a in all_angles if a.get("run") == run_no]}
            pool = usable_angles(latest)
            if family:  # ép họ style: lấy trong mọi lượt đã sinh
                pool = [a for a in usable_angles({"angles": all_angles}) if a.get("style_family") == family]
                if not pool:
                    raise ValueError(f"Chưa có góc nào thuộc họ style '{family}' - chạy thêm --more")
            # họ style ít dùng trong danh mục được ưu tiên -> danh mục không lặp một kiểu vẽ
            chosen = catalog.rank_angles(pool, projects_root)[:auto_pick]
        result = IdeationResult(kdir, all_angles)

        # ---- P2: concept cho từng góc đã chọn ----
        for angle in chosen:
            cdir = kdir / f"{angle['id']}-{slugify(angle['title'], 30)}"
            if (cdir / "concept.json").exists():
                result.concepts.append(cdir)
                continue
            print(f"▶ P2: viết concept 12 tháng cho \"{angle['title']}\" "
                  f"[{angle.get('style_family')}]...", flush=True)
            angle_style = style or (angle.get("suggested_styles") or ["soft watercolor"])[0]
            angle_view = {k: v for k, v in angle.items() if k != "run"}
            prompt = templates.p2_concept(angle_view, angle_style, year, market)
            concept, errors, warnings = _ask_validated(
                chat, f"p2_concept_{angle['id']}", prompt,
                lambda c: validate_concept(c, year, market), max_repairs)
            cdir.mkdir(parents=True, exist_ok=True)
            if errors:
                (cdir / "concept_failed.json").write_text(json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")
                _report(cdir, angle, errors, warnings)
                result.failed.append(angle["id"])
                continue
            concept.update({"year": year, "market": market, "keyword": keyword, "angle_id": angle["id"]})
            concept["style"]["family"] = angle.get("style_family")
            if concept.get("content_type") == "bible_verse_kjv":
                for m in concept["months"]:  # lời câu lấy từ dữ liệu KJV, không lấy từ ChatGPT
                    m["content"]["text"] = kjv.lookup(m["content"]["value"])
            (cdir / "concept.json").write_text(json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")
            _report(cdir, angle, [], warnings)
            result.concepts.append(cdir)
    return result


def import_angles(keyword: str, data: dict, projects_root: Path, source: str) -> tuple[list[dict], list[str], list[str]]:
    """Nhập một lượt góc tiếp cận do nơi khác nghĩ ra (vd Gemini) vào angles.json như một lượt P1.

    Chạy đúng bộ kiểm tra của P1; có lỗi thì KHÔNG nhập. Trả về (góc đã nhập, lỗi, cảnh báo)."""
    errors, warnings = validate_angles(data)
    if errors:
        return [], errors, warnings
    kdir = projects_root / slugify(keyword)
    kdir.mkdir(parents=True, exist_ok=True)
    angles_file = kdir / "angles.json"
    all_angles = json.loads(angles_file.read_text(encoding="utf-8")) if angles_file.exists() else []
    run_no = max((a.get("run", 1) for a in all_angles), default=0) + 1
    new = []
    for a in data["angles"]:
        a = dict(a, id=f"r{run_no}{a['id']}", run=run_no, source=source)
        new.append(a)
    angles_file.write_text(json.dumps(all_angles + new, ensure_ascii=False, indent=2), encoding="utf-8")
    return new, [], warnings


def _report(cdir: Path, angle: dict, errors: list[str], warnings: list[str]) -> None:
    lines = [f"# {angle['title']} ({angle['id']})", "", f"- Người mua: {angle.get('buyer', '')}",
             f"- Khuôn 12 tháng: {angle.get('frame_type')}", f"- Hook: {angle.get('hook', '')}", ""]
    if errors:
        lines += ["## Lỗi chưa sửa được (concept KHÔNG được nhận)", *[f"- {e}" for e in errors], ""]
    if warnings:
        lines += ["## Cảnh báo", *[f"- {w}" for w in warnings], ""]
    if not errors and not warnings:
        lines.append("Không có lỗi hay cảnh báo.")
    (cdir / "concept_report.md").write_text("\n".join(lines), encoding="utf-8")
