"""Một phiên chat ChatGPT ra NHIỀU ảnh (10 artwork trong một lượt, rồi nhắn tiếp trong cùng phiên lấy 2 ảnh nữa).

Dùng lại phần trang của driver (mở trang, đính ảnh, gửi, phân loại lỗi), chỉ khác cách chờ: chờ tới khi lượt trả
lời xong hẳn (hết nút Stop, hết khung đang vẽ, số ảnh mới đứng yên một lúc) rồi lấy TẤT CẢ ảnh mới theo thứ tự trên
trang. Ảnh trùng (ChatGPT hiện lại cùng ảnh với đường dẫn khác) bị bỏ bằng dấu vân ảnh.
"""
from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..imagegen import driver
from ..imagegen.driver import (FETCH_JS, MIN_SIDE, STATE_JS, QuotaExceeded, TempError, ThirdPartyIPRefused, _eval,
                               classify, generating)

THINK_BTN = 'button[aria-label="Select ChatGPT model"]'
# nhãn mức hiện tại: dòng trạng thái của thanh trượt, vd "Medium, 2 of 3."
THINK_LABEL_JS = """() => { const s = document.querySelector('[role="menu"] [role="status"]');
  return s ? s.innerText.trim() : ''; }"""
# Ảnh lười tải (loading="lazy") nằm ngoài khung nhìn chưa tải -> complete=false, driver tưởng ảnh chưa xong: ép tải hết.
EAGER_JS = """() => { for (const im of document.querySelectorAll('main img, [role="main"] img, article img'))
  if (im.loading === 'lazy') im.loading = 'eager'; }"""
STUCK_S = 240             # số ảnh đứng yên bấy nhiêu giây mà trang vẫn còn dấu "đang vẽ" (kẹt): nhận phần đã có
PER_IMAGE_S = 300        # một ảnh vẽ tối đa ~5 phút
SETTLE_S = 20             # số ảnh mới đứng yên bấy nhiêu giây (không còn vẽ) mới chốt lượt
QUIET_S = 90              # đã có vài ảnh, lượt im hẳn bấy nhiêu giây mà vẫn thiếu: chốt phần đã có


@dataclass
class Turn:
    """Kết quả một lượt: ảnh lấy được (bytes, theo thứ tự) + lỗi làm lượt dừng sớm (nếu có)."""
    images: list[bytes] = field(default_factory=list)
    problem: Exception | None = None
    text: str = ""


def _fingerprint(data: bytes) -> tuple:
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        small = im.convert("RGB").resize((16, 12))
        return tuple(c // 12 for px in small.getdata() for c in px)


def _big_new(st: dict, old: set[str]) -> list[str]:
    seen, out = set(), []
    for im in st.get("pageImgs", []):
        src = im["src"]
        if src in old or src in seen or not im["done"] or max(im["w"], im["h"]) < MIN_SIDE:
            continue
        seen.add(src)
        out.append(src)
    return out


class Session:
    """Một tài khoản, một trang ChatGPT, một cuộc trò chuyện (nhiều lượt)."""

    def __init__(self, page, profile_dir: Path, *, timeout_scale: float = 1.0, clock=time.monotonic):
        self.page = page
        self.w = driver._Worker(Path(profile_dir), "hidden", 420)
        self.scale = timeout_scale
        self.clock = clock
        self.started = False
        self.on_sent = None                          # gọi (link chat) ngay sau khi gửi tin nhắn đầu: để chạy lại lấy ảnh cũ

    def open(self, url: str | None = None) -> None:
        """Mở ChatGPT (url = mở lại một cuộc chat cũ để lấy ảnh đã vẽ và nhắn tiếp trong đó)."""
        if not hasattr(self.page, "_calforge_rate"):
            self.page._calforge_rate = driver.RateWatch(self.page)
        driver.open_home(self.page, url or driver.URL)
        self.w._find(self.page, driver.SEL_PROMPT, 60_000)
        from ..llm import plan
        plan.record(self.page, self.w.profile_dir)    # gói Plus + hạn: cập nhật luôn
        self.thinking = self.set_thinking_high()      # mức thinking cao nhất trước khi prompt
        self.started = True

    def set_thinking_high(self) -> str:
        """Trước khi prompt: đưa thanh "Thinking effort" (nút "Select ChatGPT model" trong ô soạn, thanh trượt 3 nấc
        0-2, thử thật 07/10/2026) lên nấc cao nhất. Trả nhãn mức sau khi đặt ("" nếu giao diện không có / đổi khác -
        không chặn việc vẽ)."""
        page = self.page
        try:
            btn = page.locator(THINK_BTN).first
            if not btn.count() or not btn.is_visible():
                return ""
            btn.click(timeout=8000)
            slider = page.locator('[role="menu"] [role="slider"]').first
            slider.wait_for(state="visible", timeout=5000)
            top = slider.get_attribute("aria-valuemax") or "2"
            if slider.get_attribute("aria-valuenow") != top:
                slider.focus()
                slider.press("End")
                page.wait_for_timeout(600)
            ok = slider.get_attribute("aria-valuenow") == top
            label = page.evaluate(THINK_LABEL_JS) or ""
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return label if ok else ""
        except Exception:  # noqa: BLE001 - giao diện đổi: vẫn vẽ với mức mặc định
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return ""

    def ask_images(self, prompt: str, want: int, attach: list[Path] | None = None) -> Turn:
        """Gửi prompt (+ ảnh đính kèm), chờ lượt xong, trả mọi ảnh mới (tối đa `want`, bỏ ảnh trùng)."""
        if attach:
            self.w._attach(self.page, list(attach))
        before = self.w._send(self.page, prompt)
        if self.on_sent:
            try:
                self.page.wait_for_timeout(1500)
                if "/c/" in (self.page.url or ""):
                    self.on_sent(self.page.url)
            except Exception:  # noqa: BLE001
                pass
        turn = self._collect(before, want)
        return turn

    def chat_url(self) -> str:
        try:
            url = self.page.url or ""
        except Exception:  # noqa: BLE001
            return ""
        return url if "/c/" in url else ""

    def harvest(self, settle_s: float = 12) -> list[bytes]:
        """Mọi ảnh lớn do ChatGPT vẽ trong cuộc chat đang mở, theo thứ tự trên trang (bỏ trùng). Dùng khi mở lại
        chat cũ: ảnh đã vẽ ở lần chạy trước không phải vẽ lại."""
        page, srcs, since = self.page, [], self.clock()
        end = self.clock() + 90
        while self.clock() < end:
            try:
                page.evaluate(EAGER_JS)
            except Exception:  # noqa: BLE001
                pass
            now = _big_new(_eval(page, STATE_JS), set())
            if now != srcs:
                srcs, since = now, self.clock()
            elif srcs and self.clock() - since >= settle_s:
                break
            page.wait_for_timeout(1500)
        return self._download(srcs, 99)

    def _download(self, srcs: list[str], want: int) -> list[bytes]:
        out, seen = [], set()
        for src in srcs:
            try:
                data = base64.b64decode(_eval(self.page, FETCH_JS, src))
                fp = _fingerprint(data)
            except Exception:  # noqa: BLE001 - một ảnh tải hỏng: bỏ ảnh đó, giữ các ảnh khác
                continue
            if fp in seen:
                continue
            seen.add(fp)
            out.append(data)
            if len(out) >= want:
                break
        return out

    def ask_text(self, prompt: str, timeout_s: float = 300) -> str:
        """Hỏi chữ trong cùng cuộc trò chuyện (ChatGPT thấy các ảnh ở trên)."""
        from ..llm import chatgpt_web as cw
        chat = cw._WebChat(self.page, timeout_s)
        chat.rate = getattr(self.page, "_calforge_rate", None)
        try:
            return chat.ask(prompt, "clone_meta")
        except cw.QuotaExceeded as e:                  # lỗi của phần chat -> cùng kiểu lỗi với phần vẽ
            raise QuotaExceeded(str(e)) from e
        except (cw.SendFailed, TimeoutError) as e:
            raise TempError(str(e)) from e

    # ---------------------------------------------------------------- chờ nhiều ảnh
    def _collect(self, before: dict, want: int) -> Turn:
        page = self.page
        start = self.clock()
        deadline = start + (PER_IMAGE_S * max(1, want) + 180) * self.scale
        no_progress = 240 * self.scale
        old = {im["src"] for im in before.get("pageImgs", []) + before.get("imgs", [])}
        srcs: list[str] = []
        last_change, progressed = start, False
        turn = Turn()
        tail = ""
        while self.clock() < deadline:
            try:
                page.evaluate(EAGER_JS)
            except Exception:  # noqa: BLE001
                pass
            st = _eval(page, STATE_JS)
            new_turn = st["assistant"] > before["assistant"]
            tail = st.get("tail", "") if new_turn else ""
            if classify(tail) == "ip_refused":
                turn.problem = ThirdPartyIPRefused(tail[-300:])
                break
            now_srcs = _big_new(st, old)
            # ảnh mới đã nằm trên trang = có lượt trả lời mới, kể cả khi giao diện không tách thành tin nhắn mới
            # (lượt "vẽ tiếp" có khi được gắn vào cụm trả lời cũ - thử thật 07/10/2026)
            if now_srcs and not new_turn:
                new_turn = True
                tail = st.get("tail", "")
            drawing = generating(st) if new_turn else bool(st.get("pending"))
            if now_srcs != srcs:
                srcs, last_change = now_srcs, self.clock()
            busy = bool(st.get("busy")) or drawing
            if new_turn or busy or srcs:
                progressed = True
            elif self.clock() - start > no_progress:
                turn.problem = TempError(f"tab kẹt: ChatGPT chưa phản hồi sau {no_progress:.0f}s")
                break
            if not busy and not srcs:
                limited = self.w._limited(page, start)
                if limited:
                    turn.problem = QuotaExceeded(limited)
                    break
            idle = self.clock() - last_change
            # Đủ ảnh mà trang vẫn giữ dấu "đang vẽ" (khung chờ / nút Stop kẹt sau lượt nhiều ảnh): ảnh đứng yên 60s
            # là xong. Thiếu ảnh mà đứng yên STUCK_S giây: nhận phần đã có, phần thiếu nhắn vẽ tiếp.
            if new_turn and srcs and ((len(srcs) >= want and idle >= 60) or idle >= STUCK_S * self.scale):
                break
            if not busy and new_turn:
                kind = classify(tail)
                if len(srcs) >= want and idle >= SETTLE_S:
                    break
                if srcs and idle >= QUIET_S:                    # lượt ra thiếu ảnh rồi im: nhận phần đã có
                    if kind in ("quota", "refused", "error"):
                        turn.problem = _problem(kind, tail)
                    break
                if not srcs and tail.strip() and idle >= 8:
                    if kind or driver.wants_source(tail) or idle >= 45:
                        turn.problem = (_problem(kind, tail) if kind else
                                        TempError(f"trả lời xong mà không có ảnh: {tail[-160:]!r}"))
                        break
            page.wait_for_timeout(1500)
        else:
            if not srcs:
                turn.problem = TempError(f"quá {deadline - start:.0f}s chưa ra ảnh")
        turn.text = tail
        turn.images = self._download(srcs, want)
        return turn


def _problem(kind: str, tail: str) -> Exception:
    if kind == "quota":
        return QuotaExceeded(tail[-200:])
    if kind in ("refused", "ip_refused"):
        return ThirdPartyIPRefused(tail[-300:])
    return TempError(f"ChatGPT báo lỗi: {tail[-160:]!r}")


def ext_of(data: bytes) -> str:
    return ".webp" if data[8:12] == b"WEBP" else ".jpg" if data[:2] == b"\xff\xd8" else ".png"


def save(data: bytes, out_no_ext: Path) -> Path:
    """Ghi ảnh (đuôi theo định dạng thật), ghi tạm rồi đổi tên để không bao giờ có file dở."""
    for old in out_no_ext.parent.glob(out_no_ext.name + ".*"):
        old.unlink(missing_ok=True)
    dst = out_no_ext.with_suffix(ext_of(data))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dst)
    return dst


def landscape_ok(data: bytes) -> str | None:
    """Artwork / trang lịch phải ngang (4:3 tới 3:2) và đủ lớn."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001
        return "ảnh hỏng"
    if max(w, h) < 1024:
        return f"ảnh nhỏ quá ({w}x{h})"
    if not 1.2 <= w / h <= 1.65:
        return f"sai tỉ lệ ({w}x{h}, cần ngang 4:3)"
    return None
