"""Cấu hình: calforge.json ở gốc repo (không có thì dùng mặc định)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "calforge.json"

DEFAULTS = {
    "year": 2027,
    "market": "US",
    "projects_dir": "projects",
    "angles_per_keyword": 5,
    "auto_pick": 1,
    "max_repairs": 2,
    "chatgpt_automation_dir": "C:/Users/Admin/Desktop/chatgpt-automation",
    "llm": {
        "backend": "chatgpt_web",
        "profile": None,           # đặt tên để cố định 1 tài khoản; None = xoay vòng "profiles"
        "profiles": ["acc2", "acc3", "acc4", "acc5", "acc1"],
        "headless": False,
        "timeout_s": 600,
    },
    "imagegen": {
        "profiles": None,          # None = mọi profile trong chatgpt-automation/.chrome-profiles
        "headless": False,
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


def make_backend(cfg: dict):
    llm = cfg["llm"]
    if llm["backend"] == "manual":
        from .llm.manual import ManualBackend
        return ManualBackend()
    if llm["backend"] == "chatgpt_web":
        from .llm.chatgpt_web import ChatGPTWebBackend
        profiles_dir = llm.get("profiles_dir") or str(Path(cfg["chatgpt_automation_dir"]) / ".chrome-profiles")
        # "profiles": danh sách xoay vòng; "profile" (cũ) = một tài khoản cố định
        profiles = llm.get("profiles") or ([llm["profile"]] if llm.get("profile") else None)
        return ChatGPTWebBackend(profiles_dir, profiles, llm.get("headless", False), llm.get("timeout_s", 600),
                                 state_file=Path(cfg["projects_dir"]) / ".llm_rotation.json")
    raise ValueError(f"Backend không hỗ trợ: {llm['backend']}")
