"""Upscale ảnh AI lên đủ khổ in bằng Real-ESRGAN (x4plus) chạy GPU, chia ô để vừa VRAM 6GB.

Ảnh ChatGPT ~1536x1024 mà trang in cần phủ 3375x2625 (sau khi cắt còn cần ~3937x2625) -> phóng
~2.6 lần. Lanczos chỉ làm ảnh to ra mà mềm; Real-ESRGAN dựng lại nét. Chạy x4 rồi thu về đúng cỡ.

Không có GPU / spandrel / trọng số thì lùi về Lanczos + unsharp và báo rõ trong kết quả.
"""
from __future__ import annotations

import threading
import time

import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
WEIGHTS = ROOT / "models" / "RealESRGAN_x4plus.pth"
WEIGHTS_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"


@lru_cache(maxsize=1)
def _model():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import torch
            from spandrel import ModelLoader
        if not WEIGHTS.exists() or not torch.cuda.is_available():
            return None
        model = ModelLoader().load_from_file(str(WEIGHTS)).eval().cuda().half()
        return model
    except Exception:  # noqa: BLE001
        return None


def engine() -> str:
    return "Real-ESRGAN x4plus (GPU)" if _model() is not None else "Lanczos (dự phòng)"


_GPU_LOCK = threading.Lock()
TILE_YIELD_S = 0.008


def _esrgan_x4(img: Image.Image, tile: int = 384, pad: int = 16) -> Image.Image:
    """tile=384 là mức nhanh nhất trên 6GB VRAM: ô to hơn tràn sang RAM chung, chậm hơn nhiều."""
    import torch

    model = _model()
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    # Ghi thẳng từng ô ra uint8 (cùng phép làm tròn như trước) thay vì giữ cả ảnh 6144x4096 dạng float32.
    out = np.empty((h * 4, w * 4, 3), dtype=np.uint8)
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
    with _GPU_LOCK, torch.no_grad():          # nhiều cuốn song song: GPU 6GB chỉ chạy 1 ảnh một lúc
        for y in range(0, h, tile):
            for x in range(0, w, tile):
                y0, x0 = max(0, y - pad), max(0, x - pad)
                y1, x1 = min(h, y + tile + pad), min(w, x + tile + pad)
                patch = t[:, :, y0:y1, x0:x1].cuda().half()
                res = model(patch).float().clamp(0, 1)[0].permute(1, 2, 0)
                oy, ox = (y - y0) * 4, (x - x0) * 4
                th, tw = min(tile, h - y) * 4, min(tile, w - x) * 4
                out[y * 4:y * 4 + th, x * 4:x * 4 + tw] = (
                    (res[oy:oy + th, ox:ox + tw] * 255 + 0.5).to(torch.uint8).cpu().numpy())
                time.sleep(TILE_YIELD_S)        # nhường GPU cho màn hình + Chrome giữa các ô: máy không giật
    return Image.fromarray(out, "RGB")


def upscale_to(src: Path, dst: Path, min_w: int, min_h: int, texture_mix: float = 0.3) -> dict:
    """Phóng ảnh sao cho phủ được min_w x min_h (giữ tỉ lệ). Ảnh đã đủ lớn thì chỉ chép.

    texture_mix: tỉ lệ trộn bản Lanczos vào bản Real-ESRGAN. ESRGAN làm nét nhưng xoá vân giấy
    màu nước (trông "nhựa"); trộn ~30% Lanczos giữ lại vân giấy mà vẫn nét.
    """
    img = Image.open(src)
    has_alpha = img.mode in ("RGBA", "LA")
    img = img.convert("RGBA" if has_alpha else "RGB")
    scale = max(min_w / img.width, min_h / img.height)
    target = (round(img.width * scale), round(img.height * scale))
    if scale <= 1.0:
        if Path(dst).suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(dst, quality=95, subsampling=0)
        else:
            img.save(dst)
        return {"engine": "không cần phóng", "scale": 1.0}
    used = engine()
    big = None
    if _model() is not None and not has_alpha:
        try:
            big = _esrgan_x4(img).resize(target, Image.LANCZOS)
            if texture_mix > 0:
                soft = img.resize(target, Image.LANCZOS)
                big = Image.blend(big, soft, texture_mix)
                used += f", trộn {texture_mix:.0%} Lanczos giữ vân giấy"
        except Exception as e:  # noqa: BLE001 - GPU hết bộ nhớ / driver lỗi: làm nét cách thường, không hỏng cuốn
            big = None
            used = f"Lanczos (GPU lỗi: {type(e).__name__})"
    if big is None:                                     # không có GPU / ảnh có nền trong suốt / GPU vừa lỗi
        big = img.resize(target, Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))
        used = "Lanczos" if has_alpha else used
    if Path(dst).suffix.lower() in (".jpg", ".jpeg"):   # ảnh in: JPG q95 không lấy mẫu màu thấp, nhẹ ~5 lần PNG
        big.convert("RGB").save(dst, quality=95, subsampling=0)
    else:
        big.save(dst, compress_level=1)  # PNG vẫn không mất dữ liệu, chỉ nén nhanh hơn
    return {"engine": used, "scale": round(scale, 2)}
