import tempfile
import multiprocessing as mp
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge.llm.pool import AccountPool, IMAGE
from calforge.ui.batch_queue import BatchQueue
from tests.test_batch_queue import FakeTasks, args


def ranked_contender(root, rank, ready, go, out):
    pool = AccountPool(Path(root), ['acc0'], cap=1, leases=True, queue_rank=rank)
    pool.acquire(IMAGE, priority=rank == 20)
    ready.set()
    if not go.wait(10):
        raise RuntimeError('start timeout')
    if rank == 10:
        time.sleep(.15)  # later job polls first but must respect the earlier job
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        name = pool.acquire(IMAGE, priority=rank == 20)
        if name:
            out.put(rank)
            time.sleep(.05)
            pool.release(name)
            return
        time.sleep(.01)
    raise RuntimeError('account wait timeout')


class QueueFillTest(unittest.TestCase):
    def test_same_book_actions_wait_but_independent_book_can_fill_slots(self):
        tasks = FakeTasks()
        q = BatchQueue(tasks, self.root / 'q.json', args, lambda _: (1, 1),
                       capacity=lambda: {'slots': 10, 'limit': 40}, fill_delay_s=0)
        book = str(self.root / 'book')
        q.add(dict(keyword='working', action='produce', concept=book))
        blocked = q.add(dict(keyword='repair', action='redo', concept=book, pages=['m01']))
        q.add(dict(keyword='independent', action='finish', concept=str(self.root / 'other')))
        self.assertEqual(tasks.started, ['working', 'independent'])
        self.assertEqual(blocked['status'], 'queued')
        tasks.tasks[q.items[0]['task_id']].status = 'success'
        q.tick()
        self.assertEqual(tasks.started, ['working', 'independent', 'repair'])

    def test_overlapping_clone_id_subsets_do_not_run_together(self):
        tasks = FakeTasks()
        q = BatchQueue(tasks, self.root / 'q.json', args, lambda _: (1, 1),
                       capacity=lambda: {'slots': 10, 'limit': 40}, fill_delay_s=0)
        q.add(dict(keyword='first', action='clone', clone_ids=['a', 'b']))
        blocked = q.add(dict(keyword='overlap', action='clone', clone_ids=['b', 'c']))
        q.add(dict(keyword='separate', action='clone', clone_ids=['d']))
        self.assertEqual(tasks.started, ['first', 'separate'])
        self.assertEqual(blocked['status'], 'queued')

    def test_parent_idea_or_clone_batch_owns_its_book_during_repairs(self):
        from calforge import products
        from calforge.ui import server
        cfg = {'projects_dir': str(self.root)}
        topic = products.root(self.root, products.DEFAULT) / 'knight-cats'
        book = topic / 'SKU'
        idea = dict(keyword='knight cats')
        repair = dict(action='redo', concept=str(book))
        clone = dict(action='clone', clone_ids=['261018084633be7fbb28'])
        with mock.patch.object(server.config, 'load', return_value=cfg), \
                mock.patch('calforge.clone.store.read', return_value={'book':str(book)}):
            self.assertTrue(server._queue_conflicts(idea, repair))
            self.assertTrue(server._queue_conflicts(repair, idea))
            self.assertTrue(server._queue_conflicts(clone, repair))
            self.assertTrue(server._queue_conflicts(idea, dict(keyword='Knight Cats')))
            self.assertFalse(server._queue_conflicts(idea, dict(action='finish', concept=str(self.root/'different'/'SKU'))))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.names = [f'acc{i}' for i in range(40)]
        for name in self.names:
            (self.root / name).mkdir()

    def pool(self, rank=None, names=None):
        pool = AccountPool(self.root, names or self.names, cap=40, global_cap=40,
                           leases=True, queue_rank=rank)
        self.addCleanup(lambda: [pool.release(n) for n in list(pool.use)])
        return pool

    def test_forty_accounts_fill_12_12_12_4_without_waiting_for_first_book(self):
        tasks = FakeTasks()
        monitor = self.pool()
        pools = []
        start = tasks.start_task
        def launch(argv, desc, action, params):
            tid = start(argv, desc, action, params)
            pool = self.pool(params['_queue_rank'])
            pools.append(pool)
            for i in range(12):
                if pool.acquire(IMAGE, request_id=f'page{i}') is None:
                    break
            return tid
        tasks.start_task = launch
        q = BatchQueue(tasks, self.root / 'q.json', args, lambda _: (1, 1),
                       capacity=lambda: {'slots': monitor.spare_capacity(), 'limit': 40}, fill_delay_s=0)
        for title in ('book1', 'book2', 'book3', 'book4', 'book5'):
            q.add({'keyword': title})
        self.assertEqual(tasks.started, ['book1', 'book2', 'book3', 'book4'])
        self.assertEqual([len(p.use) for p in pools], [12, 12, 12, 4])
        self.assertEqual(len(set().union(*(set(p.use) for p in pools))), 40)
        self.assertEqual(q.items[-1]['status'], 'queued')
        self.assertEqual(monitor.spare_capacity(), 0)

    def test_earlier_queue_request_beats_later_grid_priority(self):
        owner = self.pool(10, ['acc0'])
        first = self.pool(20, ['acc0'])
        later = self.pool(30, ['acc0'])
        owner.acquire(IMAGE)
        self.assertIsNone(later.acquire(IMAGE, priority=True))
        self.assertIsNone(first.acquire(IMAGE))
        owner.release('acc0')
        self.assertIsNone(later.acquire(IMAGE, priority=True))
        self.assertEqual(first.acquire(IMAGE), 'acc0')
        self.assertFalse(first.should_yield('acc0'))
        first.release('acc0')
        self.assertEqual(later.acquire(IMAGE, priority=True), 'acc0')
        self.assertIsNone(first.acquire(IMAGE))
        self.assertTrue(later.should_yield('acc0'))

    def test_real_processes_honor_queue_order_even_when_later_job_polls_first(self):
        owner = self.pool(1, ['acc0'])
        owner.acquire(IMAGE)
        ctx = mp.get_context('spawn')
        go, out = ctx.Event(), ctx.Queue()
        ready = [ctx.Event(), ctx.Event()]
        children = [ctx.Process(target=ranked_contender, args=(str(self.root), rank, ready[i], go, out))
                    for i, rank in enumerate((20, 10))]
        try:
            for child, event in zip(children, ready):
                child.start()
                self.assertTrue(event.wait(10))
            owner.release('acc0')
            go.set()
            self.assertEqual([out.get(timeout=15), out.get(timeout=15)], [10, 20])
            for child in children:
                child.join(10)
                self.assertEqual(child.exitcode, 0)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join()

    def test_spare_capacity_reserves_earlier_waiters_before_admitting_more(self):
        monitor = self.pool()
        pending = self.pool(1)
        # Register a request while capacity is temporarily unavailable.
        pending.cap = 1
        held = pending.acquire(IMAGE, request_id='owner')
        self.assertIsNone(pending.acquire(IMAGE, request_id='next'))
        pending.release(held)
        # Refresh its eligible names now that its local slot is available.
        owner = self.pool(0)
        for name in self.names:
            owner.acquire(IMAGE, only=name)
        self.assertIsNone(pending.acquire(IMAGE, request_id='next'))
        owner.release('acc0')
        self.assertEqual(monitor.spare_capacity(), 0)
        owner.release('acc1')
        self.assertEqual(monitor.spare_capacity(), 1)

    def test_start_order_pause_and_launch_pacing_with_spare_accounts(self):
        tasks = FakeTasks()
        now = [0]
        q = BatchQueue(tasks, self.root / 'q.json', args, lambda _: (1, 1),
                       capacity=lambda: {'slots': 20, 'limit': 40}, clock=lambda: now[0], fill_delay_s=3)
        for title in ('idea', 'clone', 'next'):
            q.add({'keyword': title, **({'action': 'clone', 'clone_ids': ['abcdef']} if title == 'clone' else {})})
        self.assertEqual(tasks.started, ['idea'])
        now[0] = 3
        q.tick()
        self.assertEqual(tasks.started, ['idea', 'clone'])
        self.assertEqual(tasks.tasks['t2'].action, 'clone')
        q.pause()
        self.assertEqual(set(tasks.stopped), {'t1', 't2'})
        self.assertEqual([i['params']['keyword'] for i in q.items], ['idea', 'clone', 'next'])
        q.tick()
        self.assertEqual(len(tasks.started), 2)

    def test_no_new_job_when_monitor_fails_or_same_topic_still_runs(self):
        tasks = FakeTasks()
        q = BatchQueue(tasks, self.root / 'q.json', args, lambda _: (1, 1),
                       capacity=lambda: {'slots': 20, 'limit': 40}, fill_delay_s=0)
        q.add({'keyword': 'same'})
        q.add({'keyword': 'same'})
        self.assertEqual(tasks.started, ['same'])
        q.remove(q.items[-1]['id'])
        q.capacity = lambda: (_ for _ in ()).throw(OSError('locked monitor'))
        q.add({'keyword': 'different'})
        self.assertEqual(tasks.started, ['same'])

    def test_child_process_receives_shared_cap_and_priority_without_inheriting_stale_values(self):
        import os
        from calforge.ui import server
        targets = []
        def thread(*, target, **kwargs):
            targets.append(target)
            return mock.Mock()
        manager = server.TaskManager()
        process = mock.Mock(stdout=[], returncode=0)
        with mock.patch.object(server.config, 'load', return_value={'projects_dir': str(self.root)}), \
                mock.patch.object(server.threading, 'Thread', side_effect=thread), \
                mock.patch.object(server.subprocess, 'Popen', return_value=process) as launch, \
                mock.patch.dict(os.environ, {'CALFORGE_QUEUE_RANK': '999', 'CALFORGE_GLOBAL_BROWSER_CAP': '999'}):
            manager.start_task(['run', 'cats'], 'cats', 'run', {'_queue_rank': 10, '_pool_cap': 7})
            targets[-1]()
            env = launch.call_args.kwargs['env']
            self.assertEqual(env['CALFORGE_QUEUE_RANK'], '10')
            self.assertEqual(env['CALFORGE_GLOBAL_BROWSER_CAP'], '7')
            manager.start_task(['run', 'cats'], 'cats', 'run', {})
            targets[-1]()
            env = launch.call_args.kwargs['env']
            self.assertNotIn('CALFORGE_QUEUE_RANK', env)
            self.assertNotIn('CALFORGE_GLOBAL_BROWSER_CAP', env)

    def test_common_cap_not_recounted_as_spare_ram_during_launch_delay(self):
        from calforge.ui import server
        from types import SimpleNamespace
        cfg = {'projects_dir': str(self.root), 'profiles_dir': str(self.root), 'max_browsers': 40}
        pool = self.pool()
        for name in self.names[:7]:
            pool.acquire(IMAGE, only=name)
        with mock.patch.object(server.config, 'load', return_value=cfg), \
                mock.patch.object(server, '_QUEUE', SimpleNamespace(pool_limit=7)), \
                mock.patch('calforge.llm.accounts.has_chatgpt_session', return_value=True), \
                mock.patch('calforge.llm.accounts.is_profile_locked', return_value=False), \
                mock.patch('calforge.llm.pool.free_ram_gb', return_value=64):
            room = server._queue_capacity()
        self.assertEqual(room, {'slots': 0, 'limit': 7})


if __name__ == '__main__':
    unittest.main()
