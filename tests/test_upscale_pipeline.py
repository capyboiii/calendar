import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import pipeline


class BackgroundUpscaleTest(unittest.TestCase):
    def _raw(self, concept_dir: Path, jid: str, age_s: float = 60.0) -> Path:
        raw = concept_dir / "_he_thong" / "anh_ai"
        raw.mkdir(parents=True, exist_ok=True)
        path = raw / f"{jid}.png"
        Image.new("RGB", (30, 20), (120, 160, 200)).save(path)
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        return path

    def test_upscales_finished_art_while_generation_runs(self):
        calls = []

        def fake_upscale(src, dst, w, h):
            calls.append(src.stem)
            Path(dst).write_bytes(b"x")
            return {"engine": "fake", "scale": 2.0}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "upscale_to", fake_upscale):
            concept_dir = Path(tmp)
            self._raw(concept_dir, "m01")
            with pipeline._BackgroundUpscaler(concept_dir, on_event=lambda _m: None, poll_s=0.05) as early:
                deadline = time.time() + 5
                while "m01" not in calls and time.time() < deadline:
                    time.sleep(0.02)
                self._raw(concept_dir, "m02", age_s=0)  # vừa ghi xong: chưa đủ 3s nên chưa được đụng tới
                time.sleep(0.2)
            self.assertEqual(early.done, ["m01"])
            self.assertEqual(calls, ["m01"])
            # Bước upscale chính sau khi gen xong làm nốt ảnh còn lại, không làm lại m01.
            self.assertEqual(pipeline.upscale_concept(concept_dir, lambda _m: None), ["m02"])
            self.assertEqual(calls, ["m01", "m02"])

    def test_regenerated_art_is_upscaled_again(self):
        calls = []

        def fake_upscale(src, dst, w, h):
            calls.append(src.stem)
            Path(dst).write_bytes(b"x")
            stamp = time.time() - 30
            os.utime(dst, (stamp, stamp))  # bản final cũ hơn ảnh gen lại bên dưới
            return {"engine": "fake", "scale": 2.0}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "upscale_to", fake_upscale):
            concept_dir = Path(tmp)
            self._raw(concept_dir, "m03")
            pipeline.upscale_concept(concept_dir, lambda _m: None)
            self._raw(concept_dir, "m03", age_s=5)  # gen lại sau khi đã upscale
            pipeline.upscale_concept(concept_dir, lambda _m: None)
            self.assertEqual(calls, ["m03", "m03"])


if __name__ == "__main__":
    unittest.main()
