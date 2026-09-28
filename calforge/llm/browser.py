"""Cách mở Chrome cho các bước tự động (chat chữ + gen ảnh).

Chế độ (config "headless"):
- "hidden" (mặc định): Chrome có cửa sổ thật nhưng đặt ra ngoài màn hình - người dùng không thấy, còn ChatGPT
  thấy như trình duyệt bình thường (headless thật hay bị ChatGPT nghi là bot và chặn).
- False: hiện cửa sổ (để xem máy làm gì / gỡ lỗi).
- True: headless thật của Chrome.
"""
from __future__ import annotations

BASE_ARGS = ["--disable-blink-features=AutomationControlled",
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
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4


def hide_offscreen_from_taskbar() -> int:
    """Bỏ biểu tượng thanh tác vụ của MỌI cửa sổ Chrome đang nằm ngoài màn hình (chế độ "hidden" ở trên).

    Đánh dấu cửa sổ là "tool window" (loại cửa sổ Windows không đưa lên thanh tác vụ). Chỉ đụng cửa sổ có toạ độ
    <= -30000, tức Chrome do tool mở ngầm - Chrome người dùng đang dùng không bị ảnh hưởng. Trả về số cửa sổ đã ẩn."""
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
        if cls.value.startswith("Chrome_WidgetWin"):
            r = wintypes.RECT()
            if u.IsWindowVisible(hwnd) and u.GetWindowRect(hwnd, ctypes.byref(r)) and r.left <= -30000:
                ex = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
                if not ex & WS_EX_TOOLWINDOW:
                    found.append((hwnd, ex))
        return True

    u.EnumWindows(each, 0)
    for hwnd, ex in found:
        u.ShowWindow(hwnd, SW_HIDE)                     # đổi kiểu phải ẩn/hiện lại thì thanh tác vụ mới cập nhật
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    return len(found)


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
