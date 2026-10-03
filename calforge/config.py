"""Cấu hình: calforge.json ở gốc repo (không có thì dùng mặc định)."""
from __future__ import annotations

import json
from pathlib import Path

from .core.dates import DEFAULT_YEAR

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "calforge.json"

DEFAULTS = {
    "year": DEFAULT_YEAR,
    "market": "US",
    "projects_dir": "projects",
    "angles_per_keyword": 1,
    "auto_pick": 1,
    "batch_retry_wait_s": 300,
    "max_browsers": 40,          # trần số Chrome mở cùng lúc; thực tế tự hạ theo RAM trống (~1 Chrome / 1.1 GB)
    "launch_gap_s": 5,           # mở Chrome cách nhau ít nhất bấy nhiêu giây (không bật ồ ạt như bot)
    # None = TỰ TÍNH theo số Chrome chạy được (llm/pool.auto_parallel): càng nhiều tài khoản + RAM càng nhiều luồng
    "book_workers": None,        # số cuốn vẽ ảnh cùng lúc trong một batch (tự tính: 3..8)
    "idea_lookahead": None,      # nghĩ ý trước tối đa bấy nhiêu cuốn chưa kịp vẽ (tự tính: = book_workers)
    "p2_parallel": None,         # số concept (P2) viết song song mỗi lượt (tự tính: 3..5)
    "finish_workers": None,      # số cuốn làm hậu kỳ (dàn trang, mockup) cùng lúc (tự tính: 1..2)
    "quota_wait_s": 1800,        # cả 5 tài khoản hết lượt: tạm dừng batch, cứ bấy nhiêu giây thử lại một lần
    "quota_max_wait_h": 24,      # chờ tối đa bấy nhiêu giờ cho một chỗ kẹt rồi mới coi là hỏng   # vòng vét cuối batch: chờ tài khoản ChatGPT hồi lượt rồi làm lại cuốn dở
    "max_repairs": 2,
    "profiles_dir": None,        # thư mục Chrome profile ChatGPT RIÊNG của calforge; None = <repo>/.chrome-profiles
    "chatgpt_automation_dir": "",  # chỉ dùng cho lệnh plan/import (đường vòng CSV); KHÔNG dùng chung tài khoản
    "llm": {
        "backend": "chatgpt_web",
        "profile": None,           # đặt tên để cố định 1 tài khoản; None = xoay vòng "profiles"
        "profiles": None,          # None = mọi profile (acc1 cuối) -> tài khoản mới đăng nhập hàng loạt tự được dùng
        "headless": "hidden",      # "hidden" = Chrome chạy ngầm ngoài màn hình; False = hiện cửa sổ; True = headless
        "timeout_s": 600,
    },
    "imagegen": {
        "profiles": None,          # None = mọi profile trong profiles_dir
        "headless": "hidden",      # "hidden" = Chrome chạy ngầm ngoài màn hình; False = hiện cửa sổ; True = headless
        "timeout_s": 420,
        "max_attempts": 3,
    },
    "printify": {
        "token": "",               # hoặc biến môi trường PRINTIFY_API_TOKEN
        "shop_id": None,
        "blueprint_id": None,
        "print_provider_id": None,
        "print_provider_name": "District Photo",
        "variant_title_contains": "11",
        "price_cents": 2999,
        "upload_workers": 4,
    },
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_FILE.exists():
        user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        merged = {k: {**cfg[k], **user.get(k, {})} for k in ("llm", "imagegen", "printify")}
        cfg.update(user)
        cfg.update(merged)
    cfg["projects_dir"] = str((ROOT / cfg["projects_dir"]).resolve())
    return cfg


def save_section(name: str, data: dict) -> None:
    """Ghi (gộp) một mục vào calforge.json - vd khoá R2 nhập từ UI. File này đã gitignore."""
    user = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
    user[name] = {**(user.get(name) or {}), **data}
    CONFIG_FILE.write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8")


def get_profiles_dir(cfg: dict | None = None) -> Path:
    """Thư mục Chrome profile (tài khoản ChatGPT) của calforge - mọi bước lấy ở đây, tách riêng khỏi
    chatgpt-automation để hai tool chạy song song không khoá profile / không ăn hạn mức của nhau."""
    cfg = cfg if cfg is not None else load()
    raw = cfg.get("profiles_dir") or (cfg.get("llm") or {}).get("profiles_dir")
    d = Path(raw) if raw else ROOT / ".chrome-profiles"
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_backend(cfg: dict):
    llm = cfg["llm"]
    if llm["backend"] == "manual":
        from .llm.manual import ManualBackend
        return ManualBackend()
    if llm["backend"] == "chatgpt_web":
        from .llm.chatgpt_web import ChatGPTWebBackend
        profiles_dir = str(get_profiles_dir(cfg))
        # "profiles": danh sách xoay vòng; "profile" (cũ) = một tài khoản cố định
        profiles = llm.get("profiles") or ([llm["profile"]] if llm.get("profile") else None)
        return ChatGPTWebBackend(profiles_dir, profiles, llm.get("headless", False), llm.get("timeout_s", 600),
                                 state_file=Path(cfg["projects_dir"]) / ".llm_rotation.json")
    raise ValueError(f"Backend không hỗ trợ: {llm['backend']}")
