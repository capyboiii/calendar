import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from calforge.clone import store, run
from calforge.ui import server
from calforge.ui.batch_queue import BatchQueue
from tests.test_batch_queue import FakeTasks
from tests.test_clone_expand import URL


class UnifiedQueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {'projects_dir': self.tmp.name}
        self.patch = mock.patch.object(server.config, 'load', return_value=self.cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.tasks = FakeTasks()
        self.q = BatchQueue(self.tasks, Path(self.tmp.name) / 'queue.json', server.run_args,
                            server._batch_result, ideas_done=lambda _: True)

    def clone(self, title='cats', count=2):
        return store.add_link_batch(self.tmp.name, URL, group=title, book_count=count)

    def test_mixed_fifo_and_clone_additions_do_not_join_active_batch(self):
        self.q.add({'keyword': 'idea A'})
        rows = self.clone()
        entries = server._enqueue_clones(rows, queue=self.q)
        clone = entries[0]
        # FakeTasks uses keyword to identify starts; production uses title.
        clone['params']['keyword'] = 'clone B'
        self.q.add({'keyword': 'idea C'})
        later = server._enqueue_clones(self.clone('dogs', 1), queue=self.q)[0]
        later['params']['keyword'] = 'clone D'
        self.assertEqual(self.tasks.started, ['idea A'])
        self.tasks.tasks['t1'].status = 'success'
        self.q.tick()
        self.assertEqual(self.tasks.started, ['idea A', 'clone B'])
        self.assertEqual(set(clone['params']['clone_ids']), {i['id'] for i in rows})
        for item in rows:
            store.write(store.item_dir(self.tmp.name, item['id']), status='done')
        self.tasks.tasks['t2'].status = 'success'
        self.q.tick()
        self.assertEqual(self.tasks.started, ['idea A', 'clone B', 'idea C'])
        self.assertEqual(clone['status'], 'done')

    def test_duplicate_start_and_pause_resume_preserve_exact_clone_ids(self):
        rows = self.clone()
        entry = server._enqueue_clones(rows, queue=self.q, start=False)[0]
        entry['params']['keyword'] = 'clone'
        self.q.tick()
        self.assertFalse(server._enqueue_clones(rows, queue=self.q))
        self.q.pause()
        self.assertEqual(self.tasks.stopped, ['t1'])
        self.assertEqual(entry['params']['clone_ids'], [r['id'] for r in sorted(rows, key=lambda r: r['id'])])
        self.q.resume()
        self.assertEqual(self.tasks.started, ['clone', 'clone'])
        self.assertEqual(self.tasks.tasks['t2'].action, 'clone')

    def test_retry_immediately_after_process_stop_is_not_deduplicated_as_running(self):
        rows = self.clone()
        old = server._enqueue_clones(rows, queue=self.q, start=False)[0]
        old['params']['keyword'] = 'clone'
        self.q.tick()
        self.tasks.tasks['t1'].status = 'stopped'
        new = self.q.add(dict(old['params']))
        self.assertNotEqual(old['id'], new['id'])
        self.assertEqual(self.tasks.started, ['clone', 'clone'])
        self.assertEqual(old['status'], 'stopped')

    def test_clone_report_rejected_and_missing_are_not_retryable(self):
        rows = self.clone()
        ids = [r['id'] for r in rows]
        store.write(store.item_dir(self.tmp.name, ids[0]), status='done')
        store.write(store.item_dir(self.tmp.name, ids[1]), status='rejected', terminal=True)
        self.assertEqual(server._batch_result({'action': 'clone', 'clone_ids': ids}), (1, 2, False))
        store.remove(self.tmp.name, ids[1], running_now=False)
        self.assertEqual(server._batch_result({'action': 'clone', 'clone_ids': ids}), (1, 2, False))

    def test_selected_clone_run_never_claims_other_waiting_group(self):
        first, second = self.clone('first', 1)[0], self.clone('second', 1)[0]
        accts = SimpleNamespace(pool=mock.Mock())
        calls = []
        def work(cfg, d, *args, step, **kwargs):
            calls.append((d.name, step))
            if step == 'art':
                # A later group appears while this batch is already running.
                if len(calls) == 1:
                    self.clone('third', 1)
                return {'next': 'grid'}
            if step == 'grid':
                return {'next': 'finish'}
            store.write(d, status='done')
            return {'ok': True}
        with mock.patch.object(run, 'run_book', side_effect=work):
            result = run.run_queue(self.cfg, on_event=lambda _: None, accts=accts,
                                   plus=[f'acc{i}' for i in range(40)], item_ids=[first['id']])
        self.assertTrue(result[0]['ok'])
        self.assertEqual({ident for ident, _ in calls}, {first['id']})
        self.assertEqual(store.read(store.item_dir(self.tmp.name, second['id']))['status'], 'pending')

    def test_add_api_publishes_exact_group_without_direct_start(self):
        handler = mock.Mock()
        data = json.dumps({'links': [URL], 'group': 'cats', 'book_count': 3}).encode()
        handler.headers = {'Content-Length': str(len(data))}
        handler.rfile = io.BytesIO(data)
        with mock.patch.object(server.workspaces, 'require'), \
                mock.patch.object(server, '_enqueue_clones') as enqueue, \
                mock.patch.object(server, '_clone_items', return_value={}), \
                mock.patch.object(server.TASK_MANAGER, 'start_task') as start:
            server.StudioHandler._api_clone(handler, 'add')
        self.assertEqual(len(enqueue.call_args.args[0]), 3)
        start.assert_not_called()

    def test_restart_keeps_clone_entry_and_migration_runs_once(self):
        rows = self.clone()
        with mock.patch.object(server, '_QUEUE', None), mock.patch.object(server, 'TASK_MANAGER', self.tasks):
            q = server.batch_queue()
            self.assertTrue(q.unified)
            self.assertEqual(len(q.items), 1)
            ids = q.items[0]['params']['clone_ids']
            self.assertEqual(set(ids), {r['id'] for r in rows})
            q.remove(q.items[0]['id'])
            server._QUEUE = None
            self.assertEqual(server.batch_queue().items, [])

    def test_removing_one_queued_clone_preserves_its_siblings(self):
        rows = self.clone()
        entry = server._enqueue_clones(rows, queue=self.q, start=False)[0]
        handler = mock.Mock()
        data = json.dumps({'id': rows[0]['id']}).encode()
        handler.headers = {'Content-Length': str(len(data))}
        handler.rfile = io.BytesIO(data)
        with mock.patch.object(server, 'batch_queue', return_value=self.q), \
                mock.patch.object(server, '_clone_items', return_value={}):
            server.StudioHandler._api_clone(handler, 'remove')
        self.assertEqual(entry['params']['clone_ids'], [rows[1]['id']])
        args, _ = server.run_args(entry['params'])
        self.assertEqual(args, ['clone-run', '--item', rows[1]['id']])

    def test_stop_before_process_launch_cannot_launch_later(self):
        manager = server.TaskManager()
        targets = []
        def thread(*, target, **kwargs):
            targets.append(target)
            return mock.Mock()
        with mock.patch.object(server.threading, 'Thread', side_effect=thread), \
                mock.patch.object(server.subprocess, 'Popen') as launch:
            tid = manager.start_task(['clone-run'], 'clone', 'clone')
            self.assertTrue(manager.stop_task(tid))
            targets[0]()
            launch.assert_not_called()
        self.assertIsNone(manager.running())

    def test_stopping_process_blocks_next_queue_entry(self):
        manager = server.TaskManager()
        task = server.Task('old', [], 'clone', 'clone')
        task.status = 'stopping'
        manager.tasks['old'] = task
        q = BatchQueue(manager, Path(self.tmp.name) / 'stopping.json', server.run_args,
                       server._batch_result)
        with mock.patch.object(manager, 'start_task') as start:
            q.add({'keyword': 'next'})
            start.assert_not_called()

    def test_legacy_idea_start_cannot_bypass_paused_queue(self):
        self.q.pause()
        handler = mock.Mock()
        data = json.dumps({'action': 'run', 'params': {'keyword': 'legacy idea'}}).encode()
        handler.headers = {'Content-Length': str(len(data))}
        handler.rfile = io.BytesIO(data)
        with mock.patch.object(server.workspaces, 'require'), \
                mock.patch.object(server, 'batch_queue', return_value=self.q), \
                mock.patch.object(server.TASK_MANAGER, 'start_task') as start:
            server.StudioHandler._handle_api_post(handler, '/api/action')
        self.assertEqual(len(self.q.items), 1)
        self.assertEqual(self.q.items[0]['status'], 'queued')
        start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
