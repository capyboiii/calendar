import errno
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from calforge.llm.pool import AccountPool, IMAGE


class PoolGateWaitTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('acc1', 'acc2'):
            (self.root / name).mkdir()
        self.a = AccountPool(self.root, ['acc1', 'acc2'], cap=2, leases=True)
        self.b = AccountPool(self.root, ['acc1', 'acc2'], cap=2, leases=True)

    def test_busy_global_gate_does_not_block_account_acquisition(self):
        with self.a._process_gate():
            started = time.monotonic()
            self.assertIsNone(self.b.acquire(IMAGE, only='acc1'))
            self.assertLess(time.monotonic() - started, .5)
            self.assertTrue(self.b._gate_busy)
            self.assertEqual(self.b.use, {})
        name = self.b.acquire(IMAGE, only='acc1')
        self.assertEqual(name, 'acc1')
        self.b.release(name)

    def test_busy_gate_does_not_prevent_releasing_an_existing_account(self):
        self.assertEqual(self.a.acquire(IMAGE, only='acc1'), 'acc1')
        with self.b._process_gate():
            self.assertIsNone(self.a.acquire(IMAGE, only='acc2'))
            started = time.monotonic()
            self.a.release('acc1')
            self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(self.a.use, {})

    def test_launch_gate_lock_wait_is_bounded(self):
        with self.a._process_gate():
            with self.assertRaisesRegex(TimeoutError, 'khóa điều phối'):
                with self.b._process_gate(timeout_s=.05):
                    self.fail('must not enter a locked gate')
        with self.b._process_gate() as acquired:
            self.assertTrue(acquired)

    def test_waiter_cleanup_does_not_block_account_release_on_busy_global_gate(self):
        self.assertEqual(self.a.acquire(IMAGE, only='acc1'), 'acc1')
        self.assertIsNone(self.b.acquire(IMAGE, only='acc1', request_id='blocked'))
        with self.b._process_gate():
            started=time.monotonic()
            self.a.cancel_wait(IMAGE, 'cleanup')
            self.a.release('acc1')
            self.assertLess(time.monotonic()-started,.5)
        self.assertEqual(self.a.use,{})
        self.b.cancel_wait(IMAGE,'blocked')
        self.assertEqual(self.b.acquire(IMAGE,only='acc1'),'acc1')
        self.b.release('acc1')

    def test_deferred_cleanup_is_flushed_before_next_allocation(self):
        import json
        from calforge.llm.pool_waiters import FILE
        self.assertEqual(self.b.acquire(IMAGE,only='acc1'),'acc1')
        self.assertIsNone(self.a.acquire(IMAGE,only='acc1',request_id='cancelled'))
        with self.b._process_gate():
            self.a.cancel_wait(IMAGE,'cancelled')
        self.assertTrue(self.a._wait_cancels)
        self.assertEqual(self.a.acquire(IMAGE,only='acc2',request_id='next'),'acc2')
        self.assertFalse(self.a._wait_cancels)
        state=json.loads((self.root/FILE).read_text())
        self.assertFalse(any(':cancelled:' in r['token'] for r in state['requests']))
        self.a.release('acc2');self.b.release('acc1')

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows API')
    def test_fatal_lock_error_is_not_retried_forever(self):
        with mock.patch('msvcrt.locking', side_effect=OSError(errno.EBADF, 'invalid handle')):
            with self.assertRaises(OSError):
                with self.a._process_gate():
                    self.fail('must propagate fatal lock error')

    def test_reboot_or_copied_profile_timestamp_cannot_delay_launch(self):
        for saved in ('9000000', 'inf', 'nan', 'bad timestamp'):
            with self.subTest(saved=saved):
                stamp = self.root / '.calforge_launch_at'
                stamp.write_text(saved, encoding='utf-8')
                sleeps=[]
                pool=AccountPool(self.root,['acc1'],cap=1,leases=True,launch_gap_s=5,
                                 clock=lambda:100, sleep=sleeps.append)
                with pool.launch_gate():pass
                self.assertEqual(sleeps,[])
                self.assertEqual(float(stamp.read_text(encoding='utf-8')),100)

    def test_valid_same_boot_timestamp_still_enforces_launch_gap(self):
        (self.root / '.calforge_launch_at').write_text('98',encoding='utf-8')
        sleeps=[]
        pool=AccountPool(self.root,['acc1'],cap=1,leases=True,launch_gap_s=5,
                         clock=lambda:100,sleep=sleeps.append)
        with pool.launch_gate():pass
        self.assertEqual(sleeps,[3])


if __name__ == '__main__':
    unittest.main()
