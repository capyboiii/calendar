import json
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from calforge.ideation import templates
from calforge.ideation.pipeline import run_ideation
from calforge.ideation.validate import contrast_ratio, usable_angles, validate_angles, validate_concept
from calforge.imagegen import plan, prompts
from calforge.llm.base import AwaitingResponse
from calforge.llm.manual import ManualBackend

from tests import fixtures


def fenced(obj) -> str:
    return "Sure!\n```json\n" + json.dumps(obj) + "\n```"


class ValidateTest(unittest.TestCase):
    def test_fixture_concept_is_valid(self):
        errors, _ = validate_concept(fixtures.concept(), 2027)
        self.assertEqual(errors, [])

    def test_easter_in_wrong_month_is_caught(self):
        c = fixtures.concept()
        c["months"][2]["holiday_tie"], c["months"][3]["holiday_tie"] = "none", "Easter"
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("falls in March 2027" in e for e in errors), errors)

    def test_verse_text_instead_of_reference(self):
        c = fixtures.concept()
        c["months"][5]["content"]["value"] = "And he arose, and rebuked the wind, and said unto the sea"
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[5].content.value" in e for e in errors), errors)

    def test_low_contrast_font_and_banned_term(self):
        c = fixtures.concept()
        c["style"]["palette"]["title"] = "#D8CBB5"
        c["style"]["fonts"]["title"] = "Comic Sans"
        c["listing"]["tags"][0] = "disney calendar"
        errors, _ = validate_concept(c, 2027)
        joined = "\n".join(errors)
        self.assertIn("contrast", joined)
        self.assertIn("Comic Sans", joined)
        self.assertIn('banned term "disney"', joined)

    def test_scene_must_show_focal_subject(self):
        c = fixtures.concept()
        c["months"][11]["focal_subject"] = "a decorated evergreen tree with a golden star on top"
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[11].scene does not show its focal_subject" in e for e in errors), errors)

    def test_holiday_month_needs_symbol(self):
        c = fixtures.concept()
        c["months"][11]["holiday_symbol"] = ""
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[11].holiday_symbol is empty" in e for e in errors), errors)

    def test_generic_theme_rejected(self):
        c = fixtures.concept()
        c["months"][4]["theme"] = "Spring"
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[4].theme" in e for e in errors), errors)

    def test_duplicate_scenes(self):
        c = fixtures.concept()
        c["months"][7]["scene"] = c["months"][6]["scene"]
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("too similar" in e for e in errors), errors)

    def test_angles_filtering(self):
        data = fixtures.angles_payload()
        errors, _ = validate_angles(data)
        self.assertEqual(errors, [])
        self.assertEqual([a["id"] for a in usable_angles(data)], ["a1"])

    def test_angles_need_style_variety(self):
        data = fixtures.angles_payload()
        for a in data["angles"]:
            a["style_family"] = "watercolor_gouache"
        errors, _ = validate_angles(data)
        self.assertTrue(any("different style_family" in e for e in errors), errors)
        self.assertTrue(any("at most ONE angle" in e for e in errors), errors)

    def test_unknown_style_family_rejected(self):
        data = fixtures.angles_payload()
        data["angles"][0]["style_family"] = "anime"
        errors, _ = validate_angles(data)
        self.assertTrue(any("angles[0].style_family" in e for e in errors), errors)

    def test_rank_prefers_least_used_family(self):
        import json as _json

        from calforge.ideation import catalog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(2):  # danh mục đã có 2 cuốn watercolor
                d = root / "kw" / f"c{i}"
                d.mkdir(parents=True)
                (d / "concept.json").write_text(_json.dumps({"style": {"family": "watercolor_gouache"}}))
            a = dict(fixtures.ANGLE, id="w", ai_feasibility={"score": 5})
            b = dict(fixtures.ANGLE, id="l", style_family="linocut_print", ai_feasibility={"score": 4})
            self.assertEqual([x["id"] for x in catalog.rank_angles([a, b], root)], ["l", "w"])

    def test_contrast_ratio_reference_values(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#FFFFFF"), 21.0, places=1)


class TemplatesTest(unittest.TestCase):
    def test_no_placeholder_left(self):
        p1 = templates.p1_angles("christian", 2027, "US", 5, [], Path(tempfile.gettempdir()) / "no-projects")
        p2 = templates.p2_concept(fixtures.ANGLE, "soft watercolor", 2027, "US")
        p3 = templates.p3_repair(["x is wrong"], {"a": 1})
        for p in (p1, p2, p3):
            self.assertIsNone(re.search(r"\{\{\w+\}\}", p))
        self.assertIn("Easter 28", p2)
        self.assertIn("Cormorant Garamond", p2)


class FakeChatGPT:
    """Trả lời theo kịch bản; ghi lại các prompt nhận được."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    @contextmanager
    def session(self, workdir):
        outer = self

        class Chat:
            def ask(self, prompt, label):
                outer.prompts.append((label, prompt))
                return outer.answers.pop(0)
        yield Chat()


class PipelineTest(unittest.TestCase):
    def test_end_to_end_with_repair(self):
        bad = fixtures.concept()
        bad["months"][2]["holiday_tie"], bad["months"][3]["holiday_tie"] = "none", "Easter"
        good = fixtures.concept()
        fake = FakeChatGPT([fenced(fixtures.angles_payload()), fenced(bad), fenced(good)])
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation("Christian", fake, Path(tmp), year=2027, max_repairs=2)
            self.assertEqual(len(res.concepts), 1)
            labels = [label for label, _ in fake.prompts]
            self.assertEqual(labels, ["p1_angles_run1", "p2_concept_r1a1", "p2_concept_r1a1_repair1"])
            self.assertIn("falls in March 2027", fake.prompts[2][1])  # lỗi được gửi lại cho ChatGPT
            concept = json.loads((res.concepts[0] / "concept.json").read_text(encoding="utf-8"))
            self.assertEqual(concept["year"], 2027)

            # Chạy lại: mọi thứ đã có trong sổ -> không hỏi thêm câu nào
            again = FakeChatGPT([])
            res2 = run_ideation("Christian", again, Path(tmp), year=2027)
            self.assertEqual(again.prompts, [])
            self.assertEqual(res2.concepts, res.concepts)

            # Kế hoạch gen ảnh + CSV cho chatgpt-automation
            jobs = plan.write_plan(res.concepts[0])
            self.assertEqual([j["id"] for j in jobs][:3], ["anchor", "m01", "m02"])
            self.assertEqual(len(jobs), 14)
            csv_text = plan.export_csv(res.concepts[0]).read_text(encoding="utf-8-sig")
            self.assertEqual(csv_text.count("cal-"), 14)

    def test_manual_backend_waits_for_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AwaitingResponse) as ctx:
                run_ideation("Chickens", ManualBackend(), Path(tmp), year=2027)
            self.assertTrue(ctx.exception.prompt_path.exists())
            ctx.exception.response_path.write_text(fenced(fixtures.angles_payload()), encoding="utf-8")
            with self.assertRaises(AwaitingResponse) as ctx2:  # P1 xong, giờ chờ P2
                run_ideation("Chickens", ManualBackend(), Path(tmp), year=2027)
            self.assertIn("p2_concept_r1a1", ctx2.exception.prompt_path.name)


class ImagePromptTest(unittest.TestCase):
    def test_month_prompt_has_fixed_constraints(self):
        c = fixtures.concept()
        p = prompts.month_prompt(c, c["months"][5])
        self.assertTrue(p.startswith(fixtures.STYLE_BIBLE))
        self.assertIn("Sea of Galilee", p)
        self.assertIn("No text", p)
        self.assertIn("3:2", p)
        self.assertIn("attached reference image", p)
        self.assertNotIn("attached reference image", prompts.month_prompt(c, c["months"][5], with_reference=False))
        dec = prompts.month_prompt(c, c["months"][11])
        self.assertIn("Focal point", dec)
        self.assertIn("Bethlehem stable", dec)
        self.assertIn("holiday symbol: a bright star", dec)
        self.assertLess(dec.index("Focal point"), dec.index("Scene:"))  # trọng tâm nói trước cảnh


if __name__ == "__main__":
    unittest.main()
