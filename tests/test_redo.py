import json
import tempfile
import unittest
from pathlib import Path

from calforge import layout
from calforge.pipeline import redo_pages
from calforge.publish import r2


def book(root: Path, product="wall_grid") -> Path:
    c = root / "Wall Calendar (Blank)" / "kw" / "Book"
    layout.ensure_system(c)
    layout.concept_file(c).write_text(json.dumps({"product": product}), encoding="utf-8")
    layout.raw(c).mkdir(parents=True)
    layout.final(c).mkdir(parents=True)
    for j in ("cover", "m05", "m06", "grid"):
        (layout.raw(c) / f"{j}.png").write_bytes(b"x")
    (layout.final(c) / "m05.jpg").write_bytes(b"x")
    return c


class RedoTest(unittest.TestCase):
    def test_moves_only_chosen_pages_and_marks_for_reexport(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = book(Path(tmp))
            r2.write_state(c, {"files": {"a": {}}, "exported_at": "2026-09-29", "exported_csv": "x.csv"})
            moved = redo_pages(c, ["m05", "grid"], on_event=lambda *_: None)
            self.assertEqual(moved, ["m05", "grid"])
            self.assertFalse((layout.raw(c) / "m05.png").exists())
            self.assertFalse((layout.final(c) / "m05.jpg").exists())           # bản upscale cũ cũng cất
            self.assertTrue((layout.raw(c) / "m06.png").exists())              # trang không chọn: giữ nguyên
            self.assertEqual(len(list(layout.tech(c, "anh_cu").iterdir())), 3)  # ảnh cũ không mất
            self.assertNotIn("exported_at", r2.read_state(c))                  # lần xuất CSV sau có bản mới
            st = json.loads(layout.status_file(c).read_text(encoding="utf-8"))
            self.assertFalse(st["ok"])

    def test_premade_has_no_grid_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = book(Path(tmp), product="wall_premade")
            with self.assertRaises(ValueError):
                redo_pages(c, ["grid"], on_event=lambda *_: None)
            self.assertTrue((layout.raw(c) / "grid.png").exists())


class QueueArgsTest(unittest.TestCase):
    def test_single_book_jobs(self):
        from calforge.ui import server
        books = [b for b in layout.books(Path(server.config.load()["projects_dir"]))]
        if not books:
            self.skipTest("cần ít nhất một cuốn")
        rel = str(books[0].relative_to(server.ROOT)).replace("\\", "/")
        args, _ = server.run_args({"action": "redo", "concept": rel, "pages": ["m05"]})
        self.assertEqual((args[0], args[-2], args[-1]), ("redo", "--pages", "m05"))
        args, _ = server.run_args({"action": "produce", "concept": rel})
        self.assertEqual(args[0], "produce")
        with self.assertRaises(ValueError):
            server.run_args({"action": "redo", "concept": rel, "pages": []})
        with self.assertRaises(ValueError):
            server.run_args({"action": "produce", "concept": "../../Windows"})


if __name__ == "__main__":
    unittest.main()
