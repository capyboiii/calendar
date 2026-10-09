"""Gói ChatGPT (Free/Plus) + ngày hết hạn của từng tài khoản: đọc, lưu, hiển thị, kiểm tra hàng loạt."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from calforge.llm import plan

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def raw(plan_type, active, expires, structure="personal"):
    item = {"structure": structure, "plan": plan_type, "active": active, "expires": expires}
    return {"logged_in": True, "status": 200, "items": [item, dict(item)]}


class ParseTest(unittest.TestCase):
    def test_plus_free_and_expired_plus(self):
        self.assertEqual(plan.parse(raw("plus", True, "2026-11-04T16:35:16+00:00")),
                         {"plan": "plus", "label": "Plus", "active": True, "expires": "2026-11-04T16:35:16+00:00"})
        self.assertEqual(plan.parse(raw("free", False, None))["label"], "Free")
        lapsed = plan.parse(raw("free", False, "2026-10-05T15:12:16+00:00"))   # Plus hết hạn, rớt về Free
        self.assertEqual((lapsed["plan"], lapsed["expires"][:10]), ("free", "2026-10-05"))
        self.assertEqual(plan.parse(raw("pro", True, None))["label"], "Pro")

    def test_personal_account_preferred_over_workspace(self):
        r = {"logged_in": True, "items": [{"structure": "workspace", "plan": "team", "active": True},
                                          {"structure": "personal", "plan": "plus", "active": True}]}
        self.assertEqual(plan.parse(r)["plan"], "plus")

    def test_unreadable_means_unknown_not_a_guess(self):
        for r in (None, {}, {"logged_in": False}, {"logged_in": True, "status": 403},
                  {"logged_in": True, "items": []}, {"error": "TypeError"}, {"logged_in": True, "items": [{}]}, "x"):
            self.assertIsNone(plan.parse(r), r)

    def test_page_errors_never_raise(self):
        page = mock.Mock(evaluate=mock.Mock(side_effect=RuntimeError("Target closed")))
        self.assertIsNone(plan.read_from_page(page))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(plan.record(page, Path(tmp)))
            self.assertFalse((Path(tmp) / plan.PLAN_FILE).exists())


class StoreTest(unittest.TestCase):
    def test_save_read_days_left_and_expired(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertIsNone(plan.read(d))
            page = mock.Mock(evaluate=mock.Mock(return_value=raw("plus", True, "2026-10-18T18:07:18+00:00")))
            plan.record(page, d)
            info = plan.read(d, NOW)
            self.assertEqual((info["label"], info["days_left"], info["expires_date"], info["expired"]),
                             ("Plus", 12, "2026-10-18", False))
            self.assertIn("checked_at", info)
            self.assertNotIn("accessToken", (d / plan.PLAN_FILE).read_text(encoding="utf-8"))
            later = datetime(2026, 10, 20, tzinfo=timezone.utc)                 # quá hạn mà chưa kiểm tra lại
            self.assertTrue(plan.read(d, later)["expired"])
            page.evaluate.return_value = raw("free", False, "2026-10-18T18:07:18+00:00")
            plan.record(page, d)
            self.assertFalse(plan.read(d, later)["expired"])                    # đã thấy rớt về Free
            page.evaluate.return_value = {"error": "x"}                          # lần sau đọc hỏng: giữ dấu cũ
            plan.record(page, d)
            self.assertEqual(plan.read(d)["plan"], "free")
            (d / plan.PLAN_FILE).write_text("{hỏng", encoding="utf-8")
            self.assertIsNone(plan.read(d))

    def test_list_accounts_has_plan(self):
        from calforge.llm import accounts
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"profiles_dir": str(Path(tmp) / "p"), "projects_dir": tmp}
            for n in ("acc1", "acc2"):
                (Path(tmp) / "p" / n).mkdir(parents=True)
            plan.save(Path(tmp) / "p" / "acc1", {"plan": "plus", "label": "Plus", "active": True,
                                                 "expires": "2030-01-01T00:00:00+00:00"})
            got = {a["name"]: a["plan"] for a in accounts.list_accounts(cfg)}
            self.assertEqual(got["acc1"]["label"], "Plus")
            self.assertIsNone(got["acc2"])


class CheckAllTest(unittest.TestCase):
    def test_checks_logged_in_accounts_and_skips_busy_dead_and_logged_out(self):
        from calforge.llm import accounts, pool
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / "p"
            for n in ("acc1", "acc2", "acc3", "acc4", "acc5"):
                (pdir / n).mkdir(parents=True)
            cfg = {"profiles_dir": str(pdir), "projects_dir": tmp}
            seen = []

            def one(d):
                seen.append(d.name)
                if d.name == "acc5":
                    raise RuntimeError("chrome hỏng")
                return {"plan": "plus"}
            with mock.patch.object(accounts, "is_profile_locked", lambda d: d.name == "acc2"), \
                    mock.patch.object(accounts, "has_chatgpt_session", lambda d: d.name != "acc3"), \
                    mock.patch.object(pool, "read_dead", lambda d: {"kind": "banned"} if d.name == "acc4" else None):
                st = plan.check_all(cfg, check_one=one)
            self.assertEqual(seen, ["acc1", "acc5"])
            self.assertFalse(st["active"])
            self.assertEqual((st["done"], st["total"]), (5, 5))
            self.assertEqual(st["skipped"], ["acc2: đang mở", "acc3: chưa đăng nhập", "acc4: đã chết",
                                             "acc5: không mở được Chrome"])

    def test_only_one_check_at_a_time(self):
        with mock.patch.object(plan.threading, "Thread") as t:
            plan.CHECK["active"] = False
            self.assertTrue(plan.start_check({}))
            self.assertFalse(plan.start_check({}))
            t.assert_called_once()
        plan.CHECK["active"] = False


class DriverRecordsPlanTest(unittest.TestCase):
    def test_worker_reads_plan_once_per_chrome(self):
        from calforge.imagegen import driver
        with tempfile.TemporaryDirectory() as tmp:
            w = driver._Worker(Path(tmp), "hidden", 60)
            calls = []
            with mock.patch.object(driver, "open_home"), mock.patch.object(w, "_find"), \
                    mock.patch.object(w, "_attach"), mock.patch.object(w, "_send", side_effect=RuntimeError("stop")), \
                    mock.patch.object(plan, "record", lambda page, d: calls.append(d)):
                page = mock.Mock()
                for _ in range(3):
                    with self.assertRaises(RuntimeError):
                        w.run_job(page, mock.Mock(attach=[], prompt="p"))
            self.assertEqual(calls, [Path(tmp)])


if __name__ == "__main__":
    unittest.main()


class K12WorkspaceTest(unittest.TestCase):
    """Tài khoản K12 (có nút Trò chuyện / Công việc): API trả workspace plan "k12", active=false, không hạn."""
    RAW = {"logged_in": True, "status": 200, "items": [
        {"structure": "workspace", "plan": "k12", "active": False, "expires": None},
        {"structure": "personal", "plan": "free", "active": False, "expires": None}]}

    def test_k12_workspace_counts_as_paid(self):
        info = plan.parse(self.RAW)
        self.assertEqual((info["plan"], info["label"], info["active"]), ("k12", "K12", True))
        self.assertTrue(plan.is_paid(info))

    def test_personal_free_stays_free(self):
        info = plan.parse({"logged_in": True, "items": [self.RAW["items"][1]]})
        self.assertEqual(info["plan"], "free")
        self.assertFalse(plan.is_paid(info))

    def test_paid_kinds(self):
        for p in ("plus", "pro", "edu", "team", "enterprise", "k12"):
            self.assertTrue(plan.is_paid({"plan": p, "active": True}), p)
        for p in ("free", "go", ""):
            self.assertFalse(plan.is_paid({"plan": p, "active": True}), p)
        self.assertFalse(plan.is_paid({"plan": "plus", "active": True, "expired": True}))
