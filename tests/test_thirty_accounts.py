"""GIẢ LẬP 30 TÀI KHOẢN: batch có hỏng / treo không khi tăng gấp đôi số tài khoản.

Dùng lại thế giới giả của test_batch_simulation (code batch, lên ý tưởng, chia việc vẽ, bộ điều phối tài khoản là
THẬT). Các cấu hình: trần Chrome 15 (mặc định), trần 30 (máy đủ RAM, tự nâng max_browsers), trần 5 (máy ít RAM),
1/3 tài khoản hỏng, mọi tài khoản hết lượt, mở Chrome có giãn cách thật, kèm AI gen mockup.
"""
import threading
import unittest
from unittest import mock

from calforge import cli, layout, pipeline  # noqa: F401 - cli đặt stdout UTF-8 như lúc chạy thật
from calforge.ideation import tones
from calforge.llm.pool import browser_cap

from tests import test_batch_simulation as tb

N = 30
ALL = [f"acc{i}" for i in range(1, N + 1)]


def sim30(tc, seed, **kw):
    p = mock.patch.object(tb, "N_ACC", N)
    p.start()
    tc.addCleanup(p.stop)
    sim = tb.Sim(tc, seed, **kw)
    tc.assertEqual(len(sim.pool.names), N)
    return sim


def used_accounts(sim):
    return {n for n, _ in getattr(sim.world.tracker, "seen", set())}


class ThirtyAccountsTest(unittest.TestCase):
    def setUp(self):
        self.before = threading.active_count()

    def finish(self, sim, cap):
        tb.check_invariants(self, sim)
        self.assertLessEqual(sim.world.tracker.peak, cap)
        self.assertLessEqual(threading.active_count(), self.before + 2, "còn luồng chưa kết thúc")

    def test_default_cap_15_queue_of_topics_with_faults(self):
        """30 tài khoản, trần 15 Chrome: hàng đợi 3 chủ đề, 16 cuốn, lỗi ngẫu nhiên, vài tài khoản hết lượt / hỏng."""
        for seed in range(2):
            with self.subTest(seed=seed):
                sim = sim30(self, 500 + seed, cap=15,
                            chat_budget={"acc3": 2, "acc17": 4, "acc28": 0},
                            image_budget={"acc2": 4, "acc11": 10, "acc22": 0, "acc30": 6},
                            broken={"acc15", "acc29"})
                for kw, n, prod, mode in [("chickens", 6, "wall_grid", "ai_page"), ("bible", 4, "wall_premade", None),
                                          ("cats", 6, "wall_grid", "background")]:
                    tb.run_until_done(self, sim, kw, n, prod, mode)
                    books = sim.books(kw, prod)
                    self.assertEqual(len(books), n)
                    self.assertEqual(len({layout.book_angle_id(b) for b in books}), n)
                self.finish(sim, 15)
                self.assertGreaterEqual(sim.world.tracker.peak, 10)       # thật sự chạy song song
                counts = tb.assigned_tones(sim)
                full = [counts.get(t, 0) for t in tones.BASE_TONES]
                self.assertLessEqual(max(full) - min(full), 1, counts)

    def test_cap_30_with_more_parallel_books(self):
        """Máy đủ RAM, nâng trần lên 30 Chrome + 6 cuốn vẽ cùng lúc: không chồng tài khoản, không treo."""
        sim = sim30(self, 520, cap=30, broken={"acc9"})
        sim.cfg.update(book_workers=6, idea_lookahead=6, p2_parallel=4)
        tb.run_until_done(self, sim, "foxes", 12, "wall_grid", "ai_page")
        self.assertEqual(len(sim.books("foxes")), 12)
        self.finish(sim, 30)
        self.assertGreaterEqual(sim.world.tracker.peak, 12)              # chạy song song nhiều tài khoản (đỉnh tuỳ nhịp máy)

    def test_low_ram_cap_5_chat_never_starves(self):
        sim = sim30(self, 530, cap=5)
        tb.run_until_done(self, sim, "owls", 6)
        self.finish(sim, 5)

    def test_one_third_of_accounts_broken(self):
        sim = sim30(self, 540, cap=15, broken={f"acc{i}" for i in range(1, 11)})
        tb.run_until_done(self, sim, "bears", 5, "wall_grid", "ai_page")
        self.assertEqual(len(sim.books("bears")), 5)
        self.finish(sim, 15)

    def test_all_30_out_of_quota_then_recover(self):
        sim = sim30(self, 550, cap=15, fault=0, chat_budget={n: 0 for n in ALL}, image_budget={n: 1 for n in ALL})
        rows = sim.run("dogs", 4)
        self.assertEqual(sum(r["ok"] for r in rows), 4)
        self.finish(sim, 15)

    def test_only_two_of_30_have_quota(self):
        """28 tài khoản hết lượt vẽ hẳn (không hồi): 2 tài khoản còn lại vẫn gánh xong batch."""
        dead = {n: 0 for n in ALL[2:]}
        sim = sim30(self, 560, cap=15, fault=0, image_budget=dead)
        sim.world.refill.update({n: 0 for n in dead})
        rows = sim.run("hens", 3, "wall_grid", "background")
        self.assertEqual(sum(r["ok"] for r in rows), 3)
        self.finish(sim, 15)

    def test_real_launch_gap_does_not_deadlock(self):
        """Mở Chrome có giãn cách thật (rút ngắn còn 0.05s) với 30 tài khoản tranh nhau: vẫn xong, không kẹt cổng."""
        sim = sim30(self, 570, cap=15, fault=0.5)
        sim.pool.launch_gap_s = 0.05
        tb.run_until_done(self, sim, "wolves", 5, "wall_grid", "ai_page")
        self.finish(sim, 15)

    def test_ai_mockups_with_30_accounts(self):
        sim = sim30(self, 580, cap=15, image_budget={"acc4": 6}, broken={"acc30"})
        reruns = 0
        for _ in range(4):
            rows = sim.run("koi", 4, "wall_grid", "ai_page", resume=reruns > 0, mockup_mode="ai")
            if sum(r["ok"] for r in rows) == 4:
                break
            reruns += 1
        self.assertEqual(sum(r["ok"] for r in rows), 4)
        for b in sim.books("koi"):
            self.assertEqual(sorted(p.stem for p in layout.listing(b).glob("*.jpg")),
                             ["01_front_cover_spiral", "02_open_spread_flat", "03_three_open_spreads",
                              "04_two_wall_spreads", "06_three_books", "07_three_open_spreads_fall", "08_wall_and_back"])
            self.assertTrue(pipeline._finished_ok(b))
        self.finish(sim, 15)


class CapTest(unittest.TestCase):
    def test_cap_follows_config_and_ram_not_account_count(self):
        self.assertEqual(browser_cap(15, free_gb=64), 15)      # 30 tài khoản vẫn tối đa 15 Chrome nếu không đổi cấu hình
        self.assertEqual(browser_cap(30, free_gb=64), 30)      # đổi max_browsers = 30 và đủ RAM
        self.assertEqual(browser_cap(30, free_gb=16), 14)      # RAM 16 GB trống: ~14 Chrome dù có 30 tài khoản
        self.assertEqual(browser_cap(30, free_gb=0.5), 1)


if __name__ == "__main__":
    unittest.main()
