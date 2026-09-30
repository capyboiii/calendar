"""Keyword -> góc tiếp cận (P1) -> concept (P2) -> kiểm tra -> sửa lỗi (P3) -> concept.json.

Thư mục (ổ đĩa là sổ tiến độ, chạy lại thì đi tiếp từ chỗ dừng):

    projects/<loại lịch>/<keyword>/
      _he_thong/ideation/       sổ hỏi/đáp với ChatGPT (*.prompt.md, *.response.md)
      _he_thong/angles.json     tất cả góc tiếp cận đã sinh cho keyword này
      <Tên cuốn>/               tên thư mục = tên cuốn; mã góc nằm ở _he_thong/angle_id.txt
        _he_thong/concept.json  concept đã qua kiểm tra (cấu trúc cuốn: calforge/layout.py)
        _he_thong/ky_thuat/concept_report.md   cảnh báo cho người duyệt
"""
from __future__ import annotations

import json
import threading
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import layout
from ..core import kjv
from ..llm.base import Backend, LazyChat, Ledger
from . import catalog, templates
from .extract import extract_json
from .validate import usable_angles, validate_angles, validate_concept
from ..render.grid_compositions import COMPOSITIONS


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].strip("-") or "untitled"


@dataclass
class IdeationResult:
    keyword_dir: Path
    angles: list[dict]
    concepts: list[Path] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


# ChatGPT trả lời kiểu "không thấy JSON gốc trong cuộc trò chuyện, hãy dán lại" (chat bị đổi phiên/tài khoản
# hoặc mất ngữ cảnh): gửi lại kèm JSON, không tính là một lần sửa.
LOST_CONTEXT = re.compile(r"(not available in this conversation|paste the (original )?json|don't have (access to )?the "
                          r"(original|previous) json|can(?:no|')t see the (original|previous)|provide the (original )?json)",
                          re.I)


def _ask_validated(chat: LazyChat, label: str, prompt: str, validator, max_repairs: int):
    """Hỏi, bóc JSON, kiểm tra; sai thì gửi P3 kèm danh sách lỗi, tối đa max_repairs lần."""
    data, errors, warnings = None, [], []
    asked: list[str] = []
    for attempt in range(max_repairs + 1):
        this_label = label if attempt == 0 else f"{label}_repair{attempt}"
        if attempt == 0:
            this_prompt = prompt
        elif data is None:
            this_prompt = ("Your previous answer did not contain valid JSON. Return ONLY the JSON "
                           "in one ```json code block, following the schema I gave.")
        else:
            # Luôn kèm JSON cũ (gọn): chat có thể đã đổi phiên/tài khoản hoặc model mất ngữ cảnh - không kèm
            # thì nó trả lời "không thấy JSON" và cuốn hỏng oan.
            this_prompt = templates.p3_repair(errors, data, include_previous=True)
        answer = chat.ask(this_prompt, this_label)
        asked.append(this_label)
        if attempt > 0 and data is not None and LOST_CONTEXT.search(answer or ""):
            print("  ⟳ ChatGPT báo không thấy JSON cũ - gửi lại kèm JSON (không tính lượt sửa)", flush=True)
            answer = chat.ask(templates.p3_repair(errors, data, include_previous=True), f"{this_label}_resend")
            asked.append(f"{this_label}_resend")
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
    # Hỏng hẳn: xoá các câu trả lời hỏng khỏi sổ hỏi/đáp, để lần chạy lại HỎI CHATGPT LẠI thay vì dùng lại mãi
    # đúng câu hỏng đó (trước đây batch kẹt vĩnh viễn ở bước này dù bấm "Làm nốt phần thiếu" bao nhiêu lần).
    ledger = getattr(chat, "ledger", None)
    if ledger is not None:
        for lbl in asked:
            try:
                ledger.response_path(lbl).unlink()
            except OSError:
                pass
    return data, errors, warnings


def _made(kdir: Path, angle: dict) -> bool:
    d = layout.find_book(kdir, angle["id"])
    return d is not None and layout.is_book(d)


def _handled(kdir: Path, angle: dict) -> bool:
    """Đã viết concept (thành cuốn hoặc hỏng hẳn sau các vòng sửa): lượt đó coi như xong."""
    return layout.find_book(kdir, angle["id"]) is not None


def _load_review(kdir: Path, run_no: int) -> dict | None:
    f = layout.ideation_dir(kdir) / f"review_run{run_no}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _review_and_pick(keyword: str, backend: Backend, ledger: Ledger, kdir: Path, projects_root: Path,
                     pool: list[dict], run_no: int, n: int, max_repairs: int,
                     quota: dict[str, int] | None = None) -> list[dict]:
    """Người thẩm định = một cuộc trò chuyện MỚI (không biết ai viết các ý) quyết định ý nào trùng danh mục
    và chọn n ý khác nhau nhất. Kết quả lưu ở ideation/review_run<N>.json."""
    if not pool:
        return []
    ids = {a["id"] for a in pool}

    def validate(data: dict) -> tuple[list[str], list[str]]:
        errors = []
        decisions = data.get("decisions") or []
        seen = [d.get("id") for d in decisions]
        missing = ids - set(seen)
        if missing:
            errors.append(f"decisions is missing ids: {', '.join(sorted(missing))}")
        unknown = set(data.get("selected") or []) - ids
        if unknown:
            errors.append(f"selected contains unknown ids: {', '.join(sorted(unknown))}")
        kept = {d.get("id") for d in decisions if d.get("keep")}
        if set(data.get("selected") or []) - kept:
            errors.append("selected may only contain ids with keep=true")
        if len(data.get("selected") or []) > n:
            errors.append(f"selected must contain at most {n} ids")
        fam = {a["id"]: a.get("style_family") for a in pool}
        for fid, k in (quota or {}).items():
            got = sum(fam.get(i) == fid for i in data.get("selected") or [])
            if got > k:
                errors.append(f'selected has {got} ids with style_family "{fid}", the style split allows at most {k}')
        return errors, []

    print(f"▶ P1b: ChatGPT (cuộc chat riêng) thẩm định trùng lặp {len(pool)} ý với cả danh mục...", flush=True)
    with LazyChat(backend, ledger) as reviewer:
        prompt = templates.p1b_review(keyword, n, pool, projects_root, quota)
        data, errors, _ = _ask_validated(reviewer, f"p1b_review_run{run_no}", prompt, validate, max_repairs)
    if errors or not data:
        print(f"  ⚠ Thẩm định lỗi, dùng xếp hạng cũ: {errors[:1]}", flush=True)
        return []
    (layout.ideation_dir(kdir) / f"review_run{run_no}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for d in data.get("decisions", []):
        mark = "✔ giữ" if d.get("keep") else "✘ loại"
        why = d.get("duplicates") or d.get("reason", "")
        print(f"  {mark} {d.get('id')}: {why[:110]}", flush=True)
    by_id = {a["id"]: a for a in pool}
    chosen = [by_id[i] for i in data.get("selected", []) if i in by_id][:n]
    if len(chosen) < n:
        print(f"  ⚠ Chỉ còn {len(chosen)}/{n} ý không trùng - chạy lại để AI nghĩ thêm lượt ý mới", flush=True)
    return chosen


_ASSIGN = threading.Lock()        # chia tông / chất liệu / bố cục khi nhiều cuốn viết concept song song
_RESERVED_TONES: list[str] = []   # tông đã giao cho cuốn đang viết (chưa ghi concept xuống đĩa)

ROUND_SIZE = 3   # số cuốn mỗi lượt P1 -> P1b: câu trả lời của AI giữ độ dài cố định dù batch lớn


def run_ideation_batched(keyword: str, backend: Backend, projects_root: Path, *, auto_pick: int = 1,
                         pick: list[str] | None = None, on_round=None, **kw) -> IdeationResult:
    """Batch N cuốn = nhiều lượt nhỏ tối đa ROUND_SIZE cuốn, mỗi lượt P1 (3x ý) + P1b riêng.
    Lượt sau thấy các cuốn lượt trước trong danh mục nên vẫn chống trùng xuyên lượt.
    on_round(res): gọi sau mỗi lượt (vd sản xuất luôn các cuốn vừa có concept)."""
    if pick or auto_pick <= ROUND_SIZE:
        res = run_ideation(keyword, backend, projects_root, auto_pick=auto_pick, pick=pick, **kw)
        if on_round:
            on_round(res)
        return res
    total: IdeationResult | None = None
    left, rnd, rounds = auto_pick, 0, -(-auto_pick // ROUND_SIZE)
    while left > 0:
        rnd += 1
        n = min(ROUND_SIZE, left)
        print(f"▶ Lượt {rnd}/{rounds}: lên ý tưởng cho {n} cuốn", flush=True)
        res = run_ideation(keyword, backend, projects_root, auto_pick=n, **kw)
        if total is None:
            total = res
        else:
            total.angles = res.angles
            total.concepts += [c for c in res.concepts if c not in total.concepts]
            total.failed += [f for f in res.failed if f not in total.failed]
        if on_round:
            on_round(res)
        left -= n
        kw["more"] = False   # --more chỉ ép lượt đầu; các lượt sau tự mở lượt ý mới khi lượt trước xong
    return total


def run_ideation(keyword: str, backend: Backend, projects_root: Path, *, year: int, market: str = "US",
                 n_angles: int = 1, more: bool = False, pick: list[str] | None = None,
                 auto_pick: int = 1, style: str | None = None, max_repairs: int = 2,
                 family: str | None = None, grid_preset: str | None = None,
                 product: str | None = None, keyword_root: Path | None = None,
                 grid_mode: str | None = None, p2_parallel: int = 3,
                 mockup_mode: str | None = None) -> IdeationResult:
    # keyword_root: thư mục loại lịch (projects/Wall Calendar (Blank)...); danh mục chống trùng, chia đều style/nền/
    # bố cục vẫn tính trên TOÀN BỘ projects_root (mọi loại lịch)
    kdir = (keyword_root or projects_root) / slugify(keyword)
    kdir.mkdir(parents=True, exist_ok=True)
    layout.ensure_system(kdir)
    ledger = Ledger(layout.ideation_dir(kdir))
    angles_file = layout.angles_file(kdir)
    all_angles: list[dict] = json.loads(angles_file.read_text(encoding="utf-8")) if angles_file.exists() else []

    with LazyChat(backend, ledger) as chat:
        # ---- P1: góc tiếp cận ----
        last_run = max((a.get("run", 1) for a in all_angles), default=0)
        has_requested_family = bool(family and any(
            a.get("style_family") == family for a in usable_angles({"angles": all_angles})
        ))
        need_p1 = more or not all_angles or bool(family and not has_requested_family)
        if not need_p1 and not pick:
            # Batch trước của keyword này đã làm thành cuốn hết -> batch mới phải nghĩ lượt ý mới.
            prev = _load_review(kdir, last_run)
            if prev and prev.get("selected") and all(
                    _handled(kdir, a) for a in all_angles if a.get("run") == last_run and a["id"] in prev["selected"]):
                need_p1 = True
        if not need_p1 and not pick and not family:
            # Ý của lượt gần nhất đã dùng hết (thành cuốn / hỏng) - kể cả khi thẩm định lượt đó lỗi, không có
            # review_run*.json - thì phải nghĩ lượt ý mới, không được chọn lại ý đã làm.
            last = [a for a in all_angles if a.get("run") == last_run]
            if not [a for a in usable_angles({"angles": last}) if not _handled(kdir, a)]:
                need_p1 = True
        n_candidates = max(n_angles, 3 * auto_pick)   # dư ý để người thẩm định có chỗ loại
        # Chia đều họ style (code quyết định, không để người dùng chọn): mỗi suất 3 ý cùng họ cho P1b chọn.
        quota = None if (family or pick) else catalog.family_quota(projects_root, auto_pick)
        cand_quota = {fid: 3 * k for fid, k in quota.items()} if quota else None
        if cand_quota:
            n_candidates = sum(cand_quota.values())
        # Lượt mới = số kế tiếp. Nếu lần trước đã có câu trả lời nhưng chưa kịp ghi angles.json
        # thì sổ hỏi/đáp vẫn giữ câu trả lời đó -> dùng lại, không hỏi lại.
        run_no = last_run + 1 if need_p1 else last_run
        if need_p1:
            print(f"▶ P1: ChatGPT nghĩ {n_candidates} góc tiếp cận cho '{keyword}'...", flush=True)
            # Cuốn đã làm đã có trong danh mục; ở đây chỉ nhắc các ý bị loại của 2 lượt gần nhất (có trần).
            existing = [f'{a["title"]} ({a["frame_type"]})' for a in all_angles
                        if a.get("run", 1) > last_run - 2 and not _made(kdir, a)]
            prompt = templates.p1_angles(keyword, year, market, n_candidates, existing, projects_root, family=family,
                                         quota=cand_quota)

            def validate_for_run(payload: dict) -> tuple[list[str], list[str]]:
                errors, warnings = validate_angles(payload)
                if family:
                    for i, angle in enumerate(payload.get("angles") or []):
                        if angle.get("style_family") != family:
                            errors.append(
                                f'angles[{i}].style_family must be exactly "{family}" because the user selected it'
                            )
                got = [a.get("style_family") for a in payload.get("angles") or []]
                for fid, k in (cand_quota or {}).items():
                    if got.count(fid) != k:
                        errors.append(f'the style split needs exactly {k} angles with style_family "{fid}", '
                                      f'got {got.count(fid)}')
                return errors, warnings

            data, errors, _ = _ask_validated(chat, f"p1_angles_run{run_no}", prompt, validate_for_run, max_repairs)
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
            pool = [a for a in usable_angles(latest) if not _handled(kdir, a)]   # không chọn lại ý đã làm
            if family:  # ép họ style: lấy trong mọi lượt đã sinh
                pool = [a for a in usable_angles({"angles": all_angles}) if a.get("style_family") == family]
                if not pool:
                    raise ValueError(f"Chưa có góc nào thuộc họ style '{family}' - chạy thêm --more")
            # AI (lượt chat riêng) soi trùng với cả danh mục và chọn các ý khác nhau nhất - code không chấm điểm.
            # Playwright không cho mở 2 trình duyệt lồng nhau trong cùng luồng: đóng phiên P1 trước, người
            # thẩm định mở phiên (cuộc chat) riêng của nó; P2 sau đó tự mở lại phiên khi cần.
            chat.close()
            chosen = _review_and_pick(keyword, backend, ledger, kdir, projects_root, pool, run_no, auto_pick,
                                      max_repairs, quota) or catalog.rank_angles(pool, projects_root)[:auto_pick]
        result = IdeationResult(kdir, all_angles)

        # Tell the art director what the portfolio already uses, so it can make a genuinely
        # informed composition choice instead of defaulting every book to the same corner.
        composition_counts = {key: 0 for key in COMPOSITIONS}
        for existing_file in projects_root.rglob("concept.json"):
            try:
                existing = json.loads(existing_file.read_text(encoding="utf-8"))
                key = (existing.get("style") or {}).get("grid_composition")
                if key in composition_counts:
                    composition_counts[key] += 1
            except Exception:  # noqa: BLE001 - one damaged old concept must not stop ideation
                pass

        # ---- P2: concept cho từng góc đã chọn - SONG SONG, mỗi cuốn một chat trên một tài khoản riêng ----
        # (P1/P1b ở trên vẫn tuần tự vì cần nhìn cả danh mục để chống trùng; P2 thì các góc đã khác nhau.)
        chat.close()
        todo = []
        for angle in chosen:
            cdir = layout.find_book(kdir, angle["id"])
            if cdir is not None and layout.is_book(cdir):
                result.concepts.append(cdir)
            else:
                todo.append((angle, cdir))

        def write(angle: dict, cdir: Path | None) -> tuple[Path | None, str | None]:
            """(thư mục cuốn, None) nếu xong; (None, id góc) nếu concept hỏng sau các vòng sửa."""
            from .. import products
            from . import tones
            print(f"▶ P2: viết concept 12 tháng cho \"{angle['title']}\" "
                  f"[{angle.get('style_family')}]...", flush=True)
            angle_style = (style or angle.get("art_direction")
                           or (angle.get("suggested_styles") or ["a distinctive buyer-led visual direction"])[0])
            angle_view = {k: v for k, v in angle.items() if k != "run"}
            tone = None
            with _ASSIGN:            # tông nền giữ chỗ ngay: các cuốn viết song song không nhận trùng tông
                usage = ", ".join(f"{key}={count}" for key, count in composition_counts.items())
                if products.ai_grid({"product": product}):
                    tone = tones.next_tone(projects_root, extra=_RESERVED_TONES)
                    _RESERVED_TONES.append(tone)
            try:
                prompt = templates.p2_concept(angle_view, angle_style, year, market, usage,
                                              base_tone_rule=tones.prompt_rule(tone, projects_root) if tone else "")
                # Mỗi cuốn một cuộc chat mới (P3 sửa lỗi vẫn trong chat của cuốn đó).
                with LazyChat(backend, ledger) as own:
                    concept, errors, warnings = _ask_validated(
                        own, f"p2_concept_{angle['id']}", prompt,
                        lambda c: validate_concept(c, year, market), max_repairs)
                with _ASSIGN:
                    if cdir is None:   # thư mục mang tên cuốn (dễ đọc); mã góc ghi trong _he_thong/angle_id.txt
                        cdir = layout.new_book_dir(kdir, (concept or {}).get("title") or angle["title"], angle["id"])
                if errors:
                    layout.ensure_system(cdir)
                    layout.tech(cdir).mkdir(parents=True, exist_ok=True)
                    layout.tech(cdir, "concept_failed.json").write_text(
                        json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")
                    _report(cdir, angle, errors, warnings)
                    return None, angle["id"]
                concept.update({"year": year, "market": market, "keyword": keyword, "angle_id": angle["id"]})
                concept["style"]["family"] = angle.get("style_family")
                if tone:   # tông giao + tông thật (xếp theo hex AI chọn) để soi lại
                    concept["style"]["base_tone"] = {"assigned": tone, "actual": tones.book_tone(concept)}
                concept["product"] = product if product in products.PRODUCTS else products.DEFAULT
                if products.ai_grid(concept):
                    concept["style"]["grid_mode"] = (grid_mode if grid_mode in products.GRID_MODES
                                                     else products.DEFAULT_GRID_MODE)
                if products.ai_page(concept):       # ảnh quảng cáo: chỉ "AI vẽ cả trang" mới có lựa chọn AI mockup
                    concept["style"]["mockup_mode"] = mockup_mode if mockup_mode in products.MOCKUP_MODES else "template"
                # Khung hình từng tháng do code chia (cùng thứ tự đã đưa vào prompt P2).
                from ..imagegen import shots
                for m, shot in zip(concept["months"],
                                   shots.assign(str(angle.get("title", "")), str(angle.get("frame_type", "")))):
                    m["shot"] = shot
                from ..render.grid_select import apply_grid_selection
                apply_grid_selection(concept, requested=grid_preset or "auto")
                if concept.get("content_type") == "bible_verse_kjv":
                    for m in concept["months"]:  # lời câu lấy từ dữ liệu KJV, không lấy từ ChatGPT
                        m["content"]["text"] = kjv.lookup(m["content"]["value"])
                # Chất liệu + bố cục chia đều theo danh mục: chọn và GHI concept trong cùng khoá, để cuốn viết
                # song song xong ngay sau đó đếm thấy cuốn này.
                from ..imagegen.prompts import next_grid_material
                from ..render.grid_layouts import next_grid_layout
                with _ASSIGN:
                    concept["style"]["grid_material"] = next_grid_material(projects_root)
                    concept["style"]["grid_layout"] = next_grid_layout(projects_root, concept["style"]["grid_material"])
                    selected_composition = concept["style"].get("grid_composition")
                    if selected_composition in composition_counts:
                        composition_counts[selected_composition] += 1
                    layout.ensure_system(cdir)
                    layout.concept_file(cdir).write_text(json.dumps(concept, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
                _report(cdir, angle, [], warnings)
                return cdir, None
            finally:
                if tone:
                    with _ASSIGN:
                        _RESERVED_TONES.remove(tone)

        if todo:
            from concurrent.futures import ThreadPoolExecutor
            workers = max(1, min(len(todo), int(p2_parallel)))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="p2") as ex:
                futures = [ex.submit(write, a, c) for a, c in todo]
                outcomes = [f.result() for f in futures]    # lỗi bất ngờ của một cuốn nổi lên như trước
            for made, failed_id in outcomes:
                if made is not None:
                    result.concepts.append(made)
                if failed_id:
                    result.failed.append(failed_id)
    return result


def import_angles(keyword: str, data: dict, projects_root: Path, source: str,
                  keyword_root: Path | None = None) -> tuple[list[dict], list[str], list[str]]:
    """Nhập một lượt góc tiếp cận do nơi khác nghĩ ra (vd Gemini) vào angles.json như một lượt P1.

    Chạy đúng bộ kiểm tra của P1; có lỗi thì KHÔNG nhập. Trả về (góc đã nhập, lỗi, cảnh báo)."""
    errors, warnings = validate_angles(data)
    if errors:
        return [], errors, warnings
    kdir = (keyword_root or projects_root) / slugify(keyword)
    kdir.mkdir(parents=True, exist_ok=True)
    layout.ensure_system(kdir)
    angles_file = layout.angles_file(kdir)
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
    layout.tech(cdir).mkdir(parents=True, exist_ok=True)
    layout.tech(cdir, "concept_report.md").write_text("\n".join(lines), encoding="utf-8")
