"""Đăng nhập hàng loạt: phân tích dòng dán vào, đặt tên profile, và mật khẩu không lọt ra ngoài."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge.llm import bulk_login


class BulkLoginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdir = Path(self.tmp.name) / "profiles"
        for n in ("acc1", "acc2"):
            (self.pdir / n).mkdir(parents=True)
        self.emails = Path(self.tmp.name) / "emails.json"
        self.emails.write_text(json.dumps({"acc2": "old@x.com"}), encoding="utf-8")
        self.seen = {}

        def fake_worker(jobs, pdir, parallel, stagger):
            self.seen["jobs"] = [(n, dict(c)) for n, c in jobs]
            for _, c in jobs:
                c.clear()
            bulk_login.BULK["active"] = False

        patches = [mock.patch.object(bulk_login, "get_profiles_dir", lambda cfg=None: self.pdir),
                   mock.patch.object(bulk_login, "EMAILS_FILE", self.emails),
                   mock.patch.object(bulk_login, "_emails", lambda: json.loads(self.emails.read_text())),
                   mock.patch.object(bulk_login, "_worker", fake_worker)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        bulk_login.BULK.update(active=False, items=[], boxes={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_names_and_no_password_leak(self):
        raw = ("new1@x.com | Secret#1 | JBSWY3DPEHPK3PXP\n"
               "OLD@x.com|Secret#2\n"
               "khong-hop-le\n"
               "new1@x.com|Secret#3\n"
               "bad2fa@x.com|Secret#4|???\n")
        res = bulk_login.start(raw)
        names = [(it["profile"], it["email"]) for it in res["items"]]
        self.assertEqual(names, [("acc3", "new1@x.com")])                 # chỉ tài khoản mới được đăng nhập
        self.assertEqual(res["skipped"], ["dòng 2: OLD@x.com đã có ở acc2",   # email đã có -> không đăng nhập lại
                                          "dòng 3: sai định dạng (email | mật khẩu | mã 2FA)",
                                          "dòng 4: trùng email với dòng 1",
                                          "dòng 5: mã 2FA sai"])
        self.assertEqual(self.seen["jobs"][0][1]["totp"], "JBSWY3DPEHPK3PXP")
        dump = json.dumps(res) + json.dumps(bulk_login.status()) + self.emails.read_text()
        for secret in ("Secret#1", "Secret#2", "JBSWY3DPEHPK3PXP"):
            self.assertNotIn(secret, dump)

    def test_only_existing_emails_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:
            bulk_login.start("old@x.com|p1\nkhông phải email|p2")
        self.assertIn("đã có ở acc2", str(ctx.exception))

    def test_rejects_empty_and_parallel_runs(self):
        with self.assertRaises(ValueError):
            bulk_login.start("   \n")
        bulk_login.BULK["active"] = True
        with self.assertRaises(RuntimeError):
            bulk_login.start("a@x.com|p")
        bulk_login.BULK["active"] = False


if __name__ == "__main__":
    unittest.main()
