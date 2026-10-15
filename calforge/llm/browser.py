"""Cách mở Chrome cho các bước tự động (chat chữ + gen ảnh).

Chế độ (config "headless"):
- "hidden" (mặc định): Chrome có cửa sổ thật nhưng đặt ra ngoài màn hình - người dùng không thấy, còn ChatGPT
  thấy như trình duyệt bình thường (headless thật hay bị ChatGPT nghi là bot và chặn).
- False: hiện cửa sổ (để xem máy làm gì / gỡ lỗi).
- True: headless thật của Chrome.
"""
from __future__ import annotations

import threading
from functools import lru_cache

BASE_ARGS = ["--disable-blink-features=AutomationControlled",
             "--hide-crash-restore-bubble",            # không hiện bong bóng "Restore pages?" sau lần tắt ngang
             # cửa sổ bị che/ở ngoài màn hình vẫn vẽ và chạy JS bình thường
             "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
             "--disable-background-timer-throttling"]
HIDDEN_ARGS = ["--window-position=-32000,-32000", "--window-size=1400,950"]


def launch_options(mode) -> dict:
    """Tham số cho launch_persistent_context theo chế độ ở trên."""
    hidden = mode == "hidden" or mode is None
    if hidden:
        _start_keeper()               # canh TRƯỚC khi mở Chrome: cửa sổ mới vừa hiện là ẩn khỏi thanh tác vụ ngay
    return {"headless": mode is True, "args": BASE_ARGS + (HIDDEN_ARGS if hidden else [])}


@lru_cache(maxsize=1)
def _user32():
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    # ctypes defaults to 32-bit integers; every HWND/HANDLE must be declared
    # explicitly or 64-bit Windows can truncate it and silently skip the window.
    signatures = {
        "GetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int]),
        "SetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]),
        "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        "IsWindowVisible": (wintypes.BOOL, [wintypes.HWND]),
        "IsIconic": (wintypes.BOOL, [wintypes.HWND]),
        "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
        "GetWindowPlacement": (wintypes.BOOL, [wintypes.HWND, ctypes.c_void_p]),
        "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]),
        "ShowWindow": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
        "SetWindowPos": (wintypes.BOOL, [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]),
        "GetWindow": (wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
        "GetWindowTextW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
        "EnumWindows": (wintypes.BOOL, [ctypes.c_void_p, wintypes.LPARAM]),
    }
    # 32-bit Windows exports only Get/SetWindowLongW.
    for name, (result, args) in signatures.items():
        if not hasattr(u, name) and "LongPtr" in name:
            setattr(u, name, getattr(u, name.replace("LongPtr", "Long")))
        fn = getattr(u, name)
        fn.restype, fn.argtypes = result, args
    return u


@lru_cache(maxsize=1)
def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                            ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetProcessTimes.restype = wintypes.BOOL
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    return k


_HIDDEN_PIDS = {}
_HIDDEN_PIDS_LOCK = threading.Lock()


def _process_stamp(pid):
    """Process creation time prevents an old registration from matching a reused PID."""
    import ctypes
    from ctypes import wintypes
    k = _kernel32()
    handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if k.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k.CloseHandle(handle)
    return None


def _registered_window(u, hwnd):
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    with _HIDDEN_PIDS_LOCK:
        record = _HIDDEN_PIDS.get(pid.value)
    return bool(record and _process_stamp(pid.value) == record['stamp'])


def register_hidden_context(ctx, mode) -> bool:
    """Register the exact browser PID for each hidden persistent context, including later books."""
    import os
    if os.name != 'nt' or mode not in ('hidden', None):
        return False
    cdp = None
    try:
        cdp = ctx.browser.new_browser_cdp_session()
        processes = cdp.send('SystemInfo.getProcessInfo')['processInfo']
        pid = int(next(p['id'] for p in processes if p['type'] == 'browser'))
        stamp = _process_stamp(pid)
        if stamp is None:
            raise RuntimeError('không đọc được thời điểm tạo tiến trình Chrome')
        with _HIDDEN_PIDS_LOCK:
            record = _HIDDEN_PIDS.setdefault(pid, {'stamp': stamp, 'refs': 0})
            if record['stamp'] != stamp:
                record = _HIDDEN_PIDS[pid] = {'stamp': stamp, 'refs': 0}
            record['refs'] += 1
        def closed(*_):
            with _HIDDEN_PIDS_LOCK:
                record = _HIDDEN_PIDS.get(pid)
                if record and record['stamp'] == stamp:
                    record['refs'] -= 1
                    if record['refs'] <= 0:
                        _HIDDEN_PIDS.pop(pid, None)
        ctx.on('close', closed)
        _start_keeper()
        hide_offscreen_from_taskbar()
        return True
    except Exception as e:
        print(f'[Chrome ẩn] Không đăng ký được PID, dùng chế độ theo tọa độ: {type(e).__name__}: {e}', flush=True)
        return False
    finally:
        if cdp is not None:
            try:
                cdp.detach()
            except Exception:
                pass


GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x00000080, 0x00040000
# Cửa sổ ngầm đặt ở -32000 nhưng Windows báo toạ độ đã chia theo tỉ lệ màn hình (125% -> -26214, 150% -> -21845,
# 175% -> -18724...). Ngưỡng -15000 phủ mọi tỉ lệ tới 200% mà vẫn xa hẳn mọi màn hình thật.
OFFSCREEN_X = -15000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4


def _enum_windows(u, callback):
    """Read physical coordinates even on machines with 250–400% display scaling."""
    import ctypes
    from ctypes import wintypes
    dpi = getattr(u, "SetThreadDpiAwarenessContext", None)
    previous = None
    if dpi is not None:
        dpi.restype = wintypes.HANDLE
        dpi.argtypes = [wintypes.HANDLE]
        previous = dpi(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2, this thread only
    try:
        return u.EnumWindows(callback, 0)
    finally:
        if previous:
            dpi(previous)


def _window_info(u, hwnd):
    """(tên file chương trình, đang thu nhỏ?, toạ độ trái của vị trí THƯỜNG của cửa sổ)."""
    import ctypes
    from ctypes import wintypes

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT), ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT)]

    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    normal_left = wp.rcNormalPosition.left if u.GetWindowPlacement(hwnd, ctypes.byref(wp)) else 0
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    k = _kernel32()
    exe = ""
    hp = k.OpenProcess(0x1000, False, pid.value)              # PROCESS_QUERY_LIMITED_INFORMATION
    if hp:
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            if k.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)):
                exe = buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            k.CloseHandle(hp)
    return exe, bool(u.IsIconic(hwnd)), normal_left


def _is_our_hidden_chrome(u, hwnd) -> bool:
    """Cửa sổ Chrome do tool mở NGẦM: đúng chrome.exe, KHÔNG đang thu nhỏ, và vị trí thường nằm ngoài màn hình.
    Cửa sổ người dùng thu nhỏ cũng bị Windows báo toạ độ -32000 - phải loại ra, nếu không Claude / Chrome / app
    Electron người dùng đang thu nhỏ sẽ bị mất khỏi thanh tác vụ (lỗi gặp thật 03/10/2026)."""
    exe, iconic, normal_left = _window_info(u, hwnd)
    return exe == "chrome.exe" and not iconic and normal_left <= OFFSCREEN_X


def hide_offscreen_from_taskbar() -> int:
    """Bỏ biểu tượng thanh tác vụ của các cửa sổ Chrome do tool mở ngầm (chế độ "hidden" ở trên).

    Đánh dấu cửa sổ là "tool window" và giữ ngoài màn hình. Ưu tiên PID được đăng ký từ phiên Playwright ngầm;
    cửa sổ mới/khôi phục vị trí vẫn bị nhận diện. Các đường gọi cũ chưa đăng ký PID dùng nhận diện theo tọa độ.
    Trả số cửa sổ đã sửa."""
    import os
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    u = _user32()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value.startswith("Chrome_WidgetWin") and u.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            registered = _registered_window(u, hwnd)
            if u.GetWindowRect(hwnd, ctypes.byref(r)) and (registered or r.left <= OFFSCREEN_X):
                ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                needs_style = not ex & WS_EX_TOOLWINDOW or ex & WS_EX_APPWINDOW
                if (registered and (needs_style or r.left > OFFSCREEN_X or u.IsIconic(hwnd))) or (
                        needs_style and _is_our_hidden_chrome(u, hwnd)):
                    found.append((hwnd, ex, registered))
        return True

    _enum_windows(u, each)
    for hwnd, ex, registered in found:
        u.ShowWindow(hwnd, SW_HIDE)                     # đổi kiểu phải ẩn/hiện lại thì thanh tác vụ mới cập nhật
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        if registered:
            # Chrome may restore saved placement or open a popup on another display.
            u.SetWindowPos(hwnd, None, -32000, -32000, 0, 0, 0x0001 | 0x0004 | 0x0010 | 0x0020)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    _start_keeper()
    return len(found)


def restore_user_windows() -> list[str]:
    """Sửa hậu quả lỗi cũ: trả biểu tượng thanh tác vụ cho các cửa sổ ỨNG DỤNG của người dùng (có thanh tiêu đề,
    không có cửa sổ cha, nằm trên màn hình) bị đánh dấu "tool window" nhầm. Không đụng Chrome ngầm của tool và các
    bong bóng / popup nhỏ (không có thanh tiêu đề). Trả về tên các cửa sổ đã trả lại."""
    import os
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    u = _user32()
    WS_CAPTION, GWL_STYLE = 0x00C00000, -16
    fixed = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if not cls.value.startswith("Chrome_WidgetWin") or not u.IsWindowVisible(hwnd) or u.GetWindow(hwnd, 4):
            return True
        ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if not ex & WS_EX_TOOLWINDOW or not (u.GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CAPTION) == WS_CAPTION:
            return True
        _exe, _iconic, normal_left = _window_info(u, hwnd)
        if normal_left <= OFFSCREEN_X:                  # Chrome ngầm của tool: giữ nguyên
            return True
        title = ctypes.create_unicode_buffer(120)
        u.GetWindowTextW(hwnd, title, 120)
        iconic = bool(u.IsIconic(hwnd))
        u.ShowWindow(hwnd, SW_HIDE)
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex & ~WS_EX_TOOLWINDOW)
        u.ShowWindow(hwnd, 7 if iconic else SW_SHOWNOACTIVATE)   # 7 = SW_SHOWMINNOACTIVE: đang thu nhỏ thì để thu nhỏ
        fixed.append(title.value)
        return True

    _enum_windows(u, each)
    return fixed


_KEEPER = {"on": False}
_KEEPER_LOCK = threading.Lock()


def _start_keeper(every_s: float = 0.2) -> None:
    """Chrome có khi tạo cửa sổ chậm hơn lúc tool gọi ẩn, hoặc mở thêm cửa sổ sau: quét lại định kỳ trong suốt tiến
    trình (rất nhẹ - mỗi lần chỉ liệt kê cửa sổ, vài mili-giây) để cửa sổ ngầm nào cũng mất khỏi thanh tác vụ.
    0.2 giây (trước 2 giây): chạy nhiều tài khoản thì Chrome mở liên tục, 2 giây đủ để biểu tượng nháy lên thanh tác
    vụ rồi mới tắt (người dùng báo 14/10/2026)."""
    import threading
    import time
    import os
    if os.name != "nt":
        return
    with _KEEPER_LOCK:
        if _KEEPER["on"]:
            return
        _KEEPER["on"] = True
    try:                                                # sửa luôn cửa sổ người dùng bị lỗi cũ ẩn nhầm (nếu còn)
        restore_user_windows()
    except Exception:  # noqa: BLE001
        pass

    def loop():
        last_error = -1e9
        while True:
            time.sleep(every_s)
            try:
                hide_offscreen_from_taskbar()
            except Exception as e:  # noqa: BLE001
                if time.monotonic() - last_error >= 60:
                    print(f"[Chrome ẩn] Không ẩn được taskbar: {type(e).__name__}: {e}", flush=True)
                    last_error = time.monotonic()
    threading.Thread(target=loop, daemon=True, name="an-chrome").start()


def show_in_taskbar(left_marker: int) -> bool:
    """Trả biểu tượng thanh tác vụ cho ĐÚNG một cửa sổ Chrome: cửa sổ đang nằm ở toạ độ x = left_marker
    (toạ độ đánh dấu riêng, đặt ngay trước khi gọi). Không đụng cửa sổ nào khác."""
    import os
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    u = _user32()
    hit = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        r = wintypes.RECT()
        if (cls.value.startswith("Chrome_WidgetWin") and u.IsWindowVisible(hwnd)
                and u.GetWindowRect(hwnd, ctypes.byref(r)) and r.left == left_marker):
            hit.append(hwnd)
        return True

    _enum_windows(u, each)
    for hwnd in hit:
        ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        u.ShowWindow(hwnd, SW_HIDE)
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return bool(hit)
