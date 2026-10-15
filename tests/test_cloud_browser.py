import unittest
from unittest import mock

from calforge.llm.chatgpt_web import _WebChat, SendFailed
from tests import test_chat_errors as chat_tests


class CloudBrowserTest(unittest.TestCase):
    def page(self, text="Use the cloud browser? ChatGPT will be able to access and interact with websites."):
        page = mock.Mock()
        page.get_by_role.return_value.count.return_value = 0
        dialogs = page.locator.return_value.filter.return_value
        dialogs.count.return_value = 1
        dialog = dialogs.nth.return_value
        dialog.is_visible.return_value = True
        dialog.inner_text.return_value = text
        buttons = dialog.get_by_role.return_value
        buttons.count.return_value = 1
        buttons.first.is_enabled.return_value = True
        return page, dialog, buttons

    def test_disabled_outside_link_fetch(self):
        page, _, buttons = self.page()
        self.assertFalse(_WebChat(page, 10)._continue_cloud_browser())
        page.locator.assert_not_called()
        buttons.first.click.assert_not_called()

    def test_scoped_dialog_english_and_vietnamese(self):
        for text in ("Use the cloud browser?", "Sử dụng trình duyệt đám mây?"):
            with self.subTest(text=text):
                page, dialog, buttons = self.page(text)
                self.assertTrue(_WebChat(page, 10, allow_cloud_browser=True)._continue_cloud_browser())
                topic = page.locator.return_value.filter.call_args.kwargs['has_text']
                self.assertRegex(text, topic)
                action = dialog.get_by_role.call_args.kwargs['name']
                for label in ("Continue", "Allow", "Tiếp tục", "Cho phép"):
                    self.assertRegex(label, action)
                for label in ("Continue with Google", "Buy now", "Cancel"):
                    self.assertNotRegex(label, action)
                buttons.first.click.assert_called_once()

    def test_no_dialog_no_click(self):
        page, _, buttons = self.page()
        page.locator.return_value.filter.return_value.count.return_value = 0
        self.assertFalse(_WebChat(page, 10, allow_cloud_browser=True)._continue_cloud_browser())
        buttons.first.click.assert_not_called()

    def test_later_book_and_account_still_handle_their_own_dialog(self):
        first, _, first_buttons = self.page()
        first.locator.return_value.filter.return_value.count.return_value = 0
        self.assertFalse(_WebChat(first, 10, allow_cloud_browser=True)._continue_cloud_browser())
        first_buttons.first.click.assert_not_called()
        for _ in range(3):
            later, _, later_buttons = self.page()
            self.assertTrue(_WebChat(later, 10, allow_cloud_browser=True)._continue_cloud_browser())
            later_buttons.first.click.assert_called_once()

    def test_real_inline_card_only_allows_current_chat(self):
        page, _, _ = self.page()
        inline = page.get_by_role.return_value
        inline.count.return_value = 1
        button = inline.nth.return_value
        button.is_visible.return_value = button.is_enabled.return_value = True
        button.evaluate.return_value = 'Allow ChatGPT to access www.etsy.com with the cloud browser?'
        self.assertTrue(_WebChat(page, 10, allow_cloud_browser=True)._continue_cloud_browser())
        action = page.get_by_role.call_args.kwargs['name']
        self.assertRegex('Allow for this chat ⏎', action)
        self.assertNotRegex('Allow all relevant sites', action)
        button.click.assert_called_once()

    def test_inline_button_without_browser_card_not_clicked(self):
        page, _, _ = self.page()
        page.locator.return_value.filter.return_value.count.return_value = 0
        inline = page.get_by_role.return_value
        inline.count.return_value = 1
        button = inline.nth.return_value
        button.is_visible.return_value = button.is_enabled.return_value = True
        button.evaluate.return_value = ''
        self.assertFalse(_WebChat(page, 10, allow_cloud_browser=True)._continue_cloud_browser())
        button.click.assert_not_called()

    def test_sensitive_or_ambiguous_dialog_not_accepted(self):
        for text, count in (("cloud browser payment", 1), ("cloud browser", 2), ("cloud browser", 0)):
            with self.subTest(text=text, count=count):
                page, _, buttons = self.page(text)
                buttons.count.return_value = count
                with self.assertRaises(SendFailed):
                    _WebChat(page, 10, allow_cloud_browser=True)._continue_cloud_browser()
                buttons.first.click.assert_not_called()

    def test_confirmation_continues_same_prompt_to_answer(self):
        harness = chat_tests.AskTest()
        with mock.patch.object(_WebChat, '_continue_cloud_browser', side_effect=[True] + [False] * 100) as confirm:
            result = harness.ask(lambda t: chat_tests.st(assistant=1, text="Artwork files ready") if t > 2 else chat_tests.st(),
                                 allow_cloud_browser=True)
        self.assertIn("Artwork files ready", result)
        self.assertGreater(confirm.call_count, 1)
        self.assertEqual(harness.page.typed, "PROMPT")

    def test_repeated_confirmation_is_bounded(self):
        harness = chat_tests.AskTest()
        with mock.patch.object(_WebChat, '_continue_cloud_browser', return_value=True) as confirm:
            with self.assertRaises(SendFailed):
                harness.ask(lambda t: chat_tests.st(), allow_cloud_browser=True, no_start_grace_s=3)
        self.assertEqual(confirm.call_count, 2)

    def test_progress_text_does_not_finish_file_request(self):
        harness = chat_tests.AskTest()
        result = harness.ask(lambda t: chat_tests.st(assistant=1, text='I am downloading the source images'),
                             response_ready=lambda: harness.clock.t >= 25)
        self.assertGreaterEqual(harness.clock.t, 25)
        self.assertIn('downloading', result)

    def test_complete_json_does_not_finish_file_request_while_busy(self):
        harness = chat_tests.AskTest()
        result = harness.ask(lambda t: chat_tests.st(assistant=1, text='files ready', codes=['{}'], busy=t < 25),
                             response_ready=lambda: True)
        self.assertGreaterEqual(harness.clock.t, 25)
        self.assertIn('files ready', result)

    def test_progress_without_artifacts_times_out(self):
        harness = chat_tests.AskTest()
        with self.assertRaises(TimeoutError):
            harness.ask(lambda t: chat_tests.st(assistant=1, text='Downloading images'),
                        response_ready=lambda: False, timeout_s=12)


if __name__ == '__main__':
    unittest.main()
