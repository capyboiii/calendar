"""Trang "Làm theo ảnh mẫu": prompt (đúng nguyên văn + ngày tính theo năm), phiên nhiều ảnh, từng bước của một cuốn
(artwork 10+2, tên + listing, bìa, 12 trang lịch có OCR), đổi tài khoản khi lỗi, chỉ dùng tài khoản Plus."""
import io
import json
import tempfile
import threading
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout  # noqa: F401
from calforge.clone import prompts, run, session, store
from calforge.imagegen.driver import NavError, QuotaExceeded, TempError, ThirdPartyIPRefused

USER_CALLS_2027 = {
    1: 'CALL 1: Page titled "JANUARY 2027". Color tone and motifs from attached image 1. January 1 falls on Friday, 31 days. Notes: Jan 1 New Year\'s Day, Jan 18 Martin Luther King Jr. Day.',
    3: 'CALL 3: Page titled "MARCH 2027". Color tone and motifs from attached image 3. March 1 falls on Monday, 31 days. Notes: Mar 14 Daylight Saving Time Begins, Mar 17 St. Patrick\'s Day, Mar 26 Good Friday, Mar 28 Easter Sunday.',
    8: 'CALL 8: Page titled "AUGUST 2027". Color tone and motifs from attached image 8. August 1 falls on Sunday, 31 days. No holidays.',
    9: 'CALL 9: Page titled "SEPTEMBER 2027". Color tone and motifs from attached image 9. September 1 falls on Wednesday, 30 days. Notes: Sep 6 Labor Day, Sep 11 Patriot Day, Sep 12 Grandparents Day.',
    10: 'CALL 10: Page titled "OCTOBER 2027". Color tone and motifs from attached image 10. October 1 falls on Friday, 31 days. Notes: Oct 11 Columbus Day / Indigenous Peoples\' Day, Oct 31 Halloween.',
}
USER_CALL_11 = 'CALL 11: Page titled "NOVEMBER 2027". Color tone and motifs from attached image 1. November 1 falls on Monday, 30 days. Notes: Nov 2 Election Day, Nov 7 Daylight Saving Time Ends, Nov 11 Veterans Day, Nov 25 Thanksgiving.'


def png(color=(120, 80, 60), size=(1536, 1152)) -> bytes:
    from PIL import ImageDraw
    buf = io.BytesIO()
    im = Image.new("RGB", size, color)
    x = color[0] * size[0] // 300 + color[1] % 40 * 3        # mỗi màu một khối ở chỗ khác: ảnh khác hẳn nhau
    ImageDraw.Draw(im).rectangle((x, 100, x + size[0] // 6, size[1] - 100), fill=(255 - color[1], color[0], 30))
    im.save(buf, "PNG")
    return buf.getvalue()


def distinct(n, start=0, size=(1536, 1152)) -> list[bytes]:
    return [png(((start + i) * 19 % 256, (start + i) * 53 % 256, 90), size) for i in range(n)]


META = {"title": "Garden Cats", "subtitle": "Twelve cozy friends", "style_name": "Soft watercolor",
        "buyer": "cat lovers", "keyword": "cat calendar", "months": [f"cat number {i}" for i in range(1, 13)],
        "etsy_title": "2027 Cat Wall Calendar, Soft Watercolor Garden Cats, Cozy Cat Lover Gift",
        "etsy_description": ("A 2027 cat wall calendar with twelve soft watercolor garden cats. " * 10
                             + "\nWhat's inside\n- 12 artworks\n- 12 monthly grids\n- a cover"),
        "tags": [f"cat tag {chr(97 + i)}" for i in range(13)]}


class PromptTest(unittest.TestCase):
    def test_grid_calls_match_the_approved_2027_text_exactly(self):
        for m, text in USER_CALLS_2027.items():
            self.assertEqual(prompts._call(2027, m, m), text)
        first = prompts.grid_prompt(2027, list(range(1, 11)))
        self.assertTrue(first.startswith("I have attached 10 artwork images in order: image 1 = January, image 2 = "
                                         "February, … image 10 = October."))
        self.assertIn("use the SAME layout on all 10 pages", first)
        self.assertIn("Call the image generation tool 10 SEPARATE TIMES", first)
        cont = prompts.grid_continue(2027, [11, 12])
        self.assertTrue(cont.startswith("Same rules as before. I have attached 2 more artworks: image 1 = November, "
                                        "image 2 = December.\nCall the image tool 2 SEPARATE times. Use the SAME "
                                        "layout as the previous 10 pages."))
        self.assertIn(USER_CALL_11, cont)

    def test_dates_follow_the_year(self):
        c = prompts._call(2028, 1, 1)
        self.assertIn('"JANUARY 2028"', c)
        self.assertIn("January 1 falls on Saturday, 31 days", c)
        self.assertIn("Jan 17 Martin Luther King Jr. Day", c)
        self.assertIn("February 1 falls on Tuesday, 29 days", prompts._call(2028, 2, 2))   # năm nhuận
        self.assertIn("Apr 16 Easter Sunday", prompts._call(2028, 4, 4))                   # Phục sinh 2028 sang tháng 4
        self.assertIn("Nov 7 Election Day", prompts._call(2028, 11, 1))

    def test_art_prompts(self):
        self.assertIn("10 SEPARATE image outputs", prompts.art_prompt(3))
        plan = prompts.art_plan(3)                                  # 3 ảnh mẫu: 3 tranh giữ chủ thể, 9 tranh chủ thể mới
        self.assertIn("- Artwork 1: reference 1 - KEEP its subject", plan)
        self.assertIn("- Artwork 4: reference 1 - NEW subject", plan)
        self.assertIn("- Artwork 12: reference 3 - NEW subject", plan)
        self.assertEqual(plan.count("KEEP"), 3)
        self.assertEqual(prompts.art_plan(10).count("NEW subject"), 2)      # 10 ảnh mẫu: chỉ tranh 11, 12 tự nghĩ
        self.assertEqual(prompts.art_plan(1).count("KEEP"), 1)
        self.assertIn("VARIETY ACROSS THE SET", prompts.art_prompt(2))
        self.assertIn("write a NEW text of the same kind instead of copying it", prompts.art_prompt(2))
        self.assertIn("never a copy", prompts.ART_CONTINUE)
        self.assertNotIn("{plan}", prompts.art_resume([4], 2))
        self.assertEqual(prompts.art_continue([11, 12]), prompts.ART_CONTINUE)
        self.assertIn("generate ONLY artwork 8, 9, 10, 11, 12", prompts.art_continue([8, 9, 10, 11, 12]))
        resume = prompts.art_resume([5, 11], 3)
        self.assertIn("I have attached reference images", resume)
        self.assertIn("generate ONLY artwork 5, 11", resume)
        self.assertIn("2 SEPARATE image outputs", resume)
        self.assertIn("Artwork 11 and Artwork 12: choose the composition", resume)
        self.assertNotIn("snowy", prompts.ART_CONTINUE)
        self.assertIn('"Garden Cats"', prompts.cover_prompt("Garden Cats", "x", 2027))
        self.assertIn("4 attached artworks", prompts.cover_prompt("Garden Cats", "x", 2027, fresh=True))
        layout_ref = prompts.grid_prompt(2027, [4, 9], layout_ref=True)
        self.assertIn("image 2 = April, image 3 = September", layout_ref)
        self.assertIn("CALL 4: Page titled \"APRIL 2027\". Color tone and motifs from attached image 2.", layout_ref)


# ------------------------------------------------------------------ phiên nhiều ảnh (trang giả)
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePage:
    def __init__(self, clock, script, images):
        self.clock, self.script, self.images = clock, script, images

    def wait_for_timeout(self, ms):
        self.clock.t += ms / 1000


def state(assistant=1, busy=False, srcs=(), tail="", pending=False):
    imgs = [{"src": s, "w": 1536, "h": 1152, "done": True} for s in srcs]
    return {"assistant": assistant, "user": 1, "busy": busy, "pending": pending, "imgs": imgs, "pageImgs": imgs,
            "tail": tail}


class CollectTest(unittest.TestCase):
    def collect(self, script, want, images=None, limited=None):
        clock = Clock()
        images = images or {f"blob:{i}": d for i, d in enumerate(distinct(14))}
        page = FakePage(clock, script, images)
        s = session.Session(page, Path("p"), clock=clock)
        s.w._limited = lambda page, since: limited(clock.t) if limited else None

        def fake_eval(page, js, *args):
            if args:
                import base64
                return base64.b64encode(page.images[args[0]]).decode()
            return page.script(clock.t)
        with mock.patch.object(session, "_eval", fake_eval):
            turn = s._collect({"assistant": 0, "pageImgs": [], "imgs": []}, want)
        self.clock = clock
        return turn

    def test_ten_images_arrive_one_by_one(self):
        def script(t):
            n = min(10, int(t // 30))
            return state(busy=n < 10, srcs=[f"blob:{i}" for i in range(n)])
        turn = self.collect(script, 10)
        self.assertEqual(len(turn.images), 10)
        self.assertIsNone(turn.problem)
        self.assertLess(self.clock.t, 340)

    def test_duplicate_image_with_new_url_is_dropped(self):
        imgs = {f"blob:{i}": d for i, d in enumerate(distinct(3))}
        imgs["blob:dup"] = imgs["blob:1"]
        turn = self.collect(lambda t: state(srcs=["blob:0", "blob:1", "blob:dup", "blob:2"]), 4, images=imgs)
        self.assertEqual(len(turn.images), 3)

    def test_turn_ends_short_then_quota_text(self):
        def script(t):
            if t < 60:
                return state(busy=True, srcs=["blob:0", "blob:1"])
            return state(srcs=["blob:0", "blob:1"], tail="You've hit the plus plan limit for image generation.")
        turn = self.collect(script, 10)
        self.assertEqual(len(turn.images), 2)                  # 2 ảnh đã ra vẫn nhận
        self.assertIsInstance(turn.problem, QuotaExceeded)

    def test_refusal_and_server_error_without_images(self):
        turn = self.collect(lambda t: state(tail="I can't create that, it may violate our content policies."), 10)
        self.assertIsInstance(turn.problem, ThirdPartyIPRefused)
        turn = self.collect(lambda t: state(tail="Something went wrong. Please try again."), 10)
        self.assertIsInstance(turn.problem, TempError)
        self.assertEqual(turn.images, [])

    def test_still_drawing_text_is_not_an_error(self):
        def script(t):
            if t < 200:
                return state(tail="Creating image", srcs=[])
            return state(srcs=["blob:0"])
        turn = self.collect(script, 1)
        self.assertEqual(len(turn.images), 1)
        self.assertIsNone(turn.problem)

    def test_stuck_tab(self):
        turn = self.collect(lambda t: state(assistant=0), 10)
        self.assertIn("tab kẹt", str(turn.problem))


# ------------------------------------------------------------------ một cuốn với phiên giả
class FakeSession:
    """ask_images trả lần lượt các lượt đã soạn; ghi lại prompt + ảnh đính để kiểm tra."""

    def __init__(self, turns, texts=None):
        self.turns, self.texts = list(turns), list(texts or [json.dumps(META)])
        self.sent = []
        self.page = object()
        self.w = types.SimpleNamespace(_attach=lambda page, files: self.sent.append(("attach", list(files))))

    def open(self):
        pass

    def ask_images(self, prompt, want, attach=None):
        self.sent.append((prompt, want, list(attach or [])))
        item = self.turns.pop(0) if self.turns else session.Turn(problem=TempError("hết kịch bản"))
        if isinstance(item, Exception):
            raise item
        return item

    def ask_text(self, prompt):
        self.sent.append((prompt, "text", []))
        t = self.texts.pop(0)
        return f"```json\n{t}\n```" if not t.startswith("!") else t[1:]


def new_item(tmp: Path, n_refs=3, year=2027):
    cfg = {"projects_dir": str(tmp / "projects"), "profiles_dir": str(tmp / "prof"), "imagegen": {}}
    it = store.add(cfg["projects_dir"], [(f"a{i}.png", png((i * 40, 10, 10))) for i in range(n_refs)],
                   group="Cats Clone", year=year)
    return cfg, store.root(cfg["projects_dir"]) / it["id"]


class BookArtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg, self.d = new_item(Path(self.tmp.name))

    def test_ten_then_two_then_name_then_cover(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(10)), session.Turn(distinct(2, 20)), session.Turn(distinct(1, 40))])
        b.art_work(s, "acc3")
        self.assertEqual(s.sent[0][0], prompts.art_prompt(3))
        self.assertEqual([p.name for p in s.sent[0][2]], ["ref01.png", "ref02.png", "ref03.png"])
        self.assertEqual(s.sent[1][0], prompts.ART_CONTINUE)               # nhắn tiếp đúng nguyên văn
        self.assertEqual(s.sent[1][2], [])                                 # cùng phiên: không đính lại
        self.assertEqual(s.sent[2][1], "text")
        self.assertIn('"Garden Cats"', s.sent[3][0])                       # bìa dùng tên ChatGPT đặt
        book = Path(b.item["book"])
        self.assertTrue(book.name.startswith("WCB-GC-"))                    # thư mục SKU theo tên cuốn
        self.assertEqual(book.parent.name, "cats-clone")
        self.assertEqual(b.missing("m"), [])
        self.assertIsNotNone(b.done("cover"))
        concept = json.loads(layout.concept_file(book).read_text(encoding="utf-8"))
        self.assertEqual((concept["product"], concept["style"]["grid_mode"], concept["style"]["mockup_mode"]),
                         ("wall_grid", "ai_page", "ai"))
        self.assertEqual(concept["months"][11]["subtitle"], "cat number 12")
        listing = json.loads(layout.listing_file(book).read_text(encoding="utf-8"))
        self.assertEqual(listing["title"], META["etsy_title"])
        self.assertIn("TITLE", (book / "listing.txt").read_text(encoding="utf-8-sig"))
        self.assertEqual(len(list((layout.tech(book) / "anh_mau").iterdir())), 3)
        self.assertFalse(list((self.d / "work").rglob("*.png")))           # ảnh đã chuyển hết sang cuốn

    def test_short_turns_keep_asking_for_exact_missing_numbers(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(7)), session.Turn(distinct(3, 10)), session.Turn(distinct(2, 20)),
                         session.Turn(distinct(1, 40))])
        b.art_work(s, "acc3")
        self.assertIn("generate ONLY artwork 8, 9, 10, 11, 12", s.sent[1][0])
        self.assertEqual(s.sent[2][0], prompts.ART_CONTINUE)
        self.assertEqual(b.missing("m"), [])

    def test_resume_in_new_session_only_draws_missing(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(10), problem=QuotaExceeded("limit"))])
        with self.assertRaises(QuotaExceeded):
            b.art_work(s, "acc3")
        self.assertEqual(b.missing("m"), [11, 12])                          # 10 ảnh đã về được giữ
        s2 = FakeSession([session.Turn(distinct(2, 30)), session.Turn(distinct(1, 50))])
        b.art_work(s2, "acc4")
        self.assertIn("generate ONLY artwork 11, 12", s2.sent[0][0])
        self.assertEqual(len(s2.sent[0][2]), 3)                             # phiên mới: đính lại ảnh mẫu
        self.assertEqual(s2.sent[1][1], "text")
        self.assertEqual(b.missing("m"), [])

    def test_new_session_for_name_attaches_artworks(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(10)), session.Turn(distinct(2, 20))], texts=[])
        s.ask_text = mock.Mock(side_effect=QuotaExceeded("chat limit"))
        with self.assertRaises(QuotaExceeded):
            b.art_work(s, "acc3")
        s2 = FakeSession([session.Turn(distinct(1, 40))])
        b.art_work(s2, "acc4")
        self.assertEqual(s2.sent[0][0], "attach")
        self.assertEqual(len(s2.sent[0][1]), 10)                            # 10 artwork đầu cho ChatGPT nhìn
        self.assertIn("4 attached artworks", s2.sent[2][0])                 # bìa: đính 4 artwork làm mẫu
        self.assertEqual(len(s2.sent[2][2]), 4)

    def test_meta_repair_then_ok(self):
        bad = dict(META, tags=["too", "few"])
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(10)), session.Turn(distinct(2, 20)), session.Turn(distinct(1, 40))],
                        texts=["!no json here", json.dumps(bad), json.dumps(META)])
        b.art_work(s, "acc3")
        texts = [p for p, w, _ in s.sent if w == "text"]
        self.assertEqual(len(texts), 3)
        self.assertIn("13", texts[2])                                       # lời sửa nêu đúng lỗi tag

    def test_wrong_size_images_are_rejected_not_numbered(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        square = distinct(1, 70, size=(1024, 1024))
        s = FakeSession([session.Turn(square + distinct(10)), session.Turn(distinct(2, 20)),
                         session.Turn(distinct(1, 40))])
        b.art_work(s, "acc3")
        self.assertEqual(b.missing("m"), [])
        self.assertEqual(len(list((layout.tech(Path(b.item["book"])) / "anh_bi_loai").iterdir())), 1)

    def test_no_progress_raises(self):
        b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        s = FakeSession([session.Turn(distinct(10)), session.Turn([]), session.Turn([])])
        with self.assertRaises(TempError):
            b.art_work(s, "acc3")


class BookGridTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg, self.d = new_item(Path(self.tmp.name))
        self.b = run.Book(self.cfg, self.d, on_event=lambda *_: None)
        self.b.art_work(FakeSession([session.Turn(distinct(10)), session.Turn(distinct(2, 20)),
                                     session.Turn(distinct(1, 40))]), "acc3")
        self.pages = {}                                                     # bytes ảnh -> tháng thật trên trang

    def grid_pages(self, months, start=100):
        out = []
        for i, m in enumerate(months):
            data = png(((start + i) * 7 % 256, m * 20, 200))
            self.pages[data] = m
            out.append(data)
        return out

    def accept(self, path, year, month):
        real = self.pages.get(Path(path).read_bytes())          # OCR giả: đọc được tên tháng thật trên trang
        if real == month:
            return None
        return f'sai tên tháng: trang ghi "{prompts.MONTHS[real - 1]}"' if real else "lịch sai: thiếu ngày 15"

    def test_ten_then_two_with_ocr(self):
        s = FakeSession([session.Turn(self.grid_pages(range(1, 11))), session.Turn(self.grid_pages([11, 12], 50))])
        with mock.patch("calforge.imagegen.generate.accept_grid_page", self.accept):
            self.b.grid_work(s, "acc4")
        self.assertEqual(self.b.missing("g"), [])
        self.assertEqual(s.sent[0][0], prompts.grid_prompt(2027, list(range(1, 11))))
        self.assertEqual([p.name for p in s.sent[0][2]], [f"m{m:02d}.png" for m in range(1, 11)])
        self.assertEqual(s.sent[1][0], prompts.grid_continue(2027, [11, 12]))
        self.assertEqual([p.name for p in s.sent[1][2]], ["m11.png", "m12.png"])

    def test_out_of_order_and_bad_page_redone_in_session(self):
        first = self.grid_pages([2, 1, 3, 4, 5, 6, 7, 8, 9]) + [png((1, 2, 3))]   # trang cuối hỏng (tháng 10)
        s = FakeSession([session.Turn(first), session.Turn(self.grid_pages([10], 60)),
                         session.Turn(self.grid_pages([11, 12], 70))])
        with mock.patch("calforge.imagegen.generate.accept_grid_page", self.accept):
            self.b.grid_work(s, "acc4")
        self.assertEqual(self.b.missing("g"), [])
        self.assertIn("The October page you just made has calendar errors", s.sent[1][0])
        self.assertTrue(list((layout.tech(Path(self.b.item["book"])) / "anh_bi_loai").glob("grid-10*")))

    def test_new_session_uses_a_finished_page_as_layout(self):
        s = FakeSession([session.Turn(self.grid_pages(range(1, 8)), problem=QuotaExceeded("limit"))])
        with mock.patch("calforge.imagegen.generate.accept_grid_page", self.accept), \
                self.assertRaises(QuotaExceeded):
            self.b.grid_work(s, "acc4")
        self.assertEqual(self.b.missing("g"), [8, 9, 10, 11, 12])
        s2 = FakeSession([session.Turn(self.grid_pages([8, 9, 10, 11, 12], 80))])
        with mock.patch("calforge.imagegen.generate.accept_grid_page", self.accept):
            self.b.grid_work(s2, "acc5")
        self.assertIn("1 finished calendar page (image 1)", s2.sent[0][0])
        self.assertEqual([p.name for p in s2.sent[0][2]][0], "g01.png")
        self.assertEqual(self.b.missing("g"), [])


# ------------------------------------------------------------------ đổi tài khoản / chỉ Plus
class FakePool:
    def __init__(self, names):
        self.names, self.dead, self.use, self.rested, self.dropped = list(names), set(), {}, [], []
        self.rest_s = 1800
        self._lock = threading.Lock()

    def acquire(self, role, only=None, prefer=None):
        with self._lock:
            if only in self.use or only in self.dead or any(n == only for n, _ in self.rested):
                return None
            self.use[only] = role
            return only

    def release(self, name):
        with self._lock:
            self.use.pop(name, None)

    def rest(self, name, role, s, why=""):
        self.rested.append((name, why))

    def trouble(self, *a):
        pass

    def drop(self, name, kind, why):
        self.dead.add(name)
        self.dropped.append((name, kind))

    def _resting(self, name, role):
        return any(n == name for n, _ in self.rested)

    def wait_change(self, t):
        pass

    @contextmanager
    def launch_gate(self):
        yield


def accts(names, pool=None):
    pool = pool or FakePool(names)
    a = run.Accounts({"projects_dir": ".", "profiles_dir": "."}, names, on_event=lambda *_: None, pool=pool,
                     open_page=contextmanager(lambda name: (yield object())))
    return a, pool


class StageTest(unittest.TestCase):
    def test_quota_switches_account_and_dead_account_is_dropped(self):
        a, pool = accts(["acc3", "acc4", "acc5"])
        used = []

        def work(s, name):
            used.append(name)
            if name == "acc3":
                raise QuotaExceeded("You've hit the plus plan limit")
            if name == "acc4":
                raise NavError("tài khoản bị đăng xuất: trang ChatGPT đòi đăng nhập lại")
        fake = lambda page, d: types.SimpleNamespace(open=lambda: None)
        self.assertEqual(run.run_stage(a, "x", work, session_factory=fake), "acc5")
        self.assertEqual(used, ["acc3", "acc4", "acc5"])
        self.assertEqual(pool.dropped, [("acc4", "logged_out")])
        self.assertEqual(pool.use, {})                                     # mọi tài khoản đã trả

    def test_avoid_prefers_another_account(self):
        a, _ = accts(["acc3", "acc4"])
        got = run.run_stage(a, "x", lambda s, n: None, avoid={"acc3"},
                            session_factory=lambda p, d: types.SimpleNamespace(open=lambda: None))
        self.assertEqual(got, "acc4")

    def test_three_refusals_reject_book(self):
        a, _ = accts(["acc3"])

        def work(s, name):
            raise ThirdPartyIPRefused("may violate our content policies")
        with self.assertRaises(run.BookRejected):
            run.run_stage(a, "x", work, session_factory=lambda p, d: types.SimpleNamespace(open=lambda: None))

    def test_repeated_temp_errors_give_up_for_now(self):
        a, _ = accts(["acc3"])
        n = []

        def work(s, name):
            n.append(1)
            raise TempError("ảnh không đạt: sai tỉ lệ")          # lỗi của ảnh (không phải lỗi phía server)
        with self.assertRaises(run.StageFailed):
            run.run_stage(a, "x", work, session_factory=lambda p, d: types.SimpleNamespace(open=lambda: None))
        self.assertEqual(len(n), run.MAX_SESSIONS)

    def test_no_plus_account_left(self):
        a, pool = accts(["acc3"])
        pool.dead.add("acc3")
        with self.assertRaises(run.StageFailed):
            run.run_stage(a, "x", lambda s, n: None)

    def test_plus_accounts_filter(self):
        from calforge.llm import accounts, plan
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp)
            info = {"acc1": ("free", False, "2026-10-05T00:00:00+00:00"), "acc2": None,
                    "acc3": ("plus", True, "2030-01-01T00:00:00+00:00"), "acc4": ("plus", True, "2020-01-01T00:00:00+00:00"),
                    "acc5": ("pro", True, "2030-01-01T00:00:00+00:00")}
            for n, v in info.items():
                (pdir / n).mkdir()
                if v:
                    plan.save(pdir / n, {"plan": v[0], "label": v[0], "active": v[1], "expires": v[2]})
            checked = []
            with mock.patch.object(accounts, "has_chatgpt_session", lambda d: True), \
                    mock.patch.object(plan, "_check_one", lambda d: checked.append(d.name)):
                got = run.plus_accounts({"profiles_dir": tmp, "projects_dir": tmp}, on_event=lambda *_: None)
            self.assertEqual(got, ["acc3", "acc5"])                         # Free, hết hạn, chưa rõ gói: bỏ
            self.assertEqual(checked, ["acc2"])                              # chưa rõ gói thì kiểm tra trước


class QueueTest(unittest.TestCase):
    def test_store_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                store.add(tmp, [], group="x")
            with self.assertRaises(ValueError):
                store.add(tmp, [("a.png", png())] * 11)
            with self.assertRaises(ValueError):
                store.add(tmp, [("a.png", b"not an image")])
            it = store.add(tmp, [("a.webp", png()), ("b.png", png((9, 9, 9)))], group="../../Evil Name", year=2028)
            d = store.root(tmp) / it["id"]
            self.assertEqual([p.name for p in store.refs(d)], ["ref01.webp", "ref02.png"])
            self.assertNotIn("/", it["group"])
            self.assertNotIn("\\", it["group"])
            with self.assertRaises(ValueError):
                store.item_dir(tmp, "../x")
            store.write(d, status="running")
            with self.assertRaises(ValueError):
                store.remove(tmp, it["id"])
            store.write(d, status="failed")
            store.retry(tmp, it["id"])
            self.assertEqual(store.read(d)["status"], "pending")
            store.remove(tmp, it["id"])
            self.assertFalse(d.exists())

    def test_run_queue_end_to_end_with_fake_chatgpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, d1 = new_item(Path(tmp))
            _, d2 = new_item(Path(tmp), n_refs=10)
            pages = {}

            def make_session(page, pdir):
                s = FakeSession([])
                state = {"n": 0}

                def ask_images(prompt, want, attach=None):
                    s.sent.append((prompt, want, list(attach or [])))
                    if prompt.startswith("I have attached") and "calendar grid" in prompt or "more artwork" in prompt:
                        months = [int(x) for x in __import__("re").findall(r"CALL (\d+):", prompt)]
                        out = []
                        for m in months:
                            data = png((m * 9, len(pages) % 250, 77))
                            pages[data] = m
                            out.append(data)
                        return session.Turn(out)
                    state["n"] += 1
                    return session.Turn(distinct(want, state["n"] * 13))
                s.ask_images = ask_images
                return s
            plus = ["acc3", "acc4"]
            a, pool = accts(plus)
            with mock.patch.object(run.session, "Session", make_session), \
                    mock.patch("calforge.imagegen.generate.accept_grid_page",
                               lambda p, y, m: None if pages.get(Path(p).read_bytes()) == m else "sai"), \
                    mock.patch.object(run.Book, "finish", lambda self, plus: {"ok": True, "stage": "listing"}):
                res = run.run_queue(cfg, on_event=lambda *_: None, accts=a, plus=plus)
            self.assertEqual([r["ok"] for r in res], [True, True])
            for d in (d1, d2):
                it = store.read(d)
                self.assertEqual(it["status"], "done")
                book = Path(it["book"])
                for job in ["cover"] + [f"m{m:02d}" for m in range(1, 13)] + [f"g{m:02d}" for m in range(1, 13)]:
                    self.assertTrue(list(layout.raw(book).glob(job + ".*")), job)
            self.assertEqual(pool.use, {})

    def test_no_plus_account_marks_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, d = new_item(Path(tmp))
            run.run_queue(cfg, on_event=lambda *_: None, plus=[])
            self.assertEqual(store.read(d)["status"], "failed")
            self.assertIn("Plus", store.read(d)["reason"])




class ThinkingTest(unittest.TestCase):
    def test_no_picker_or_broken_ui_never_blocks(self):
        page = mock.Mock()
        page.locator.return_value.first.count.return_value = 0
        self.assertEqual(session.Session(page, Path("p")).set_thinking_high(), "")
        page = mock.Mock()
        page.locator.return_value.first.count.side_effect = RuntimeError("Target closed")
        self.assertEqual(session.Session(page, Path("p")).set_thinking_high(), "")

    def test_moves_slider_to_top(self):
        state = {"now": "1"}
        slider = mock.Mock()
        slider.get_attribute.side_effect = lambda k: {"aria-valuemax": "2", "aria-valuenow": state["now"]}[k]
        slider.press.side_effect = lambda key: state.update(now="2") if key == "End" else None
        btn = mock.Mock()
        btn.count.return_value, btn.is_visible.return_value = 1, True
        page = mock.Mock()
        page.locator.side_effect = lambda sel: mock.Mock(first=btn if "Select ChatGPT model" in sel else slider)
        page.evaluate.return_value = "High, 3 of 3."
        self.assertEqual(session.Session(page, Path("p")).set_thinking_high(), "High, 3 of 3.")
        slider.press.assert_called_once_with("End")


class StuckFlagsAndReopenTest(unittest.TestCase):
    def test_enough_images_but_page_still_says_drawing(self):
        """Lượt 10 ảnh xong mà trang vẫn giữ nút Stop / khung chờ: ảnh đứng yên 60s là chốt, không chờ 53 phút."""
        c = CollectTest()
        turn = c.collect(lambda t: state(busy=True, pending=True, srcs=[f"blob:{i}" for i in range(min(10, int(t // 20)))]), 10)
        self.assertEqual(len(turn.images), 10)
        self.assertLess(c.clock.t, 300)

    def test_partial_and_stuck_takes_what_is_there(self):
        c = CollectTest()
        turn = c.collect(lambda t: state(busy=True, srcs=["blob:0", "blob:1", "blob:2"]), 10)
        self.assertEqual(len(turn.images), 3)
        self.assertLess(c.clock.t, session.STUCK_S + 30)

    def test_reopen_old_chat_takes_unsaved_images_then_continues_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, d = new_item(Path(tmp))
            store.write(d, art_chat={"url": "https://chatgpt.com/c/abc", "account": "acc3", "saved": 0})
            b = run.Book(cfg, d, on_event=lambda *_: None)
            s = FakeSession([session.Turn(distinct(2, 20)), session.Turn(distinct(1, 40))])
            s.harvest = lambda: distinct(10)
            s.w._find = lambda *a: None
            opened = []
            with mock.patch.object(run.driver, "open_home", lambda page, url: opened.append(url)):
                b.art_work(s, "acc3")
            self.assertEqual(opened, ["https://chatgpt.com/c/abc"])
            self.assertEqual(s.sent[0][0], prompts.ART_CONTINUE)          # không vẽ lại 10 ảnh đầu
            self.assertEqual(b.missing("m"), [])
            self.assertEqual(store.read(d)["art_chat"]["saved"], 12)

    def test_old_chat_of_another_account_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, d = new_item(Path(tmp))
            store.write(d, art_chat={"url": "https://chatgpt.com/c/abc", "account": "acc3", "saved": 0})
            b = run.Book(cfg, d, on_event=lambda *_: None)
            s = FakeSession([session.Turn(distinct(10)), session.Turn(distinct(2, 20)), session.Turn(distinct(1, 40))])
            b.art_work(s, "acc4")
            self.assertEqual(s.sent[0][0], prompts.art_prompt(3))

    def test_prefers_account_with_old_chat(self):
        a, _ = accts(["acc3", "acc4", "acc5"])
        self.assertEqual(a.acquire(prefer="acc5"), "acc5")


class ImagesWithoutNewTurnTest(unittest.TestCase):
    def test_images_attached_to_old_turn_still_count(self):
        c = CollectTest()
        turn = c.collect(lambda t: state(assistant=0, srcs=["blob:0", "blob:1"] if t > 30 else []), 2)
        self.assertEqual(len(turn.images), 2)
        self.assertLess(c.clock.t, 120)


class ServerErrorRotationTest(unittest.TestCase):
    def test_server_side_errors_rest_account_and_switch_not_count_as_failed_session(self):
        a, pool = accts(["acc3", "acc4"])
        used = []

        def work(s, name):
            used.append(name)
            if len(used) <= 3:
                raise TempError("ChatGPT báo lỗi: 'Internal server error'")
        fake = lambda page, d: types.SimpleNamespace(open=lambda: None)
        pool._resting = lambda n, role: False                               # nghỉ 120s xong là dùng lại
        pool.acquire = lambda role, only=None, prefer=None: only if only not in pool.use else None
        self.assertIn(run.run_stage(a, "x", work, session_factory=fake), ("acc3", "acc4"))
        self.assertEqual(len(used), 4)
        self.assertEqual(len(pool.rested), 3)                                # mỗi lần lỗi server: tài khoản nghỉ ngắn
        self.assertTrue(run._server_side("tab kẹt: ChatGPT chưa phản hồi sau 240s"))
        self.assertFalse(run._server_side("ảnh không đạt: sai tỉ lệ"))


class AnyFileTypeTest(unittest.TestCase):
    def raw(self, fmt, **kw):
        buf = io.BytesIO()
        Image.new("RGB", (300, 200), (200, 30, 30)).save(buf, fmt, **kw)
        return buf.getvalue()

    def test_any_image_format_and_pdf_pages(self):
        for name, fmt in (("a.tif", "TIFF"), ("b.bmp", "BMP"), ("c.gif", "GIF"), ("d.ico", "ICO")):
            [(out, data)] = store.to_images(name, self.raw(fmt))
            self.assertTrue(out.endswith(".png"), out)
            with Image.open(io.BytesIO(data)) as im:
                self.assertEqual(im.format, "PNG")
        jpg = self.raw("JPEG")
        self.assertEqual(store.to_images("x.jpg", jpg), [("x.jpg", jpg)])            # JPG/PNG/WEBP giữ nguyên
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page(width=400, height=300)
        pages = store.to_images("mau.pdf", doc.tobytes())
        self.assertEqual([n for n, _ in pages], ["mau-p1.png", "mau-p2.png", "mau-p3.png"])  # mỗi trang một ảnh
        with self.assertRaises(ValueError) as e:
            store.to_images("ghi-chu.docx", b"PK\x03\x04 not an image")
        self.assertIn("ghi-chu.docx", str(e.exception))

    def test_add_counts_pdf_pages_toward_limit(self):
        try:
            import pymupdf
        except ImportError:
            import fitz as pymupdf
        doc = pymupdf.open()
        for _ in range(9):
            doc.new_page(width=400, height=300)
        with tempfile.TemporaryDirectory() as tmp:
            it = store.add(tmp, [("mau.pdf", doc.tobytes()), ("a.bmp", self.raw("BMP"))])
            d = store.root(tmp) / it["id"]
            self.assertEqual(len(store.refs(d)), 10)
            self.assertEqual(store.refs(d)[-1].name, "ref10.png")
            with self.assertRaises(ValueError) as e:
                store.add(tmp, [("mau.pdf", doc.tobytes()), ("a.bmp", self.raw("BMP")), ("b.bmp", self.raw("BMP"))])
            self.assertIn("trang PDF", str(e.exception))
