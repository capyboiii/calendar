import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from calforge import config
from tools import package

SHEETS = {'endpoint': 'https://script.google.com/macros/s/test-deployment/exec', 'secret': 's' * 48}
R2 = dict(account_id='account', access_key_id='access', secret_access_key='test-secret', bucket='test', public_url='https://example.com')


class PackageSheetTest(unittest.TestCase):
    def test_bundle_includes_only_r2_and_sheet_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'; source.mkdir()
            app = Path(tmp) / 'app'; app.mkdir()
            (source/'calforge.json').write_text(json.dumps(dict(r2=R2, sheets=SHEETS,
                printify={'token':'private-token'}, profiles_dir='private-profiles', projects_dir='private-projects')))
            with mock.patch.object(package, 'ROOT', source), contextlib.redirect_stdout(io.StringIO()):
                package._bundle_r2(app)
            self.assertEqual(json.loads((app/'calforge.json').read_text()), {'r2':R2})
            self.assertEqual(json.loads((app/'data/sheet_sync_defaults.json').read_text()), SHEETS)
            self.assertFalse((app/'private-profiles').exists())

    def test_bundle_rejects_missing_sheet_instead_of_silently_shipping_unsynced_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'calforge.json').write_text(json.dumps({'r2':R2}))
            with mock.patch.object(package,'ROOT',root), self.assertRaisesRegex(SystemExit,'Sheet'):
                package._bundle_r2(root)

    def load_at(self, root):
        with mock.patch.object(config,'ROOT',root), mock.patch.object(config,'CONFIG_FILE',root/'calforge.json'), \
                mock.patch.dict('os.environ',{'CALFORGE_PROJECT_ID':''}):
            return config.load()

    def test_new_install_and_upgrade_use_bundled_sheet_without_rewriting_user_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/sheet_sync_defaults.json').write_text(json.dumps(SHEETS))
            for user in ({'r2':R2}, {'r2':R2, 'sheets':{'endpoint':'','secret':''}, 'projects_dir':'other-drive'}):
                with self.subTest(user=user):
                    text=json.dumps(user);(root/'calforge.json').write_text(text)
                    loaded=self.load_at(root)
                    self.assertEqual(loaded['sheets'],SHEETS)
                    self.assertEqual(loaded['r2'],R2)
                    self.assertEqual((root/'calforge.json').read_text(),text)

    def test_custom_or_partial_connection_is_not_mixed_with_bundled_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir()
            (root/'data/sheet_sync_defaults.json').write_text(json.dumps(SHEETS))
            for custom in ({'endpoint':'https://example.com/custom','secret':'custom-key'}, {'endpoint':'https://example.com/custom'}):
                (root/'calforge.json').write_text(json.dumps({'sheets':custom}))
                self.assertEqual(self.load_at(root)['sheets'],custom)

    def test_generic_package_excludes_secret_fallback_file(self):
        self.assertIn('data/sheet_sync_defaults.json',package.NEVER_FILES)


if __name__ == '__main__':
    unittest.main()
