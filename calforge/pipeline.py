"""Dây chuyền trọn gói: keyword -> concept -> ảnh -> upscale -> 26 trang + PDF -> listing -> Printify (nháp).

Mọi bước đều dựa trên file đã có: chạy lại sau khi đứt (hết lượt ChatGPT, mất mạng, tắt máy) thì
đi tiếp đúng chỗ dừng. Bước nào thiếu điều kiện (vd còn ảnh chưa gen được) thì dừng concept đó và
ghi rõ lý do vào status.json, không render một cuốn thiếu trang.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .ideation.pipeline import run_ideation
from .imagegen import plan
from .imagegen.generate import generate_concept
from .imagegen.upscale import engine as upscale_engine
from .imagegen.upscale import upscale_to
from .publish.listing import write_listing
from .render.build import load_format, render_concept

UPSCALE_JOBS = ["anchor"] + [f"m{m:02d}" for m in range(1, 13)]


def upscale_concept(concept_dir: Path, on_event=print) -> list[str]:
    fmt = load_format()
    W, H = fmt["size_px"]
    final = concept_dir / "art" / "final"
    final.mkdir(parents=True, exist_ok=True)
    done = []
    for jid in UPSCALE_JOBS:
        src = plan.job_done(concept_dir, jid)
        dst = final / f"{jid}.png"
        if src is None or dst.exists():
            continue
        info = upscale_to(src, dst, W, H)
        on_event(f"upscale {jid}: x{info['scale']} ({info['engine']})")
        done.append(jid)
    return done


def _status(concept_dir: Path, **kw) -> dict:
    f = concept_dir / "status.json"
    st = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if kw.get("ok"):  # bước đã qua: xoá lỗi của lần chạy trước để status không báo sai
        for stale in ("reason", "failed", "issues"):
            if stale not in kw:
                st.pop(stale, None)
    st.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    f.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return st


def produce(concept_dir: Path, cfg: dict, *, printify: bool = True, publish: bool = False, on_event=print) -> dict:
    """Từ concept.json đến sản phẩm. Trả về status."""
    ig = cfg["imagegen"]
    on_event(f"== {concept_dir.name}")
    plan.write_plan(concept_dir)
    profiles_dir = Path(ig.get("profiles_dir") or Path(cfg["chatgpt_automation_dir"]) / ".chrome-profiles")
    res = generate_concept(concept_dir, profiles_dir, ig.get("profiles"), headless=ig.get("headless", False),
                           timeout_s=ig.get("timeout_s", 420), max_attempts=ig.get("max_attempts", 3),
                           on_event=on_event)
    if res["missing"]:
        return _status(concept_dir, stage="images", ok=False,
                       reason=f"còn thiếu ảnh: {', '.join(res['missing'])} - chạy lại khi tài khoản có lượt",
                       failed=res["failed"])
    _status(concept_dir, stage="images", ok=True, drift_flags=res["drift_flags"])

    on_event(f"Upscale bằng {upscale_engine()}")
    upscale_concept(concept_dir, on_event)
    r = render_concept(concept_dir)
    if r["issues"] or not r["complete"]:
        return _status(concept_dir, stage="render", ok=False, reason="preflight chưa sạch", issues=r["issues"])
    _status(concept_dir, stage="render", ok=True, pages=len(r["pages"]), digital=r["digital"])

    write_listing(concept_dir)
    if not printify:
        return _status(concept_dir, stage="listing", ok=True, note="bỏ qua Printify theo yêu cầu")
    from .publish.printify import PrintifyError, create_product, token_from

    if not token_from(cfg):
        return _status(concept_dir, stage="listing", ok=True,
                       note="chưa có Printify token - sản phẩm sẵn sàng upload (render/printify/)")
    try:
        state = create_product(concept_dir, cfg, publish=publish, on_event=on_event)
    except PrintifyError as e:
        return _status(concept_dir, stage="printify", ok=False, reason=str(e))
    return _status(concept_dir, stage="printify", ok=True, product_id=state.get("product_id"),
                   published=state.get("published", False))


def run(keyword: str, cfg: dict, *, pick: list[str] | None = None, auto_pick: int | None = None,
        printify: bool = True, publish: bool = False, on_event=print) -> list[dict]:
    backend = config.make_backend(cfg)
    res = run_ideation(keyword, backend, Path(cfg["projects_dir"]), year=cfg["year"], market=cfg["market"],
                       n_angles=cfg["angles_per_keyword"], pick=pick, auto_pick=auto_pick or cfg["auto_pick"],
                       max_repairs=cfg["max_repairs"])
    out = []
    for cdir in res.concepts:
        st = produce(cdir, cfg, printify=printify, publish=publish, on_event=on_event)
        out.append({"concept": str(cdir), **st})
    for aid in res.failed:
        out.append({"concept": aid, "stage": "ideation", "ok": False, "reason": "concept không qua kiểm tra"})
    return out
