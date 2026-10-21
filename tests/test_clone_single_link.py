import io
import json
import unittest
from unittest import mock
from calforge.clone.fetch import single_link
from calforge.ui import server

URL='https://www.etsy.com/listing/123/example?ref=shop_home'
class SingleCloneLinkTest(unittest.TestCase):
    def test_single_url_and_surrounding_whitespace(self):
        self.assertEqual(single_link([' \n'+URL+'\n ']),URL)
        for bad in ([],[URL,URL],[URL,'https://example.com/item'],URL,{},[None],[123],[URL+'\nhttps://example.com/item'],[URL+',https://example.com/item']):
            with self.subTest(bad=bad),self.assertRaises(ValueError):single_link(bad)

    def test_api_rejects_multiple_before_adding_any_book(self):
        for links in ([URL,URL],[URL,'https://example.com/item'],[URL+'\nhttps://example.com/item'],URL,[]):
            h=mock.Mock();data=json.dumps({'links':links}).encode()
            h.headers={'Content-Length':str(len(data))};h.rfile=io.BytesIO(data)
            with self.subTest(links=links),mock.patch.object(server.config,'load',return_value={'projects_dir':'unused'}),mock.patch('calforge.clone.store.add_link_batch') as add:
                server.StudioHandler._api_clone(h,'add')
                add.assert_not_called()
                self.assertEqual(h._send_json.call_args.kwargs['status'],400)

    def test_api_accepts_exactly_one_book_per_request(self):
        h=mock.Mock();data=json.dumps({'links':[URL], 'group': 'Test clone'}).encode()
        h.headers={'Content-Length':str(len(data))};h.rfile=io.BytesIO(data)
        with mock.patch.object(server.config,'load',return_value={'projects_dir':'unused'}),mock.patch.object(server.workspaces,'require'),mock.patch('calforge.clone.store.add_link_batch', autospec=True) as add,mock.patch.object(server,'_clone_items',return_value={}),mock.patch.object(server,'_enqueue_clones'):
            server.StudioHandler._api_clone(h,'add')
            self.assertEqual(add.call_count,1)
            self.assertEqual(add.call_args.args[1],URL)
