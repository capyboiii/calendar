"""Mở CalForge Studio như một app: không cửa sổ đen, trang làm lịch hiện trong cửa sổ riêng (Chrome --app).

Biểu tượng "CalForge Studio" (bộ cài) chạy:  python\\pythonw.exe -m calforge.app
- Tool đang chạy sẵn: chỉ mở lại cửa sổ, không chạy tool thứ hai.
- Đóng cửa sổ KHÔNG tắt tool (lịch vẫn làm tiếp); tắt hẳn bằng nút "Tắt tool" trên trang.
- Log của máy chủ ghi vào logs/app.log (pythonw không có màn hình để in).
"""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME_PATHS = [Path(os.environ.get(v, "")) / "Google/Chrome/Application/chrome.exe"
                for v in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]


def _chrome() -> Path | None:
    return next((p for p in CHROME_PATHS if p.is_file()), None)


def _message(text: str) -> None:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, "CalForge Studio", 0x40)


def _open_window(url: str) -> None:
    chrome = _chrome()
    if chrome:
        subprocess.Popen([str(chrome), f"--app={url}", "--new-window"])
    else:
        webbrowser.open(url)


def main() -> None:
    os.chdir(ROOT)
    if sys.stdout is None:                                  # pythonw: ghi log ra file
        (ROOT / "logs").mkdir(exist_ok=True)
        log = open(ROOT / "logs" / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    if os.name == "nt" and not _chrome():
        _message("Máy chưa có Google Chrome - tool cần Chrome để dùng ChatGPT.\n\n"
                 "Trang tải Chrome sẽ mở ra. Cài xong thì bấm lại biểu tượng CalForge Studio.")
        webbrowser.open("https://www.google.com/chrome/")
        return
    from .ui.server import run_server
    run_server(opener=_open_window)


if __name__ == "__main__":
    main()
