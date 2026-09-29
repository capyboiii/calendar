import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import layout, pipeline
from calforge.render import mockups


def book(root: Path, product="wall_grid", status=None, arts=True) -> Path:
    c = root / "kw" / "Book"
    layout.ensure_system(c)
    layout.concept_file(c).write_text(json.dumps({"product": product}), encoding="utf-8")
    layout.status_file(c).write_text(json.dumps(status or {"stage": "images", "ok": True}), encoding="utf-8")
    layout.raw(c).mkdir(parents=True, exist_ok=True)
    if arts:
        for j in pipeline.RENDER_ART_JOBS:
            (layout.raw(c) / f"{j}.png").write_bytes(b"x")
    return c


class FinishTest(unittest.TestCase):
    def test_needs_finishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(pipeline.needs_finishing(book(Path(tmp))))           # đủ tranh, dừng giữa chừng
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(pipeline.needs_finishing(book(Path(tmp), arts=False)))   # thiếu tranh: cần ChatGPT
        with tempfile.TemporaryDirectory() as tmp:
            done = book(Path(tmp), status={"stage": "listing", "ok": True})
            self.assertFalse(pipeline.needs_finishing(done))
        with tempfile.TemporaryDirectory() as tmp:
            c = book(Path(tmp), product="wall_premade", arts=False)
            for j in pipeline.RENDER_ART_JOBS[:-1]:                               # grid in sẵn: không cần grid
                (layout.raw(c) / f"{j}.png").write_bytes(b"x")
            self.assertTrue(pipeline.needs_finishing(c))

    def test_one_bad_preview_does_not_stop_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = book(Path(tmp))
            layout.print_dir(c).mkdir(parents=True)
            layout.listing(c).mkdir(parents=True)
            calls = []

            def fake_render(name, pages, out):
                calls.append(name)
                if name == mockups.PREVIEWS[1]:
                    raise OSError("hỏng khung")
                out.write_bytes(b"jpg")
            with mock.patch.object(mockups, "_dependencies", lambda name, pages: []), \
                    mock.patch.object(mockups, "render", fake_render), \
                    mock.patch("builtins.max", lambda *a, **k: 0):
                with self.assertRaises(mockups.PreviewError) as err:
                    mockups.previews(c, on_event=lambda *_: None)
            self.assertEqual(calls, mockups.PREVIEWS)                              # vẫn làm đủ 5 tấm
            self.assertEqual(len(err.exception.made), 4)
            self.assertEqual(len(mockups.missing_previews(c)), 1)


if __name__ == "__main__":
    unittest.main()
