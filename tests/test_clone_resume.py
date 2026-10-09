"""Các nút Làm tiếp / Làm lại / Gen lại / Vẽ lại / Hoàn thiện trên cuốn Clone (loại Thường), đi đúng đường của
trang chính: lệnh `produce` (Làm tiếp), `finish` (Hoàn thiện / Làm lại ảnh quảng cáo / Gen lại 1 ảnh), `redo` (Sửa
trang hỏng) và nút "Làm tiếp" của hàng đợi clone. ChatGPT / Chrome giả; dựng sách + ghép mockup chạy THẬT."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from calforge import layout, pipeline
from calforge.clone import run, store

from tests.test_clone import META, accts, png
from tests.test_clone_errors import World
from tests.test_mixed_kinds import MixedSession

PLUS = ["acc3", "acc4", "acc5", "acc6"]


def art(color, size=(1536, 1024)):
    im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).ellipse((400, 200, 1000, 800), fill=(250, 240, 230))
    return im


class CloneResumeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cfg = {"projects_dir": str(self.root / "projects"), "profiles_dir": str(self.root / "prof"),
                    "imagegen": {"profiles": None}, "quota_max_wait_h": 0.01}
        self.world = World()
        self.fake_accts, self.pool = accts(PLUS)
        for p in (mock.patch.object(run, "plus_accounts", lambda cfg, **k: list(PLUS)),
                  mock.patch.object(run, "Accounts", lambda cfg, names, on_event=print, **k: self.fake_accts),
                  mock.patch.object(run.session, "Session", lambda page, pdir: MixedSession(self.world, Path(pdir).name)),
                  mock.patch("calforge.imagegen.generate.accept_grid_page", self.world.accept),
                  mock.patch("calforge.imagegen.ai_mockups.ai_previews", lambda *a, **k: {"ai": [], "kept_code": []}),
                  mock.patch.object(run, "GRID_POLL_S", 0.05),
                  mock.patch.object(pipeline, "upscale_concept", lambda *a, **k: [])):   # upscale GPU thật: rất lâu
            p.start()
            self.addCleanup(p.stop)
        MixedSession.refuse = None
        self.addCleanup(lambda: setattr(MixedSession, "refuse", None))

    # ---------------------------------------------------------------- dựng sẵn một cuốn (thiếu vài ảnh)
    def book(self, kind, missing=()):
        it = store.add(self.cfg["projects_dir"], [("a.png", png((120, 40, 60)))], group="t", kind=kind)
        d = store.root(self.cfg["projects_dir"]) / it["id"]
        b = run.Book(self.cfg, d)
        t = layout.tech(b.dir)
        t.mkdir(parents=True, exist_ok=True)
        (t / "clone_meta.json").write_text(json.dumps(META), encoding="utf-8")
        b._adopt()
        raw = layout.raw(b.dir)
        raw.mkdir(parents=True, exist_ok=True)
        jobs = ["cover"] + [f"m{m:02d}" for m in range(1, 13)] + [f"g{m:02d}" for m in range(1, 13)]
        rnd = random.Random(1)
        for j in jobs:
            if j not in missing:
                if j.startswith("g"):
                    data = png((int(j[1:]) * 9, 99, 33))
                    self.world.pages[data] = int(j[1:])
                    (raw / f"{j}.png").write_bytes(data)
                else:
                    art((rnd.randint(0, 255), 90, 120)).save(raw / f"{j}.png")
        store.write(d, status="failed", reason="hết lượt", art_state="done" if not any(
            j.startswith(("m", "c")) for j in missing) else "failed")
        return d, b.dir

    def produce(self, book):
        with mock.patch.object(pipeline, "finish_book", lambda *a, **k: {"ok": True, "stage": "listing"}):
            return pipeline.produce(book, self.cfg, printify=False, on_event=lambda *_: None)

    def test_early_grid_without_artwork_11_12_attaches_only_real_files(self):
        """Lỗi 09/10/2026: chỉ có artwork 1-10, chưa trang lịch nào -> ảnh đính kèm đầu là None (TypeError)."""
        d, book = self.book("normal", missing=("m11", "m12") + tuple(f"g{m:02d}" for m in range(1, 13)))
        sent = []

        class Stop(Exception):
            pass

        class S:
            def ask_images(self, prompt, want, attach=None):
                sent.append((want, list(attach)))
                raise Stop
        with self.assertRaises(Stop):
            run.Book(self.cfg, d, lambda *_: None).grid_work(S(), "acc4")
        want, attach = sent[0]
        self.assertEqual(want, 10)
        self.assertTrue(all(isinstance(a, Path) and a.is_file() for a in attach), attach)

    # ---------------------------------------------------------------- Làm tiếp (trang chính)
    def test_continue_normal_book_draws_only_missing_grid_pages(self):
        d, book = self.book("normal", missing=("g11", "g12"))
        st = self.produce(book)
        self.assertTrue(st["ok"], st)
        self.assertTrue(all((layout.raw(book) / f"g{m}.png").is_file() for m in (11, 12)))
        prompts_sent = [p for _, p in self.world.calls]
        self.assertTrue(prompts_sent and all("artwork" not in p.lower() or "calendar" in p.lower() for p in prompts_sent))
        self.assertEqual(self.pool.use, {})


    def test_continue_complete_book_does_not_call_chatgpt(self):
        d, book = self.book("normal")
        st = self.produce(book)
        self.assertTrue(st["ok"])
        self.assertEqual(self.world.calls, [])

    def test_continue_clone_book_without_queue_item_reports_clearly(self):
        d, book = self.book("normal", missing=("g12",))
        import shutil
        shutil.rmtree(d)                                                     # mục hàng đợi đã bị xoá (bấm Bỏ)
        st = self.produce(book)
        self.assertFalse(st["ok"])
        self.assertIn("g12", st["reason"])

    # ---------------------------------------------------------------- Vẽ lại trang (Sửa trang hỏng)

    # ---------------------------------------------------------------- Làm tiếp (hàng đợi clone)


    # ---------------------------------------------------------------- Hoàn thiện / Làm lại / Gen lại ảnh quảng cáo

if __name__ == "__main__":
    unittest.main()
