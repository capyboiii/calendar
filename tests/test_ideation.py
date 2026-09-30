import json
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from calforge.ideation import catalog, templates
from calforge.ideation.pipeline import run_ideation
from calforge.ideation.validate import contrast_ratio, usable_angles, validate_angles, validate_concept
from calforge.imagegen import plan, prompts
from calforge.llm.base import AwaitingResponse, LazyChat, Ledger
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

    def test_low_contrast_font_with_unfiltered_brand(self):
        c = fixtures.concept()
        c["style"]["palette"]["title"] = "#D8CBB5"
        c["style"]["fonts"]["title"] = "Comic Sans"
        c["listing"]["tags"][0] = "disney calendar"
        errors, _ = validate_concept(c, 2027)
        joined = "\n".join(errors)
        self.assertIn("contrast", joined)
        self.assertIn("Comic Sans", joined)
        self.assertNotIn('banned term', joined)

    def test_scene_focal_subject_mismatch_is_only_a_warning(self):
        c = fixtures.concept()
        c["months"][11]["focal_subject"] = "a decorated evergreen tree with a golden star on top"
        errors, warnings = validate_concept(c, 2027)
        self.assertFalse(any("months[11].scene" in e and "focal_subject" in e for e in errors), errors)
        self.assertTrue(any("months[11].scene may not clearly show its focal_subject" in w for w in warnings), warnings)

    def test_holiday_month_needs_symbol(self):
        c = fixtures.concept()
        c["months"][11]["holiday_symbol"] = ""
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[11].holiday_symbol is empty" in e for e in errors), errors)

    def test_holiday_symbol_wording_mismatch_is_only_a_warning(self):
        c = fixtures.concept()
        c["months"][11]["holiday_symbol"] = "a carved wooden nativity ornament beside a candle"
        errors, warnings = validate_concept(c, 2027)
        self.assertFalse(any("holiday_symbol" in e and "does not include" in e for e in errors), errors)
        self.assertTrue(any("holiday_symbol" in w and "may not clearly include" in w for w in warnings), warnings)

    def test_generic_theme_rejected(self):
        c = fixtures.concept()
        c["months"][4]["theme"] = "Spring"
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("months[4].theme" in e for e in errors), errors)

    def test_duplicate_scenes_are_only_a_warning(self):
        c = fixtures.concept()
        c["months"][7]["scene"] = c["months"][6]["scene"]
        errors, warnings = validate_concept(c, 2027)
        self.assertFalse(any("too similar" in e for e in errors), errors)
        self.assertTrue(any("too similar" in w for w in warnings), warnings)

    def test_angles_filtering(self):
        data = fixtures.angles_payload()
        errors, _ = validate_angles(data)
        self.assertEqual(errors, [])
        self.assertEqual([a["id"] for a in usable_angles(data)], ["a1", "a2"])

    def test_style_family_does_not_force_creative_variety(self):
        data = fixtures.angles_payload()
        for a in data["angles"]:
            a["style_family"] = "styled_photography"
        errors, _ = validate_angles(data)
        self.assertFalse(any("style_family values" in e or "at most ONE angle" in e for e in errors), errors)

    def test_unknown_style_family_rejected(self):
        data = fixtures.angles_payload()
        data["angles"][0]["style_family"] = "anime"
        errors, _ = validate_angles(data)
        self.assertTrue(any("angles[0].style_family" in e for e in errors), errors)

    def test_artwork_composition_system_is_required(self):
        c = fixtures.concept()
        del c["style"]["artwork_composition_system"]
        errors, _ = validate_concept(c, 2027)
        self.assertTrue(any("artwork_composition_system is required" in e for e in errors), errors)

    def test_rank_prefers_feasibility_then_underused_family(self):
        import json as _json

        from calforge.ideation import catalog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(2):  # danh mục đã có 2 cuốn photography
                d = root / "kw" / f"c{i}" / "_he_thong"
                d.mkdir(parents=True)
                (d / "concept.json").write_text(_json.dumps({"style": {"family": "styled_photography"}}))
            a = dict(fixtures.ANGLE, id="w", ai_feasibility={"score": 5})
            b = dict(fixtures.ANGLE, id="l", style_family="papercut_collage", ai_feasibility={"score": 4})
            self.assertEqual([x["id"] for x in catalog.rank_angles([a, b], root)], ["l", "w"])
            b["ai_feasibility"] = {"score": 3}
            self.assertEqual([x["id"] for x in catalog.rank_angles([a, b], root)], ["w", "l"])

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
        self.assertIn("production contract", p1)
        self.assertIn("BUYER-LED ART DIRECTION", p2)
        self.assertIn("Portfolio diversity matters", p1)
        self.assertIn("Recent visual systems", p1)
        self.assertIn("none yet", p1)
        self.assertIn('{"a":1}', p3)

    def test_p1_can_require_styled_photography(self):
        prompt = templates.p1_angles(
            "bible", 2027, "US", 1, [], Path(tempfile.gettempdir()) / "no-projects",
            family="styled_photography",
        )
        self.assertIn('use exactly style_family "styled_photography"', prompt)
        self.assertIn("Styled photography", prompt)
        self.assertIn("do not return another family", prompt)

    def test_prompts_allow_anonymous_people_and_mixed_subjects(self):
        p1 = templates.p1_angles("gardening", 2027, "US", 1, [], Path(tempfile.gettempdir()) / "no-projects")
        p2 = templates.p2_concept(fixtures.ANGLE, "soft watercolor", 2027, "US")
        self.assertNotIn("never depict identifiable real people", p1)
        self.assertNotIn("avoid tight close-ups of faces", p1 + p2)
        self.assertNotIn("No identifiable real person", p2)
        self.assertIn("mix these types across the 12 months", p2)
        self.assertNotIn("No real people's likeness", p2)

    def test_live_repair_prompt_does_not_repeat_previous_json(self):
        p3 = templates.p3_repair(["x is wrong"], {"large": "payload"}, include_previous=False)
        self.assertIn("immediately previous answer", p3)
        self.assertNotIn("payload", p3)

    def test_p1_receives_recent_visual_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "old" / "book"
            project.mkdir(parents=True)
            concept = fixtures.concept()
            concept["style"]["surface_system"] = "flat cobalt poster ink"
            (project / "_he_thong").mkdir(parents=True, exist_ok=True)
            (project / "_he_thong" / "concept.json").write_text(json.dumps(concept), encoding="utf-8")
            prompt = templates.p1_angles("travel", 2027, "US", 1, [], root)
            self.assertIn("flat cobalt poster ink", prompt)
            self.assertIn("Asymmetric edge-led scenes", prompt)


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
    def setUp(self):
        # Các kịch bản ở đây kiểm tra luồng chat; chia style có test riêng (StyleSplitTest).
        from unittest import mock
        patcher = mock.patch.object(catalog, "family_quota", lambda root, n: {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_end_to_end_with_repair(self):
        bad = fixtures.concept()
        bad["months"][2]["holiday_tie"], bad["months"][3]["holiday_tie"] = "none", "Easter"
        good = fixtures.concept()
        keep = fenced({"decisions": [{"id": "r1a1", "keep": True, "duplicates": "", "reason": "new"}, {"id": "r1a2", "keep": False, "reason": "same product"}],
                       "selected": ["r1a1"]})
        fake = FakeChatGPT([fenced(fixtures.angles_payload()), keep, fenced(bad), fenced(good)])
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation("Christian", fake, Path(tmp), year=2027, max_repairs=2)
            self.assertEqual(len(res.concepts), 1)
            self.assertEqual(res.concepts[0].name, "A Year with Jesus")        # thư mục = tên cuốn
            self.assertEqual((res.concepts[0] / "_he_thong" / "angle_id.txt").read_text(encoding="utf-8"), "r1a1")
            self.assertTrue((Path(tmp) / "christian" / "_he_thong" / "angles.json").is_file())
            labels = [label for label, _ in fake.prompts]
            self.assertEqual(labels, ["p1_angles_run1", "p1b_review_run1", "p2_concept_r1a1",
                                      "p2_concept_r1a1_repair1"])
            self.assertIn("first priority is artwork that fulfills the keyword", fake.prompts[1][1])
            self.assertIn("falls in March 2027", fake.prompts[3][1])  # lỗi được gửi lại cho ChatGPT
            self.assertIn('"months":', fake.prompts[3][1])  # lần sửa luôn kèm JSON cũ (chat có thể đã đổi phiên)
            concept = json.loads((res.concepts[0] / "_he_thong" / "concept.json").read_text(encoding="utf-8"))
            self.assertEqual(concept["year"], 2027)
            self.assertEqual(concept["grid_selection"]["mode"], "auto")
            self.assertTrue(concept["grid_selection"]["grid_uses_shared_artwork"])

            # Chạy lại đúng góc đã làm: mọi thứ đã có trong sổ -> không hỏi thêm câu nào
            again = FakeChatGPT([])
            res2 = run_ideation("Christian", again, Path(tmp), year=2027, pick=["r1a1"])
            self.assertEqual(again.prompts, [])
            self.assertEqual(res2.concepts, res.concepts)

            # Batch mới cùng keyword: batch cũ đã làm xong -> nghĩ lượt ý mới, AI thấy cuốn cũ trong danh mục
            angles2 = fixtures.angles_payload()
            keep2 = fenced({"decisions": [{"id": "r2a1", "keep": True}, {"id": "r2a2", "keep": False}], "selected": ["r2a1"]})
            nxt = FakeChatGPT([fenced(angles2), keep2, fenced(fixtures.concept())])
            run_ideation("Christian", nxt, Path(tmp), year=2027)
            self.assertEqual([l for l, _ in nxt.prompts], ["p1_angles_run2", "p1b_review_run2", "p2_concept_r2a1"])
            self.assertIn('"A Year with Jesus"', nxt.prompts[0][1])   # danh mục đưa vào P1
            self.assertIn('"A Year with Jesus"', nxt.prompts[1][1])   # và vào lượt thẩm định

            # Kế hoạch gen ảnh + CSV cho chatgpt-automation
            jobs = plan.write_plan(res.concepts[0])
            self.assertEqual([j["id"] for j in jobs][:4], ["anchor", "cover", "m01", "m02"])
            # cuốn Blank mới: AI vẽ nguyên 12 trang lịch (g01..g12), không còn một nền grid chung
            self.assertEqual(len(jobs), 26)
            self.assertNotIn("grid", [j["id"] for j in jobs])
            g01 = next(j for j in jobs if j["id"] == "g01")
            self.assertEqual(g01["attach"], ["_he_thong/anh_ai/anchor_swatch.png"])
            self.assertIn("SUN MON TUE WED THU FRI SAT", g01["prompt"])
            csv_text = plan.export_csv(res.concepts[0]).read_text(encoding="utf-8-sig")
            self.assertEqual(csv_text.count("cal-"), 14)  # CSV không đính ảnh, bỏ nền grid chung

    def test_review_never_opens_a_nested_chat_session(self):
        # Playwright sync không cho mở 2 trình duyệt lồng nhau: phiên P1 phải đóng trước khi thẩm định mở phiên riêng.
        class StrictBackend:
            def __init__(self, answers):
                self.answers, self.open, self.labels = list(answers), 0, []

            @contextmanager
            def session(self, workdir):
                if self.open:
                    raise AssertionError("mở phiên chat lồng nhau")
                self.open += 1
                outer = self

                class Chat:
                    def ask(self, prompt, label):
                        outer.labels.append(label)
                        return outer.answers.pop(0)
                try:
                    yield Chat()
                finally:
                    self.open -= 1

        keep = fenced({"decisions": [{"id": "r1a1", "keep": True}, {"id": "r1a2", "keep": False}], "selected": ["r1a1"]})
        backend = StrictBackend([fenced(fixtures.angles_payload()), keep, fenced(fixtures.concept())])
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation("Nature", backend, Path(tmp), year=2027)
        self.assertEqual(backend.labels, ["p1_angles_run1", "p1b_review_run1", "p2_concept_r1a1"])
        self.assertEqual(len(res.concepts), 1)

    def test_each_concept_gets_its_own_chat(self):
        # Batch nhiều cuốn: mỗi P2 một cuộc chat mới, vòng sửa P3 ở lại chat của cuốn đó.
        class CountingBackend:
            def __init__(self, answers):
                self.answers, self.n, self.calls = list(answers), 0, []

            @contextmanager
            def session(self, workdir):
                self.n += 1
                sid, outer = self.n, self

                class Chat:
                    def ask(self, prompt, label):
                        outer.calls.append((label, sid))
                        return outer.answers.pop(0)
                yield Chat()

        payload = fixtures.angles_payload()
        payload["angles"][1] = dict(payload["angles"][0], id="a2", title="A Second Year")
        ids = ["a1", "a2"]
        keep = fenced({"decisions": [{"id": f"r1{i}", "keep": True} for i in ids],
                       "selected": [f"r1{i}" for i in ids]})
        bad = fixtures.concept()
        bad["months"][2]["holiday_tie"], bad["months"][3]["holiday_tie"] = "none", "Easter"
        backend = CountingBackend([fenced(payload), keep,
                                   fenced(bad), fenced(fixtures.concept()), fenced(fixtures.concept())])
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation("Nature", backend, Path(tmp), year=2027, auto_pick=2, max_repairs=2)
        self.assertEqual(len(res.concepts), 2)
        sid = dict(backend.calls)
        p2 = [l for l, _ in backend.calls if l.startswith("p2_") and "repair" not in l]
        self.assertEqual(len(p2), 2)
        self.assertNotEqual(sid[p2[0]], sid[p2[1]])
        self.assertEqual(sid[p2[0] + "_repair1"], sid[p2[0]])

    def test_big_batch_runs_in_rounds_of_three(self):
        # 4 cuốn = lượt 3 + lượt 1; mỗi lượt P1/P1b riêng, lượt 2 thấy các cuốn lượt 1 trong danh mục.
        from calforge.ideation.pipeline import run_ideation_batched

        def payload(names):
            p = fixtures.angles_payload()
            p["angles"] = [dict(p["angles"][0], id=f"a{i + 1}", title=t) for i, t in enumerate(names)]
            return p

        def keep(run, n):
            ids = [f"r{run}a{i + 1}" for i in range(n)]
            return fenced({"decisions": [{"id": i, "keep": True} for i in ids], "selected": ids})

        answers = ([fenced(payload(["Alpha", "Beta", "Gamma"])), keep(1, 3)] + [fenced(fixtures.concept())] * 3
                   + [fenced(payload(["Delta"])), keep(2, 1), fenced(fixtures.concept())])
        fake = FakeChatGPT(answers)
        rounds = []
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation_batched("Nature", fake, Path(tmp), year=2027, auto_pick=4,
                                       on_round=lambda r: rounds.append(len(r.concepts)))
            self.assertEqual(len(res.concepts), 4)
        self.assertEqual(rounds, [3, 1])
        labels = [l for l, _ in fake.prompts]
        self.assertEqual(labels, ["p1_angles_run1", "p1b_review_run1", "p2_concept_r1a1", "p2_concept_r1a2",
                                  "p2_concept_r1a3", "p1_angles_run2", "p1b_review_run2", "p2_concept_r2a1"])
        self.assertIn("9", fake.prompts[0][1])            # lượt 3 cuốn -> xin 9 ý, không phải 12
        self.assertIn('"A Year with Jesus"', fake.prompts[5][1])   # lượt 2 thấy cuốn lượt 1 trong danh mục

    def test_manual_backend_waits_for_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AwaitingResponse) as ctx:
                run_ideation("Chickens", ManualBackend(), Path(tmp), year=2027)
            self.assertTrue(ctx.exception.prompt_path.exists())
            ctx.exception.response_path.write_text(fenced(fixtures.angles_payload()), encoding="utf-8")
            with self.assertRaises(AwaitingResponse) as ctx2:  # P1 xong, giờ chờ AI thẩm định trùng
                run_ideation("Chickens", ManualBackend(), Path(tmp), year=2027)
            self.assertIn("p1b_review_run1", ctx2.exception.prompt_path.name)

    def test_lazy_chat_marks_cached_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp))
            ledger.record("cached", "prompt", "answer")
            fake = FakeChatGPT(["fresh answer"])
            with LazyChat(fake, ledger) as chat:
                self.assertEqual(chat.ask("ignored", "cached"), "answer")
                self.assertTrue(chat.last_was_cached)
                self.assertEqual(chat.ask("new prompt", "fresh"), "fresh answer")
                self.assertFalse(chat.last_was_cached)


class ImagePromptTest(unittest.TestCase):
    def test_cover_prompt_lets_ai_integrate_exact_title(self):
        c = fixtures.concept()
        c["year"] = 2027
        p = prompts.cover_prompt(c)
        self.assertIn('"A Year with Jesus"', p)
        self.assertIn('"2027"', p)
        self.assertIn("Art-direct the lettering yourself", p)
        self.assertIn("must not look like a software text overlay", p)
        self.assertIn("CENTER the whole title block", p)
        self.assertIn("Do NOT add any haze, glow", p)   # không đệm nền mờ sau chữ bìa
        self.assertIn("between 15% and 85% of the canvas width", p)
        self.assertNotIn("No text, no letters", p)

    def test_month_prompt_has_fixed_constraints(self):
        c = fixtures.concept()
        p = prompts.month_prompt(c, c["months"][5])
        self.assertTrue(p.startswith(prompts.CREATE_WITH_SWATCH))  # lệnh "tạo ảnh mới" đứng đầu
        self.assertEqual(p.splitlines()[1], fixtures.STYLE_BIBLE)
        self.assertIn("Sea of Galilee", p)
        self.assertNotIn("No text", p)
        self.assertNotIn("Do not depict copyrighted or trademarked characters", p)
        self.assertIn("3:2", p)
        self.assertIn("attached reference image", p)
        self.assertIn("it may be off-center", p)
        self.assertIn("COLOR AND TEXTURE SWATCH", p)
        self.assertIn("Shot type for this month:", p)
        self.assertIn("COLLECTION COLOR ANCHOR", p)
        self.assertIn("soft sage green (#A8B7A0)", p)
        self.assertIn("POSITIVE COLLECTION MOOD", p)
        self.assertIn("Mid-tones and rich color are welcome", p)
        self.assertNotIn("overrides", p)
        self.assertIn("Do not rotate the background", p)
        self.assertNotIn("calm open space at the top center", p)
        self.assertNotIn("attached reference image", prompts.month_prompt(c, c["months"][5], with_reference=False))
        dec = prompts.month_prompt(c, c["months"][11])
        self.assertIn("Focal point", dec)
        self.assertIn("Bethlehem stable", dec)
        self.assertNotIn("Must include this holiday symbol", dec)
        self.assertIn('This calendar is "A Year with Jesus"', dec)
        self.assertLess(dec.index("Focal point"), dec.index("Scene:"))  # trọng tâm nói trước cảnh

    def test_prompts_say_create_a_new_image(self):
        # ChatGPT từng trả lời "hãy tải ảnh tham chiếu lên" vì prompt không nói rõ là tạo ảnh mới.
        c = fixtures.concept()
        c["year"] = 2027
        a = prompts.anchor_prompt(c)
        self.assertTrue(a.startswith(prompts.CREATE_NEW))
        self.assertNotIn("This image defines", a)
        self.assertTrue(prompts.cover_prompt(c).startswith(prompts.CREATE_WITH_SWATCH))
        self.assertTrue(prompts.month_prompt(c, c["months"][0], with_reference=False).startswith(prompts.CREATE_NEW))

    def test_cover_year_is_rendered_only_once(self):
        c = fixtures.concept()
        c["year"] = 2027
        c["cover"]["title"] = "Treasures of Bethlehem 2027"
        c["cover"]["subtitle"] = "12 Practices of Courage for 2027"
        p = prompts.cover_prompt(c)
        self.assertIn('spelled exactly: "Treasures of Bethlehem".', p)
        self.assertIn('spelled exactly: "12 Practices of Courage".', p)
        self.assertEqual(p.count("2027"), 1)

    def test_grid_prompt_has_no_double_periods(self):
        c = fixtures.concept()
        c["buyer"] = "Christian mothers."
        c["style"]["surface_system"] = "Matte blue poster ink."
        self.assertNotIn("..", prompts.grid_background_prompt(c))

    def test_one_scene_12_seasons_keeps_place_friendly_shots(self):
        from calforge.imagegen import shots

        order = shots.assign("Nature at the Window", "one_scene_12_seasons")
        self.assertEqual(len(order), 12)
        self.assertTrue(set(order) <= set(shots.PLACE_SHOTS))
        self.assertTrue(all(a != b for a, b in zip(order, order[1:])))  # không trùng tháng liền kề

    def test_single_images_drop_per_month_motif_wording(self):
        c = fixtures.concept()
        c["year"] = 2027
        c["style"]["recurring_motif"] = "a tiny gold star, free to sit in a different place each month"
        for p in (prompts.anchor_prompt(c), prompts.cover_prompt(c)):
            self.assertIn("Include subtly: a tiny gold star (one small instance)", p)
            motif_line = next(l for l in p.splitlines() if "Include subtly:" in l)
            self.assertNotIn("each month", motif_line.split("Include subtly:")[1])

    def test_p1_and_p2_rules_are_consistent(self):
        root = Path(tempfile.gettempdir()) / "no-projects"
        forced = templates.p1_angles("flowers", 2027, "US", 1, [], root, family="mid_century_retro")
        self.assertIn("If a REQUIRED PRODUCTION STYLE or REQUIRED STYLE SPLIT is given above, follow it exactly", forced)
        p2 = templates.p2_concept(fixtures.ANGLE, "soft watercolor", 2027, "US")
        self.assertIn("Focal subjects must be specific to the niche and buyer expectation", p2)
        self.assertIn("tint of shared_base_color", p2)
        self.assertIn("The grid background has no decorative motifs", p2)
        self.assertNotIn("decorative motif clusters", p2)

    def test_each_month_gets_a_different_shot(self):
        from calforge.imagegen import shots

        order = shots.assign("A Year with Jesus")
        self.assertEqual(len(order), 12)
        self.assertEqual(len(set(order)), 12)
        self.assertEqual(order, shots.assign("A Year with Jesus"))  # chạy lại ra đúng thứ tự cũ
        self.assertNotEqual(order, shots.assign("Nature at the Window"))  # cuốn khác, thứ tự khác
        c = fixtures.concept()
        lines = [next(l for l in prompts.month_prompt(c, m).splitlines() if l.startswith("Shot type"))
                 for m in c["months"]]
        self.assertEqual(len(set(lines)), 12)
        c["months"][0]["shot"] = "overhead"  # khung đã lưu trong concept được ưu tiên
        self.assertIn("OVERHEAD VIEW", prompts.month_prompt(c, c["months"][0]))

    def test_p2_receives_the_month_shots(self):
        p = templates.p2_concept(fixtures.ANGLE, "soft watercolor", 2027, "US")
        self.assertIn("Shot type assigned to each month", p)
        self.assertIn("- Dec: ", p)

    def test_swatch_keeps_colors_but_not_layout(self):
        from PIL import Image
        from calforge.imagegen.swatch import make_swatch

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "anchor.png"
            img = Image.new("RGB", (1536, 1024), (240, 200, 90))
            img.paste((40, 90, 160), (0, 0, 1536, 300))  # dải trời xanh phía trên
            img.save(src)
            out = make_swatch(src, Path(tmp) / "anchor_swatch.png")
            with Image.open(out) as sw:
                self.assertEqual(sw.size, (1536, 1024))
                colors = {c for _, c in sw.convert("RGB").getcolors(1 << 20)}
            self.assertIn((240, 200, 90), colors)
            self.assertIn((40, 90, 160), colors)

    def test_ai_chooses_colors_freely(self):
        from calforge.ideation.validate import validate_concept

        c = fixtures.concept()
        c["style"]["shared_base_color"] = {"name": "deep forest", "hex": "#1F3B2D"}  # nền đậm cũng được
        c["style"]["palette"]["paper"] = "#F7F3EC"                                     # nền grid kem cũng được
        errors, _ = validate_concept(c, 2027)
        self.assertFalse(any("shared_base_color" in e or "cream" in e for e in errors), errors)
        p = prompts.month_prompt(c, c["months"][0])
        self.assertIn("use deep forest (#1F3B2D) as the shared ground", p)
        p1 = templates.p1_angles("gardening", 2027, "US", 1, [], Path(tempfile.gettempdir()) / "no-projects")
        p2 = templates.p2_concept(fixtures.ANGLE, "soft watercolor", 2027, "US")
        for text in (p1, p2):
            self.assertNotIn("cream", text.lower())
            self.assertNotIn("sky blue", text.lower())

    def test_mid_tone_base_is_kept_as_is(self):
        c = fixtures.concept()
        c["style"]["shared_base_color"] = {"name": "dusty teal", "hex": "#5E8C8A"}
        p = prompts.month_prompt(c, c["months"][0])
        self.assertIn("use dusty teal (#5E8C8A) as the shared ground/surface color", p)
        self.assertNotIn("is very dark", p)
        from calforge.ideation.validate import validate_concept
        errors, _ = validate_concept(c, 2027)
        self.assertFalse(any("shared_base_color" in e for e in errors), errors)

    def test_grid_prompt_never_requests_a_dark_surface(self):
        c = fixtures.concept()
        c["style"]["palette"]["title"] = "#F8F8F8"
        c["style"]["palette"]["text"] = "#FFFFFF"
        p = prompts.grid_background_prompt(c)
        self.assertIn("always uses dark software title/body text", p)
        self.assertIn("renderer will replace them with dark", p)
        self.assertIn("LIGHT pastel tint", p)
        self.assertNotIn("clearly DARK muted shade", p)
        self.assertNotIn("subdued deep tones for light", p)


if __name__ == "__main__":
    unittest.main()


class GridMaterialTest(unittest.TestCase):
    def test_materials_are_spread_evenly(self):
        from calforge.imagegen import prompts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            picks = []
            for i in range(6):
                key = prompts.next_grid_material(root)
                picks.append(key)
                c = fixtures.concept()
                c["style"]["grid_material"] = key
                d = root / "kw" / f"b{i}" / "_he_thong"
                d.mkdir(parents=True)
                (d / "concept.json").write_text(json.dumps(c), encoding="utf-8")
        self.assertEqual(picks[:3], list(prompts.GRID_MATERIALS))     # 3 cuốn liên tiếp = đủ 3 loại
        self.assertEqual(sorted(picks[3:]), sorted(prompts.GRID_MATERIALS))

    def test_prompt_uses_locked_material(self):
        from calforge.imagegen import prompts
        c = fixtures.concept()
        c["style"]["grid_material"] = "laid"
        text = prompts.grid_background_prompt(c)
        self.assertIn("laid writing paper", text)
        self.assertNotIn("watercolor paper", text)
        self.assertTrue(text.startswith(prompts.CREATE_NEW))
        self.assertIn("no watercolor washes", text)                   # giấy khô: cấm vệt loang
        self.assertNotIn("blended undertones", text)
        c["style"]["grid_material"] = "watercolor"
        self.assertNotIn("no watercolor washes", prompts.grid_background_prompt(c))


class PortfolioFingerprintTest(unittest.TestCase):
    def test_portfolio_is_compact_and_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kw, n in (("nature", 2), ("dogs", 60)):
                for i in range(n):
                    c = fixtures.concept()
                    c["title"] = f"{kw} book {i}"
                    if kw == "nature":
                        c["fingerprint"] = {"promise": "calm", "subject_world": "shorelines",
                                            "months": [f"s{m}" for m in range(12)]}
                    d = root / kw / f"b{i}" / "_he_thong"
                    d.mkdir(parents=True)
                    (d / "concept.json").write_text(json.dumps(c), encoding="utf-8")
            text = catalog.portfolio_text(root, "nature", short_limit=10, title_limit=20)
        self.assertIn("world: shorelines | months: s0; s1", text)      # cùng keyword: đủ vân tay
        self.assertEqual(text.count("| months:"), 2)                   # keyword khác không kèm 12 cảnh
        self.assertIn("also:", text)
        self.assertIn("...and 30 older calendars", text)


class StyleSplitTest(unittest.TestCase):
    def test_quota_spreads_families_by_least_used(self):
        ids = [f["id"] for f in catalog.families()]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(catalog.family_quota(root, 3), {i: 1 for i in ids})
            c = fixtures.concept()
            c["style"]["family"] = ids[0]
            d = root / "kw" / "Old Book" / "_he_thong"
            d.mkdir(parents=True)
            (d / "concept.json").write_text(json.dumps(c), encoding="utf-8")
            self.assertEqual(catalog.family_quota(root, 3), {i: 1 for i in ids})     # vẫn đều trong batch
            self.assertEqual(catalog.family_quota(root, 2), {ids[1]: 1, ids[2]: 1})   # suất dư: họ ít cuốn trước
            self.assertEqual(catalog.family_quota(root, 7), {ids[0]: 2, ids[1]: 3, ids[2]: 2})

    def test_batch_follows_style_split(self):
        ids = [f["id"] for f in catalog.families()]
        base = fixtures.angles_payload()["angles"][0]
        angles = [dict(base, id=f"a{i + 1}", title=f"Idea {i + 1}", style_family=ids[i // 3]) for i in range(9)]
        wrong = [dict(a, style_family=ids[0]) for a in angles]
        pick = ["r1a1", "r1a4", "r1a7"]
        too_many = fenced({"decisions": [{"id": f"r1a{i + 1}", "keep": True} for i in range(9)],
                           "selected": ["r1a1", "r1a2", "r1a3"]})
        good = fenced({"decisions": [{"id": f"r1a{i + 1}", "keep": True} for i in range(9)], "selected": pick})
        fake = FakeChatGPT([fenced({"angles": wrong}), fenced({"angles": angles}), too_many, good]
                           + [fenced(fixtures.concept())] * 3)
        with tempfile.TemporaryDirectory() as tmp:
            res = run_ideation("Nature", fake, Path(tmp), year=2027, auto_pick=3, max_repairs=2)
            fams = [json.loads((c / "_he_thong" / "concept.json").read_text(encoding="utf-8"))["style"]["family"]
                    for c in res.concepts]
        self.assertIn("REQUIRED STYLE SPLIT", fake.prompts[0][1])
        self.assertIn("style split needs exactly 3", fake.prompts[1][1])     # P1 sai tỉ lệ -> bắt sửa
        self.assertIn("STYLE SPLIT", fake.prompts[2][1])
        self.assertIn("allows at most 1", fake.prompts[3][1])                # P1b chọn lệch -> bắt sửa
        self.assertEqual(sorted(fams), sorted(ids))                           # 3 cuốn = 3 style khác nhau


class GridLayoutRotationTest(unittest.TestCase):
    def test_layouts_spread_evenly_and_avoid_bad_pairs(self):
        from calforge.imagegen import prompts
        from calforge.render import grid_layouts as gl
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            picks = []
            for i in range(15):
                mat = prompts.next_grid_material(root)
                lay = gl.next_grid_layout(root, mat)
                picks.append((mat, lay))
                c = fixtures.concept()
                c["style"].update(grid_material=mat, grid_layout=lay)
                d = root / "kw" / f"b{i}" / "_he_thong"
                d.mkdir(parents=True)
                (d / "concept.json").write_text(json.dumps(c), encoding="utf-8")
        counts = {k: sum(l == k for _, l in picks) for k in gl.ROTATION}
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)       # 15 cuốn -> mỗi bố cục ~3
        self.assertFalse([p for p in picks if p[1] in gl.AVOID.get(p[0], ())])     # không có cặp hợp kém
        self.assertGreater(len(set(picks)), 5)                                       # không khoá cặp chất liệu-bố cục



class RepairContextTest(unittest.TestCase):
    def test_repair_always_carries_json_and_resends_on_lost_context(self):
        from calforge.ideation.pipeline import _ask_validated

        class Chat:
            last_was_cached = False

            def __init__(self):
                self.prompts = []
                self.answers = ['```json\n{"a": 1}\n```',
                                "The original JSON is not available in this conversation. Please paste the original JSON.",
                                '```json\n{"a": 2}\n```']

            def ask(self, prompt, label):
                self.prompts.append(prompt)
                return self.answers.pop(0)

        chat = Chat()
        data, errors, _ = _ask_validated(chat, "p2", "go", lambda d: ([] if d.get("a") == 2 else ["a must be 2"], []), 1)
        self.assertEqual((data, errors), ({"a": 2}, []))                 # lượt gửi lại không tính là một lần sửa
        self.assertIn('{"a":1}', chat.prompts[1])                        # lần sửa có kèm JSON cũ
        self.assertIn('{"a":1}', chat.prompts[2])


class BrokenAnswerNotCachedTest(unittest.TestCase):
    def test_failed_answers_are_asked_again_next_run(self):
        from calforge.ideation.pipeline import _ask_validated
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(Path(tmp))

            class Chat:
                def __init__(self, answers):
                    self.answers, self.asked = list(answers), []
                    self.ledger, self.last_was_cached = ledger, False

                def ask(self, prompt, label):
                    cached = ledger.cached(label)
                    if cached is not None:
                        return cached
                    self.asked.append(label)
                    a = self.answers.pop(0)
                    ledger.record(label, prompt, a)
                    return a

            bad = Chat(["no json", "still no json"])
            _, errors, _ = _ask_validated(bad, "p1", "go", lambda d: ([], []), 1)
            self.assertTrue(errors)
            good = Chat(['```json\n{"ok": 1}\n```'])            # chạy lại: phải hỏi ChatGPT thật, không dùng câu hỏng
            data, errors, _ = _ask_validated(good, "p1", "go", lambda d: ([], []), 1)
            self.assertEqual((data, errors, good.asked), ({"ok": 1}, [], ["p1"]))
