"""Điều phối tài khoản ChatGPT cho MỘT tiến trình batch (chat lên ý tưởng + vẽ ảnh chạy song song).

Quy tắc:
- Mỗi tài khoản (Chrome profile) tại một thời điểm chỉ được MỘT việc mượn: chat HOẶC vẽ.
- Số Chrome mở cùng lúc có trần: tự tính theo RAM trống (~1 Chrome / 1.1 GB), không quá "max_browsers" (40).
- Trần CO GIÃN lúc đang chạy (limit): RAM trống tụt thấp -> không mở thêm / bớt Chrome; nhiều tài khoản cùng lỗi
  trang / bị chặn trong vài phút -> giảm một nửa số Chrome rồi tăng dần lại (không dồn dập vào lúc ChatGPT chặn).
- Mở Chrome cách nhau ít nhất "launch_gap_s" giây (mặc định 5) - không bật ồ ạt như bot.
- Hết lượt tính RIÊNG cho chat và vẽ: tài khoản hết lượt vẽ vẫn được đi chat và ngược lại.
- Khi đang cần chat (lên ý tưởng) thì giữ chỗ cho chat: việc vẽ không được mượn chỗ cuối cùng, và luồng vẽ
  đang giữ tài khoản sẽ nhường lại sau khi xong ảnh đang vẽ (should_yield).
- Tài khoản đang bị Chrome ngoài giữ (cửa sổ đăng nhập, tool khác) thì bỏ qua, không tranh.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import random
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

CHAT, IMAGE = "chat", "image"
GB_PER_BROWSER = 1.1
RAM_HOLD_GB = 1.5         # RAM trống dưới mức này: không mở thêm Chrome
RAM_SHED_GB = 0.8         # dưới mức này: bớt Chrome (luồng vẽ nhường sau ảnh đang vẽ)
RAM_CHECK_S = 15.0
MIN_LIMIT = 2             # co trần cũng không xuống dưới 2 (1 chat + 1 vẽ)
BANNED_REST_S = 24 * 3600
DEAD_MARKER = ".calforge_dead.json"       # trong thư mục profile: tài khoản chết (bị đăng xuất / bị khoá)
DEAD_LABEL = {"logged_out": "bị đăng xuất - cần đăng nhập lại", "banned": "bị khoá / vô hiệu hoá - cần thay tài khoản"}


def read_dead(profile_dir: Path) -> dict | None:
    """Dấu tài khoản chết trong profile ({"kind", "why", "at"}); đăng nhập lại thành công thì dấu bị xoá."""
    try:
        d = json.loads((Path(profile_dir) / DEAD_MARKER).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d.get("kind") else None
    except (OSError, ValueError):
        return None


def clear_dead(profile_dir: Path) -> None:
    try:
        (Path(profile_dir) / DEAD_MARKER).unlink(missing_ok=True)
    except OSError:
        pass


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


def browser_cap(max_browsers: int = 40, free_gb: float | None = None) -> int:
    free_gb = free_ram_gb() if free_gb is None else free_gb
    return max(1, min(int(max_browsers), int(free_gb / GB_PER_BROWSER)))


def auto_parallel(cfg: dict, cap: int) -> dict:
    """Số luồng của batch theo số Chrome chạy được (cap). Giá trị ghi rõ trong cấu hình thì giữ nguyên.
    Một cuốn "AI vẽ cả trang" có ~26 ảnh nên ~8 Chrome / cuốn là vừa: đủ việc cho mọi Chrome mà không mở quá
    nhiều cuốn dở cùng lúc."""
    def pick(key, value):
        v = cfg.get(key)
        return max(1, int(v)) if v else value
    books = pick("book_workers", max(3, min(8, math.ceil(cap / 8))))
    return {"book_workers": books,
            "idea_lookahead": pick("idea_lookahead", books),
            "p2_parallel": pick("p2_parallel", max(3, min(5, math.ceil(cap / 10)))),
            "finish_workers": pick("finish_workers", 2 if books >= 5 else 1)}


def planned_cap(cfg: dict) -> int:
    """Số Chrome dự kiến chạy được: trần cấu hình, RAM trống và số tài khoản (không dựng bộ điều phối)."""
    from .. import config
    try:
        pdir = config.get_profiles_dir(cfg)
        n = sum(1 for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")) if pdir.exists() else 0
    except OSError:
        n = 0
    cap = browser_cap(cfg.get("max_browsers", 40))
    return max(1, min(cap, n)) if n else cap


def human_pause(lo: float = 0.6, hi: float = 2.0) -> None:
    """Độ trễ ngẫu nhiên nhỏ trước khi gửi tin - nhịp người thật, không dồn dập đều tăm tắp."""
    time.sleep(random.uniform(lo, hi))


LEASE = ".calforge_lease"     # file khoá trong profile: tiến trình nào đang giữ tài khoản (pid)


def _pid_alive(pid: int) -> bool:
    """Tiến trình còn chạy không (Windows: OpenProcess + GetExitCodeProcess; nơi khác: os.kill(pid, 0))."""
    import os
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class AccountPool:
    def __init__(self, profiles_dir: Path, names: list[str], *, cap: int, launch_gap_s: float = 5.0,
                 locked=None, state_file: Path | None = None, clock=time.monotonic, sleep=time.sleep,
                 free_ram=None, notify=None, leases: bool = False, later=None):
        self.profiles_dir = Path(profiles_dir)
        self.names = list(names)
        self.cap = max(1, int(cap))
        self.launch_gap_s = float(launch_gap_s)
        self.state_file = state_file
        self._locked = locked or (lambda name: False)
        # Khoá giữa các TIẾN TRÌNH (batch theo ý tưởng và clone sản phẩm chạy song song, mỗi bên một bộ điều phối):
        # mượn tài khoản = tạo file khoá trong profile; tiến trình khác thấy khoá thì bỏ qua tài khoản đó.
        self._leases = leases
        self._later = later or (lambda: set())            # tài khoản nên để dành cho tiến trình khác (lấy sau cùng)
        self._clock, self._sleep = clock, sleep
        self._cv = threading.Condition()
        self.use: dict[str, str] = {}                      # tài khoản -> vai đang giữ
        self.rest_until: dict[tuple[str, str], float] = {}  # (tài khoản, vai) -> hết nghỉ lúc
        self.rest_why: dict[tuple[str, str], str] = {}
        self.chat_reserve = 0                               # số chỗ đang giữ cho việc chat
        self._launch_lock = threading.Lock()
        self._last_launch = -1e9
        self.rest_s = 1800.0                                # tài khoản hết lượt nghỉ bao lâu (quota_wait_s)
        # ---- trần co giãn ----
        self._free_ram = free_ram                           # hàm -> GB RAM trống (None = không theo dõi RAM)
        self._notify = notify or (lambda msg: print(f"[tài khoản] {msg}", flush=True))
        self._ram_checked, self._ram_limit, self._ram_state = -1e9, None, "ok"
        self.throttle_window_s = 180.0                      # đếm tài khoản gặp lỗi trang / bị chặn trong khoảng này
        self.throttle_hold_s = 300.0                        # giữ mức giảm bấy lâu rồi tăng gấp đôi dần
        self._troubles: deque = deque()
        self._throttle_cap: int | None = None
        self._throttle_until = 0.0
        self.throttle_count = 0
        self.banned: dict[str, str] = {}                    # tài khoản bị khoá / vô hiệu -> lý do
        self.dead: dict[str, dict] = {}                     # tài khoản chết (bị đăng xuất / bị khoá) -> {kind, why}
        for n in self.names:                                # chết từ lần chạy trước mà chưa đăng nhập lại: bỏ luôn
            d = read_dead(self.profiles_dir / n)
            if d:
                self._mark_dead(n, d["kind"], str(d.get("why", "")))

    # ---------- trạng thái ----------
    def _resting(self, name: str, role: str) -> bool:
        t = self.rest_until.get((name, role))
        return t is not None and t > self._clock()

    def _free_for(self, name: str, role: str) -> bool:
        return (name not in self.use and name not in self.dead and not self._resting(name, role)
                and not self._locked(name) and not self._leased_elsewhere(name))

    # ---------- khoá tài khoản giữa các tiến trình ----------
    def _lease_file(self, name: str) -> Path:
        return self.profiles_dir / name / LEASE

    def _lease_owner(self, name: str) -> int:
        try:
            return int((self._lease_file(name).read_text(encoding="utf-8") or "0").split()[0])
        except (OSError, ValueError, IndexError):
            return 0

    def _leased_elsewhere(self, name: str) -> bool:
        if not self._leases:
            return False
        import os
        owner = self._lease_owner(name)
        return bool(owner and owner != os.getpid() and _pid_alive(owner))

    def _take_lease(self, name: str) -> bool:
        """Tạo file khoá (O_EXCL: hai tiến trình cùng tạo thì chỉ một bên được). Khoá của tiến trình đã chết thì dọn."""
        if not self._leases or not (self.profiles_dir / name).is_dir():
            return True
        import os
        f = self._lease_file(name)
        for _ in range(2):
            try:
                fd = os.open(str(f), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = self._lease_owner(name)
                if owner == os.getpid():
                    return True
                if owner and _pid_alive(owner):
                    return False
                try:                                     # khoá mồ côi (tiến trình đã tắt): dọn rồi thử lại
                    f.unlink()
                except OSError:
                    return False
                continue
            except OSError:
                return True                              # không ghi được file khoá: không chặn việc chính
            with os.fdopen(fd, "w", encoding="utf-8") as h:
                h.write(str(os.getpid()))
            return True
        return False

    def _drop_lease(self, name: str) -> None:
        if not self._leases:
            return
        import os
        if self._lease_owner(name) == os.getpid():
            try:
                self._lease_file(name).unlink()
            except OSError:
                pass

    def _count(self, role: str) -> int:
        return sum(1 for r in self.use.values() if r == role)

    def _image_slots(self) -> int:
        """Chỗ vẽ tối đa: trần trừ chỗ giữ cho chat (chỉ giữ khi có tài khoản chat được)."""
        chat_able = sum(1 for n in self.names if not self._resting(n, CHAT))
        need_chat = max(0, min(self.chat_reserve, chat_able) - self._count(CHAT))
        room = min(self._limit(), len(self.names))          # ít tài khoản hơn trần: tính theo số tài khoản
        return max(0, room - self._count(CHAT) - need_chat)

    # ---------- trần co giãn ----------
    def _floor(self) -> int:
        return min(self.cap, MIN_LIMIT)

    def _ram_cap(self) -> int:
        """Trần theo RAM lúc đang chạy (đo lại mỗi RAM_CHECK_S). Chrome đang mở đã ăn RAM nên so mức trống tuyệt đối."""
        if self._free_ram is None:
            return self.cap
        now = self._clock()
        if self._ram_limit is None or now - self._ram_checked >= RAM_CHECK_S:
            self._ram_checked = now
            try:
                free = float(self._free_ram())
            except Exception:  # noqa: BLE001 - không đo được thì coi như đủ RAM
                free = 99.0
            used = len(self.use)
            if free < RAM_SHED_GB:
                state, limit = "shed", max(self._floor(), used - max(1, used // 4))
            elif free < RAM_HOLD_GB:
                state, limit = "hold", max(self._floor(), used)
            else:
                state, limit = "ok", self.cap
            if state != self._ram_state:
                self._notify({"shed": f"RAM trống còn {free:.1f} GB - bớt Chrome xuống {limit}",
                              "hold": f"RAM trống còn {free:.1f} GB - tạm không mở thêm Chrome (đang {used})",
                              "ok": f"RAM đã đủ ({free:.1f} GB) - mở lại tới {self.cap} Chrome"}[state])
            self._ram_state, self._ram_limit = state, limit
        return self._ram_limit

    def _limit(self) -> int:
        """Số Chrome được mở lúc này: trần cấu hình, RAM đang trống, và mức giảm khi nhiều tài khoản cùng lỗi."""
        lim = min(self.cap, self._ram_cap())
        if self._throttle_cap is not None:
            now = self._clock()
            if now >= self._throttle_until:                 # yên ổn đủ lâu: tăng gấp đôi, tới trần thì thôi giảm
                nxt = self._throttle_cap * 2
                if nxt >= self.cap:
                    self._throttle_cap = None
                    self._notify(f"đã ổn định - chạy lại đủ {self.cap} Chrome")
                else:
                    self._throttle_cap, self._throttle_until = nxt, now + self.throttle_hold_s
                    self._notify(f"đang ổn định lại - tăng lên {nxt} Chrome")
            if self._throttle_cap is not None:
                lim = min(lim, self._throttle_cap)
        return max(1, lim)

    def limit(self) -> int:
        with self._cv:
            return self._limit()

    def trouble(self, name: str, why: str = "") -> None:
        """Một tài khoản vừa gặp lỗi trang / mạng / bị chặn tốc độ. Nhiều tài khoản KHÁC NHAU cùng gặp trong
        throttle_window_s => không phải lỗi của riêng tài khoản nào (mạng yếu, ChatGPT chặn theo máy/IP, máy quá
        tải): giảm một nửa số Chrome, giữ throttle_hold_s rồi tăng dần lại."""
        with self._cv:
            now = self._clock()
            self._troubles.append((now, name))
            while self._troubles and now - self._troubles[0][0] > self.throttle_window_s:
                self._troubles.popleft()
            distinct = {n for _, n in self._troubles}
            current = self._limit()
            if len(distinct) < max(4, math.ceil(current * 0.3)) or current <= self._floor():
                return
            self._throttle_cap = max(self._floor(), current // 2)
            self._throttle_until = now + self.throttle_hold_s
            self._troubles.clear()
            self.throttle_count += 1
            self._notify(f"{len(distinct)} tài khoản cùng lỗi trang / bị chặn trong ít phút ({why[:60]}) - "
                         f"giảm còn {self._throttle_cap} Chrome, sẽ tăng dần lại")
            self._save()
            self._cv.notify_all()

    def _mark_dead(self, name: str, kind: str, why: str) -> None:
        self.dead[name] = {"kind": kind, "why": why[:160]}
        if kind == "banned":
            self.banned[name] = why[:160]
        until = self._clock() + BANNED_REST_S
        for role in (CHAT, IMAGE):
            self.rest_until[(name, role)] = until
            self.rest_why[(name, role)] = f"tài khoản chết ({DEAD_LABEL.get(kind, kind)})"

    def drop(self, name: str, kind: str, why: str = "") -> bool:
        """Tài khoản CHẾT (kind: "logged_out" = trang ChatGPT hiện màn hình đăng nhập, "banned" = bị khoá):
        bỏ hẳn khỏi batch cho cả chat lẫn vẽ, ghi dấu vào profile để các batch sau và UI cũng bỏ qua / báo cho
        người dùng. Đăng nhập lại thành công thì dấu bị xoá (bulk_login.mark_logged_in). True = vừa mới phát hiện."""
        with self._cv:
            first = name not in self.dead
            self._mark_dead(name, kind, why)
            try:
                pdir = self.profiles_dir / name
                if pdir.is_dir():
                    (pdir / DEAD_MARKER).write_text(json.dumps(
                        {"kind": kind, "why": why[:300], "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                        ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            self._save()
            self._cv.notify_all()
        if first:
            self._notify(f"✘ TÀI KHOẢN CHẾT: {name} {DEAD_LABEL.get(kind, kind)} - đã bỏ khỏi batch")
        return first

    def ban(self, name: str, why: str) -> None:
        """Tài khoản bị khoá / vô hiệu hoá: bỏ hẳn (xem drop)."""
        self.drop(name, "banned", why)

    def alive_names(self) -> list[str]:
        with self._cv:
            return [n for n in self.names if n not in self.dead]

    # ---------- mượn / trả ----------
    def acquire(self, role: str, *, prefer: list[str] | None = None, only: str | None = None) -> str | None:
        """Mượn một tài khoản cho vai `role`; không có thì None (không chờ)."""
        with self._cv:
            if len(self.use) >= self._limit():
                return None
            if role == IMAGE and self._count(IMAGE) >= self._image_slots():
                return None
            order = [only] if only else (prefer or []) + [n for n in self.names if n not in (prefer or [])]
            if not only:                                  # tài khoản để dành cho tiến trình khác: lấy sau cùng
                later = self._later()
                if later:
                    order = [n for n in order if n not in later] + [n for n in order if n in later]
            for name in order:
                if name in self.names and self._free_for(name, role) and self._take_lease(name):
                    self.use[name] = role
                    self._save()
                    return name
            return None

    def release(self, name: str) -> None:
        with self._cv:
            self.use.pop(name, None)
            self._drop_lease(name)
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
            if self.use.get(name) != IMAGE:
                return False
            return self._count(IMAGE) > self._image_slots() or len(self.use) > self._limit()   # chat thiếu chỗ / co trần

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
        return {"cap": self.cap, "limit": self._limit(), "throttled": self._throttle_cap is not None,
                "ram": self._ram_state, "banned": dict(self.banned), "dead": dict(self.dead),
                "chat_reserve": self.chat_reserve, "accounts": accs,
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
            cap = browser_cap(cfg.get("max_browsers", 40))
            _POOL = AccountPool(pdir, names, cap=cap, launch_gap_s=cfg.get("launch_gap_s", 5),
                                locked=lambda n: is_profile_locked(pdir / n), free_ram=free_ram_gb,
                                state_file=Path(cfg["projects_dir"]) / ".tai_khoan_live.json",
                                leases=True, later=_plus_saved_for_clone(cfg))
            _POOL.rest_s = float(cfg.get("quota_wait_s", 1800))
            print(f"[tài khoản] {len(names)} tài khoản, tối đa {cap} Chrome cùng lúc "
                  f"(RAM trống {free_ram_gb():.1f} GB), mở cách nhau {_POOL.launch_gap_s:.0f}s", flush=True)
        return _POOL


def _plus_saved_for_clone(cfg: dict):
    """Khi hàng đợi "Clone sản phẩm" đang có việc (cuốn chờ / đang chạy), tiến trình KHÁC (batch theo ý tưởng) lấy
    tài khoản Free trước, tài khoản Plus sau cùng - clone chỉ dùng được Plus. Đọc lại tối đa 30 giây một lần."""
    import os
    cache = {"at": -1e9, "names": set()}

    def later() -> set[str]:
        if os.environ.get("CALFORGE_CLONE_RUN"):        # chính tiến trình clone: không để dành gì
            return set()
        now = time.monotonic()
        if now - cache["at"] < 30:
            return cache["names"]
        cache["at"] = now
        names: set[str] = set()
        try:
            from ..clone import store
            if store.pending(cfg["projects_dir"]):
                from . import plan
                pdir = config_profiles(cfg)
                for d in pdir.iterdir() if pdir.exists() else []:
                    info = plan.read(d) if d.is_dir() else None
                    if plan.is_paid(info):
                        names.add(d.name)
        except Exception:  # noqa: BLE001 - chỉ là thứ tự ưu tiên, lỗi thì bỏ qua
            names = set()
        cache["names"] = names
        return names
    return later


def config_profiles(cfg: dict):
    from .. import config
    return config.get_profiles_dir(cfg)


def peek_pool() -> AccountPool | None:
    """Bộ điều phối đang dùng (không dựng mới)."""
    return _POOL


def reset_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        _POOL = None
