"""Quản lý và đăng nhập các Chrome profile ChatGPT."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from .. import config

ROOT = Path(__file__).resolve().parents[2]


def get_profiles_dir(cfg: dict | None = None) -> Path:
    """Xác định thư mục chứa các Chrome profile."""
    if cfg is None:
        cfg = config.load()
    llm = cfg.get("llm") or {}
    pdir = llm.get("profiles_dir")
    if pdir and Path(pdir).exists():
        return Path(pdir)

    auto_dir = cfg.get("chatgpt_automation_dir")
    if auto_dir:
        p = Path(auto_dir) / ".chrome-profiles"
        if p.exists():
            return p

    # Mặc định tạo thư mục .chrome-profiles ở gốc workspace
    local = ROOT / ".chrome-profiles"
    local.mkdir(parents=True, exist_ok=True)
    return local


def is_profile_locked(profile_dir: Path) -> bool:
    """Kiểm tra xem profile có đang được một tiến trình Chrome nào mở không."""
    lock_file = profile_dir / "lockfile"
    if not lock_file.exists():
        return False
    try:
        # Trên Windows, nếu file đang bị Chrome giữ lock thì không thể mở ghi
        with open(lock_file, "r+"):
            return False
    except (IOError, PermissionError):
        return True


def has_chatgpt_session(profile_dir: Path) -> bool:
    """Kiểm tra xem profile đã từng lưu cookie/session duyệt web chưa."""
    indicators = [
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
        profile_dir / "Default" / "Local Storage",
        profile_dir / "Default" / "IndexedDB",
    ]
    return any(p.exists() and (p.is_dir() or p.stat().st_size > 0) for p in indicators)


def list_accounts(cfg: dict | None = None) -> list[dict[str, Any]]:
    """Liệt kê danh sách tài khoản cùng thông tin trạng thái."""
    if cfg is None:
        cfg = config.load()
    pdir = get_profiles_dir(cfg)
    if not pdir.exists():
        return []

    # Đọc thông tin xoay vòng từ .llm_rotation.json
    rot_file = Path(cfg["projects_dir"]) / ".llm_rotation.json"
    rot_data = {}
    if rot_file.exists():
        try:
            rot_data = json.loads(rot_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    last_used = rot_data.get("last")
    counts = rot_data.get("count", {})

    accounts = []
    for d in sorted(pdir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue

        locked = is_profile_locked(d)
        has_session = has_chatgpt_session(d)
        mtime = d.stat().st_mtime

        accounts.append({
            "name": d.name,
            "path": str(d),
            "is_locked": locked,
            "has_session": has_session,
            "use_count": counts.get(d.name, 0),
            "is_last_used": (d.name == last_used),
            "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
        })

    return accounts


def create_account(name: str, cfg: dict | None = None) -> Path:
    """Tạo một profile tài khoản mới."""
    name = name.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
        raise ValueError("Tên tài khoản chỉ được chứa chữ cái, số, gạch dưới (_) hoặc gạch ngang (-).")

    pdir = get_profiles_dir(cfg)
    acc_dir = pdir / name
    if acc_dir.exists():
        raise FileExistsError(f"Tài khoản '{name}' đã tồn tại trong {pdir}")

    acc_dir.mkdir(parents=True, exist_ok=True)
    return acc_dir


def delete_account(name: str, cfg: dict | None = None) -> bool:
    """Xóa tài khoản và toàn bộ thư mục profile trên ổ đĩa."""
    import shutil

    name = name.strip()
    if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
        raise ValueError("Tên tài khoản không hợp lệ.")

    pdir = get_profiles_dir(cfg)
    acc_dir = (pdir / name).resolve()

    # An toàn: đường dẫn phải nằm trong pdir
    if not str(acc_dir).startswith(str(pdir.resolve())):
        raise ValueError("Đường dẫn không hợp lệ.")

    if not acc_dir.exists():
        raise FileNotFoundError(f"Không tìm thấy tài khoản '{name}' trong {pdir}")

    if is_profile_locked(acc_dir):
        raise RuntimeError(f"Tài khoản '{name}' đang mở trong Chrome. Vui lòng đóng cửa sổ Chrome trước khi xóa.")

    # Xóa vĩnh viễn thư mục profile trên ổ đĩa
    shutil.rmtree(acc_dir)

    # Dọn dẹp trong .llm_rotation.json nếu có
    if cfg is None:
        cfg = config.load()
    rot_file = Path(cfg["projects_dir"]) / ".llm_rotation.json"
    if rot_file.exists():
        try:
            rot_data = json.loads(rot_file.read_text(encoding="utf-8"))
            changed = False
            if rot_data.get("last") == name:
                rot_data.pop("last", None)
                changed = True
            if "count" in rot_data and name in rot_data["count"]:
                rot_data["count"].pop(name, None)
                changed = True
            if changed:
                rot_file.write_text(json.dumps(rot_data, indent=2), encoding="utf-8")
        except Exception:
            pass

    return True


def wait_until_browser_closed(ctx, udir: Path | None = None, poll: float = 0.5) -> None:
    """Chờ tới khi người dùng đóng cửa sổ Chrome, rồi trả về (không bao giờ ném lỗi).

    Dùng đồng thời hai tín hiệu vì mỗi cái hụt ở một tình huống:
      1. Playwright: sự kiện "close", danh sách pages rỗng, hoặc đọc pages ném lỗi
         (đóng bình thường bằng nút X). Nhưng khi Chrome bị tắt đột ngột, sync API có thể
         KHÔNG cập nhật kịp -> treo.
      2. Khóa profile ở mức hệ điều hành: Chrome chạy thì giữ khóa, thoát thì nhả. Đây là
         tín hiệu chắc chắn cho cả đóng thường lẫn đóng đột ngột. Chờ khóa xuất hiện (browser
         lên) rồi biến mất (browser đóng).
    """
    closed = threading.Event()
    try:
        ctx.on("close", lambda: closed.set())
    except Exception:
        pass
    became_locked = False
    while not closed.is_set():
        try:
            if not ctx.pages:
                return
        except Exception:
            return
        if udir is not None:
            if is_profile_locked(udir):
                became_locked = True
            elif became_locked:      # đã từng mở, giờ khóa nhả -> đã đóng
                return
        closed.wait(poll)


def open_login_browser(name: str, cfg: dict | None = None, on_event=print) -> None:
    """Mở trình duyệt Chrome giao diện thật để người dùng đăng nhập tài khoản ChatGPT."""
    from playwright.sync_api import sync_playwright

    pdir = get_profiles_dir(cfg)
    udir = pdir / name
    udir.mkdir(parents=True, exist_ok=True)

    if is_profile_locked(udir):
        raise RuntimeError(f"Tài khoản '{name}' đang mở ở một cửa sổ khác. Vui lòng đóng cửa sổ đó trước.")

    on_event(f"🚀 Đang mở trình duyệt Chrome cho tài khoản: {name}")
    on_event("👉 Hãy đăng nhập ChatGPT trên cửa sổ vừa mở.")
    on_event("👉 Khi đăng nhập xong, hãy ĐÓNG CỬA SỔ TRÌNH DUYỆT để hoàn tất lưu phiên.")

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(udir),
                headless=False,
                channel="chrome",
                viewport=None,
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as e:
            # Fallback nếu channel chrome không tìm thấy
            on_event(f"Thử lại với trình duyệt chromium mặc định ({e})")
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(udir),
                headless=False,
                viewport=None,
                args=["--disable-blink-features=AutomationControlled"],
            )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://chatgpt.com/", timeout=60_000)
        except Exception as e:
            on_event(f"Lưu ý khi mở trang: {e}")

        wait_until_browser_closed(ctx, udir)   # chờ người dùng đóng cửa sổ (không ném lỗi)

        try:
            ctx.close()
        except Exception:
            pass

    # Báo trung thực theo trạng thái THẬT của profile, không báo thành công vô điều kiện.
    if has_chatgpt_session(udir):
        on_event(f"✔ Đã lưu phiên cho '{name}'. Kiểm tra lại bằng: python -m calforge accounts")
    else:
        on_event(f"⚠ Đã đóng trình duyệt nhưng '{name}' chưa có phiên đăng nhập. "
                 f"Hãy mở lại và đăng nhập ChatGPT trước khi đóng cửa sổ.")
