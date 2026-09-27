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
