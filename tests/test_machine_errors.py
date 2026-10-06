"""LỖI PHÍA MÁY / NGOÀI TOOL: không có GPU, GPU hết bộ nhớ giữa chừng, máy chưa có Chrome, cài bộ GPU hỏng mạng,
ghép mockup thiếu trang, dữ liệu đăng nhập hàng loạt sai, xoá tài khoản sai tên."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import cli, layout  # noqa: F401
from calforge.imagegen import upscale


class UpscaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.src = self.d / "a.png"
        Image.new("RGB", (300, 200), "red").save(self.src)

    def test_no_gpu_falls_back_to_lanczos(self):
        with mock.patch.object(upscale, "_model", lambda: None):
            res = upscale.upscale_to(self.src, self.d / "b.jpg", 900, 600)
        self.assertTrue(res["engine"].startswith("Lanczos"))
        with Image.open(self.d / "b.jpg") as im:
            self.assertGreaterEqual(im.size, (900, 600))

    def test_gpu_out_of_memory_midway_does_not_break_the_book(self):
        with mock.patch.object(upscale, "_model", lambda: object()), \
                mock.patch.object(upscale, "_esrgan_x4", mock.Mock(side_effect=RuntimeError("CUDA out of memory"))):
            res = upscale.upscale_to(self.src, self.d / "c.png", 900, 600)
        self.assertIn("GPU lỗi", res["engine"])
        with Image.open(self.d / "c.png") as im:
            self.assertEqual(im.size, (900, 600))

    def test_gpu_path_and_transparent_and_already_big(self):
        with mock.patch.object(upscale, "_model", lambda: object()), \
                mock.patch.object(upscale, "_esrgan_x4", lambda img: img.resize((img.width * 4, img.height * 4))):
            res = upscale.upscale_to(self.src, self.d / "d.png", 900, 600)
        self.assertIn("Lanczos giữ vân giấy", res["engine"])
        rgba = self.d / "t.png"
        Image.new("RGBA", (300, 200)).save(rgba)
        with mock.patch.object(upscale, "_model", lambda: object()), \
                mock.patch.object(upscale, "_esrgan_x4", mock.Mock(side_effect=AssertionError)):
            self.assertEqual(upscale.upscale_to(rgba, self.d / "t2.png", 900, 600)["engine"], "Lanczos")
        self.assertEqual(upscale.upscale_to(self.src, self.d / "e.jpg", 100, 50)["engine"], "không cần phóng")

    def test_missing_torch_means_no_model(self):
        upscale._model.cache_clear()
        self.addCleanup(upscale._model.cache_clear)
        with mock.patch.dict("sys.modules", {"torch": None}):
            self.assertIsNone(upscale._model())
        upscale._model.cache_clear()
        self.assertIn(upscale.engine(), ("Lanczos (dự phòng)", "Real-ESRGAN x4plus (GPU)"))


class AppStartTest(unittest.TestCase):
    def test_no_chrome_shows_message_and_download_page(self):
        from calforge import app
        msgs, opened = [], []
        with mock.patch.object(app, "_chrome", lambda: None), mock.patch.object(app.os, "name", "nt"), \
                mock.patch.object(app, "_message", msgs.append), mock.patch.object(app.webbrowser, "open", opened.append), \
                mock.patch.object(app.os, "chdir"), mock.patch("calforge.ui.server.run_server") as run:
            app.main()
        self.assertTrue(msgs and "Chrome" in msgs[0])
        self.assertEqual(opened, ["https://www.google.com/chrome/"])
        run.assert_not_called()                                           # không chạy tool nửa vời

    def test_with_chrome_starts_server_and_opens_app_window(self):
        from calforge import app
        with mock.patch.object(app, "_chrome", lambda: Path("C:/chrome.exe")), mock.patch.object(app.os, "chdir"), \
                mock.patch("calforge.ui.server.run_server") as run:
            app.main()
        run.assert_called_once()
        with mock.patch.object(app, "_chrome", lambda: Path("C:/chrome.exe")), \
                mock.patch.object(app.subprocess, "Popen") as popen:
            app._open_window("http://127.0.0.1:8080")
        self.assertIn("--app=http://127.0.0.1:8080", popen.call_args[0][0])
        with mock.patch.object(app, "_chrome", lambda: None), mock.patch.object(app.webbrowser, "open") as wb:
            app._open_window("http://127.0.0.1:8080")
        wb.assert_called_once()


class GpuSetupTest(unittest.TestCase):
    def test_every_outcome_returns_0_so_install_never_fails(self):
        from calforge import gpu_setup as g
        with mock.patch.object(g, "has_nvidia", lambda: False):
            self.assertEqual(g.main(), 0)
        with mock.patch.object(g, "has_nvidia", lambda: True), mock.patch.object(g, "ready", lambda: True):
            self.assertEqual(g.main(), 0)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(g, "GPU_DIR", Path(tmp) / "gpu"), \
                mock.patch.object(g, "has_nvidia", lambda: True), mock.patch.object(g, "ready", lambda: False), \
                mock.patch.object(g, "_pip", lambda *a: False):                  # mất mạng lúc tải torch
            self.assertEqual(g.main(), 0)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(g, "GPU_DIR", Path(tmp) / "gpu"), \
                mock.patch.object(g, "has_nvidia", lambda: True), mock.patch.object(g, "ready", lambda: False), \
                mock.patch.object(g, "_pip", lambda *a: True), \
                mock.patch.dict("sys.modules", {"fetch_assets": mock.Mock(
                    fetch_upscaler=mock.Mock(side_effect=OSError("tải trọng số hỏng")))}):
            self.assertEqual(g.main(), 0)

    def test_ready_survives_broken_python(self):
        from calforge import gpu_setup as g
        with mock.patch.object(g.subprocess, "run", mock.Mock(side_effect=OSError("không chạy được"))):
            self.assertFalse(g.ready())


class MockupRenderTest(unittest.TestCase):
    """Ghép mockup thật (ảnh nhỏ) cho các mockup mới + báo đúng tấm thiếu trang."""

    def pages(self, d: Path, skip=()):
        d.mkdir(parents=True, exist_ok=True)
        names = ["front_cover", "back_cover"] + [f"m{m:02d}_{k}" for m in range(1, 13) for k in ("month", "grid")]
        for n in names:
            if n not in skip:
                Image.new("RGB", (3375 // 8, 2625 // 8), (40 * (len(n) % 6), 90, 140)).save(d / f"{n}.png")
        return d

    def test_new_mockups_render(self):
        from calforge.render import mockups
        with tempfile.TemporaryDirectory() as tmp:
            pages = self.pages(Path(tmp) / "p")
            for name in ("three_books", "two_wall_spreads"):
                out = Path(tmp) / f"{name}.jpg"
                mockups.render(name, pages, out)
                with Image.open(out) as im:
                    self.assertEqual(im.width, im.height)                       # ảnh vuông như mockup gốc
                    self.assertGreater(im.width, 2000)

    def test_missing_page_is_reported_per_preview(self):
        from calforge.render import mockups
        from tests import test_ai_mockups as tam
        with tempfile.TemporaryDirectory() as tmp:
            c = tam.book(Path(tmp))
            for f in layout.listing(c).glob("*.jpg"):
                f.unlink()
            self.pages(layout.print_dir(c), skip=("m08_grid",))
            calls = []
            with mock.patch.object(mockups, "render", lambda n, p, o: (calls.append(n),
                                                                       Image.new("RGB", (10, 10)).save(o))):
                with self.assertRaises(mockups.PreviewError) as e:
                    mockups.previews(c, on_event=lambda *_: None)
            self.assertTrue(any("06_three_books" in x and "m08_grid" in x for x in e.exception.errors))
            self.assertNotIn("three_books", calls)
            self.assertIn("two_wall_spreads", calls)                           # tấm khác vẫn ghép được
            self.assertEqual(mockups.missing_previews(c), ["06_three_books.jpg", "09_year_grid.jpg"])   # lưới 12 tháng cũng cần T8


class AccountInputTest(unittest.TestCase):
    def test_bulk_login_rejects_bad_lines_without_starting(self):
        from calforge.llm import bulk_login
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"profiles_dir": tmp, "projects_dir": tmp}
            for raw in ("", "   \n  ", "khong-phai-email | pass | ABC", "a@b.c | pass | 2FA-SAI-!!"):
                with self.subTest(raw=raw), mock.patch.object(bulk_login.threading, "Thread", mock.Mock()) as t:
                    bulk_login.BULK["active"] = False
                    with self.assertRaises(ValueError):                       # không có dòng hợp lệ: báo ngay
                        bulk_login.start(raw, cfg)
                    t.assert_not_called()
            raw = "a@b.c | SecretPw123 | JBSWY3DPEHPK3PXP\na@b.c | SecretPw123 | JBSWY3DPEHPK3PXP\nrac | x"
            with mock.patch.object(bulk_login.threading, "Thread", mock.Mock()):
                bulk_login.BULK["active"] = False
                res = bulk_login.start(raw, cfg)
                self.assertEqual(res["started"], 1)                          # dòng trùng / rác bị bỏ, dòng tốt chạy
                self.assertTrue(any("trùng email" in s for s in res["skipped"]))
                self.assertTrue(any("sai định dạng" in s for s in res["skipped"]))
                self.assertNotIn("SecretPw123", str(res))                    # không trả mật khẩu ra ngoài
                with self.assertRaises(RuntimeError):                        # đang chạy một lượt: không chồng lượt
                    bulk_login.start(raw, cfg)
            bulk_login.BULK["active"] = False

    def test_account_names_cannot_escape_profiles_dir(self):
        from calforge.llm import accounts
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"profiles_dir": tmp, "projects_dir": tmp}
            for bad in ("../x", "a/b", "..", "", "acc 1", "acc;rm"):
                with self.assertRaises(ValueError, msg=bad):
                    accounts.create_account(bad, cfg)
                with self.assertRaises(ValueError, msg=bad):
                    accounts.delete_account(bad, cfg)
            accounts.create_account("acc1", cfg)
            with self.assertRaises(FileExistsError):
                accounts.create_account("acc1", cfg)
            with self.assertRaises(FileNotFoundError):
                accounts.delete_account("acc9", cfg)


if __name__ == "__main__":
    unittest.main()
