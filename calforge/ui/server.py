"""Máy chủ Web CalForge Studio (dùng Python standard library)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
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
                "logs": self.logs[since:],
                "total_logs": len(self.logs),
            }


class TaskManager:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.lock = threading.Lock()

    def start_task(self, args: list[str], description: str, action: str = "", params: dict | None = None) -> str:
        task_id = f"t_{int(time.time() * 1000)}"
        # -u: không đệm stdout, để log chảy trực tiếp lên UI (không dồn về cuối)
        cmd = [sys.executable, "-u", "-m", "calforge"] + args
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

    def running(self) -> Task | None:
        with self.lock:
            return next((t for t in self.tasks.values() if t.status == "running"), None)

    def stop_task(self, task_id: str) -> bool:
        """Dừng tác vụ + mọi tiến trình con (Chrome của Playwright) để lần chạy sau không vướng profile."""
        with self.lock:
            task = self.tasks.get(task_id)
        if not task or task.status != "running" or not task.process:
            return False
        task.status = "stopped"
        task.append_log("\n⏹ Người dùng bấm Dừng")
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(task.process.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            task.process.kill()
        return True

    def list_tasks(self) -> list[dict]:
        with self.lock:
            return [t.to_dict() for t in sorted(self.tasks.values(), key=lambda x: x.start_time, reverse=True)[:10]]


TASK_MANAGER = TaskManager()


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
        
        static_file = STATIC_DIR / path.lstrip("/")
        if static_file.is_file() and str(static_file.resolve()).startswith(str(STATIC_DIR.resolve())):
            return super().do_GET()

        return self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
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
                keyword = params.get("keyword", "").strip()
                if not keyword:
                    return self._send_json({"error": "Keyword is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["run", keyword]
                if params.get("pick"):
                    cmd_args += ["--pick", params["pick"]]
                batch = int(params.get("batch_size") or 1)
                if batch > 1:
                    cmd_args += ["--auto", str(min(batch, 20))]
                if params.get("grid_preset"):
                    cmd_args += ["--grid-preset", params["grid_preset"]]
                if params.get("family"):
                    cmd_args += ["--family", params["family"]]
                if params.get("product") in products.PRODUCTS:
                    cmd_args += ["--product", params["product"]]
                if params.get("publish"):
                    cmd_args += ["--publish"]
                desc = f"Chạy trọn gói {batch} cuốn cho keyword: {keyword}" if batch > 1 else f"Chạy trọn gói cho keyword: {keyword}"

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
                cmd_args = ["produce", concept_path]
                if params.get("publish"):
                    cmd_args += ["--publish"]
                desc = f"Sản xuất từ concept: {Path(concept_path).name}"

            elif action == "shop":
                cmd_args = ["shop"]
                desc = "Đẩy lên R2 + xuất CSV"

            elif action == "login":
                profile_name = params.get("profile", "").strip()
                if not profile_name:
                    return self._send_json({"error": "Profile name is required"}, status=HTTPStatus.BAD_REQUEST)
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

        if path in ("/api/open", "/api/task/stop"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception as e:
                return self._send_json({"error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
            if path == "/api/task/stop":
                return self._send_json({"ok": TASK_MANAGER.stop_task(str(body.get("id", "")))})
            target = (ROOT / str(body.get("path", "")).lstrip("/\\")).resolve()
            if not str(target).startswith(str(ROOT.resolve())) or not target.exists():
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

        if path == "/api/accounts/bulk-login":
            # Mật khẩu chỉ đi qua RAM của máy chủ tới cửa sổ Chrome: không ghi log, không trả về, không lưu đĩa.
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            except Exception:
                return self._send_json({"error": "Dữ liệu không hợp lệ"}, status=HTTPStatus.BAD_REQUEST)
            busy = TASK_MANAGER.running()
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
        if not str(target).startswith(str(ROOT.resolve())) or not target.is_dir():
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
        if not str(target).startswith(str(ROOT.resolve())) or not target.is_file():
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
        target = (ROOT / rel_path.lstrip("/\\")).resolve()
        if not str(target).startswith(str(ROOT.resolve())) or not target.is_file():
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
    return {"cover": _rel(cover) if cover.exists() else "", "previews": [_rel(p) for p in previews],
            "pdfs": pdfs, "listing": listing}


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
    return {k: b.get(k) for k in ("target", "started", "finished", "report")}


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


def run_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True):
    import webbrowser

    url = f"http://{host}:{port}"
    if _already_running(url):
        # người dùng bấm biểu tượng lần nữa khi tool đang chạy: chỉ mở lại trang, không chạy tool thứ hai
        print("CalForge Studio đang chạy sẵn - mở lại trang.")
        if open_browser:
            webbrowser.open(url)
        return
    try:
        server = _Server((host, port), StudioHandler)
    except OSError:
        print(f"Cổng {port} đang bị chương trình khác dùng. Tắt chương trình đó hoặc khởi động lại máy.")
        raise SystemExit(1)
    print(f"\n========================================================")
    print(f" ✨ CalForge Studio đang chạy tại: {url}")
    print(f" 📂 Bấm Ctrl+C để dừng máy chủ")
    print(f"========================================================\n")

    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ CalForge Studio.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
