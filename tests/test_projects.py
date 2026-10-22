import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import threading
from unittest import mock

from calforge import config, layout, projects, products
from calforge.clone import store
from calforge.ui import server
from tests import fixtures


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=server.ROOT / '.cache')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = config.load()
        self.cfg['projects_dir'] = str(self.root)
        self.patch = mock.patch.object(server.config, 'load', return_value=self.cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def handler(self, data):
        h = mock.Mock()
        raw = json.dumps(data).encode()
        h.headers = {'Content-Length': str(len(raw)), 'Content-Type': 'application/json'}
        h.rfile = io.BytesIO(raw)
        return h

    def test_create_reopen_validate_and_preserve_legacy(self):
        p = projects.create(self.root, 'Dự án tháng 10')
        self.assertEqual(projects.entries(self.root), [p])
        self.assertEqual(projects.require(self.root, p['id']).parent.name, '_du_an')
        for name in ('', 'x' * 101, 'DỰ ÁN THÁNG 10', 'bad\nname'):
            with self.assertRaises(ValueError): projects.create(self.root, name)
        for ident in ('', '../outside', 'a'*32, None):
            with self.assertRaises(ValueError): projects.require(self.root, ident)
        self.assertEqual(projects.run_root(self.root, {}), self.root)

    def test_external_storage_discovery_resume_and_path_permissions(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT / '.cache') as folder:
            parent = Path(folder)
            p = projects.create(self.root, 'Other drive', str(parent))
            target = projects.require(self.root, p['id'])
            self.assertEqual(target.parent, parent)
            self.assertNotEqual(target, parent)
            book = layout.new_book_dir(products.root(target) / 'topic', 'Example', 'r1a1')
            layout.concept_file(book).write_text(json.dumps(fixtures.concept()), encoding='utf-8')
            self.assertIn(book, layout.books(self.root))
            self.assertTrue(server._in_projects(book))
            self.assertFalse(server._in_projects(parent / 'private.txt'))
            self.assertEqual(server._book_arg({'concept': str(book)}), book)
            self.assertEqual((server.ROOT / server._rel(book)).resolve(), book.resolve())
            h = mock.Mock()
            server.StudioHandler._api_list_projects(h)
            result = h._send_json.call_args.args[0]
            self.assertEqual(result['projects'][0]['project_id'], p['id'])
            self.assertEqual(result['projects'][0]['concepts'][0]['path'], server._rel(book))
            image = book / 'sample.png'
            image.write_bytes(b'image')
            h = mock.Mock()
            server.StudioHandler._api_get_file(h, server._rel(image))
            self.assertEqual(h._serve_file.call_args.args[0], image.resolve())
            with mock.patch.dict(os.environ, {'CALFORGE_PROJECT_ID': p['id']}):
                self.assertEqual(projects.run_root(self.root, {'project_id': p['id']}), target)

    def test_external_clone_shared_source_and_recovery(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT / '.cache') as folder:
            p = projects.create(self.root, 'Clone external', folder)
            rows = store.add_link_batch(self.root, 'https://example.com/item', book_count=2, project_id=p['id'])
            d = store.item_dir(self.root, rows[0]['id'])
            source = store.source_dir(d)
            self.assertTrue(source.is_relative_to(projects.require(self.root, p['id'])))
            store.write(source, published=False)
            (d / 'item.json').unlink()
            d.rmdir()
            store.recover_batches(self.root)
            self.assertEqual(store.source_dir(d), source)
            store.write(d, source_path=str(Path(folder) / '_clone_sources' / 'abc123'))
            with self.assertRaises(ValueError): store.source_dir(d)

    def test_external_clone_adoption_uses_selected_directory(self):
        from calforge.clone.run import Book
        with tempfile.TemporaryDirectory(dir=server.ROOT / '.cache') as folder:
            p = projects.create(self.root, 'External adoption', folder)
            item = store.add_link(self.root, 'https://example.com/item', project_id=p['id'])
            d = store.item_dir(self.root, item['id'])
            work = d / 'work'
            layout.ensure_system(work)
            meta = {'title': 'Example', 'etsy_title': 'Example calendar', 'etsy_description': 'Description',
                    'tags': ['calendar'], 'months': [f'Month {i}' for i in range(1, 13)]}
            layout.tech(work).mkdir(parents=True, exist_ok=True)
            (layout.tech(work) / 'clone_meta.json').write_text(json.dumps(meta))
            b = Book(self.cfg, d, on_event=lambda _: None)
            b._adopt_locked()
            saved = Path(store.read(d)['book'])
            self.assertTrue(saved.is_relative_to(projects.require(self.root, p['id'])))
            self.assertTrue(layout.is_book(saved))
            self.assertIn(saved, layout.books(self.root))

    def test_external_invalid_parent_and_missing_drive(self):
        for value in ('relative', str(self.root / 'missing')):
            with self.assertRaises(ValueError): projects.create(self.root, 'Invalid', value)
        self.assertEqual(projects.entries(self.root), [])
        with tempfile.TemporaryDirectory(dir=server.ROOT / '.cache') as folder:
            p = projects.create(self.root, 'Offline', folder)
            projects.require(self.root, p['id']).rmdir()
            with self.assertRaisesRegex(ValueError, 'ổ đĩa'): projects.require(self.root, p['id'])
            h = mock.Mock()
            server.StudioHandler._api_list_projects(h)
            self.assertEqual(h._send_json.call_args.args[0]['workspaces'][0]['id'], p['id'])

    def test_external_delete_keeps_selected_parent_and_removes_registry(self):
        with tempfile.TemporaryDirectory(dir=server.ROOT / '.cache') as folder:
            p = projects.create(self.root, 'Delete external', folder)
            target = projects.require(self.root, p['id'])
            q = mock.Mock(items=[], lock=threading.RLock())
            with mock.patch.object(server, 'batch_queue', return_value=q), mock.patch.object(server.TASK_MANAGER, 'tasks', {}), mock.patch.object(server, '_to_recycle_bin', side_effect=lambda path: path.rmdir()):
                server._delete_workspace(p['id'])
            self.assertFalse(target.exists())
            self.assertTrue(Path(folder).is_dir())
            self.assertEqual(projects.entries(self.root), [])

    def test_two_projects_same_keyword_separate_batches_and_legacy_visible(self):
        a, b = [projects.create(self.root, name) for name in ('A', 'B')]
        for p, ok in ((a, True), (b, False)):
            kdir = products.root(projects.require(self.root, p['id'])) / 'same'
            book = layout.new_book_dir(kdir, 'Same', 'r1a1')
            layout.concept_file(book).write_text(json.dumps(fixtures.concept()), encoding='utf-8')
            layout.status_file(book).write_text(json.dumps({'ok': ok, 'stage': 'listing'}))
            layout.batch_file(kdir).parent.mkdir(parents=True, exist_ok=True)
            layout.batch_file(kdir).write_text(json.dumps({'target': 1, 'concepts': [book.name], 'report': [{'ok': ok}]}))
        legacy = products.root(self.root) / 'old'
        book = layout.new_book_dir(legacy, 'Old', 'r1a1')
        layout.concept_file(book).write_text(json.dumps(fixtures.concept()), encoding='utf-8')
        h = mock.Mock()
        server.StudioHandler._api_list_projects(h)
        data = h._send_json.call_args.args[0]
        self.assertEqual({p['project_id'] for p in data['projects']}, {'', a['id'], b['id']})
        self.assertEqual(len(data['workspaces']), 2)
        self.assertEqual(server._batch_result({'keyword': 'same', 'project_id': a['id']}), (1, 1, False))
        self.assertEqual(server._batch_result({'keyword': 'same', 'project_id': b['id']}), (0, 1, True))

    def test_clone_add_requires_project_and_keeps_membership_after_retry(self):
        h = self.handler({'links': ['https://example.com/item']})
        server.StudioHandler._api_clone(h, 'add')
        self.assertEqual(h._send_json.call_args.kwargs['status'], 400)
        p = projects.create(self.root, 'Clone')
        h = self.handler({'links': ['https://example.com/item'], 'project_id': p['id'], 'group': 'Test clone'})
        with mock.patch.object(server, '_clone_items', return_value={}):
            server.StudioHandler._api_clone(h, 'add')
        item = store.items(self.root)[0]
        self.assertEqual(item['project_id'], p['id'])
        store.write(store.item_dir(self.root, item['id']), status='failed', reason='temporary')
        store.retry(self.root, item['id'])
        self.assertEqual(store.items(self.root)[0]['project_id'], p['id'])

    def test_queue_rejects_missing_project_and_preserves_resume_project(self):
        p = projects.create(self.root, 'Idea')
        for params, accepted in (({'keyword': 'test'}, False), ({'keyword': 'test', 'project_id': p['id']}, True),
                                 ({'keyword': 'old', 'resume': True}, True)):
            h = self.handler({'params': params})
            h.path = '/api/queue/add'
            h._cross_site.return_value = ''
            with mock.patch.object(server, 'batch_queue') as queue:
                server.StudioHandler._handle_api_post(h, '/api/queue/add')
                self.assertEqual(queue.return_value.add.called, accepted)
                if accepted: self.assertEqual(queue.return_value.add.call_args.args[0], params)

    def test_subprocess_config_project_override_does_not_change_saved_config(self):
        p = projects.create(self.root, 'Env')
        file = self.root / 'calforge.json'
        file.write_text(json.dumps({'projects_dir': str(self.root)}))
        self.patch.stop()
        try:
            with mock.patch.object(config, 'CONFIG_FILE', file), mock.patch.dict(os.environ, {'CALFORGE_PROJECT_ID': p['id']}):
                self.assertEqual(Path(config.load()['projects_dir']), projects.require(self.root, p['id']))
            self.assertEqual(json.loads(file.read_text())['projects_dir'], str(self.root))
        finally:
            self.patch.start()

    def test_clone_adopts_into_project_and_reopening_keeps_same_book(self):
        from calforge.clone.run import Book
        p = projects.create(self.root, 'Adopt')
        item = store.add_link(self.root, 'https://example.com/item', project_id=p['id'])
        d = store.item_dir(self.root, item['id'])
        work = d / 'work'
        layout.ensure_system(work)
        meta = {'title': 'Example', 'etsy_title': 'Example calendar', 'etsy_description': 'Description', 'tags': ['calendar'],
                'months': [f'Month {i}' for i in range(1, 13)]}
        layout.tech(work).mkdir(parents=True, exist_ok=True)
        (layout.tech(work) / 'clone_meta.json').write_text(json.dumps(meta))
        b = Book(self.cfg, d, on_event=lambda _: None)
        b._adopt_locked()
        saved = Path(store.read(d)['book'])
        self.assertTrue(saved.is_relative_to(projects.require(self.root, p['id'])))
        self.assertTrue(layout.concept_file(saved).is_file())
        self.assertEqual(store.read(d)['project_id'], p['id'])
        again = Book(self.cfg, d, on_event=lambda _: None)
        again._adopt_locked()
        self.assertEqual(again.dir, saved)
        self.assertEqual(len(layout.books(projects.require(self.root, p['id']))), 1)

    def test_clone_api_rejects_empty_topic(self):
        p = projects.create(self.root, 'Topic')
        for topic in ('', '  ', None):
            h = self.handler({'links': ['https://example.com/item'], 'project_id': p['id'], 'group': topic})
            with mock.patch.object(store, 'add_link') as add:
                server.StudioHandler._api_clone(h, 'add')
                add.assert_not_called()
                self.assertEqual(h._send_json.call_args.kwargs['status'], 400)

    def test_delete_requires_confirmation_and_blocks_active_work(self):
        p = projects.create(self.root, 'Delete')
        target = projects.require(self.root, p['id'])
        h = self.handler({'id': p['id']})
        server.StudioHandler._handle_api_post(h, '/api/workspaces/delete')
        self.assertEqual(h._send_json.call_args.kwargs['status'], 400)
        q = mock.Mock(items=[], lock=threading.RLock())
        with mock.patch.object(server, 'batch_queue', return_value=q), mock.patch.object(server.TASK_MANAGER, 'tasks', {}), mock.patch.object(server, '_to_recycle_bin') as recycle:
            for status in ('queued', 'running'):
                q.items = [{'params': {'project_id': p['id']}, 'status': status}]
                with self.assertRaisesRegex(ValueError, 'hàng đợi'): server._delete_workspace(p['id'])
            q.items = []
            item = store.add_link(self.root, 'https://example.com/item', project_id=p['id'])
            with self.assertRaisesRegex(ValueError, 'clone'): server._delete_workspace(p['id'])
            recycle.assert_not_called()
        self.assertTrue(target.exists())

    def test_delete_archives_clone_and_rolls_back_when_recycle_fails(self):
        p = projects.create(self.root, 'Archive')
        target = projects.require(self.root, p['id'])
        item = store.add_link(self.root, 'https://example.com/item', project_id=p['id'])
        d = store.item_dir(self.root, item['id'])
        store.write(d, status='failed')
        q = mock.Mock(items=[{'params': {'project_id': p['id']}, 'status': 'failed'}], lock=threading.RLock())
        with mock.patch.object(server, 'batch_queue', return_value=q), mock.patch.object(server.TASK_MANAGER, 'tasks', {}):
            with mock.patch.object(server, '_to_recycle_bin', side_effect=OSError('locked')):
                with self.assertRaises(OSError): server._delete_workspace(p['id'])
            self.assertTrue(d.exists())
            self.assertTrue(target.exists())
            archived = self.root / '_trash'
            with mock.patch.object(server, '_to_recycle_bin', side_effect=lambda path: path.rename(archived)):
                server._delete_workspace(p['id'])
            self.assertFalse(target.exists())
            self.assertFalse(d.exists())
            self.assertTrue((archived / '_clone_queue' / item['id'] / 'item.json').is_file())
            self.assertFalse(q.items[0]['retryable'])
            self.assertEqual(projects.entries(self.root), [])
