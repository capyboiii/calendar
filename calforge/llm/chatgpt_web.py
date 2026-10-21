"""Hỏi ChatGPT web bằng Playwright, dùng lại Chrome profile đã đăng nhập của chatgpt-automation.

Chỉ lấy câu trả lời CHỮ (bước lên ý tưởng); gen ảnh đi đường riêng. Các selector và cách dán
prompt bằng execCommand('insertText') lấy theo chatgpt_pool.py - chỗ đó đã chạy ổn thực tế
(gõ từng ký tự thì dấu xuống dòng biến thành Enter và gửi dở prompt).

Lưu ý: một Chrome profile chỉ mở được ở MỘT nơi. Đang chạy chatgpt-automation trên acc1 thì
cấu hình tool này dùng tài khoản khác.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

URL = "https://chatgpt.com/"
SEL_PROMPT = ["#prompt-textarea", 'div.ProseMirror[contenteditable="true"]', "textarea[data-id]"]
SEL_SEND = ['button[data-testid="send-button"]', 'button[aria-label="Send" i]',
            'button[aria-label="Gửi" i]', 'button[aria-label*="Send" i]']

# Lượt trả lời của ChatGPT: thử nhiều mốc vì ChatGPT đã đổi DOM (xem ghi chú trong chatgpt_pool.py)
TURNS_JS = r"""() => {
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
  // Work can temporarily hide the composer Stop button between tool calls.
  const work = pick('main .tabular-nums, main [role="status"], main button');
  if (work.some(el => vis(el) && /^(Working for\b|Working[.…]|Đang (?:làm việc|xử lý)(?:\s|[.…]))/i.test((el.innerText || '').trim()))) busy = true;
  const last = a.length ? a[a.length - 1] : null;
  const identity = (el) => {
    if (!el) return '';
    const article = el.closest('article');
    return el.getAttribute('data-message-id') || el.getAttribute('data-chatgpt-search-unit-key') ||
      el.getAttribute('data-turn-id') || (article && (article.getAttribute('data-turn-id') ||
      article.getAttribute('data-testid') || article.id)) || el.id || '';
  };
  return {
    assistant: a.length, user: u.length, busy,
    assistant_id: identity(last), user_id: identity(u[u.length - 1]),
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
    def __init__(self, page, timeout_s: float, settle_s: float = 4.0, no_response_grace_s: float = 30.0,
                 no_start_grace_s: float = 90.0, allow_cloud_browser: bool = False, response_ready=None):
        self.page = page
        self.timeout_s = timeout_s
        self.settle_s = settle_s
        self.no_response_grace_s = no_response_grace_s
        self.no_start_grace_s = no_start_grace_s
        self.allow_cloud_browser = allow_cloud_browser
        self.response_ready = response_ready

    def _continue_cloud_browser(self) -> bool:
        """Only the link-fetch workflow authorizes this specific browser-use prompt.

        Never click an unrelated Continue button (login, purchase, sharing, etc.).
        """
        if not self.allow_cloud_browser:
            return False
        topic = re.compile(r"cloud browser|trình duyệt (?:đám mây|trên đám mây)", re.I)
        # The live Work UI uses an inline permission card, not role=dialog.
        # Choose only the per-chat grant; never "Allow all relevant sites".
        inline = self.page.get_by_role("button", name=re.compile(
            r"^(?:Allow for this chat|Cho phép (?:cho |trong )?(?:cuộc )?(?:trò chuyện|chat) này)(?:\s*[⏎↵])?$", re.I))
        for i in range(inline.count()):
            button = inline.nth(i)
            if not button.is_visible() or not button.is_enabled():
                continue
            card = button.evaluate("""el => {
                for (let p=el.parentElement; p && p!==document.body; p=p.parentElement) {
                    const t=p.innerText || '';
                    if (/cloud browser|trình duyệt (?:đám mây|trên đám mây)/i.test(t))
                        return t.length < 3000 ? t : '';
                }
                return '';
            }""")
            if card and topic.search(card):
                button.click(timeout=4000)
                return True
        action = re.compile(r"^(?:Continue|Allow|Confirm|Use browser|Use cloud browser|"
                            r"Tiếp tục|Cho phép|Xác nhận|Sử dụng trình duyệt)$", re.I)
        dialogs = self.page.locator('[role="dialog"], [role="alertdialog"]').filter(has_text=topic)
        for i in range(dialogs.count()):
            dialog = dialogs.nth(i)
            if not dialog.is_visible():
                continue
            # Do not authorize broader operations that happen to mention a browser.
            text = dialog.inner_text()
            if re.search(r"password|payment|purchase|publish|delete|mật khẩu|thanh toán|mua hàng|xoá|xóa", text, re.I):
                raise SendFailed("Cloud browser đang chờ xác nhận thao tác khác; cần người dùng kiểm tra hộp thoại")
            buttons = dialog.get_by_role("button", name=action)
            if buttons.count() != 1 or not buttons.first.is_enabled():
                raise SendFailed("Cloud browser đang chờ xác nhận; không xác định được nút tiếp tục an toàn")
            buttons.first.click(timeout=4000)
            return True
        return False

    @staticmethod
    def _complete_json(codes: list[str]) -> bool:
        """UI đôi khi giữ nút Stop dù JSON cuối đã hoàn chỉnh; chỉ nhận sớm khi parse được trọn khối JSON."""
        for code in reversed(codes or []):
            try:
                value = json.loads(code)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, (dict, list)):
                return True
        return False

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

    def _limited(self, since: float) -> str | None:
        """Bị giới hạn (429/503 hoặc hộp thoại/banner báo hết lượt/quá tải) kể từ mốc since."""
        from .limits import classify, page_notice

        watch = getattr(self, "rate", None)
        hit = watch.recent(since) if watch else None
        if hit:
            return hit
        notice = page_notice(self.page)
        return notice[-200:] if notice and classify(notice) == "quota" else None

    def _state(self) -> dict:
        from ..imagegen.driver import _eval

        return _eval(self.page, TURNS_JS)

    @staticmethod
    def _new_reply(state: dict, before: dict) -> bool:
        return (state['assistant'] > before['assistant'] or
                bool(state.get('assistant_id') and state.get('assistant_id') != before.get('assistant_id')))

    def _wait_sent(self, before: dict, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            st = self._state()
            if (st["user"] > before["user"] or self._new_reply(st, before) or st.get("busy") or
                    bool(st.get('user_id') and st.get('user_id') != before.get('user_id'))):
                return True
            if time.monotonic() > deadline:
                return False
            self.page.wait_for_timeout(400)

    def _submit(self, box):
        """Resolve the current Send control again after Work/composer rerenders."""
        for sel in SEL_SEND:
            btn = self.page.locator(sel).first
            try:
                if btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=4000)
                    return
            except Exception:
                continue
        box.press('Enter')

    def ask(self, prompt: str, label: str) -> str:
        print(f"   [chat] gửi yêu cầu ({label})...", flush=True)
        before = self._state()
        box = self._find(SEL_PROMPT)
        from .pool import human_pause
        human_pause()                                   # nhịp người thật trước khi gõ + gửi
        box.click()
        box.evaluate(INSERT_JS, prompt)
        self.page.wait_for_timeout(400)
        self._submit(box)

        sent_at = time.monotonic()
        if not self._wait_sent(before, 15):
            if self._limited(sent_at):
                raise QuotaExceeded(f"chặn lúc gửi: {self._limited(sent_at)}")
            print(f"   [chat] tin nhắn chưa đi sau 15s, bấm gửi lại...", flush=True)
            try:
                self._submit(self._find(SEL_PROMPT))
            except Exception:  # noqa: BLE001 - khung nhập bị popup che: để bước dưới báo lỗi
                pass
            if not self._wait_sent(before, 15):
                if self._limited(sent_at):
                    raise QuotaExceeded(f"chặn lúc gửi: {self._limited(sent_at)}")
                raise SendFailed(f"[{label}] Không gửi được tin nhắn")

        # Chờ trả lời xong: có lượt trả lời mới, hết nút Stop, và chữ đứng yên settle_s giây
        started = time.monotonic()
        deadline = started + self.timeout_s
        last_text, stable_since = None, time.monotonic()
        next_beat = started + 15
        saw_reply_activity = False
        stopped_without_reply_since = None
        no_activity_since = started
        browser_confirmations = 0
        while True:
            if self.allow_cloud_browser:
                if browser_confirmations >= 2:
                    self.allow_cloud_browser = False  # bounded: never keep accepting a repeated prompt forever
                elif self._continue_cloud_browser():
                    browser_confirmations += 1
                    print("   [chat] đã xác nhận dùng cloud browser để lấy ảnh từ link; tiếp tục chờ cùng chat", flush=True)
                    stopped_without_reply_since = None
                    no_activity_since = time.monotonic()
                    self.page.wait_for_timeout(700)
                    continue
            st = self._state()
            new_reply = self._new_reply(st, before)
            if st.get("busy") or new_reply:
                saw_reply_activity = True
            reply_changed = st["text"] != last_text
            if new_reply and (not st["busy"] or
                    (self.response_ready is None and self._complete_json(st["codes"]))):
                if reply_changed:
                    last_text, stable_since = st["text"], time.monotonic()
                elif time.monotonic() - stable_since >= self.settle_s and last_text.strip() and (
                        self.response_ready is None or self.response_ready()):
                    break
                elif (self.response_ready is not None and last_text.strip() and
                      time.monotonic() - stable_since >= 120):
                    raise SendFailed(f"[{label}] ChatGPT đã dừng 120s nhưng chưa gửi file/ảnh hợp lệ: {last_text[-200:]}")
            if not (new_reply and st["text"].strip()) and not st["busy"]:
                limited = self._limited(started)
                if limited:
                    raise QuotaExceeded(limited)
            now = time.monotonic()
            has_reply_text = new_reply and bool(st["text"].strip())
            if has_reply_text:
                from .limits import classify, page_notice

                notice = page_notice(self.page)
                kind = classify(_notice_text(st) + " " + notice)
                if kind == "quota":
                    raise QuotaExceeded((notice or st["text"])[-200:])
                if kind in ("error", "refused", "ip_refused") and not st.get("codes"):
                    raise SendFailed(f"[{label}] ChatGPT trả {kind}: {st['text'][-200:]}")
            elif not st.get("busy"):
                from .limits import classify, page_notice

                notice = page_notice(self.page)
                kind = classify(notice)
                if kind == "quota":
                    raise QuotaExceeded(notice[-200:])
                if kind in ("error", "refused", "ip_refused"):
                    raise SendFailed(f"[{label}] ChatGPT hiện thông báo {kind}: {notice[-200:]}")
            if saw_reply_activity and not st.get("busy") and not has_reply_text:
                stopped_without_reply_since = stopped_without_reply_since or now
                if now - stopped_without_reply_since >= self.no_response_grace_s:
                    from .limits import classify, page_notice

                    notice = page_notice(self.page)
                    kind = classify((st.get("text") or "") + " " + notice)
                    detail = (notice or st.get("text") or "không đọc được nội dung phản hồi")[-200:]
                    raise SendFailed(f"[{label}] ChatGPT đã dừng nhưng không có câu trả lời đọc được"
                                     f" ({kind or 'lỗi giao diện'}: {detail})")
            else:
                stopped_without_reply_since = None
            if not saw_reply_activity and now - no_activity_since >= self.no_start_grace_s:
                raise SendFailed(f"[{label}] ChatGPT không bắt đầu trả lời sau {self.no_start_grace_s:.0f}s")
            if now >= next_beat:  # nhịp báo mỗi 15s để biết còn đang chờ, không phải treo
                state = "ChatGPT đang soạn" if st.get("busy") else "chờ ChatGPT phản hồi"
                print(f"   [chat] {state}... ({now - started:.0f}s)", flush=True)
                next_beat = now + 15
            if now > deadline:
                raise TimeoutError(f"[{label}] ChatGPT chưa trả lời xong sau {self.timeout_s:.0f}s")
            self.page.wait_for_timeout(700)
        print(f"   [chat] nhận trả lời sau {time.monotonic() - started:.0f}s", flush=True)

        if not st["codes"]:
            from .limits import classify, page_notice

            notice = page_notice(self.page)
            if classify(_notice_text(st) + " " + notice) == "quota":
                raise QuotaExceeded((notice or st["text"])[-160:])
        # innerText không còn dấu ``` của markdown -> dựng lại khối code để bộ bóc JSON nhận ra
        blocks = "".join(f"\n```json\n{code.strip()}\n```\n" for code in st["codes"])
        return st["text"] + ("\n" + blocks if blocks else "")


NOTICE_MAX_CHARS = 600


def _notice_text(st: dict) -> str:
    """Lượt trả lời chỉ được coi là thông báo của ChatGPT khi nó ngắn và không phải JSON / khối code. Câu trả lời thật
    (concept, listing...) hay chứa chữ trùng câu báo lỗi ("Overloaded Supply Cart", "wait until spring"...) - dò cả
    bài sẽ đuổi nhầm tài khoản đang trả lời bình thường."""
    text = (st.get("text") or "").strip()
    if st.get("codes") or len(text) > NOTICE_MAX_CHARS or "{" in text or '":' in text:
        return ""
    return text


class QuotaExceeded(RuntimeError):
    """Tài khoản hết lượt chat -> chuyển sang tài khoản kế tiếp."""


class SendFailed(RuntimeError):
    """Tin nhắn không gửi đi được (popup che, nút gửi không bật...) -> thử tài khoản kế tiếp."""


class NoAccountLeft(RuntimeError):
    """Mọi tài khoản đều hết lượt / không mở được: batch nên CHỜ rồi thử lại, không coi là hỏng."""


MAX_REQUEST_ACCOUNTS = 5


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
        self.failed: set[str] = set()                        # không mở được trong phiên này
        # một prompt lỗi phản hồi chỉ thử mỗi tài khoản 1 lần, và không quá MAX_REQUEST_ACCOUNTS tài khoản (có 40 tài
        # khoản cũng không đem một prompt hỏng đi thử cả 40)
        self.max_request_accounts = min(len(self.order), MAX_REQUEST_ACCOUNTS)

    def _open_next(self, exclude: set[str] | None = None) -> None:
        """Mượn tài khoản kế tiếp qua bộ điều phối (không đụng tài khoản đang vẽ / đang nghỉ chat) và mở chat.
        Mọi tài khoản đang bận vẽ thì CHỜ (luồng vẽ sẽ nhường chỗ sau ảnh đang vẽ); chỉ báo NoAccountLeft khi
        mọi tài khoản đều hết lượt chat hoặc không mở được."""
        from .pool import CHAT, get_pool
        exclude = exclude or set()
        self.close()
        pool = get_pool()
        self._waiting_pool = pool
        while True:
            self._waiting_pool = pool
            usable = [n for n in self.order if n not in self.failed and n not in exclude]
            # Register the complete eligible set so the earlier queue job can
            # claim any available chat account, not just the last profile probed.
            name = pool.acquire(CHAT, prefer=usable, eligible=usable) if usable else None
            for name in ([name] if name is not None else []):
                self.order.remove(name)
                self.order.append(name)                     # lần sau bắt đầu từ tài khoản khác
                udir = self.backend.profiles_dir / name
                self.profile = name                         # đã mượn: mở Chrome hỏng thì close() phải TRẢ lại
                try:
                    from .browser import launch_options, register_hidden_context
                    with pool.launch_gate():
                        self.ctx = self.pw.chromium.launch_persistent_context(
                            user_data_dir=str(udir), channel="chrome", viewport={"width": 1400, "height": 950},
                            **launch_options(self.backend.headless))
                    register_hidden_context(self.ctx, self.backend.headless)
                    page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
                    if self.backend.headless in ("hidden", None):
                        from .browser import hide_offscreen_from_taskbar
                        hide_offscreen_from_taskbar()        # Chrome ngầm: không hiện biểu tượng dưới thanh tác vụ
                    from ..imagegen.driver import open_home
                    open_home(page, URL)                  # mạng chập / chuyển hướng: chờ + thử lại
                    self.chat = _WebChat(page, self.backend.timeout_s)
                    from .limits import RateWatch
                    self.chat.rate = RateWatch(page)        # 429/503 từ máy chủ ChatGPT -> hết lượt
                    self.chat._find(SEL_PROMPT, 60_000)
                    self.backend.mark_used(name)
                    print(f"[chat] dùng tài khoản {name}")
                    return
                except Exception as e:  # noqa: BLE001 - chưa đăng nhập / profile hỏng: không thử lại trong phiên
                    self.failed.add(name)
                    kind = ""
                    try:                                   # trang hiện màn hình đăng nhập / báo bị khoá = tài khoản chết
                        from ..imagegen.driver import account_state
                        pg = self.ctx.pages[0] if self.ctx and self.ctx.pages else None
                        kind = account_state(pg)[0] if pg is not None else ""
                    except Exception:  # noqa: BLE001
                        kind = ""
                    if kind:
                        pool.drop(name, kind, str(e))
                        print(f"[chat] ✘ TÀI KHOẢN CHẾT: {name} "
                              + ("bị khoá - cần thay tài khoản" if kind == "banned" else
                                 "bị đăng xuất, giao diện là màn hình đăng nhập - cần đăng nhập lại")
                              + ". Đã bỏ khỏi batch")
                    else:
                        print(f"[chat] bỏ qua {name}: {str(e)[:120]}")
                        pool.rest(name, CHAT, 600, f"không mở được Chrome: {e}")
                        pool.trouble(name, f"chat không mở được: {e}")
                    self.close()
            if name is not None and name in self.failed:
                continue
            usable = [n for n in self.order if n not in self.failed and n not in exclude]
            if not usable or all(pool._resting(n, CHAT) for n in usable):
                if exclude:
                    raise RuntimeError("Không còn tài khoản chưa thử cho yêu cầu chat này")
                raise NoAccountLeft("Không còn tài khoản ChatGPT nào dùng được cho bước chat (hết lượt)")
            pool.wait_change(5)                             # tài khoản đang bận vẽ: chờ luồng vẽ nhường

    def ask(self, prompt: str, label: str) -> str:
        response_failed: set[str] = set()
        while True:
            if self.chat is None:
                self._open_next(response_failed)
            try:
                return self.chat.ask(prompt, label)
            except QuotaExceeded as e:
                print(f"[chat] {self.profile} hết lượt ({str(e)[:80]}) - chuyển tài khoản")
                from .pool import CHAT, get_pool
                pool = get_pool()
                pool.rest(self.profile, CHAT, pool.rest_s, str(e))
                self.close()
            except SendFailed as e:
                response_failed.add(self.profile)
                print(f"[chat] {self.profile} không gửi được tin nhắn ({str(e)[:80]}) - chuyển tài khoản")
                self._drop_if_dead(str(e))
                self.close()
                if len(response_failed) >= self.max_request_accounts:
                    raise RuntimeError(f"[{label}] Tất cả {self.max_request_accounts} tài khoản đều không trả lời đọc được") from e
            except TimeoutError as e:
                # Tab có thể đã đổi DOM / mất lượt trả lời sau khi nút Stop biến mất. Đừng làm hỏng cả batch:
                # đóng tab và gửi lại nguyên prompt trên tài khoản kế tiếp.
                response_failed.add(self.profile)
                print(f"[chat] {self.profile} chờ phản hồi quá lâu ({str(e)[:80]}) - chuyển tài khoản")
                self._drop_if_dead(str(e))
                self.close()
                if len(response_failed) >= self.max_request_accounts:
                    raise RuntimeError(f"[{label}] Tất cả {self.max_request_accounts} tài khoản đều timeout phản hồi") from e
            except Exception as e:  # noqa: BLE001 - Chrome sập giữa chừng, ô chat bị che, trang đổi DOM...
                # Lỗi của tab / tài khoản đang dùng, không phải của prompt: đóng tab, hỏi lại trên tài khoản kế tiếp.
                response_failed.add(self.profile)
                print(f"[chat] {self.profile} lỗi trang ({type(e).__name__}: {str(e).splitlines()[0][:80] if str(e) else ''})"
                      " - chuyển tài khoản")
                self._drop_if_dead(str(e))
                self.close()
                if len(response_failed) >= self.max_request_accounts:
                    raise RuntimeError(f"[{label}] Tất cả {self.max_request_accounts} tài khoản đều lỗi trang: "
                                       f"{type(e).__name__}: {str(e)[:120]}") from e

    def _drop_if_dead(self, why: str) -> None:
        """Tab vừa lỗi: nếu trang đang hiện màn hình đăng nhập / báo bị khoá thì tài khoản CHẾT -> bỏ hẳn."""
        page = getattr(self.chat, "page", None)
        if page is None or self.profile is None:
            return
        try:
            from ..imagegen.driver import account_state
            kind = account_state(page)[0]
        except Exception:  # noqa: BLE001
            return
        if kind:
            from .pool import get_pool
            get_pool().drop(self.profile, kind, why)
            print(f"[chat] ✘ TÀI KHOẢN CHẾT: {self.profile} "
                  + ("bị khoá - cần thay tài khoản" if kind == "banned" else
                     "bị đăng xuất, giao diện là màn hình đăng nhập - cần đăng nhập lại") + ". Đã bỏ khỏi batch")

    def close(self) -> None:
        from .pool import CHAT, get_pool
        pending = getattr(self, '_waiting_pool', None)
        if pending is not None:
            pending.cancel_wait(CHAT)
            self._waiting_pool = None
        if self.ctx is not None:
            try:
                self.ctx.close()
            except Exception:  # noqa: BLE001
                pass
        if self.profile is not None:
            from .pool import get_pool
            get_pool().release(self.profile)
        self.ctx = self.chat = self.profile = None


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
        last = self._read_state().get("last")
        if last in self.profiles:
            i = self.profiles.index(last) + 1
            return self.profiles[i:] + self.profiles[:i]
        return list(self.profiles)

    def mark_used(self, name: str) -> None:
        if not self.state_file:
            return
        st = self._read_state()
        st["last"] = name
        counts = st.get("count") if isinstance(st.get("count"), dict) else {}
        counts[name] = int(counts.get(name, 0) or 0) + 1
        st["count"] = counts
        try:                                   # file xoay vòng chỉ để rải đều tài khoản: không ghi được cũng không sao
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(st, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _read_state(self) -> dict:
        """File xoay vòng tài khoản; hỏng / cụt thì coi như chưa có (không làm sập bước lên ý tưởng)."""
        if not self.state_file:
            return {}
        try:
            st = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return st if isinstance(st, dict) else {}

    @contextmanager
    def session(self, workdir: Path):
        from playwright.sync_api import sync_playwright

        from .pool import get_pool
        with sync_playwright() as pw, get_pool().reserve_chat(1):   # giữ 1 chỗ chat khi đang lên ý tưởng
            chat = _RotatingChat(self, pw)
            try:
                yield chat
            finally:
                chat.close()
