import io,json,tempfile,unittest
from pathlib import Path
from unittest import mock
from calforge import layout
from calforge.ui import server
from tests import fixtures

class CloneReviewTest(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name);self.book=self.root/'projects'/'demo'
        layout.ensure_system(self.book)
        self.concept=fixtures.concept();self.concept.update(source='clone',source_url='https://example.com/product')
        layout.concept_file(self.book).write_text(json.dumps(self.concept),encoding='utf-8')
        p=mock.patch.object(server.config,'load',return_value={'projects_dir':str(self.root/'projects')});p.start();self.addCleanup(p.stop)
    def request(self,value,path=None):
        h=mock.Mock();data=json.dumps({'path':str(path or self.book),'reviewed':value}).encode()
        h.headers={'Content-Length':str(len(data))};h.rfile=io.BytesIO(data)
        server.StudioHandler._handle_api_post(h,'/api/book/review')
        return h._send_json.call_args
    def test_checked_unchecked_persist_without_touching_render_inputs(self):
        original=layout.concept_file(self.book).read_bytes();mtime=layout.concept_file(self.book).stat().st_mtime_ns
        self.assertTrue(self.request(True).args[0]['ok'])
        self.assertTrue(server._clone_book_info(self.book,self.concept)['reviewed'])
        self.assertFalse(self.request(False).args[0]['reviewed'])
        self.assertFalse(server._clone_book_info(self.book,self.concept)['reviewed'])
        self.assertEqual(layout.concept_file(self.book).read_bytes(),original)
        self.assertEqual(layout.concept_file(self.book).stat().st_mtime_ns,mtime)
    def test_rejects_outside_project_and_non_boolean(self):
        self.assertEqual(self.request(True,self.root).kwargs['status'],400)
        for value in ('true',1,None):self.assertEqual(self.request(value).kwargs['status'],400)
    def test_idea_book_can_check_uncheck_without_clone_url(self):
        self.concept['source']='idea';layout.concept_file(self.book).write_text(json.dumps(self.concept))
        self.assertEqual(server._clone_book_info(self.book,self.concept),{'reviewed':False})
        self.assertTrue(self.request(True).args[0]['ok'])
        self.assertEqual(server._clone_book_info(self.book,self.concept),{'reviewed':True})
        self.assertFalse(self.request(False).args[0]['reviewed'])
    def test_legacy_clone_url_loaded_from_original_queue(self):
        c={'source':'clone','angle_id':'clone-123456'}
        with mock.patch('calforge.clone.store.read',return_value={'source_url':'https://example.com/legacy'}):
            self.assertEqual(server._clone_book_info(self.book,c)['source_url'],'https://example.com/legacy')
