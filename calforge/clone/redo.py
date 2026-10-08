"""Vẽ lại vài trang hỏng của một cuốn "Làm theo ảnh mẫu" (nút "Vẽ lại" ở mục Sửa trang hỏng của trang chính).

Không dựng lại prompt gốc: đính kèm ĐÚNG ảnh đang lỗi và nhờ ChatGPT vẽ lại y chang, chỉ sửa lỗi nhân vật (tay, chân,
mặt, ngón...). Chỉ dùng tài khoản Plus, mức thinking cao. Trang lịch vẽ lại xong vẫn qua OCR soát ngày.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import layout, pipeline
from ..imagegen import driver
from ..imagegen.driver import TempError
from ..imagegen.plan import job_done
from ..imagegen.prompts import CHARACTER_ACCURACY
from . import run, session

GRID_REDO_TRIES = 3

FIX_PROMPT = """The attached image is a finished calendar artwork. It is the ONLY reference.
Recreate it as ONE new image that is IDENTICAL to the attached image: the same subjects, poses, composition, camera angle, background, colors, lighting, drawing / photo style, and the same text (word for word, same spelling, same placement), if any.

Fix ONLY these problems, wherever they appear:
{rules}
- No warped, melted or blurry faces; eyes, nose and mouth are clear and natural for the style.
- Objects that characters hold or touch connect to them naturally.

Change nothing else. Keep the same landscape aspect ratio, full bleed, no border, no frame, no watermark.
Output ONLY 1 image. No text reply."""

GRID_RULES = """
This image is a calendar grid page: keep the title, weekday headers, every date number, every holiday note and the whole layout EXACTLY as they are, in the same cells. Do not add, remove or move any date."""


# Tranh tháng / bìa (người dùng chốt 08/10/2026): (1) ChatGPT nhìn ảnh, tả lại thành một prompt chữ; (2) CHAT MỚI không
# đính ảnh, vẽ lại từ đúng bản chữ đó. Vẽ từ chữ thì ChatGPT dựng lại cả cơ thể nhân vật - không chép lỗi tay chân cũ.
DESCRIBE_PROMPT = """Look at the attached image carefully. Do NOT generate any image. Reply with text only.

Write ONE detailed image-generation prompt (in English, 150-250 words) that would let an artist recreate this artwork from scratch WITHOUT seeing it. Describe, in this order:
1. Main subject(s): who or what, appearance, age, hair, clothing, colors, expression, pose and what they are doing.
2. Secondary elements and props, and where they sit in the frame.
3. Composition and camera: shot type (close-up / medium / wide), camera angle, where the subject is placed (left / center / right), foreground / background depth.
4. Background and setting: place, season, time of day, weather.
5. Color palette: the main colors with simple names (e.g. "warm cream, dusty rose, sage green"), overall brightness and warmth.
6. Lighting: direction, softness, mood.
7. Art style: medium and technique (e.g. watercolor, gouache, vintage photo, flat vector), stroke quality, texture, level of detail.
8. Text in the artwork (if any): copy it EXACTLY, word for word, with its line breaks, and describe its font style, color and position. If there is no text, write "No text".

Rules for the prompt you write:
- Describe every person and animal with correct anatomy (two hands with five fingers each, natural joints, clear faces), even if the attached image has mistakes; do not mention the mistakes.
- Do not mention calendars, dates, borders, frames, watermarks or that this is a copy of an image.
- End the prompt with: "Landscape 4:3, full bleed, no border, no frame, no watermark."

Return ONLY the prompt inside a ```text code block."""

DRAW_PREFIX = "Generate a new image from this text description now, without asking any questions.\n\n"


def description_from(answer: str) -> str:
    """Lấy prompt trong khối ```text (không có khối thì lấy cả câu trả lời)."""
    import re
    m = re.search(r"```[A-Za-z]*\s*\n(.*?)```", answer or "", re.S)   # khối code (giao diện có khi gắn nhãn json)
    text = (m.group(1) if m else (answer or "")).strip()
    return text


def fix_prompt(page: str) -> str:
    """Trang lịch: giữ y bố cục + mọi ngày, chỉ sửa lỗi nhân vật (tranh tháng / bìa đi đường tìm lỗi -> sửa)."""
    rules = CHARACTER_ACCURACY.split("\n", 1)[1]           # trang lịch: giữ y bố cục + mọi ngày, chỉ sửa lỗi nhân vật
    return FIX_PROMPT.format(rules=rules) + GRID_RULES


def is_clone(concept_dir: Path) -> bool:
    try:
        return json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8")).get("source") == "clone"
    except (OSError, ValueError):
        return False


def redo(concept_dir: Path, pages: list[str], cfg: dict, on_event=print, accts: run.Accounts | None = None,
         plus: list[str] | None = None) -> dict:
    """Vẽ lại các trang `pages` (vd ["m05", "g05", "cover"]) rồi làm lại trang in, PDF, ảnh quảng cáo."""
    concept_dir = Path(concept_dir)
    year = int(json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8")).get("year") or 2027)
    sources = {}
    for p in pages:                                         # ảnh đang lỗi = ảnh sẽ đính kèm
        src = job_done(concept_dir, p)
        if src is None:
            raise ValueError(f"trang {p} chưa có ảnh để vẽ lại")
        keep = layout.tech(concept_dir, "anh_sua") / f"{p}{src.suffix}"
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, keep)
        sources[p] = keep
    pipeline.redo_pages(concept_dir, pages, on_event)        # cất ảnh cũ vào ky_thuat/anh_cu, đánh dấu chưa xuất CSV
    plus = plus if plus is not None else run.plus_accounts(cfg, on_event=on_event)
    if not plus:
        _restore(concept_dir, sources)
        raise ValueError("không có tài khoản ChatGPT Plus còn hạn để vẽ lại")
    accts = accts or run.Accounts(cfg, plus, on_event)

    def work(s, name: str) -> None:
        from ..imagegen.generate import accept_grid_page
        first = True
        for p, src in sources.items():
            if job_done(concept_dir, p) is not None:
                continue
            if not first:                                   # mỗi trang một chat riêng ("ảnh đính kèm" không lẫn)
                driver.open_home(s.page, driver.URL)
                s.w._find(s.page, driver.SEL_PROMPT, 60_000)
                session.ensure_chat_mode(s.page)
            first = False
            if not p.startswith("g"):
                describe_and_redraw(s, name, p, src)
                continue
            for attempt in range(GRID_REDO_TRIES if p.startswith("g") else 1):
                turn = s.ask_images(fix_prompt(p), 1, attach=[src])
                if not turn.images:
                    raise turn.problem or TempError(f"{p}: ChatGPT không trả ảnh")
                data = turn.images[0]
                why = session.landscape_ok(data)
                if why is None and p.startswith("g"):
                    tmp = layout.tech(concept_dir) / f"redo_check_{p}{session.ext_of(data)}"
                    tmp.write_bytes(data)
                    why = accept_grid_page(tmp, year, int(p[1:]))
                    tmp.unlink(missing_ok=True)
                if why is None:
                    session.save(data, layout.raw(concept_dir) / p)
                    on_event(f"[{name}] {p}: đã vẽ lại")
                    break
                on_event(f"[{name}] {p}: ảnh vẽ lại chưa đạt ({why[:100]})")
            else:
                raise TempError(f"{p}: vẽ lại chưa đạt")

    def describe_and_redraw(s, name: str, p: str, src: Path) -> None:
        """Tranh tháng / bìa: (1) đính ảnh lỗi, hỏi chữ - ChatGPT tả lại thành prompt vẽ; (2) chat mới, không đính ảnh,
        vẽ lại từ đúng bản chữ đó."""
        (s.attach([src]) if hasattr(s, "attach") else s.w._attach(s.page, [src]))
        desc = description_from(s.ask_text(DESCRIBE_PROMPT))
        if len(desc) < 80:
            raise TempError(f"{p}: ChatGPT chưa tả được ảnh")
        (layout.tech(concept_dir) / f"mo_ta_{p}.txt").write_text(desc, encoding="utf-8")
        on_event(f"[{name}] {p}: đã tả ảnh ({len(desc.split())} từ) - vẽ lại từ bản mô tả trong chat mới")
        driver.open_home(s.page, driver.URL)                 # chat mới: không còn ảnh cũ để ChatGPT bám vào
        s.w._find(s.page, driver.SEL_PROMPT, 60_000)
        session.ensure_chat_mode(s.page)
        turn = s.ask_images(DRAW_PREFIX + desc, 1)
        if not turn.images:
            raise turn.problem or TempError(f"{p}: ChatGPT không trả ảnh vẽ lại")
        why = session.landscape_ok(turn.images[0])
        if why:
            raise TempError(f"{p}: ảnh vẽ lại chưa đạt ({why})")
        session.save(turn.images[0], layout.raw(concept_dir) / p)
        on_event(f"[{name}] {p}: đã vẽ lại")

    try:
        run.run_stage(accts, f"vẽ lại {', '.join(pages)}", work)
    except (run.StageFailed, run.BookRejected) as e:
        _restore(concept_dir, {p: s for p, s in sources.items() if job_done(concept_dir, p) is None})
        return pipeline._status(concept_dir, stage="images", ok=False, reason=f"chưa vẽ lại được: {e}"[:300])
    pipeline._status(concept_dir, stage="images", ok=True)
    pipeline.upscale_concept(concept_dir, on_event)
    return pipeline.finish_book(concept_dir, cfg, printify=False, on_event=on_event)   # mockup AI: mọi tài khoản


def _restore(concept_dir: Path, sources: dict) -> None:
    """Vẽ lại không được: đặt lại ảnh cũ để cuốn vẫn đủ trang như trước."""
    for p, src in sources.items():
        if job_done(concept_dir, p) is None:
            shutil.copy2(src, layout.raw(concept_dir) / f"{p}{src.suffix}")
