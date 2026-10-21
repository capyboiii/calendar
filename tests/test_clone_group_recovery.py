import tempfile
import unittest
from pathlib import Path
from unittest import mock
from PIL import Image
from calforge.clone import expand, fetch, store
from calforge.clone.run import StageFailed
from calforge.render import mockups
from tests.test_clone_single_session import SingleSessionTest, Planner
from tests.test_clone_expand import image


class RecoveryTest(unittest.TestCase):
    def test_scheduler_reclaims_recovered_child_without_duplicate_result(self):
        from types import SimpleNamespace
        from calforge.clone import run
        with tempfile.TemporaryDirectory() as tmp:
            books,source=SingleSessionTest().setup_books(tmp)
            first=books[0].d.name
            calls=[]
            def work(cfg,d,accts,plus,stop,on_event,*,step,**kwargs):
                calls.append((d.name,step))
                if d.name==first and step=='art' and calls.count((first,'art'))==1:
                    reason='nguồn: chưa xong sau 4 phiên'
                    store.write(d,status='failed',stage='lấy ảnh nguồn dùng chung',reason=reason)
                    return {'ok':False,'status':'failed','reason':reason}
                if step=='art':
                    store.write(source,plan_ready=True)
                    expand.recover_preparation_children(cfg,source)
                    return {'next':'grid'}
                if step=='grid':return {'next':'finish'}
                store.write(d,status='done',reason='')
                return {'ok':True}
            accts=SimpleNamespace(pool=mock.Mock())
            with mock.patch.object(run,'run_book',side_effect=work):
                results=run.run_queue({'projects_dir':tmp},on_event=lambda _:None,accts=accts,plus=['acc1'])
            self.assertEqual(len(results),2)
            self.assertTrue(all(r['ok'] for r in results), (results,calls,[store.read(b.d) for b in books]))
            self.assertEqual(calls.count((first,'art')),2)
            self.assertTrue(all(store.read(b.d)['status']=='done' for b in books))

    def test_sibling_finishes_plan_and_revives_only_source_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            books,d=SingleSessionTest().setup_books(tmp)
            store.write(books[0].d,status='failed',stage='lấy ảnh nguồn dùng chung',
                        reason='lấy ảnh: chưa xong sau 4 phiên')
            def fetcher(b,s,name):fetch.save_refs(b.d,[('1.png',image(1))])
            def stage(accts,label,work,**kw):
                if 'lấy ảnh nguồn' in label:
                    self.assertNotIn('only',kw)
                    work(Planner(),'acc2')
                else:
                    work(Planner(),'acc3')
            with mock.patch('calforge.clone.run.run_stage',side_effect=stage),mock.patch.object(fetch,'fetch_work',side_effect=fetcher):
                expand.prepare(books[1],None)
            self.assertTrue(store.read(d)['plan_ready'])
            self.assertEqual({v['account'] for v in store.read(d)['artwork_planners'].values()}, {'acc3'})
            self.assertEqual(len(store.read(d)['completion_plan']),24)
            recovered=store.read(books[0].d)
            self.assertEqual(recovered['status'],'pending')
            self.assertTrue(recovered['preparation_recovered'])
            self.assertFalse(recovered['reason'])
            store.write(books[0].d,status='failed',stage='mockup',reason='different error')
            expand.recover_preparation_children(books[0].cfg,d)
            self.assertEqual(store.read(books[0].d)['stage'],'mockup')

    def test_unicode_mockup_reader_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'Tiếng Việt ™ & hens.png'
            Image.new('RGB',(40,30),'red').save(p)
            im=mockups.read_image(p)
            self.assertEqual(im.shape,(30,40,3))
            self.assertEqual(tuple(im[0,0]),(0,0,255))
            out=p.with_name('Ảnh xuất ™.png')
            mockups.write_image(out,im)
            self.assertEqual(mockups.read_image(out).shape,im.shape)
            self.assertIsNone(mockups.read_image(p.with_name('missing.png')))
