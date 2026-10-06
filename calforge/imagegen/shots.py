"""Loại khung hình cho từng tháng: CODE chia, không để AI tự chọn.

Để một mình, AI viết 12 cảnh theo cùng một kiểu máy (cùng tầm mắt, cùng khung toàn cảnh),
nên 12 tháng nhìn na ná nhau. Ở đây mỗi tháng nhận một loại khung khác hẳn, thứ tự xáo theo
tên cuốn (cuốn khác nhau ra thứ tự khác nhau, chạy lại vẫn ra đúng thứ tự cũ). Màu chung của
cả bộ do style_bible + màu base + dải màu đính kèm giữ, không phụ thuộc bố cục.
"""
from __future__ import annotations

import hashlib
import random

SHOTS: dict[str, str] = {
    "wide_vista": "WIDE ESTABLISHING VIEW: the focal subject sits within a broad environment; clear horizon or "
                  "deep space, the setting carries as much weight as the subject.",
    "close_detail": "CLOSE-UP DETAIL: the focal subject fills most of the frame, cropped tight enough to show "
                    "texture and small details; the surroundings are only a soft suggestion.",
    "overhead": "OVERHEAD VIEW: look straight or steeply down onto the focal subject and its arrangement; no "
                "horizon and no sky.",
    "low_angle": "LOW ANGLE: camera near the ground looking up at the focal subject, which rises tall against "
                 "the sky, canopy or ceiling.",
    "foreground_still_life": "FOREGROUND STILL LIFE: a small arrangement of objects tied to the month fills the "
                             "near foreground; the wider setting stays soft behind it.",
    "hero_subject": "BOLD OFF-CENTER HERO SUBJECT: the focal subject is large and visually dominant, occupying "
                    "roughly 45–65% of the frame with a strong readable silhouette. Use an off-center composition, "
                    "but do not require or reserve blank space on the opposite side.",
    "natural_frame": "NATURAL FRAME: view the focal subject through a frame formed by nature (branches, leaves, "
                     "flowers, rocks or waves), not through architecture.",
    "minimal_space": "CONTROLLED NEGATIVE SPACE: keep the focal subject visually prominent, occupying roughly "
                     "40–55% of the frame, with roughly 35–45% intentional open space. The open area supports "
                     "the composition but must not make the subject look small, distant or stranded.",
    "leading_lines": "LEADING LINES: a path, stream, row, fence or shoreline pulls the eye diagonally from the "
                     "near edge toward the focal subject.",
    "pattern_field": "PATTERN FIELD: repeated elements (petals, leaves, birds, shells, fruit) fill the frame "
                     "edge to edge, and the focal subject breaks the rhythm.",
    "in_motion": "IN MOTION: capture the focal subject mid-action with strong diagonal energy; the moment feels "
                 "caught, not posed.",
    "layered_depth": "LAYERED DEPTH: distinct foreground, middle and background layers (or a reflection in water) "
                     "stack into depth, with the focal subject in the middle layer.",
}


# "Một nơi qua 12 mùa" phải giữ nơi đó nhận ra được: bỏ các khung làm mất nơi chốn
# (nhìn thẳng từ trên, cận cảnh, trường hoa văn, tĩnh vật tiền cảnh, chuyển động).
PLACE_SHOTS = ["wide_vista", "layered_depth", "natural_frame", "leading_lines", "minimal_space", "low_angle",
               "hero_subject"]


# Họ Anime: ảnh AI chỉ 1536x1024, khung nhìn từ trên / trường hoa văn làm nhân vật bé tí, mặt nhoè -> bỏ. 06/10/2026.
ANIME_FAMILY = "anime_illustration"
ANIME_EXCLUDED = ("overhead", "pattern_field")
ANIME_SHOTS = [s for s in SHOTS if s not in ANIME_EXCLUDED]
# Toàn cảnh vẫn giữ cho anime, nhưng nhân vật chính phải đủ lớn để vẽ rõ mặt.
ANIME_WIDE_NOTE = (" For this anime artwork the main characters still occupy at least about 30% of the frame "
                   "height, so their faces stay large enough to draw clearly.")


def assign(seed: str, frame_type: str = "", family: str = "") -> list[str]:
    """Khung cho tháng 1..12, thứ tự cố định theo seed (tên cuốn). Bình thường 12 khung khác nhau;
    one_scene_12_seasons chỉ dùng các khung giữ được nơi chốn (lặp lại nhưng không trùng tháng liền kề).
    Họ Anime bỏ các khung làm nhân vật quá nhỏ (ANIME_EXCLUDED), 10 khung còn lại lặp không trùng tháng liền kề."""
    rnd = random.Random(int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12], 16))
    anime = family == ANIME_FAMILY
    if frame_type == "one_scene_12_seasons" or anime:
        pool = PLACE_SHOTS if frame_type == "one_scene_12_seasons" else ANIME_SHOTS
        order: list[str] = []
        while len(order) < 12:
            batch = list(pool)
            rnd.shuffle(batch)
            if order and batch[0] == order[-1]:
                batch.append(batch.pop(0))
            order += batch
        return order[:12]
    order = list(SHOTS)
    rnd.shuffle(order)
    return order


def month_shot(concept: dict, month: dict) -> str:
    """Khung của một tháng: lấy cái đã lưu trong concept; concept cũ chưa có (hoặc cuốn anime cũ còn khung đã bỏ)
    thì chia lại theo tên cuốn."""
    family = str((concept.get("style") or {}).get("family") or "")
    shot = month.get("shot")
    if shot in SHOTS and not (family == ANIME_FAMILY and shot in ANIME_EXCLUDED):
        return shot
    return assign(str(concept.get("title", "")), str(concept.get("frame_type", "")), family)[int(month["month"]) - 1]


def shot_text(shot: str, family: str = "") -> str:
    """Mô tả khung đưa vào prompt; anime + toàn cảnh thêm yêu cầu nhân vật đủ lớn."""
    text = SHOTS[shot]
    return text + ANIME_WIDE_NOTE if family == ANIME_FAMILY and shot == "wide_vista" else text


def describe(seed: str, frame_type: str = "", family: str = "") -> str:
    """Danh sách khung theo tháng để đưa vào prompt P2."""
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return "\n".join(f"- {name}: {shot_text(shot, family)}"
                     for name, shot in zip(names, assign(seed, frame_type, family)))
