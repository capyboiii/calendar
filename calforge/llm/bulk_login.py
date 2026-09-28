"""Đăng nhập hàng loạt tài khoản ChatGPT (theo cách của chatgpt-automation/server.py).

Dán nhiều dòng `email | mật khẩu | mã 2FA`, mỗi tài khoản một cửa sổ Chrome riêng, chạy song song, tự điền
form (calforge/llm/auth_login.py) và tự sinh mã 2FA.

AN TOÀN
- Mật khẩu và seed 2FA chỉ nằm trong RAM của lượt chạy: không ghi đĩa, không ghi log, không trả về API; dùng xong
  là xoá khỏi bộ nhớ (creds.clear()).
- Chỉ lưu EMAIL của từng profile (data/account_emails.json). Email đã có tài khoản thì BỎ QUA, không đăng nhập
  lại (muốn đăng nhập lại một tài khoản: nút "Đăng nhập lại" của tài khoản đó).
- Chrome chạy ngầm (cửa sổ ngoài màn hình); gặp captcha / "xác minh bạn là người" thì DỪNG và đưa đúng cửa sổ đó
  ra màn hình để người dùng tự xác minh (không vượt rào).
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path

from . import auth_login
from .accounts import get_profiles_dir, is_profile_locked

ROOT = Path(__file__).resolve().parents[2]
EMAILS_FILE = ROOT / "data" / "account_emails.json"      # profile -> email (KHÔNG có mật khẩu)

EMAIL_RE = re.compile(r"^[^@\s|]+@[^@\s|]+\.[^@\s|]+$")

BULK: dict = {"active": False, "items": [], "started": 0.0, "boxes": {}}
_LOCK = threading.Lock()

# Đã đăng nhập hay chưa: đo trên giao diện (xem chatgpt-automation/server.py LOGIN_STATE_JS) - còn nút
# "Log in"/"Sign up" là chưa đăng nhập; cookie hay /backend-api/me đều không tin được.
LOGIN_STATE_JS = """() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const txts = [...document.querySelectorAll('button,a')].filter(vis)
        .map((b) => (b.innerText || '').trim().toLowerCase());
    const hasLoginBtn = txts.some((t) => /^(log in|sign up|đăng nhập|đăng ký)/.test(t));
    const appReady = !!document.querySelector('#prompt-textarea, div.ProseMirror[contenteditable="true"]')
        || document.querySelectorAll('a[href^="/c/"]').length > 0;
    return {hasLoginBtn, appReady};
}"""


def check_logged_in(page) -> bool:
    try:
        if "auth.openai.com" in (page.url or "").lower():
            return False
        st = page.evaluate(LOGIN_STATE_JS)
        return bool(st.get("appReady")) and not st.get("hasLoginBtn")
    except Exception:  # noqa: BLE001
        return False


def _emails() -> dict:
    """profile -> email của các tài khoản calforge đã đăng nhập hàng loạt."""
    try:
        return json.loads(EMAILS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_email(name: str, email: str) -> None:
    with _LOCK:
        data = _emails()
        data[name] = email
        EMAILS_FILE.parent.mkdir(parents=True, exist_ok=True)
        EMAILS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _next_name(taken: set[str]) -> str:
    i = 1
    while f"acc{i}" in taken:
        i += 1
    return f"acc{i}"


def _tile(idx: int, total: int) -> list[str]:
    """Xếp các cửa sổ thành lưới để lúc cần xác minh người thật biết cửa sổ nào là của ai."""
    if total <= 1:
        return ["--window-size=1400,950", "--window-position=40,20"]
    cols = math.ceil(math.sqrt(total))
    rows = math.ceil(total / cols)
    w, h = max(560, 1920 // cols), max(460, 1040 // rows)
    return [f"--window-size={w},{h}", f"--window-position={(idx % cols) * w},{(idx // cols) * h}"]


def _reveal(ctx, page, tile: list[str]) -> None:
    """Đưa cửa sổ đang ẩn ngoài màn hình về đúng ô lưới của nó và đưa lên trước."""
    try:
        w, h = (int(v) for v in next(t for t in tile if t.startswith("--window-size=")).split("=")[1].split(","))
        x, y = (int(v) for v in next(t for t in tile if t.startswith("--window-position=")).split("=")[1].split(","))
        cdp = ctx.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "normal"}})
        # toạ độ đánh dấu riêng để tìm đúng cửa sổ này trả lại biểu tượng thanh tác vụ, rồi mới đưa ra màn hình
        marker = -31000 - (win % 900)
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"left": marker, "top": -31000}})
        from .browser import show_in_taskbar
        show_in_taskbar(marker)
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"left": x, "top": y, "width": w, "height": h}})
        page.bring_to_front()
    except Exception:  # noqa: BLE001 - không đưa ra được thì thôi, người dùng vẫn thấy trạng thái trên UI
        pass


def _open_chatgpt(ctx, page, tries: int = 3):
    """Mở chatgpt.com, tab kẹt thì bỏ mở tab mới (nhiều Chrome cùng lúc hay có tab tải mãi)."""
    last = None
    for i in range(tries):
        try:
            page.goto("https://chatgpt.com/", wait_until="commit", timeout=45_000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:  # noqa: BLE001
                pass
            return page
        except Exception as e:  # noqa: BLE001
            last = e
            if i + 1 < tries:
                try:
                    fresh = ctx.new_page()
                    page.close()
                    page = fresh
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(3)
    raise last


def _one(idx: int, name: str, creds: dict, total: int, sem: threading.Semaphore, pdir: Path) -> None:
    from playwright.sync_api import sync_playwright

    item = BULK["items"][idx]
    with sem:
        if not BULK["active"]:
            item.update(status="failed", error="Đã huỷ")
            creds.clear()
            return
        item["status"] = "running"
        udir = pdir / name
        udir.mkdir(parents=True, exist_ok=True)
        box = {"phase": "starting", "needs_human": False, "error": None}
        BULK["boxes"][name] = box
        try:
            if is_profile_locked(udir):
                raise RuntimeError("Profile đang được Chrome khác mở (đang chạy batch?)")
            tile = _tile(idx, total)
            size = next(t for t in tile if t.startswith("--window-size="))
            with sync_playwright() as pw:
                # Chạy ngầm: cửa sổ nằm ngoài màn hình (headless thật bị ChatGPT/Cloudflare chặn đăng nhập).
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(udir), headless=False, channel="chrome", no_viewport=True,
                    args=["--disable-blink-features=AutomationControlled",
                          "--disable-features=CalculateNativeWinOcclusion",
                          "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                          "--disable-background-timer-throttling", "--no-first-run",
                          "--no-default-browser-check", size, "--window-position=-32000,-32000"])
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                from .browser import hide_offscreen_from_taskbar
                hide_offscreen_from_taskbar()               # không hiện biểu tượng dưới thanh tác vụ
                page = _open_chatgpt(ctx, page)
                shown = {"v": False}

                def check(pg):
                    # Trang đòi người thật xác minh (captcha): đưa đúng cửa sổ này ra màn hình cho người dùng làm.
                    if box.get("needs_human") and not shown["v"]:
                        _reveal(ctx, pg, tile)
                        shown["v"] = True
                    return check_logged_in(pg)

                ok = auth_login.auto_login(page, creds, box, check)
                if ok:
                    _save_email(name, item["email"])
                    item["status"] = "done"
                else:
                    item["status"] = "needs_human" if box.get("needs_human") else "failed"
                    item["error"] = box.get("error") or "Cần bạn xác minh thủ công"
                ctx.close()
        except Exception as e:  # noqa: BLE001
            item.update(status="failed", error=str(e)[:200])
        finally:
            creds.clear()                     # xoá mật khẩu khỏi RAM ngay khi dùng xong
            item["phase"] = box.get("phase")
            BULK["boxes"].pop(name, None)


def _worker(jobs: list[tuple[str, dict]], pdir: Path, parallel: int, stagger: float) -> None:
    total = len(jobs)
    sem = threading.Semaphore(parallel if parallel > 0 else total)
    threads = []
    for idx, (name, creds) in enumerate(jobs):
        t = threading.Thread(target=_one, args=(idx, name, creds, total, sem, pdir), daemon=True)
        t.start()
        threads.append(t)
        jobs[idx] = (name, {})                # bỏ tham chiếu mật khẩu ở danh sách gốc
        if stagger and idx + 1 < total:
            time.sleep(stagger)
    for t in threads:
        t.join()
    BULK["active"] = False
    BULK["boxes"].clear()


def start(raw: str, cfg: dict | None = None, parallel: int = 0, stagger: float = 2.0) -> dict:
    """Bắt đầu một lượt. raw: nhiều dòng `email | mật khẩu | mã 2FA`. Trả về danh sách (không có mật khẩu)."""
    if BULK["active"]:
        raise RuntimeError("Đang chạy một lượt đăng nhập hàng loạt khác.")
    pdir = get_profiles_dir(cfg)
    by_email = {e.lower(): n for n, e in _emails().items()}
    taken = {d.name for d in pdir.iterdir() if d.is_dir()} if pdir.exists() else set()
    jobs, items, seen, bad = [], [], {}, []
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        if not line.strip():
            continue
        creds = auth_login.parse_creds(line)
        if not creds or not EMAIL_RE.match(creds["email"]):
            bad.append(f"dòng {lineno}: sai định dạng (email | mật khẩu | mã 2FA)")
            continue
        if not auth_login.check_totp_seed(creds["totp"]):
            bad.append(f"dòng {lineno}: mã 2FA sai")
            continue
        email = creds["email"].lower()
        if email in seen:
            bad.append(f"dòng {lineno}: trùng email với dòng {seen[email]}")
            continue
        seen[email] = lineno
        if email in by_email:                 # email đã có tài khoản -> không đăng nhập lại
            bad.append(f"dòng {lineno}: {creds['email']} đã có ở {by_email[email]}")
            creds.clear()
            continue
        name = _next_name(taken)
        taken.add(name)
        jobs.append((name, creds))
        items.append({"profile": name, "email": creds["email"], "status": "pending", "error": None})
    if not jobs:
        raise ValueError("Không có tài khoản mới nào để đăng nhập: " + "; ".join(bad) if bad
                         else "Chưa dán tài khoản nào.")
    BULK.update(active=True, items=items, started=time.time(), boxes={})
    threading.Thread(target=_worker, args=(jobs, pdir, parallel, stagger), daemon=True).start()
    return {"started": len(jobs), "skipped": bad, "items": items}


def status() -> dict:
    boxes = BULK.get("boxes", {})
    items = []
    for it in BULK["items"]:
        b = boxes.get(it["profile"]) or {}
        items.append({**it, "phase": b.get("phase") or it.get("phase"), "needs_human": bool(b.get("needs_human"))})
    return {"active": BULK["active"], "items": items}
