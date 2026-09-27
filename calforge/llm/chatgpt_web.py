"""Hỏi ChatGPT web bằng Playwright, dùng lại Chrome profile đã đăng nhập của chatgpt-automation.

Chỉ lấy câu trả lời CHỮ (bước lên ý tưởng); gen ảnh đi đường riêng. Các selector và cách dán
prompt bằng execCommand('insertText') lấy theo chatgpt_pool.py - chỗ đó đã chạy ổn thực tế
(gõ từng ký tự thì dấu xuống dòng biến thành Enter và gửi dở prompt).

Lưu ý: một Chrome profile chỉ mở được ở MỘT nơi. Đang chạy chatgpt-automation trên acc1 thì
cấu hình tool này dùng tài khoản khác.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

URL = "https://chatgpt.com/"
SEL_PROMPT = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', "textarea[data-id]"]
SEL_SEND = ['button[data-testid="send-button"]', 'button[aria-label*="Send" i]']

# Lượt trả lời của ChatGPT: thử nhiều mốc vì ChatGPT đã đổi DOM (xem ghi chú trong chatgpt_pool.py)
TURNS_JS = """() => {
  const pick = (sel) => Array.from(document.querySelectorAll(sel));
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
                   'button[aria-label*="Stop" i]', '[data-testid="stop-generating"]']) {
    if (vis(document.querySelector(s))) { busy = true; break; }
  }
  const last = a.length ? a[a.length - 1] : null;
  return {
    assistant: a.length, user: u.length, busy,
    text: last ? last.innerText : '',
    codes: last ? Array.from(last.querySelectorAll('pre code')).map((c) => c.textContent) : [],
  };
}"""

INSERT_JS = """(el, txt) => {
  el.focus();
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  sel.removeAllRanges(); sel.addRange(range);
  document.execCommand('insertText', false, txt);
  el.dispatchEvent(new Event('input', {bubbles: true}));
}"""


class _WebChat:
    def __init__(self, page, timeout_s: float, settle_s: float = 4.0):
        self.page = page
        self.timeout_s = timeout_s
        self.settle_s = settle_s

    def _find(self, selectors, timeout_ms=30_000):
        per = max(1500, timeout_ms // len(selectors))
        for sel in selectors:
            loc = self.page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=per)
                return loc
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError(f"Không thấy phần tử nào khớp {selectors} (ChatGPT đổi giao diện?)")

    def _state(self) -> dict:
        from ..imagegen.driver import _eval

        return _eval(self.page, TURNS_JS)

    def _wait_sent(self, before: dict, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            st = self._state()
            if st["user"] > before["user"] or st["assistant"] > before["assistant"] or st.get("busy"):
                return True
            if time.monotonic() > deadline:
                return False
            self.page.wait_for_timeout(400)

    def ask(self, prompt: str, label: str) -> str:
        print(f"   [chat] gửi yêu cầu ({label})...", flush=True)
        before = self._state()
        box = self._find(SEL_PROMPT)
        box.click()
        box.evaluate(INSERT_JS, prompt)
        self.page.wait_for_timeout(400)
        sent = False
        for sel in SEL_SEND:
            btn = self.page.locator(sel).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=4000)
                    sent = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not sent:
            box.press("Enter")

        if not self._wait_sent(before, 15):
            print(f"   [chat] tin nhắn chưa đi sau 15s, bấm gửi lại...", flush=True)
            try:
                box.press("Enter")
            except Exception:  # noqa: BLE001 - khung nhập bị popup che: để bước dưới báo lỗi
                pass
            if not self._wait_sent(before, 15):
                raise SendFailed(f"[{label}] Không gửi được tin nhắn")

        # Chờ trả lời xong: có lượt trả lời mới, hết nút Stop, và chữ đứng yên settle_s giây
        started = time.monotonic()
        deadline = started + self.timeout_s
        last_text, stable_since = None, time.monotonic()
        next_beat = started + 15
        while True:
            st = self._state()
            if st["assistant"] > before["assistant"] and not st["busy"]:
                if st["text"] != last_text:
                    last_text, stable_since = st["text"], time.monotonic()
                elif time.monotonic() - stable_since >= self.settle_s and last_text.strip():
                    break
            now = time.monotonic()
            if now >= next_beat:  # nhịp báo mỗi 15s để biết còn đang chờ, không phải treo
                state = "ChatGPT đang soạn" if st.get("busy") else "chờ ChatGPT phản hồi"
                print(f"   [chat] {state}... ({now - started:.0f}s)", flush=True)
                next_beat = now + 15
            if now > deadline:
                raise TimeoutError(f"[{label}] ChatGPT chưa trả lời xong sau {self.timeout_s:.0f}s")
            self.page.wait_for_timeout(700)
        print(f"   [chat] nhận trả lời sau {time.monotonic() - started:.0f}s", flush=True)

        if not st["codes"]:
            from ..imagegen.driver import classify

            if classify(st["text"]) == "quota":
                raise QuotaExceeded(st["text"][-160:])
        # innerText không còn dấu ``` của markdown -> dựng lại khối code để bộ bóc JSON nhận ra
        blocks = "".join(f"\n```json\n{code.strip()}\n```\n" for code in st["codes"])
        return st["text"] + ("\n" + blocks if blocks else "")


class QuotaExceeded(RuntimeError):
    """Tài khoản hết lượt chat -> chuyển sang tài khoản kế tiếp."""


class SendFailed(RuntimeError):
    """Tin nhắn không gửi đi được (popup che, nút gửi không bật...) -> thử tài khoản kế tiếp."""


class _RotatingChat:
    """Phiên chat xoay vòng tài khoản: tài khoản đang dùng hết lượt / không mở được thì tự sang
    tài khoản kế tiếp và hỏi lại câu đó (prompt của pipeline tự đủ ngữ cảnh nên hỏi lại được)."""

    def __init__(self, backend: "ChatGPTWebBackend", pw):
        self.backend = backend
        self.pw = pw
        self.order = backend.rotation_order()
        self.ctx = None
        self.chat: _WebChat | None = None
        self.profile = None

    def _open_next(self) -> None:
        self.close()
        while self.order:
            name = self.order.pop(0)
            udir = self.backend.profiles_dir / name
            try:
                self.ctx = self.pw.chromium.launch_persistent_context(
                    user_data_dir=str(udir), headless=self.backend.headless, channel="chrome",
                    viewport={"width": 1400, "height": 950}, args=["--disable-blink-features=AutomationControlled"])
                page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
                self.chat = _WebChat(page, self.backend.timeout_s)
                self.chat._find(SEL_PROMPT, 60_000)
                self.profile = name
                self.backend.mark_used(name)
                print(f"[chat] dùng tài khoản {name}")
                return
            except Exception as e:  # noqa: BLE001 - profile đang mở ở nơi khác / chưa đăng nhập
                print(f"[chat] bỏ qua {name}: {str(e)[:120]}")
                self.close()
        raise RuntimeError("Không còn tài khoản ChatGPT nào dùng được cho bước chat")

    def ask(self, prompt: str, label: str) -> str:
        while True:
            if self.chat is None:
                self._open_next()
            try:
                return self.chat.ask(prompt, label)
            except QuotaExceeded as e:
                print(f"[chat] {self.profile} hết lượt ({str(e)[:80]}) - chuyển tài khoản")
                self.close()
            except SendFailed as e:
                print(f"[chat] {self.profile} không gửi được tin nhắn ({str(e)[:80]}) - chuyển tài khoản")
                self.close()

    def close(self) -> None:
        if self.ctx is not None:
            try:
                self.ctx.close()
            except Exception:  # noqa: BLE001
                pass
        self.ctx = self.chat = None


class ChatGPTWebBackend:
    def __init__(self, profiles_dir: str, profiles: list[str] | str, headless: bool = False,
                 timeout_s: float = 600, state_file: Path | None = None):
        self.profiles_dir = Path(profiles_dir)
        wanted = [profiles] if isinstance(profiles, str) else list(profiles or [])
        if not wanted:  # mặc định: mọi profile, acc1 để cuối
            wanted = sorted((p.name for p in self.profiles_dir.iterdir() if p.is_dir()),
                            key=lambda n: (n == "acc1", n))
        self.profiles = [p for p in wanted if (self.profiles_dir / p).is_dir()]
        if not self.profiles:
            raise FileNotFoundError(f"Không có Chrome profile nào trong {self.profiles_dir}")
        self.headless = headless
        self.timeout_s = timeout_s
        self.state_file = state_file

    def rotation_order(self) -> list[str]:
        """Bắt đầu từ tài khoản ngay sau tài khoản dùng lần trước, để việc rải đều."""
        last = None
        if self.state_file and self.state_file.exists():
            last = json.loads(self.state_file.read_text(encoding="utf-8")).get("last")
        if last in self.profiles:
            i = self.profiles.index(last) + 1
            return self.profiles[i:] + self.profiles[:i]
        return list(self.profiles)

    def mark_used(self, name: str) -> None:
        if not self.state_file:
            return
        st = json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file.exists() else {}
        st["last"] = name
        st.setdefault("count", {})[name] = st.get("count", {}).get(name, 0) + 1
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(st, indent=2), encoding="utf-8")

    @contextmanager
    def session(self, workdir: Path):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            chat = _RotatingChat(self, pw)
            try:
                yield chat
            finally:
                chat.close()
