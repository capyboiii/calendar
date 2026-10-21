import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from calforge.clone import expand, fetch, session, store
from calforge.clone.run import Book, PoolWaiting
from calforge.imagegen.driver import TempError

URL = "https://www.etsy.com/listing/1234567/example"


def image(index):
    out = io.BytesIO()
    Image.new("RGB", (1200, 900), (index, 80, 120)).save(out, "PNG")
    return out.getvalue()


class ExpansionTest(unittest.TestCase):
    def setUp(self):
        # Existing fixtures exercise the previously shipped planner and resume path.
        original = store.add_link_batch
        def legacy(*args, **kw):
            items = original(*args, **kw)
            d = store.item_dir(args[0], items[0]['id'])
            store.write(store.source_dir(d), planning_mode='legacy')
            return items
        patcher = mock.patch.object(store, 'add_link_batch', side_effect=legacy)
        patcher.start()
        self.addCleanup(patcher.stop)
    def test_all_count_combinations(self):
        for k in range(1, 13):
            for n in range(1, 6):
                with self.subTest(k=k, n=n):
                    jobs = expand.assignments(k, n)
                    self.assertEqual(len(jobs), n * (12-k))
                    self.assertEqual(len({j['id'] for j in jobs}), len(jobs))
                    for book in range(1, n+1):
                        self.assertEqual([j['artwork_index'] for j in jobs if j['book_index'] == book], list(range(k+1, 13)))
        for k, n in [(0, 1), (13, 1), (10, 0), (10, 6)]:
            with self.assertRaises(ValueError):
                expand.assignments(k, n)

    def test_count_validation_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            for count in (0, 6, -1, True, 1.5, '2', None):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    store.add_link_batch(tmp, URL, book_count=count)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_group_commit_recovery_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(store, '_publish_group', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    store.add_link_batch(tmp, URL, book_count=5)
            children = store.items(tmp)
            self.assertEqual(len(children), 5)
            self.assertEqual(len({i['source_group'] for i in children}), 1)
            store.remove(tmp, children[0]['id'], running_now=False)
            self.assertEqual(len(store.items(tmp)), 4)
            self.assertEqual(len(store.pending(tmp)), 4)

    def test_shared_prepare_once_and_resume(self):
        for k in (1, 10, 11, 12):
            with self.subTest(k=k), tempfile.TemporaryDirectory() as tmp:
                children = store.add_link_batch(tmp, URL, book_count=3)
                for child in children:
                    store.write(store.item_dir(tmp, child['id']), kind='source_expand')
                calls = []
                plan_calls = []
                def fetch_work(b, s, name):
                    calls.append(name)
                    fetch.save_refs(b.d, [(f'{i}.png', image(i)) for i in range(1, k+1)])
                class Planner:
                    def attach(self, refs):
                        self.refs = refs
                    def ask_text(self, prompt):
                        import json
                        if 'Assignments:\n' not in prompt:
                            return 'Acknowledged.'
                        jobs = json.loads(prompt.split('Assignments:\n')[-1])
                        plan_calls.append(jobs)
                        return json.dumps({'artworks': [{'id': j['id'], 'prompt': ('A distinct detailed artwork scene with the same reference identity and palette. ' + j['id'])} for j in jobs]})
                def stage(accts, label, work, **kw):
                    work(Planner(), 'acc1')
                    return 'acc1'
                cfg = {'projects_dir': tmp}
                with mock.patch('calforge.clone.run.run_stage', side_effect=stage), mock.patch.object(fetch, 'fetch_work', side_effect=fetch_work):
                    for item in children:
                        b = Book(cfg, store.item_dir(tmp, item['id']), lambda _: None)
                        expand.prepare(b, None)
                        expand.prepare(b, None)
                        self.assertEqual(b.missing('m'), list(range(k+1, 13)))
                        self.assertEqual(b.done('m01').read_bytes(), image(1))
                self.assertEqual(len(calls), 1)
                self.assertEqual(sum(map(len, plan_calls)), 3*(12-k))

    def test_nonblocking_group_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with expand.group_lock(Path(tmp)):
                with self.assertRaises(PoolWaiting):
                    with expand.group_lock(Path(tmp)):
                        self.fail('lock was acquired twice')
            with expand.group_lock(Path(tmp)):
                pass

    def test_plan_rejects_wrong_duplicate_or_empty_assignments(self):
        jobs = expand.assignments(10, 1)
        for rows in ([], [{'id': 'wrong', 'prompt': 'x'*100}]*2,
                     [{'id': jobs[0]['id'], 'prompt': 'x'*100}]*2,
                     [{'id': j['id'], 'prompt': ''} for j in jobs],
                     [{'id': j['id'], 'prompt': 'x'*100} for j in jobs]):
            with self.assertRaises(TempError):
                expand.validate_plan({'artworks': rows}, jobs)

    def test_generate_exact_assignment_and_preserve_saved_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = store.add_link_batch(tmp, URL, book_count=2)[1]
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, item['id']), lambda _: None)
            b.status(kind='source_expand')
            source = store.source_dir(b.d)
            fetch.save_refs(source, [(f'{i}.png', image(i)) for i in range(1, 11)])
            store.write(source, completion_plan={'b02m11': 'eleven', 'b02m12': 'twelve'})
            for m in range(1, 12):
                session.save(image(m), b.raw(f'm{m:02d}'))
            s = mock.Mock()
            s.ask_images.return_value = session.Turn([image(90), image(91)])
            expand.generate(b, s, 'acc2')
            s.ask_images.assert_called_once()
            self.assertIn('twelve', s.ask_images.call_args.args[0])
            self.assertEqual(b.done('m11').read_bytes(), image(11))
            self.assertEqual(b.done('m12').read_bytes(), image(90))
            expand.generate(b, s, 'acc2')
            self.assertEqual(s.ask_images.call_count, 1)

    def test_interrupted_copy_recovers_without_generating_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = store.add_link_batch(tmp, URL)[0]
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, item['id']), lambda _: None)
            b.status(kind='source_expand')
            source = store.source_dir(b.d)
            fetch.save_refs(source, [(f'{i}.png', image(i)) for i in range(1, 12)])
            store.write(source, completion_plan={'b01m12': 'planned image'})
            for m in range(1, 12):
                session.save(image(m), b.raw(f'm{m:02d}'))
            s = mock.Mock()
            s.ask_images.return_value = session.Turn([image(90)])
            save = session.save
            def fail_child(data, path):
                if path == b.raw('m12'):
                    raise PermissionError('locked child file')
                return save(data, path)
            with mock.patch.object(session, 'save', side_effect=fail_child), self.assertRaises(PermissionError):
                expand.generate(b, s, 'acc1')
            self.assertIsNone(b.done('m12'))
            expand.generate(b, s, 'acc1')
            self.assertEqual(s.ask_images.call_count, 1)
            self.assertEqual(b.done('m12').read_bytes(), image(90))

    def test_corrupt_shared_source_does_not_silently_replace_used_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = store.add_link_batch(tmp, URL)[0]
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, item['id']), lambda _: None)
            source = store.source_dir(b.d)
            fetch.save_refs(source, [('1.png', image(1))])
            store.write(source, source_fingerprint=expand.fingerprint(store.refs(source)))
            store.refs(source)[0].write_bytes(b'broken')
            with mock.patch('calforge.clone.run.run_stage') as stage, self.assertRaises(TempError):
                expand.prepare(b, None)
            stage.assert_not_called()

    def test_new_variants_all_counts(self):
        for k in range(1, 13):
            for n in range(1, 6):
                jobs = expand.variant_assignments(k, n)
                self.assertEqual(len(jobs), n*12)
                self.assertEqual(len({j['id'] for j in jobs}), n*12)
                for job in jobs:
                    m = job['artwork_index']
                    self.assertEqual(job['reference_index'], m if m <= k else 1)

    def test_twelve_sources_still_plan_twenty_four_new_images(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            children = store.add_link_batch(tmp, URL, book_count=2)
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, children[0]['id']), lambda _: None)
            source = store.source_dir(b.d)
            fetch.save_refs(source, [(f'{i}.png', image(i)) for i in range(1, 13)])
            class Planner:
                def attach(self, refs):
                    pass
                def ask_text(self, prompt):
                    if 'Assignments:\n' not in prompt:
                        return 'OK'
                    jobs = json.loads(prompt.split('Assignments:\n')[-1])
                    return json.dumps({'artworks': [{'id': j['id'], 'prompt': 'An entirely new, upright full-bleed composition with distinct action and clothing. '+j['id']} for j in jobs]})
            def stage(accts, label, work, **kw):
                work(Planner(), 'acc1')
            with mock.patch('calforge.clone.run.run_stage', side_effect=stage) as call:
                for child in children:
                    book = Book({'projects_dir': tmp}, store.item_dir(tmp, child['id']), lambda _: None)
                    expand.prepare(book, None)
                    self.assertEqual(book.missing('m'), list(range(1,13)))
                self.assertEqual(call.call_count, 4)
            self.assertEqual(len(store.read(source)['completion_plan']), 24)

    def test_variants_reject_bad_orientation_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = store.add_link_batch(tmp, URL)[0]
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, item['id']), lambda _: None)
            source = store.source_dir(b.d)
            fetch.save_refs(source, [('1.png', image(1)), ('2.png', image(2))])
            store.write(source, completion_plan={'b01m02': 'A new upright scene'})
            s = mock.Mock()
            s.ask_images.side_effect = [session.Turn([image(90)]), session.Turn([image(91)])]
            s.ask_text.side_effect = ['{"upright":false,"artwork_only":false,"distinct":true,"reason":"tilted calendar page"}',
                                     '{"upright":true,"artwork_only":true,"distinct":true}']
            expand.generate(b, s, 'acc1', months=[2])
            self.assertEqual(b.done('m02').read_bytes(), image(91))
            self.assertEqual(s.ask_images.call_args_list[0].kwargs['attach'], [store.refs(source)[1]])
            self.assertIn('tilted calendar page', s.ask_images.call_args_list[1].args[0])
            self.assertIsNone(b.done('m01'))

    def test_batch_parallel_uses_eleven_accounts_without_collisions(self):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            items = store.add_link_batch(tmp, URL, book_count=2)
            books = [Book({'projects_dir': tmp}, store.item_dir(tmp, i['id']), lambda _: None) for i in items]
            accts = SimpleNamespace(names=list(range(11)), _request=threading.local(), pool=mock.Mock())
            slots = threading.Semaphore(11)
            lock = threading.Lock()
            current = peak = 0
            def stage(accts, label, work, **kw):
                nonlocal current, peak
                with slots:
                    with lock:
                        current += 1
                        peak = max(peak, current)
                    try:
                        work(SimpleNamespace(), 'test')
                    finally:
                        with lock:
                            current -= 1
            def generate(b, s, name, *, months, yield_check=None):
                for m in months:
                    time.sleep(.05)
                    session.save(image(m), b.raw(f'm{m:02d}'))
            start = time.monotonic()
            with mock.patch('calforge.clone.run.run_stage', side_effect=stage), mock.patch.object(expand, 'generate', side_effect=generate):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    list(executor.map(lambda b: expand.generate_parallel(b, accts), books))
            elapsed = time.monotonic()-start
            self.assertGreaterEqual(peak, 10)
            self.assertLessEqual(peak, 11)
            self.assertTrue(all(not b.missing('m') for b in books))
            # Relative to serial simulated ChatGPT latency (24 * .05s).
            self.assertLess(elapsed, 1.2)

    def test_variant_worker_yields_only_after_saving_completed_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = store.add_link_batch(tmp, URL)[0]
            b = Book({'projects_dir': tmp}, store.item_dir(tmp, item['id']), lambda _: None)
            source = store.source_dir(b.d)
            fetch.save_refs(source, [('1.png', image(1))])
            store.write(source, completion_plan={'b01m01': 'first new scene', 'b01m02': 'second new scene'})
            s = mock.Mock()
            s.ask_images.return_value = session.Turn([image(90)])
            s.ask_text.return_value = '{"upright":true,"artwork_only":true,"distinct":true}'
            with self.assertRaises(PoolWaiting):
                expand.generate(b, s, 'acc1', months=[1,2], yield_check=lambda: True)
            self.assertEqual(b.done('m01').read_bytes(), image(90))
            self.assertIsNone(b.done('m02'))
            s.ask_images.assert_called_once()

    def test_verification_error_resumes_candidate_without_regenerating(self):
        with tempfile.TemporaryDirectory() as tmp:
            item=store.add_link_batch(tmp,URL)[0]
            b=Book({'projects_dir':tmp},store.item_dir(tmp,item['id']),lambda _:None)
            source=store.source_dir(b.d)
            fetch.save_refs(source,[('1.png',image(1))])
            store.write(source,completion_plan={'b01m01':'A planned new scene'})
            s=mock.Mock()
            s.ask_images.return_value=session.Turn([image(90)])
            s.ask_text.side_effect=TempError('network failure during verification')
            with self.assertRaises(TempError):expand.generate(b,s,'acc1',months=[1])
            self.assertIsNone(b.done('m01'))
            s.ask_text.side_effect=None
            s.ask_text.return_value='{"upright":true,"artwork_only":true,"distinct":true}'
            expand.generate(b,s,'acc2',months=[1])
            self.assertEqual(s.ask_images.call_count,1)
            self.assertEqual(b.done('m01').read_bytes(),image(90))
            self.assertIn('LAST attachment',s.ask_text.call_args.args[0])
            self.assertEqual(list((source/'candidates').glob('*.png')),[])

    def test_malformed_verification_does_not_discard_or_regenerate_candidate(self):
        for report in ('not JSON','{"upright":true,"artwork_only":true}'):
            with self.subTest(report=report),tempfile.TemporaryDirectory() as tmp:
                item=store.add_link_batch(tmp,URL)[0]
                b=Book({'projects_dir':tmp},store.item_dir(tmp,item['id']),lambda _:None)
                source=store.source_dir(b.d)
                fetch.save_refs(source,[('1.png',image(1))])
                store.write(source,completion_plan={'b01m01':'A planned new scene'})
                s=mock.Mock()
                s.ask_images.return_value=session.Turn([image(90)])
                s.ask_text.return_value=report
                with self.assertRaises(TempError):expand.generate(b,s,'acc1',months=[1])
                s.ask_text.return_value='{"upright":true,"artwork_only":true,"distinct":true}'
                expand.generate(b,s,'acc2',months=[1])
                self.assertEqual(s.ask_images.call_count,1)
                self.assertEqual(b.done('m01').read_bytes(),image(90))


if __name__ == '__main__':
    unittest.main()
