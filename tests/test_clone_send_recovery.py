import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from calforge.clone.run import Accounts, run_stage
from calforge.imagegen.driver import TempError
from calforge.llm.pool import AccountPool


class SendRecoveryTest(unittest.TestCase):
    def test_unacknowledged_send_re_resolves_button_and_acknowledged_send_is_not_repeated(self):
        from calforge.llm import chatgpt_web as cw
        from tests.test_chat_errors import Clock, Page, st
        for acknowledgments, clicks in (([True], 1), ([False, True], 2)):
            with self.subTest(acknowledgments=acknowledgments):
                clock = Clock()
                page = Page(clock)
                chat = cw._WebChat(page, 10, settle_s=0)
                before = [True]
                def state():
                    if before:
                        before.pop()
                        return st(user=0)
                    return st(user=1, assistant=1, text='OK')
                with mock.patch.object(cw.time, 'monotonic', clock.monotonic), \
                        mock.patch('calforge.llm.pool.human_pause'), \
                        mock.patch.object(chat, '_state', side_effect=state), \
                        mock.patch.object(chat, '_wait_sent', side_effect=acknowledgments), \
                        mock.patch.object(chat, '_submit') as submit:
                    self.assertEqual(chat.ask('prompt', 'clone_meta'), 'OK')
                self.assertEqual(submit.call_count, clicks)

    def test_unsent_source_prompt_moves_to_another_account_and_releases_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = ['acc1', 'acc2', 'acc3']
            pool = AccountPool(Path(tmp), names, cap=3)
            accts = Accounts({'profiles_dir': tmp, 'projects_dir': tmp}, names, pool=pool,
                             on_event=lambda _: None, open_page=lambda _: nullcontext(None))
            used = []
            def work(s, name):
                used.append(name)
                if len(used) < 3:
                    raise TempError('[clone_meta] Không gửi được tin nhắn')
            name = run_stage(accts, 'lấy ảnh nguồn dùng chung', work,
                             session_factory=lambda *_: SimpleNamespace(open=lambda: None))
            self.assertEqual(name, 'acc3')
            self.assertEqual(used, names)
            self.assertEqual(pool.use, {})

    def test_pinned_legacy_planner_does_not_switch_chat_account_on_send_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = AccountPool(Path(tmp), ['acc1', 'acc2'], cap=2)
            accts = Accounts({'profiles_dir': tmp, 'projects_dir': tmp}, ['acc1', 'acc2'], pool=pool,
                             on_event=lambda _: None, open_page=lambda _: nullcontext(None))
            used = []
            def work(s, name):
                used.append(name)
                if len(used) == 1:
                    raise TempError('[clone_meta] Không gửi được tin nhắn')
            run_stage(accts, 'planner', work, only='acc1',
                      session_factory=lambda *_: SimpleNamespace(open=lambda: None))
            self.assertEqual(used, ['acc1', 'acc1'])
            self.assertEqual(pool.use, {})
