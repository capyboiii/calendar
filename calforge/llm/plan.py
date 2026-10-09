"""Gói ChatGPT của từng tài khoản (Free / Plus / Pro...) và ngày hết hạn.

Đọc y như trang ChatGPT tự hỏi để biết hiện nút "Upgrade": /api/auth/session rồi /backend-api/accounts/check, chạy
NGAY TRONG trang ChatGPT đã đăng nhập của profile. Mã đăng nhập chỉ nằm trong trang, không trả về Python, không lưu,
không ghi log; chỉ lưu tên gói + ngày hết hạn vào .calforge_plan.json trong profile.
Đây là lời gọi nội bộ (OpenAI không công bố): đọc không được thì để "không rõ", không đoán. Thử thật 06/10/2026.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PLAN_FILE = ".calforge_plan.json"
CHECK_URL = "/backend-api/accounts/check/v4-2023-04-27"

PLAN_JS = r"""async (url) => {
  try {
    const s = await (await fetch('/api/auth/session', {credentials: 'include'})).json();
    if (!s || !s.accessToken) return {logged_in: false};
    const r = await fetch(url, {headers: {Authorization: 'Bearer ' + s.accessToken}, credentials: 'include'});
    if (!r.ok) return {logged_in: true, status: r.status};
    const j = await r.json();
    const items = Object.values(j.accounts || {}).map(a => ({
      structure: a.account && a.account.structure,
      plan: a.account && a.account.plan_type,
      active: !!(a.entitlement && a.entitlement.has_active_subscription),
      expires: (a.entitlement && a.entitlement.expires_at) || null,
    }));
    return {logged_in: true, status: r.status, items};
  } catch (e) { return {error: String(e).slice(0, 120)}; }
}"""

LABEL = {"free": "Free", "plus": "Plus", "pro": "Pro", "team": "Team", "enterprise": "Enterprise", "edu": "Edu",
         "go": "Go", "k12": "K12"}
# Gói vẽ ảnh mạnh như Plus. Tài khoản K12 / Edu (có nút Trò chuyện / Công việc) = workspace trả phí: tính như Plus.
NOT_PAID = {"", "free", "guest", "go"}


def is_paid(info: dict | None) -> bool:
    """Gói trả phí còn hạn (Plus / Pro / K12 / Edu / Team / Enterprise...)."""
    return bool(info) and str(info.get("plan") or "").lower() not in NOT_PAID         and info.get("active", True) is not False and not info.get("expired")


def parse(raw: dict | None) -> dict | None:
    """Kết quả PLAN_JS -> {"plan", "label", "active", "expires"}; None nếu không đọc được (giữ dấu cũ)."""
    if not isinstance(raw, dict) or not raw.get("logged_in") or not raw.get("items"):
        return None
    items = raw["items"]
    # Một đăng nhập có thể có nhiều không gian (cá nhân Free + workspace K12/Edu trả phí): lấy gói trả phí đang
    # hoạt động nếu có, không thì không gian cá nhân như trước
    # (workspace K12/Edu: has_active_subscription luôn false, không có ngày hết hạn - vẫn là gói dùng được)
    paid = [i for i in items if str(i.get("plan") or "").lower() not in NOT_PAID
            and (i.get("active") or i.get("structure") == "workspace")]
    paid.sort(key=lambda i: i.get("structure") != "personal")    # cá nhân trả phí (Plus) trước workspace
    item = paid[0] if paid else next((i for i in items if i.get("structure") == "personal"), items[0])
    if paid and item.get("structure") == "workspace":
        item = {**item, "active": True}
    plan = str(item.get("plan") or "").lower()
    if not plan:
        return None
    expires = item.get("expires") or ""
    return {"plan": plan, "label": LABEL.get(plan, plan.title()), "active": bool(item.get("active")),
            "expires": str(expires)[:25]}


def read_from_page(page) -> dict | None:
    try:
        return parse(page.evaluate(PLAN_JS, CHECK_URL))
    except Exception:  # noqa: BLE001 - trang đóng / lời gọi đổi: không ảnh hưởng việc chính
        return None


def save(profile_dir: Path, info: dict) -> None:
    data = {**info, "checked_at": time.strftime("%Y-%m-%d %H:%M")}
    f = Path(profile_dir) / PLAN_FILE
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def record(page, profile_dir: Path) -> dict | None:
    """Đọc + lưu gói của profile đang mở (gọi kèm lúc tool đã mở ChatGPT để làm việc khác). Không bao giờ lỗi."""
    info = read_from_page(page)
    if info:
        try:
            save(profile_dir, info)
        except OSError:
            pass
    return info


def days_left(expires: str, now: datetime | None = None) -> int | None:
    try:
        end = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (end - (now or datetime.now(timezone.utc))).days


def read(profile_dir: Path, now: datetime | None = None) -> dict | None:
    """Gói đã lưu của profile, kèm days_left và expired (gói trả phí đã quá ngày hết hạn)."""
    try:
        d = json.loads((Path(profile_dir) / PLAN_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not d.get("plan"):
        return None
    left = days_left(d.get("expires") or "", now)
    d["days_left"] = left
    d["expires_date"] = (d.get("expires") or "")[:10]
    # gói trả phí mà đã quá ngày hết hạn (lần kiểm tra sau sẽ thấy rớt về Free)
    d["expired"] = d["plan"] != "free" and left is not None and left < 0
    return d


# ------------------------------------------------------------------ kiểm tra tất cả tài khoản (nút trên giao diện)
CHECK = {"active": False, "done": 0, "total": 0, "skipped": [], "at": ""}
_LOCK = threading.Lock()


def _check_one(udir: Path) -> dict | None:
    from playwright.sync_api import sync_playwright

    from .browser import BASE_ARGS, HIDDEN_ARGS, hide_offscreen_from_taskbar
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(udir), headless=False, channel="chrome", no_viewport=True,
            ignore_default_args=["--enable-automation", "--no-sandbox"], args=BASE_ARGS + HIDDEN_ARGS)
        try:
            hide_offscreen_from_taskbar()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=60_000)
            for _ in range(6):                    # trang mới tải: chờ phiên sẵn sàng
                page.wait_for_timeout(2000)
                info = record(page, udir)
                if info:
                    return info
            return None
        finally:
            ctx.close()


def check_all(cfg: dict, check_one=_check_one) -> dict:
    """Mở ngầm lần lượt từng tài khoản đã đăng nhập, đọc gói. Bỏ qua tài khoản đang mở (batch đang dùng) hoặc đã chết
    - batch tự cập nhật gói của tài khoản nó đang dùng."""
    from .accounts import get_profiles_dir, has_chatgpt_session, is_profile_locked
    from .pool import read_dead
    pdir = get_profiles_dir(cfg)
    dirs = [d for d in sorted(pdir.iterdir()) if d.is_dir() and not d.name.startswith(".")] if pdir.exists() else []
    with _LOCK:
        CHECK.update(active=True, done=0, total=len(dirs), skipped=[], at="")
    try:
        for d in dirs:
            why = ("đang mở" if is_profile_locked(d) else "đã chết" if read_dead(d)
                   else "chưa đăng nhập" if not has_chatgpt_session(d) else "")
            if not why:
                try:
                    if not check_one(d):
                        why = "không đọc được gói"
                except Exception:  # noqa: BLE001
                    why = "không mở được Chrome"
            with _LOCK:
                CHECK["done"] += 1
                if why:
                    CHECK["skipped"].append(f"{d.name}: {why}")
    finally:
        with _LOCK:
            CHECK.update(active=False, at=time.strftime("%Y-%m-%d %H:%M"))
    return status()


def start_check(cfg: dict) -> bool:
    with _LOCK:
        if CHECK["active"]:
            return False
        CHECK["active"] = True
    threading.Thread(target=check_all, args=(cfg,), daemon=True, name="plan-check").start()
    return True


def status() -> dict:
    with _LOCK:
        return {**CHECK, "skipped": list(CHECK["skipped"])}
