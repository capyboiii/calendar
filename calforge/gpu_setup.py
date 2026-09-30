"""Cài bộ làm nét ảnh Real-ESRGAN cho máy có card NVIDIA (chạy lúc cài app, hoặc tay: python -m calforge.gpu_setup).

Bộ cài không chứa sẵn torch (~2.5 GB) cho nhẹ. Máy có card NVIDIA thì tải thêm torch (bản CUDA) + spandrel vào
thư mục <app>/gpu (nằm ngoài <app>/python nên cài bản mới đè lên KHÔNG phải tải lại), và trọng số mô hình vào
<app>/models. Máy không có card NVIDIA: thoát ngay, app vẫn chạy và làm nét bằng cách thường (Lanczos).
Lỗi mạng hay cài hỏng không chặn app - lần cài/chạy sau thử lại.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPU_DIR = ROOT / "gpu"
TORCH_INDEX = "https://download.pytorch.org/whl/cu121"


def has_nvidia() -> bool:
    if shutil.which("nvidia-smi"):
        return True
    return (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe").exists()


def ready() -> bool:
    """torch dùng được CUDA, có spandrel và trọng số mô hình."""
    from .imagegen.upscale import WEIGHTS
    code = "import torch, spandrel; raise SystemExit(0 if torch.cuda.is_available() else 1)"
    try:
        ok = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=180).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return ok and WEIGHTS.exists()


def _pip(*args: str) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
           "--upgrade", "--target", str(GPU_DIR), *args]
    return subprocess.run(cmd).returncode == 0


def main() -> int:
    if not has_nvidia():
        print("Máy không có card NVIDIA - bỏ qua bộ làm nét ảnh GPU (app vẫn chạy bình thường).")
        return 0
    if ready():
        print("Bộ làm nét ảnh Real-ESRGAN (GPU) đã sẵn sàng.")
        return 0
    print("=" * 64)
    print(" Máy có card NVIDIA: đang tải bộ làm nét ảnh Real-ESRGAN (khoảng 2.5 GB).")
    print(" Lần đầu mất 5-30 phút tuỳ mạng. ĐỪNG TẮT cửa sổ này.")
    print("=" * 64)
    GPU_DIR.mkdir(exist_ok=True)
    ok = _pip("torch", "torchvision", "--index-url", TORCH_INDEX)
    # spandrel cài --no-deps: không để pip kéo thêm một bản torch CPU từ PyPI đè lên bản CUDA
    ok = ok and _pip("--no-deps", "spandrel", "safetensors", "einops")
    if ok:
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            from fetch_assets import fetch_upscaler
            fetch_upscaler(False)
        except Exception as e:  # noqa: BLE001
            print(f"Không tải được trọng số mô hình: {e}")
            ok = False
    if ok and ready():
        print("✔ Xong: app sẽ làm nét ảnh bằng card NVIDIA.")
        return 0
    print("⚠ Chưa cài được bộ làm nét GPU (kiểm tra mạng). App vẫn chạy, làm nét bằng cách thường;")
    print("  cài lại bản mới hoặc chạy: python\\python.exe -m calforge.gpu_setup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
