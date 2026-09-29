"""Dây chuyền trọn gói: keyword -> concept -> ảnh -> upscale -> 26 trang + PDF -> listing -> Printify (nháp).

Mọi bước đều dựa trên file đã có: chạy lại sau khi đứt (hết lượt ChatGPT, mất mạng, tắt máy) thì
đi tiếp đúng chỗ dừng. Bước nào thiếu điều kiện (vd còn ảnh chưa gen được) thì dừng concept đó và
ghi rõ lý do vào status.json, không render một cuốn thiếu trang.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from . import config, layout
from .imagegen import plan
from .imagegen.generate import generate_concept
from .imagegen.upscale import engine as upscale_engine
from .imagegen.upscale import upscale_to
from .publish.listing import write_listing
from . import products
from .render.build import FORMATS, art_source, expected_pages, load_format, render_concept

# Chỉ upscale ảnh xuất hiện như artwork toàn trang. Anchor chỉ dùng làm reference; nền grid
# ít chi tiết được renderer nội suy một lần rồi phủ text/vector chính xác lên trên.
UPSCALE_JOBS = ["cover"] + [f"m{m:02d}" for m in range(1, 13)]
RENDER_ART_JOBS = ["cover"] + [f"m{m:02d}" for m in range(1, 13)] + ["grid"]


def upscale_concept(concept_dir: Path, on_event=print, *, settle_s: float = 0.0) -> list[str]:
    """Upscale mọi artwork đã có mà bản final còn cũ. settle_s > 0: bỏ qua ảnh vừa ghi chưa đủ lâu
    (đang chạy song song với bước gen, file có thể chưa ghi xong) - lượt sau sẽ làm."""
    # đủ lớn cho khổ in LỚN NHẤT (11x8.5 và 14x11.5 dùng chung một bộ ảnh final)
    W, H = (max(load_format(f)["size_px"][i] for f in FORMATS) for i in (0, 1))
    final = layout.final(concept_dir)
    final.mkdir(parents=True, exist_ok=True)
    done = []
    for jid in UPSCALE_JOBS:
        src = plan.job_done(concept_dir, jid)
        dst = final / f"{jid}.jpg"
        if src is None:
            continue
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            try:
                with Image.open(dst) as im:
                    big_enough = im.width / W >= 0.99 or im.height / H >= 0.99
            except OSError:
                big_enough = True                     # không đọc được cỡ: giữ như cũ, không upscale lại
            if big_enough:                            # ảnh cũ chỉ đủ cho khổ nhỏ thì upscale lại cho khổ lớn
                continue
        if settle_s and time.time() - src.stat().st_mtime < settle_s:
            continue
        info = upscale_to(src, dst, W, H)
        on_event(f"upscale {jid}: x{info['scale']} ({info['engine']})")
        done.append(jid)
    return done


class _BackgroundUpscaler:
    """Upscale từng artwork ngay khi nó gen xong, chạy song song lúc chờ ChatGPT gen các ảnh khác
    (GPU vốn ngồi không trong lúc đó). Kết quả y hệt chạy tuần tự: cùng hàm, cùng tham số; ảnh nào
    bị gen lại sau khi đã upscale thì bước upscale chính sau đó sẽ làm lại theo mtime."""

    def __init__(self, concept_dir: Path, on_event=print, poll_s: float = 5.0):
        import threading

        self.concept_dir, self.on_event, self.poll_s = concept_dir, on_event, poll_s
        self.done: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="upscale", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.done += upscale_concept(self.concept_dir, self.on_event, settle_s=3.0)
            except Exception as e:  # noqa: BLE001 - lỗi ở đây không được làm hỏng bước gen; bước chính làm lại
                self.on_event(f"  ⚠ upscale song song lỗi, sẽ làm lại sau: {e}")
            self._stop.wait(self.poll_s)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def _render_is_current(concept_dir: Path, format_id: str) -> bool:
    """True khi đủ trang/PDF (của khổ format_id) còn mới hơn concept và mọi ảnh thực sự dùng để render."""
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    pngs = list(layout.print_dir(concept_dir, format_id).glob("*.png"))
    val_file = layout.render_file(concept_dir, "validation.json", format_id)
    required = [val_file, layout.printable_file(concept_dir, format_id)]
    if len(pngs) != expected_pages(concept, format_id) or any(not p.is_file() for p in required):
        return False
    try:
        validation = json.loads(val_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not validation.get("complete") or validation.get("issues"):
        return False
    inputs = [layout.concept_file(concept_dir)]
    for jid in RENDER_ART_JOBS:
        if jid == "grid" and not products.ai_grid(concept):
            continue
        src, _kind = art_source(concept_dir, jid)
        if src is None:
            return False
        inputs.append(src)
    newest_input = max(p.stat().st_mtime for p in inputs)
    oldest_output = min(p.stat().st_mtime for p in [*pngs, *required])
    return oldest_output >= newest_input


def _listing_is_current(concept_dir: Path) -> bool:
    listing = layout.listing_file(concept_dir)
    concept = layout.concept_file(concept_dir)
    return listing.is_file() and listing.stat().st_mtime >= concept.stat().st_mtime


def _status(concept_dir: Path, **kw) -> dict:
    f = layout.status_file(concept_dir)
    st = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    if kw.get("ok"):  # bước đã qua: xoá lỗi của lần chạy trước để status không báo sai
        for stale in ("reason", "failed", "issues"):
            if stale not in kw:
                st.pop(stale, None)
    st.update(kw, updated=time.strftime("%Y-%m-%d %H:%M:%S"))
    f.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return st


REDO_PAGES = ["cover"] + [f"m{m:02d}" for m in range(1, 13)] + ["grid"]


def redo_pages(concept_dir: Path, pages: list[str], on_event=print) -> list[str]:
    """Chuẩn bị vẽ lại các trang hỏng: cất ảnh AI cũ (+ bản upscale) vào _he_thong/ky_thuat/anh_cu/ để lượt sản xuất
    sau gen lại đúng các trang đó; mọi bước sau (upscale, render, mockup) tự làm lại vì ảnh mới hơn. Cuốn đã xuất CSV
    được đánh dấu chưa xuất để lần Đẩy R2 + xuất CSV sau có bản mới. Trả về các trang đã cất."""
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    allowed = [p for p in REDO_PAGES if p != "grid" or products.ai_grid(concept)]
    bad = [p for p in pages if p not in allowed]
    if bad:
        raise ValueError(f"trang không vẽ lại được: {', '.join(bad)} (được: {', '.join(allowed)})")
    old = layout.tech(concept_dir, "anh_cu")
    old.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    moved = []
    for jid in pages:
        for f in list(layout.raw(concept_dir).glob(f"{jid}.*")) + list(layout.final(concept_dir).glob(f"{jid}.*")):
            f.replace(old / f"{f.stem}-{f.parent.name}-{stamp}{f.suffix}")
            if jid not in moved:
                moved.append(jid)
    from .publish import r2
    st = r2.read_state(concept_dir)
    if st.get("exported_at"):
        st.pop("exported_at", None)
        st.pop("exported_csv", None)
        r2.write_state(concept_dir, st)
    _status(concept_dir, stage="images", ok=False, reason=f"đang vẽ lại: {', '.join(pages)}")
    on_event(f"↻ Vẽ lại {len(pages)} trang: {', '.join(pages)} (ảnh cũ cất ở ky_thuat/anh_cu)")
    return moved


def needs_finishing(concept_dir: Path) -> bool:
    """Đã vẽ đủ tranh nhưng chưa xong phần máy tự làm (trang in / PDF / mockup / listing) - thường do bị dừng
    giữa chừng. Phần còn lại không cần ChatGPT."""
    try:
        concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
        st = json.loads(layout.status_file(concept_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if st.get("ok") and st.get("stage") in ("listing", "printify"):
        return False
    jobs = [j for j in RENDER_ART_JOBS if j != "grid" or products.ai_grid(concept)]
    return all(plan.job_done(concept_dir, j) is not None for j in jobs)


def produce(concept_dir: Path, cfg: dict, *, printify: bool = True, publish: bool = False, on_event=print) -> dict:
    """Từ concept.json đến sản phẩm. Trả về status."""
    failed = produce_images(concept_dir, cfg, on_event=on_event)
    if failed is not None:
        return failed
    return finish_book(concept_dir, cfg, printify=printify, publish=publish, on_event=on_event)


def produce_images(concept_dir: Path, cfg: dict, *, on_event=print) -> dict | None:
    """Phần cần ChatGPT: gen ảnh (+ upscale chạy kèm). None = đủ ảnh; dict = status lỗi."""
    ig = cfg["imagegen"]
    on_event(f"===== Sản xuất: {concept_dir.name} =====")
    plan.write_plan(concept_dir)
    profiles_dir = config.get_profiles_dir(cfg)
    on_event("▶ Bước 2/6: Sinh ảnh (ảnh neo → bìa + 12 artwork → 1 nền grid dùng chung)")
    from .imagegen.generate import QUOTA_MARK
    waited = 0.0
    while True:
        with _BackgroundUpscaler(concept_dir, on_event) as early:
            try:
                res = generate_concept(concept_dir, profiles_dir, ig.get("profiles"),
                                       headless=ig.get("headless", False), timeout_s=ig.get("timeout_s", 420),
                                       max_attempts=ig.get("max_attempts", 3), on_event=on_event)
            except RuntimeError as e:          # ảnh neo không gen được
                if QUOTA_MARK not in str(e):
                    raise
                res = {"missing": ["anchor"], "failed": {"anchor": str(e)}, "drift_flags": []}
        quota = res["missing"] and any(QUOTA_MARK in str(v) for v in res["failed"].values())
        if not quota or not _wait_for_quota(cfg, waited, on_event, "gen ảnh"):
            break
        waited += cfg.get("quota_wait_s", 1800)
    if early.done:
        on_event(f"  ✔ Đã upscale sẵn {len(early.done)} artwork trong lúc chờ gen ảnh")
    if res["missing"]:
        return _status(concept_dir, stage="images", ok=False,
                       reason=f"còn thiếu ảnh: {', '.join(res['missing'])} - chạy lại khi tài khoản có lượt",
                       failed=res["failed"])
    _status(concept_dir, stage="images", ok=True, drift_flags=res["drift_flags"])

    on_event(f"▶ Bước 3/6: Upscale {len(UPSCALE_JOBS)} artwork in bằng {upscale_engine()} (bỏ anchor + grid)")
    upscaled = upscale_concept(concept_dir, on_event)
    if not upscaled:
        on_event("  ↷ Upscale đã xong hết (làm song song lúc gen ảnh)" if early.done else "  ↷ Upscale đã mới, bỏ qua")
    return None


def finish_book(concept_dir: Path, cfg: dict, *, printify: bool = True, publish: bool = False,
                on_event=print) -> dict:
    """Phần máy tự làm, không cần ChatGPT: render 2 khổ + PDF, ảnh preview, listing, Printify.
    Batch chạy phần này ở luồng nền trong lúc cuốn sau đang gen ảnh."""
    concept = json.loads(layout.concept_file(concept_dir).read_text(encoding="utf-8"))
    product = products.get(concept)
    digital = []
    for i, fid in enumerate(product["formats"]):
        label = layout.SIZE_LABEL[fid]
        n = expected_pages(concept, fid)
        step = "▶ Bước 4/6" if i == 0 else f"▶ Bước 4 ({label})"
        if _render_is_current(concept_dir, fid):
            on_event(f"{step}: {n} trang + PDF khổ {label} đã mới, bỏ qua render")
        else:
            on_event(f"{step}: Render {n} trang Printify + PDF in tại nhà khổ {label}")
            r = render_concept(concept_dir, proofs=False, previews=False, format_id=fid)
            if r["issues"] or not r["complete"]:
                return _status(concept_dir, stage="render", ok=False, reason=f"preflight khổ {label} chưa sạch",
                               issues=r["issues"])
            on_event(f"  ✔ Render xong {len(r['pages'])} trang khổ {label}, preflight sạch")
        digital.append(str(layout.printable_file(concept_dir, fid)))
    _status(concept_dir, stage="render", ok=True, pages=expected_pages(concept, product["formats"][0]),
            digital=digital)

    # 5 ảnh preview (mockup) cho listing. Lỗi ở đây không chặn sản phẩm: trang in đã xong.
    on_event("▶ Bước 4b: Ghép 5 ảnh preview mockup cho listing")
    preview_error = ""
    if not product["mockups"]:
        on_event("  ↷ Loại lịch này chưa có ảnh mockup - bỏ qua")
    else:
        from .render.mockups import PreviewError, missing_previews, previews
        try:
            made = previews(concept_dir, on_event)
            on_event(f"  ✔ {len(made)} ảnh preview mới" if made else "  ↷ Ảnh preview đã mới, bỏ qua")
        except PreviewError as e:
            preview_error = "; ".join(e.errors)
        except Exception as e:  # noqa: BLE001
            preview_error = str(e)
        lacking = missing_previews(concept_dir)
        if lacking and not preview_error:
            preview_error = f"thiếu {', '.join(lacking)}"

    if _listing_is_current(concept_dir):
        on_event("▶ Bước 5/6: Listing đã mới, bỏ qua")
    else:
        on_event("▶ Bước 5/6: Tạo listing (title, tags, mô tả)")
        write_listing(concept_dir)
    if preview_error:     # trang in + listing xong nhưng thiếu ảnh quảng cáo: chưa đủ để đăng bán
        on_event(f"  ✘ Thiếu ảnh quảng cáo: {preview_error}")
        return _status(concept_dir, stage="mockup", ok=False, reason=f"thiếu ảnh quảng cáo: {preview_error}")
    if not printify:
        return _status(concept_dir, stage="listing", ok=True, note="bỏ qua Printify theo yêu cầu")
    if not product["printify"]:
        return _status(concept_dir, stage="listing", ok=True, printify_skipped=True,
                       note="loại lịch grid in sẵn chưa cấu hình Printify - trang in sẵn sàng trong 11x8.5 và 14x11.5")
    from .publish.printify import PrintifyError, create_product, token_from

    if not token_from(cfg):
        return _status(concept_dir, stage="listing", ok=True, printify_skipped=True,
                       note="chưa có Printify token - trang in sẵn sàng upload trong thư mục 11x8.5 và 14x11.5")
    on_event("▶ Bước 6/6: Upload + tạo sản phẩm nháp trên Printify")
    try:
        state = create_product(concept_dir, cfg, publish=publish, on_event=on_event)
    except PrintifyError as e:
        return _status(concept_dir, stage="printify", ok=False, reason=str(e))
    return _status(concept_dir, stage="printify", ok=True, product_id=state.get("product_id"),
                   published=state.get("published", False))


# ---------------------------------------------------------------------------
# Batch: cô lập lỗi từng cuốn, vòng vét cuối, báo cáo tổng, chạy lại chỉ làm phần còn thiếu
# ---------------------------------------------------------------------------
RETRY_STAGES = {"images", "crash"}   # thiếu ảnh (hết lượt) hoặc lỗi bất ngờ: đáng thử lại một lần


def _wait_for_quota(cfg: dict, waited: float, on_event, what: str) -> bool:
    """Cả 5 tài khoản hết lượt: TẠM DỪNG (không làm hỏng cuốn) rồi thử lại. False = đã chờ quá lâu, thôi."""
    wait = cfg.get("quota_wait_s", 1800)
    if waited + wait > cfg.get("quota_max_wait_h", 24) * 3600:
        on_event(f"  ✘ Đã chờ {waited / 3600:.1f} giờ mà tài khoản vẫn hết lượt {what} - dừng chờ")
        return False
    resume = time.strftime("%H:%M", time.localtime(time.time() + wait))
    on_event(f"⏸ Tất cả tài khoản hết lượt {what} - tạm dừng, thử lại lúc {resume} "
             f"(đã chờ {waited / 60:.0f} phút)")
    time.sleep(wait)
    on_event(f"▶ Hết giờ chờ - thử lại {what}")
    return True


class _Finisher:
    """Hậu kỳ (render/preview/listing/Printify) của cuốn trước chạy ở 1 luồng nền, song song với việc gen ảnh
    cuốn sau - tài khoản ChatGPT không phải ngồi chờ render. Lỗi vẫn chỉ hỏng cuốn đó (ghi status.json)."""

    def __init__(self, cfg: dict, on_event, **kw):
        from concurrent.futures import ThreadPoolExecutor
        self.cfg, self.on_event, self.kw = cfg, on_event, kw
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hau_ky")
        self.jobs = []

    def submit(self, cdir: Path) -> None:
        # log hậu kỳ có nhãn cuốn và không mang dấu "▶ Bước" để UI không nhầm tiến độ của cuốn đang gen ảnh
        log = lambda m, n=cdir.name: self.on_event(f"  [hậu kỳ · {n}] " + str(m).replace("▶ ", "").strip())
        self.jobs.append(self.pool.submit(_safe_call, finish_book, cdir, self.cfg, log, **self.kw))

    def wait(self) -> None:
        for j in self.jobs:
            j.result()
        self.jobs = []

    def close(self) -> None:
        self.wait()
        self.pool.shutdown()


def _safe_call(fn, cdir: Path, cfg: dict, on_event=print, **kw) -> dict:
    import traceback
    try:
        return fn(cdir, cfg, on_event=on_event, **kw)
    except Exception as e:  # noqa: BLE001 - một cuốn hỏng không được giết cả batch
        on_event(f"  ✘ {cdir.name}: lỗi bất ngờ - {type(e).__name__}: {e}")
        return _status(cdir, stage="crash", ok=False, reason=f"{type(e).__name__}: {e}"[:500],
                       traceback=traceback.format_exc()[-4000:])


def _safe_pipelined(cdir: Path, cfg: dict, finisher: "_Finisher", on_event=print) -> None:
    """Gen ảnh ở luồng chính (cần Chrome); đủ ảnh thì đẩy hậu kỳ sang luồng nền."""
    res = _safe_call(lambda c, g, on_event: produce_images(c, g, on_event=on_event) or {"ok": True, "_next": True},
                     cdir, cfg, on_event)
    if res.get("_next"):
        finisher.submit(cdir)


def _safe_produce(cdir: Path, cfg: dict, on_event=print, **kw) -> dict:
    """produce() nhưng lỗi gì cũng chỉ hỏng cuốn đó: ghi lý do + traceback vào status.json rồi đi tiếp.
    Trình duyệt được đóng bởi các khối with bên trong khi exception đi ra."""
    import traceback
    try:
        return produce(cdir, cfg, on_event=on_event, **kw)
    except Exception as e:  # noqa: BLE001 - cố ý: một cuốn hỏng không được giết cả batch
        on_event(f"  ✘ {cdir.name}: lỗi bất ngờ - {type(e).__name__}: {e}")
        return _status(cdir, stage="crash", ok=False, reason=f"{type(e).__name__}: {e}"[:500],
                       traceback=traceback.format_exc()[-4000:])


def _batch_file(kdir: Path) -> Path:
    return layout.batch_file(kdir)


def _load_batch(kdir: Path) -> dict | None:
    try:
        return json.loads(_batch_file(kdir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_batch(kdir: Path, batch: dict) -> None:
    layout.ensure_system(kdir)
    _batch_file(kdir).write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_status(cdir: Path) -> dict:
    try:
        return json.loads(layout.status_file(cdir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _finished_ok(cdir: Path) -> bool:
    st = _read_status(cdir)
    return bool(st.get("ok")) and st.get("stage") in ("listing", "printify")


def batch_report(kdir: Path, batch: dict) -> list[dict]:
    """Bảng tổng: mỗi cuốn xong chưa, dừng ở bước nào, vì sao. Ghi "Báo cáo batch.md" cạnh các cuốn."""
    rows = []
    for rel in batch.get("concepts", []):
        cdir = kdir / rel
        st = _read_status(cdir)
        title = rel
        try:
            title = json.loads(layout.concept_file(cdir).read_text(encoding="utf-8")).get("title") or rel
        except (OSError, json.JSONDecodeError):
            pass
        rows.append({"concept": rel, "title": title, "ok": _finished_ok(cdir), "stage": st.get("stage", "chưa chạy"),
                     "reason": st.get("reason") or st.get("note") or "", "updated": st.get("updated", "")})
    for aid in batch.get("failed_ideas", []):
        rows.append({"concept": aid, "title": aid, "ok": False, "stage": "ideation",
                     "reason": "concept không qua kiểm tra sau các vòng sửa", "updated": ""})
    for err in batch.get("errors", []):
        rows.append({"concept": "", "title": "(lên ý tưởng)", "ok": False, "stage": "ideation", "reason": err,
                     "updated": ""})
    done = sum(r["ok"] for r in rows)
    md = [f"# Báo cáo batch {kdir.name}", "",
          f"Mục tiêu {batch.get('target')} cuốn · xong {done} · lỗi {len(rows) - done} · "
          f"bắt đầu {batch.get('started', '')} · kết thúc {batch.get('finished', '') or 'đang chạy'}", "",
          "| Cuốn | Kết quả | Bước | Lý do |", "|---|---|---|---|"]
    for r in rows:
        reason = str(r["reason"]).replace("|", "/").replace("\n", " ")[:200]
        md.append(f"| {r['title']} | {'✔ xong' if r['ok'] else '✘ lỗi'} | {r['stage']} | {reason} |")
    layout.batch_report_file(kdir).write_text("\n".join(md) + "\n", encoding="utf-8")
    batch["report"] = rows
    _save_batch(kdir, batch)
    return rows


def run(keyword: str, cfg: dict, *, pick: list[str] | None = None, auto_pick: int | None = None,
        printify: bool = True, publish: bool = False, grid_preset: str | None = None,
        family: str | None = None, on_event=print, retry_wait_s: float | None = None,
        product: str | None = None) -> list[dict]:
    """Chạy trọn gói một batch N cuốn theo lượt tối đa ROUND_SIZE cuốn.

    - Lỗi của một cuốn chỉ hỏng cuốn đó (status.json có lý do + traceback), batch đi tiếp.
    - Cuối batch: chờ retry_wait_s rồi làm lại MỘT lần các cuốn dừng vì thiếu ảnh / lỗi bất ngờ.
    - projects/<keyword>/_he_thong/batch.json nhớ batch đang chạy: chạy lại khi batch chưa xong thì chỉ làm nốt
      các cuốn dở và lên ý đủ số còn thiếu, không mở batch mới.
    - Báo cáo tổng: projects/<keyword>/Báo cáo batch.md (+ mục "report" trong batch.json cho UI)."""
    from .ideation.pipeline import ROUND_SIZE, run_ideation, slugify

    backend = config.make_backend(cfg)
    from . import products as _p
    prod_root = _p.root(cfg["projects_dir"], product if product in _p.PRODUCTS else _p.DEFAULT)
    kdir = prod_root / slugify(keyword)
    kdir.mkdir(parents=True, exist_ok=True)
    wait = cfg.get("batch_retry_wait_s", 300) if retry_wait_s is None else retry_wait_s
    common = dict(year=cfg["year"], market=cfg["market"], n_angles=cfg["angles_per_keyword"],
                  max_repairs=cfg["max_repairs"], grid_preset=grid_preset, family=family, product=product)
    kw = dict(printify=printify, publish=publish)

    from . import products as _products
    product = product if product in _products.PRODUCTS else _products.DEFAULT
    batch = None if pick else _load_batch(kdir)
    if batch and batch.get("product", _products.DEFAULT) != product:
        batch = None            # batch dở của loại lịch khác: không làm tiếp nhầm loại, mở batch mới
    if batch and not batch.get("finished"):
        on_event(f"▶ Tiếp tục batch dở: {len(batch['concepts'])}/{batch['target']} cuốn đã có ý tưởng")
    else:
        batch = {"target": len(pick) if pick else (auto_pick or cfg["auto_pick"]), "product": product, "concepts": [],
                 "failed_ideas": [], "errors": [], "started": time.strftime("%Y-%m-%d %H:%M:%S"), "finished": ""}
    _save_batch(kdir, batch)

    finisher = _Finisher(cfg, on_event, **kw)          # hậu kỳ cuốn trước chạy nền lúc cuốn sau gen ảnh
    try:
        rows = _run_batch(keyword, cfg, kdir, batch, backend, common, finisher, pick, wait, on_event)
    finally:
        finisher.close()
    return rows


def _run_batch(keyword, cfg, kdir, batch, backend, common, finisher, pick, wait, on_event):
    from .ideation.pipeline import ROUND_SIZE, run_ideation
    from .llm.chatgpt_web import NoAccountLeft

    # 1) Cuốn đã có ý tưởng từ lần chạy trước nhưng chưa xong: làm nốt trước.
    for rel in list(batch["concepts"]):
        if layout.is_book(kdir / rel) and not _finished_ok(kdir / rel):
            _safe_pipelined(kdir / rel, cfg, finisher, on_event)

    # 2) Lên ý + sản xuất theo lượt cho đủ số còn thiếu.
    on_event("▶ Bước 1/6: Lên ý tưởng (P1 góc tiếp cận → P2 concept). Chờ ChatGPT vài phút...")
    empty_rounds = 0
    idea_waited = 0.0
    while True:
        left = batch["target"] - len(batch["concepts"]) - len(batch["failed_ideas"])
        if left <= 0 or empty_rounds >= 2:
            break
        n = min(ROUND_SIZE, left)
        on_event(f"▶ Lượt lên ý: {n} cuốn (còn thiếu {left}/{batch['target']})")
        try:
            res = run_ideation(keyword, backend, Path(cfg["projects_dir"]), pick=pick, auto_pick=n,
                               keyword_root=kdir.parent, **common)
        except NoAccountLeft:
            # hết lượt chat ở mọi tài khoản: chờ rồi làm lại đúng lượt này (sổ hỏi/đáp giữ phần đã có)
            if _wait_for_quota(cfg, idea_waited, on_event, "chat"):
                idea_waited += cfg.get("quota_wait_s", 1800)
                continue
            batch["errors"].append("hết lượt chat ở mọi tài khoản quá lâu")
            _save_batch(kdir, batch)
            break
        except Exception as e:  # noqa: BLE001 - ChatGPT/mạng hỏng: ghi lại, vẫn vét + báo cáo các cuốn đã có
            batch["errors"].append(f"{type(e).__name__}: {e}"[:500])
            _save_batch(kdir, batch)
            on_event(f"  ✘ Lên ý tưởng lỗi: {e}")
            break
        new = [c for c in res.concepts if c.name not in batch["concepts"]]
        batch["concepts"] += [c.name for c in new]
        batch["failed_ideas"] += [f for f in res.failed if f not in batch["failed_ideas"]]
        _save_batch(kdir, batch)
        empty_rounds = 0 if new or res.failed else empty_rounds + 1
        for cdir in new:
            _safe_pipelined(cdir, cfg, finisher, on_event)
        if pick:
            break

    # 3) Vòng vét: làm lại một lần các cuốn dừng vì thiếu ảnh / lỗi bất ngờ (chờ hậu kỳ nền xong để đọc đúng status).
    finisher.wait()
    retry = [rel for rel in batch["concepts"] if layout.is_book(kdir / rel)
             and not _read_status(kdir / rel).get("ok") and _read_status(kdir / rel).get("stage") in RETRY_STAGES]
    if retry:
        on_event(f"▶ Vòng vét: {len(retry)} cuốn dở - chờ {int(wait)}s cho tài khoản hồi lượt rồi làm lại")
        time.sleep(wait)
        for rel in retry:
            _safe_pipelined(kdir / rel, cfg, finisher, on_event)
        finisher.wait()

    batch["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = batch_report(kdir, batch)
    on_event(f"▶ Batch xong: {sum(r['ok'] for r in rows)}/{batch['target']} cuốn thành công - "
             f"báo cáo: {layout.batch_report_file(kdir)}")
    return [{"concept": str(kdir / r["concept"]), "ok": r["ok"], "stage": r["stage"], "reason": r["reason"]}
            for r in rows]
