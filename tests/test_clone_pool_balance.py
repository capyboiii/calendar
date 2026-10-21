import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from calforge.clone import expand, session, store
from calforge.clone.run import Accounts, Book, PoolWaiting
from calforge.llm.pool import AccountPool, CHAT
from tests.test_clone_expand import image, URL


class CloneBalanceTest(unittest.TestCase):
    def test_yielded_branch_resumes_before_slow_sibling_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.books(tmp)[0]
            pool = mock.Mock()
            pool.image_capacity.return_value = 4
            accts = SimpleNamespace(names=list(range(4)), _request=threading.local(), pool=pool)
            resumed = threading.Event()
            attempts = [0]
            def stage(accts, label, work, **kw):
                work(SimpleNamespace(), 'acc1')
            def draw(book, s, name, *, months, yield_check=None):
                if months[0] == 1:
                    attempts[0] += 1
                    if attempts[0] == 1:
                        raise PoolWaiting('yield to earlier idea job')
                    resumed.set()
                else:
                    self.assertTrue(resumed.wait(3), 'idle branch waited for the slow sibling')
                for month in months:
                    session.save(image(month), book.raw(f'm{month:02d}'))
            with mock.patch('calforge.clone.run.run_stage', side_effect=stage), \
                    mock.patch.object(expand, 'generate', side_effect=draw):
                expand.generate_parallel(b, accts)
            self.assertGreaterEqual(attempts[0], 2)
            self.assertFalse(b.missing('m'))

    def books(self, root):
        rows=store.add_link_batch(root,URL,book_count=2)
        result=[Book({'projects_dir':root},store.item_dir(root,r['id']),lambda _:None) for r in rows]
        store.write(store.source_dir(result[0].d),planning_mode='legacy')
        for b in result:
            store.write(b.d,status='running')  # admitted books, not untouched future queue entries
        return result

    def test_future_queue_groups_do_not_reduce_current_clone_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            books = self.books(tmp)
            for _ in range(6):
                store.add_link_batch(tmp, URL, book_count=5)
            pool = mock.Mock()
            pool.image_capacity.return_value = 40
            accts = SimpleNamespace(names=list(range(40)), _request=threading.local(), pool=pool,
                                    clone_item_ids={b.d.name for b in books})
            with mock.patch('calforge.clone.run.run_stage', side_effect=PoolWaiting('busy')):
                with self.assertRaises(PoolWaiting):
                    expand.generate_parallel(books[0], accts)
            self.assertEqual(store.read(books[0].d)['pool_art_workers'], 12)

    def test_share_ram_slots_then_expand_for_remaining_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            books=self.books(tmp)
            pool=mock.Mock();pool.image_capacity.return_value=4
            accts=SimpleNamespace(names=list(range(40)),_request=threading.local(),pool=pool)
            chunks=[]
            def stage(accts,label,work,**kw):
                chunks.append(label)
                raise PoolWaiting('busy')
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage):
                for b in books:
                    with self.assertRaises(PoolWaiting):expand.generate_parallel(b,accts)
                    self.assertEqual(store.read(b.d)['pool_art_workers'],2)
                for m in range(1,13):session.save(image(m),books[0].raw(f'm{m:02d}'))
                accts._clone_art_share=(0,0)
                with self.assertRaises(PoolWaiting):expand.generate_parallel(books[1],accts)
                self.assertEqual(store.read(books[1].d)['pool_art_workers'],4)

    def test_wait_tokens_survive_retry_and_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=self.books(tmp)[0]
            pool=mock.Mock();pool.image_capacity.return_value=4
            accts=SimpleNamespace(names=list(range(40)),_request=threading.local(),pool=pool)
            tokens=[]
            def stage(accts,label,work,**kw):
                tokens.append(accts._request.ident)
                raise PoolWaiting('busy')
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage):
                with self.assertRaises(PoolWaiting):expand.generate_parallel(b,accts)
                first=set(tokens);tokens.clear()
                session.save(image(1),b.raw('m01'))
                with self.assertRaises(PoolWaiting):expand.generate_parallel(b,accts)
                self.assertEqual(set(tokens),first)
            pool.cancel_wait.assert_not_called()
            expand.clear_art_waits(b.d,accts)
            self.assertEqual({c.args[1] for c in pool.cancel_wait.call_args_list},first)

    def test_stop_before_work_cleans_waiters_without_borrowing_an_account(self):
        from calforge.clone.run import StageFailed
        with tempfile.TemporaryDirectory() as tmp:
            b=self.books(tmp)[0]
            pool=mock.Mock();pool.image_capacity.return_value=4
            accts=SimpleNamespace(names=list(range(40)),_request=threading.local(),pool=pool,
                                  acquire=mock.Mock(),on_event=lambda _:None)
            stop=threading.Event();stop.set()
            with self.assertRaises(StageFailed):expand.generate_parallel(b,accts,stop)
            accts.acquire.assert_not_called()
            tokens={c.args[1] for c in pool.cancel_wait.call_args_list}
            self.assertTrue(any(':art:worker:0' in t for t in tokens))

    def test_mixed_idea_clone_forty_accounts_four_chrome_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            books=self.books(tmp)
            profiles=Path(tmp)/'profiles'
            names=[f'acc{i}' for i in range(1,41)]
            for name in names:(profiles/name).mkdir(parents=True)
            pool=AccountPool(profiles,names,cap=4,leases=True)
            pool.chat_reserve=1
            accts=Accounts({'projects_dir':tmp,'profiles_dir':str(profiles)},names,on_event=lambda _:None,pool=pool)
            guard=threading.Lock()
            owners=set();peak=0;completed={1:0,2:0};first_start={};idea_count=0
            deadline=time.monotonic()+40
            def enter(name):
                nonlocal peak
                with guard:
                    self.assertNotIn(name,owners)
                    owners.add(name);peak=max(peak,len(owners))
                    self.assertLessEqual(len(owners),4)
            def leave(name):
                with guard:owners.remove(name)
            def stage(accts,label,work,**kw):
                name=accts.acquire()
                enter(name)
                try:work(SimpleNamespace(),name)
                finally:leave(name);accts.release(name)
            def draw(b,s,name,*,months,yield_check=None):
                index=b.item['book_index']
                with guard:first_start.setdefault(index,dict(completed))
                for m in months:
                    if b.done(f'm{m:02d}'):continue
                    time.sleep(.015)
                    session.save(image(m),b.raw(f'm{m:02d}'))
                    with guard:completed[index]+=1
                    if yield_check and m!=months[-1] and yield_check():raise PoolWaiting('yield')
            def clone(b):
                while b.missing('m'):
                    self.assertLess(time.monotonic(),deadline)
                    try:expand.generate_parallel(b,accts)
                    except PoolWaiting:time.sleep(.005)
                expand.clear_art_waits(b.d,accts)
            def idea():
                nonlocal idea_count
                for turn in range(40):
                    name=None
                    while name is None:
                        self.assertLess(time.monotonic(),deadline)
                        name=pool.acquire(CHAT,request_id=f'idea:{turn}')
                        if name is None:time.sleep(.003)
                    enter(name)
                    try:time.sleep(.01);idea_count+=1
                    finally:leave(name);pool.release(name)
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage),mock.patch.object(expand,'generate',side_effect=draw):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures=[executor.submit(clone,b) for b in books]+[executor.submit(idea)]
                    for f in futures:f.result(timeout=45)
            self.assertEqual(completed,{1:12,2:12})
            self.assertEqual(idea_count,40)
            self.assertLess(first_start[2][1],12)
            self.assertLess(first_start[1][2],12)
            self.assertGreaterEqual(peak,3)
            self.assertEqual(owners,set())
            self.assertEqual(pool.use,{})
            from calforge.llm.pool_waiters import FILE
            import json
            self.assertEqual(json.loads((profiles/FILE).read_text())['requests'],[])
