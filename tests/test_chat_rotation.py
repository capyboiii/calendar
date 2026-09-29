import unittest

from calforge.llm import chatgpt_web as cw


class _FakeChat:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def ask(self, prompt, label):
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return self.behaviour


class RotationTest(unittest.TestCase):
    def _rot(self, behaviours):
        rot = cw._RotatingChat.__new__(cw._RotatingChat)
        rot.order, rot.ctx, rot.chat, rot.profile = [f"acc{i}" for i in range(len(behaviours))], None, None, None
        opened = []

        def open_next():
            name = rot.order.pop(0)
            rot.profile, rot.chat = name, _FakeChat(behaviours[len(opened)])
            opened.append(name)

        rot._open_next = open_next
        rot.close = lambda: setattr(rot, "chat", None)
        return rot, opened

    def test_send_failure_moves_to_next_account(self):
        rot, opened = self._rot([cw.SendFailed("popup"), "answer"])
        self.assertEqual(rot.ask("p", "p1"), "answer")
        self.assertEqual(opened, ["acc0", "acc1"])

    def test_quota_still_moves_to_next_account(self):
        rot, opened = self._rot([cw.QuotaExceeded("limit"), "answer"])
        self.assertEqual(rot.ask("p", "p1"), "answer")
        self.assertEqual(opened, ["acc0", "acc1"])


if __name__ == "__main__":
    unittest.main()


class ImageRotationTest(unittest.TestCase):
    def test_each_book_starts_on_next_account(self):
        import tempfile
        from pathlib import Path
        from calforge.imagegen.generate import rotate_profiles
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "rot.json"
            firsts = [rotate_profiles(["acc2", "acc3", "acc4"], state)[0] for _ in range(4)]
        self.assertEqual(firsts, ["acc2", "acc3", "acc4", "acc2"])


class LimitMessagesTest(unittest.TestCase):
    def test_classify_known_messages(self):
        from calforge.llm.limits import classify
        quota = [
            "You've reached your limit for image generation. You can create more images in 2 hours.",
            "You've hit the Plus plan limit for GPT-4o. Responses will use another model until your limit resets.",
            "Too many requests in 1 hour. Try again later.",
            "You're sending messages too quickly. Please slow down.",
            "ChatGPT is at capacity right now",
            "We're experiencing high demand. Please try again in a few minutes.",
            "Unusual activity has been detected from your device. Try again later.",
            "Bạn đã đạt giới hạn tạo ảnh. Vui lòng quay lại sau.",
            "Quá nhiều yêu cầu. Hãy thử lại sau vài phút.",
            "Please try again in 15 minutes.",
        ]
        for m in quota:
            self.assertEqual(classify(m), "quota", m)
        self.assertEqual(classify("I can't create that image because it violates our content policy. "
                                  "You can try again in a new chat with a different request."), "refused")
        self.assertEqual(classify("Something went wrong while generating the response."), "error")
        self.assertEqual(classify("Get Plus - upgrade your plan for more features"), "")      # banner quảng cáo
        self.assertEqual(classify("Here is your calendar concept."), "")

    def test_rate_watch_only_core_requests(self):
        from calforge.llm.limits import RateWatch

        class Page:
            def on(self, _ev, fn):
                self.fn = fn

        class Resp:
            def __init__(self, url, status, body=""):
                self.url, self.status, self._b = url, status, body

            def text(self):
                return self._b
        import time as _t
        page = Page()
        w = RateWatch(page)
        t0 = _t.monotonic()
        page.fn(Resp("https://chatgpt.com/backend-api/lat/r", 503))              # request phụ: bỏ qua
        self.assertIsNone(w.recent(t0))

        class Get(Resp):
            request = type("R", (), {"method": "GET"})()
        # đọc danh sách chat / tải lại một chat bị 429 khi nhiều tab: KHÔNG phải hết lượt
        page.fn(Get("https://chatgpt.com/backend-api/conversations?offset=0&limit=28", 429))
        page.fn(Get("https://chatgpt.com/backend-api/conversation/6abb4487-5ef4-83ec", 429))
        page.fn(Resp("https://chatgpt.com/backend-api/conversations/6abb44ba-08f0", 429))
        self.assertIsNone(w.recent(t0))
        page.fn(Resp("https://chatgpt.com/backend-api/f/conversation", 429))
        self.assertIn("429", w.recent(t0))
        page2 = Page()
        w2 = RateWatch(page2)
        page2.fn(Resp("https://chatgpt.com/backend-api/conversation", 403, '{"detail":{"code":"rate_limit_exceeded"}}'))
        self.assertIsNotNone(w2.recent(t0))
