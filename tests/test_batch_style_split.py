"""Chọn "Ngẫu nhiên": phong cách chia đều TRONG BATCH đang chạy (không ép 1 phong cách cho cả batch, không xét
chủ đề / kho khác). Batch lên ý theo lượt 3 cuốn: mỗi lượt lấy phong cách batch đang ít cuốn nhất."""
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from calforge import layout, pipeline
from calforge.ideation import catalog

IDS = [f["id"] for f in catalog.families()]


class BatchStyleSplitTest(unittest.TestCase):
    def run_batch(self, total, round_size=3):
        """Mô phỏng một batch: mỗi lượt lấy quota, 'làm' đúng các cuốn theo quota (ghi concept.json)."""
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "cat"
            batch = {"started": "2026-10-14 10:00:00", "concepts": []}
            made = []
            while len(made) < total:
                n = min(round_size, total - len(made))
                quota = pipeline._batch_family_quota(kdir, batch, n)
                self.assertEqual(sum(quota.values()), n)
                for fam, k in quota.items():
                    for _ in range(k):
                        rel = f"b{len(made)}"
                        layout.ensure_system(kdir / rel)
                        layout.concept_file(kdir / rel).write_text(json.dumps({"style": {"family": fam}}),
                                                                   encoding="utf-8")
                        batch["concepts"].append(rel)
                        made.append(fam)
            return Counter(made)

    def test_five_books_five_different_styles(self):
        c = self.run_batch(5)
        self.assertEqual(sorted(c), sorted(IDS))
        self.assertTrue(all(v == 1 for v in c.values()))

    def test_six_books_spread_evenly(self):
        c = self.run_batch(6)
        self.assertEqual(len(c), 5)                                   # đủ 5 phong cách
        self.assertEqual(max(c.values()) - min(c.values()), 1)        # chênh nhau nhiều nhất 1 cuốn

    def test_large_batch_even(self):
        for total in (10, 13):
            c = self.run_batch(total)
            self.assertLessEqual(max(c.values()) - min(c.values()), 1, (total, c))

    def test_failed_idea_is_made_up_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "cat"
            batch = {"started": "x", "concepts": []}
            first = pipeline._batch_family_quota(kdir, batch, 3)
            # lượt 1 chỉ ra 2 cuốn (1 ý hỏng): phong cách hỏng chưa có cuốn -> lượt sau vẫn được ưu tiên
            done = list(first)[:2]
            for i, fam in enumerate(done):
                layout.ensure_system(kdir / f"b{i}")
                layout.concept_file(kdir / f"b{i}").write_text(json.dumps({"style": {"family": fam}}), encoding="utf-8")
                batch["concepts"].append(f"b{i}")
            nxt = pipeline._batch_family_quota(kdir, batch, 3)
            self.assertFalse(set(nxt) & set(done))                    # không lặp phong cách đã có khi còn phong cách trống

    def test_same_batch_same_tie_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "cat"
            b = {"started": "2026-10-14 10:00:00", "concepts": []}
            self.assertEqual(pipeline._batch_family_quota(kdir, b, 3), pipeline._batch_family_quota(kdir, b, 3))


if __name__ == "__main__":
    unittest.main()
