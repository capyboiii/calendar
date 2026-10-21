import contextlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

# QPC gives a shared high-resolution ordering on Windows; monotonic_ns on
# Python 3.12 can tie distinct acquire/release events at millisecond resolution.
stamp = time.perf_counter_ns


def hold_until_killed(root, ready):
    b=BookBudget(root,1)
    if not b.acquire('interrupted'):raise AssertionError('cannot claim')
    ready.set()
    time.sleep(60)

from calforge import config, layout, pipeline
from calforge.clone import run, store
from calforge.imagegen import driver
from calforge.llm.book_budget import BookBudget, FILE, limit_for_capacity
from calforge.llm.pool import AccountPool


def simulated_batch(root, kind, capacity, barrier, active_count, peak_count, count_lock, events, ready, go):
    """Real schedulers and OS profile leases; only model/image generation is fake."""
    try:
        root=Path(root); profiles=root/'profiles'
        os.environ['CALFORGE_GLOBAL_BROWSER_CAP']=str(capacity)
        os.environ['CALFORGE_QUEUE_RANK']='1' if kind=='idea' else '2'
        cfg=dict(projects_dir=str(root/'projects'),profiles_dir=str(profiles),max_browsers=capacity,
                 book_workers=4,idea_lookahead=1,p2_parallel=1,finish_workers=1,
                 crash_retry_waits_s=[0,0],batch_retry_wait_s=0)
        names=[f'acc{i:02d}' for i in range(capacity)]
        pool=AccountPool(profiles,names,cap=capacity,global_cap=capacity,leases=True,queue_rank=int(os.environ['CALFORGE_QUEUE_RANK']))
        pool.wait_change=lambda _:time.sleep(.01)
        held=set(); local=threading.Lock()
        original_acquire,original_release=pool.acquire,pool.release
        def acquire(*a,**kw):
            name=original_acquire(*a,**kw)
            if name:
                with local:held.add(name)
                events.put((stamp(),'account_in',kind,name))
                with count_lock:
                    active_count.value+=1;peak_count.value=max(peak_count.value,active_count.value)
                    if active_count.value==capacity:barrier.set()
            return name
        def release(name):
            with local:
                ours=name in held
                held.discard(name)
            if ours:
                events.put((stamp(),'account_out',kind,name))
                with count_lock:active_count.value-=1
            original_release(name)
        pool.acquire, pool.release=acquire, release
        admitted=set()
        old_admit,old_release=BookBudget.acquire,BookBudget.release
        def admit(budget,key):
            ok=old_admit(budget,key)
            if ok:
                with local:
                    first=str(key) not in admitted
                    admitted.add(str(key))
                if first:events.put((stamp(),'book_in',kind,str(key)))
            return ok
        def finish(budget,key):
            old_release(budget,key)
            with local:
                ours=str(key) in admitted
                admitted.discard(str(key))
            if ours:events.put((stamp(),'book_out',kind,str(key)))
        attempts={}
        def render(page,job):
            barrier.wait(8)
            ident=str(job.out)
            attempts[ident]=attempts.get(ident,0)+1
            if job.id=='m01' and attempts[ident]==1:
                events.put((stamp(),'retry',kind,ident))
                raise driver.TempError('simulated temporary network timeout')
            time.sleep(.02)
            job.out.parent.mkdir(parents=True,exist_ok=True)
            result=job.out.with_suffix('.png');result.write_bytes(b'fake-image')
            return result
        def images(path,prefix,total):
            jobs=[driver.GenJob(f'{prefix}{i:02d}','prompt',Path(path)/f'{prefix}{i:02d}') for i in range(1,total+1)]
            driver.run_jobs(jobs,profiles,names,pool=pool,open_page=lambda _:contextlib.nullcontext(None),on_event=lambda _:None)
            if not all(j.result and not j.error for j in jobs):raise AssertionError('unfinished image jobs')
        def generated(cdir,cfg,on_event):
            events.put((stamp(),'art',kind,str(cdir)))
            images(cdir/'raw','m',12);images(cdir/'raw','g',12)
        def post(cdir,cfg,on_event,**kw):
            events.put((stamp(),'post',kind,str(cdir)))
            time.sleep(.04)
            images(cdir/'preview','p',7)
            return pipeline._status(cdir,ok=True,stage='listing',queue_wait=False)
        def clone_book(cfg,d,accts,plus,stop,on_event,*,step,on_grid_ready=None):
            if step=='art':
                generated(d,cfg,on_event)
                return {'next':'grid'}
            if step=='grid':return {'next':'finish'}
            post(d,cfg,on_event)
            store.write(d,status='done',stage='listing',reason='')
            return {'ok':True,'stage':'listing'}
        counter=[0]
        def idea(*a,**kw):
            counter[0]+=1;cdir=root/'projects'/'idea'/f'book{counter[0]:02d}'
            layout.ensure_system(cdir)
            layout.concept_file(cdir).write_text(json.dumps({'cover':{'title':cdir.name}}))
            return SimpleNamespace(concepts=[cdir],failed=[])
        def report(kdir,batch):
            return [dict(concept=rel,ok=pipeline._read_status(kdir/rel).get('ok',False),stage='listing',reason='') for rel in batch['concepts']]
        with mock.patch.object(BookBudget,'acquire',admit),mock.patch.object(BookBudget,'release',finish), \
                mock.patch.object(driver,'_Worker',side_effect=lambda *a,**kw:SimpleNamespace(run_job=render)), \
                mock.patch.object(pipeline,'produce_images',generated),mock.patch.object(pipeline,'finish_book',post), \
                mock.patch.object(pipeline,'batch_report',report),mock.patch('calforge.ideation.pipeline.run_ideation',side_effect=idea), \
                mock.patch.object(run,'run_book',clone_book):
            ready.set()
            if not go.wait(10):raise AssertionError('start timeout')
            if kind=='idea':
                batch=dict(target=10,concepts=[],failed_ideas=[],errors=[])
                finisher=pipeline._Finisher(cfg,lambda _:None)
                try:
                    result=pipeline._run_batch('idea',cfg,root/'projects'/'idea',batch,None,{'family':'styled_photography'},finisher,None,0,lambda _:None)
                    if not all(r['ok'] for r in result):raise AssertionError(result)
                finally:finisher.close()
            else:
                for i in range(2):
                    store.add_link_batch(cfg['projects_dir'],'https://www.etsy.com/listing/4591486406/2027-cat-knight-calendar-fantasy',
                                         book_count=5,group=f'clone{i}',year=2027)
                accts=run.Accounts(cfg,names,pool=pool,on_event=lambda _:None)
                result=run.run_queue(cfg,accts=accts,plus=names,on_event=lambda _:None)
                if len(result)!=10 or not all(r['ok'] for r in result):raise AssertionError(result)
        if pool.use or held or admitted:raise AssertionError('leaked books/accounts')
        events.put((stamp(),'success',kind,10))
    except BaseException as error:
        import traceback
        events.put((stamp(),'failure',kind,traceback.format_exc()))
        raise


class BookBudgetTest(unittest.TestCase):
    def test_book_slot_is_held_until_postproduction_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg={'projects_dir':tmp,'profiles_dir':str(root/'profiles'),'finish_workers':1}
            budget=BookBudget(root/'profiles',1)
            entered,allow=threading.Event(),threading.Event()
            def finish(*a,**kw):
                entered.set();allow.wait(3)
                return {'ok':True}
            self.assertTrue(budget.acquire('first'))
            with mock.patch.object(pipeline,'produce_images',return_value=None),mock.patch.object(pipeline,'finish_book',side_effect=finish):
                finisher=pipeline._Finisher(cfg,lambda _:None)
                try:
                    pipeline._safe_pipelined(root/'book',cfg,finisher,lambda _:None,on_complete=lambda:budget.release('first'))
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(budget.acquire('second'),'images done must not release a book still doing postproduction')
                    allow.set();finisher.wait()
                    self.assertTrue(budget.acquire('second'))
                finally:allow.set();finisher.close();budget.close()

    def test_image_failure_releases_book_and_post_retry_does_not_release_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg={'projects_dir':tmp,'profiles_dir':str(root/'profiles'),'finish_workers':1,'crash_retry_waits_s':[0]}
            budget=BookBudget(root/'profiles',1)
            self.assertTrue(budget.acquire('broken'))
            with mock.patch.object(pipeline,'produce_images',side_effect=ValueError('bad input')):
                finisher=mock.Mock()
                pipeline._safe_pipelined(root/'bad',cfg,finisher,lambda _:None,on_complete=lambda:budget.release('broken'))
                finisher.submit.assert_not_called()
            self.assertTrue(budget.acquire('next'))
            def finish(*a,**kw):
                self.assertFalse(budget.acquire('extra'))
                if finish.calls==0:
                    finish.calls+=1;raise MemoryError('temporary')
                return {'ok':True}
            finish.calls=0
            with mock.patch.object(pipeline,'produce_images',return_value=None),mock.patch.object(pipeline,'finish_book',side_effect=finish):
                finisher=pipeline._Finisher(cfg,lambda _:None)
                try:
                    pipeline._safe_pipelined(root/'good',cfg,finisher,lambda _:None,on_complete=lambda:budget.release('next'))
                    finisher.wait()
                finally:finisher.close()
            self.assertEqual(finish.calls,1)
            self.assertTrue(budget.acquire('extra'));budget.close()

    def test_terminated_process_book_slot_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx=mp.get_context('spawn');ready=ctx.Event();p=ctx.Process(target=hold_until_killed,args=(tmp,ready))
            p.start()
            try:
                self.assertTrue(ready.wait(10))
                b=BookBudget(tmp,1)
                self.assertFalse(b.acquire('resume'))
                p.terminate();p.join(5)
                self.assertTrue(b.acquire('resume'));b.close()
            finally:
                if p.is_alive():p.terminate()
                p.join(5)

    def test_limits(self):
        self.assertEqual([limit_for_capacity(n) for n in (1,6,12,24,40)],[1,2,2,2,4])

    def test_shared_limit_no_duplicate_book_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=BookBudget(tmp,2,rank=1),BookBudget(tmp,2,rank=2)
            self.addCleanup(a.close);self.addCleanup(b.close)
            self.assertTrue(a.acquire('one'));self.assertTrue(b.acquire('two'))
            self.assertFalse(b.acquire('one'));self.assertFalse(a.acquire('three'))
            a.release('one');self.assertTrue(a.acquire('three'))
            self.assertFalse(b.acquire('four'))

    def test_dead_process_reclaimed_and_bad_state_never_opens_book(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=BookBudget(tmp,1)
            (Path(tmp)/FILE).write_text('broken json')
            self.assertFalse(b.acquire('new'))
            (Path(tmp)/FILE).write_text(json.dumps({'active':[dict(pid=99999999,key='dead',owner='dead',limit=1)],'waiting':[]}))
            self.assertTrue(b.acquire('new'));b.close()

    def test_no_new_book_when_all_account_slots_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in ('acc1','acc2'):(root/n).mkdir()
            budget=BookBudget(root,2,capacity=2)
            pool=AccountPool(root,['acc1','acc2'],cap=2,leases=True)
            self.assertTrue(budget.acquire('one'))
            first=pool.acquire('image');second=pool.acquire('image')
            try:
                self.assertFalse(budget.acquire('two'))
                pool.release(first);self.assertTrue(budget.acquire('two'))
            finally:pool.release(second);budget.close()

    def test_temporary_release_write_error_retried_on_next_admission(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=BookBudget(tmp,1)
            self.assertTrue(b.acquire('one'))
            with mock.patch.object(b,'_state',side_effect=PermissionError('locked')):b.release('one')
            self.assertTrue(b.acquire('two'));b.close()

    def run_mixed(self,capacity):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'profiles').mkdir();(root/'projects').mkdir()
            for i in range(capacity):(root/'profiles'/f'acc{i:02d}').mkdir()
            ctx=mp.get_context('spawn');events=ctx.Queue();go=ctx.Event();barrier=ctx.Event()
            count=ctx.Value('i',0);peak=ctx.Value('i',0);lock=ctx.Lock();ready=[ctx.Event(),ctx.Event()]
            processes=[ctx.Process(target=simulated_batch,args=(tmp,kind,capacity,barrier,count,peak,lock,events,ready[i],go)) for i,kind in enumerate(('idea','clone'))]
            collected=[];started=time.monotonic()
            try:
                for p in processes:p.start()
                for event in ready:self.assertTrue(event.wait(15))
                go.set()
                deadline=time.monotonic()+100
                while time.monotonic()<deadline:
                    try:collected.append(events.get(timeout=.2))
                    except Exception:pass
                    if all(not p.is_alive() for p in processes):break
                for p in processes:p.join(2)
                while True:
                    try:collected.append(events.get(timeout=.1))
                    except Exception:break
                failures=[e for e in collected if e[1]=='failure']
                self.assertFalse(failures,failures)
                self.assertTrue(all(p.exitcode==0 for p in processes),[p.exitcode for p in processes])
                live_books=set();live_accounts=set();book_peak=0;completed=0;admission_at_first_finish=None
                admitted=0
                for _,event,kind,value in sorted(collected):
                    if event=='book_in':
                        self.assertNotIn((kind,value),live_books)
                        live_books.add((kind,value));admitted+=1
                        book_peak=max(book_peak,len(live_books))
                        self.assertLessEqual(len(live_books),limit_for_capacity(capacity))
                    elif event=='book_out':
                        live_books.remove((kind,value));completed+=1
                        if admission_at_first_finish is None:admission_at_first_finish=admitted
                    elif event=='account_in':
                        self.assertNotIn(value,live_accounts);live_accounts.add(value)
                        self.assertLessEqual(len(live_accounts),capacity)
                    elif event=='account_out':live_accounts.remove(value)
                self.assertEqual(completed,20);self.assertFalse(live_books);self.assertFalse(live_accounts)
                self.assertLessEqual(admission_at_first_finish,limit_for_capacity(capacity))
                self.assertEqual(peak.value,capacity)
                state=json.loads((root/'profiles'/FILE).read_text())
                self.assertEqual(state['active'],[]);self.assertEqual(state['waiting'],[])
                retries=sum(e[1]=='retry' for e in collected)
                self.assertGreaterEqual(retries,20)
                self.assertEqual(json.loads((root/'profiles'/'.calforge_waiters.json').read_text())['requests'],[])
                if os.environ.get('CALFORGE_SIM_REPORT_DIR'):
                    out=Path(os.environ['CALFORGE_SIM_REPORT_DIR']);out.mkdir(parents=True,exist_ok=True)
                    (out/f'accounts-{capacity}.json').write_text(json.dumps(dict(capacity=capacity,completed=completed,
                        book_peak=book_peak,profile_peak=peak.value,retries=retries,
                        admitted_before_first_finish=admission_at_first_finish,
                        elapsed_seconds=time.monotonic()-started,events=sorted(collected)),indent=2),encoding='utf-8')
                print(f'SIM {capacity} accounts: 20/20 books, peak accounts {peak.value}, peak unfinished {book_peak}, retry events {retries}, {time.monotonic()-started:.2f}s',flush=True)
            finally:
                for p in processes:
                    if p.is_alive():p.terminate()
                    p.join(5)

    def test_mixed_twelve_accounts_twenty_books(self):self.run_mixed(12)
    def test_mixed_forty_accounts_twenty_books(self):self.run_mixed(40)


if __name__=='__main__':unittest.main()
