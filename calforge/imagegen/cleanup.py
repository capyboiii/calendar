"""Làm sạch ảnh AI trước khi ghép vào lịch.

- remove_fake_checkerboard: ảnh có ô caro xám/trắng "giả trong suốt" vẽ luôn vào pixel (Gemini hay bị).
- paper_to_alpha: tranh màu nước trên giấy -> bỏ tờ giấy, giữ lớp màu (tương đương blend multiply).
- ensure_alpha: tự chọn cách: ảnh đã có nền trong suốt thật thì giữ nguyên, nền ô caro giả thì
  gỡ caro, nền trơn (trắng/kem) thì bỏ giấy.

Chạy:  python -m calforge.imagegen.cleanup checker in.webp out.png
       python -m calforge.imagegen.cleanup paper   in.webp out.png
"""
import sys
import warnings

import numpy as np
from PIL import Image

with warnings.catch_warnings():
    warnings.simplefilter("ignore")  # scipy cảnh báo lệch phiên bản numpy nhưng vẫn chạy đúng
    from scipy import ndimage


def background_kind(src) -> str:
    """'alpha' | 'checker' | 'plain' - đoán nền ảnh họa tiết từ viền ảnh."""
    img = Image.open(src)
    if img.mode in ("RGBA", "LA") and np.asarray(img.getchannel("A")).min() < 250:
        return "alpha"
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w = rgb.shape[:2]
    k = max(8, min(h, w) // 25)
    border = np.concatenate([rgb[:k].reshape(-1, 3), rgb[-k:].reshape(-1, 3),
                             rgb[:, :k].reshape(-1, 3), rgb[:, -k:].reshape(-1, 3)])
    lum = border.mean(1)
    # ô caro: xám trung tính, có HAI mức sáng rõ rệt (~210 và ~255)
    if (border.max(1) - border.min(1)).mean() < 6 and ((lum < 225).mean() > 0.2) and ((lum > 245).mean() > 0.2):
        return "checker"
    return "plain"


def ensure_alpha(src, dst) -> str:
    kind = background_kind(src)
    if kind == "alpha":
        img = Image.open(src).convert("RGBA")
        img.crop(img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()).save(dst)
    elif kind == "checker":
        remove_fake_checkerboard(src, dst)
    else:
        paper_to_alpha(src, dst)
    return kind


def remove_fake_checkerboard(src, dst, chroma_min=12, dark_max=190, min_blob=300):
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    chroma = rgb.max(2) - rgb.min(2)
    lum = rgb.mean(2)

    # Ô caro là xám trung tính (~209 và ~254); lá, cành, quả thì có màu hoặc tối
    seed = (chroma > chroma_min) | (lum < dark_max)
    seed = ndimage.binary_opening(seed, iterations=1)
    labels, n = ndimage.label(seed)
    sizes = ndimage.sum(seed, labels, range(1, n + 1))
    obj = np.isin(labels, np.nonzero(sizes >= min_blob)[0] + 1)

    # Lấp lỗ bên trong (vệt sáng trên lá), nhưng KHÔNG lấp khoảng caro kẹp giữa các lá
    holes, nh = ndimage.label(ndimage.binary_fill_holes(obj) & ~obj)
    for i in range(1, nh + 1):
        hole = holes == i
        if chroma[hole].mean() > 4 or hole.sum() < 60:
            obj |= hole
    obj = ndimage.binary_closing(obj, iterations=1)

    # Mép mềm + khử viền: pixel sát mép lấy màu của pixel lõi gần nhất (loại màu xám caro lẫn vào)
    core = ndimage.binary_erosion(obj, iterations=2)
    _, (iy, ix) = ndimage.distance_transform_edt(~core, return_indices=True)
    clean = rgb[iy, ix]
    alpha = ndimage.gaussian_filter(obj.astype(np.float32), 1.0)
    out = np.dstack([clean, alpha * 255]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    img.crop(img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()).save(dst)


def paper_to_alpha(src, dst, paper=None, floor=0.04):
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    if paper is None:  # màu giấy = trung vị 4 góc ảnh
        h, w = rgb.shape[:2]
        k = max(20, min(h, w) // 20)
        corners = np.concatenate([rgb[:k, :k], rgb[:k, -k:], rgb[-k:, :k], rgb[-k:, -k:]]).reshape(-1, 3)
        paper = np.median(corners, 0)
    paper = np.asarray(paper, np.float32)
    # Màu nước là lớp màu trong: chỉ phần TỐI hơn giấy mới là sơn; đốm sáng hơn giấy coi như giấy
    alpha = np.clip((paper - rgb) / paper, 0, 1).max(2)
    alpha = np.where(alpha < floor, 0, (alpha - floor) / (1 - floor))
    a = np.maximum(alpha, 1e-3)[..., None]
    color = np.clip((rgb - (1 - a) * paper) / a, 0, 255)
    out = np.dstack([color, alpha * 255]).astype(np.uint8)
    img = Image.fromarray(out, "RGBA")
    img.crop(img.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()).save(dst)
    return paper


if __name__ == "__main__":
    mode, src, dst = sys.argv[1:4]
    if mode == "checker":
        remove_fake_checkerboard(src, dst)
    else:
        print("paper color:", paper_to_alpha(src, dst).round())
