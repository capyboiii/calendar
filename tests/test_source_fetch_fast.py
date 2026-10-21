import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from calforge.clone import fetch, session, store
from calforge.imagegen.driver import TempError
from calforge.ui.server import Task
from tests import test_chat_errors as chat_cases
from tests.test_clone_link import GOOD_ZIP, art


st = chat_cases.st


class SourceResponseTest(unittest.TestCase):
    ask = chat_cases.AskTest.ask
    def test_busy_work_over_five_minutes_is_not_treated_as_failure(self):
        answer=self.ask(lambda t:st(assistant=1,busy=t<420,text='Working...' if t<420 else 'Files ready'),
                        timeout_s=900,response_ready=lambda:self.clock.t>=420)
        self.assertIn('Files ready',answer)
        self.assertGreater(self.clock.t,420)

    def test_real_progress_is_allowed_until_file_ready(self):
        answer = self.ask(lambda t: st(assistant=1, busy=t < 210, text=f'Processing step {int(t//40)}'),
                          timeout_s=255, response_ready=lambda:self.clock.t >= 210)
        self.assertIn('Processing',answer)
        self.assertGreater(self.clock.t,200)

    def test_stopped_without_file_is_distinct_from_busy_work(self):
        with self.assertRaisesRegex(Exception, 'chưa gửi file/ảnh hợp lệ'):
            self.ask(lambda t:st(assistant=1,text='Done'), timeout_s=300,
                     response_ready=lambda:False)
        self.assertLess(self.clock.t,125)


class SourceFetchFastTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name)
        self.logs=[]
        self.b=types.SimpleNamespace(d=self.d,item={'source_url':'https://example.com/product'},
                                     status=lambda **kw:None,on_event=self.logs.append)

    def test_download_failure_requests_links_again_in_same_chat_and_deduplicates(self):
        calls=[]
        s=types.SimpleNamespace(page=object(),last_download_errors=[])
        def ask(prompt):
            calls.append(prompt)
            s.last_download_errors=['link 2 timeout'] if len(calls)==1 else []
            return 'files', [('art.png',art(1))] if len(calls)==1 else [('art.png',art(1)),('art2.png',art(2))]
        s.ask_files=ask
        with mock.patch.object(session,'ensure_work_mode',return_value='work'):
            fetch.fetch_work(self.b,s,'acc1')
        self.assertEqual(len(calls),2)
        self.assertIn('Không truy cập lại',calls[1])
        self.assertEqual(len(store.refs(self.d)),2)
        events=[json.loads(line) for line in (self.d/'source_fetch.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(events[0]['event'],'bắt đầu')
        self.assertEqual(events[-1]['refs_count'],2)
        self.assertFalse(hasattr(s,'source_deadline'))

    def test_failed_repair_never_publishes_partial_refs(self):
        s=types.SimpleNamespace(page=object(),last_download_errors=['timeout'],
                                ask_files=lambda _:('file',[('art.png',art(1))]))
        with mock.patch.object(session,'ensure_work_mode',return_value='work'):
            with self.assertRaisesRegex(TempError,'không tải đủ'):
                fetch.fetch_work(self.b,s,'acc1')
        self.assertFalse(store.read(self.d).get('refs_complete'))
        self.assertIn('lỗi phiên',(self.d/'source_fetch.jsonl').read_text(encoding='utf-8'))

    def test_file_wait_keeps_existing_timeout_and_no_five_minute_cutoff(self):
        s=session.Session.__new__(session.Session)
        current=[0];s.clock=lambda:current[0];s.page=mock.Mock()
        def answer(prompt,timeout_s,**kwargs):
            self.assertEqual(timeout_s,900)
            self.assertNotIn('response_idle_s',kwargs)
            self.assertNotIn('file_grace_s',kwargs)
            current[0]=930
            return 'ready'
        s.ask_text=answer;s.download_files=mock.Mock(return_value=[])
        s.ask_files('prompt')
        s.download_files.assert_called_once_with()

    def test_final_file_promise_is_returned_for_same_chat_repair(self):
        s=session.Session.__new__(session.Session)
        s.page=mock.Mock()
        s.page.evaluate.return_value={'text':'Tải 12 artwork PNG — file ZIP', 'busy':False}
        s.ask_text=mock.Mock(side_effect=TempError('đã dừng 120s nhưng chưa gửi file/ảnh hợp lệ'))
        s.download_files=mock.Mock(return_value=[])
        self.assertEqual(s.ask_files('prompt'), ('Tải 12 artwork PNG — file ZIP', []))
        s.page.evaluate.return_value={'text':'Working', 'busy':True}
        with self.assertRaises(TempError):s.ask_files('prompt')

    def test_network_download_has_bounded_body_transfer(self):
        s=session.Session.__new__(session.Session);s.clock=lambda:0
        page=mock.Mock();s.page=page;page.evaluate.return_value=1
        download=mock.Mock(url='https://files.example/one.zip',suggested_filename='one.zip')
        page.expect_download.return_value.__enter__=mock.Mock(return_value=types.SimpleNamespace(value=download))
        page.expect_download.return_value.__exit__=mock.Mock(return_value=False)
        response=page.request.get.return_value;response.ok=True;response.body.return_value=GOOD_ZIP
        self.assertEqual(s.download_files(timeout_s=30),[('one.zip',GOOD_ZIP)])
        download.cancel.assert_called_once();download.path.assert_not_called()
        self.assertLessEqual(page.request.get.call_args.kwargs['timeout'],30000)
        response.dispose.assert_called_once()

    def test_task_log_keeps_timestamped_history_beyond_memory_limit(self):
        path=self.d/'logs'/'task.log'
        task=Task('test',[],'source',log_file=path)
        for i in range(3002):task.append_log(f'event {i}')
        self.assertEqual(len(task.logs),3000)
        text=path.read_text(encoding='utf-8')
        self.assertIn('event 0\n',text);self.assertIn('event 3001\n',text)
        self.assertRegex(text,r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        self.assertEqual(task.to_dict()['log_file'],str(path))
