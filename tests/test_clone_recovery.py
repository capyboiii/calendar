import copy
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from calforge.clone import fetch, run, session, store
from tests.test_clone import new_item, distinct, accts

class RecoveryTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.cfg,self.d=new_item(self.root)
        self.b=run.Book(self.cfg,self.d,on_event=lambda *_:None)

    def test_finish_retries_transients_but_not_code_errors(self):
        from calforge import pipeline
        for error in (MemoryError(),PermissionError('locked'),TimeoutError('slow')):
            with self.subTest(error=error), mock.patch.object(self.b,'_finish_attempt',side_effect=[error,{'ok':True}]) as work, mock.patch.object(pipeline.time,'sleep') as sleep:
                self.assertTrue(self.b.finish([])['ok']);self.assertEqual(work.call_count,2)
                sleep.assert_called_once_with(30)
        with mock.patch.object(self.b,'_finish_attempt',side_effect=MemoryError()),mock.patch.object(pipeline.time,'sleep') as sleep:
            self.assertFalse(self.b.finish([])['ok']);self.assertEqual([c.args[0] for c in sleep.call_args_list],[30,90])
        with mock.patch.object(self.b,'_finish_attempt',side_effect=KeyError('bad')) as work,mock.patch.object(pipeline.time,'sleep') as sleep:
            self.assertFalse(self.b.finish([])['ok']);self.assertEqual(work.call_count,1);sleep.assert_not_called()

    def test_stop_interrupts_postproduction_retry(self):
        self.b.stop=threading.Event()
        def work(_):self.b.stop.set();raise TimeoutError('slow')
        with mock.patch.object(self.b,'_finish_attempt',side_effect=work) as attempt:
            self.assertEqual(self.b.finish([])['stage'],'stopped');self.assertEqual(attempt.call_count,1)

    def test_refs_failure_keeps_previous_generation_and_retry_publishes_all(self):
        images=list(zip(['a.png','b.png'],distinct(2)))
        fetch.save_refs(self.d,images)
        old=store.read(self.d)['refs_dir'];before=[p.read_bytes() for p in store.refs(self.d)]
        real=Path.write_bytes
        def fail(path,data):
            if path.name=='ref02.png':raise PermissionError('locked')
            return real(path,data)
        with mock.patch.object(Path,'write_bytes',fail),self.assertRaises(PermissionError):fetch.save_refs(self.d,list(zip(['a.png','b.png'],distinct(2,30))))
        self.assertEqual(store.read(self.d)['refs_dir'],old)
        self.assertEqual([p.read_bytes() for p in store.refs(self.d)],before)
        fetch.save_refs(self.d,list(zip(['a.png','b.png'],distinct(2,30))))
        self.assertNotEqual(store.read(self.d)['refs_dir'],old)
        self.assertEqual(len(store.refs(self.d)),2)

    def test_incomplete_legacy_refs_are_refetched(self):
        store.write(self.d,source_url='https://example.com/item',names=[])
        self.b.item=store.read(self.d)
        with mock.patch.object(run,'run_stage') as stage:run.fetch_refs(self.b,None)
        stage.assert_called_once()

    def test_cursor_commits_only_saved_images_and_deduplicates_after_crash(self):
        images=distinct(3)
        self.b.status(art_chat={'account':'acc3','url':'https://chatgpt.com/c/test','saved':0})
        real=session.save
        def fail(data,path):
            if path.name=='m02':raise PermissionError('locked')
            return real(data,path)
        with mock.patch.object(session,'save',side_effect=fail),self.assertRaises(PermissionError):self.b._take_art(session.Turn(images),'acc3')
        self.assertEqual(store.read(self.d)['art_chat']['saved'],1)
        self.assertEqual(self.b.missing('m'),list(range(2,13)))
        self.b._take_art(session.Turn(images[1:]),'acc3')
        self.assertEqual(store.read(self.d)['art_chat']['saved'],3)
        self.b.status(art_chat={'account':'acc3','saved':0})
        self.b._take_art(session.Turn(images),'acc3')
        self.assertEqual(self.b.missing('m'),list(range(4,13)))

    def test_busy_account_wait_times_out_even_without_quota(self):
        a,p=accts(['acc3']);a.max_busy_wait_s=1
        p.acquire=lambda *args,**kw:None;p.wait_change=lambda *_:None
        import itertools
        with mock.patch.object(run.time,'monotonic',side_effect=itertools.count(0,2)),self.assertRaisesRegex(run.StageFailed,'đang bận'):
            a.acquire()

    def test_corrupt_raw_quarantined_and_valid_raw_unchanged(self):
        self.b.raw('m01').parent.mkdir(parents=True,exist_ok=True)
        self.b.raw('m01').with_suffix('.png').write_bytes(b'not a PNG')
        good=session.save(distinct(1)[0],self.b.raw('m02'))
        self.assertIsNone(self.b.done('m01'))
        self.assertTrue(list(good.parent.glob('m01.*.bad')))
        self.assertEqual(self.b.done('m02'),good)
        good.write_bytes(b'truncated')
        self.assertIsNone(self.b.done('m02'))

    def test_failed_image_write_preserves_existing_image(self):
        path=session.save(distinct(1)[0],self.b.raw('m01'));old=path.read_bytes()
        with mock.patch.object(Path,'write_bytes',side_effect=PermissionError('locked')),self.assertRaises(PermissionError):
            session.save(distinct(1,40)[0],self.b.raw('m01'))
        self.assertEqual(path.read_bytes(),old)

    def test_actual_postproduction_retries_upscale_and_render_without_image_generation(self):
        from calforge import pipeline
        session.save(distinct(1)[0],self.b.raw('cover'))
        for failing in ('upscale','render'):
            with self.subTest(failing=failing), mock.patch.object(run,'repair_month_captions'), mock.patch.object(pipeline.time,'sleep') as sleep, mock.patch.object(pipeline,'upscale_concept',side_effect=[MemoryError(),[]] if failing=='upscale' else [[],[]]) as upscale, mock.patch.object(pipeline,'finish_book',side_effect=[TimeoutError(),{'ok':True}] if failing=='render' else [{'ok':True}]) as render:
                self.assertTrue(self.b.finish([])['ok'])
                self.assertEqual(upscale.call_count,2)
                self.assertEqual(render.call_count,1 if failing=='upscale' else 2)
                sleep.assert_called_once_with(30)

    def test_complete_refs_not_published_when_metadata_commit_fails(self):
        old=store.refs(self.d)
        with mock.patch.object(store,'write',side_effect=PermissionError('locked')),self.assertRaises(PermissionError):
            fetch.save_refs(self.d,list(zip(['a.png','b.png'],distinct(2))))
        self.assertEqual(store.refs(self.d),old)

    def test_corrupt_published_refs_are_fetched_again(self):
        fetch.save_refs(self.d,list(zip(['a.png','b.png'],distinct(2))))
        store.write(self.d,source_url='https://example.com/item')
        store.refs(self.d)[0].write_bytes(b'broken')
        self.b.item=store.read(self.d)
        with mock.patch.object(run,'run_stage') as stage:run.fetch_refs(self.b,None)
        stage.assert_called_once()
