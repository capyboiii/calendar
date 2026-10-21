"""Clone sản phẩm từ LINK: ChatGPT tách artwork của sản phẩm thành file zip -> ảnh mẫu -> các bước cũ giữ nguyên.
Lỗi: link sai, ChatGPT không tải được ảnh / không trả zip, zip hỏng / có rác, hết lượt giữa chừng."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge.clone import fetch, store
from calforge.imagegen.driver import QuotaExceeded

from tests.test_clone_errors import FakeSession, complete, setup

URL = "https://www.etsy.com/listing/123456789/cozy-cats-2027-wall-calendar"


def art(i, size=(1200, 900)):
    buf = io.BytesIO()
    Image.new("RGB", size, (i * 20 % 255, 80, 120)).save(buf, "PNG")
    return buf.getvalue()


def zip_of(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


GOOD_ZIP = zip_of({f"artworks/{i:02d}.png": art(i) for i in (1, 2, 10, 3)})


class ZipAndValidationTest(unittest.TestCase):
    def test_link_validation(self):
        self.assertEqual(fetch.valid_url("  " + URL + " "), URL)
        for bad in ("", "etsy.com/listing/1", "ftp://x.com/a", "https://", "javascript:alert(1)"):
            with self.assertRaises(ValueError, msg=bad):
                fetch.valid_url(bad)

    def test_zip_images_natural_order_and_junk_skipped(self):
        data = zip_of({"10.png": art(10), "2.png": art(2), "1.png": art(1), "__MACOSX/._1.png": b"x",
                       ".DS_Store": b"x", "readme.txt": b"hello", "icon.png": art(9, (64, 64))})
        imgs = fetch.images_from_zip(data)
        self.assertEqual([n for n, _ in imgs], ["1.png", "2.png", "10.png"])        # 2 trước 10; bỏ rác + ảnh bé

    def test_zip_with_uncropped_originals_keeps_only_cropped_artworks(self):
        """ChatGPT gửi kèm ảnh gốc chưa cắt (ZIP Kit_Connor 14/10/2026): chỉ lấy ảnh artwork đã cắt."""
        data = zip_of({**{f"artworks/{i:02d}_Month_564x564.png": art(i) for i in range(1, 13)},
                       "originals_fullxfull/02_january_april_il_fullxfull.jpg": art(20, (3000, 1683)),
                       "originals_fullxfull/05_product_information_il_fullxfull.jpg": art(21, (3000, 2000)),
                       "README.txt": b"x", "crop_manifest.csv": b"a,b"})
        names = [n for n, _ in fetch.images_from_zip(data)]
        self.assertEqual(len(names), 12)
        self.assertFalse([n for n in names if "fullxfull" in n])
        flat = zip_of({"00-cover.png": art(0), **{f"{i:02d}-artwork.png": art(i) for i in range(1, 13)}})
        self.assertEqual(len(fetch.images_from_zip(flat)), 13)                       # kiểu Hudson: lấy hết
        odd = zip_of({"original_1.png": art(1), "original_2.png": art(2)})             # chỉ có tên lạ: vẫn lấy
        self.assertEqual(len(fetch.images_from_zip(odd)), 2)

    def test_add_link_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            it = store.add_link(tmp, URL, group="cats", year=2027)
            d = store.root(tmp) / it["id"]
            self.assertEqual((it["source_url"], it["status"], store.refs(d)), (URL, "pending", []))
            with self.assertRaises(ValueError):
                store.add_link(tmp, "khong-phai-link")

    def test_prompt_asks_for_real_crops_in_a_zip(self):
        p = fetch.fetch_prompt(URL)
        self.assertIn(URL, p)
        self.assertIn("il_fullxfull", p)                               # lấy ảnh gốc từ network, không ảnh thu nhỏ
        self.assertTrue(p.startswith("Từ link sản phẩm này, hãy lấy ảnh của sản phẩm, cắt chỉ lấy mỗi artwork"))
        self.assertNotIn("CANNOT", p)                                  # không cho lối thoát (ChatGPT bỏ cuộc sớm)


class LinkFlowTest(unittest.TestCase):
    def go(self, ask_files, n=1):
        cfg, _, world, pool, go = setup(self, n_books=0)
        ds = [store.root(cfg["projects_dir"]) / store.add_link(cfg["projects_dir"], f"{URL}?v={i}", group="cats")["id"]
              for i in range(n)]
        calls = []

        def fake(self_, prompt):
            calls.append((self_.account, prompt))
            return ask_files(len(calls), prompt)
        with mock.patch.object(FakeSession, "ask_files", fake, create=True), \
                mock.patch.object(FakeSession, "harvest", lambda self_: [], create=True):
            go()
        return ds, calls, world

    def test_link_book_runs_whole_clone_flow(self):
        ds, calls, world = self.go(lambda k, p: ("Here is your zip.", [("artworks.zip", GOOD_ZIP)]))
        d = ds[0]
        self.assertEqual(len(calls), 1)
        self.assertIn(URL, calls[0][1])
        self.assertEqual(len(store.refs(d)), 4)                                     # 4 artwork trong zip -> 4 ảnh mẫu
        complete(self, d)                                                           # rồi vẽ artwork, lịch, bìa như cũ
        art_prompts = [p for _, p in world.calls if p.startswith("OUTPUT FORMAT")]
        self.assertTrue(art_prompts)

    def test_no_file_first_time_repairs_same_session_then_succeeds(self):
        def ask(k, p):
            if k == 1:
                return "Etsy gallery images are visible, but could not be downloaded.", []
            return "ok", [("artworks.zip", GOOD_ZIP)]
        ds, calls, _ = self.go(ask)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertIn('Không truy cập lại', calls[1][1])
        complete(self, ds[0])

    def test_no_zip_at_all_fails_book_without_drawing(self):
        ds, calls, world = self.go(lambda k, p: ("I made some notes but no file.", []))
        it = store.read(ds[0])
        self.assertEqual(it["status"], "failed")
        self.assertIn("chưa gửi artwork", it["reason"])
        self.assertEqual(world.calls, [])                                          # không vẽ gì khi chưa có ảnh mẫu
        self.assertGreater(len(calls), 1)                                           # đã thử nhiều phiên

    def test_invalid_download_retries_original_prompt_then_recovers(self):
        bad_files = [
            ("artworks.zip", b"PK broken zip"),
            ("artworks.zip", zip_of({"README.txt": b"no artwork"})),
            ("artworks.zip", zip_of({})),
            ("artworks.zip", b"<html>download expired</html>"),
            ("answer.txt", b"Here is your artwork"),
            ("artwork.png", b"not an image"),
        ]
        for bad in bad_files:
            with self.subTest(filename=bad[0], content=bad[1][:30]):
                ds, calls, _ = self.go(lambda k, p: ("ok", [bad] if k == 1 else [("artworks.zip", GOOD_ZIP)]))
                self.assertEqual(len(calls), 2)
                if bad[0].endswith('.zip'):
                    self.assertIn('File ZIP bạn vừa gửi', calls[1][1])
                    self.assertEqual(calls[0][0], calls[1][0])
                else:
                    self.assertEqual(calls[0][1], calls[1][1])
                complete(self, ds[0])

    def test_valid_png_without_zip_is_accepted(self):
        ds, calls, _ = self.go(lambda k, p: ("Artwork attached", [("artwork.png", art(1))]))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(store.refs(ds[0])), 1)
        complete(self, ds[0])

    def test_images_shown_in_chat_become_refs(self):
        """Prompt không đòi ZIP: ChatGPT thường gửi thẳng các ảnh đã cắt trong chat -> tool tự lưu làm ảnh mẫu."""
        cfg, _, world, pool, go = setup(self, n_books=0)
        d = store.root(cfg["projects_dir"]) / store.add_link(cfg["projects_dir"], URL)["id"]
        shown = [art(i) for i in range(1, 13)]
        with mock.patch.object(FakeSession, "ask_files", lambda s_, p: ("Đây là 12 artwork đã cắt.", []), create=True),                 mock.patch.object(FakeSession, "harvest", lambda s_: shown, create=True):
            go()
        self.assertEqual(len(store.refs(d)), 12)
        complete(self, d)

    def test_quota_while_fetching_switches_account(self):
        def ask(k, p):
            if k == 1:
                raise QuotaExceeded("You've hit the plus plan limit")
            return "ok", [("artworks.zip", GOOD_ZIP)]
        ds, calls, _ = self.go(ask)
        self.assertNotEqual(calls[0][0], calls[1][0])                               # đổi tài khoản
        complete(self, ds[0])

    def test_refs_fetched_once_then_reused_on_retry(self):
        ds, calls, _ = self.go(lambda k, p: ("ok", [("artworks.zip", GOOD_ZIP)]))
        d = ds[0]
        store.write(d, status="failed")
        with mock.patch.object(fetch, "fetch_work", side_effect=AssertionError("không được lấy lại")):
            from calforge.clone import run
            b = run.Book({"projects_dir": str(d.parent.parent)}, d)
            run.fetch_refs(b, None)                                                 # đã có ảnh mẫu: bỏ qua
        self.assertEqual(len(store.refs(d)), 4)

    def test_many_links_many_books(self):
        ds, calls, _ = self.go(lambda k, p: ("ok", [("artworks.zip", GOOD_ZIP)]), n=3)
        self.assertEqual(len(calls), 3)
        for d in ds:
            complete(self, d)


if __name__ == "__main__":
    unittest.main()
