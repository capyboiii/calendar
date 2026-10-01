import json
import unittest
import urllib.request
import urllib.parse
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

from calforge.ui.server import StudioHandler, ROOT


class UiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StudioHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()

    def _first_concept_path(self):
        _, data = self._get("/api/projects")
        projects = json.loads(data.decode("utf-8")).get("projects") or []
        for project in projects:
            concepts = project.get("concepts") or []
            if concepts:
                return concepts[0]["path"]
        self.fail("UI test requires at least one concept project")

    def test_serve_index_html(self):
        status, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"CalForge", data)
        self.assertIn(b"STUDIO", data)
        self.assertEqual(data.count(b'class="style-sample'), 4)
        self.assertIn(b'data-style-family="random"', data)

    def test_api_styles(self):
        status, data = self._get("/api/styles")
        self.assertEqual(status, 200)
        res = json.loads(data.decode("utf-8"))
        self.assertIn("families", res)
        self.assertEqual(
            [f["id"] for f in res["families"]],
            ["styled_photography", "papercut_collage", "mid_century_retro"],
        )

    def test_api_projects(self):
        status, data = self._get("/api/projects")
        self.assertEqual(status, 200)
        res = json.loads(data.decode("utf-8"))
        self.assertIn("projects", res)
        self.assertGreaterEqual(len(res["projects"]), 1)

    def test_api_concept(self):
        concept_path = urllib.parse.quote(self._first_concept_path(), safe="/")
        status, data = self._get(f"/api/concept?path={concept_path}")
        self.assertEqual(status, 200)
        res = json.loads(data.decode("utf-8"))
        self.assertIn("concept", res)
        self.assertEqual(res["concept"]["year"], 2027)
        self.assertIn("files", res)
        self.assertIn("art_final", res["files"])

    def test_file_security_prevents_directory_traversal(self):
        # Attempt traversal outside root
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/file?path=../../windows/win.ini")
        self.assertIn(ctx.exception.code, (400, 404))

    def test_api_file_serves_valid_file(self):
        concept_path = urllib.parse.quote(self._first_concept_path() + "/_he_thong/concept.json", safe="/")
        status, data = self._get(f"/api/file?path={concept_path}")
        self.assertEqual(status, 200)
        res = json.loads(data.decode("utf-8"))
        self.assertIn("cover", res)


    def test_api_accounts(self):
        status, data = self._get("/api/accounts")
        self.assertEqual(status, 200)
        res = json.loads(data.decode("utf-8"))
        self.assertIn("accounts", res)
        self.assertIn("profiles_dir", res)
        names = [a["name"] for a in res["accounts"]]
    def test_create_and_delete_account(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/accounts/create",
            data=json.dumps({"name": "temp_acc_test"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)
            res = json.loads(r.read().decode("utf-8"))
            self.assertTrue(res.get("ok"))
            created_path = Path(res["path"])
            self.assertTrue(created_path.exists())

        req_del = urllib.request.Request(
            f"{self.base_url}/api/accounts/delete",
            data=json.dumps({"name": "temp_acc_test"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req_del, timeout=5) as r:
            self.assertEqual(r.status, 200)
            res = json.loads(r.read().decode("utf-8"))
            self.assertTrue(res.get("ok"))
            self.assertFalse(created_path.exists())


if __name__ == "__main__":
    unittest.main()


class LoginWaitTest(unittest.TestCase):
    """Đóng cửa sổ Chrome không được làm hàm login ném lỗi (nếu không UI báo failed)."""

    def test_returns_when_pages_empty(self):
        from calforge.llm.accounts import wait_until_browser_closed

        class Ctx:
            pages = []
            def on(self, *_): pass
        wait_until_browser_closed(Ctx(), poll=0.01)  # không treo, không lỗi

    def test_returns_when_pages_raises_after_close(self):
        from calforge.llm.accounts import wait_until_browser_closed

        class Ctx:
            def on(self, *_): pass
            @property
            def pages(self):
                raise RuntimeError("Target page, context or browser has been closed")
        wait_until_browser_closed(Ctx(), poll=0.01)  # nuốt lỗi, thoát sạch

    def test_returns_on_close_event(self):
        import threading as _t

        from calforge.llm.accounts import wait_until_browser_closed

        class Ctx:
            def __init__(self): self._cb = None
            def on(self, _evt, cb): self._cb = cb
            @property
            def pages(self): return [object()]  # vẫn còn tab
        c = Ctx()
        _t.Timer(0.05, lambda: c._cb()).start()  # mô phỏng sự kiện close
        wait_until_browser_closed(c, poll=0.01)
