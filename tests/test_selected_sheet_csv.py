import csv
import io
import json
import unittest
import urllib.error
from unittest import mock

from calforge.publish import selected_sheet_csv as mod
from calforge.ui.server import StudioHandler


def catalog():
    rows = [list(mod.REQUIRED)]
    for base in ('WCB-AA-12345', 'WCB-AB-12345'):
        rows.append([base, 'Description\nPaper: Matte or Glossy', 'tag1, tag2', 'Title "quoted"', '', '', '',
                     f'https://cdn.example/{base}/1.jpg\nhttps://cdn.example/{base}/2.jpg'])
        for suffix, paper in [('11SM', 'Matte'), ('11SG', 'Glossy'), ('14SM', 'Matte'), ('14SG', 'Glossy')]:
            rows.append([base+'-'+suffix, '', '', '', '11 x 8.5' if suffix.startswith('11') else '14 x 11.5',
                         paper, 'https://cdn.example/front.png\nhttps://cdn.example/back.png', ''])
    stream=io.StringIO(newline='');csv.writer(stream).writerows(rows)
    return stream.getvalue(), rows


class SelectedCsvTest(unittest.TestCase):
    def test_exact_base_includes_all_variants_preserves_multiline_and_header(self):
        text, original = catalog()
        result = mod.export_selected('\ufeffwcb-aa-12345\r\nWCB-AA-12345\n',sheet_csv=text)
        rows=list(csv.reader(io.StringIO(result['csv'].lstrip('\ufeff'),newline='')))
        self.assertEqual(rows,[original[0],*original[1:6]])
        self.assertEqual(result['products'],1);self.assertEqual(result['rows'],5)
        self.assertTrue(result['csv'].startswith('\ufeff'))

    def test_sheet_order_and_repeated_selection(self):
        text,rows=catalog()
        result=mod.export_selected('WCB-AB-12345\nWCB-AA-12345\nWCB-AB-12345',sheet_csv=text)
        self.assertEqual(list(csv.reader(io.StringIO(result['csv'].lstrip('\ufeff')))),rows)
        self.assertEqual(result['products'],2)

    def test_missing_or_variant_sku_aborts_instead_of_silently_omitting(self):
        for sku in ('WCB-UNKNOWN-12345','WCB-AA-12345-11SM','WCB-AA-123'):
            with self.subTest(sku=sku),self.assertRaisesRegex(mod.SelectionError,'SKU chung'):
                mod.export_selected('WCB-AA-12345\n'+sku,sheet_csv=catalog()[0])

    def test_invalid_input_never_fetches_sheet(self):
        for text in ('','\ufeff \n','1. WCB-AA-12345','WCB-AA-12345,WCB-AB-12345',None,'x'*200001):
            with self.subTest(text=str(text)[:20]),mock.patch.object(mod,'read_sheet') as fetch:
                with self.assertRaises(mod.SelectionError):mod.export_selected(text)
                fetch.assert_not_called()

    def test_wrong_schema_and_malformed_sheet(self):
        for text in ('<html>Sign in</html>','SKU,Title\na,b','SKU,SKU\na,b','"unclosed'):
            with self.subTest(text=text),self.assertRaises(mod.SelectionError):
                mod.export_selected('WCB-AA-12345',sheet_csv=text)

    def test_duplicate_selected_sku_is_rejected(self):
        text,rows=catalog()
        extra=io.StringIO(newline='');csv.writer(extra).writerow(rows[1])
        with self.assertRaisesRegex(mod.SelectionError,'trùng'):
            mod.export_selected('WCB-AA-12345',sheet_csv=text+extra.getvalue())

    def test_network_retry_then_success(self):
        response=mock.MagicMock();response.__enter__.return_value.read.return_value=catalog()[0].encode()
        with mock.patch.object(mod.urllib.request,'urlopen',side_effect=[urllib.error.URLError('offline'),response]) as fetch:
            wait=mock.Mock();self.assertEqual(mod.read_sheet(sleep=wait),catalog()[0]);self.assertEqual(fetch.call_count,2)
            wait.assert_called_once_with(1)

    def test_permission_and_network_failure_are_actionable(self):
        for error in (urllib.error.HTTPError('url',403,'Forbidden',{},None),urllib.error.URLError('offline')):
            with mock.patch.object(mod.urllib.request,'urlopen',side_effect=error):
                with self.assertRaises(mod.SelectionError):mod.read_sheet(sleep=lambda _:None)

    def api(self,body):
        handler=object.__new__(StudioHandler)
        raw=json.dumps(body).encode();handler.headers={'Content-Length':str(len(raw))};handler.rfile=io.BytesIO(raw)
        handler._send_json=lambda data,**kw:(data,kw)
        return handler._handle_api_post('/api/sheet/export-selected')

    def test_api_success_and_bad_input(self):
        with mock.patch.object(mod,'read_sheet',return_value=catalog()[0]):
            data,_=self.api({'text':'WCB-AA-12345'})
            self.assertEqual(data['products'],1);self.assertEqual(data['rows'],5)
            data,status=self.api({'text':''})
            self.assertIn('error',data);self.assertEqual(status['status'],400)


if __name__=='__main__':unittest.main()
