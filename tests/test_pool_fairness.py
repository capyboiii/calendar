import json
import itertools
import multiprocessing as mp
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge.llm.pool import AccountPool, IMAGE
from calforge.llm import pool_waiters as waits
from calforge.clone import run, store
from tests.test_clone import accts, new_item


def contender(root, urgent, ready, go, output):
    pool = AccountPool(Path(root), ['acc1'], cap=1, leases=True)
    try:
        deadline=time.monotonic()+10
        while True:
            assert pool.acquire(IMAGE, priority=urgent) is None
            try:
                if any(r['pid']==os.getpid() for r in json.loads((Path(root)/waits.FILE).read_text())['requests']):break
            except (OSError,ValueError):pass
            if time.monotonic()>deadline:raise RuntimeError('registration timeout')
            time.sleep(.02)
        ready.set()
        if not go.wait(10): raise RuntimeError('start timeout')
        if urgent: time.sleep(.15)  # idea hits acquire first, must still respect the reserved turn
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            name = pool.acquire(IMAGE, priority=urgent)
            if name:
                output.put('clone' if urgent else 'idea')
                time.sleep(.1)
                pool.release(name)
                return
            time.sleep(.02)
        output.put('timeout')
    finally:
        pool.cancel_wait(IMAGE)


class FairPoolTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'acc1').mkdir()

    def pool(self):
        p=AccountPool(self.root, ['acc1'], cap=1, leases=True)
        self.addCleanup(p.release,'acc1')
        return p

    def test_real_processes_idea_cannot_steal_clone_turn(self):
        owner = self.pool()
        self.assertEqual(owner.acquire(IMAGE), 'acc1')
        ctx = mp.get_context('spawn'); output=ctx.Queue(); go=ctx.Event()
        ready=[ctx.Event(),ctx.Event()]
        children=[ctx.Process(target=contender,args=(str(self.root),urgent,ready[i],go,output)) for i,urgent in enumerate((False,True))]
        try:
            for p in children:p.start()
            for event in ready:self.assertTrue(event.wait(10))
            owner.release('acc1');go.set()
            self.assertEqual([output.get(timeout=20),output.get(timeout=20)],['clone','idea'])
            for p in children:p.join(10);self.assertEqual(p.exitcode,0)
        finally:
            owner.release('acc1')
            for p in children:
                if p.is_alive():p.terminate();p.join()

    def test_two_priority_turns_then_ordinary_gets_turn(self):
        owner, ordinary = self.pool(), self.pool()
        urgent = [self.pool() for _ in range(3)]
        owner.acquire(IMAGE)
        ordinary.acquire(IMAGE, request_id='idea')
        for p in urgent:p.acquire(IMAGE, request_id='clone', priority=True)
        owner.release('acc1')
        for p in urgent[:2]:
            self.assertIsNone(ordinary.acquire(IMAGE,request_id='idea'))
            self.assertEqual(p.acquire(IMAGE,request_id='clone',priority=True),'acc1')
            p.release('acc1')
        self.assertIsNone(urgent[2].acquire(IMAGE,request_id='clone',priority=True))
        self.assertEqual(ordinary.acquire(IMAGE,request_id='idea'),'acc1')
        ordinary.release('acc1');urgent[2].cancel_wait(IMAGE,'clone')

    def test_abandoned_and_dead_waiters_do_not_reserve_accounts(self):
        state={'requests':[], 'priority_streak':0}
        waits.register(state,'stale',['acc1'],IMAGE,True)
        state['requests'][0]['seen']=time.time()-waits.TTL-1
        waits.register(state,'dead',['acc1'],IMAGE,True)
        state['requests'][1]['pid']=-1
        waits.save(self.root,state)
        p=self.pool()
        self.assertEqual(p.acquire(IMAGE),'acc1');p.release('acc1')

    def test_busy_generation_over_ten_minutes_is_not_failure(self):
        owner, pool = self.pool(), self.pool()
        owner.acquire(IMAGE)
        a=run.Accounts({'projects_dir':str(self.root),'profiles_dir':str(self.root)},['acc1'],pool=pool,on_event=lambda _:None)
        a.max_busy_wait_s=1
        ticks=itertools.count(0,1000)
        def release(_): owner.release('acc1')
        with mock.patch.object(run.time,'monotonic',side_effect=lambda:next(ticks)),mock.patch.object(pool,'wait_change',side_effect=release):
            self.assertEqual(a.acquire(),'acc1')
        a.release('acc1')

    def test_waiting_stage_requeues_without_failing_book_and_stop_works(self):
        cfg,d=new_item(self.root)
        a,p=accts(['acc3'])
        calls=[]
        def step(cfg,d,*args,step,**kw):
            calls.append(step)
            if len(calls)==1:
                store.write(d,status='running',stage='chờ tài khoản')
                return {'next':'pool_wait'}
            if step=='art':return {'next':'grid'}
            if step=='grid':return {'next':'finish'}
            store.write(d,status='done');return {'ok':True}
        with mock.patch.object(run,'run_book',side_effect=step):
            result=run.run_queue(cfg,accts=a,plus=['acc3'],on_event=lambda _:None)
        self.assertEqual(calls,['art','art','grid','finish'])
        self.assertTrue(result[0]['ok'])
        self.assertEqual(store.read(d)['status'],'done')
        stop=threading.Event();stop.set()
        with self.assertRaisesRegex(run.StageFailed,'dừng'):a.acquire(stop=stop)

    def test_idea_worker_yields_only_at_completed_image_boundary(self):
        idea,clone=self.pool(),self.pool()
        idea.acquire(IMAGE)
        self.assertFalse(idea.should_yield('acc1'))
        clone.acquire(IMAGE,request_id='grid',priority=True)
        self.assertTrue(idea.should_yield('acc1'))
        clone.cancel_wait(IMAGE,'grid')
        self.assertFalse(idea.should_yield('acc1'));idea.release('acc1')

    def test_real_clone_stage_reports_wait_instead_of_failure(self):
        cfg,d=new_item(self.root)
        owner,pool=self.pool(),self.pool()
        owner.acquire(IMAGE)
        a=run.Accounts({**cfg,'profiles_dir':str(self.root)},['acc1'],pool=pool,on_event=lambda _:None)
        result=run.run_book(cfg,d,a,['acc1'],step='art',on_event=lambda _:None)
        self.assertEqual(result,{'next':'pool_wait'})
        saved=store.read(d)
        self.assertEqual(saved['status'],'running')
        self.assertEqual(saved['art_state'],'queued')
        self.assertFalse(saved['reason'])
        self.assertEqual(pool.use,{})
        owner.release('acc1');pool.cancel_wait(IMAGE,f'{d.resolve()}:art')

    def test_stop_during_deferred_wait_cancels_without_retrying(self):
        cfg,d=new_item(self.root)
        a,p=accts(['acc3']);stop=threading.Event()
        def work(*args,**kw):stop.set();return {'next':'pool_wait'}
        with mock.patch.object(run,'run_book',side_effect=work) as job:
            result=run.run_queue(cfg,accts=a,plus=['acc3'],stop=stop,on_event=lambda _:None)
        self.assertEqual(job.call_count,1)
        self.assertFalse(result[0]['ok'])
        self.assertIn('dừng',store.read(d)['reason'])

    def test_waiter_file_lock_and_commit_error_do_not_leak_lease(self):
        p=self.pool()
        with mock.patch.object(waits,'save',side_effect=PermissionError('locked')):
            self.assertIsNone(p.acquire(IMAGE))
        self.assertEqual(p.use,{})
        real_save=waits.save; calls=[]
        def fail_commit(root,state):
            calls.append(1)
            if len(calls)==2:raise PermissionError('commit locked')
            real_save(root,state)
        with mock.patch.object(waits,'save',side_effect=fail_commit):
            self.assertIsNone(p.acquire(IMAGE))
        self.assertEqual(p.use,{})
        self.assertFalse(p._lease_handles)
        self.assertEqual(p.acquire(IMAGE),'acc1');p.release('acc1')

    def test_multiple_ready_requests_get_distinct_reservations(self):
        state={'requests':[],'priority_streak':0}
        for token in ('a','b','c'): waits.register(state,token,['acc1','acc2','acc3'],IMAGE,False)
        assigned=waits.allocations(state,lambda *_:True,3)
        self.assertEqual(len(assigned),3)
        self.assertEqual(set(assigned.values()),{'acc1','acc2','acc3'})
