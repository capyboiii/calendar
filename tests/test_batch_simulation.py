"""GIẢ LẬP TOÀN BỘ BATCH: nhiều chủ đề (như hàng đợi), nhiều cuốn, 15 tài khoản, lỗi ngẫu nhiên khắp nơi.

Code THẬT: pipeline.run (lượt lên ý, nghĩ trước, vẽ song song, vòng vét, báo cáo, chạy lại), run_ideation
(P1 -> P1b -> P2 song song, sửa JSON, gửi lại khi mất ngữ cảnh, chia tông giữ chỗ), generate_concept + run_jobs
(chia việc vẽ, QC loại -> vẽ lại, hết lượt -> nghỉ), bộ điều phối tài khoản (chat vs vẽ, trần Chrome, chừa chỗ chat).
Chỉ thay GIẢ: ChatGPT (trả lời đúng khuôn + lỗi ngẫu nhiên), Chrome (mở được/không), phóng to và dàn trang in.

Điều kiện phải giữ ở MỌI kịch bản:
- không lúc nào 2 việc (chat/vẽ) cùng dùng một tài khoản; không vượt trần Chrome;
- mọi luồng kết thúc (không treo), trả hết tài khoản;
- mỗi chủ đề ra đúng số cuốn yêu cầu (lỗi tạm được vòng vét / chờ hồi lượt cứu), không cuốn trùng thư mục;
- chạy lại sau khi tắt ngang chỉ làm phần thiếu; tông màu chia đều.
"""
import copy
import itertools
import json
import random
import re
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge import layout, pipeline
from calforge.ideation import catalog, tones
from calforge.imagegen import driver, generate
from calforge.imagegen.driver import QuotaExceeded, Refused, TempError
from calforge.llm import pool as poolmod
from calforge.llm.chatgpt_web import NoAccountLeft
from calforge.llm.pool import CHAT, IMAGE, AccountPool

from tests import fixtures

N_ACC = 15


class Tracker:
    def __init__(self, cap):
        self.cap, self.active, self.peak, self.violations = cap, set(), 0, []
        self.lock = threading.Lock()
        self.chat_calls = self.image_calls = 0

    @contextmanager
    def use(self, name, kind):
        with self.lock:
            if name in self.active:
                self.violations.append(f"{name} bị dùng chung")
            self.active.add(name)
            self.peak = max(self.peak, len(self.active))
            if len(self.active) > self.cap:
                self.violations.append(f"vượt trần {len(self.active)}>{self.cap}")
            if kind == CHAT:
                self.chat_calls += 1
            else:
                self.image_calls += 1
        try:
            yield
        finally:
            with self.lock:
                self.active.discard(name)


class World:
    """Trạng thái giả lập dùng chung: ngẫu nhiên có hạt giống, hạn mức từng tài khoản, tài khoản hỏng."""

    def __init__(self, seed, pool, *, fault=1.0, chat_budget=None, image_budget=None, broken=()):
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.pool = pool
        self.fault = fault
        self.tracker = Tracker(pool.cap)
        self.chat_budget = dict(chat_budget or {})
        self.image_budget = dict(image_budget or {})
        self.refill = {k: 10 ** 6 for k in pool.names}        # hết nghỉ thì hồi lượt
        self.broken = set(broken)
        self.titles = itertools.count(1)
        self.asked = {}                                       # nhãn câu hỏi gốc -> yêu cầu (số ý, danh sách id)

    def chance(self, p):
        with self.lock:
            return self.rng.random() < p * self.fault

    def spend(self, budget: dict, name: str, role: str) -> bool:
        """Trừ 1 lượt; False = hết lượt. Tài khoản đã nghỉ xong thì được hồi lượt."""
        with self.lock:
            left = budget.get(name, 10 ** 9)
            if left <= 0 and not self.pool._resting(name, role) and (name, role) in self.pool.rest_until:
                left = self.refill[name]
            budget[name] = left - 1
            return left > 0


# ------------------------------------------------------------------ ChatGPT giả (chat)
def p1_answer(world, prompt, n):
    angles = []
    for i in range(1, n + 1):
        a = copy.deepcopy(fixtures.ANGLE)
        a.update(id=f"a{i}", title=f"Idea {next(world.titles)}",
                 style_family=["styled_photography", "papercut_collage", "mid_century_retro"][i % 3])
        angles.append(a)
    return "```json\n" + json.dumps({"keyword": "x", "angles": angles}) + "\n```"


def p1b_answer(ids, n):
    data = {"decisions": [{"id": i, "keep": True, "duplicates": "", "reason": "ok", "new_direction": ""} for i in ids],
            "selected": ids[:n]}
    return "```json\n" + json.dumps(data) + "\n```"


def p2_answer(label, broken=False, prompt=""):
    c = fixtures.concept()
    anchor = re.search(r"near (#[0-9A-Fa-f]{6})", prompt)     # ChatGPT theo đúng tông máy giao
    if anchor:
        c["style"]["shared_base_color"] = {"name": "assigned", "hex": anchor.group(1)}
    c["title"] = f"Book {label.split('_')[2]}"
    c["fingerprint"] = {"promise": "p", "subject_world": "w", "months": [f"m{i}" for i in range(12)]}
    if broken:
        c["months"][11]["holiday_symbol"] = ""                # lỗi khách quan -> buộc sửa (P3)
    return "```json\n" + json.dumps(c) + "\n```"


class FakeSession:
    """Như _RotatingChat: mượn 1 tài khoản CHAT qua bộ điều phối, hết lượt thì nghỉ chat + đổi tài khoản."""

    def __init__(self, world):
        self.world, self.name = world, None

    def _get(self):
        pool = self.world.pool
        while self.name is None:
            for n in pool.names:
                if n in self.world.broken:
                    continue
                if pool.acquire(CHAT, only=n):
                    self.name = n
                    return
            usable = [n for n in pool.names if n not in self.world.broken]
            if all(pool._resting(n, CHAT) for n in usable):
                raise NoAccountLeft("hết lượt chat")
            pool.wait_change(0.05)

    def ask(self, prompt, label):
        w = self.world
        while True:
            self._get()
            with w.tracker.use(self.name, CHAT):
                time.sleep(w.rng.uniform(0.001, 0.004))
                ok = w.spend(w.chat_budget, self.name, CHAT)
            if not ok:
                w.pool.rest(self.name, CHAT, w.pool.rest_s, "limit")
                self.close()
                continue
            break
        base = label.split("_repair")[0].split("_resend")[0]
        with w.lock:                                          # câu nhắc sửa không nhắc lại số lượng: nhớ yêu cầu gốc
            if label.startswith("p1_angles") and base == label:
                w.asked[base] = int(re.search(r"Propose the (\d+)", prompt).group(1))
            if label.startswith("p1b_review") and base == label:
                run = re.search(r"run(\d+)", label).group(1)      # chỉ ứng viên của lượt này (danh mục có id cũ)
                w.asked[base] = (list(dict.fromkeys(re.findall(rf"\br{run}a\d+\b", prompt))),
                                 int(re.search(r"WE NEED: (\d+)", prompt).group(1)))
            if label.startswith("p2_concept") and base == label:
                w.asked["p2:" + base] = prompt                # câu sửa không có lại prompt gốc
            asked = w.asked.get(base)
        if label.startswith("p1_angles"):
            return p1_answer(w, prompt, asked) if not w.chance(.1) else "Sorry, something went wrong."
        if label.startswith("p1b_review"):
            return p1b_answer(*asked)
        if "_repair" in label and w.chance(.3):
            return "The original JSON is not available in this conversation. Please paste the original JSON."
        if label.startswith("p2_concept"):
            first = "_repair" not in label and "_resend" not in label
            if first and w.chance(.15):
                return "I'm not sure what you mean."          # không có JSON -> nhắc trả JSON
            return p2_answer(label, broken=first and w.chance(.3), prompt=w.asked.get("p2:" + base, prompt))
        return "```json\n{}\n```"

    def close(self):
        if self.name:
            self.world.pool.release(self.name)
            self.name = None


class FakeBackend:
    def __init__(self, world):
        self.world = world

    @contextmanager
    def session(self, workdir):
        with self.world.pool.reserve_chat(1):
            s = FakeSession(self.world)
            try:
                yield s
            finally:
                s.close()


# ------------------------------------------------------------------ Chrome + máy vẽ giả
def make_worker(world):
    class FakeImageWorker:
        def __init__(self, profile_dir, headless, timeout_s, settle_s=8.0):
            self.name = Path(profile_dir).name

        def run_job(self, page, job):
            with world.tracker.use(self.name, IMAGE):
                time.sleep(world.rng.uniform(0.001, 0.006))
                if not world.spend(world.image_budget, self.name, IMAGE):
                    raise QuotaExceeded("You've hit the image generation limit")
                if world.chance(.07):
                    raise TempError("ảnh không đạt: lịch sai: thiếu ngày 15")
                if world.chance(.02):
                    raise Refused("content policy")
                if world.chance(.02):
                    raise RuntimeError("Target page, context or browser has been closed")
                if world.chance(.03):                          # mạng chập / trang tự chuyển hướng lúc mở ChatGPT
                    raise driver.NavError("không mở được ChatGPT: chrome-error://chromewebdata/")
                out = job.out.with_suffix(".png")
                out.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (300, 200), (world.rng.randint(0, 255), 120, 90)).save(out)
                return out
    return FakeImageWorker


def make_open(world):
    @contextmanager
    def fake_open(profile):
        if profile in world.broken:
            raise RuntimeError("Target closed: profile chưa đăng nhập")
        yield object()
    return fake_open


class _NoUpscale:
    def __init__(self, *a, **k):
        self.done = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Sim:
    """Dựng thế giới giả + vá đúng các điểm chạm với ChatGPT/Chrome; code batch còn lại là THẬT."""

    def __init__(self, tc, seed, *, cap=N_ACC, **world_kw):
        self.tmp = tempfile.TemporaryDirectory()
        tc.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        pdir = root / "profiles"
        names = [f"acc{i}" for i in range(1, N_ACC + 1)]
        for n in names:
            (pdir / n).mkdir(parents=True)
        self.pool = AccountPool(pdir, names, cap=cap, launch_gap_s=0)
        self.pool.rest_s = 0.3
        self.world = World(seed, self.pool, **world_kw)
        self.cfg = {"projects_dir": str(root / "projects"), "profiles_dir": str(pdir), "year": 2027, "market": "US",
                    "angles_per_keyword": 1, "max_repairs": 2, "auto_pick": 1,
                    "imagegen": {"profiles": None, "headless": "hidden", "timeout_s": 5, "max_attempts": 3},
                    "llm": {"backend": "fake"}, "quota_wait_s": 0.3, "quota_max_wait_h": 0.02,
                    "book_workers": 3, "idea_lookahead": 3, "p2_parallel": 3, "batch_retry_wait_s": 0}
        self.finish_calls = {}
        self.mockup_results = {}
        self.finish_lock = threading.Lock()
        w = self.world

        def finish_book(cdir, cfg, on_event=print, **kw):
            with self.finish_lock:
                k = self.finish_calls[cdir.name] = self.finish_calls.get(cdir.name, 0) + 1
            if k == 1 and w.chance(.05):
                raise RuntimeError("render crashed")          # lỗi hậu kỳ lần đầu -> vòng vét cứu
            import json as _j
            from calforge import products as _p
            concept = _j.loads(layout.concept_file(cdir).read_text(encoding="utf-8"))
            if _p.ai_mockups(concept):                       # "AI gen mockup": code ghép 4 ảnh rồi AI dựng bối cảnh (THẬT)
                layout.listing(cdir).mkdir(parents=True, exist_ok=True)
                for name in ("01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads",
                             "05_wall_page_turn"):
                    f = layout.listing(cdir) / f"{name}.jpg"
                    if not f.exists():
                        Image.new("RGB", (1600, 1067), "gray").save(f)
                from calforge.imagegen.ai_mockups import ai_previews
                self.mockup_results[cdir.name] = ai_previews(cdir, cfg, on_event)
            return pipeline._status(cdir, stage="listing", ok=True, note="sim")

        patches = [
            mock.patch.object(poolmod, "get_pool", lambda cfg=None: self.pool),
            mock.patch.object(pipeline.config, "make_backend", lambda cfg: FakeBackend(w)),
            mock.patch.object(catalog, "family_quota", lambda *a, **k: None),
            mock.patch.object(driver, "_Worker", make_worker(w)),
            mock.patch.object(generate, "run_jobs", partial(driver.run_jobs, open_page=make_open(w))),
            mock.patch.object(driver, "run_jobs", partial(driver.run_jobs, open_page=make_open(w))),   # AI mockup
            mock.patch.object(pipeline, "_BackgroundUpscaler", _NoUpscale),
            mock.patch.object(pipeline, "upscale_concept", lambda *a, **k: []),
            mock.patch.object(pipeline, "finish_book", finish_book),
            mock.patch.object(pipeline, "_render_is_current", lambda *a, **k: True),
        ]
        for p in patches:
            p.start()
            tc.addCleanup(p.stop)

    def run(self, keyword, n, product="wall_grid", grid_mode=None, timeout=240, resume=False, mockup_mode=None):
        out = {}

        def go():
            out["rows"] = pipeline.run(keyword, self.cfg, auto_pick=n, printify=False, product=product,
                                       grid_mode=grid_mode, retry_wait_s=0, resume=resume,
                                       mockup_mode=mockup_mode, on_event=lambda *_: None)
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            raise AssertionError(f"batch '{keyword}' bị treo quá {timeout}s")
        if "rows" not in out:
            raise AssertionError(f"batch '{keyword}' dừng giữa chừng (không có báo cáo)")
        return out["rows"]

    def kdir(self, keyword, product="wall_grid"):
        from calforge import products
        return products.root(self.cfg["projects_dir"], product) / keyword

    def books(self, keyword, product="wall_grid"):
        return [b for b in sorted(self.kdir(keyword, product).iterdir()) if layout.is_book(b)]


def run_until_done(tc, sim, kw, n, prod="wall_grid", mode=None, max_reruns=3):
    """Như người dùng: chạy batch; cuốn nào hỏng (lỗi ngẫu nhiên dày) thì bấm "Làm nốt phần thiếu" (chạy lại)."""
    for attempt in range(1 + max_reruns):
        rows = sim.run(kw, n, prod, mode, resume=attempt > 0)   # lần sau = bấm "Làm nốt phần thiếu"
        for r in rows:                                        # cuốn hỏng luôn có lý do rõ ràng
            if not r["ok"]:
                tc.assertTrue(r.get("reason"), r)
        if sum(r["ok"] for r in rows) == n:
            return attempt
    tc.fail(f"{kw}: sau {max_reruns} lần làm nốt vẫn chưa đủ {n} cuốn: {rows}")


def assigned_tones(sim):
    import json as _j
    out = {}
    for b in layout.books(Path(sim.cfg["projects_dir"])):
        c = _j.loads(layout.concept_file(b).read_text(encoding="utf-8"))
        t = ((c.get("style") or {}).get("base_tone") or {}).get("assigned")
        if t:
            out[t] = out.get(t, 0) + 1
    return out


def check_invariants(tc, sim):
    tc.assertEqual(sim.world.tracker.violations, [])
    tc.assertEqual(sim.pool.use, {}, "chưa trả hết tài khoản")
    tc.assertEqual(sim.pool.chat_reserve, 0)


class BatchSimulationTest(unittest.TestCase):
    def test_queue_of_topics_many_books_15_accounts_with_random_faults(self):
        """Hàng đợi 4 chủ đề (cả 2 loại lịch, cả 2 chế độ trang lịch), 18 cuốn, 15 tài khoản, lỗi ngẫu nhiên."""
        for seed in range(3):
            with self.subTest(seed=seed):
                sim = Sim(self, seed,
                          chat_budget={"acc3": 2, "acc7": 5}, image_budget={"acc2": 4, "acc11": 10, "acc12": 0},
                          broken={"acc15"})
                topics = [("chickens", 6, "wall_grid", "ai_page"), ("bible", 4, "wall_premade", None),
                          ("cats", 5, "wall_grid", "background"), ("chickens", 3, "wall_grid", "ai_page")]
                made = {}
                for kw, n, prod, mode in topics:                  # hàng đợi: lần lượt từng batch
                    run_until_done(self, sim, kw, n, prod, mode)
                    made[(kw, prod)] = made.get((kw, prod), 0) + n
                for (kw, prod), n in made.items():                # đúng số cuốn, không thừa, không trùng thư mục
                    books = sim.books(kw, prod)
                    self.assertEqual(len(books), n)
                    self.assertEqual(len({layout.book_angle_id(b) for b in books}), n)
                check_invariants(self, sim)
                self.assertGreaterEqual(sim.world.tracker.peak, 8)   # thật sự chạy song song nhiều tài khoản
                # tông nền chia đều (cuốn Blank mới giao tông lúc viết concept, kể cả khi viết song song)
                counts = assigned_tones(sim)                      # 14 cuốn Blank / 6 tông: lệch nhau tối đa 1
                self.assertEqual(sum(counts.values()), 14)
                full = [counts.get(t, 0) for t in tones.BASE_TONES]
                self.assertLessEqual(max(full) - min(full), 1, counts)
                # cuốn Blank chọn "AI vẽ cả trang" có đủ 12 trang lịch AI, cuốn "AI vẽ nền" có 1 nền chung
                b = sim.books("cats")[0]
                self.assertIsNotNone(generate.job_done(b, "grid"))
                b = sim.books("chickens")[0]
                self.assertTrue(all(generate.job_done(b, f"g{m:02d}") for m in range(1, 13)))

    def test_every_account_runs_out_then_recovers(self):
        """Mọi tài khoản hết lượt chat + vẽ ngay từ đầu: batch tự chờ hồi lượt rồi làm xong, không hỏng cuốn."""
        sim = Sim(self, 11, chat_budget={f"acc{i}": 0 for i in range(1, 16)},
                  image_budget={f"acc{i}": 1 for i in range(1, 16)}, fault=0)
        rows = sim.run("dogs", 4)
        self.assertEqual(sum(r["ok"] for r in rows), 4)
        check_invariants(self, sim)

    def test_few_browsers_many_accounts_chat_never_starves(self):
        """Trần chỉ 3 Chrome, 15 tài khoản, việc vẽ dồn dập: lên ý tưởng vẫn đi được, không kẹt."""
        sim = Sim(self, 5, cap=3)
        run_until_done(self, sim, "owls", 7)
        check_invariants(self, sim)
        self.assertLessEqual(sim.world.tracker.peak, 3)

    def test_crash_mid_batch_then_rerun_makes_only_what_is_missing(self):
        """Tắt ngang giữa batch (lỗi chết ở lượt lên ý 2) rồi chạy lại: đủ số, không vẽ lại cuốn đã xong."""
        sim = Sim(self, 21, fault=0)
        real = pipeline.run_ideation if hasattr(pipeline, "run_ideation") else None
        from calforge.ideation import pipeline as ideation
        orig = ideation.run_ideation
        calls = {"n": 0}

        def dying(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt("tắt ngang")
            return orig(*a, **k)
        with mock.patch.object(ideation, "run_ideation", dying):
            with self.assertRaises(AssertionError):           # luồng batch chết (KeyboardInterrupt) -> không có rows
                sim.run("bees", 6, timeout=60)
        done_first = {b.name for b in sim.books("bees") if pipeline._finished_ok(b)}
        self.assertTrue(done_first)
        before = dict(sim.finish_calls)
        rows = sim.run("bees", 6)
        self.assertEqual(sum(r["ok"] for r in rows), 6)
        self.assertEqual(len(sim.books("bees")), 6)
        for name in done_first:                              # cuốn xong từ lần trước không làm lại
            self.assertEqual(sim.finish_calls[name], before[name])
        check_invariants(self, sim)
        del real


if __name__ == "__main__":
    unittest.main()


class MockupModeSimulationTest(unittest.TestCase):
    def test_mockup_choice_is_saved_only_for_ai_page_books(self):
        import json as _j
        sim = Sim(self, 3, fault=0)
        sim.run("pigs", 2, "wall_grid", "ai_page", mockup_mode="ai")
        sim.run("hens", 1, "wall_grid", "background", mockup_mode="ai")
        sim.run("owls", 1, "wall_premade", None, mockup_mode="ai")
        style = lambda b: _j.loads(layout.concept_file(b).read_text(encoding="utf-8"))["style"]
        self.assertTrue(all(style(b).get("mockup_mode") == "ai" for b in sim.books("pigs")))
        self.assertTrue(all("mockup_mode" not in style(b) for b in sim.books("hens")))
        self.assertTrue(all("mockup_mode" not in style(b) for b in sim.books("owls", "wall_premade")))


class AiMockupBatchSimulationTest(unittest.TestCase):
    def test_batch_with_ai_mockups_under_faults(self):
        """Batch "AI vẽ cả trang" + "AI gen mockup", 15 tài khoản, lỗi ngẫu nhiên (kể cả lỗi mở trang)."""
        import json as _j
        from calforge.imagegen import ai_mockups
        for seed in range(3):
            with self.subTest(seed=seed):
                sim = Sim(self, 300 + seed, image_budget={"acc4": 6}, broken={"acc15"})
                reruns = 0
                for _ in range(4):
                    rows = sim.run("koi", 4, "wall_grid", "ai_page", resume=reruns > 0, mockup_mode="ai")
                    if sum(r["ok"] for r in rows) == 4:
                        break
                    reruns += 1
                self.assertEqual(sum(r["ok"] for r in rows), 4)
                for b in sim.books("koi"):
                    names = sorted(p.stem for p in layout.listing(b).glob("*.jpg"))
                    self.assertEqual(names, ["01_front_cover_spiral", "02_open_spread_flat",
                                             "03_three_open_spreads", "05_wall_page_turn"])   # 4 ảnh, không có 04
                    res = sim.mockup_results.get(b.name) or {}
                    st = _j.loads(layout.tech(b, "mockup_ai.json").read_text(encoding="utf-8"))                         if layout.tech(b, "mockup_ai.json").exists() else {}
                    for n in res.get("ai", []):                                 # ảnh AI ghi nhận đúng
                        self.assertIn(n, st)
                    for n in res.get("kept_code", []):                          # hỏng: giữ mockup code, gen lại sau
                        self.assertIn(n, ai_mockups.pending(b))
                self.assertGreater(sum(len(r.get("ai", [])) for r in sim.mockup_results.values()), 0)
                check_invariants(self, sim)
