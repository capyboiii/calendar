import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import cli, config, projects
from calforge.clone import run, store
from calforge.ui import server
from tests.test_clone_expand import URL


class CloneProjectStartTest(unittest.TestCase):
    def test_actual_cli_config_load_keeps_global_clone_queue_with_project_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'books'
            project = projects.create(root, 'Test project')
            rows = store.add_link_batch(root, URL, project_id=project['id'], book_count=2)
            settings = Path(tmp) / 'config.json'
            settings.write_text(json.dumps({'projects_dir': str(root)}), encoding='utf-8')
            seen = []
            def execute(cfg, **kwargs):
                seen.append(cfg['projects_dir'])
                pending = [p.name for p in store.pending(cfg['projects_dir'])]
                self.assertIn(kwargs['item_ids'][0], pending)
                # Output is still assigned to the requested project.
                book = run.Book(cfg, store.item_dir(root, kwargs['item_ids'][0]))
                self.assertEqual(projects.run_root(Path(cfg['projects_dir']), book.item),
                                 projects.require(root, project['id']))
                return [{'ok': True}]
            with mock.patch.object(config, 'CONFIG_FILE', settings), \
                    mock.patch.dict(os.environ, {'CALFORGE_PROJECT_ID': project['id']}), \
                    mock.patch.object(run, 'run_queue', side_effect=execute), self.assertRaises(SystemExit) as exit:
                cli.main(['clone-run', '--item', rows[0]['id']])
            self.assertEqual(exit.exception.code, 0)
            self.assertEqual(seen, [str(root.resolve())])

    def test_task_manager_does_not_send_project_root_override_for_clone(self):
        targets = []
        manager = server.TaskManager()
        def thread(*, target, **kwargs):
            targets.append(target)
            return mock.Mock()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(server.config, 'load', return_value={'projects_dir': tmp}), \
                mock.patch.object(server.threading, 'Thread', side_effect=thread), \
                mock.patch.object(server.subprocess, 'Popen', return_value=mock.Mock(stdout=[], returncode=0)) as launch:
            manager.start_task(['clone-run', '--item', 'abcdef'], 'clone', 'clone', {'project_id': 'project'})
            targets[-1]()
            self.assertNotIn('CALFORGE_PROJECT_ID', launch.call_args.kwargs['env'])
            manager.start_task(['run', 'cats'], 'idea', 'run', {'project_id': 'project'})
            targets[-1]()
            self.assertEqual(launch.call_args.kwargs['env']['CALFORGE_PROJECT_ID'], 'project')

    def test_wrong_queue_root_fails_clearly_instead_of_saying_empty_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'abcdef'):
                run.run_queue({'projects_dir': tmp}, item_ids=['abcdef'], on_event=lambda _: None)
