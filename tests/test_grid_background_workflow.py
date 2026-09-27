"""Một nền grid AI dùng chung cho 12 tháng, còn hình học lịch luôn do code."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from calforge.imagegen.generate import accept_grid_background, generate_concept
from calforge.imagegen.plan import build_jobs
from calforge.render.grid_select import apply_grid_selection
from calforge.render.grid_compositions import COMPOSITIONS
from tests import fixtures


class GridBackgroundWorkflowTest(unittest.TestCase):
    def _concept(self):
        concept = fixtures.concept()
        concept.update(year=2027, market="US")
        apply_grid_selection(concept, requested="auto")
        return concept

    def test_plan_creates_one_shared_grid_from_collection_anchor(self):
        concept = self._concept()
        jobs = build_jobs(concept)
        self.assertEqual(len(jobs), 15)
        background = next(j for j in jobs if j["id"] == "grid")
        self.assertEqual(background["attach"], ["_he_thong/anh_ai/anchor.png"])
        self.assertIn("all 12 monthly", background["prompt"])
        self.assertIn("Software will overprint the exact 7-column grid", background["prompt"])
        self.assertIn("MANDATORY LIGHTNESS", background["prompt"])
        self.assertIn("EXTREMELY LIGHT near-white pastel tint", background["prompt"])
        self.assertIn("5–10% base-color strength", background["prompt"])
        self.assertIn("NO DECORATIVE MOTIFS OR OBJECTS ANYWHERE", background["prompt"])
        self.assertIn("collection-specific surface system", background["prompt"])
        self.assertNotIn("cream", background["prompt"].lower())  # không còn ép tránh màu kem
        self.assertIn("GRID COLOR INTENSITY", background["prompt"])
        self.assertIn("5–15%", background["prompt"])
        self.assertIn("Never fill the page with full-strength primary color", background["prompt"])
        self.assertIn("STRICT COLOR HIERARCHY", background["prompt"])
        self.assertIn("SHARED COLLECTION BASE", background["prompt"])
        self.assertIn("soft sage green (#A8B7A0)", background["prompt"])
        self.assertIn("shared collection base named above must occupy at least 85%", background["prompt"])
        self.assertIn("No rainbow palette, patchwork", background["prompt"])
        self.assertIn("reused unchanged behind all 12", background["prompt"])
        self.assertIn("Do not introduce a season, month, holiday", background["prompt"])
        self.assertIn("do not reserve or decorate a title corner", background["prompt"])
        self.assertIn("No leaves, flowers, produce, animals", background["prompt"])
        self.assertIn("No concentric edge bands", background["prompt"])
        self.assertIn("THIS IS A FLAT SURFACE DESIGN, NOT AN ARTWORK PAGE", background["prompt"])
        self.assertIn("No landscape, scenery, environment, horizon", background["prompt"])
        self.assertIn("TEXT-ZONE CONTRAST OVERRIDES THE SURFACE SYSTEM", background["prompt"])
        self.assertIn("x=8–92%, y=27–94%", background["prompt"])
        self.assertNotIn("one continuous sheet of pale paper", background["prompt"])
        self.assertIn("must not compete with them", background["prompt"])
        self.assertNotIn("collection-specific illustration", background["prompt"])
        self.assertNotIn("collection-specific vignette", background["prompt"])

        apply_grid_selection(concept, requested="quiet_luxury")
        self.assertEqual(len(build_jobs(concept)), 14)

    def test_generation_waits_for_month_art_before_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            concept_dir = root / "concept"
            concept_dir.mkdir()
            (concept_dir / "_he_thong").mkdir(parents=True, exist_ok=True)
            (concept_dir / "_he_thong" / "concept.json").write_text(json.dumps(self._concept()), encoding="utf-8")
            profiles = root / "profiles"
            (profiles / "acc1").mkdir(parents=True)
            batches = []

            def fake_run_jobs(jobs, *_args, **_kwargs):
                batches.append([job.id for job in jobs])
                for job in jobs:
                    if job.id == "grid":
                        self.assertEqual(job.attach, [concept_dir / "_he_thong" / "anh_ai" / "anchor.png"])
                        self.assertTrue(job.attach[0].exists())
                    elif job.id != "anchor":  # cover + tháng: đính dải màu, không đính nguyên ảnh neo
                        self.assertEqual(job.attach, [concept_dir / "_he_thong" / "anh_ai" / "anchor_swatch.png"])
                        self.assertTrue(job.attach[0].exists())
                    out = job.out.with_suffix(".png")
                    out.parent.mkdir(parents=True, exist_ok=True)
                    Image.new("RGB", (1536, 1024), (220, 230, 228)).save(out)
                    job.result = out
                return jobs

            with patch("calforge.imagegen.generate.run_jobs", side_effect=fake_run_jobs):
                result = generate_concept(concept_dir, profiles, on_event=lambda *_: None)

            self.assertEqual(result["missing"], [])
            self.assertEqual(batches[0], ["anchor"])
            self.assertEqual(len(batches[1]), 13)  # cover + 12 artwork
            self.assertEqual(batches[2], ["grid"])

    def test_shared_grid_rejects_busy_calendar_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            quiet = Path(tmp) / "quiet.png"
            busy = Path(tmp) / "busy.png"
            Image.new("RGB", (1536, 1024), (239, 231, 211)).save(quiet)
            image = Image.new("RGB", (1536, 1024), "white")
            pixels = image.load()
            for y in range(300, 900):
                for x in range(120, 1410):
                    if (x // 24 + y // 24) % 2:
                        pixels[x, y] = (25, 35, 45)
            image.save(busy)
            self.assertIsNone(accept_grid_background(quiet))
            self.assertIsNotNone(accept_grid_background(busy))

    def test_grid_qc_accepts_dark_surface_with_light_text_and_rejects_low_contrast(self):
        with tempfile.TemporaryDirectory() as tmp:
            dark = Path(tmp) / "dark.png"
            low_contrast = Path(tmp) / "low-contrast.png"
            Image.new("RGB", (1536, 1024), (24, 34, 48)).save(dark)
            Image.new("RGB", (1536, 1024), (65, 65, 65)).save(low_contrast)
            self.assertIsNone(accept_grid_background(dark, ["#F5F1E8"]))
            self.assertIsNotNone(accept_grid_background(low_contrast, ["#3B332E"]))

    def test_grid_qc_requires_a_very_pale_surface_for_dark_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            pale = Path(tmp) / "pale.png"
            midtone = Path(tmp) / "midtone.png"
            Image.new("RGB", (1536, 1024), (220, 239, 236)).save(pale)
            Image.new("RGB", (1536, 1024), (165, 204, 201)).save(midtone)
            self.assertIsNone(accept_grid_background(pale, ["#173B67", "#24344A"]))
            self.assertIsNotNone(accept_grid_background(midtone, ["#173B67", "#24344A"]))

    def test_grid_surface_prompt_is_independent_of_text_composition(self):
        prompts = set()
        for composition in COMPOSITIONS:
            concept = self._concept()
            concept["style"]["grid_composition"] = composition
            grid = next(j for j in build_jobs(concept) if j["id"] == "grid")
            self.assertIn("NO DECORATIVE MOTIFS OR OBJECTS ANYWHERE", grid["prompt"])
            prompts.add(grid["prompt"])
        self.assertEqual(len(prompts), 1)


if __name__ == "__main__":
    unittest.main()
