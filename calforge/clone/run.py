"""Chạy hàng đợi "Làm theo ảnh mẫu" - CHỈ dùng tài khoản ChatGPT Plus còn hạn.

Mỗi cuốn:
  1. Phiên A (tài khoản Plus X): đính ảnh tham chiếu -> 10 artwork -> nhắn tiếp lấy 2 artwork còn lại -> hỏi chữ lấy
     tên cuốn + listing Etsy -> vẽ bìa. Có tên thì chuyển sang thư mục SKU thật.
  2. Phiên B (tài khoản Plus khác nếu có): đính 10 artwork -> 10 trang lịch -> đính 2 artwork cuối -> 2 trang nữa.
     OCR soát từng trang; trang sai vẽ lại ngay trong phiên.
  3. Dựng sách bằng pipeline của trang chính: upscale, 2 khổ in + PDF, mockup AI (mọi tài khoản, thinking mặc định), listing.txt.
Lỗi giữa chừng (hết lượt, mạng, tài khoản chết, lỗi server): ảnh đã về được giữ, phiên mới chỉ vẽ phần còn thiếu.
Hàng đợi chia theo bước: artwork/trang lịch dùng chung pool Plus linh hoạt; hậu kỳ có executor riêng.
Mỗi cuốn chỉ chạy một bước tại một thời điểm. Số Chrome thực tế vẫn chịu trần RAM của pool chung.
"""
from __future__ import annotations

import copy
import json
import queue
import shutil
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path

from .. import config, layout, products
from ..imagegen import driver
from ..imagegen.driver import BANNED, LOGGED_OUT, NavError, QuotaExceeded, TempError, ThirdPartyIPRefused
from ..imagegen.plan import job_done
from . import prompts, session, store

PAID = {"plus", "pro"}
MAX_TURNS = 4             # một phiên nhắn "vẽ tiếp" tối đa bấy nhiêu lượt không ra ảnh mới thì đổi phiên
MAX_SESSIONS = 4          # một bước hỏng (không phải lỗi tài khoản) bấy nhiêu phiên thì tạm bỏ cuốn (chạy lại sau)
GRID_REDO = 2             # một trang lịch OCR sai: vẽ lại trong phiên bấy nhiêu lần
REF_BATCH = 10            # ChatGPT nhận tối đa 10 ảnh một tin nhắn


class BookRejected(RuntimeError):
    """ChatGPT từ chối (TM/bản quyền/nội dung nhạy cảm) 3 lần liền: bỏ cuốn."""


class StageFailed(RuntimeError):
    """Bước chưa xong sau nhiều phiên / hết tài khoản Plus: cuốn để lại, chạy lại sau làm tiếp."""


# ------------------------------------------------------------------ tài khoản Plus
def plus_accounts(cfg: dict, check_unknown: bool = True, on_event=print) -> list[str]:
    """Tài khoản Plus/Pro còn hạn. Chưa rõ gói thì đọc gói trước (mở ngầm); Free / hết hạn / chết thì bỏ."""
    from ..llm import accounts, plan
    from ..llm.pool import read_dead
    pdir = config.get_profiles_dir(cfg)
    out = []
    for d in sorted(p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")) if pdir.exists() else []:
        if read_dead(d) or not accounts.has_chatgpt_session(d):
            continue
        info = plan.read(d)
        if info is None and check_unknown and not accounts.is_profile_locked(d):
            on_event(f"[tài khoản] {d.name}: chưa rõ gói - đang kiểm tra...")
            try:
                plan._check_one(d)
            except Exception:  # noqa: BLE001
                pass
            info = plan.read(d)
        if info and info.get("plan") in PAID and info.get("active", True) and not info.get("expired"):
            out.append(d.name)
    return out


class Accounts:
    """Mượn / trả tài khoản Plus qua bộ điều phối chung (không đụng tài khoản đang bận ở tiến trình khác)."""

    def __init__(self, cfg: dict, names: list[str], on_event=print, pool=None, open_page=None):
        from ..llm.pool import get_pool
        self.cfg, self.names, self.on_event = cfg, list(names), on_event
        self.pool = pool or get_pool(cfg)
        self.pdir = config.get_profiles_dir(cfg)
        self.open_page = open_page or self._default_open
        self.max_wait_s = float(cfg.get("quota_max_wait_h", 6)) * 3600

    def acquire(self, avoid: set[str] | None = None, stop: threading.Event | None = None,
                prefer: str | None = None) -> str:
        from ..llm.pool import IMAGE
        waited_from = time.monotonic()
        while not (stop and stop.is_set()):
            alive = [n for n in self.names if n not in self.pool.dead]
            if not alive:
                raise StageFailed("không còn tài khoản Plus nào dùng được")
            order = [n for n in alive if n not in (avoid or set())] + [n for n in alive if n in (avoid or set())]
            if prefer in order:                          # tài khoản có chat dở của cuốn này: dùng lại trước
                order.remove(prefer)
                order.insert(0, prefer)
            for n in order:
                if self.pool.acquire(IMAGE, only=n):
                    return n
            if all(self.pool._resting(n, IMAGE) for n in alive):
                if time.monotonic() - waited_from > self.max_wait_s:
                    raise StageFailed("mọi tài khoản Plus đều hết lượt quá lâu - chạy lại sau")
            self.pool.wait_change(3.0)
        raise StageFailed("người dùng dừng")

    def release(self, name: str) -> None:
        self.pool.release(name)

    @contextmanager
    def _default_open(self, name: str):
        from playwright.sync_api import sync_playwright
        from ..llm.browser import hide_offscreen_from_taskbar, launch_options
        headless = (self.cfg.get("imagegen") or {}).get("headless", "hidden")
        with sync_playwright() as pw:
            with self.pool.launch_gate():
                ctx = pw.chromium.launch_persistent_context(
                    str(self.pdir / name), channel="chrome", viewport={"width": 1400, "height": 950},
                    **launch_options(headless))
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                if headless in ("hidden", None):
                    hide_offscreen_from_taskbar()
                yield page
            finally:
                ctx.close()


def run_stage(accts: Accounts, label: str, work, *, avoid: set[str] | None = None,
              stop: threading.Event | None = None, session_factory=None, prefer=None) -> str:
    """Chạy `work(session)` tới khi xong, đổi tài khoản khi cần. Trả tên tài khoản đã làm xong bước."""
    from ..llm.pool import IMAGE
    session_factory = session_factory or session.Session
    fails = refusals = nav = 0
    last = ""
    while True:
        if stop and stop.is_set():
            raise StageFailed("người dùng dừng")
        want = prefer() if callable(prefer) else prefer
        name = accts.acquire(avoid, stop, prefer=want)
        try:
            with accts.open_page(name) as page:
                s = session_factory(page, accts.pdir / name)
                s.open()
                think = getattr(s, "thinking", None)
                accts.on_event(f"[{name}] {label}: bắt đầu phiên"
                               + (f" (thinking: {think})" if think else
                                  " (⚠ không đặt được mức thinking - dùng mức sẵn có)" if think == "" else ""))
                work(s, name)
                return name
        except QuotaExceeded as e:
            accts.pool.rest(name, IMAGE, accts.pool.rest_s, str(e))
            accts.on_event(f"[{name}] {label}: HẾT LƯỢT, nghỉ tài khoản này, chuyển tài khoản Plus khác: {str(e)[:100]}")
            if any(h in str(e).lower() for h in driver.RATE_HINTS):
                accts.pool.trouble(name, str(e))
        except NavError as e:
            kind = "banned" if BANNED in str(e) else "logged_out" if LOGGED_OUT in str(e) else ""
            if kind:
                accts.pool.drop(name, kind, str(e))
                accts.on_event(f"[{name}] ✘ TÀI KHOẢN CHẾT ({kind}) - đã bỏ, chuyển tài khoản Plus khác")
            else:
                accts.pool.rest(name, IMAGE, driver.NAV_REST_S, str(e))
                accts.pool.trouble(name, str(e))
                nav += 1
                accts.on_event(f"[{name}] {label}: lỗi trang ChatGPT ({str(e)[:80]}) - đổi tài khoản")
                if nav >= driver.NAV_MAX:
                    nav, fails = 0, fails + 1
        except ThirdPartyIPRefused as e:
            refusals += 1
            accts.on_event(f"[{name}] {label}: ChatGPT từ chối (TM/bản quyền/nội dung nhạy cảm) lần "
                           f"{refusals}/{driver.REFUSAL_TRIES}: {str(e)[:120]}")
            if refusals >= driver.REFUSAL_TRIES:
                raise BookRejected(str(e)[:300]) from e
        except (BookRejected, StageFailed):
            raise
        except TempError as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
            if _server_side(str(e)):
                # lỗi phía server ChatGPT / tab kẹt: như lỗi trang ở trang chính - tài khoản nghỉ ngắn, phiên mới
                # trên tài khoản khác, không tính là phiên hỏng cho tới NAV_MAX lần
                accts.pool.rest(name, IMAGE, driver.NAV_REST_S, last)
                accts.pool.trouble(name, last)
                nav += 1
                accts.on_event(f"[{name}] {label}: ChatGPT lỗi phía server ({str(e)[:90]}) - đổi tài khoản")
                if nav >= driver.NAV_MAX:
                    nav, fails = 0, fails + 1
            else:
                fails += 1
                accts.on_event(f"[{name}] {label}: lỗi ({last[:140]}) - thử phiên mới ({fails}/{MAX_SESSIONS})")
        except Exception as e:  # noqa: BLE001 - Chrome hỏng, lỗi lạ: thử phiên mới
            last = f"{type(e).__name__}: {str(e)[:200]}"
            if _network_error(last):                     # mạng chập / Playwright hết giờ: như lỗi trang, đổi tài khoản
                accts.pool.rest(name, IMAGE, driver.NAV_REST_S, last)
                nav += 1
                accts.on_event(f"[{name}] {label}: lỗi mạng ({last[:100]}) - đổi tài khoản ({nav}/{driver.NAV_MAX})")
                if nav >= driver.NAV_MAX:
                    nav, fails = 0, fails + 1
            else:
                fails += 1
                accts.on_event(f"[{name}] {label}: lỗi ({last[:140]}) - thử phiên mới ({fails}/{MAX_SESSIONS})")
                if "không mở được" in last or "Target" in last:
                    accts.pool.rest(name, IMAGE, 300, last)
        finally:
            accts.release(name)
        if fails >= MAX_SESSIONS:
            raise StageFailed(f"{label}: chưa xong sau {fails} phiên ({last[:160]})")


@contextmanager
def ocr_memo():
    """Trong lúc soát một lượt trang lịch: nhớ kết quả OCR theo nội dung ảnh, để soát cùng một trang với nhiều tháng
    (trang về lệch thứ tự) không phải OCR lại. Chỉ trong tiến trình clone; code soát của trang chính không đổi."""
    import hashlib
    from ..imagegen import grid_check
    real = grid_check._ocr_scored
    memo: dict = {}
    lock = threading.Lock()

    def cached(img):
        key = (img.size, hashlib.md5(img.tobytes()).hexdigest())
        with lock:
            if key in memo:
                return memo[key]
        out = real(img)
        with lock:
            memo[key] = out
        return out
    with _OCR_MEMO_LOCK:
        grid_check._ocr_scored = cached
        try:
            yield
        finally:
            grid_check._ocr_scored = real


_OCR_MEMO_LOCK = threading.Lock()


def _month_named(reason: str) -> int | None:
    """Lý do OCR 'sai tên tháng: trang ghi "February" ...' -> 2 (không có thì None)."""
    import re
    m = re.search(r'trang ghi "([A-Za-z]+)"', reason or "")
    names = [n.lower() for n in prompts.MONTHS]
    return names.index(m.group(1).lower()) + 1 if m and m.group(1).lower() in names else None


NET_HINTS = ("timeout", "timed out", "net::", "err_", "connection", "network", "socket", "đính kèm",
             "upload", "econnreset", "getaddrinfo", "dns")


def _network_error(text: str) -> bool:
    """Lỗi do mạng / trang chưa tải (Playwright hết giờ chờ, net::ERR_*, mất kết nối, tải ảnh lên lỗi)."""
    low = text.lower()
    return any(k in low for k in NET_HINTS)


def _server_side(text: str) -> bool:
    """Lỗi tạm do phía ChatGPT (server báo lỗi, tab kẹt không phản hồi, lượt xong mà không ra ảnh)."""
    low = text.lower()
    return any(k in low for k in ("chatgpt báo lỗi", "tab kẹt", "trả lời xong mà không có ảnh", "chưa ra ảnh"))


# ------------------------------------------------------------------ một cuốn
GRID_WAIT_S = 1200        # trang lịch chạy sớm: chờ artwork 11-12 bấy lâu trong cùng phiên rồi mới thôi
GRID_POLL_S = 10
_ITEM_LOCKS: dict[str, threading.RLock] = {}
_ITEM_LOCKS_GUARD = threading.Lock()


def _item_lock(name: str) -> threading.RLock:
    """Một khoá cho mỗi cuốn: bước artwork và bước trang lịch của CÙNG cuốn chạy song song, không được ghi file
    đúng lúc thư mục work/ đang được chuyển sang thư mục SKU."""
    with _ITEM_LOCKS_GUARD:
        return _ITEM_LOCKS.setdefault(name, threading.RLock())


class Book:
    def __init__(self, cfg: dict, d: Path, on_event=print):
        self.cfg, self.d, self.on_event = cfg, d, on_event
        self.item = store.read(d)
        self.year = int(self.item.get("year") or 2027)
        self.lock = _item_lock(d.name)
        self.on_grid_ready = None                      # gọi (thư mục mục) khi đủ artwork 1-10: trang lịch chạy sớm
        self._grid_signalled = False

    @property
    def dir(self) -> Path:
        """Thư mục đang chứa ảnh: thư mục SKU nếu đã có tên, chưa thì work/ của mục. Đọc lại item.json mỗi lần: bước
        kia của cùng cuốn có thể vừa chuyển ảnh sang thư mục SKU."""
        book = store.read(self.d).get("book") or self.item.get("book")
        if book and Path(book).is_dir():
            return Path(book)
        return self.d / "work"

    def _grid_ready_check(self) -> None:
        if self.on_grid_ready and not self._grid_signalled and all(self.done(f"m{m:02d}") for m in range(1, 11)):
            self._grid_signalled = True
            self.on_grid_ready(self.d)

    def raw(self, job: str) -> Path:
        return layout.raw(self.dir) / job

    def done(self, job: str) -> Path | None:
        return job_done(self.dir, job)

    def missing(self, prefix: str) -> list[int]:
        return [m for m in range(1, 13) if self.done(f"{prefix}{m:02d}") is None]

    def meta(self) -> dict | None:
        try:
            return json.loads((layout.tech(self.dir) / "clone_meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def status(self, **kw) -> None:
        self.item = store.write(self.d, **kw)

    # -------------------------------------------------------------- phiên A: artwork + tên + bìa
    def _watch(self, s, name: str, what: str) -> None:
        """Báo tiến độ mỗi phút trong lúc chờ một lượt nhiều ảnh (nhật ký + dòng trạng thái của cuốn)."""
        def report(got, want, busy, secs):
            state = "ChatGPT đang vẽ" if busy else "chờ ChatGPT phản hồi"
            self.on_event(f"[{name}] {what}: đã ra {got}/{want} ảnh trong lượt này - {state} ({secs // 60} phút)")
        s.progress = report

    def art_work(self, s, name: str) -> None:
        refs = store.refs(self.d)
        self._watch(s, name, "artwork")
        missing = self.missing("m")
        self.status(art_account=name)                   # trang lịch chạy sớm tránh tài khoản này
        self._grid_ready_check()
        if missing:
            self.status(stage=f"vẽ artwork ({12 - len(missing)}/12)")
            if not self._reopen_chat(s, name):
                first = len(missing) == 12
                prompt = prompts.art_prompt(len(refs)) if first else prompts.art_resume(missing, len(refs))
                want = 10 if first else len(missing)
                s.on_sent = lambda url: self.status(art_chat={"url": url, "account": name, "saved": 0})
                turn = s.ask_images(prompt, want, attach=refs)
                s.on_sent = None
                s.has_art = True                        # phiên này đã có artwork: bìa/tên hỏi ngay trong phiên
                self._take_art(turn, name)
            self._grid_ready_check()
            idle = 0
            while self.missing("m"):
                missing = self.missing("m")
                self.status(stage=f"vẽ artwork ({12 - len(missing)}/12)")
                before = len(missing)
                turn = s.ask_images(prompts.art_continue(missing, len(refs)), len(missing))
                self._take_art(turn, name)
                self._grid_ready_check()
                idle = idle + 1 if len(self.missing("m")) == before else 0
                if idle >= 2:
                    raise TempError(f"ChatGPT không vẽ thêm artwork (còn thiếu {self.missing('m')})")
        if self.meta() is None:
            self.status(stage="đặt tên + listing")
            self._ask_meta(s, attach_art=not s_has_art(s))
        self._adopt()                                   # có tên -> chuyển sang thư mục SKU
        if self.done("cover") is None:
            self.status(stage="vẽ bìa")
            meta = self.meta()
            fresh = not s_has_art(s)
            attach = [self.done(f"m{m:02d}") for m in (1, 4, 7, 10)] if fresh else None
            turn = s.ask_images(prompts.cover_prompt(meta["title"], meta.get("subtitle", ""), self.year, fresh=fresh),
                                1, attach=attach)
            why = session.landscape_ok(turn.images[0]) if turn.images else None
            if turn.images and why is None:
                with self.lock:
                    session.save(turn.images[0], self.raw("cover"))
                self.on_event(f"[{name}] bìa: xong")
            elif turn.problem:
                raise turn.problem
            else:
                if turn.images:
                    self._reject(turn.images[0], "cover")
                raise TempError(f"không nhận được ảnh bìa hợp lệ{f' ({why})' if why else ''}")

    def _reopen_chat(self, s, name: str) -> bool:
        """Lần chạy trước đã vẽ trong một cuộc chat của chính tài khoản này (bị dừng / kẹt giữa chừng): mở lại chat
        đó, lấy các ảnh đã vẽ mà chưa lưu, rồi nhắn tiếp ngay trong chat đó. False = không có chat cũ dùng được."""
        chat = self.item.get("art_chat") or {}
        if chat.get("account") != name or not chat.get("url"):
            return False
        try:
            driver.open_home(s.page, chat["url"])
            s.w._find(s.page, driver.SEL_PROMPT, 60_000)
            session.ensure_chat_mode(s.page)
            images = s.harvest()
        except NavError:
            raise
        except Exception as e:  # noqa: BLE001 - chat cũ mở không được: vẽ trong chat mới
            self.on_event(f"[{name}] không mở lại được chat cũ ({str(e)[:80]}) - vẽ trong chat mới")
            self.status(art_chat={})
            return False
        saved = int(chat.get("saved", 0))
        fresh = images[saved:]
        self.on_event(f"[{name}] mở lại chat cũ: {len(images)} ảnh trong chat, {len(fresh)} ảnh chưa lưu")
        s.has_art = True
        if fresh:
            self._take_art(session.Turn(fresh), name)
        return True

    def _take_art(self, turn, name: str) -> None:
        chat = self.item.get("art_chat") or {}
        if chat.get("account") == name:                 # đếm ảnh đã lấy từ chat này (mở lại chat không lấy trùng)
            self.status(art_chat={**chat, "saved": int(chat.get("saved", 0)) + len(turn.images)})
        missing = self.missing("m")
        got = 0
        for data in turn.images:
            if not missing:
                break
            why = session.landscape_ok(data)
            if why:
                self._reject(data, f"art-{missing[0]:02d}")
                self.on_event(f"[{name}] bỏ 1 ảnh artwork: {why}")
                continue
            m = missing.pop(0)
            with self.lock:
                session.save(data, self.raw(f"m{m:02d}"))
            got += 1
        self.on_event(f"[{name}] artwork: +{got} ảnh, còn thiếu {len(self.missing('m'))}")
        if turn.problem and (not got or isinstance(turn.problem, (QuotaExceeded, ThirdPartyIPRefused))):
            raise turn.problem

    def _reject(self, data: bytes, tag: str) -> None:
        with self.lock:
            d = layout.tech(self.dir) / "anh_bi_loai"
            d.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%H%M%S')
            n = 0
            while (d / f"{tag}-{stamp}-{n}{session.ext_of(data)}").exists():   # nhiều ảnh cùng giây: không ghi đè
                n += 1
            (d / f"{tag}-{stamp}-{n}{session.ext_of(data)}").write_bytes(data)

    def _ask_meta(self, s, attach_art: bool) -> None:
        from ..ideation.extract import extract_json
        ask = prompts.meta_prompt(self.year)
        if attach_art:                                  # phiên mới: ChatGPT chưa thấy ảnh -> đính 10 artwork đầu
            arts = [self.done(f"m{m:02d}") for m in range(1, 11)]
            (s.attach(arts) if hasattr(s, "attach") else s.w._attach(s.page, arts))
            ask = ("I have attached 10 of the 12 artworks of this calendar (January to October).\n" + ask)
        for attempt in range(3):
            answer = s.ask_text(ask)
            try:
                data = extract_json(answer)
            except Exception:  # noqa: BLE001
                data = None
            errors = validate_meta(data)
            if not errors:
                data["months"] = month_captions(data.get("months"))
                with self.lock:
                    layout.tech(self.dir).mkdir(parents=True, exist_ok=True)
                    (layout.tech(self.dir) / "clone_meta.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                self.on_event(f"  ✔ Tên cuốn: {data['title']}")
                return
            self.on_event(f"  ⚠ JSON tên/listing chưa đạt ({'; '.join(errors)[:140]}) - nhờ ChatGPT sửa")
            ask = prompts.meta_repair(errors)
        raise TempError("ChatGPT chưa trả được tên cuốn + listing hợp lệ")

    def _adopt(self) -> None:
        with self.lock:                                 # bước trang lịch của cùng cuốn chờ chuyển xong mới ghi tiếp
            self._adopt_locked()

    def _adopt_locked(self) -> None:
        """Có tên: tạo thư mục SKU thật, chuyển ảnh sang, ghi concept.json + listing."""
        self.item = store.read(self.d) or self.item
        if self.item.get("book") and Path(self.item["book"]).is_dir():
            return
        meta = self.meta()
        kdir = products.root(Path(self.cfg["projects_dir"]), "wall_grid") / self.item.get("group", "lam-theo-mau")
        book = layout.new_book_dir(kdir, meta["title"], f"clone-{self.item['id']}", "wall_grid")
        work = self.d / "work"
        for sub in (layout.RAW, f"{layout.SYSTEM}/ky_thuat"):
            src = work / sub
            if src.is_dir():
                dst = book / sub
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.iterdir():
                    shutil.move(str(f), str(dst / f.name))
        refs_dst = layout.tech(book) / "anh_mau"
        refs_dst.mkdir(parents=True, exist_ok=True)
        for f in store.refs(self.d):
            shutil.copy2(f, refs_dst / f.name)
        write_concept(book, meta, self.year, self.item)
        self.status(book=str(book), title=meta["title"], sku=layout.book_sku(book))
        self.on_event(f"  ✔ Thư mục cuốn: {book}")

    # -------------------------------------------------------------- phiên B: 12 trang lịch
    def grid_work(self, s, name: str) -> None:
        """Vẽ trang lịch cho các tháng ĐÃ có artwork. Chạy sớm (song song lúc tài khoản kia còn vẽ artwork 11-12 /
        đặt tên / vẽ bìa) thì vẽ 10 tháng đầu trước, rồi chờ artwork 11-12 ngay trong phiên (GRID_WAIT_S) để nhắn
        tiếp; quá lâu thì dừng bước, bộ điều phối chạy lại phần còn thiếu sau."""
        first_round = [m for m in range(1, 11)]
        idle = 0
        self._watch(s, name, "trang lịch")
        while self.missing("g"):
            ready = [m for m in self.missing("g") if self.done(f"m{m:02d}")]
            if not ready:                               # artwork tháng còn thiếu chưa vẽ xong: chờ trong phiên
                waited = 0.0
                while not ready and waited < GRID_WAIT_S:
                    if store.read(self.d).get("art_state") not in (None, "running"):
                        break                           # bước artwork đã dừng (xong / lỗi): khỏi chờ nữa
                    self.status(stage=f"vẽ trang lịch ({12 - len(self.missing('g'))}/12) - chờ artwork tháng "
                                      + ", ".join(str(m) for m in self.missing("g")))
                    time.sleep(GRID_POLL_S)
                    waited += GRID_POLL_S
                    ready = [m for m in self.missing("g") if self.done(f"m{m:02d}")]
                if not ready:
                    return                              # bộ điều phối chạy lại bước này khi artwork xong
            arts = {m: self.done(f"m{m:02d}") for m in range(1, 13)}
            missing = ready
            self.status(stage=f"vẽ trang lịch ({12 - len(self.missing('g'))}/12)")
            if not getattr(s, "grid_started", False):
                done = [m for m in range(1, 13) if m not in missing]
                if not done:
                    batch = [m for m in missing if m in first_round]
                    prompt, attach = prompts.grid_prompt(self.year, batch), [arts[m] for m in batch]
                else:                                   # phiên mới vẽ bù: ảnh 1 = một trang đã xong (giữ bố cục)
                    batch = missing[:REF_BATCH - 1]
                    prompt = prompts.grid_prompt(self.year, batch, layout_ref=True)
                    attach = [self.done(f"g{done[0]:02d}")] + [arts[m] for m in batch]
                s.grid_started = True
            else:
                batch = missing[:REF_BATCH]
                prompt, attach = prompts.grid_continue(self.year, batch), [arts[m] for m in batch]
            turn = s.ask_images(prompt, len(batch), attach=attach)
            self._take_grid(s, turn, batch, name)
            if set(missing) <= set(self.missing("g")):    # cả lượt không thêm được trang nào
                idle += 1
                if turn.problem and not turn.images:
                    raise turn.problem
                if idle >= 2:
                    raise TempError(f"ChatGPT không vẽ thêm trang lịch (còn thiếu {self.missing('g')})")
            else:
                idle = 0

    def _take_grid(self, s, turn, batch: list[int], name: str) -> None:
        from ..imagegen.generate import accept_grid_page
        left = [m for m in batch if self.done(f"g{m:02d}") is None]
        failed: dict[int, str] = {}
        with ocr_memo():                                  # mỗi trang OCR một lần, so với nhiều tháng không đọc lại
            for pos, data in enumerate(turn.images):
                if not left:
                    break
                check_dir = Path(self.d) / "ocr"        # file soát OCR tạm: nằm ngoài thư mục bị chuyển
                check_dir.mkdir(parents=True, exist_ok=True)
                tmp = check_dir / f"grid_check_{pos:02d}{session.ext_of(data)}"
                tmp.write_bytes(data)
                # ChatGPT hay trả trang lệch thứ tự: thử tháng đúng vị trí trước, rồi lần lượt các tháng còn thiếu
                expected = batch[pos] if pos < len(batch) and batch[pos] in left else left[0]
                month, first_why = None, None
                for m in [expected] + [x for x in left if x != expected]:
                    why = accept_grid_page(tmp, self.year, m)
                    if why is None:
                        month = m
                        break
                    first_why = first_why or why
                if month is None:
                    failed.setdefault(expected, first_why or "sai lịch")
                    self._reject(data, f"grid-{expected:02d}")
                    self.on_event(f"[{name}] trang lịch ảnh {pos + 1}: OCR loại - không khớp tháng còn thiếu nào "
                                  f"(so với tháng {expected}: {(first_why or '')[:80]})")
                else:
                    with self.lock:
                        session.save(data, self.raw(f"g{month:02d}"))
                    left.remove(month)
                    failed.pop(month, None)
                    note = "" if month == expected else f" (ảnh {pos + 1} về lệch thứ tự)"
                    self.on_event(f"[{name}] trang lịch tháng {month}: OCR đạt, đã lưu{note}")
                tmp.unlink(missing_ok=True)
        self.on_event(f"[{name}] trang lịch: còn thiếu {len(self.missing('g'))}/12")
        if turn.problem and isinstance(turn.problem, (QuotaExceeded, ThirdPartyIPRefused)) and left:
            raise turn.problem
        for m in list(left):                              # vẽ lại ngay trong phiên các trang OCR loại
            for i in range(GRID_REDO):
                reason = failed.get(m, "thiếu trang")
                self.on_event(f"[{name}] trang lịch tháng {m}: {reason[:100]} - vẽ lại ({i + 1}/{GRID_REDO})")
                redo = s.ask_images(prompts.grid_redo(self.year, m, reason[:160]), 1)
                if redo.images:
                    (Path(self.d) / "ocr").mkdir(parents=True, exist_ok=True)
                    tmp = Path(self.d) / "ocr" / f"grid_check_{m:02d}{session.ext_of(redo.images[0])}"
                    tmp.write_bytes(redo.images[0])
                    why = accept_grid_page(tmp, self.year, m)
                    tmp.unlink(missing_ok=True)
                    if why is None:
                        with self.lock:
                            session.save(redo.images[0], self.raw(f"g{m:02d}"))
                        break
                    failed[m] = why
                    self._reject(redo.images[0], f"grid-{m:02d}")
                elif redo.problem:
                    raise redo.problem

    # -------------------------------------------------------------- dựng sách
    def finish(self, plus: list[str]) -> dict:
        from .. import pipeline
        book = self.dir
        repair_month_captions(book)
        anchor = layout.raw(book) / "anchor"
        if job_done(book, "anchor") is None:          # ảnh neo của trang chính = bìa (bảng màu trang + QC màu)
            src = self.done("cover") or self.done("m01")
            shutil.copy2(src, anchor.with_suffix(src.suffix))
        cfg = copy.deepcopy(self.cfg)                   # mockup AI: dùng mọi tài khoản, mức thinking mặc định
        self.status(stage="upscale")
        pipeline.upscale_concept(book, self.on_event)
        self.status(stage="dựng trang in + mockup + listing")
        return pipeline.finish_book(book, cfg, printify=False, on_event=self.on_event)


def s_has_art(s) -> bool:
    """Phiên hiện tại đã thấy các artwork chưa (vừa vẽ trong phiên này)."""
    return bool(getattr(s, "has_art", False))


# ------------------------------------------------------------------ concept + listing từ JSON ChatGPT trả
def month_captions(months) -> list[str]:
    """Accept plain captions or explicitly named caption objects, never stringify data."""
    if not isinstance(months, list) or len(months) != 12:
        raise ValueError('"months" must have exactly 12 captions')
    out = []
    for i, entry in enumerate(months, 1):
        if isinstance(entry, dict):
            label = entry.get("month")
            if label is not None and str(label).strip().lower() not in (str(i), prompts.MONTHS[i - 1].lower()):
                raise ValueError(f'"months[{i}]" has an incorrect month; use January to December order')
            entry = entry.get("caption")
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f'"months[{i}]" must be a non-empty caption string')
        out.append(short_caption(entry))
    return out


CAPTION_WORDS = 5


def short_caption(text: str) -> str:
    """Chú thích tháng in dưới ảnh nhỏ ở bìa sau + trên trang: ngắn như trang chính (2-5 từ). ChatGPT hay viết
    "Rebel Heart — A relaxed portrait in ..." -> lấy phần tên trước dấu gạch / hai chấm, tối đa 5 từ."""
    import re
    head = re.split(r"\s+[—–-]\s+|:\s+|\.\s", text.strip(), maxsplit=1)[0].strip(" .,;:—–-")
    words = head.split()
    return " ".join(words[:CAPTION_WORDS]) or text.strip()[:30]


def repair_month_captions(book: Path) -> None:
    """Repair previously adopted clone books from their original structured metadata."""
    path = layout.concept_file(book)
    concept = json.loads(path.read_text(encoding="utf-8"))
    if concept.get("source") != "clone":
        return
    meta = json.loads((layout.tech(book) / "clone_meta.json").read_text(encoding="utf-8"))
    captions = month_captions(meta.get("months"))
    changed = False
    for month in concept["months"]:
        caption = captions[int(month["month"]) - 1]
        if month.get("subtitle") != caption:
            month["subtitle"] = caption
            changed = True
    if changed:
        backup = path.with_name("concept_before_caption_fix.json")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_meta(d) -> list[str]:
    from ..publish.etsy_listing import validate
    if not isinstance(d, dict):
        return ["the answer must be a JSON object"]
    errors = []
    for k in ("title", "subtitle", "style_name", "keyword"):
        if not isinstance(d.get(k), str) or not d[k].strip():
            errors.append(f'"{k}" is missing')
    if isinstance(d.get("title"), str) and len(d["title"]) > 60:
        errors.append("title must be at most 60 characters")
    try:
        month_captions(d.get("months"))
    except ValueError as e:
        errors.append(str(e))
    errors += validate({"title": d.get("etsy_title"), "description": d.get("etsy_description"), "tags": d.get("tags")})
    return [e.replace("title is", "etsy_title is").replace("description ", "etsy_description ") for e in errors]


def write_concept(book: Path, meta: dict, year: int, item: dict) -> dict:
    from ..publish.etsy_listing import DETAILS_HTML, DETAILS_TEXT, to_html
    from ..publish.listing import write_listing_txt
    concept = {
        "title": meta["title"].strip(), "angle_id": f"clone-{item['id']}", "source": "clone",
        "keyword": meta.get("keyword", ""), "buyer": meta.get("buyer", ""), "year": year, "market": "US",
        "product": "wall_grid", "listing_style": "etsy", "content_type": "none", "grid_function": "standard",
        "frame_type": "clone",
        "style": {"name": meta.get("style_name", ""), "family": "clone", "grid_mode": "ai_page",
                  "mockup_mode": item.get("mockup_mode") if item.get("mockup_mode") in ("ai", "template") else "ai",
                  "palette": {"paper": "#F7F3EA", "title": "#2E2A26", "text": "#2E2A26", "accent": "#8A6B4E",
                              "grid_line": "#CFC6B6"},
                  "fonts": {"title": "Cormorant Garamond", "body": "Montserrat", "numbers": "Lora"}},
        "cover": {"title": meta["title"].strip(), "subtitle": meta.get("subtitle", "").strip()},
        "months": [{"month": i + 1, "subtitle": c, "content": {}} for i, c in enumerate(month_captions(meta.get("months")))],
        "back_cover": {"line": meta.get("subtitle", "").strip()},
        "listing": {"seo_title": meta["etsy_title"].strip(), "tags": [str(t).strip().lower() for t in meta["tags"]]},
    }
    layout.concept_file(book).write_text(json.dumps(concept, ensure_ascii=False, indent=2), encoding="utf-8")
    text = meta["etsy_description"].strip()
    listing = {"title": meta["etsy_title"].strip(), "description": to_html(text) + DETAILS_HTML,
               "description_text": text + "\n\n" + DETAILS_TEXT, "tags": concept["listing"]["tags"], "style": "etsy"}
    time.sleep(0.01)                                       # listing mới hơn concept -> pipeline coi listing là mới
    layout.listing_file(book).write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")
    write_listing_txt(book, listing)
    return concept


# ------------------------------------------------------------------ cả hàng đợi
def run_book(cfg: dict, d: Path, accts: Accounts, plus: list[str], stop: threading.Event | None = None,
             on_event=print, *, step: str = "all", on_grid_ready=None) -> dict:
    """Chạy cả cuốn hoặc một bước; bước thành công trả `next` cho bộ điều phối.
    step "art": artwork + tên + bìa (on_grid_ready(d) được gọi ngay khi đủ artwork 1-10 để trang lịch chạy SONG SONG
    trên tài khoản khác). step "grid": trang lịch các tháng đã có artwork - còn tháng chưa có artwork thì trả
    next="grid_wait" để chạy lại sau. step "finish": dựng sách."""
    b = Book(cfg, d, on_event)
    b.status(status="running", reason="")
    try:
        if stop and stop.is_set():
            raise StageFailed("người dùng dừng")
        art_acc = b.item.get("art_account", "")
        if step in ("all", "art"):
            b.on_grid_ready = on_grid_ready
            b.status(art_state="running")
            try:
                art_acc = run_stage(accts, f"{d.name} artwork", b.art_work, stop=stop,
                                    prefer=lambda: (b.item.get("art_chat") or {}).get("account")) \
                    if (b.missing("m") or b.meta() is None or b.done("cover") is None or not b.item.get("book")) \
                    else art_acc
                b._adopt() if b.meta() else None
            except BaseException:
                b.status(art_state="failed")
                raise
            b.status(art_account=art_acc, art_state="done")
            if step == "art":
                b.status(stage="chờ trang lịch" if b.missing("g") else "chờ hậu kỳ")
                return {"next": "grid"}
        if step in ("all", "grid"):
            if b.missing("g"):
                run_stage(accts, f"{b.item.get('sku') or d.name} trang lịch", b.grid_work,
                          avoid={art_acc} if art_acc else None, stop=stop)
            if step == "grid":
                if b.missing("g"):                      # còn tháng chưa có artwork: chạy lại khi artwork xong
                    return {"next": "grid_wait"}
                b.status(stage="chờ hậu kỳ")
                return {"next": "finish"}
        if stop and stop.is_set():
            raise StageFailed("người dùng dừng")
        res = b.finish(plus)
        ok = bool(res.get("ok"))
        b.status(status="done" if ok else "failed", stage=res.get("stage", ""),
                 reason="" if ok else str(res.get("reason", ""))[:300])
        return res
    except BookRejected as e:
        b.status(status="rejected", reason=f"ChatGPT từ chối 3 lần (TM/bản quyền/nội dung nhạy cảm): {e}"[:300])
    except StageFailed as e:
        b.status(status="failed", reason=str(e)[:300])
    except Exception as e:  # noqa: BLE001 - lỗi lạ của một cuốn không làm dừng cả hàng đợi
        b.status(status="failed", reason=f"{type(e).__name__}: {str(e)[:250]}")
    on_event(f"✘ {d.name}: {b.item.get('reason', '')}")
    return {"ok": False, "status": b.item.get("status"), "reason": b.item.get("reason", "")}


def run_queue(cfg: dict, on_event=print, stop: threading.Event | None = None, accts: Accounts | None = None,
              plus: list[str] | None = None) -> list[dict]:
    """Điều phối từng bước, ưu tiên trang lịch sẵn sàng và tách hậu kỳ khỏi worker AI.
    Quét thêm cuốn khi đang chạy; giới hạn số cuốn dở để hậu kỳ chậm không làm tích hàng vô hạn."""
    projects = Path(cfg["projects_dir"])
    todo = store.pending(projects)
    if not todo:
        on_event("Hàng đợi trống - không có cuốn nào cần làm")
        return []
    plus = plus if plus is not None else plus_accounts(cfg, on_event=on_event)
    if not plus:
        on_event("✘ Không có tài khoản ChatGPT Plus nào còn hạn - trang này chỉ dùng tài khoản Plus")
        for d in todo:
            store.write(d, status="failed", reason="không có tài khoản Plus còn hạn")
        return []
    on_event(f"▶ {len(todo)} cuốn, chỉ dùng {len(plus)} tài khoản Plus: {', '.join(plus)}")
    accts = accts or Accounts(cfg, plus, on_event)
    # Artwork and grid borrow the same accounts: idle capacity is never reserved
    # for a stage with no ready work. The global pool still enforces RAM/Chrome limits.
    workers = max(1, len(set(plus)))
    finish_workers = max(1, min(2, int(cfg.get("finish_workers") or 1)))
    max_inflight = workers * 2 + finish_workers
    on_event(f"▶ Chia pool động: {workers} luồng artwork/trang lịch dùng chung tài khoản Plus, "
             f"{finish_workers} luồng hậu kỳ; trần Chrome/RAM do pool chung điều phối. "
             "Ưu tiên trang lịch đã sẵn sàng, không giữ cặp acc cố định cho từng cuốn.")
    claimed: set[str] = set()
    active: set[str] = set()
    ready = deque()
    finishing = deque()
    results: list[dict] = []
    early: "queue.Queue[Path]" = queue.Queue()      # cuốn vừa đủ artwork 1-10 (báo từ luồng artwork)
    stage: dict[str, dict] = {}                     # mục -> {"art": ..., "grid": ..., "fail": (status, reason)}

    def record(d, res):
        active.discard(d.name)
        st = stage.pop(d.name, {})
        if not res.get("ok") and st.get("fail"):    # lỗi của bước kia: ghi lại đúng trạng thái + lý do cuối
            status, reason = st["fail"]
            store.write(d, status=status or "failed", reason=reason)
        results.append(res)
        on_event(f"◆ CUỐN {'XONG' if res.get('ok') else 'LỖI'}: {store.read(d).get('sku') or d.name}")

    def cancelled(d):
        store.write(d, status="failed", reason="người dùng dừng; chạy tiếp để làm phần còn thiếu")
        stage.pop(d.name, None)
        active.discard(d.name)
        results.append({"ok": False})
        on_event(f"◆ CUỐN LỖI: {store.read(d).get('sku') or d.name}")

    def queue_grid(d):
        st = stage.setdefault(d.name, {})
        if st.get("grid") in (None, "wait"):
            st["grid"] = "queued"
            ready.appendleft((d, "grid"))           # trang lịch sẵn sàng: ưu tiên trước cuốn mới

    def settle(d):
        """Cả hai bước đã dừng: đủ thì hậu kỳ, không thì ghi lỗi."""
        st = stage.get(d.name, {})
        art, grid = st.get("art"), st.get("grid")
        if art in ("queued", "running") or grid in ("queued", "running"):
            return
        if art == "done" and grid == "done":
            finishing.append((d, "finish"))
        elif art == "done" and grid == "wait":
            queue_grid(d)
        elif art == "failed" or grid == "failed":
            record(d, {"ok": False})

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clone-ai") as ai, \
            ThreadPoolExecutor(max_workers=finish_workers, thread_name_prefix="clone-finish") as post:
        jobs = {}
        while True:
            while True:                                 # trang lịch chạy sớm cho cuốn vừa đủ artwork 1-10
                try:
                    d = early.get_nowait()
                except queue.Empty:
                    break
                if d.name in stage and not (stop and stop.is_set()):
                    on_event(f"▶ {store.read(d).get('title') or d.name}: đủ artwork 1-10 - vẽ trang lịch song song")
                    queue_grid(d)
            stopping = stop and stop.is_set()
            if stopping:
                for q in (ready, finishing):
                    while q:
                        d, _ = q.popleft()
                        if not any(dd.name == d.name for dd, _, _ in jobs.values()):
                            cancelled(d)
            else:
                # Rescan throughout the run, even while all earlier books are busy.
                for d in store.pending(projects):
                    if len(active) >= max_inflight:
                        break
                    if d.name not in claimed:
                        claimed.add(d.name)
                        active.add(d.name)
                        stage[d.name] = {"art": "queued", "grid": None}
                        store.write(d, status="running", stage="chờ pool artwork", reason="")
                        ready.append((d, "art"))
                for q, executor, capacity, kind in ((ready, ai, workers, "ai"),
                                                     (finishing, post, finish_workers, "finish")):
                    free = capacity - sum(k == kind for _, _, k in jobs.values())
                    for _ in range(min(free, len(q))):
                        d, step = q.popleft()
                        st = stage.setdefault(d.name, {})
                        if step in ("art", "grid"):
                            st[step] = "running"
                        cb = early.put if step == "art" else None
                        future = executor.submit(run_book, cfg, d, accts, plus, stop, on_event, step=step,
                                                 on_grid_ready=cb)
                        jobs[future] = (d, step, kind)
            if not jobs:
                if not ready and not finishing and early.empty():
                    break
                time.sleep(0.05)
                continue
            completed, _ = wait(jobs, timeout=0.25, return_when=FIRST_COMPLETED)
            for future in completed:
                d, step, kind = jobs.pop(future)
                try:
                    res = future.result()
                except Exception as e:  # isolate even failures before Book initialization
                    store.write(d, status="failed", reason=f"{type(e).__name__}: {str(e)[:250]}")
                    res = {"ok": False, "status": "failed", "reason": f"{type(e).__name__}: {str(e)[:250]}"}
                st = stage.setdefault(d.name, {})
                next_step = res.get("next")
                if step == "finish":
                    record(d, res)
                    continue
                if next_step and stop and stop.is_set():
                    if step == "art":
                        st["art"] = "failed"
                    else:
                        st["grid"] = "failed"
                    st.setdefault("fail", ("failed", "người dùng dừng; chạy tiếp để làm phần còn thiếu"))
                    settle(d)
                    continue
                if step == "art":
                    if next_step == "grid":
                        st["art"] = "done"
                        if st.get("grid") is None:
                            queue_grid(d)
                        else:
                            settle(d)
                    else:
                        st["art"] = "failed"
                        st["fail"] = (res.get("status") or "failed", res.get("reason", ""))
                        if st.get("grid") == "queued":      # trang lịch chưa bắt đầu: bỏ luôn
                            for item in list(ready):
                                if item[0].name == d.name and item[1] == "grid":
                                    ready.remove(item)
                            st["grid"] = "failed"
                        settle(d)
                elif step == "grid":
                    if next_step == "finish":
                        st["grid"] = "done"
                    elif next_step == "grid_wait":
                        st["grid"] = "wait"
                    else:
                        st["grid"] = "failed"
                        st["fail"] = (res.get("status") or "failed", res.get("reason", ""))
                    settle(d)
    ok = sum(1 for r in results if r.get("ok"))
    on_event(f"🏁 Xong {ok}/{len(results)} cuốn")
    return results


def resume_book(book: Path, cfg: dict, on_event=print) -> dict | None:
    """Nút "Làm tiếp" của trang chính cho cuốn clone còn thiếu ảnh: tìm mục hàng đợi của cuốn (angle_id clone-<id>),
    đưa về chờ chạy, rồi chạy riêng phần vẽ (artwork / trang lịch) của mục đó. Hậu kỳ do trang chính làm tiếp."""
    try:
        concept = json.loads(layout.concept_file(book).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    item_id = str(concept.get("angle_id") or "").removeprefix("clone-")
    try:
        d = store.item_dir(cfg["projects_dir"], item_id)
    except ValueError:
        return None
    if not (d / "item.json").is_file():
        return None
    plus = plus_accounts(cfg, on_event=on_event)
    if not plus:
        on_event("✘ Không có tài khoản ChatGPT Plus nào còn hạn - clone sản phẩm chỉ dùng tài khoản Plus")
        return None
    store.write(d, status="running", reason="")
    accts = Accounts(cfg, plus, on_event)
    b = Book(cfg, d, on_event)
    try:
        if b.missing("m") or b.meta() is None or b.done("cover") is None:
            run_stage(accts, f"{d.name} artwork", b.art_work,
                      prefer=lambda: (b.item.get("art_chat") or {}).get("account"))
        if b.missing("g"):
            run_stage(accts, f"{b.item.get('sku') or d.name} trang lịch", b.grid_work)
        store.write(d, status="running", stage="dựng trang in + mockup + listing")
        return {"ok": True}
    except (StageFailed, BookRejected) as e:
        store.write(d, status="rejected" if isinstance(e, BookRejected) else "failed", reason=str(e)[:300])
        return {"ok": False}
