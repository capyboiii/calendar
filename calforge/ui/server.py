"""Máy chủ Web CalForge Studio (dùng Python standard library)."""
from __future__ import annotations

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

from .. import config

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Task:
    def __init__(self, task_id: str, cmd: list[str], description: str):
        self.id = task_id
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

    def start_task(self, args: list[str], description: str) -> str:
        task_id = f"t_{int(time.time() * 1000)}"
        # -u: không đệm stdout, để log chảy trực tiếp lên UI (không dồn về cuối)
        cmd = [sys.executable, "-u", "-m", "calforge"] + args
        task = Task(task_id, cmd, description)
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
        if path == "/api/styles":
            return self._api_get_styles()
        if path == "/api/task":
            task_id = query.get("id", [""])[0]
            since = int(query.get("since", [0])[0])
            return self._api_get_task(task_id, since)
        if path == "/api/tasks":
            return self._send_json({"tasks": TASK_MANAGER.list_tasks()})
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
                if params.get("publish"):
                    cmd_args += ["--publish"]
                desc = f"Chạy trọn gói cho keyword: {keyword}"

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

            elif action == "login":
                profile_name = params.get("profile", "").strip()
                if not profile_name:
                    return self._send_json({"error": "Profile name is required"}, status=HTTPStatus.BAD_REQUEST)
                cmd_args = ["login", profile_name]
                desc = f"Mở trình duyệt đăng nhập ChatGPT: {profile_name}"

            else:
                return self._send_json({"error": f"Unknown action: {action}"}, status=HTTPStatus.BAD_REQUEST)

            task_id = TASK_MANAGER.start_task(cmd_args, desc)
            return self._send_json({"task_id": task_id, "description": desc, "status": "started"})

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
        for kw_dir in sorted(projects_dir.iterdir()):
            if not kw_dir.is_dir() or kw_dir.name.startswith("."):
                continue

            angles_file = kw_dir / "angles.json"
            angles = []
            if angles_file.exists():
                try:
                    angles = json.loads(angles_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            concepts = []
            for c_dir in sorted(kw_dir.iterdir()):
                if not c_dir.is_dir() or not (c_dir / "concept.json").exists():
                    continue

                concept_data = {}
                try:
                    concept_data = json.loads((c_dir / "concept.json").read_text(encoding="utf-8"))
                except Exception:
                    pass

                status_data = {}
                if (c_dir / "status.json").exists():
                    try:
                        status_data = json.loads((c_dir / "status.json").read_text(encoding="utf-8"))
                    except Exception:
                        pass

                raw_count = len([f for f in (c_dir / "art" / "raw").glob("*.*") if f.is_file()]) if (c_dir / "art" / "raw").exists() else 0
                final_count = len([f for f in (c_dir / "art" / "final").glob("*.*") if f.is_file()]) if (c_dir / "art" / "final").exists() else 0
                render_count = len([f for f in (c_dir / "render" / "printify").glob("*.png") if f.is_file()]) if (c_dir / "render" / "printify").exists() else 0
                has_digital = (c_dir / "render" / "digital" / "calendar_11x8_5.pdf").exists()

                concepts.append({
                    "id": c_dir.name,
                    "path": str(c_dir.relative_to(ROOT)).replace("\\", "/"),
                    "title": (concept_data.get("cover") or {}).get("title") or c_dir.name,
                    "subtitle": (concept_data.get("cover") or {}).get("subtitle", ""),
                    "year": concept_data.get("year", cfg.get("year", 2027)),
                    "family": (concept_data.get("style") or {}).get("family", ""),
                    "status": status_data,
                    "raw_count": raw_count,
                    "final_count": final_count,
                    "render_count": render_count,
                    "has_digital": has_digital,
                })

            results.append({
                "keyword": kw_dir.name,
                "path": str(kw_dir.relative_to(ROOT)).replace("\\", "/"),
                "total_angles": len(angles),
                "concepts": concepts,
            })

        return self._send_json({"projects": results, "year": cfg.get("year", 2027), "market": cfg.get("market", "US")})

    def _api_get_concept(self, rel_path: str):
        if not rel_path:
            return self._send_json({"error": "Path required"}, status=HTTPStatus.BAD_REQUEST)
        
        target = (ROOT / rel_path).resolve()
        if not str(target).startswith(str(ROOT.resolve())) or not target.is_dir():
            return self._send_json({"error": "Invalid concept path"}, status=HTTPStatus.BAD_REQUEST)

        concept_file = target / "concept.json"
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
        status_data = _read_json(target / "status.json") or {}
        palette_data = _read_json(target / "palette.json") or {}
        listing_data = _read_json(target / "listing.json") or {}
        jobs_data = _read_json(target / "jobs.json") or []
        printify_data = _read_json(target / "printify.json") or {}

        render_report = _read_text(target / "render" / "report.md")
        concept_report = _read_text(target / "concept_report.md")

        files = {
            "art_raw": _list_files(target / "art" / "raw"),
            "art_final": _list_files(target / "art" / "final"),
            "render_printify": _list_files(target / "render" / "printify"),
            "render_proof": _list_files(target / "render" / "proof"),
            "render_digital": _list_files(target / "render" / "digital"),
        }

        return self._send_json({
            "path": rel_path.replace("\\", "/"),
            "name": target.name,
            "concept": concept_data,
            "status": status_data,
            "palette": palette_data,
            "listing": listing_data,
            "jobs": jobs_data,
            "printify": printify_data,
            "render_report": render_report,
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

        return self._serve_file(target, mime)

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

    def _serve_file(self, file_path: Path, content_type: str):
        try:
            data = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
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

    def log_message(self, format, *args):
        # Tắt log mặc định của SimpleHTTPRequestHandler cho đỡ rác console
        pass


def run_server(host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True):
    server = ThreadingHTTPServer((host, port), StudioHandler)
    url = f"http://{host}:{port}"
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
