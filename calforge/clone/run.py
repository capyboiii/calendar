"""Chạy hàng đợi "Làm theo ảnh mẫu" - CHỈ dùng tài khoản ChatGPT Plus còn hạn.

Mỗi cuốn:
  1. Phiên A (tài khoản Plus X): đính ảnh tham chiếu -> 10 artwork -> nhắn tiếp lấy 2 artwork còn lại -> hỏi chữ lấy
     tên cuốn + listing Etsy -> vẽ bìa. Có tên thì chuyển sang thư mục SKU thật.
  2. Phiên B (tài khoản Plus khác nếu có): đính 10 artwork -> 10 trang lịch -> đính 2 artwork cuối -> 2 trang nữa.
     OCR soát từng trang; trang sai vẽ lại ngay trong phiên.
  3. Dựng sách bằng pipeline của trang chính: upscale, 2 khổ in + PDF, mockup AI (mọi tài khoản, thinking mặc định), listing.txt.
Lỗi giữa chừng (hết lượt, mạng, tài khoản chết, lỗi server): ảnh đã về được giữ, phiên mới chỉ vẽ phần còn thiếu.
"""
from __future__ import annotations

import copy
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
            fails += 1
            last = f"{type(e).__name__}: {str(e)[:200]}"
            accts.on_event(f"[{name}] {label}: lỗi ({last[:140]}) - thử phiên mới ({fails}/{MAX_SESSIONS})")
            if "không mở được" in last or "Target" in last:
                accts.pool.rest(name, IMAGE, 300, last)
        finally:
            accts.release(name)
        if fails >= MAX_SESSIONS:
            raise StageFailed(f"{label}: chưa xong sau {fails} phiên ({last[:160]})")


def _month_named(reason: str) -> int | None:
    """Lý do OCR 'sai tên tháng: trang ghi "February" ...' -> 2 (không có thì None)."""
    import re
    m = re.search(r'trang ghi "([A-Za-z]+)"', reason or "")
    names = [n.lower() for n in prompts.MONTHS]
    return names.index(m.group(1).lower()) + 1 if m and m.group(1).lower() in names else None


def _server_side(text: str) -> bool:
    """Lỗi tạm do phía ChatGPT (server báo lỗi, tab kẹt không phản hồi, lượt xong mà không ra ảnh)."""
    low = text.lower()
    return any(k in low for k in ("chatgpt báo lỗi", "tab kẹt", "trả lời xong mà không có ảnh", "chưa ra ảnh"))


# ------------------------------------------------------------------ một cuốn
class Book:
    def __init__(self, cfg: dict, d: Path, on_event=print):
        self.cfg, self.d, self.on_event = cfg, d, on_event
        self.item = store.read(d)
        self.year = int(self.item.get("year") or 2027)

    @property
    def dir(self) -> Path:
        """Thư mục đang chứa ảnh: thư mục SKU nếu đã có tên, chưa thì work/ của mục."""
        book = self.item.get("book")
        if book and Path(book).is_dir():
            return Path(book)
        return self.d / "work"

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
    def art_work(self, s, name: str) -> None:
        refs = store.refs(self.d)
        missing = self.missing("m")
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
            idle = 0
            while self.missing("m"):
                missing = self.missing("m")
                self.status(stage=f"vẽ artwork ({12 - len(missing)}/12)")
                before = len(missing)
                turn = s.ask_images(prompts.art_continue(missing), len(missing))
                self._take_art(turn, name)
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
            session.save(data, self.raw(f"m{m:02d}"))
            got += 1
        self.on_event(f"[{name}] artwork: +{got} ảnh, còn thiếu {len(self.missing('m'))}")
        if turn.problem and (not got or isinstance(turn.problem, (QuotaExceeded, ThirdPartyIPRefused))):
            raise turn.problem

    def _reject(self, data: bytes, tag: str) -> None:
        d = layout.tech(self.dir) / "anh_bi_loai"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tag}-{time.strftime('%H%M%S')}{session.ext_of(data)}").write_bytes(data)

    def _ask_meta(self, s, attach_art: bool) -> None:
        from ..ideation.extract import extract_json
        ask = prompts.meta_prompt(self.year)
        if attach_art:                                  # phiên mới: ChatGPT chưa thấy ảnh -> đính 10 artwork đầu
            arts = [self.done(f"m{m:02d}") for m in range(1, 11)]
            s.w._attach(s.page, arts)
            ask = ("I have attached 10 of the 12 artworks of this calendar (January to October).\n" + ask)
        for attempt in range(3):
            answer = s.ask_text(ask)
            try:
                data = extract_json(answer)
            except Exception:  # noqa: BLE001
                data = None
            errors = validate_meta(data)
            if not errors:
                layout.tech(self.dir).mkdir(parents=True, exist_ok=True)
                (layout.tech(self.dir) / "clone_meta.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                                                      encoding="utf-8")
                self.on_event(f"  ✔ Tên cuốn: {data['title']}")
                return
            self.on_event(f"  ⚠ JSON tên/listing chưa đạt ({'; '.join(errors)[:140]}) - nhờ ChatGPT sửa")
            ask = prompts.meta_repair(errors)
        raise TempError("ChatGPT chưa trả được tên cuốn + listing hợp lệ")

    def _adopt(self) -> None:
        """Có tên: tạo thư mục SKU thật, chuyển ảnh sang, ghi concept.json + listing."""
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
        arts = {m: self.done(f"m{m:02d}") for m in range(1, 13)}
        first_round = [m for m in range(1, 11)]
        idle = 0
        while self.missing("g"):
            missing = self.missing("g")
            self.status(stage=f"vẽ trang lịch ({12 - len(missing)}/12)")
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
            if set(missing) == set(self.missing("g")):    # cả lượt không thêm được trang nào
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
        for data in turn.images:
            if not left:
                break
            tmp = layout.tech(self.dir) / f"grid_check_{left[0]:02d}{session.ext_of(data)}"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            month, why = None, accept_grid_page(tmp, self.year, left[0])   # thường về đúng thứ tự
            if why is None:
                month = left[0]
            else:                                         # tiêu đề ghi tháng khác (về lệch thứ tự): soát đúng tháng đó
                other = _month_named(why)
                if other in left and other != left[0] and accept_grid_page(tmp, self.year, other) is None:
                    month = other
            if month is None:
                failed.setdefault(left[0], why or "sai lịch")
                self._reject(data, f"grid-{left[0]:02d}")
                self.on_event(f"[{name}] trang lịch ảnh {len(batch) - len(left) + 1}: OCR loại ({(why or '')[:90]})")
            else:
                session.save(data, self.raw(f"g{month:02d}"))
                left.remove(month)
                failed.pop(month, None)
                self.on_event(f"[{name}] trang lịch tháng {month}: OCR đạt, đã lưu")
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
                    tmp = layout.tech(self.dir) / f"grid_check_{m:02d}{session.ext_of(redo.images[0])}"
                    tmp.write_bytes(redo.images[0])
                    why = accept_grid_page(tmp, self.year, m)
                    tmp.unlink(missing_ok=True)
                    if why is None:
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
    months = d.get("months")
    if not isinstance(months, list) or len([m for m in months if str(m).strip()]) != 12:
        errors.append('"months" must have exactly 12 captions')
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
        "months": [{"month": i + 1, "subtitle": str(c).strip(), "content": {}} for i, c in enumerate(meta["months"])],
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
             on_event=print) -> dict:
    b = Book(cfg, d, on_event)
    b.status(status="running", reason="")
    try:
        art_acc = run_stage(accts, f"{d.name} artwork", b.art_work, stop=stop,
                            prefer=lambda: (b.item.get("art_chat") or {}).get("account")) \
            if (b.missing("m") or b.meta() is None or b.done("cover") is None or not b.item.get("book")) else ""
        b._adopt() if b.meta() else None
        if b.missing("g"):
            run_stage(accts, f"{b.item.get('sku') or d.name} trang lịch", b.grid_work,
                      avoid={art_acc} if art_acc else None, stop=stop)
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
    return {"ok": False}


def run_queue(cfg: dict, on_event=print, stop: threading.Event | None = None, accts: Accounts | None = None,
              plus: list[str] | None = None) -> list[dict]:
    """Chạy hàng đợi. Cuốn thêm vào TRONG LÚC đang chạy cũng được làm luôn (mỗi luồng xong một cuốn lại bốc cuốn
    tiếp theo từ hàng đợi), không phải chờ lượt sau."""
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
    claimed: set[str] = set()
    lock = threading.Lock()
    results: list[dict] = []

    def next_item() -> Path | None:
        with lock:
            for d in store.pending(projects):
                if d.name not in claimed:
                    claimed.add(d.name)
                    return d
        return None

    def worker() -> None:
        while not (stop and stop.is_set()):
            d = next_item()
            if d is None:
                return
            res = run_book(cfg, d, accts, plus, stop, on_event)
            with lock:
                results.append(res)
            on_event(f"◆ CUỐN {'XONG' if res.get('ok') else 'LỖI'}: {store.read(d).get('sku') or d.name}")

    workers = max(1, min(len(todo) + 2, len(plus)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="clone") as ex:
        for f in [ex.submit(worker) for _ in range(workers)]:
            f.result()
    ok = sum(1 for r in results if r.get("ok"))
    on_event(f"🏁 Xong {ok}/{len(results)} cuốn")
    return results
