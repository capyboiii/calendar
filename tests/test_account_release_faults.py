import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from calforge.clone.run import PoolWaiting, StageFailed, run_stage
from calforge.imagegen.driver import NavError, QuotaExceeded, TempError


class ReleaseFaultMatrixTest(unittest.TestCase):
    def test_each_error_releases_account_and_closes_context(self):
        failures=[TempError('temporary'),TimeoutError('timeout'),MemoryError('RAM'),
                  PermissionError('locked file'),RuntimeError('Target closed'),
                  NavError('network error'),QuotaExceeded('quota'),
                  PoolWaiting('yield'),StageFailed('stop'),KeyboardInterrupt()]
        for location in ('open','work'):
            for failure in failures:
                with self.subTest(location=location,failure=type(failure).__name__):
                    owned=set();acquired=[];closed=[]
                    def acquire(*args,**kw):
                        self.assertFalse(owned,'previous failed attempt leaked an account')
                        if len(acquired)==2:raise StageFailed('test ends after two attempts')
                        name=f'acc{len(acquired)+1}'
                        acquired.append(name);owned.add(name)
                        return name
                    def release(name):
                        self.assertIn(name,owned)
                        owned.remove(name)
                    @contextmanager
                    def page(name):
                        try:yield None
                        finally:closed.append(name)
                    def open_chat():
                        if location=='open':raise failure
                    def work(s,name):
                        if location=='work':raise failure
                    accts=SimpleNamespace(acquire=acquire,release=mock.Mock(side_effect=release),
                        pool=mock.Mock(),on_event=lambda _:None,pdir=Path('.'),open_page=page)
                    s=SimpleNamespace(open=open_chat)
                    with self.assertRaises(BaseException):
                        run_stage(accts,'fault matrix',work,session_factory=lambda *_:s)
                    self.assertFalse(owned)
                    self.assertEqual(closed,acquired)
                    self.assertEqual(accts.release.call_count,len(acquired))

    def test_success_also_releases_account(self):
        accts=SimpleNamespace(acquire=mock.Mock(return_value='acc1'),release=mock.Mock(),
            pool=mock.Mock(),on_event=lambda _:None,pdir=Path('.'))
        closed=[]
        @contextmanager
        def page(name):
            try:yield None
            finally:closed.append(name)
        accts.open_page=page
        result=run_stage(accts,'success',lambda *_:None,
                         session_factory=lambda *_:SimpleNamespace(open=lambda:None))
        self.assertEqual(result,'acc1')
        accts.release.assert_called_once_with('acc1')
        self.assertEqual(closed,['acc1'])

    def test_context_close_error_does_not_keep_account_owned(self):
        for error in (TimeoutError('close timeout'),RuntimeError('Target closed')):
            with self.subTest(error=type(error).__name__):
                owned=set();attempts=[]
                def acquire(*args,**kw):
                    self.assertFalse(owned)
                    if len(attempts)==2:raise StageFailed('bounded test')
                    attempts.append('acc1');owned.add('acc1');return 'acc1'
                @contextmanager
                def page(name):
                    yield None
                    raise error
                accts=SimpleNamespace(acquire=acquire,release=mock.Mock(side_effect=owned.remove),
                    pool=mock.Mock(),on_event=lambda _:None,pdir=Path('.'),open_page=page)
                with self.assertRaises(StageFailed):
                    run_stage(accts,'close error',lambda *_:None,
                              session_factory=lambda *_:SimpleNamespace(open=lambda:None))
                self.assertFalse(owned)
                self.assertEqual(accts.release.call_count,2)
