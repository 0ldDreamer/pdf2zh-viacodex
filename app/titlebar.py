# SPDX-License-Identifier: AGPL-3.0-or-later
"""Place a Tk control over the Windows caption without replacing native chrome."""
import ctypes
from ctypes import wintypes
import tkinter as tk

CAPTION_COLOR = '#f3f6fa'
GW_HWNDPREV = 3
GW_OWNER = 4
GWLP_HWNDPARENT = -8
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x0008
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
WM_WINDOWPOSCHANGED = 0x0047
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
WM_NCDESTROY = 0x0082
MOVE_SUBCLASS_ID = 1


class WindowPosition(ctypes.Structure):
    _fields_ = [('hwnd', wintypes.HWND), ('hwndInsertAfter', wintypes.HWND),
                ('x', ctypes.c_int), ('y', ctypes.c_int), ('cx', ctypes.c_int),
                ('cy', ctypes.c_int), ('flags', wintypes.UINT)]


SUBCLASS_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
    wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t,
)
comctl32 = ctypes.windll.comctl32
comctl32.SetWindowSubclass.argtypes = (wintypes.HWND, SUBCLASS_PROC, ctypes.c_size_t, ctypes.c_size_t)
comctl32.SetWindowSubclass.restype = wintypes.BOOL
comctl32.RemoveWindowSubclass.argtypes = (wintypes.HWND, SUBCLASS_PROC, ctypes.c_size_t)
comctl32.RemoveWindowSubclass.restype = wintypes.BOOL
comctl32.DefSubclassProc.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
comctl32.DefSubclassProc.restype = ctypes.c_ssize_t

set_window_position = ctypes.windll.user32.SetWindowPos
set_window_position.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT)
set_window_position.restype = wintypes.BOOL

def visible_frame_origin(frame):
    """Return the visible frame's screen origin in Tk's logical coordinates."""
    visible = wintypes.RECT()
    dwm = ctypes.windll.dwmapi
    if dwm.DwmGetWindowAttribute(frame, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(visible), ctypes.sizeof(visible)) == 0:
        edge = wintypes.POINT(visible.left, visible.top)
        if ctypes.windll.user32.PhysicalToLogicalPointForPerMonitorDPI(frame, ctypes.byref(edge)):
            return edge
    return None


def caption_menu_origin(owner):
    frame = wintypes.HWND(int(owner.frame(), 16))
    edge = visible_frame_origin(frame)
    client = wintypes.POINT()
    if not ctypes.windll.user32.ClientToScreen(frame, ctypes.byref(client)):
        return (edge.x if edge is not None else owner.winfo_rootx()), owner.winfo_rooty()
    return (edge.x if edge is not None else client.x), client.y


def keep_above_owner(window, owner, geometry=None):
    """Align a borderless Tk HWND's ownership and z-order with the main HWND."""
    user32 = ctypes.windll.user32
    get_window = user32.GetWindow
    get_window.argtypes = (wintypes.HWND, wintypes.UINT)
    get_window.restype = wintypes.HWND
    window_handle = int(window.frame(), 16)
    owner_handle = int(owner.frame(), 16)
    if get_window(window_handle, GW_OWNER) != owner_handle:
        # Tk can map an override-redirect transient without a native owner.
        set_owner = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
        set_owner.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        set_owner.restype = ctypes.c_ssize_t
        set_owner(window_handle, GWLP_HWNDPARENT, owner_handle)

    get_style = user32.GetWindowLongW
    get_style.argtypes = (wintypes.HWND, ctypes.c_int)
    owner_topmost = get_style(owner_handle, GWL_EXSTYLE) & WS_EX_TOPMOST
    window_topmost = get_style(window_handle, GWL_EXSTYLE) & WS_EX_TOPMOST
    flags = SWP_NOACTIVATE
    if owner_topmost != window_topmost:
        insert_after = HWND_TOPMOST if owner_topmost else HWND_NOTOPMOST
    else:
        insert_after = get_window(owner_handle, GW_HWNDPREV)
        if insert_after == window_handle:
            flags |= SWP_NOZORDER
    if geometry is None:
        geometry = (0, 0, 0, 0)
        flags |= SWP_NOMOVE | SWP_NOSIZE
    set_window_position(window_handle, insert_after, *geometry, flags)


class CaptionControl(tk.Toplevel):
    def __init__(self, owner):
        super().__init__(owner)
        self.withdraw()
        self.overrideredirect(True)
        self.transient(owner)
        self.configure(background=CAPTION_COLOR)
        self.owner = owner
        self.position_job = None
        self.caption_hwnd = None
        self.followed_frame = None
        self.overlay_hwnd = None
        self.subclass_proc = SUBCLASS_PROC(self.on_native_message)
        for sequence in ('<Map>', '<Unmap>', '<Configure>', '<FocusIn>'):
            owner.bind(sequence, self.owner_changed, add='+')
        self.schedule_position()

    def owner_changed(self, event):
        if event.widget is self.owner:
            self.schedule_position()

    def schedule_position(self):
        if self.position_job is None:
            # Let DWM update its caption bounds after the owner is resized or mapped.
            self.position_job = self.after(25, self.position)

    def on_native_message(self, hwnd, message, wparam, lparam, _subclass, _data):
        if message == WM_WINDOWPOSCHANGED and self.overlay_hwnd:
            pos = ctypes.cast(lparam, ctypes.POINTER(WindowPosition)).contents
            if not pos.flags & SWP_NOMOVE and ctypes.windll.user32.IsWindowVisible(self.overlay_hwnd):
                # Handle dragging inside Windows' move loop; it can defer Tk callbacks.
                x = pos.x + self.offset_x
                y = pos.y + self.offset_y
                set_window_position(self.overlay_hwnd, None, x, y, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        elif message == WM_NCDESTROY:
            self.stop_following()
        return comctl32.DefSubclassProc(hwnd, message, wparam, lparam)

    def stop_following(self):
        if self.followed_frame is not None:
            comctl32.RemoveWindowSubclass(self.followed_frame, self.subclass_proc, MOVE_SUBCLASS_ID)
            self.followed_frame = None
        self.overlay_hwnd = None

    def destroy(self):
        self.stop_following()
        if self.position_job is not None:
            self.after_cancel(self.position_job)
            self.position_job = None
        super().destroy()

    def position(self):
        self.position_job = None
        owner = self.owner
        if owner.state() not in ('normal', 'zoomed') or not owner.winfo_ismapped():
            self.withdraw()
            return

        user32 = ctypes.windll.user32
        dwm = ctypes.windll.dwmapi
        frame = wintypes.HWND(int(owner.frame(), 16))
        bounds = wintypes.RECT()
        client_origin = wintypes.POINT(0, 0)
        if not (user32.GetWindowRect(frame, ctypes.byref(bounds))
                and user32.ClientToScreen(frame, ctypes.byref(client_origin))):
            self.withdraw()
            return
        if frame.value != self.caption_hwnd:
            color = wintypes.DWORD(0xFAF6F3)  # COLORREF stores red in its low byte.
            # Keep the native title and icons for the taskbar. The caption uses
            # matching text/background colors, and the button covers its small icon.
            if dwm.DwmSetWindowAttribute(frame, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color)) == 0:
                dwm.DwmSetWindowAttribute(frame, DWMWA_TEXT_COLOR, ctypes.byref(color), ctypes.sizeof(color))
            self.caption_hwnd = frame.value

        # In a maximized window, the normal window rect can extend beyond its visible frame.
        edge = visible_frame_origin(frame)
        visible_top = max(bounds.top, edge.y) if edge is not None else bounds.top

        height = max(1, client_origin.y - visible_top - 8)
        width = max(self.winfo_reqwidth(), height + 4)
        x = client_origin.x + 3
        y = visible_top + 4
        if self.state() == 'withdrawn':
            self.geometry(f'{width}x{height}+{max(0, x)}+{max(0, y)}')
            self.deiconify()
        keep_above_owner(self, owner, (x, y, width, height))
        if frame.value != self.followed_frame:
            self.stop_following()
            if comctl32.SetWindowSubclass(frame, self.subclass_proc, MOVE_SUBCLASS_ID, 0):
                self.followed_frame = frame.value
        self.offset_x = x - bounds.left
        self.offset_y = y - bounds.top
        self.overlay_hwnd = wintypes.HWND(int(self.frame(), 16))
