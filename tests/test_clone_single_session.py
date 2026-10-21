import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from calforge.clone import expand, fetch, store
from calforge.clone.run import Book, PoolWaiting, StageFailed
from calforge.imagegen.driver import TempError
from tests.test_clone_expand import image, URL

CHAT = 'https://chatgpt.com/c/12345678-abcd-4321-abcd-123456789012'


class Planner:
    def __init__(self, fail_month=None):
        self.opens, self.batches, self.attachments = [], [], []
        self.fail_month = fail_month
    def open(self, url=None):
        self.opens.append(url)
    def chat_url(self):
        return CHAT
    def attach(self, refs):
        self.attachments.append(list(refs))
    def ask_text(self, prompt):
        if 'Assignments:\n' not in prompt:
            return 'OK'
        jobs = json.JSONDecoder().raw_decode(prompt.split('Assignments:\n')[-1])[0]
        self.batches.append(jobs)
        if jobs[0]['artwork_index'] == self.fail_month:
            raise TempError('interrupted')
        return json.dumps({'artworks': [{'id': j['id'], 'prompt':
            'A complete original scene with its assigned reference, distinctive clothing and meaningful composition. '+j['id']}
            for j in jobs]})


class SingleSessionTest(unittest.TestCase):
    def setup_books(self, root, count=2):
        items = store.add_link_batch(root, URL, book_count=count)
        books = [Book({'projects_dir': root}, store.item_dir(root, i['id']), lambda _: None) for i in items]
        return books, store.source_dir(books[0].d)

    def test_sources_distributed_but_each_month_keeps_all_variants(self):
        from types import SimpleNamespace
        for k, n in ((1,1), (10,2), (11,3), (12,5)):
            with self.subTest(k=k,n=n), tempfile.TemporaryDirectory() as tmp:
                books,d=self.setup_books(tmp,n)
                sessions=[]
                barrier=threading.Barrier(3)
                def source(b,s,name):
                    fetch.save_refs(b.d, [(f'{i}.png',image(i)) for i in range(1,k+1)])
                def stage(accts,label,work,**kw):
                    planner=Planner()
                    if 'lập idea artwork' in label:
                        self.assertNotIn('only',kw)
                        month=int(label.rsplit(' ',1)[-1])
                        if month<=3:barrier.wait(5)
                        sessions.append(planner)
                    work(planner,threading.current_thread().name)
                with mock.patch('calforge.clone.run.run_stage',side_effect=stage),mock.patch.object(fetch,'fetch_work',side_effect=source):
                    expand.prepare(books[0],SimpleNamespace(names=['a','b','c']))
                    expand.prepare(books[-1],SimpleNamespace(names=['a','b','c']))
                self.assertEqual(len(sessions),12)
                self.assertEqual(sum(len(s.batches) for s in sessions),12)
                for planner in sessions:
                    batch=planner.batches[0]
                    month=batch[0]['artwork_index']
                    self.assertEqual({j['book_index'] for j in batch},set(range(1,n+1)))
                    self.assertEqual({j['artwork_index'] for j in batch},{month})
                    self.assertEqual({j['reference_index'] for j in batch},{1})
                    self.assertEqual(len(planner.attachments),1)
                    expected=store.refs(d)[month-1 if month<=k else 0]
                    self.assertEqual(planner.attachments[0],[expected])
                data=store.read(d)
                self.assertTrue(data['plan_ready'])
                self.assertEqual(len(data['completion_plan']),12*n)
                self.assertGreater(len({v['account'] for v in data['artwork_planners'].values()}),1)

    def test_resume_only_missing_months_and_can_change_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            books,d=self.setup_books(tmp)
            fetch.save_refs(d,[('1.png',image(1))])
            def first(accts,label,work,**kw):work(Planner(fail_month=4),'acc1')
            with mock.patch('calforge.clone.run.run_stage',side_effect=first),self.assertRaises(TempError):
                expand.prepare(books[0],None)
            data=store.read(d)
            self.assertFalse(data['plan_ready'])
            self.assertEqual(len(data['completion_plan']),22)
            before=data['completion_plan']
            second=Planner()
            def stage(accts,label,work,**kw):
                self.assertNotIn('only',kw)
                work(second,'acc2')
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage):
                expand.prepare(books[1],None)
            self.assertEqual([j[0]['artwork_index'] for j in second.batches],[4])
            self.assertTrue(store.read(d)['plan_ready'])
            for key,value in before.items():self.assertEqual(store.read(d)['completion_plan'][key],value)

    def test_old_group_owner_does_not_pin_remaining_artwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            books,d=self.setup_books(tmp)
            fetch.save_refs(d,[('1.png',image(1))])
            store.write(d,planner_account='acc1',planner_started=True,planner_chat='')
            def stage(accts,label,work,**kw):
                self.assertNotIn('only',kw)
                work(Planner(),'acc2')
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage):
                expand.prepare(books[0],None)
            self.assertTrue(store.read(d)['plan_ready'])

    def test_uncommitted_plan_cannot_generate(self):
        with tempfile.TemporaryDirectory() as tmp:
            books,d=self.setup_books(tmp)
            s=mock.Mock()
            with self.assertRaises(TempError):expand.generate(books[0],s,'acc3')
            with self.assertRaises(TempError):expand.generate_parallel(books[0],s)
            s.ask_images.assert_not_called()
            s.acquire.assert_not_called()

    def test_sibling_waits_while_group_plan_is_being_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            books,d=self.setup_books(tmp)
            entered,release=threading.Event(),threading.Event()
            errors=[]
            def prepare(b,accts,stop):
                entered.set()
                release.wait(3)
            def run():
                try:expand.prepare(books[0],None)
                except Exception as e:errors.append(e)
            with mock.patch.object(expand,'prepare_single_session',side_effect=prepare):
                thread=threading.Thread(target=run)
                thread.start()
                self.assertTrue(entered.wait(2))
                try:
                    with self.assertRaises(PoolWaiting):expand.prepare(books[1],None)
                finally:
                    release.set();thread.join(4)
            self.assertFalse(errors)

    def test_stage_retries_are_pinned_and_quota_does_not_switch_account(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from calforge.clone.run import run_stage
        from calforge.imagegen.driver import QuotaExceeded
        for quota in (False,True):
            with self.subTest(quota=quota):
                owner={'name':None}
                accts=SimpleNamespace(acquire=mock.Mock(return_value='acc1'),release=mock.Mock(),
                    on_event=lambda _:None,pool=mock.Mock(),pdir=Path('.'),open_page=lambda _:nullcontext(None))
                s=SimpleNamespace(open=lambda:None)
                calls=[]
                def work(s,name):
                    owner['name']=name
                    calls.append(name)
                    if len(calls)==1:
                        if quota:raise QuotaExceeded('quota')
                        raise TempError('transient')
                run_stage(accts,'planner',work,only=lambda:owner['name'],session_factory=lambda *_:s)
                self.assertEqual(calls,['acc1','acc1'])
                self.assertEqual(accts.acquire.call_args.kwargs['only'],'acc1')
                if quota:
                    accts.pool.rest.assert_called_once()
                self.assertEqual(accts.release.call_count,len(calls))

    def test_pinned_quota_releases_before_wait_and_honors_stop(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from calforge.clone.run import run_stage
        from calforge.imagegen.driver import QuotaExceeded
        stop=threading.Event()
        released=[]
        def acquire(*args,**kwargs):
            if released:
                self.assertEqual(kwargs['only'],'acc1')
                stop.set()
                raise StageFailed('người dùng dừng')
            return 'acc1'
        accts=SimpleNamespace(acquire=acquire,release=lambda n:released.append(n),
            on_event=lambda _:None,pool=mock.Mock(),pdir=Path('.'),open_page=lambda _:nullcontext(None))
        owner={'name':None}
        def work(s,name):
            owner['name']=name
            raise QuotaExceeded('quota')
        with self.assertRaisesRegex(StageFailed,'người dùng dừng'):
            run_stage(accts,'planner',work,only=lambda:owner['name'],stop=stop,
                      session_factory=lambda *_:SimpleNamespace(open=lambda:None))
        self.assertEqual(released,['acc1'])

    def test_repeated_pinned_quota_has_bounded_wait(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from calforge.clone.run import run_stage
        from calforge.imagegen.driver import QuotaExceeded
        accts=SimpleNamespace(acquire=mock.Mock(return_value='acc1'),release=mock.Mock(),
            max_wait_s=10,on_event=lambda _:None,pool=mock.Mock(),pdir=Path('.'),
            open_page=lambda _:nullcontext(None))
        def work(s,name):raise QuotaExceeded('quota')
        with mock.patch('calforge.clone.run.time.monotonic',side_effect=[0,11]):
            with self.assertRaisesRegex(StageFailed,'thời gian chờ tối đa'):
                run_stage(accts,'planner',work,only='acc1',
                          session_factory=lambda *_:SimpleNamespace(open=lambda:None))
        self.assertEqual(accts.release.call_count,2)

    def test_scheduler_treats_waiting_for_group_planner_as_normal_wait(self):
        from types import SimpleNamespace
        from calforge.clone.run import run_book
        with tempfile.TemporaryDirectory() as tmp:
            books,d=self.setup_books(tmp)
            accts=SimpleNamespace(_request=threading.local())
            with expand.group_lock(d):
                result=run_book({'projects_dir':tmp},books[1].d,accts,['acc1'],step='art',on_event=lambda _:None)
            self.assertEqual(result,{'next':'pool_wait'})
            data=store.read(books[1].d)
            self.assertEqual(data['status'],'running')
            self.assertEqual(data['art_state'],'queued')
            self.assertEqual(data['stage'],'chờ nguồn/kế hoạch artwork của nhóm')
            self.assertFalse(data.get('reason'))


if __name__=='__main__':unittest.main()
