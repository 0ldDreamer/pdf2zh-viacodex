# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receive files dropped from Windows Explorer without additional dependencies."""
import ctypes
from ctypes import wintypes

from titlebar import SUBCLASS_PROC, WM_NCDESTROY, comctl32

WM_DROPFILES = 0x0233
DROP_SUBCLASS_ID = 2
QUERY_FILE_COUNT = 0xFFFFFFFF

shell32 = ctypes.windll.shell32
shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
shell32.DragAcceptFiles.restype = None
shell32.DragFinish.argtypes = (wintypes.HANDLE,)
shell32.DragFinish.restype = None
shell32.DragQueryFileW.argtypes = (wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT)
shell32.DragQueryFileW.restype = wintypes.UINT


class FileDropTarget:
    def __init__(self, window, on_drop):
        self.window = window
        self.on_drop = on_drop
        self.hwnd = None
        self.callback = SUBCLASS_PROC(self.window_message)
        window.bind('<Map>', self.on_map, add='+')
        window.bind('<Destroy>', self.on_destroy, add='+')
        if window.winfo_ismapped():
            self.attach()

    def on_map(self, event):
        if event.widget is self.window:
            self.attach()

    def on_destroy(self, event):
        if event.widget is self.window:
            self.detach()

    def attach(self):
        hwnd = int(self.window.frame(), 16)
        if hwnd == self.hwnd:
            return
        self.detach()
        if comctl32.SetWindowSubclass(hwnd, self.callback, DROP_SUBCLASS_ID, 0):
            self.hwnd = hwnd
            shell32.DragAcceptFiles(hwnd, True)

    def detach(self):
        if self.hwnd is not None:
            shell32.DragAcceptFiles(self.hwnd, False)
            comctl32.RemoveWindowSubclass(self.hwnd, self.callback, DROP_SUBCLASS_ID)
            self.hwnd = None

    def window_message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == WM_DROPFILES:
            paths = []
            try:
                count = shell32.DragQueryFileW(wparam, QUERY_FILE_COUNT, None, 0)
                for index in range(count):
                    length = shell32.DragQueryFileW(wparam, index, None, 0)
                    if length:
                        path = ctypes.create_unicode_buffer(length + 1)
                        if shell32.DragQueryFileW(wparam, index, path, len(path)):
                            paths.append(path.value)
            finally:
                shell32.DragFinish(wparam)
            if paths:
                self.on_drop(paths)
            return 0
        if message == WM_NCDESTROY:
            self.detach()
        return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)
