"""Gen ảnh bằng ChatGPT web: mỗi job = 1 chat mới, đính ảnh neo, lấy về đúng 1 ảnh.

Chạy song song: mỗi tài khoản (Chrome profile đã đăng nhập của chatgpt-automation) là một luồng
riêng, cùng rút job từ một hàng đợi. Tài khoản hết lượt thì nghỉ, job của nó trả về hàng đợi cho
tài khoản khác. Các bài học xương máu lấy từ chatgpt_pool.py:
- trang có nhiều input[type=file]; cái `mobile-*` là của khung soạn bản mobile -> bỏ qua;
- phải chờ thumbnail upload xong mới gửi, không thì ChatGPT chỉ nhận chữ;
- ChatGPT hay vẽ lại ảnh phút chót -> chờ ảnh đứng yên vài giây mới chốt;
- đọc chữ cuối trang để phân biệt hết lượt / bị từ chối / lỗi tạm.
"""
from __future__ import annotations

import base64
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("calforge.imagegen")

URL = "https://chatgpt.com/"
SEL_PROMPT = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', "textarea[data-id]"]
SEL_SEND = ['button[data-testid="send-button"]', 'button[aria-label*="Send" i]']
# Lọc ảnh gen thật với ảnh nền/icon giao diện theo CẠNH DÀI. Không dùng cạnh ngắn: họa tiết
# thường rộng và thấp (vd cành lá 2000x667) -> cạnh ngắn < 768 sẽ bị loại nhầm, khiến driver
# tưởng chưa có ảnh và gen lại nhiều lần dù ChatGPT đã gen xong.
MIN_SIDE = 768  # ảnh gen thật cạnh dài >= 1024; icon/nền giao diện <= 512 -> loại

QUOTA_PAT = ("reached your limit", "reached the limit", "hit your limit", "limit for image",
             "image generation limit", "you can create more images", "able to create images again",
             "out of image generation", "out of image", "please try again in", "try again in ",
             "usage limit", "rate limit", "too many requests", "đã đạt giới hạn", "hết lượt")
REFUSE_PAT = ("i can't help with that", "i cannot help with that", "i'm unable to create", "i can't create",
              "i cannot create", "i'm not able to generate", "content policy", "usage policies", "violates")
TEMP_PAT = ("something went wrong", "an error occurred", "error generating", "network error",
            "please try again", "try again later", "unable to generate", "wasn't able to generate")

STATE_JS = """() => {
  const pick = (s) => Array.from(document.querySelectorAll(s));
  let a = pick('[data-message-author-role="assistant"]');
  if (!a.length) a = pick('article[data-turn="assistant"], [data-turn="assistant"]');
  // Giao diện mới (acc2/acc5, 09/2026): không còn data-message-author-role, mỗi tin nhắn mang
  // data-chatgpt-search-unit-key="...:user" hoặc "...:assistant".
  if (!a.length) a = pick('[data-chatgpt-search-unit-key$=":assistant"]');
  let u = pick('[data-message-author-role="user"]');
  if (!u.length) u = pick('article[data-turn="user"], [data-turn="user"]');
  if (!u.length) u = pick('[data-chatgpt-search-unit-key$=":user"]');
  const vis = (el) => el && el.getBoundingClientRect().width > 0;
  let busy = false;
  for (const s of ['button[data-testid="stop-button"]', 'button[data-testid*="stop" i]',
                   'button[aria-label*="Stop" i]', '[data-testid="stop-generating"]'])
    if (vis(document.querySelector(s))) { busy = true; break; }
  const last = a.length ? a[a.length - 1] : null;
  const imgs = [];
  if (last) for (const im of last.querySelectorAll('img')) {
    if (im.closest('form')) continue;
    const src = im.currentSrc || im.src || '';
    if (src) imgs.push({src, w: im.naturalWidth, h: im.naturalHeight, done: im.complete});
  }
  // Ảnh đang vẽ: ảnh chưa tải xong, hoặc khung chờ (shimmer/skeleton/aria-busy/progress) trong lượt cuối.
  let pending = imgs.some((im) => !im.done);
  if (last && !pending)
    pending = !!last.querySelector('[aria-busy="true"], [role="progressbar"], [class*="shimmer" i], ' +
                                   '[class*="skeleton" i], [class*="loading" i], [class*="placeholder" i]');
  const skip = 'form, nav, aside, header, [contenteditable="true"], [data-user-message-bubble], ' +
    '[data-message-author-role="user"], [data-turn="user"], [data-chatgpt-search-unit-key$=":user"]';
  const pageImgs = [];
  for (const im of document.querySelectorAll('img')) {
    if (im.closest(skip)) continue;
    const src = im.currentSrc || im.src || '';
    if (src) pageImgs.push({src, w: im.naturalWidth, h: im.naturalHeight, done: im.complete});
  }
  const tail = (last ? last.innerText : '') + ' ' +
    pick('[role="dialog"], [role="alert"], .toast-root').map((e) => e.innerText).join(' ');
  return {assistant: a.length, user: u.length, busy, pending, imgs, pageImgs, tail: tail.slice(-1500)};
}"""

ATTACH_JS = """() => {
  const form = document.querySelector('form') || document.body;
  const q = (s) => form.querySelectorAll(s).length;
  const n = Math.max(q('img[src^="blob:"], img[src^="data:"]'), q('[data-testid*="attachment" i]'),
                     q('button[aria-label*="Remove" i]'));
  const up = form.querySelector('[role="progressbar"], svg[class*="spin" i], [class*="uploading" i]');
  return {n, uploading: !!up};
}"""

INSERT_JS = """(el, txt) => {
  el.focus();
  const sel = window.getSelection(); const range = document.createRange();
  range.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(range);
  document.execCommand('insertText', false, txt);
  el.dispatchEvent(new Event('input', {bubbles: true}));
}"""

FETCH_JS = """async (src) => {
  const r = await fetch(src, {credentials: 'include'});
  const b = new Uint8Array(await r.arrayBuffer());
  let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return btoa(s);
}"""


class QuotaExceeded(RuntimeError): ...


class Refused(RuntimeError): ...


class TempError(RuntimeError): ...


class WantsSourceImage(TempError):
    """ChatGPT coi nhầm là việc sửa ảnh và đòi ảnh gốc thay vì tự vẽ."""


# Chữ tạm ChatGPT hiện TRONG LÚC vẽ ảnh (chưa có ảnh, không có nút Stop). Thấy các chữ này nghĩa là
# ảnh đang được tạo, phải chờ tiếp - trước đây driver tưởng "trả lời xong mà không có ảnh" và bỏ ngang.
GEN_PAT = ("creating image", "generating image", "generating your image", "making your image", "getting started",
           "adding details", "adding final", "almost done", "almost there", "finishing up", "final touches",
           "image is being", "working on your image", "đang tạo", "đang vẽ", "sắp xong", "thêm chi tiết")


# ChatGPT trả lời đòi ảnh gốc / bảo là việc sửa ảnh (công cụ vẽ chọn nhầm chế độ sửa).
SOURCE_PAT = ("upload the", "upload a", "upload an", "source image", "reference image", "image to edit",
              "treated the request as an edit", "treated this as an edit", "as an edit", "edit request",
              "attach the image", "attach an image", "provide the image", "provide an image", "image target")
NUDGE_NEW = ("Please generate it now as a completely new image from the text description above. "
             "This is text-to-image generation, not an edit, so no other image is needed.")


def wants_source(text: str) -> bool:
    low = " ".join((text or "").lower().replace("\u2019", "'").split())
    return any(p in low for p in SOURCE_PAT)


def generating(st: dict) -> bool:
    """Trang cho thấy ảnh đang được vẽ (khung chờ trong DOM hoặc chữ tạm kiểu "Creating image")."""
    low = " ".join((st.get("tail") or "").lower().split())
    return bool(st.get("pending")) or any(p in low for p in GEN_PAT)


def _sent(st: dict, before: dict) -> bool:
    """Tin nhắn đã đi: có thêm tin người dùng, có lượt trả lời mới, hoặc ChatGPT đang làm (nút Stop)."""
    return st["user"] > before["user"] or st["assistant"] > before["assistant"] or bool(st.get("busy"))


def _new_images(st: dict, before: dict) -> list[dict]:
    """Ảnh lớn đã tải xong trong khung trả lời cuối."""
    return [im for im in st["imgs"] if max(im["w"], im["h"]) >= MIN_SIDE and im["done"]]


def classify(text: str) -> str:
    low = " ".join((text or "").lower().split())
    for pats, kind in ((QUOTA_PAT, "quota"), (REFUSE_PAT, "refused"), (TEMP_PAT, "error")):
        if any(p in low for p in pats):
            return kind
    return ""


@dataclass
class GenJob:
    id: str
    prompt: str
    out: Path                          # đường dẫn không đuôi; đuôi theo định dạng ảnh nhận về
    attach: list[Path] = field(default_factory=list)
    accept: object = None              # hàm (Path) -> str | None: lý do loại ảnh, None = nhận
    attempts: int = 0
    result: Path | None = None
    error: str | None = None


def _eval(page, js: str, *args, tries: int = 6):
    """page.evaluate chịu được lúc ChatGPT chuyển trang (từ / sang /c/<id> ngay sau khi gửi):
    ngữ cảnh JS bị huỷ giữa chừng thì chờ trang nạp xong rồi đọc lại, không coi là lỗi job."""
    for i in range(tries):
        try:
            return page.evaluate(js, *args)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if i == tries - 1 or not ("context was destroyed" in msg or "navigation" in msg.lower()):
                raise
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)


class _Worker:
    def __init__(self, profile_dir: Path, headless: bool, timeout_s: float, settle_s: float = 8.0):
        self.profile_dir = profile_dir
        self.headless = headless
        self.timeout_s = timeout_s
        self.settle_s = settle_s

    # ---- trang ----
    def _find(self, page, selectors, timeout_ms=30_000):
        per = max(1500, timeout_ms // len(selectors))
        for sel in selectors:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=per)
                return loc
            except Exception:  # noqa: BLE001
                continue
        raise TempError(f"không thấy {selectors[0]} (ChatGPT đổi giao diện hoặc chưa đăng nhập)")

    def _attach(self, page, files: list[Path]) -> None:
        if not files:
            return
        page.locator('input[type="file"]').first.wait_for(state="attached", timeout=15_000)
        ranked = []
        for inp in page.locator('input[type="file"]').all():
            ident = (inp.get_attribute("id") or "").lower()
            if "camera" not in ident:
                ranked.append((ident.startswith("mobile-"), inp))
        for _, inp in sorted(ranked, key=lambda x: x[0]):
            try:
                inp.set_input_files([str(f) for f in files])
            except Exception:  # noqa: BLE001
                continue
            deadline = time.monotonic() + 30 + 5 * len(files)
            while time.monotonic() < deadline:
                st = _eval(page, ATTACH_JS)
                if st["n"] >= len(files) and not st["uploading"]:
                    page.wait_for_timeout(600)
                    return
                page.wait_for_timeout(500)
        raise TempError("không đính kèm được ảnh neo")

    def _send(self, page, prompt: str) -> dict:
        before = _eval(page, STATE_JS)
        box = self._find(page, SEL_PROMPT)
        box.click()
        box.evaluate(INSERT_JS, prompt)
        page.wait_for_timeout(400)
        for sel in SEL_SEND:
            btn = page.locator(sel).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=4000)
                    break
            except Exception:  # noqa: BLE001
                continue
        else:
            box.press("Enter")
        deadline = time.monotonic() + 30
        while not _sent(_eval(page, STATE_JS), before):
            if time.monotonic() > deadline:
                raise TempError("gửi tin nhắn không đi")
            page.wait_for_timeout(400)
        return before

    def _wait_image(self, page, before: dict) -> str:
        """Chờ đến khi có ảnh lớn trong lượt trả lời mới và ảnh đứng yên settle_s giây."""
        start = time.monotonic()
        deadline = start + self.timeout_s
        hard_deadline = start + self.timeout_s * 1.5  # hết giờ mà vẫn đang vẽ thì cho thêm, không cắt ngang
        # Chỉ bỏ sớm khi trang THẬT SỰ không có gì xảy ra. Gen ảnh không hiện nút Stop và lượt trả lời
        # có khi chỉ hiện lúc ảnh gần xong, nên mọi dấu hiệu "đang vẽ" đều tính là có tiến triển.
        no_progress = min(240.0, self.timeout_s * .6)
        chosen, since, quiet_since, progressed = None, 0.0, None, False
        old_srcs = {im["src"] for im in before.get("pageImgs", []) + before.get("imgs", [])}
        drawing = False
        while time.monotonic() < deadline or (drawing and time.monotonic() < hard_deadline):
            st = _eval(page, STATE_JS)
            new_turn = st["assistant"] > before["assistant"]
            drawing = generating(st) if new_turn else bool(st.get("pending"))
            big = _new_images(st, before) if new_turn else []
            if not big:
                big = [im for im in st.get("pageImgs", []) if im["src"] not in old_srcs
                       and max(im["w"], im["h"]) >= MIN_SIDE and im["done"]]
                new_turn = new_turn or bool(big)
            if new_turn or st.get("busy") or drawing:
                progressed = True
            elif not progressed and time.monotonic() - start > no_progress:
                raise TempError(f"tab kẹt: ChatGPT chưa phản hồi sau {no_progress:.0f}s")
            if big:
                best = max(big, key=lambda im: im["w"] * im["h"])["src"]
                if best != chosen:
                    chosen, since = best, time.monotonic()
                elif not st["busy"] and time.monotonic() - since >= self.settle_s:
                    return chosen
            elif new_turn and not st["busy"] and not drawing and st["tail"].strip():
                # Chỉ kết luận khi lượt trả lời ĐÃ CÓ CHỮ, không còn dấu hiệu đang vẽ, mà vẫn không có ảnh.
                kind = classify(st["tail"])
                quiet_since = quiet_since or time.monotonic()
                if kind == "quota":
                    raise QuotaExceeded(st["tail"][-200:])
                if wants_source(st["tail"]):
                    raise WantsSourceImage(st["tail"][-200:])
                if kind == "refused":
                    raise Refused(st["tail"][-200:])
                if kind == "error" or time.monotonic() - quiet_since > 45:
                    raise TempError(f"trả lời xong mà không có ảnh: {st['tail'][-160:]!r}")
            else:
                quiet_since = None
            page.wait_for_timeout(1000)
        raise TempError(f"quá {self.timeout_s:.0f}s chưa ra ảnh")

    def run_job(self, page, job: GenJob) -> Path:
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        self._find(page, SEL_PROMPT, 60_000)
        self._attach(page, job.attach)
        before = self._send(page, job.prompt)
        try:
            src = self._wait_image(page, before)
        except WantsSourceImage:
            # nhắc lại ngay trong chat này thay vì mở chat mới gửi lại cả prompt
            before = self._send(page, NUDGE_NEW)
            src = self._wait_image(page, before)
        data = base64.b64decode(_eval(page, FETCH_JS, src))
        ext = ".webp" if data[8:12] == b"WEBP" else ".jpg" if data[:2] == b"\xff\xd8" else ".png"
        dst = job.out.with_suffix(ext)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(ext + ".part")
        tmp.write_bytes(data)
        reason = job.accept(tmp) if job.accept else None
        if reason:
            rejected = job.out.parent.parent / "ky_thuat" / "anh_bi_loai"   # _he_thong/ky_thuat/, xem calforge/layout.py
            rejected.mkdir(parents=True, exist_ok=True)
            tmp.replace(rejected / f"{job.id}-attempt{job.attempts}{ext}")
            raise TempError(f"ảnh không đạt: {reason}")
        tmp.replace(dst)
        return dst


def run_jobs(jobs: list[GenJob], profiles_dir: Path, profiles: list[str], *, headless=False,
             timeout_s=420, max_attempts=3, on_event=print) -> list[GenJob]:
    """Chạy hết job trên các tài khoản song song. Trả về danh sách job (có result hoặc error)."""
    from playwright.sync_api import sync_playwright

    q: queue.Queue[GenJob] = queue.Queue()
    for j in jobs:
        q.put(j)
    remaining = {"n": len(jobs)}
    lock = threading.Lock()
    alive = {"n": 0}

    def finish(job: GenJob):
        with lock:
            remaining["n"] -= 1

    def worker(profile: str):
        udir = profiles_dir / profile
        w = _Worker(udir, headless, timeout_s)
        try:
            with sync_playwright() as pw:
                ctx = pw.chromium.launch_persistent_context(
                    str(udir), headless=headless, channel="chrome", viewport={"width": 1400, "height": 950},
                    args=["--disable-blink-features=AutomationControlled",
                          "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"])
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    while True:
                        with lock:
                            if remaining["n"] <= 0:
                                return
                        try:
                            job = q.get(timeout=2)
                        except queue.Empty:
                            continue
                        job.attempts += 1
                        on_event(f"[{profile}] {job.id}: gen (lần {job.attempts})")
                        try:
                            job.result = w.run_job(page, job)
                            job.error = None
                            on_event(f"[{profile}] {job.id}: xong -> {job.result.name}")
                            finish(job)
                        except QuotaExceeded as e:
                            job.attempts -= 1            # không tính lượt: lỗi của tài khoản
                            q.put(job)
                            on_event(f"[{profile}] HẾT LƯỢT, nghỉ tài khoản này: {str(e)[:120]}")
                            recruit()                    # gọi tài khoản dự bị vào thay (nếu còn việc)
                            return
                        except Refused as e:
                            job.error = f"bị từ chối: {str(e)[:200]}"
                            on_event(f"[{profile}] {job.id}: {job.error}")
                            finish(job)
                        except TempError as e:
                            job.error = str(e)[:300]
                            if job.attempts < max_attempts:
                                if job.id == "grid" and "vùng đặt lịch" in job.error:
                                    job.prompt += (
                                        f"\n\nRETRY CORRECTION {job.attempts}: The previous result was rejected because "
                                        "the calendar writing area was too busy or lacked contrast with the specified "
                                        "software text colors. Preserve the chosen surface system, but remove illustrated "
                                        "objects and strong high-frequency marks from x=8–92%, y=30–88%, and adjust its "
                                        "tone until the supplied title and body colors are clearly readable. Do not turn "
                                        "it into generic pale paper. Keep decorative motifs solely above y=27%. "
                                        "Do not solve this by adding or moving a character, animal, focal object, "
                                        "still life or miniature scene to the margins; decorative motifs only."
                                    )
                                q.put(job)
                                on_event(f"[{profile}] {job.id}: QC không đạt ({job.error[:120]}) - sửa prompt và thử lại")
                            else:
                                on_event(f"[{profile}] {job.id}: bỏ sau {job.attempts} lần: {job.error[:160]}")
                                finish(job)
                        except Exception as e:  # noqa: BLE001 - lỗi tạm: thử lại nếu còn lượt
                            job.error = str(e)[:300]
                            if job.attempts < max_attempts:
                                q.put(job)
                                on_event(f"[{profile}] {job.id}: lỗi ({job.error[:120]}) - thử lại")
                            else:
                                on_event(f"[{profile}] {job.id}: bỏ sau {job.attempts} lần: {job.error[:160]}")
                                finish(job)
                finally:
                    ctx.close()
        except Exception as e:  # noqa: BLE001 - không mở được Chrome/profile (thường do profile bị khóa
            # bởi Chrome mồ côi từ lần chạy trước) -> gọi tài khoản dự bị vào thay, đừng để job kẹt.
            on_event(f"[{profile}] không mở được Chrome (profile bị khóa?): {str(e)[:160]}")
            recruit()
        finally:
            with lock:
                alive["n"] -= 1

    # Chỉ mở số cửa sổ Chrome bằng số việc: gen ảnh neo (1 việc) không mở thừa 4 cửa sổ trắng.
    # Giữ nguyên thứ tự tài khoản (ưu tiên); các tài khoản dư để dành làm dự bị.
    n_workers = max(1, min(len(profiles), len(jobs)))
    threads = []
    reserves = list(profiles[n_workers:])   # tài khoản dự bị, gọi vào khi worker hết lượt

    def spawn(profile: str):
        with lock:
            alive["n"] += 1
        t = threading.Thread(target=worker, args=(profile,), daemon=True)
        t.start()
        threads.append(t)

    def recruit():
        """Khi một worker nghỉ vì hết lượt: gọi một tài khoản dự bị vào thay (nếu còn việc)."""
        with lock:
            if remaining["n"] <= 0 or not reserves:
                return
            nxt = reserves.pop(0)
        on_event(f"[{nxt}] gọi tài khoản dự bị vào thay")
        spawn(nxt)

    for p in profiles[:n_workers]:
        spawn(p)
        time.sleep(1.5)  # bật Chrome lệch nhau cho đỡ nghẽn
    while any(t.is_alive() for t in threads):
        for t in list(threads):
            t.join(timeout=1)
    left = []
    while not q.empty():
        j = q.get()
        j.error = j.error or "hết tài khoản còn lượt"
        left.append(j)
    return jobs
