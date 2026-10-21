import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from calforge.imagegen import driver
from calforge.llm.pool import AccountPool


class WorkerCapacityTest(unittest.TestCase):
    def test_twelve_ready_images_use_twelve_accounts_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = [f'acc{i}' for i in range(40)]
            pool = AccountPool(Path(tmp), names, cap=40)
            gate, lock = threading.Event(), threading.Lock()
            active = [0]
            peak = [0]
            def render(page, job):
                with lock:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                    if active[0] == 12:
                        gate.set()
                gate.wait(3)
                with lock:
                    active[0] -= 1
                return job.out.with_suffix('.png')
            jobs = [driver.GenJob(f'm{i:02}', 'prompt', Path(tmp)/str(i)) for i in range(12)]
            with mock.patch.object(driver, '_Worker', return_value=SimpleNamespace(run_job=render)):
                result = driver.run_jobs(jobs, Path(tmp), names, pool=pool,
                                         open_page=lambda _: nullcontext(None), on_event=lambda _: None)
            self.assertEqual(peak[0], 12)
            self.assertTrue(all(j.result and not j.error for j in result))
            self.assertEqual(pool.use, {})

    def test_starting_browsers_reserve_jobs_without_opening_extra_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = [f'acc{i}' for i in range(40)]
            pool = AccountPool(Path(tmp), names, cap=40)
            gate, lock = threading.Event(), threading.Lock()
            opened = []
            @contextmanager
            def opener(name):
                with lock:
                    opened.append(name)
                    if len(opened) == 3:
                        gate.set()
                gate.wait(3)
                time.sleep(.05)
                yield None
            jobs = [driver.GenJob(str(i), 'prompt', Path(tmp)/str(i)) for i in range(3)]
            worker = SimpleNamespace(run_job=lambda p, j: j.out.with_suffix('.png'))
            with mock.patch.object(driver, '_Worker', return_value=worker):
                driver.run_jobs(jobs, Path(tmp), names, pool=pool, open_page=opener, on_event=lambda _: None)
            self.assertEqual(len(opened), 3)
            self.assertEqual(len(set(opened)), 3)
            self.assertEqual(pool.use, {})
