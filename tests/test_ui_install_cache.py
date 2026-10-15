import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from calforge.ui import cache, server


class UIInstallCacheTest(unittest.TestCase):
    def test_reinstall_changes_ui_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=cache.mark_installed(root)
            self.assertEqual(cache.install_id(root),first)
            second=cache.mark_installed(root)
            self.assertNotEqual(first,second)
            self.assertEqual(cache.install_id(root),second)

    def test_index_clears_only_cache_and_versions_assets_by_content_and_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);static=root/'static';static.mkdir()
            (static/'index.html').write_text('<script src="app.js"></script>',encoding='utf-8')
            asset=static/'app.js';asset.write_text('version one',encoding='utf-8')
            original_time=asset.stat().st_mtime
            cache.mark_installed(root)
            def index():
                h=mock.Mock();h.wfile=io.BytesIO()
                with mock.patch.object(server,'ROOT',root),mock.patch.object(server,'STATIC_DIR',static):
                    server.StudioHandler._serve_index(h)
                headers=dict(call.args for call in h.send_header.call_args_list)
                self.assertNotIn('Clear-Site-Data',headers)
                self.assertEqual(headers['Cache-Control'],'no-store')
                return h.wfile.getvalue()
            first=index()
            asset.write_text('version two',encoding='utf-8')
            os.utime(asset,(original_time,original_time))
            second=index()
            self.assertNotEqual(first,second)
            cache.mark_installed(root)
            self.assertNotEqual(second,index())

    def test_only_ui_cache_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('Cache','Code Cache','GPUCache','Local Storage'):
                d=root/cache.UI_PROFILE/'Default'/name;d.mkdir(parents=True)
                (d/'keep-or-cache').write_text('data')
            cookies=root/cache.UI_PROFILE/'Default'/'Cookies';cookies.write_text('session')
            chat=root/'.chrome-profiles'/'acc1';chat.mkdir(parents=True)
            (chat/'Cookies').write_text('chatgpt session')
            self.assertEqual(set(cache.clear_ui_cache(root)),{'Cache','Code Cache','GPUCache'})
            self.assertEqual(cookies.read_text(),'session')
            self.assertTrue((cookies.parent/'Local Storage'/'keep-or-cache').exists())
            self.assertEqual((chat/'Cookies').read_text(),'chatgpt session')


if __name__=='__main__':unittest.main()
