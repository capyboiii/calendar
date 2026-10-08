"""Máy chủ Web CalForge Studio (dùng Python standard library)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import config, layout, products
from ..render.pages import PRESET_NAMES, resolve_grid_preset

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Task:
    def __init__(self, task_id: str, cmd: list[str], description: str, action: str = "", params: dict | None = None):
        self.id = task_id
        self.action = action
        self.params = params or {}
        self.cmd = cmd
        self.description = description
        self.status = "running"  # running, success, failed
        self.logs: list[str] = []
        self.log_offset = 0
        self.start_time = time.time()
        self.end_time: float | None = None
        self.return_code: int | None = None
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    def append_log(self, text: str):
        with self.lock:
            self.logs.append(text)
            if len(self.logs) > 3000:
                self.logs.pop(0)
                self.log_offset += 1

    def to_dict(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "description": self.description,
                "action": self.action,
                "params": self.params,
                "status": self.status,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "return_code": self.return_code,
                "logs": self.logs[max(0, since - self.log_offset):],
                "total_logs": self.log_offset + len(self.logs),
            }


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # tác vụ con không bật cửa sổ đen


def _console_python() -> str:
    """App mở bằng pythonw.exe (không có cửa sổ) - tác vụ con cần python.exe để đọc được log."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return sys.executable


class TaskManager:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.lock = threading.Lock()

    def start_task(self, args: list[str], description: str, action: str = "", params: dict | None = None) -> str:
        task_id = f"t_{int(time.time() * 1000)}"
        # -u: không đệm stdout, để log chảy trực tiếp lên UI (không dồn về cuối)
        cmd = [_console_python(), "-u", "-m", "calforge"] + args
        task = Task(task_id, cmd, description, action, params)
        with self.lock:
            self.tasks[task_id] = task

        def _worker():
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["PYTHONUNBUFFERED"] = "1"
            try:
                task.append_log(f"🚀 Bắt đầu: python -m calforge {' '.join(args)}\n")
                p = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                    creationflags=NO_WINDOW,
                )
                task.process = p
                for line in p.stdout:
                    task.append_log(line.rstrip())
                p.wait()
                task.return_code = p.returncode
                if task.status != "stopped":
                    task.status = "success" if p.returncode == 0 else "failed"
                task.end_time = time.time()
                task.append_log(f"\n🏁 Hoàn thành (mã thoát: {p.returncode}) trong {task.end_time - task.start_time:.1f}s")
            except Exception as e:
                task.status = "failed"
                task.end_time = time.time()
                task.append_log(f"\n❌ Lỗi hệ thống: {e}")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return task_id

    def get_task(self, task_id: str, since: int = 0) -> dict | None:
        with self.lock:
            task = self.tasks.get(task_id)
            return task.to_dict(since) if task else None

    def running(self, include_login: bool = False, include_clone: bool = False) -> Task | None:
        """Việc chính đang chạy. Không tính: cửa sổ đăng nhập một tài khoản (không được chặn batch), và lượt
        "Clone sản phẩm" (chạy SONG SONG với batch theo ý tưởng - hai bên chia tài khoản bằng khoá trong profile)."""
        with self.lock:
            return next((t for t in self.tasks.values() if t.status == "running"
                         and (include_login or t.action != "login")
                         and (include_clone or t.action != "clone")), None)

    def clone_running(self) -> Task | None:
        with self.lock:
            return next((t for t in self.tasks.values() if t.status == "running" and t.action == "clone"), None)

    def login_running(self, profile: str) -> Task | None:
        with self.lock:
            return next((t for t in self.tasks.values() if t.status == "running" and t.action == "login"
                         and (t.params or {}).get("profile") == profile), None)

    def stop_task(self, task_id: str) -> bool:
        """Dừng tác vụ + mọi tiến trình con (Chrome của Playwright) để lần chạy sau không vướng profile."""
        with self.lock:
            task = self.tasks.get(task_id)
        if not task or task.status != "running" or not task.process:
            return False
        task.status = "stopped"
        task.append_log("\n⏹ Người dùng bấm Dừng")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(task.process.pid), "/T", "/F"], capture_output=True, check=False,
                           creationflags=NO_WINDOW)
        else:
            task.process.kill()
        return True

    def list_tasks(self) -> list[dict]:
        with self.lock:
            return [t.to_dict() for t in sorted(self.tasks.values(), key=lambda x: x.start_time, reverse=True)[:10]]


TASK_MANAGER = TaskManager()
CLONE_MAX_BODY = 120 * 1024 * 1024


def _clone_cover(book: str | None) -> str:
    """Ảnh đại diện của cuốn: ảnh quảng cáo bìa nếu đã có, chưa thì tranh bìa AI."""
    if not book or not Path(book).is_dir():
        return ""
    for pattern in ("preview/01_*.jpg", "_he_thong/anh_ai/cover.*", "_he_thong/anh_ai/m01.*"):
        hit = sorted(Path(book).glob(pattern))
        if hit:
            return str(hit[0])
    return ""


def _clone_items() -> dict:
    """Hàng đợi trang "Làm theo ảnh mẫu" + tài khoản Plus (đọc nhãn gói đã lưu, không mở Chrome) + việc đang chạy."""
    from ..clone import store
    from ..llm import accounts, plan
    from ..llm.pool import read_dead
    cfg = config.load()
    # Không còn việc nào đang chạy (lượt clone bị Dừng / tắt tool / tiến trình chết) mà cuốn vẫn ghi "running":
    # dấu cũ - chuyển về "Bị dở" để giao diện không báo "Đang làm" mãi và bỏ / làm tiếp được.
    if not TASK_MANAGER.running(include_clone=True):
        store.mark_stopped(cfg["projects_dir"])
    pdir = accounts.get_profiles_dir(cfg)
    plus, unknown = [], []
    for d in sorted(p for p in pdir.iterdir() if p.is_dir() and not p.name.startswith(".")) if pdir.exists() else []:
        if read_dead(d) or not accounts.has_chatgpt_session(d):
            continue
        info = plan.read(d)
        if info is None:
            unknown.append(d.name)
        elif info.get("plan") in ("plus", "pro") and info.get("active", True) and not info.get("expired"):
            plus.append({"name": d.name, "expires": info.get("expires_date", ""), "days_left": info.get("days_left")})
    items = store.items(Path(cfg["projects_dir"]))
    for it in items:
        d = store.root(cfg["projects_dir"]) / it.get("id", "")
        it["ref_paths"] = [str(p) for p in store.refs(d)]
        it["cover"] = _clone_cover(it.get("book"))
    task = next(({k: v for k, v in t.items() if k != "logs"} for t in TASK_MANAGER.list_tasks()
                 if t.get("action") == "clone"), None)
    return {"items": items, "plus": plus, "unknown": unknown, "task": task}


def _free_profile(name: str) -> str:
    """Trước khi mở cửa sổ đăng nhập: profile đang bị Chrome giữ thì
    - Chrome thuộc một batch/tác vụ đang chạy -> không giật tài khoản của batch, trả lời dễ hiểu;
    - Chrome mồ côi (tool cũ tắt ngang, cửa sổ bị khuất...) -> tự đóng rồi cho đăng nhập.
    Trả về "" nếu đã sẵn sàng."""
    from ..llm import accounts
    udir = accounts.get_profiles_dir(config.load()) / name
    if not udir.exists() or not accounts.is_profile_locked(udir):
        return ""
    with TASK_MANAGER.lock:
        running = {t.process.pid: t for t in TASK_MANAGER.tasks.values()
                   if t.status == "running" and t.process and t.action != "login"}
    owners = accounts.profile_users(udir, set(running)) if running else set()
    if owners:
        t = running[next(iter(owners))]
        return (f"'{name}' đang được dùng trong việc đang chạy ({t.description}). Chờ việc đó xong, "
                "hoặc bấm Tạm dừng ở Hàng đợi rồi đăng nhập lại.")
    accounts.close_profile_chrome(udir)
    if accounts.is_profile_locked(udir):
        return f"Không đóng được Chrome đang mở '{name}'. Hãy tắt hết cửa sổ Chrome của tài khoản này rồi thử lại."
    return ""


def _unfinished_books() -> list[dict]:
    """Cuốn đã vẽ đủ tranh nhưng chưa hoàn thiện (bị dừng giữa chừng / thiếu mockup), trừ cuốn đang được xử lý
    hoặc đã nằm trong hàng đợi."""
    from ..ideation.pipeline import slugify
    from ..pipeline import needs_finishing
    cfg = config.load()
    root = Path(cfg["projects_dir"])
    busy_books, busy_kw = set(), set()
    for it in batch_queue().snapshot()["items"]:
        if it["status"] not in ("queued", "running"):
            continue
        p = it["params"]
        if p.get("concept"):
            busy_books.add((ROOT / p["concept"]).resolve())
        elif p.get("keyword"):
            busy_kw.add((products.root(root, p.get("product") or products.DEFAULT) / slugify(p["keyword"])).resolve())
    out = []
    for b in layout.books(root):
        if b.resolve() in busy_books or b.parent.resolve() in busy_kw or not needs_finishing(b):
            continue
        try:
            title = json.loads(layout.concept_file(b).read_text(encoding="utf-8")).get("title") or b.name
        except (OSError, ValueError):
            title = b.name
        out.append({"path": _rel(b), "title": title})
    return out


def _sku_of(b: Path) -> str:
    """SKU gốc của cuốn: mã lưu sẵn (cuốn mới) hoặc mã tính lại đúng như lúc xuất CSV (cuốn cũ đã có listing)."""
    sku = layout.book_sku(b)
    if sku:
        return sku
    try:
        from ..publish.shop_csv import shop_settings
        from ..sku_rename import legacy_sku
        return legacy_sku(b, shop_settings(config.load()))
    except Exception:  # noqa: BLE001 - cuốn chưa có listing: chưa có SKU
        return ""


def _done_at(b: Path) -> str:
    """Lúc cuốn làm xong: mốc "updated" trong status.json (ghi khi xong bước cuối). Không dùng giờ sửa file vì đổi
    tên / sửa đường dẫn hàng loạt làm mọi cuốn cùng một giờ, mất thứ tự mới -> cũ."""
    try:
        st = json.loads(layout.status_file(b).read_text(encoding="utf-8"))
        if isinstance(st, dict) and str(st.get("updated", ""))[:4].isdigit():
            return str(st["updated"])[:16]
    except (OSError, ValueError):
        pass
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(layout.status_file(b).stat().st_mtime))
    except OSError:
        return ""


def _shop_books() -> list[dict]:
    """Các cuốn đã xong (đưa lên web được) + trạng thái R2/CSV, cho hộp chọn cuốn của nút Đẩy R2 + xuất CSV."""
    from ..publish import r2
    from ..publish.shop_csv import ready_books
    cfg = config.load()
    out = []
    for b in ready_books(Path(cfg["projects_dir"])):
        try:
            concept = json.loads(layout.concept_file(b).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            concept = {}
        st = r2.read_state(b)
        previews = sorted(layout.listing(b).glob("*.jpg"))
        out.append({
            "path": _rel(b), "title": concept.get("title") or b.name, "keyword": b.parent.name,
            "sku": _sku_of(b),
            "product": products.product_id(concept), "cover": _vrel(previews[0]) if previews else "",
            "pushed_at": st.get("pushed_at", ""), "exported_at": st.get("exported_at", ""),
            "exported_csv": st.get("exported_csv", ""),
            "calendaria_exported_at": st.get("calendaria_exported_at", ""),
            "calendaria_exported_csv": st.get("calendaria_exported_csv", ""),
            "done_at": _done_at(b),
        })
    out.sort(key=lambda x: x["done_at"], reverse=True)
    return out


def _book_arg(params: dict) -> Path:
    root = (ROOT / config.load()["projects_dir"]).resolve()
    target = (ROOT / str(params.get("concept", ""))).resolve()
    if not target.is_relative_to(root) or not layout.is_book(target):   # chỉ nhận thư mục cuốn nằm TRONG projects
        raise ValueError("Không tìm thấy cuốn này.")
    return target


def run_args(params: dict) -> tuple[list[str], str]:
    """Lệnh cho một việc trong hàng đợi: batch mới (mặc định), "produce" = làm tiếp một cuốn, "redo" = vẽ lại trang."""
    kind = params.get("action") or "run"
    if kind == "produce":
        target = _book_arg(params)
        _reject_terminal_book(target)
        return ["produce", str(target), "--no-printify"], f"Làm tiếp: {target.name}"
    if kind == "finish":
        target = _book_arg(params)
        _reject_terminal_book(target)
        redo = params.get("redo_previews")
        if isinstance(redo, list):                  # gen lại đúng các ảnh quảng cáo được chọn
            names = [str(n) for n in redo]
            have = {p.stem for p in layout.listing(target).glob("*.jpg")}
            bad = [n for n in names if not re.fullmatch(r"\d\d_[a-z0-9_]+", n) or n not in have]
            if not names or bad:
                raise ValueError(f"Không có ảnh quảng cáo: {', '.join(bad) or '(chưa chọn)'}")
            args = ["finish", str(target)]
            for n in names:
                args += ["--redo-preview", n]
            return args, f"Gen lại {len(names)} ảnh quảng cáo: {target.name}"
        args = ["finish", str(target)] + (["--redo-previews"] if redo else [])
        return args, (f"Làm lại ảnh quảng cáo: {target.name}" if redo else f"Hoàn thiện: {target.name}")
    if kind == "redo":
        target = _book_arg(params)
        _reject_terminal_book(target)
        pages = [p for p in (params.get("pages") or []) if isinstance(p, str)]
        if not pages:
            raise ValueError("Chưa chọn trang nào để vẽ lại.")
        known = {"cover", "grid"} | {f"{k}{m:02d}" for k in "mg" for m in range(1, 13)}
        bad = [p for p in pages if p not in known]
        if bad:
            raise ValueError(f"Trang không hợp lệ: {', '.join(bad)}")
        return ["redo", str(target), "--pages", ",".join(pages)], f"Vẽ lại {len(pages)} trang: {target.name}"
    keyword = str(params.get("keyword", "")).strip()
    if not keyword:
        raise ValueError("Nhập chủ đề trước đã.")
    cmd_args = ["run", keyword, "--no-printify"]
    if params.get("pick"):
        cmd_args += ["--pick", params["pick"]]
    batch = int(params.get("batch_size") or 1)
    if batch > 1:
        cmd_args += ["--auto", str(min(batch, 20))]
    if params.get("grid_preset"):
        cmd_args += ["--grid-preset", params["grid_preset"]]
    if params.get("family"):
        from ..ideation.catalog import family_ids
        if params["family"] not in family_ids():
            raise ValueError("Phong cách tranh không hợp lệ.")
        cmd_args += ["--family", params["family"]]
    if params.get("product") in products.PRODUCTS:
        cmd_args += ["--product", params["product"]]
    if params.get("resume"):
        cmd_args += ["--resume"]
    if params.get("listing_style") == "etsy":
        cmd_args += ["--listing-style", "etsy"]
    if params.get("grid_mode") in products.GRID_MODES and params.get("product", products.DEFAULT) == "wall_grid":
        cmd_args += ["--grid-mode", params["grid_mode"]]
        if params["grid_mode"] == "ai_page" and params.get("mockup_mode") in products.MOCKUP_MODES:
            cmd_args += ["--mockup-mode", params["mockup_mode"]]
    desc = f"Chạy trọn gói {batch} cuốn cho keyword: {keyword}" if batch > 1 else f"Chạy trọn gói cho keyword: {keyword}"
    return cmd_args, desc


def _reject_terminal_book(target: Path) -> None:
    """Cuốn đã bị loại do TM/bản quyền là trạng thái cuối: mọi nút chạy lại đều phải từ chối."""
    try:
        st = json.loads(layout.status_file(target).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if st.get("terminal"):
        raise ValueError(st.get("reason") or "Cuốn này đã bị loại và không thể chạy lại.")


def _batch_result(params: dict) -> tuple[int, int, bool]:
    """(số đạt, tổng, còn việc có thể làm lại) cho hàng đợi."""
    if (params.get("action") or "run") != "run":
        try:
            st = json.loads(layout.status_file(_book_arg(params)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0, 1, True
        ok = bool(st.get("ok") and st.get("stage") in ("listing", "printify"))
        return (1 if ok else 0), 1, bool(not ok and not st.get("terminal"))
    from ..ideation.pipeline import slugify
    cfg = config.load()
    kdir = products.root(cfg["projects_dir"], params.get("product") or products.DEFAULT) / slugify(params["keyword"])
    b = _read_batch(kdir) or {}
    rows = b.get("report") or []
    target = int(b.get("target") or len(rows))
    concepts = list(b.get("concepts") or [])
    retryable = len(concepts) < target
    for rel in concepts:
        try:
            st = json.loads(layout.status_file(kdir / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            retryable = True
            continue
        done = bool(st.get("ok") and st.get("stage") in ("listing", "printify"))
        if not done and not st.get("terminal"):
            retryable = True
    return sum(1 for r in rows if r.get("ok")), target, retryable


_QUEUE = None


def batch_queue():
    global _QUEUE
    if _QUEUE is None:
        from .batch_queue import BatchQueue
        cfg = config.load()
        _QUEUE = BatchQueue(TASK_MANAGER, Path(cfg["projects_dir"]) / ".hang_doi.json", run_args, _batch_result)
    return _QUEUE


class StudioHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            return self._handle_api_get(path, query)

        # Serve static assets or index.html for root
        if path == "/huong-dan":               # hướng dẫn sử dụng (HUONG_DAN.html ở gốc repo)
            return self._serve_file(ROOT / "HUONG_DAN.html", "text/html; charset=utf-8")
        if path == "/" or path == "/index.html":
            return self._serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/clone":                   # trang cũ "Làm theo ảnh mẫu": nay là "Clone sản phẩm" ở trang chính
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/?mode=clone")
            self.end_headers()
            return None
        
        static_file = STATIC_DIR / path.lstrip("/")
        if static_file.is_file() and str(static_file.resolve()).startswith(str(STATIC_DIR.resolve())):
            return super().do_GET()

        return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _cross_site(self) -> str:
        """Lý do chặn nếu yêu cầu POST đến từ trang web khác (CSRF): trang lạ mở trong trình duyệt không được tự bấm
        "mở file", đổi khoá R2, chạy batch... trên máy chủ cục bộ này. Rỗng = cho qua."""
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if site and site not in ("same-origin", "none"):
            return f"Sec-Fetch-Site={site}"
        origin = self.headers.get("Origin")
        if origin:
            o = urllib.parse.urlparse(origin)
            if o.hostname not in ("127.0.0.1", "localhost", "::1") or o.port != self.server.server_address[1]:
                return f"Origin={origin}"
        # trang lạ chỉ gửi được "simple request" (text/plain, form) mà không qua bước hỏi trước (preflight)
        if "application/json" not in (self.headers.get("Content-Type") or "").lower():
            return "Content-Type phải là application/json"
        return ""

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            why = self._cross_site()
            if why:
                try:                                   # đọc bỏ phần thân để kết nối đóng gọn
                    self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 1 << 20))
                except (OSError, ValueError):
                    pass
                return self._send_json({"error": f"Từ chối yêu cầu không đến từ giao diện CalForge ({why})"},
                                       status=HTTPStatus.FORBIDDEN)
            return self._handle_api_post(path)
        return self._send_json({"error": "Method not allowed"}, status=HTTPStatus.METHOD_NOT_ALLOWED)

    def _handle_api_get(self, path: str, query: dict[str, list[str]]):
        if path == "/api/projects":
            return self._api_list_projects()
        if path == "/api/concept":
            rel_path = query.get("path", [""])[0]
            return self._api_get_concept(rel_path)
        if path == "/api/file":
            rel_path = query.get("path", [""])[0]
            return self._api_get_file(rel_path)
        if path == "/api/products":
            return self._send_json({"products": [{"id": k, "name": v["name"]} for k, v in products.PRODUCTS.items()],
                                    "default": products.DEFAULT})
        if path == "/api/styles":
            return self._api_get_styles()
        if path == "/api/thumb":
            return self._api_thumb(query.get("path", [""])[0], int(query.get("w", [480])[0]))
        if path == "/api/task":
            task_id = query.get("id", [""])[0]
            since = int(query.get("since", [0])[0])
            return self._api_get_task(task_id, since)
        if path == "/api/tasks":
            return self._send_json({"tasks": TASK_MANAGER.list_tasks()})
        if path == "/api/r2":
            cfg = config.load()
            r2 = cfg.get("r2") or {}
            sec = str(r2.get("secret_access_key") or "")
            return self._send_json({
                "account_id": r2.get("account_id", ""), "access_key_id": r2.get("access_key_id", ""),
                "bucket": r2.get("bucket", ""), "public_url": r2.get("public_url", ""),
                "prefix": r2.get("prefix", "calendars"),
                "secret_set": bool(sec), "secret_hint": ("…" + sec[-4:]) if len(sec) > 8 else ""})
        if path == "/api/unfinished":
            return self._send_json({"books": _unfinished_books()})

        if path == "/api/shop/books":
            return self._send_json({"books": _shop_books()})

        if path == "/api/queue":
            return self._send_json(batch_queue().snapshot())

        if path == "/api/clone/items":
            return self._send_json(_clone_items())
        if path == "/api/accounts/plan-check/status":
            from ..llm import plan
            return self._send_json(plan.status())
        if path == "/api/accounts/bulk-login/status":
            from ..llm import bulk_login
            return self._send_json(bulk_login.status())
        if path == "/api/accounts":
            from ..llm import accounts
            cfg = config.load()
            return self._send_json({
                "profiles_dir": str(accounts.get_profiles_dir(cfg)),
                "accounts": accounts.list_accounts(cfg),
            })

        return self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)

    def _handle_api_post(self, path: str):
        if path == "/api/action":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception as e:
                return self._send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)

            action = body.get("action")
            params = body.get("params", {})
            concept_path = params.get("concept", "")

            cmd_args = []
            desc = ""

            if action == "run":
                try:
                    cmd_args, desc = run_args(params)
                except ValueError as e:
                    return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)

            elif action == "ideate":
                keyword = params.get("keyword", "").strip()
                if not keyword:
                    return self._send_json({"error": "Keyword is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["ideate", keyword]
                if params.get("style"):
                    cmd_args += ["--style", params["style"]]
                if params.get("family"):
                    cmd_args += ["--family", params["family"]]
                if params.get("more"):
                    cmd_args += ["--more"]
                if params.get("grid_preset"):
                    cmd_args += ["--grid-preset", params["grid_preset"]]
                desc = f"Lên ý tưởng cho keyword: {keyword}"

            elif action == "render":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["render", concept_path]
                desc = f"Render 26 trang in: {Path(concept_path).name}"

            elif action == "upscale":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["upscale", concept_path]
                desc = f"Upscale ảnh Real-ESRGAN: {Path(concept_path).name}"

            elif action == "gen":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["gen", concept_path]
                if params.get("profiles"):
                    cmd_args += ["--profiles", params["profiles"]]
                desc = f"Sinh tranh ChatGPT: {Path(concept_path).name}"

            elif action == "listing":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["listing", concept_path]
                desc = f"Tạo listing: {Path(concept_path).name}"

            elif action == "printify":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["printify", concept_path]
                if params.get("publish"):
                    cmd_args += ["--publish"]
                desc = f"Đẩy lên Printify: {Path(concept_path).name}"

            elif action == "produce":
                if not concept_path:
                    return self._send_json({"error": "Concept path is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["produce", concept_path, "--no-printify"]
                if params.get("publish"):
                    cmd_args += ["--publish"]
                desc = f"Sản xuất từ concept: {Path(concept_path).name}"

            elif action == "shop":
                cmd_args = ["shop"]
                export_format = params.get("format", "printify")
                if export_format not in ("printify", "calendaria"):
                    return self._send_json({"error": "Định dạng CSV không hợp lệ"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args += ["--format", export_format]
                books = params.get("books")
                if books is not None:
                    root = (ROOT / config.load()["projects_dir"]).resolve()
                    picked = []
                    for b in books:
                        target = (ROOT / str(b)).resolve()
                        if not str(target).startswith(str(root)) or not layout.is_book(target):
                            return self._send_json({"error": f"Không tìm thấy cuốn: {b}"}, status=HTTPStatus.BAD_REQUEST)
                        picked.append(str(target))
                    if not picked:
                        return self._send_json({"error": "Chưa chọn cuốn nào."}, status=HTTPStatus.BAD_REQUEST)
                    for b in picked:
                        cmd_args += ["--book", b]
                desc = f"Đẩy lên R2 + xuất CSV ({len(books)} cuốn)" if books is not None else "Đẩy lên R2 + xuất CSV"

            elif action == "login":
                profile_name = params.get("profile", "").strip()
                if not profile_name:
                    return self._send_json({"error": "Profile name is required"}, status=HTTPStatus.BAD_REQUEST)
                old = TASK_MANAGER.login_running(profile_name)
                if old:   # bấm lại = muốn cửa sổ mới (cửa sổ cũ bị khuất/kẹt): đóng cửa sổ cũ rồi mở lại
                    TASK_MANAGER.stop_task(old.id)
                    time.sleep(2)
                busy_msg = _free_profile(profile_name)
                if busy_msg:
                    return self._send_json({"error": busy_msg}, status=HTTPStatus.CONFLICT)
                cmd_args = ["login", profile_name]
                desc = f"Mở trình duyệt đăng nhập ChatGPT: {profile_name}"

            else:
                return self._send_json({"error": f"Unknown action: {action}"}, status=HTTPStatus.BAD_REQUEST)

            busy = TASK_MANAGER.running()
            if busy and action != "login":
                return self._send_json({"error": f"Đang chạy việc khác: {busy.description}. Chờ xong hoặc bấm Dừng."},
                                       status=HTTPStatus.CONFLICT)
            task_id = TASK_MANAGER.start_task(cmd_args, desc, action, params)
            return self._send_json({"task_id": task_id, "description": desc, "status": "started"})

        if path.startswith("/api/queue/"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception as e:
                return self._send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
            q = batch_queue()
            op = path.rsplit("/", 1)[-1]
            try:
                if op == "add":
                    q.add(body.get("params") or {})
                elif op == "remove":
                    q.remove(str(body.get("id", "")))
                elif op == "move":
                    q.move(str(body.get("id", "")), int(body.get("delta", 0)))
                elif op == "pause":
                    q.pause()
                elif op == "resume":
                    q.resume()
                elif op == "clear":
                    q.clear_finished()
                else:
                    return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except ValueError as e:
                return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            except OSError as e:           # không ghi được hàng đợi (hết đĩa, file bị khoá): báo rõ, máy chủ không sập
                return self._send_json({"error": f"Không lưu được hàng đợi: {e}"},
                                       status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return self._send_json(q.snapshot())

        if path == "/api/shutdown":
            # nút "Tắt tool": dừng mọi việc đang chạy (kể cả Chrome ngầm) rồi tắt máy chủ
            for t in TASK_MANAGER.list_tasks():
                if t.get("status") == "running":
                    TASK_MANAGER.stop_task(t["id"])
            self._send_json({"ok": True})
            threading.Timer(0.5, lambda: os._exit(0)).start()
            return None

        if path in ("/api/open", "/api/task/stop"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception as e:
                return self._send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
            if path == "/api/task/stop":
                batch_queue().stopped_by_user(str(body.get("id", "")))
                ok = TASK_MANAGER.stop_task(str(body.get("id", "")))
                if not TASK_MANAGER.clone_running():          # vừa dừng lượt clone: cuốn dở về "Bị dở", bỏ được
                    from ..clone import store
                    store.mark_stopped(config.load()["projects_dir"])
                return self._send_json({"ok": ok})
            target = (ROOT / str(body.get("path", "")).lstrip("/\\")).resolve()
            # CHỈ mở THƯ MỤC nằm trong tool: mở file bằng os.startfile = chạy file đó (python.exe, .bat...)
            if not target.is_relative_to(ROOT.resolve()) or not target.is_dir():
                return self._send_json({"error": "Không tìm thấy thư mục"}, status=HTTPStatus.NOT_FOUND)
            _open_in_explorer(target)
            return self._send_json({"ok": True})

        if path == "/api/r2":
            # Khoá R2 lưu vào calforge.json (gitignore). Secret để trống = giữ secret cũ; không bao giờ trả lại secret.
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception:
                return self._send_json({"error": "Dữ liệu không hợp lệ"}, status=HTTPStatus.BAD_REQUEST)
            keep = ("account_id", "access_key_id", "secret_access_key", "bucket", "public_url", "prefix")
            data = {k: str(body[k]).strip() for k in keep if k in body and str(body[k]).strip()}
            config.save_section("r2", data)
            return self._send_json({"ok": True})

        if path.startswith("/api/clone/"):
            return self._api_clone(path.rsplit("/", 1)[-1])

        if path == "/api/accounts/plan-check":
            # Mở ngầm lần lượt từng tài khoản (không đang dùng) để đọc gói Free/Plus + ngày hết hạn.
            from ..llm import plan
            started = plan.start_check(config.load())
            return self._send_json({"ok": True, "started": started, **plan.status()})

        if path == "/api/accounts/bulk-login":
            # Mật khẩu chỉ đi qua RAM của máy chủ tới cửa sổ Chrome: không ghi log, không trả về, không lưu đĩa.
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception:
                return self._send_json({"error": "Dữ liệu không hợp lệ"}, status=HTTPStatus.BAD_REQUEST)
            busy = TASK_MANAGER.running(include_clone=True)
            if busy and busy.action != "login":
                return self._send_json({"error": f"Đang chạy: {busy.description}. Chờ xong rồi đăng nhập."},
                                       status=HTTPStatus.CONFLICT)
            from ..llm import bulk_login
            try:
                res = bulk_login.start(str(body.pop("creds", "")), config.load())
            except (ValueError, RuntimeError) as e:
                return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
            finally:
                body.clear()
            return self._send_json(res)

        if path == "/api/accounts/create":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                name = body.get("name", "").strip()
                from ..llm import accounts
                cfg = config.load()
                p = accounts.create_account(name, cfg)
                return self._send_json({"ok": True, "name": name, "path": str(p)})
            except Exception as e:
                return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)

        if path == "/api/accounts/delete":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                name = body.get("name", "").strip()
                from ..llm import accounts
                cfg = config.load()
                accounts.delete_account(name, cfg)
                return self._send_json({"ok": True, "name": name, "deleted": True})
            except Exception as e:
                return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)

        return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _api_list_projects(self):
        cfg = config.load()
        projects_dir = ROOT / cfg.get("projects_dir", "projects")
        if not projects_dir.exists():
            return self._send_json({"projects": []})

        results = []
        # projects/<loại lịch>/<chủ đề>/<cuốn>; thư mục chủ đề cũ nằm thẳng dưới projects/ vẫn đọc được
        folders = {v["folder"]: k for k, v in products.PRODUCTS.items()}
        kw_dirs = []
        for top in sorted(projects_dir.iterdir()):
            if not top.is_dir() or top.name.startswith((".", "_")):
                continue
            if top.name in folders:
                kw_dirs += [(d, top.name, folders[top.name]) for d in sorted(top.iterdir())
                            if d.is_dir() and not d.name.startswith((".", "_"))]
            else:
                kw_dirs.append((top, "", None))
        for kw_dir, group, group_product in kw_dirs:

            angles_file = layout.angles_file(kw_dir)
            angles = []
            if angles_file.exists():
                try:
                    angles = json.loads(angles_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            concepts = []
            for c_dir in sorted(kw_dir.iterdir()):
                if not c_dir.is_dir() or not layout.is_book(c_dir):
                    continue

                concept_data = {}
                try:
                    concept_data = json.loads(layout.concept_file(c_dir).read_text(encoding="utf-8"))
                except Exception:
                    pass

                status_data = {}
                if layout.status_file(c_dir).exists():
                    try:
                        status_data = json.loads(layout.status_file(c_dir).read_text(encoding="utf-8"))
                    except Exception:
                        pass

                # Grid mặc định có một nền AI dùng chung cho cả 12 tháng.
                required_art = {"anchor", "cover", *[f"m{i:02d}" for i in range(1, 13)]}
                if products.ai_grid(concept_data) and resolve_grid_preset(concept_data) == "art_matched":
                    required_art.add("grid")
                def _required_count(directory: Path) -> int:
                    return len({f.stem for f in directory.glob("*.*") if f.is_file() and f.stem in required_art}) \
                        if directory.exists() else 0
                raw_count = _required_count(layout.raw(c_dir))
                final_count = _required_count(layout.final(c_dir))
                render_count = len([f for f in layout.print_dir(c_dir).glob("*.png") if f.is_file()])
                has_digital = layout.printable_file(c_dir).exists()

                concepts.append({
                    "id": c_dir.name,
                    "sku": _sku_of(c_dir),
                    "path": str(c_dir.relative_to(ROOT)).replace("\\", "/"),
                    "title": (concept_data.get("cover") or {}).get("title") or c_dir.name,
                    "subtitle": (concept_data.get("cover") or {}).get("subtitle", ""),
                    "product": products.product_id(concept_data),
                    "product_name": products.get(concept_data)["name"],
                    "year": concept_data.get("year", cfg.get("year", 2027)),
                    "family": (concept_data.get("style") or {}).get("family", ""),
                    "grid_preset": resolve_grid_preset(concept_data),
                    "grid_preset_name": PRESET_NAMES.get(resolve_grid_preset(concept_data), ""),
                    "grid_selection": (json.loads(layout.tech(c_dir, "grid_selection.json").read_text(encoding="utf-8"))
                                       if layout.tech(c_dir, "grid_selection.json").exists()
                                       else concept_data.get("grid_selection", {})),
                    "status": status_data,
                    "raw_count": raw_count,
                    "final_count": final_count,
                    "art_total": len(required_art),
                    "render_count": render_count,
                    "has_digital": has_digital,
                    **_book_outputs(c_dir),
                })

            results.append({
                "keyword": kw_dir.name,
                "group": group,
                "product": group_product,
                "path": str(kw_dir.relative_to(ROOT)).replace("\\", "/"),
                "total_angles": len(angles),
                "concepts": concepts,
                "batch": _read_batch(kw_dir),
            })

        return self._send_json({"projects": results, "year": cfg.get("year", 2027), "market": cfg.get("market", "US")})

    def _api_get_concept(self, rel_path: str):
        if not rel_path:
            return self._send_json({"error": "Path required"}, status=HTTPStatus.BAD_REQUEST)
        
        target = (ROOT / rel_path).resolve()
        if not _in_projects(target) or not target.is_dir():
            return self._send_json({"error": "Invalid concept path"}, status=HTTPStatus.BAD_REQUEST)

        concept_file = layout.concept_file(target)
        if not concept_file.exists():
            return self._send_json({"error": "concept.json not found"}, status=HTTPStatus.NOT_FOUND)

        def _read_json(f: Path):
            if f.exists():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return None

        def _read_text(f: Path):
            return f.read_text(encoding="utf-8") if f.exists() else ""

        def _list_files(f_dir: Path):
            if not f_dir.exists() or not f_dir.is_dir():
                return []
            return sorted(f.name for f in f_dir.iterdir() if f.is_file())

        concept_data = _read_json(concept_file) or {}
        status_data = _read_json(layout.status_file(target)) or {}
        palette_data = _read_json(layout.tech(target, "palette.json")) or {}
        listing_data = _read_json(layout.listing_file(target)) or {}
        jobs_data = _read_json(layout.tech(target, "jobs.json")) or []
        printify_data = _read_json(layout.tech(target, "printify.json")) or {}
        grid_selection = _read_json(layout.tech(target, "grid_selection.json")) or concept_data.get("grid_selection", {})

        render_report = _read_text(layout.render_file(target, "report.md"))
        concept_report = _read_text(layout.tech(target, "concept_report.md"))

        files = {
            "art_raw": _list_files(layout.raw(target)),
            "art_raw_v": {f.name: f.stat().st_mtime_ns for f in layout.raw(target).iterdir() if f.is_file()}
            if layout.raw(target).is_dir() else {},
            "art_final": _list_files(layout.final(target)),
            "render_printify": _list_files(layout.print_dir(target)),
            "render_printify_14x11_5": _list_files(layout.print_dir(target, "printify_wall_14x11_5")),
            "listing_images": _list_files(layout.listing(target)),
            "render_proof": _list_files(layout.tech(target, "proof_11x8.5")),
            "render_digital": [f for f in _list_files(layout.print_dir(target)) if f.endswith(".pdf")],
            "grid_options": _list_files(layout.tech(target, "grid_options")),
        }

        return self._send_json({
            "path": rel_path.replace("\\", "/"),
            "name": target.name,
            "grid_preset": resolve_grid_preset(concept_data),
            "grid_preset_name": PRESET_NAMES.get(resolve_grid_preset(concept_data), ""),
            "concept": concept_data,
            "status": status_data,
            "palette": palette_data,
            "listing": listing_data,
            "jobs": jobs_data,
            "printify": printify_data,
            "grid_selection": grid_selection,
            "render_report": render_report,
            "render_validation": _read_json(layout.render_file(target, "validation.json")) or {},
            "folders": {"raw": layout.RAW, "final": layout.FINAL, "print": layout.PRINT["printify_wall_11x8_5"],
                        "listing": layout.LISTING, "system": layout.SYSTEM, "tech": layout.TECH},
            "concept_report": concept_report,
            "files": files,
        })

    def _api_get_file(self, rel_path: str):
        if not rel_path:
            return self._send_json({"error": "Path required"}, status=HTTPStatus.BAD_REQUEST)

        # Allow files in projects/ or formats/
        clean_rel = Path(rel_path.lstrip("/\\"))
        target = (ROOT / clean_rel).resolve()
        
        # Security check: must reside inside ROOT
        if not _in_projects(target) or not target.is_file():   # chỉ file lịch trong projects (không lộ khoá R2, cookie)
            return self._send_json({"error": "File not found or forbidden"}, status=HTTPStatus.NOT_FOUND)

        mime, _ = mimetypes.guess_type(str(target))
        if not mime:
            if target.suffix.lower() == ".pdf":
                mime = "application/pdf"
            elif target.suffix.lower() in (".md", ".txt"):
                mime = "text/plain; charset=utf-8"
            elif target.suffix.lower() == ".json":
                mime = "application/json; charset=utf-8"
            else:
                mime = "application/octet-stream"

        return self._serve_file(target, mime, download=target.suffix.lower() == ".csv")

    def _api_thumb(self, rel_path: str, width: int):
        """Ảnh thu nhỏ (JPEG) cho lưới kết quả; lưu tạm theo mtime để lần sau trả ngay."""
        rel_path = rel_path.split("?v=")[0]               # "?v=<mtime>": chỉ để trình duyệt không dùng ảnh cũ
        target = (ROOT / rel_path.lstrip("/\\")).resolve()
        if not _in_projects(target) or not target.is_file():   # chỉ file lịch trong projects (không lộ khoá R2, cookie)
            return self._send_json({"error": "File not found or forbidden"}, status=HTTPStatus.NOT_FOUND)
        width = max(120, min(width, 1600))
        cache = ROOT / ".cache" / "thumbs"
        key = f"{hashlib.sha1(str(target).encode()).hexdigest()[:16]}_{int(target.stat().st_mtime)}_{width}.jpg"
        out = cache / key
        if not out.exists():
            from PIL import Image
            cache.mkdir(parents=True, exist_ok=True)
            with Image.open(target) as im:
                im = im.convert("RGB")
                im.thumbnail((width, width * 2))
                im.save(out, quality=85)
        return self._serve_file(out, "image/jpeg")

    def _api_get_styles(self):
        styles_file = ROOT / "data" / "style_families.json"
        if styles_file.exists():
            return self._send_json(json.loads(styles_file.read_text(encoding="utf-8")))
        return self._send_json({"families": []})

    def _api_get_task(self, task_id: str, since: int):
        task = TASK_MANAGER.get_task(task_id, since)
        if not task:
            return self._send_json({"error": "Task not found"}, status=HTTPStatus.NOT_FOUND)
        return self._send_json(task)

    def _serve_file(self, file_path: Path, content_type: str, download: bool = False):
        try:
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            if download:                       # tải về đúng tên file (kể cả tên có dấu) thay vì "file"
                from urllib.parse import quote
                self.send_header("Content-Disposition",
                                 f"attachment; filename=\"{file_path.name.encode('ascii', 'ignore').decode()}\"; "
                                 f"filename*=UTF-8''{quote(file_path.name)}")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"error": str(e)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api_clone(self, op: str):
        """Trang "Làm theo ảnh mẫu": thêm cuốn (ảnh tham chiếu base64), xoá, chạy lại, bắt đầu chạy hàng đợi."""
        import base64
        from ..clone import store
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > CLONE_MAX_BODY:
                self.rfile.read(min(length, 1 << 20))
                return self._send_json({"error": "Ảnh tải lên quá lớn (tối đa ~120 MB mỗi lần)"},
                                       status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
        except Exception as e:
            return self._send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
        cfg = config.load()
        projects = Path(cfg["projects_dir"])
        try:
            if op == "add":
                images = []
                for im in body.get("images") or []:
                    data = str(im.get("data", ""))
                    images.append((str(im.get("name", "anh.png"))[:80],
                                   base64.b64decode(data.split(",", 1)[-1], validate=False)))
                store.add(projects, images, group=str(body.get("group", "")), year=int(body.get("year") or 2027),
                          mockup_mode=str(body.get("mockup_mode") or "ai"))
            elif op == "remove":
                store.remove(projects, str(body.get("id", "")), running_now=bool(TASK_MANAGER.clone_running()))
            elif op == "retry":
                store.retry(projects, str(body.get("id", "")))
            elif op == "start":
                # chạy SONG SONG với batch theo ý tưởng (hai bên chia tài khoản bằng khoá trong profile); chỉ chặn khi
                # đã có một lượt clone đang chạy
                busy = TASK_MANAGER.clone_running()
                if busy:
                    return self._send_json({"error": f"Đang chạy việc khác: {busy.description}. Chờ xong hoặc bấm Dừng."},
                                           status=HTTPStatus.CONFLICT)
                show = bool(body.get("show"))
                tid = TASK_MANAGER.start_task(["clone-run"] + (["--show"] if show else []),
                                              "Làm theo ảnh mẫu (chỉ tài khoản Plus)"
                                              + (" - hiện Chrome" if show else ""), "clone")
                return self._send_json({"task_id": tid, **_clone_items()})
            else:
                return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
        except OSError as e:
            return self._send_json({"error": f"Không lưu được: {e}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
        return self._send_json(_clone_items())

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # noqa: A002 - tắt log request (không in body/mật khẩu)
        # Tắt log mặc định của SimpleHTTPRequestHandler cho đỡ rác console
        pass


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def _vrel(p: Path) -> str:
    """Đường dẫn ảnh kèm phiên bản (thời điểm sửa): ảnh bị ghi đè cùng tên (vd ảnh quảng cáo AI thay mockup code)
    có URL mới, trình duyệt không hiện ảnh cũ trong bộ nhớ."""
    try:
        return f"{_rel(p)}?v={p.stat().st_mtime_ns}"
    except OSError:
        return _rel(p)


def _book_outputs(c_dir: Path) -> dict:
    """Những thứ người bán cần thấy: ảnh bìa, 5 ảnh preview, PDF in tại nhà, listing."""
    previews = sorted(layout.listing(c_dir).glob("*.jpg")) if layout.listing(c_dir).exists() else []
    cover = previews[0] if previews else layout.print_dir(c_dir) / "front_cover.png"
    pdfs = []
    for label in dict.fromkeys(layout.PRINT.values()):      # nhiều loại lịch dùng chung thư mục khổ
        fid = next(k for k, v in layout.PRINT.items() if v == label)
        f = layout.printable_file(c_dir, fid)
        if f.exists():
            pdfs.append({"label": label, "path": _rel(f)})
    listing = {}
    try:
        listing = json.loads(layout.listing_file(c_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"cover": _vrel(cover) if cover.exists() else "", "previews": [_vrel(p) for p in previews],
            "pdfs": pdfs, "listing": listing}


def _in_projects(target: Path) -> bool:
    """File / thư mục nằm TRONG thư mục projects (lịch đã làm). Giao diện chỉ cần đọc ở đây; file khác của tool
    (calforge.json có khoá R2, .chrome-profiles có cookie tài khoản...) không bao giờ được trả ra."""
    try:
        root = Path(config.load()["projects_dir"]).resolve()
        return Path(target).resolve().is_relative_to(root)
    except (OSError, KeyError, ValueError):
        return False


def _open_in_explorer(target: Path) -> None:
    if os.name == "nt":
        os.startfile(str(target))  # noqa: S606 - chỉ mở thư mục trong dự án
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])


def _read_batch(kw_dir: Path) -> dict:
    """Batch gần nhất của keyword (projects/<kw>/_he_thong/batch.json) - bảng báo cáo trên UI."""
    try:
        b = json.loads(layout.batch_file(kw_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: b.get(k) for k in ("target", "started", "finished", "report", "concepts")}


def _already_running(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"{url}/api/tasks", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class _Server(ThreadingHTTPServer):
    # Windows cho 2 tiến trình cùng giữ 1 cổng khi bật reuse -> tắt để không chạy 2 tool chồng nhau
    allow_reuse_address = False


def run_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True, opener=None):
    import webbrowser

    opener = opener or webbrowser.open
    url = f"http://{host}:{port}"
    if _already_running(url):
        # người dùng bấm biểu tượng lần nữa khi tool đang chạy: chỉ mở lại trang, không chạy tool thứ hai
        print("CalForge Studio đang chạy sẵn - mở lại trang.")
        if open_browser:
            opener(url)
        return
    try:
        server = _Server((host, port), StudioHandler)
    except OSError:
        print(f"Cổng {port} đang bị chương trình khác dùng. Tắt chương trình đó hoặc khởi động lại máy.")
        raise SystemExit(1)
    print(f"\n========================================================")
    try:                                   # cuốn làm trước khi có SKU: đổi tên thư mục sang SKU (trước khi đọc hàng đợi)
        from ..publish.shop_csv import shop_settings
        from ..sku_rename import rename_all
        cfg = config.load()
        renamed = rename_all(Path(cfg["projects_dir"]), shop=shop_settings(cfg))
        if renamed:
            print(f" Đã đổi tên {len(renamed)} cuốn cũ sang mã SKU")
    except Exception as e:  # noqa: BLE001 - đổi tên lỗi không được chặn mở tool
        print(f" ⚠ Chưa đổi tên được các cuốn cũ sang SKU: {e}")
    batch_queue().start()                  # chạy lần lượt các batch trong hàng đợi
    print(f" ✨ CalForge Studio đang chạy tại: {url}")
    print(f" 📂 Bấm Ctrl+C để dừng máy chủ")
    print(f"========================================================\n")

    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: opener(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ CalForge Studio.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
