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
from contextlib import contextmanager
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

from ..llm.limits import QUOTA_PAT, REFUSE_PAT, TEMP_PAT, RateWatch, classify, page_notice  # noqa: E402,F401

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
    pick('[role="dialog"], [role="alert"], [role="status"], .toast-root, [data-testid*="toast" i], [class*="toast" i]')
      .filter((e) => e.getBoundingClientRect().width > 0).map((e) => e.innerText).join(' ');
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


class ThirdPartyIPRefused(Refused):
    """ChatGPT từ chối vì TM, bản quyền, quyền sở hữu trí tuệ của bên thứ ba, hoặc quy định ảnh khỏa thân/tình dục."""


class TempError(RuntimeError): ...


class NavError(RuntimeError):
    """Không mở được trang ChatGPT (mạng chập / trang tự chuyển hướng / Cloudflare): lỗi của tài khoản-mạng,
    KHÔNG phải lỗi ảnh -> không tính là một lần vẽ; việc chuyển sang tài khoản khác."""


NAV_TRANSIENT = ("interrupted by another navigation", "chrome-error://", "net::err", "err_", "navigation failed",
                 "timeout", "target page, context or browser has been closed")


def open_home(page, url: str, tries: int = 4, wait_ms: int = 1500, net_wait_ms: int = 12_000) -> None:
    """Mở trang ChatGPT chắc chắn: bị chuyển hướng giữa chừng thì chờ trang ổn định rồi kiểm tra; trang lỗi mạng
    (chrome-error) thì chờ mạng rồi mở lại. Hết số lần mà vẫn không vào được -> NavError."""
    last = ""
    for i in range(tries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            if "chrome-error://" not in (page.url or ""):
                return
            last = f"trang lỗi mạng ({page.url})"
        except Exception as e:  # noqa: BLE001
            last = str(e).splitlines()[0][:200]
            if not any(k in last.lower() for k in NAV_TRANSIENT):
                raise
            # bị chuyển hướng sang chính chatgpt.com: chờ trang nạp xong, nếu đã ở trang ChatGPT là được
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:  # noqa: BLE001
                pass
            if "chatgpt.com" in (page.url or "") and "chrome-error" not in last.lower():
                return
        page.wait_for_timeout(net_wait_ms if "chrome-error" in last.lower() or "err_" in last.lower() else wait_ms)
    raise NavError(f"không mở được ChatGPT sau {tries} lần: {last}")


LOGGED_OUT = "tài khoản bị đăng xuất"
BANNED = "tài khoản bị khoá"
BODY_TEXT_JS = "() => (document.body ? document.body.innerText : '').slice(0, 4000)"
# lỗi hết lượt mang dấu hiệu bị CHẶN TỐC ĐỘ (không phải hết lượt theo gói): tính vào việc giảm số Chrome
RATE_HINTS = ("429", "too many", "rate limit", "rate_limit", "slow down", "unusual activity", "suspicious",
              "quá nhiều", "bất thường", "chặn lúc gửi")
NAV_MAX = 6               # một ảnh gặp lỗi trang/mạng quá bấy nhiêu lần (trên nhiều tài khoản) thì mới tính là lần hỏng


def _login_screen(page) -> bool:
    from ..llm.bulk_login import LOGIN_STATE_JS
    try:
        st = page.evaluate(LOGIN_STATE_JS)
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(st, dict) or st.get("appReady"):
        return False
    return bool(st.get("hasLoginBtn")) or "auth" in (getattr(page, "url", "") or "")


def account_state(page) -> tuple[str, str]:
    """Trang ChatGPT cho thấy tài khoản CHẾT? -> ("banned" | "logged_out" | "", chi tiết).
    "logged_out" = giao diện là màn hình đăng nhập (còn nút Log in / Sign up, không có ô chat). Kiểm tra 2 lần cách
    nhau vài giây để không bỏ nhầm tài khoản lúc trang đang tải dở."""
    from ..llm.limits import is_banned
    try:
        body = page.evaluate(BODY_TEXT_JS)
    except Exception:  # noqa: BLE001
        body = ""
    if isinstance(body, str) and is_banned(body):
        return "banned", " ".join(body.split())[:160]
    if not _login_screen(page):
        return "", ""
    try:
        page.wait_for_timeout(3000)
    except Exception:  # noqa: BLE001
        pass
    return ("logged_out", "trang ChatGPT hiện màn hình đăng nhập") if _login_screen(page) else ("", "")


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


@dataclass
class GenJob:
    id: str
    prompt: str
    out: Path                          # đường dẫn không đuôi; đuôi theo định dạng ảnh nhận về
    attach: list[Path] = field(default_factory=list)
    accept: object = None              # hàm (Path) -> str | None: lý do loại ảnh, None = nhận
    attempts: int = 0
    nav_errors: int = 0                # số lần lỗi trang/mạng (không tính vào attempts cho tới NAV_MAX)
    refusals: int = 0                  # số lần ChatGPT từ chối prompt này vì TM / nội dung nhạy cảm
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
        # Không thấy ô chat: trang chưa tải xong / bị che / tài khoản chết - lỗi của trang, KHÔNG phải ảnh
        kind, detail = account_state(page)
        if kind == "banned":
            raise NavError(f"{BANNED}: {detail}")
        if kind == "logged_out":
            raise NavError(f"{LOGGED_OUT}: trang ChatGPT đòi đăng nhập lại")
        raise NavError(f"không thấy ô chat {selectors[0]} (trang chưa tải xong / bị che)")

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
        from ..llm.pool import human_pause
        human_pause()                                   # nhịp người thật trước khi gõ + gửi
        try:
            box.click(timeout=15_000)
            box.evaluate(INSERT_JS, prompt)
        except Exception as e:  # noqa: BLE001 - ô chat bị hộp thoại che / trang đang tải lại
            raise NavError(f"không gõ được vào ô chat: {str(e).splitlines()[0][:120]}") from e
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
            try:
                box.press("Enter", timeout=15_000)
            except Exception as e:  # noqa: BLE001
                raise NavError(f"không bấm gửi được: {str(e).splitlines()[0][:120]}") from e
        sent_at = time.monotonic()
        deadline = sent_at + 30
        while not _sent(_eval(page, STATE_JS), before):
            limited = self._limited(page, sent_at)
            if limited:
                raise QuotaExceeded(f"chặn lúc gửi: {limited}")
            if time.monotonic() > deadline:
                raise NavError("gửi tin nhắn không đi (trang ChatGPT không phản hồi)")
            page.wait_for_timeout(400)
        return before

    def _limited(self, page, since: float) -> str | None:
        """Bị giới hạn (mạng 429/503 hoặc hộp thoại/banner báo hết lượt/quá tải) kể từ mốc since."""
        watch = getattr(page, "_calforge_rate", None)
        hit = watch.recent(since) if watch else None
        if hit:
            return hit
        notice = page_notice(page)
        return notice[-200:] if notice and classify(notice) == "quota" else None

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
        # quá giờ mà vẫn đang vẽ, hoặc ảnh vừa ra đang chờ đứng yên: cho thêm tới hard_deadline
        while time.monotonic() < deadline or ((drawing or chosen) and time.monotonic() < hard_deadline):
            st = _eval(page, STATE_JS)
            new_turn = st["assistant"] > before["assistant"]
            # IP/TM là lỗi kết thúc của cả cuốn: bắt ngay khi text xuất hiện, kể cả giao diện còn giữ
            # spinner/aria-busy. Nếu chờ cờ "đang vẽ" biến mất, một UI bị kẹt có thể làm phí đủ 420 giây.
            if classify(st.get("tail", "")) == "ip_refused":
                raise ThirdPartyIPRefused(st["tail"][-300:])
            drawing = generating(st) if new_turn else bool(st.get("pending"))
            big = _new_images(st, before) if new_turn else []
            if not big:
                big = [im for im in st.get("pageImgs", []) if im["src"] not in old_srcs
                       and max(im["w"], im["h"]) >= MIN_SIDE and im["done"]]
                new_turn = new_turn or bool(big)
            if not big:                      # banner/hộp thoại/429 báo giới hạn giữa chừng -> nghỉ tài khoản
                limited = self._limited(page, start)
                if limited and not drawing:
                    raise QuotaExceeded(limited)
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
                if kind == "ip_refused":
                    raise ThirdPartyIPRefused(st["tail"][-300:])
                if kind == "refused":         # từ chối chung ("may violate our content policies"): xử lý như TM -
                    raise ThirdPartyIPRefused(st["tail"][-300:])   # gửi lại 2 lần, vẫn bị thì bỏ cuốn (03/10/2026)
                if kind == "error" or time.monotonic() - quiet_since > 45:
                    raise TempError(f"trả lời xong mà không có ảnh: {st['tail'][-160:]!r}")
            else:
                quiet_since = None
            page.wait_for_timeout(1000)
        raise TempError(f"quá {self.timeout_s:.0f}s chưa ra ảnh")

    def run_job(self, page, job: GenJob) -> Path:
        if not hasattr(page, "_calforge_rate"):
            page._calforge_rate = RateWatch(page)          # theo dõi 429/503 của trang (gắn 1 lần)
        open_home(page, URL)                             # mạng chập / chuyển hướng: chờ + thử lại, không tính lượt
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


def _correct_prompt(job: GenJob) -> None:
    """Ảnh bị QC/OCR loại: thêm lời sửa vào prompt cho lần vẽ lại."""
    if job.id.startswith("g") and "lịch sai" in (job.error or ""):
        job.prompt += (
            f"\n\nRETRY CORRECTION {job.attempts}: the previous page had calendar errors "
            "found by an automatic check. Redraw the page and place EVERY number exactly "
            "in the week and weekday column listed above, each number once, weekday "
            "labels in the order SUN MON TUE WED THU FRI SAT from left to right, with "
            "clear, evenly spaced columns."
        )
    if job.id == "grid" and "vùng đặt lịch" in (job.error or ""):
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


NAV_REST_S = 120          # tài khoản mở trang lỗi nghỉ vẽ bấy nhiêu giây
REFUSAL_TRIES = 3         # ChatGPT từ chối vì TM / nội dung nhạy cảm: gửi lại đúng prompt đó thêm 2 lần rồi mới bỏ cuốn


def run_jobs(jobs: list[GenJob], profiles_dir: Path, profiles: list[str], *, headless=False,
             timeout_s=420, max_attempts=3, on_event=print, pool=None, open_page=None) -> list[GenJob]:
    """Chạy hết job, mỗi tài khoản rảnh một luồng; tài khoản mượn qua bộ điều phối chung (llm/pool.py) nên
    nhiều cuốn / bước chat chạy song song không bao giờ dùng chung một tài khoản.

    - Luồng vẽ hết việc trong hàng -> trả tài khoản ngay (cuốn khác / chat dùng); có việc mới thì mượn lại.
    - Hết lượt vẽ -> tài khoản nghỉ vẽ (vẫn chat được), việc trả về hàng, không tính lượt thử.
    - Chat đang thiếu chỗ -> luồng vẽ nhường tài khoản sau ảnh đang vẽ.
    - Mọi tài khoản đều nghỉ vẽ -> dừng, việc còn lại ghi QUOTA_MARK để batch chờ rồi thử lại.
    open_page(profile) (tuỳ chọn, cho test): context manager trả về trang đã mở."""
    from ..llm.pool import IMAGE, get_pool

    pool = pool or get_pool()
    q: queue.Queue[GenJob] = queue.Queue()
    for j in jobs:
        q.put(j)
    lock = threading.Lock()
    state = {"remaining": len(jobs), "alive": 0}
    broken: set[str] = set()                          # không mở được Chrome trong lần chạy này
    fatal_ip = threading.Event()                      # một job dính IP/TM => huỷ mọi job chưa gửi của cuốn
    fatal_ip_detail = {"text": ""}

    def finish(job: GenJob) -> None:
        with lock:
            state["remaining"] -= 1
        pool.poke()                                   # đánh thức vòng điều phối

    @contextmanager
    def default_open(profile: str):
        from playwright.sync_api import sync_playwright
        from ..llm.browser import launch_options
        udir = profiles_dir / profile
        with sync_playwright() as pw:
            with pool.launch_gate():
                ctx = pw.chromium.launch_persistent_context(
                    str(udir), channel="chrome", viewport={"width": 1400, "height": 950},
                    **launch_options(headless))
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                if headless in ("hidden", None):
                    from ..llm.browser import hide_offscreen_from_taskbar
                    hide_offscreen_from_taskbar()     # Chrome ngầm: không hiện biểu tượng dưới thanh tác vụ
                yield page
            finally:
                ctx.close()

    opener = open_page or default_open

    def handle(profile: str, w, page, job: GenJob) -> bool:
        """Chạy 1 việc. False = tài khoản phải thôi (hết lượt)."""
        job.attempts += 1
        on_event(f"[{profile}] {job.id}: gen (lần {job.attempts})")
        try:
            job.result = w.run_job(page, job)
            job.error = None
            on_event(f"[{profile}] {job.id}: xong -> {job.result.name}")
            finish(job)
        except QuotaExceeded as e:
            job.attempts -= 1                         # không tính lượt: lỗi của tài khoản
            q.put(job)
            pool.rest(profile, IMAGE, pool.rest_s, str(e))
            on_event(f"[{profile}] HẾT LƯỢT VẼ, nghỉ vẽ tài khoản này: {str(e)[:120]}")
            if any(h in str(e).lower() for h in RATE_HINTS):
                pool.trouble(profile, str(e))             # bị chặn tốc độ: nhiều tài khoản cùng bị thì giảm số Chrome
            return False
        except NavError as e:
            dead_kind = "banned" if BANNED in str(e) else "logged_out" if LOGGED_OUT in str(e) else ""
            if dead_kind:                                 # tài khoản CHẾT: bỏ hẳn, không phải lỗi mạng của việc này
                pool.drop(profile, dead_kind, str(e))
                job.attempts -= 1
                q.put(job)
                on_event(f"[{profile}] ✘ TÀI KHOẢN CHẾT: "
                         + (f"{BANNED} - cần thay tài khoản" if dead_kind == "banned" else
                            f"{LOGGED_OUT}, giao diện là màn hình đăng nhập - cần đăng nhập lại")
                         + f". Đã bỏ tài khoản này khỏi batch, chuyển {job.id} sang tài khoản khác")
                return False
            pool.rest(profile, IMAGE, NAV_REST_S, str(e))   # tài khoản nghỉ, việc sang acc khác
            pool.trouble(profile, str(e))
            job.nav_errors += 1
            if job.nav_errors < NAV_MAX:
                job.attempts -= 1                     # lỗi trang / mạng, không phải lỗi ảnh: không tính lượt
                q.put(job)
                on_event(f"[{profile}] lỗi trang ChatGPT ({str(e)[:80]}); chuyển {job.id} sang tài khoản khác")
            else:                                     # lỗi trang lặp mãi trên nhiều tài khoản: tính như lỗi thường
                job.error = f"lỗi trang ChatGPT lặp lại: {str(e)[:200]}"
                if job.attempts < max_attempts:
                    q.put(job)
                else:
                    on_event(f"[{profile}] {job.id}: bỏ sau {job.attempts} lần: {job.error[:160]}")
                    finish(job)
            return False
        except ThirdPartyIPRefused as e:
            job.refusals += 1
            if job.refusals < REFUSAL_TRIES and not fatal_ip.is_set():
                # ChatGPT đôi khi bắt nhầm: gửi lại ngay đúng prompt này (không tính vào số lần vẽ lỗi của ảnh)
                on_event(f"[{profile}] {job.id}: ChatGPT từ chối (TM/bản quyền, nội dung nhạy cảm hoặc vi phạm chính sách) lần "
                         f"{job.refusals}/{REFUSAL_TRIES} - gửi lại prompt: {str(e)[:120]}")
                job.attempts -= 1
                return handle(profile, w, page, job)
            job.error = f"IP/TM_REJECTED: {str(e)[:260]}"
            fatal_ip_detail["text"] = str(e)[:260]
            fatal_ip.set()
            on_event(f"[{profile}] {job.id}: BỎ CUỐN - ChatGPT từ chối (TM/bản quyền, nội dung nhạy cảm hoặc vi phạm chính sách) "
                     f"{job.refusals} lần liền: {str(e)[:160]}")
            finish(job)
        except Refused as e:
            job.error = f"bị từ chối: {str(e)[:200]}"
            on_event(f"[{profile}] {job.id}: {job.error}")
            finish(job)
        except Exception as e:  # noqa: BLE001 - TempError (QC/OCR/mạng) và lỗi tạm: thử lại nếu còn lượt
            job.error = str(e)[:300]
            if job.attempts < max_attempts:
                if isinstance(e, TempError):
                    _correct_prompt(job)
                q.put(job)
                on_event(f"[{profile}] {job.id}: không đạt ({job.error[:120]}) - thử lại")
            else:
                on_event(f"[{profile}] {job.id}: bỏ sau {job.attempts} lần: {job.error[:160]}")
                finish(job)
        return True

    def worker(profile: str) -> None:
        w = _Worker(profiles_dir / profile, headless, timeout_s)
        try:
            with opener(profile) as page:
                while not pool.should_yield(profile) and not fatal_ip.is_set():
                    try:
                        job = q.get_nowait()
                    except queue.Empty:
                        return                        # hết việc: trả tài khoản cho cuốn khác / chat
                    if not handle(profile, w, page, job):
                        return
        except Exception as e:  # noqa: BLE001 - không mở được Chrome/profile: đổi tài khoản khác
            on_event(f"[{profile}] không mở được Chrome: {str(e)[:160]}")
            with lock:
                broken.add(profile)
            pool.rest(profile, IMAGE, 600, f"không mở được Chrome: {e}")   # các cuốn khác khỏi thử lại liên tục
            pool.trouble(profile, f"không mở được Chrome: {e}")
        finally:
            with lock:
                state["alive"] -= 1
            pool.release(profile)

    threads: list[threading.Thread] = []
    while True:
        if fatal_ip.is_set():
            # Không gửi thêm prompt nào của cuốn này. Các job đã chạy đồng thời sẽ tự kết thúc rồi thoát.
            while True:
                try:
                    cancelled = q.get_nowait()
                except queue.Empty:
                    break
                cancelled.error = f"IP/TM_REJECTED: {fatal_ip_detail['text']}"
                finish(cancelled)
        with lock:
            remaining, alive = state["remaining"], state["alive"]
        if remaining <= 0 and alive == 0:
            break
        queued = q.qsize()
        spawned = False
        if queued > alive:                            # còn việc chưa có người làm: mượn thêm tài khoản
            prefer = [n for n in profiles if n not in broken]
            name = pool.acquire(IMAGE, prefer=prefer)
            if name and name in broken:
                pool.release(name)
            elif name:
                with lock:
                    state["alive"] += 1
                t = threading.Thread(target=worker, args=(name,), daemon=True)
                t.start()
                threads.append(t)
                spawned = True
        if not spawned:
            if alive == 0 and queued:
                usable = [n for n in pool.names if n not in broken]
                if not usable or all(pool._resting(n, IMAGE) for n in usable):
                    break                             # mọi tài khoản nghỉ vẽ / hỏng: để batch chờ rồi thử lại
            pool.wait_change(1.0)
    for t in threads:
        t.join(timeout=5)
    while not q.empty():
        j = q.get()
        j.error = "hết tài khoản còn lượt"      # = generate.QUOTA_MARK: batch sẽ chờ rồi thử lại
    return jobs
