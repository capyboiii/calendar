import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge.llm import accounts, bulk_login


class FakePage:
    def __init__(self, url, ui_logged, email):
        self.url, self.ui_logged, self.email = url, ui_logged, email

    def evaluate(self, js):
        if "auth/session" in js:          # JS thật tự kiểm tra tên miền của trang (location.hostname)
            return self.email if "chatgpt.com" in self.url else ""
        return {"appReady": True, "hasLoginBtn": not self.ui_logged}


class FakeCtx:
    def __init__(self, pages):
        self.pages = pages


class SessionTest(unittest.TestCase):
    def test_marker_beats_cookies(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Default" / "Local Storage").mkdir(parents=True)          # có cookie/storage
            self.assertTrue(accounts.has_chatgpt_session(d))             # profile cũ: lùi về cookie
            (d / ".calforge_new").write_text("")
            self.assertFalse(accounts.has_chatgpt_session(d))            # tạo bằng tool, chưa xác nhận
            bulk_login.mark_logged_in(d, "a@b.com")
            self.assertTrue(accounts.has_chatgpt_session(d))
            self.assertEqual(json.loads((d / bulk_login.MARKER).read_text())["email"], "a@b.com")

    def test_create_account_starts_not_logged_in(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(accounts, "get_profiles_dir", lambda cfg=None: Path(tmp)):
            d = accounts.create_account("acc9")
            (d / "Default" / "Network").mkdir(parents=True)
            (d / "Default" / "Network" / "Cookies").write_bytes(b"x")
            self.assertFalse(accounts.has_chatgpt_session(d))

    def test_guest_page_is_not_logged_in(self):
        guest = FakePage("https://chatgpt.com/", ui_logged=False, email="")
        ui_only = FakePage("https://chatgpt.com/", ui_logged=True, email="")    # ô chat khách, máy chủ chưa có user
        modal = FakePage("https://chatgpt.com/", ui_logged=False, email="new@x.com")  # hộp chào mừng che ô chat
        google = FakePage("https://accounts.google.com/", ui_logged=True, email="x@y.com")
        self.assertEqual(bulk_login.logged_in_email(FakeCtx([guest, ui_only, google])), "")
        self.assertEqual(bulk_login.logged_in_email(FakeCtx([modal])), "new@x.com")
        real = FakePage("https://chatgpt.com/", ui_logged=True, email="me@x.com")
        self.assertEqual(bulk_login.logged_in_email(FakeCtx([guest, real])), "me@x.com")   # tab nào cũng được


class ServerLoginTest(unittest.TestCase):
    def test_login_window_does_not_block_batch(self):
        from calforge.ui import server
        tm = server.TaskManager()
        t = server.Task("t1", ["x"], "login", "login", {"profile": "acc1"})
        t.status = "running"
        tm.tasks["t1"] = t
        self.assertIsNone(tm.running())
        self.assertIs(tm.running(include_login=True), t)
        self.assertIs(tm.login_running("acc1"), t)
        self.assertIsNone(tm.login_running("acc2"))


class LoginWindowOnScreenTest(unittest.TestCase):
    def test_login_window_is_placed_on_screen(self):
        """Profile vừa chạy ngầm (Chrome nhớ vị trí -32000): cửa sổ đăng nhập phải ghi rõ vị trí trên màn hình."""
        import inspect
        from calforge.llm import accounts
        pos = [a for a in accounts.LOGIN_ARGS if a.startswith("--window-position=")]
        self.assertEqual(len(pos), 1)
        x, y = (int(v) for v in pos[0].split("=", 1)[1].split(","))
        self.assertTrue(0 <= x < 1000 and 0 <= y < 800)
        src = inspect.getsource(accounts.open_login_browser)
        self.assertEqual(src.count("args=LOGIN_ARGS"), 2)                  # cả lần mở Chrome và lần lùi về Chromium
        self.assertIn("bring_to_front", src)


if __name__ == "__main__":
    unittest.main()


class ProfileUsersTest(unittest.TestCase):
    def test_finds_task_owning_chrome_or_none_for_orphan(self):
        udir = Path(tempfile.gettempdir()) / "profs" / "acc3"
        key = str(udir.resolve())
        procs = [
            {"ProcessId": 10, "ParentProcessId": 1, "Name": "python.exe", "CommandLine": "python -m calforge run x"},
            {"ProcessId": 11, "ParentProcessId": 10, "Name": "node.exe", "CommandLine": "node driver"},
            {"ProcessId": 12, "ParentProcessId": 11, "Name": "chrome.exe", "CommandLine": f"chrome --user-data-dir={key}"},
            {"ProcessId": 20, "ParentProcessId": 1, "Name": "chrome.exe", "CommandLine": "chrome --user-data-dir=C:/other"},
        ]
        with mock.patch.object(accounts, "_processes", lambda: procs):
            self.assertEqual(accounts.profile_users(udir, {10, 99}), {10})
            self.assertEqual(accounts.profile_users(udir, {99}), set())          # mồ côi: không tác vụ nào giữ
