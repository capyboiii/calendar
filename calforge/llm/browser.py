"""Cách mở Chrome cho các bước tự động (chat chữ + gen ảnh).

Chế độ (config "headless"):
- "hidden" (mặc định): Chrome có cửa sổ thật nhưng đặt ra ngoài màn hình - người dùng không thấy, còn ChatGPT
  thấy như trình duyệt bình thường (headless thật hay bị ChatGPT nghi là bot và chặn).
- False: hiện cửa sổ (để xem máy làm gì / gỡ lỗi).
- True: headless thật của Chrome.
"""
from __future__ import annotations

BASE_ARGS = ["--disable-blink-features=AutomationControlled",
             "--hide-crash-restore-bubble",            # không hiện bong bóng "Restore pages?" sau lần tắt ngang
             # cửa sổ bị che/ở ngoài màn hình vẫn vẽ và chạy JS bình thường
             "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
             "--disable-background-timer-throttling"]
HIDDEN_ARGS = ["--window-position=-32000,-32000", "--window-size=1400,950"]


def launch_options(mode) -> dict:
    """Tham số cho launch_persistent_context theo chế độ ở trên."""
    hidden = mode == "hidden" or mode is None
    return {"headless": mode is True, "args": BASE_ARGS + (HIDDEN_ARGS if hidden else [])}


def _user32():
    import ctypes
    from ctypes import wintypes

    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    return u


GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x00000080, 0x00040000
# Cửa sổ ngầm đặt ở -32000 nhưng Windows báo toạ độ đã chia theo tỉ lệ màn hình (125% -> -26214, 150% -> -21845,
# 175% -> -18724...). Ngưỡng -15000 phủ mọi tỉ lệ tới 200% mà vẫn xa hẳn mọi màn hình thật.
OFFSCREEN_X = -15000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4


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
    k = ctypes.WinDLL("kernel32", use_last_error=True)
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

    Đánh dấu cửa sổ là "tool window" (loại cửa sổ Windows không đưa lên thanh tác vụ). Chỉ đụng cửa sổ chrome.exe
    đang mở (không thu nhỏ) mà vị trí thường nằm ngoài màn hình (<= OFFSCREEN_X), tức Chrome do tool mở ngầm - cửa sổ
    người dùng (kể cả đang thu nhỏ, kể cả app khác dùng nền Chrome như Claude) không bị ảnh hưởng. Trả về số cửa sổ
    đã ẩn."""
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
            if u.GetWindowRect(hwnd, ctypes.byref(r)) and r.left <= OFFSCREEN_X:
                ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                if not ex & WS_EX_TOOLWINDOW and _is_our_hidden_chrome(u, hwnd):
                    found.append((hwnd, ex))
        return True

    u.EnumWindows(each, 0)
    for hwnd, ex in found:
        u.ShowWindow(hwnd, SW_HIDE)                     # đổi kiểu phải ẩn/hiện lại thì thanh tác vụ mới cập nhật
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
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

    u.EnumWindows(each, 0)
    return fixed


_KEEPER = {"on": False}


def _start_keeper(every_s: float = 2.0) -> None:
    """Chrome có khi tạo cửa sổ chậm hơn lúc tool gọi ẩn, hoặc mở thêm cửa sổ sau: quét lại định kỳ trong suốt tiến
    trình (rất nhẹ) để cửa sổ ngầm nào cũng mất khỏi thanh tác vụ."""
    import threading
    import time
    if _KEEPER["on"]:
        return
    _KEEPER["on"] = True
    try:                                                # sửa luôn cửa sổ người dùng bị lỗi cũ ẩn nhầm (nếu còn)
        restore_user_windows()
    except Exception:  # noqa: BLE001
        pass

    def loop():
        while True:
            time.sleep(every_s)
            try:
                hide_offscreen_from_taskbar()
            except Exception:  # noqa: BLE001
                pass
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

    u.EnumWindows(each, 0)
    for hwnd in hit:
        ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        u.ShowWindow(hwnd, SW_HIDE)
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return bool(hit)
