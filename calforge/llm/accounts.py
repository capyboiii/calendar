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
    """Thư mục Chrome profile của calforge (riêng, không dùng chung chatgpt-automation): config.get_profiles_dir."""
    return config.get_profiles_dir(cfg)


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
    """Đã đăng nhập ChatGPT chưa. Profile có dấu đăng nhập (MARKER, ghi khi máy XÁC NHẬN đăng nhập thành công)
    thì tin dấu đó; profile cũ (trước khi có dấu) mới lùi về kiểm tra cookie."""
    from .bulk_login import MARKER
    marker = profile_dir / MARKER
    if marker.exists():
        try:
            return bool(json.loads(marker.read_text(encoding="utf-8")).get("email"))
        except (OSError, ValueError):
            return False
    if (profile_dir / ".calforge_new").exists():      # tạo mới bằng tool mà chưa đăng nhập được lần nào
        return False
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

    from . import plan
    from .bulk_login import _emails
    emails = _emails()
    accounts = []
    for d in sorted(pdir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue

        locked = is_profile_locked(d)
        from .pool import DEAD_LABEL, read_dead
        dead = read_dead(d)                               # batch phát hiện tài khoản chết (bị đăng xuất / bị khoá)
        has_session = has_chatgpt_session(d) and not dead
        mtime = d.stat().st_mtime

        accounts.append({
            "name": d.name,
            "path": str(d),
            "is_locked": locked,
            "has_session": has_session,
            "dead": ({"kind": dead["kind"], "label": DEAD_LABEL.get(dead["kind"], dead["kind"]),
                      "at": dead.get("at", "")} if dead else None),
            "use_count": counts.get(d.name, 0),
            "is_last_used": (d.name == last_used),
            "modified_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            "email": emails.get(d.name, ""),
            "plan": plan.read(d),
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
    (acc_dir / ".calforge_new").write_text("", encoding="utf-8")   # chưa đăng nhập: cookie không được tính
    return acc_dir


def close_profile_chrome(udir: Path, wait: float = 8.0) -> None:
    """Tắt các tiến trình Chrome đang dùng đúng thư mục profile này (không đụng Chrome khác)."""
    import os
    import subprocess
    import time
    if os.name != "nt":
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | Where-Object { $_.CommandLine -like "
          f"'*{udir.resolve()}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force "
          "-ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    end = time.time() + wait
    while is_profile_locked(udir) and time.time() < end:
        time.sleep(0.5)


def _processes() -> list[dict]:
    """Mọi tiến trình Windows: ProcessId, ParentProcessId, Name, CommandLine."""
    import os
    import subprocess
    if os.name != "nt":
        return []
    ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,CommandLine "
          "| ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", check=False,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def profile_users(udir: Path, candidates: set[int]) -> set[int]:
    """Trong các PID `candidates` (vd tiến trình của các tác vụ đang chạy), PID nào là "tổ tiên" của Chrome đang
    mở profile này - tức tác vụ nào đang dùng tài khoản. Rỗng = Chrome mồ côi (không tác vụ nào giữ)."""
    procs = _processes()
    parent = {p["ProcessId"]: p.get("ParentProcessId") for p in procs}
    key = str(udir.resolve()).lower()
    owners: set[int] = set()
    for p in procs:
        if (p.get("Name") or "").lower() == "chrome.exe" and key in (p.get("CommandLine") or "").lower():
            pid, seen = p["ProcessId"], set()
            while pid and pid not in seen:
                seen.add(pid)
                if pid in candidates:
                    owners.add(pid)
                    break
                pid = parent.get(pid)
    return owners


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
        close_profile_chrome(acc_dir)          # xoá = bỏ tài khoản: tự đóng Chrome của đúng profile này
    if is_profile_locked(acc_dir):
        raise RuntimeError(f"Tài khoản '{name}' đang mở trong Chrome. Vui lòng đóng cửa sổ Chrome trước khi xóa.")

    # Xóa vĩnh viễn thư mục profile trên ổ đĩa
    shutil.rmtree(acc_dir)
    from .bulk_login import forget_email
    forget_email(name)

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


def wait_until_browser_closed(ctx, udir: Path | None = None, poll: float = 0.5, done=None,
                              timeout: float | None = None) -> bool:
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
    import time as _time
    deadline = _time.time() + timeout if timeout else None
    while not closed.is_set():
        if deadline and _time.time() > deadline:
            return False
        if done is not None:
            try:
                if done():
                    return True           # điều kiện xong (vd đã đăng nhập) -> không cần chờ người dùng đóng
            except Exception:  # noqa: BLE001
                pass
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
        # Chờ bằng Playwright (không dùng closed.wait): API đồng bộ chỉ nhận sự kiện của trình duyệt (đổi trang,
        # tab mới, đóng) khi đang gọi Playwright - ngủ kiểu threading thì ctx.pages / page.url đứng yên mãi.
        try:
            ctx.pages[0].wait_for_timeout(poll * 1000)
        except Exception:  # noqa: BLE001 - trang vừa đóng: vòng sau sẽ thấy
            closed.wait(poll)


LOGIN_TIMEOUT_S = 15 * 60      # để quên cửa sổ đăng nhập: tự đóng, không treo tác vụ mãi
# Cửa sổ đăng nhập phải HIỆN trên màn hình. Chrome nhớ vị trí cửa sổ trong profile; profile vừa chạy batch ngầm
# (đặt ở -32000, ngoài màn hình) mà mở lại không ghi rõ vị trí thì Chrome đặt cửa sổ đăng nhập ra ngoài màn hình.
LOGIN_ARGS = ["--disable-blink-features=AutomationControlled", "--window-position=80,60", "--window-size=1280,900"]


def open_login_browser(name: str, cfg: dict | None = None, on_event=print) -> bool:
    """Mở trình duyệt Chrome giao diện thật để người dùng đăng nhập tài khoản ChatGPT."""
    from playwright.sync_api import sync_playwright

    pdir = get_profiles_dir(cfg)
    udir = pdir / name
    udir.mkdir(parents=True, exist_ok=True)

    if is_profile_locked(udir):
        raise RuntimeError(f"Tài khoản '{name}' đang mở ở một cửa sổ khác. Vui lòng đóng cửa sổ đó trước.")

    on_event(f"🚀 Đang mở trình duyệt Chrome cho tài khoản: {name}")
    on_event("👉 Hãy đăng nhập ChatGPT trên cửa sổ vừa mở.")
    on_event("👉 Đăng nhập xong, cửa sổ sẽ tự đóng.")

    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(udir),
                headless=False,
                channel="chrome",
                viewport=None,
                args=LOGIN_ARGS,
                # bỏ cờ "Chrome đang bị phần mềm tự động điều khiển": Google coi là dấu hiệu bot khi đăng nhập
                ignore_default_args=["--enable-automation", "--no-sandbox"],
            )
        except Exception as e:
            # Fallback nếu channel chrome không tìm thấy
            on_event(f"Thử lại với trình duyệt chromium mặc định ({e})")
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(udir),
                headless=False,
                viewport=None,
                args=LOGIN_ARGS,
                # bỏ cờ "Chrome đang bị phần mềm tự động điều khiển": Google coi là dấu hiệu bot khi đăng nhập
                ignore_default_args=["--enable-automation", "--no-sandbox"],
            )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.bring_to_front()                       # đưa cửa sổ đăng nhập lên trước mặt người dùng
        except Exception:  # noqa: BLE001
            pass
        try:
            page.goto("https://chatgpt.com/", timeout=60_000)
        except Exception as e:
            on_event(f"Lưu ý khi mở trang: {e}")

        from .bulk_login import logged_in_email
        # Tự nhận đăng nhập xong: giao diện có ô chat VÀ máy chủ ChatGPT trả email (khách chưa đăng nhập cũng thấy ô
        # chat, nên không tin riêng giao diện). Ở mọi tab. Người dùng vẫn có thể tự đóng cửa sổ.
        found = {"email": "", "polls": 0}

        def done() -> bool:
            found["email"] = logged_in_email(ctx)
            found["polls"] += 1
            if not found["email"] and found["polls"] % 30 == 0:      # ~1 phút/lần: ghi đang ở trang nào để dò lỗi
                try:
                    urls = ", ".join((pg.url or "")[:60] for pg in ctx.pages)
                except Exception:  # noqa: BLE001
                    urls = "?"
                on_event(f"… vẫn chờ đăng nhập '{name}' (trang: {urls})")
            return bool(found["email"])

        wait_until_browser_closed(ctx, udir, poll=2.0, done=done, timeout=LOGIN_TIMEOUT_S)
        if found["email"]:
            on_event(f"✔ Đã đăng nhập '{name}' ({found['email']}). Đang lưu và đóng cửa sổ...")
            time.sleep(3)                                  # để Chrome kịp ghi cookie phiên xuống đĩa
        try:
            ctx.close()
        except Exception:
            pass

    email = found["email"]
    if not email:
        # người dùng tự đóng trước khi máy kịp nhận (hoặc hết giờ): mở ngầm kiểm tra lại cho chắc
        on_event("… Đang kiểm tra lại phiên đăng nhập...")
        email = verify_session(udir)
    if not email:
        on_event(f"⚠ '{name}' chưa đăng nhập được ChatGPT. Bấm Đăng nhập để thử lại.")
        return False
    from .bulk_login import _emails, _save_email, mark_logged_in
    dup = [n for n, e in _emails().items() if n != name and e.lower() == email.lower() and (pdir / n).is_dir()]
    if dup:
        on_event(f"⚠ Email {email} đã có ở {dup[0]} - '{name}' bị trùng, nên xoá '{name}'.")
    _save_email(name, email)
    mark_logged_in(udir, email)
    (udir / ".calforge_new").unlink(missing_ok=True)
    on_event(f"✔ Đã lưu phiên cho '{name}' ({email}).")
    return True


def verify_session(udir: Path, wait_s: float = 30.0) -> str:
    """Mở ngầm profile (ngoài màn hình), vào ChatGPT, trả email nếu đã đăng nhập thật ('' nếu chưa)."""
    from playwright.sync_api import sync_playwright

    from .browser import BASE_ARGS, HIDDEN_ARGS, hide_offscreen_from_taskbar
    from .bulk_login import logged_in_email
    if is_profile_locked(udir):
        return ""
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(udir), headless=False, channel="chrome", no_viewport=True,
                ignore_default_args=["--enable-automation", "--no-sandbox"], args=BASE_ARGS + HIDDEN_ARGS)
            try:
                hide_offscreen_from_taskbar()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://chatgpt.com/", timeout=60_000)
                end = time.time() + wait_s
                while time.time() < end:
                    email = logged_in_email(ctx)
                    if email:
                        from . import plan
                        plan.record(page, udir)           # vừa xác nhận đăng nhập: đọc luôn gói + hạn
                        return email
                    page.wait_for_timeout(1500)
                return ""
            finally:
                ctx.close()
    except Exception:  # noqa: BLE001
        return ""


