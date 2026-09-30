"""Điều phối tài khoản ChatGPT cho MỘT tiến trình batch (chat lên ý tưởng + vẽ ảnh chạy song song).

Quy tắc:
- Mỗi tài khoản (Chrome profile) tại một thời điểm chỉ được MỘT việc mượn: chat HOẶC vẽ.
- Số Chrome mở cùng lúc có trần: tự tính theo RAM trống (~1 Chrome / 1.1 GB), không quá "max_browsers" (15).
- Mở Chrome cách nhau ít nhất "launch_gap_s" giây (mặc định 5) - không bật ồ ạt như bot.
- Hết lượt tính RIÊNG cho chat và vẽ: tài khoản hết lượt vẽ vẫn được đi chat và ngược lại.
- Khi đang cần chat (lên ý tưởng) thì giữ chỗ cho chat: việc vẽ không được mượn chỗ cuối cùng, và luồng vẽ
  đang giữ tài khoản sẽ nhường lại sau khi xong ảnh đang vẽ (should_yield).
- Tài khoản đang bị Chrome ngoài giữ (cửa sổ đăng nhập, tool khác) thì bỏ qua, không tranh.
"""
from __future__ import annotations

import ctypes
import json
import os
import random
import threading
import time
from contextlib import contextmanager
from pathlib import Path

CHAT, IMAGE = "chat", "image"
GB_PER_BROWSER = 1.1


def free_ram_gb() -> float:
    """RAM trống (GB); không đọc được thì coi như 8 GB."""
    if os.name == "nt":
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
            return ms.ullAvailPhys / 1024 ** 3
    return 8.0


def browser_cap(max_browsers: int = 15, free_gb: float | None = None) -> int:
    free_gb = free_ram_gb() if free_gb is None else free_gb
    return max(1, min(int(max_browsers), int(free_gb / GB_PER_BROWSER)))


def human_pause(lo: float = 0.6, hi: float = 2.0) -> None:
    """Độ trễ ngẫu nhiên nhỏ trước khi gửi tin - nhịp người thật, không dồn dập đều tăm tắp."""
    time.sleep(random.uniform(lo, hi))


class AccountPool:
    def __init__(self, profiles_dir: Path, names: list[str], *, cap: int, launch_gap_s: float = 5.0,
                 locked=None, state_file: Path | None = None, clock=time.monotonic, sleep=time.sleep):
        self.profiles_dir = Path(profiles_dir)
        self.names = list(names)
        self.cap = max(1, int(cap))
        self.launch_gap_s = float(launch_gap_s)
        self.state_file = state_file
        self._locked = locked or (lambda name: False)
        self._clock, self._sleep = clock, sleep
        self._cv = threading.Condition()
        self.use: dict[str, str] = {}                      # tài khoản -> vai đang giữ
        self.rest_until: dict[tuple[str, str], float] = {}  # (tài khoản, vai) -> hết nghỉ lúc
        self.rest_why: dict[tuple[str, str], str] = {}
        self.chat_reserve = 0                               # số chỗ đang giữ cho việc chat
        self._launch_lock = threading.Lock()
        self._last_launch = -1e9
        self.rest_s = 1800.0                                # tài khoản hết lượt nghỉ bao lâu (quota_wait_s)

    # ---------- trạng thái ----------
    def _resting(self, name: str, role: str) -> bool:
        t = self.rest_until.get((name, role))
        return t is not None and t > self._clock()

    def _free_for(self, name: str, role: str) -> bool:
        return name not in self.use and not self._resting(name, role) and not self._locked(name)

    def _count(self, role: str) -> int:
        return sum(1 for r in self.use.values() if r == role)

    def _image_slots(self) -> int:
        """Chỗ vẽ tối đa: trần trừ chỗ giữ cho chat (chỉ giữ khi có tài khoản chat được)."""
        chat_able = sum(1 for n in self.names if not self._resting(n, CHAT))
        need_chat = max(0, min(self.chat_reserve, chat_able) - self._count(CHAT))
        room = min(self.cap, len(self.names))               # ít tài khoản hơn trần: tính theo số tài khoản
        return max(0, room - self._count(CHAT) - need_chat)

    # ---------- mượn / trả ----------
    def acquire(self, role: str, *, prefer: list[str] | None = None, only: str | None = None) -> str | None:
        """Mượn một tài khoản cho vai `role`; không có thì None (không chờ)."""
        with self._cv:
            if len(self.use) >= self.cap:
                return None
            if role == IMAGE and self._count(IMAGE) >= self._image_slots():
                return None
            order = [only] if only else (prefer or []) + [n for n in self.names if n not in (prefer or [])]
            for name in order:
                if name in self.names and self._free_for(name, role):
                    self.use[name] = role
                    self._save()
                    return name
            return None

    def release(self, name: str) -> None:
        with self._cv:
            self.use.pop(name, None)
            self._save()
            self._cv.notify_all()

    def rest(self, name: str, role: str, seconds: float, why: str = "") -> None:
        with self._cv:
            self.rest_until[(name, role)] = self._clock() + seconds
            self.rest_why[(name, role)] = why[:160]
            self._save()
            self._cv.notify_all()

    def should_yield(self, name: str) -> bool:
        """Luồng vẽ đang giữ `name`: có nên nhả ra cho chat không (chat đang thiếu chỗ)."""
        with self._cv:
            return self.use.get(name) == IMAGE and self._count(IMAGE) > self._image_slots()

    @contextmanager
    def reserve_chat(self, n: int = 1):
        """Đang lên ý tưởng: giữ n chỗ cho chat trong suốt khối lệnh."""
        with self._cv:
            self.chat_reserve += n
            self._save()
        try:
            yield
        finally:
            with self._cv:
                self.chat_reserve = max(0, self.chat_reserve - n)
                self._save()
                self._cv.notify_all()

    def poke(self) -> None:
        """Đánh thức các vòng đang chờ (vd một việc vẽ vừa xong)."""
        with self._cv:
            self._cv.notify_all()

    def wait_change(self, timeout: float) -> None:
        with self._cv:
            self._cv.wait(timeout)

    def all_resting(self, role: str) -> bool:
        with self._cv:
            return all(self._resting(n, role) for n in self.names)

    def next_wake(self, role: str) -> float:
        """Còn bao nhiêu giây thì có tài khoản đầu tiên hết nghỉ cho vai này (0 = có ngay)."""
        with self._cv:
            now = self._clock()
            waits = [max(0.0, self.rest_until.get((n, role), 0) - now) for n in self.names]
            return min(waits) if waits else 0.0

    @contextmanager
    def launch_gate(self):
        """Mở Chrome cách nhau ít nhất launch_gap_s giây trên toàn batch."""
        with self._launch_lock:
            wait = self._last_launch + self.launch_gap_s - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_launch = self._clock()
        yield

    # ---------- ghi trạng thái cho UI ----------
    def snapshot(self) -> dict:
        now = self._clock()
        accs = []
        for n in self.names:
            rests = {r: round(t - now) for (a, r), t in self.rest_until.items() if a == n and t > now}
            accs.append({"name": n, "role": self.use.get(n, ""), "rest_s": rests,
                         "why": {r: self.rest_why.get((n, r), "") for r in rests}})
        return {"cap": self.cap, "chat_reserve": self.chat_reserve, "accounts": accs,
                "updated": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _save(self) -> None:
        if not self.state_file:
            return
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.state_file)
        except OSError:
            pass


_POOL: AccountPool | None = None
_POOL_LOCK = threading.Lock()


def get_pool(cfg: dict | None = None) -> AccountPool:
    """Bộ điều phối dùng chung trong tiến trình (lần đầu dựng từ cấu hình)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from .. import config
            from .accounts import is_profile_locked
            cfg = cfg or config.load()
            pdir = config.get_profiles_dir(cfg)
            names = sorted((p.name for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")),
                           key=lambda n: (n == "acc1", n)) if pdir.exists() else []
            cap = browser_cap(cfg.get("max_browsers", 15))
            _POOL = AccountPool(pdir, names, cap=cap, launch_gap_s=cfg.get("launch_gap_s", 5),
                                locked=lambda n: is_profile_locked(pdir / n),
                                state_file=Path(cfg["projects_dir"]) / ".tai_khoan_live.json")
            _POOL.rest_s = float(cfg.get("quota_wait_s", 1800))
            print(f"[tài khoản] {len(names)} tài khoản, tối đa {cap} Chrome cùng lúc "
                  f"(RAM trống {free_ram_gb():.1f} GB), mở cách nhau {_POOL.launch_gap_s:.0f}s", flush=True)
        return _POOL


def reset_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        _POOL = None
