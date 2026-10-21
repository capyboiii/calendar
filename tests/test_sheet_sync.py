import hashlib
import hmac
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from calforge import cli, layout
from calforge.publish import calendaria_csv, guard, r2, sheets, shop_csv
from calforge.ui import server
from tests.test_shop_csv import FakeS3, make_book
from tests.test_publish_errors import CFG_R2, FlakyS3

SETTINGS = {"endpoint": "https://script.google.com/macros/s/test/exec", "secret": "x" * 40}


class SheetSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.book = make_book(self.root, "cats", "Cat Days")
        self.cfg = {"projects_dir": str(self.root), "r2": dict(CFG_R2), "sheets": dict(SETTINGS)}
        self.s3 = FakeS3()
        self.logs = []
        patcher = mock.patch.object(r2, "client", return_value=self.s3)
        patcher.start(); self.addCleanup(patcher.stop)

    def run_publish(self, module=calendaria_csv, only=None):
        return module.publish_all(self.cfg, on_event=self.logs.append, only=only)

    def test_both_buttons_sync_same_canonical_rows_and_paper(self):
        for module in (calendaria_csv, shop_csv):
            with self.subTest(module=module.__name__):
                r2.state_file(self.book).unlink(missing_ok=True)
                with mock.patch.object(sheets, "send") as send:
                    result = self.run_publish(module)
                rows = send.call_args.args[0]
                self.assertEqual(len(rows), 5)
                self.assertEqual(sheets.HEADER, ['SKU', 'Description', 'Tags', 'Title', 'Sizes', 'Paper', 'Design', 'Mockup'])
                self.assertEqual([row[0].rsplit('-', 1)[-1] for row in rows[1:]], ['11SM','11SG','14SM','14SG'])
                self.assertIn('- Paper: Matte or Glossy', rows[0][1])
                self.assertNotIn('<p>', rows[0][1])
                self.assertTrue(rows[0][3].startswith('Cat Days'))
                self.assertEqual(rows[0][4:7], ['', '', ''])
                self.assertEqual(rows[0][7].splitlines(), [f['url'] for n, f in sorted(r2.read_state(self.book)['files'].items())
                                                           if '/' not in n and n.endswith('.jpg')])
                self.assertTrue(rows[0][7])                                       # Mockup: link preview trên R2
                self.assertEqual({row[7] for row in rows[1:]}, {''})
                self.assertEqual([row[5] for row in rows[1:]], ['Matte','Glossy','Matte','Glossy'])
                self.assertEqual(rows[1][1:4], ['', '', ''])
                self.assertEqual(rows[1][4], '11 x 8.5')
                self.assertEqual(rows[3][4], '14 x 11.5')
                for row in rows[1:]:
                    self.assertEqual([url.rsplit('/',1)[-1] for url in row[6].splitlines()],
                                     [name+'.png' for name in r2.PAGE_ORDER])
                self.assertEqual(rows[1][6], rows[2][6])
                self.assertEqual(rows[3][6], rows[4][6])
                self.assertNotEqual(rows[1][6], rows[3][6])
                self.assertEqual(result['sheet']['synced'], ['Cat Days'])
                self.assertFalse(r2.read_state(self.book)['sheet_pending'])

    def test_printify_export_blocks_crayon_before_any_r2_call(self):
        with mock.patch.object(sheets, 'send'):
            self.run_publish(shop_csv)
        before = r2.state_file(self.book).read_bytes()
        for only in (None, [self.book]):
            with mock.patch.object(r2, 'client') as client, mock.patch.object(sheets, 'send') as send:
                result = self.run_publish(only=only)
            self.assertEqual(result['skipped'], ['Cat Days'])
            self.assertIsNone(result['csv'])
            client.assert_not_called(); send.assert_not_called()
            self.assertEqual(r2.state_file(self.book).read_bytes(), before)

    def test_mixed_selection_skips_printify_and_syncs_new(self):
        r2.write_state(self.book, {'exported_at':'old'})
        dog = make_book(self.root, 'dogs', 'Dog Days')
        with mock.patch.object(sheets, 'send') as send:
            result = self.run_publish(only=[self.book, dog])
        self.assertEqual(result['exported'], ['Dog Days'])
        self.assertEqual(result['skipped'], ['Cat Days'])
        self.assertEqual(send.call_count, 1)
        self.assertTrue(all('/dogs/' in key for key in self.s3.keys))

    def test_sheet_failure_retry_does_not_upload_or_export_again(self):
        with mock.patch.object(sheets, 'send', side_effect=sheets.SheetError('Sheet tạm lỗi')):
            result = self.run_publish()
        self.assertTrue(Path(result['csv']).is_file())
        self.assertTrue(r2.read_state(self.book)['calendaria_exported_at'])
        self.assertTrue(r2.read_state(self.book)['sheet_pending'])
        count = len(self.s3.keys)
        with mock.patch.object(sheets, 'send') as send:
            retry = self.run_publish()
        self.assertIsNone(retry['csv']); self.assertEqual(len(self.s3.keys), count)
        send.assert_called_once()
        self.assertFalse(r2.read_state(self.book)['sheet_pending'])
        with mock.patch.object(sheets, 'send') as send:
            self.run_publish()
        send.assert_not_called()

    def test_changed_listing_and_endpoint_resync(self):
        with mock.patch.object(sheets, 'send'):
            self.run_publish()
        listing = json.loads(layout.listing_file(self.book).read_text())
        listing['title'] = 'Updated title'
        layout.listing_file(self.book).write_text(json.dumps(listing))
        with mock.patch.object(sheets, 'send') as send:
            self.run_publish(); self.assertEqual(send.call_count, 1)
        self.cfg['sheets']['endpoint'] = SETTINGS['endpoint'].replace('/test/', '/other/')
        with mock.patch.object(sheets, 'send') as send:
            self.run_publish(); self.assertEqual(send.call_count, 1)

    def test_partial_upload_never_syncs_or_marks_csv(self):
        with mock.patch.object(r2, 'client', return_value=FlakyS3(fail_on='m07')), mock.patch.object(sheets, 'send') as send:
            result = self.run_publish()
        send.assert_not_called()
        self.assertIsNone(result['csv'])
        self.assertNotIn('calendaria_exported_at', r2.read_state(self.book))

    def test_missing_config_pending_then_connect_and_recover(self):
        self.cfg.pop('sheets')
        with mock.patch.object(sheets, 'send') as send:
            result = self.run_publish()
        send.assert_not_called()
        self.assertTrue(result['sheet']['failed'])
        self.cfg['sheets'] = dict(SETTINGS)
        with mock.patch.object(sheets, 'send') as send:
            self.run_publish()
        send.assert_called_once()

    def test_missing_design_page_rejected(self):
        with mock.patch.object(sheets, 'send'):
            self.run_publish()
        layout.print_dir(self.book, r2.SIZES[0]).joinpath('m02_grid.png').unlink()
        with self.assertRaises(sheets.SheetError): sheets.book_rows(self.book, self.cfg)

    def test_parallel_publish_is_rejected_and_lock_released(self):
        with guard.publish_lock(self.root):
            with self.assertRaises(r2.R2Error): self.run_publish()
        with mock.patch.object(sheets, 'send'):
            self.assertTrue(self.run_publish()['csv'])

    def test_description_paper_not_duplicated(self):
        for original in ('Details\n- Finish: Matte or Glossy\n- Binding: test',
                         'Details\n- Paper: Matte or Glossy\n- Binding: test'):
            text = sheets.description_text({'description_text':original})
            self.assertEqual(text.count('Paper:'), 1)
            self.assertNotIn('Finish:', text)
            self.assertLess(text.index('Paper:'), text.index('Binding:'))

    def test_legacy_console_encoding_does_not_mark_success_pending(self):
        def legacy_console(message):
            message.encode('cp1252')
        with mock.patch.object(sheets, 'send'):
            self.run_publish()
            state = r2.read_state(self.book); state['sheet_pending'] = True; r2.write_state(self.book, state)
            result = sheets.sync_books([self.book], self.cfg, on_event=legacy_console)
        self.assertEqual(result['failed'], [])
        self.assertFalse(r2.read_state(self.book)['sheet_pending'])


class TransportTest(unittest.TestCase):
    rows = [['SKU','body','tag','Title','','','','https://cdn/mockup.jpg'],
            ['SKU-11SM','','','','11','Matte','https://cdn/design','']]

    def test_signed_payload_and_acknowledgement(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'ok':True,'skus':['SKU','SKU-11SM']}).encode()
        opener = mock.Mock(); opener.open.return_value = response
        with mock.patch.object(sheets.urllib.request, 'build_opener', return_value=opener):
            sheets.send(self.rows, SETTINGS)
        request = opener.open.call_args.args[0]
        envelope = json.loads(request.data)
        self.assertEqual(envelope['signature'], hmac.new(SETTINGS['secret'].encode(), envelope['payload'].encode(), hashlib.sha256).hexdigest())
        self.assertNotIn(SETTINGS['secret'], request.data.decode())
        self.assertEqual(json.loads(envelope['payload'])['rows'], self.rows)

    def test_network_retry_bounded_no_secret_in_error(self):
        opener = mock.Mock(); opener.open.side_effect = urllib.error.URLError(SETTINGS['secret'])
        with mock.patch.object(sheets.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(sheets.SheetError) as exc:
                sheets.send(self.rows, SETTINGS, sleep=lambda _: None)
        self.assertEqual(opener.open.call_count, 3)
        self.assertNotIn(SETTINGS['secret'], str(exc.exception))

    def test_invalid_ack_or_html_not_success(self):
        for raw in (b'<html>login</html>', b'{"ok":true,"skus":[]}', b'{"ok":false,"code":"auth"}'):
            response = mock.MagicMock(); response.__enter__.return_value.read.return_value = raw
            opener = mock.Mock(); opener.open.return_value = response
            with mock.patch.object(sheets.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(sheets.SheetError): sheets.send(self.rows, SETTINGS)

    def test_invalid_settings(self):
        for endpoint in ('http://script.google.com/macros/s/x/exec','https://evil.com/exec',
                         'https://script.google.com/macros/s/x/dev'):
            with self.assertRaises(sheets.SheetError):
                sheets.validate_settings({'endpoint':endpoint,'secret':'x'*40})

    def test_busy_receiver_retries_and_succeeds(self):
        opener = mock.Mock()
        def response(data):
            value = mock.MagicMock(); value.__enter__.return_value.read.return_value = json.dumps(data).encode()
            return value
        opener.open.side_effect = [response({'ok':False,'code':'busy'}),
                                  response({'ok':True,'skus':['SKU','SKU-11SM']})]
        with mock.patch.object(sheets.urllib.request, 'build_opener', return_value=opener):
            sheets.send(self.rows, SETTINGS, sleep=lambda _:None)
        self.assertEqual(opener.open.call_count,2)

    def test_redirect_rejects_non_google(self):
        with self.assertRaises(sheets.SheetError):
            sheets._GoogleRedirect().redirect_request(None,None,302,'',{},'https://evil.test/collect')


class SheetSettingsApiTest(unittest.TestCase):
    def test_get_never_returns_sheet_secret(self):
        h = mock.Mock()
        with mock.patch.object(server.config, 'load', return_value={'sheets':SETTINGS}):
            server.StudioHandler._handle_api_get(h, '/api/r2', {})
        result = h._send_json.call_args.args[0]
        self.assertEqual(result['sheets'], {'endpoint':SETTINGS['endpoint'], 'secret_set':True})
        self.assertNotIn(SETTINGS['secret'], json.dumps(result))

    def test_invalid_sheet_settings_do_not_save_r2(self):
        h = mock.Mock(); body = json.dumps({'sheets':{'endpoint':'https://evil.test','secret':'x'*40}}).encode()
        h.headers={'Content-Length':str(len(body))}; h.rfile=io.BytesIO(body)
        with mock.patch.object(server.config, 'load', return_value={}), mock.patch.object(server.config, 'save_section') as save:
            server.StudioHandler._handle_api_post(h, '/api/r2')
        save.assert_not_called()
        self.assertEqual(h._send_json.call_args.kwargs['status'], 400)

    def test_cli_reports_pending_sheet_as_failed_task(self):
        result={'books':1,'pushed':[],'exported':['x'],'failed':[], 'csv':'saved.csv',
                'sheet':{'synced':[], 'failed':['x pending']}}
        with mock.patch.object(shop_csv, 'publish_all', return_value=result), mock.patch('builtins.print'):
            with self.assertRaises(SystemExit) as exc:
                cli.cmd_shop(type('Args',(),{'format':'printify','book':None})(), {})
        self.assertEqual(exc.exception.code, 1)

    def test_blank_secret_keeps_existing_secret(self):
        h = mock.Mock(); body=json.dumps({'sheets':{'endpoint':SETTINGS['endpoint'],'secret':''}}).encode()
        h.headers={'Content-Length':str(len(body))}; h.rfile=io.BytesIO(body)
        with mock.patch.object(server.config,'load',return_value={'sheets':SETTINGS}), \
                mock.patch.object(server.config,'save_section') as save:
            server.StudioHandler._handle_api_post(h,'/api/r2')
        self.assertEqual(save.call_args_list[-1].args, ('sheets',{'endpoint':SETTINGS['endpoint']}))
