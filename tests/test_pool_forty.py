import multiprocessing as mp
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
from calforge.llm.pool import AccountPool, CHAT, IMAGE, LEASE


def compete(root, index, owners, guard, output, start):
    names = [f'acc{i}' for i in range(1, 41)]
    pool = AccountPool(Path(root), names, cap=10, leases=True)
    used=set()
    errors=[]
    start.wait(15)
    def work(slot):
        for turn in range(40):
            n=(slot+turn*7+index*11)%40
            name=names[n]
            deadline=time.monotonic()+60
            while pool.acquire(CHAT if index%2 else IMAGE, only=name) is None:
                if time.monotonic()>deadline:
                    errors.append('timeout '+name);return
                time.sleep(.001)
            try:
                with guard:
                    if owners[n]: errors.append('overlap '+name)
                    owners[n]+=1
                    if sum(owners)>10: errors.append('global cap exceeded')
                used.add(name)
                time.sleep(.002)
            finally:
                with guard: owners[n]-=1
                pool.release(name)
    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(work,range(10)))
    output.put((sorted(used),errors,len(pool.use)))


def hold(root, ready):
    p=AccountPool(Path(root),['acc1'],cap=1,leases=True)
    assert p.acquire(IMAGE)=='acc1'
    ready.set()
    time.sleep(60)


class FortyAccountPoolTest(unittest.TestCase):
    def test_four_processes_forty_workers_no_duplicate_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(1,41): (Path(tmp)/f'acc{i}').mkdir()
            ctx=mp.get_context('spawn')
            owners=ctx.Array('i',40,lock=False);guard=ctx.Lock();out=ctx.Queue();start=ctx.Event()
            procs=[ctx.Process(target=compete,args=(tmp,i,owners,guard,out,start)) for i in range(4)]
            try:
                for p in procs:p.start()
                start.set()
                results=[out.get(timeout=180) for _ in procs]
                for p in procs:p.join(10);self.assertEqual(p.exitcode,0)
                self.assertEqual(set().union(*(set(r[0]) for r in results)),{f'acc{i}' for i in range(1,41)})
                self.assertEqual([r[1] for r in results],[[]]*4)
                self.assertEqual([r[2] for r in results],[0]*4)
                self.assertEqual(list(owners),[0]*40)
                self.assertEqual(list(Path(tmp).glob('*/'+LEASE)),[])
            finally:
                for p in procs:
                    if p.is_alive():p.terminate();p.join()

    def test_process_death_releases_lock_and_empty_pid_cannot_steal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/'acc1';d.mkdir()
            ctx=mp.get_context('spawn');ready=ctx.Event();p=ctx.Process(target=hold,args=(tmp,ready))
            p.start()
            try:
                self.assertTrue(ready.wait(15))
                other=AccountPool(Path(tmp),['acc1'],cap=1,leases=True)
                (d/LEASE).write_text('') # reproduces partially written PID metadata
                self.assertIsNone(other.acquire(IMAGE))
                p.terminate();p.join(10)
                self.assertEqual(other.acquire(IMAGE),'acc1')
                other.release('acc1')
            finally:
                if p.is_alive():p.terminate();p.join()

    def test_two_pool_instances_in_same_process_and_missing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'acc1').mkdir()
            a=AccountPool(Path(tmp),['acc1'],cap=1,leases=True)
            b=AccountPool(Path(tmp),['acc1'],cap=1,leases=True)
            self.assertEqual(a.acquire(IMAGE),'acc1')
            try:self.assertIsNone(b.acquire(CHAT))
            finally:a.release('acc1')
            self.assertEqual(b.acquire(CHAT),'acc1');b.release('acc1')
            c=AccountPool(Path(tmp),['missing'],cap=1,leases=True)
            self.assertIsNone(c.acquire(CHAT))

    def test_global_cap_and_launch_gap_shared_by_pool_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            names=['acc1','acc2','acc3']
            for n in names:(Path(tmp)/n).mkdir()
            clock={'now':1000.0}
            def now(): return clock['now']
            def sleep(seconds): clock['now']+=seconds
            a=AccountPool(Path(tmp),names,cap=2,leases=True,launch_gap_s=.1,clock=now,sleep=sleep)
            b=AccountPool(Path(tmp),names,cap=2,leases=True,launch_gap_s=.1,clock=now,sleep=sleep)
            self.assertEqual(a.acquire(IMAGE,only='acc1'),'acc1')
            self.assertEqual(b.acquire(CHAT,only='acc2'),'acc2')
            try:
                self.assertIsNone(b.acquire(IMAGE,only='acc3'))
                with a.launch_gate(): first=now()
                with b.launch_gate(): second=now()
                self.assertGreaterEqual(second-first,.1-1e-9)
            finally:
                a.release('acc1');b.release('acc2')
            self.assertEqual(b.acquire(IMAGE,only='acc3'),'acc3')
            b.release('acc3')

    def test_per_mode_cap_does_not_block_other_mode_under_shared_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            names=['acc1','acc2','acc3']
            for n in names:(Path(tmp)/n).mkdir()
            clone=AccountPool(Path(tmp),names,cap=2,global_cap=3,leases=True)
            idea=AccountPool(Path(tmp),names,cap=1,global_cap=3,leases=True)
            try:
                self.assertEqual(clone.acquire(IMAGE,only='acc1'),'acc1')
                self.assertEqual(clone.acquire(IMAGE,only='acc2'),'acc2')
                self.assertEqual(idea.acquire(CHAT,only='acc3'),'acc3')
                self.assertIsNone(clone.acquire(IMAGE))
                self.assertIsNone(idea.acquire(CHAT))
            finally:
                for n in names:clone.release(n);idea.release(n)

    def test_stale_v1_pid_does_not_block_account_or_global_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            names=['acc1','acc2']
            for n in names:(Path(tmp)/n).mkdir()
            a=AccountPool(Path(tmp),names,cap=1,leases=True)
            self.assertEqual(a.acquire(IMAGE,only='acc1'),'acc1')
            with mock.patch.object(Path,'unlink',side_effect=PermissionError('locked')):
                a.release('acc1')
            b=AccountPool(Path(tmp),names,cap=1,leases=True)
            self.assertEqual(b.acquire(IMAGE,only='acc2'),'acc2')
            b.release('acc2')
            self.assertEqual(b.acquire(IMAGE,only='acc1'),'acc1')
            b.release('acc1')
