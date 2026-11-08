"""Let Figma receive Alt+Shift while retaining the desktop layout shortcut elsewhere."""
import ctypes
import ctypes.util
import os
import select
import signal
import subprocess
import sys

from Xlib import X, display, error

class XkbState(ctypes.Structure):
    _fields_ = [
        ('group', ctypes.c_ubyte), ('locked_group', ctypes.c_ubyte),
        ('base_group', ctypes.c_ushort), ('latched_group', ctypes.c_ushort),
        ('mods', ctypes.c_ubyte), ('base_mods', ctypes.c_ubyte),
        ('latched_mods', ctypes.c_ubyte), ('locked_mods', ctypes.c_ubyte),
        ('compat_state', ctypes.c_ubyte), ('grab_mods', ctypes.c_ubyte),
        ('compat_grab_mods', ctypes.c_ubyte), ('lookup_mods', ctypes.c_ubyte),
        ('compat_lookup_mods', ctypes.c_ubyte), ('ptr_buttons', ctypes.c_ushort),
    ]

class InputGuard:
    def __init__(self):
        self.connection = display.Display()
        self.root = self.connection.screen().root
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.connection.flush()
        self.active_atom = self.connection.intern_atom('_NET_ACTIVE_WINDOW')
        self.rules_atom = self.connection.intern_atom('_XKB_RULES_NAMES')
        self.original = None
        self.applied = None
        self.x11 = ctypes.CDLL(ctypes.util.find_library('X11'))
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.x11.XkbGetState.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(XkbState)]
        self.x11.XkbLockGroup.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.xdisplay = self.x11.XOpenDisplay(None)

    def options(self):
        prop = self.root.get_full_property(self.rules_atom, X.AnyPropertyType)
        if not prop:
            return []
        parts = bytes(prop.value).decode().split('\0')
        return [v for v in parts[4].split(',') if v] if len(parts) > 4 else []

    def figma_focused(self):
        prop = self.root.get_full_property(self.active_atom, X.AnyPropertyType)
        if not prop or not prop.value[0]:
            return False
        try:
            window = self.connection.create_resource_object('window', int(prop.value[0]))
            return window.get_wm_class() == ('Navigator', 'Figma')
        except error.XError:
            return False

    def set_options(self, options):
        state = XkbState()
        have_state = self.xdisplay and self.x11.XkbGetState(self.xdisplay, 0x100, ctypes.byref(state)) == 0
        args = ['setxkbmap', '-option', '']
        for option in options:
            args.extend(('-option', option))
        subprocess.run(args, check=True, capture_output=True, timeout=3)
        if have_state:
            self.x11.XkbLockGroup(self.xdisplay, 0x100, state.group)
            self.x11.XSync(self.xdisplay, False)

    def update(self):
        current = self.options()
        if self.figma_focused():
            conflicts = [v for v in current if v.startswith('grp:') and 'alt_shift' in v]
            if conflicts:
                self.original = current
                self.applied = [v for v in current if v not in conflicts]
                # Super+Space is handled by Cinnamon's layout switcher so
                # the active language and its panel indicator stay in sync.
                self.set_options(self.applied)
        elif self.applied is not None:
            self.restore()

    def restore(self):
        if self.applied is not None and self.options() == self.applied:
            self.set_options(self.original)
        self.original = self.applied = None

    def close(self):
        self.restore()
        self.connection.close()
        if self.xdisplay:
            self.x11.XCloseDisplay(self.xdisplay)

def main():
    browser_pid = int(sys.argv[1])
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    guard = InputGuard()
    try:
        while running:
            try:
                os.kill(browser_pid, 0)
            except ProcessLookupError:
                break
            guard.update()
            select.select([guard.connection.fileno()], [], [], .25)
            while guard.connection.pending_events():
                guard.connection.next_event()
    finally:
        guard.close()

if __name__ == '__main__':
    main()
