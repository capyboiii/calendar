"""Listing chuẩn Etsy: luật Etsy soát đúng, ChatGPT sai thì nhờ sửa, vẫn sai / lỗi thì lùi về listing thường,
lựa chọn đi đúng đường từ giao diện -> lệnh -> concept -> listing.json."""
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from calforge import cli, config, layout, pipeline  # noqa: F401
from calforge.publish import etsy_listing as el
from calforge.publish.listing import build_listing, write_listing
from calforge.ui import server

from tests import fixtures
from tests import test_batch_simulation as tb

GOOD = {
    "title": "2027 Garden Cat Wall Calendar, Retro Flower Cats Art, Cat Lover Gift for Her",
    "description": ("This 2027 garden cat wall calendar brings a retro flower cat to every month of the year.\n\n"
                    "Each page shows an original mid-century style illustration of a happy cat among tulips, daisies "
                    "and sunflowers, printed in warm, cheerful colors. It makes a thoughtful gift for cat lovers, "
                    "gardeners and anyone who enjoys vintage floral art on their wall.\n\n"
                    "What's inside\n- 12 original monthly artworks\n- Monthly grids with US holidays\n"
                    "- Large date boxes for notes and appointments\n- Front and back cover"),
    "tags": ["2027 cat calendar", "cat wall calendar", "retro cat art", "flower cat calendar", "cat lover gift",
             "vintage floral art", "garden cat decor", "mid century cats", "cute cat calendar", "gift for her",
             "2027 wall calendar", "cottagecore decor", "kitchen calendar"],
}


def fenced(d):
    return "```json\n" + json.dumps(d) + "\n```"


class RulesTest(unittest.TestCase):
    def test_good_listing_passes(self):
        self.assertEqual(el.validate(GOOD), [])

    def test_every_rule(self):
        cases = {
            "title has 141 characters": {"title": "A" * 0 + ("Calendar " * 16)[:141]},
            'uses ":" 2 times': {"title": "2027 Cat Calendar: Retro Cats: Flower Art Wall Calendar Gift"},
            "does not allow: $": {"title": "2027 Cat Wall Calendar Retro Flower Cats Gift $25 Value"},
            "ALL CAPS": {"title": "2027 CAT WALL CALENDAR RETRO Flower Cats Lover Gift Idea"},
            "repeats these words": {"title": "Cat Calendar 2027, Cat Wall Art, Cat Lover Gift, Retro Flowers"},
            "emojis": {"title": "2027 Cat Wall Calendar Retro Flower Cats Lover Gift 🐱"},
            "too short": {"title": "Cat Calendar"},
            "plain text": {"description": "<p>" + GOOD["description"] + "</p>"},
            "write 600 to 1500": {"description": "A cat calendar."},
            "exactly 13": {"tags": GOOD["tags"][:12]},
            "longer than 20": {"tags": GOOD["tags"][:12] + ["retro flower cat calendar 2027"]},
            "letters, numbers and spaces": {"tags": GOOD["tags"][:12] + ["cat-lover's gift"]},
            "all be different": {"tags": GOOD["tags"][:12] + [GOOD["tags"][0]]},
        }
        for expect, change in cases.items():
            errors = el.validate({**GOOD, **change})
            self.assertTrue(any(expect in e for e in errors), (expect, errors))
        self.assertTrue(el.validate("not a dict"))
        self.assertTrue(el.validate({}))

    def test_once_chars_allowed_once(self):
        self.assertEqual(el.validate({**GOOD, "title": "2027 Cat Wall Calendar: Retro Flower Cats & Garden Art Gift"}), [])

    def test_plain_text_to_html(self):
        out = el.to_html("Hello world.\n\nWhat's inside\n- one & two\n- three\n\nBye.")
        self.assertEqual(out, "<p>Hello world.</p><p>What&#x27;s inside</p><ul><li>one &amp; two</li>"
                              "<li>three</li></ul><p>Bye.</p>")


class FakeBackend:
    def __init__(self, answers):
        self.answers, self.prompts = list(answers), []

    @contextmanager
    def session(self, workdir):
        backend = self

        class Chat:
            def ask(self, prompt, label):
                backend.prompts.append((label, prompt))
                a = backend.answers.pop(0)
                if isinstance(a, BaseException):
                    raise a
                return a
        yield Chat()


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c = Path(self.tmp.name) / "kw" / "WCB-TST-ABCDE"
        layout.ensure_system(self.c)
        concept = {**fixtures.concept(), "year": 2027, "keyword": "cats", "listing_style": "etsy"}
        layout.concept_file(self.c).write_text(json.dumps(concept), encoding="utf-8")
        self.concept = concept
        self.logs = []

    def write(self, backend, cfg=True):
        with mock.patch.object(config, "make_backend", lambda c: backend):
            return write_listing(self.c, {"llm": {}} if cfg else None, self.logs.append)

    def test_first_answer_ok(self):
        b = FakeBackend([fenced(GOOD)])
        lst = self.write(b)
        self.assertEqual((lst["style"], lst["title"]), ("etsy", GOOD["title"]))
        self.assertTrue(lst["description"].startswith("<p>This 2027 garden cat"))
        self.assertTrue(lst["description"].endswith(el.DETAILS_HTML))            # Details cố định nối cuối
        self.assertTrue(lst["description_text"].endswith(el.DETAILS_TEXT))       # bản chữ thường để chép lên Etsy
        self.assertNotIn("<", lst["description_text"])
        self.assertEqual(len(lst["tags"]), 13)
        saved = json.loads(layout.listing_file(self.c).read_text(encoding="utf-8"))
        self.assertEqual(saved, lst)
        prompt = b.prompts[0][1]
        for rule in ("140 characters", "at most once: % : & +", "exactly 13 different tags", "plain text"):
            self.assertIn(rule, prompt)

    def test_broken_then_repaired(self):
        bad = {**GOOD, "title": "2027 CAT WALL CALENDAR RETRO Flower Cats: Gift: Art"}
        b = FakeBackend([fenced(bad), "Sure! Here you go, no JSON", fenced(GOOD)])
        lst = self.write(b)
        self.assertEqual(lst["style"], "etsy")
        self.assertEqual([l for l, _ in b.prompts], ["etsy_listing", "etsy_listing_repair1", "etsy_listing_repair2"])
        self.assertIn("ALL CAPS", b.prompts[1][1])
        self.assertIn(bad["title"], b.prompts[1][1])                             # sửa thì phải kèm bài cũ
        self.assertIn("did not contain the JSON", b.prompts[2][1])

    def test_still_broken_falls_back_to_standard(self):
        b = FakeBackend([fenced({**GOOD, "tags": ["x"]})] * 3)
        lst = self.write(b)
        self.assertNotIn("style", lst)
        self.assertEqual(lst, build_listing(self.concept))                       # vẫn có listing, cuốn không kẹt
        self.assertTrue(any("vẫn chưa đạt luật" in l for l in self.logs))

    def test_chatgpt_error_falls_back(self):
        for err in (RuntimeError("Không còn tài khoản"), TimeoutError("chat timeout")):
            lst = self.write(FakeBackend([err]))
            self.assertEqual(lst, build_listing(self.concept))
        self.assertTrue(any("Không viết được listing Etsy" in l for l in self.logs))

    def test_standard_books_and_no_cfg_never_call_chatgpt(self):
        b = FakeBackend([])
        self.assertEqual(self.write(b, cfg=False), build_listing(self.concept))
        self.concept["listing_style"] = "standard"
        layout.concept_file(self.c).write_text(json.dumps(self.concept), encoding="utf-8")
        self.assertEqual(self.write(b), build_listing(self.concept))
        self.assertEqual(b.prompts, [])


class OptionPathTest(unittest.TestCase):
    def test_ui_param_to_cli_args(self):
        args, _ = server.run_args({"keyword": "cats", "product": "wall_grid", "listing_style": "etsy"})
        self.assertEqual(args[args.index("--listing-style") + 1], "etsy")
        args, _ = server.run_args({"keyword": "cats", "product": "wall_grid", "listing_style": "standard"})
        self.assertNotIn("--listing-style", args)
        args, _ = server.run_args({"keyword": "cats", "listing_style": "<script>"})
        self.assertNotIn("--listing-style", args)

    def test_batch_saves_choice_in_every_concept(self):
        s = tb.Sim(self, 61, fault=0)
        for style, kw in (("etsy", "foxes"), (None, "owls")):
            out = {}

            def go(style=style, kw=kw):
                out["rows"] = pipeline.run(kw, s.cfg, auto_pick=2, printify=False, product="wall_grid",
                                           grid_mode="ai_page", retry_wait_s=0, listing_style=style,
                                           on_event=lambda *_: None)
            t = threading.Thread(target=go, daemon=True)
            t.start()
            t.join(120)
            self.assertFalse(t.is_alive())
            for b in s.books(kw):
                c = json.loads(layout.concept_file(b).read_text(encoding="utf-8"))
                self.assertEqual(c["listing_style"], style or "standard")
        tb.check_invariants(self, s)


if __name__ == "__main__":
    unittest.main()


class ListingTxtTest(unittest.TestCase):
    def test_txt_file_next_to_print_folders(self):
        from calforge.publish.listing import write_listing_txt
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "kw" / "WCB-TST-ABCDE"
            layout.ensure_system(c)
            concept = {**fixtures.concept(), "year": 2027}
            layout.concept_file(c).write_text(json.dumps(concept), encoding="utf-8")
            lst = write_listing(c)                                         # listing thường: tự có listing.txt
            text = (c / "listing.txt").read_text(encoding="utf-8-sig")
            self.assertTrue(text.startswith("TITLE\n" + lst["title"] + "\n\nTAGS\n"))
            self.assertIn(", ".join(lst["tags"]), text)
            self.assertNotIn("<", text)                                    # chữ thường, không còn thẻ HTML
            self.assertIn("Details\n- Sizes:\n  - 11 x 8.5 in (opens to 11 x 17 in)\n  - 14 x 11.5 in", text)
            write_listing_txt(c, {"title": "T", "tags": ["a"], "description": "<p>x</p>", "description_text": "PLAIN"})
            self.assertIn("DESCRIPTION\nPLAIN", (c / "listing.txt").read_text(encoding="utf-8-sig"))   # bản Etsy
