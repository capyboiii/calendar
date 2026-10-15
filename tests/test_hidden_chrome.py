import ctypes
import os
import unittest
from unittest import mock
from calforge.llm import browser as b

class HiddenChromeTest(unittest.TestCase):
    def test_only_offscreen_non_minimized_chrome_is_hidden(self):
        for info, expected in [
            (('chrome.exe',False,-32000),True),
            (('chrome.exe',True,-32000),False),
            (('chrome.exe',False,0),False),
            (('claude.exe',False,-32000),False),
            (('',False,-32000),False),
        ]:
            with self.subTest(info=info), mock.patch.object(b,'_window_info',return_value=info):
                self.assertEqual(b._is_our_hidden_chrome(None,1),expected)

    def test_dpi_context_is_restored_even_when_enumeration_fails(self):
        u=mock.Mock()
        u.SetThreadDpiAwarenessContext.return_value=123
        u.EnumWindows.side_effect=RuntimeError('test')
        with self.assertRaises(RuntimeError): b._enum_windows(u,None)
        self.assertEqual(u.SetThreadDpiAwarenessContext.call_count,2)
        self.assertEqual(u.SetThreadDpiAwarenessContext.call_args.args,(123,))

    @unittest.skipUnless(os.name=='nt','Windows API')
    def test_pointer_sized_signatures_and_process_query(self):
        from ctypes import wintypes
        u,k=b._user32(),b._kernel32()
        self.assertEqual(ctypes.sizeof(k.OpenProcess.restype),ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(u.GetWindowPlacement.argtypes[0],wintypes.HWND)
        hp=k.OpenProcess(0x1000,False,os.getpid())
        self.assertTrue(hp)
        try:
            buf=ctypes.create_unicode_buffer(520)
            size=wintypes.DWORD(520)
            self.assertTrue(k.QueryFullProcessImageNameW(hp,0,buf,ctypes.byref(size)))
            self.assertIn('python',buf.value.lower())
        finally: k.CloseHandle(hp)

    @unittest.skipUnless(os.name=='nt','Windows API')
    def test_keeper_clears_appwindow_even_when_toolwindow_already_set(self):
        from ctypes import wintypes
        u=mock.Mock()
        def classname(hwnd,buf,size):
            buf.value='Chrome_WidgetWin_1';return 1
        def rect(hwnd,p):
            ctypes.cast(p,ctypes.POINTER(wintypes.RECT)).contents.left=-32000;return True
        u.GetClassNameW.side_effect=classname
        u.GetWindowRect.side_effect=rect
        u.IsWindowVisible.return_value=True
        u.GetWindowLongPtrW.return_value=b.WS_EX_TOOLWINDOW|b.WS_EX_APPWINDOW
        with mock.patch.object(b,'_user32',return_value=u),mock.patch.object(b,'_enum_windows',side_effect=lambda _,cb:cb(42,0)),mock.patch.object(b,'_is_our_hidden_chrome',return_value=True),mock.patch.object(b,'_start_keeper'):
            self.assertEqual(b.hide_offscreen_from_taskbar(),1)
        style=u.SetWindowLongPtrW.call_args.args[2]
        self.assertTrue(style&b.WS_EX_TOOLWINDOW)
        self.assertFalse(style&b.WS_EX_APPWINDOW)

    @unittest.skipUnless(os.name=='nt','Windows API')
    def test_registered_browser_window_on_screen_is_moved_and_hidden(self):
        from ctypes import wintypes
        u=mock.Mock()
        u.GetClassNameW.side_effect=lambda hwnd,buf,size:setattr(buf,'value','Chrome_WidgetWin_1') or 1
        def rect(hwnd,p):
            ctypes.cast(p,ctypes.POINTER(wintypes.RECT)).contents.left=120
            return True
        u.GetWindowRect.side_effect=rect
        u.IsWindowVisible.return_value=True
        u.GetWindowLongPtrW.return_value=b.WS_EX_APPWINDOW
        with mock.patch.object(b,'_user32',return_value=u), \
             mock.patch.object(b,'_enum_windows',side_effect=lambda _,cb:cb(42,0)), \
             mock.patch.object(b,'_registered_window',return_value=True), \
             mock.patch.object(b,'_is_our_hidden_chrome',return_value=False),mock.patch.object(b,'_start_keeper'):
            self.assertEqual(b.hide_offscreen_from_taskbar(),1)
        self.assertEqual(u.SetWindowPos.call_args.args[2:4],(-32000,-32000))
        style=u.SetWindowLongPtrW.call_args.args[2]
        self.assertTrue(style&b.WS_EX_TOOLWINDOW)
        self.assertFalse(style&b.WS_EX_APPWINDOW)

    @unittest.skipUnless(os.name=='nt','Windows API')
    def test_each_hidden_context_registers_and_releases_its_pid(self):
        contexts=[mock.Mock(),mock.Mock()]
        with mock.patch.dict(b._HIDDEN_PIDS,{},clear=True),mock.patch.object(b,'_process_stamp',return_value=100), \
             mock.patch.object(b,'hide_offscreen_from_taskbar'),mock.patch.object(b,'_start_keeper'):
            for pid,ctx in enumerate(contexts,1001):
                ctx.browser.new_browser_cdp_session.return_value.send.return_value={'processInfo':[{'type':'browser','id':pid}]}
                self.assertTrue(b.register_hidden_context(ctx,'hidden'))
            self.assertEqual(set(b._HIDDEN_PIDS),{1001,1002})
            for ctx in contexts:ctx.on.call_args.args[1]()
            self.assertEqual(b._HIDDEN_PIDS,{})

    def test_visible_or_headless_context_is_not_registered(self):
        for mode in (False,True):
            ctx=mock.Mock()
            self.assertFalse(b.register_hidden_context(ctx,mode))
            ctx.browser.new_browser_cdp_session.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows API')
    def test_reused_pid_is_not_treated_as_registered_browser(self):
        from ctypes import wintypes
        u=mock.Mock()
        def pid(hwnd,p):ctypes.cast(p,ctypes.POINTER(wintypes.DWORD)).contents.value=123
        u.GetWindowThreadProcessId.side_effect=pid
        with mock.patch.dict(b._HIDDEN_PIDS,{123:{'stamp':100,'refs':1}},clear=True), \
             mock.patch.object(b,'_process_stamp',return_value=200):
            self.assertFalse(b._registered_window(u,42))
