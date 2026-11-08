"""Launch Figma's independent Firefox window with desktop identity."""
from pathlib import Path
import os
import subprocess
import sys
import select

from Xlib import X, Xatom, display, error
import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf


def app_icon(icon_path):
    values = []
    for size in (32, 64, 128):
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(icon_path), size, size, True)
        pixels = pixbuf.get_pixels()
        width, height = pixbuf.get_width(), pixbuf.get_height()
        stride, channels = pixbuf.get_rowstride(), pixbuf.get_n_channels()
        values.extend((width, height))
        for y in range(height):
            for x in range(width):
                i = y * stride + x * channels
                r, g, b = pixels[i:i+3]
                a = pixels[i+3] if channels == 4 else 255
                values.append((a << 24) | (r << 16) | (g << 8) | b)
    return values

class DesktopIntegration:
    """Update desktop properties only when windows or their titles change."""

    def __init__(self, connection, icons):
        self.connection = connection
        self.icons = icons
        self.root = connection.screen().root
        self.client_atom = connection.intern_atom('_NET_CLIENT_LIST')
        self.utf8 = connection.intern_atom('UTF8_STRING')
        self.title_atom = connection.intern_atom('_NET_WM_NAME')
        self.icon_atom = connection.intern_atom('_NET_WM_ICON')
        self.windows = {}
        self.figma = set()
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.refresh_windows()
        connection.flush()

    def update_title(self, window):
        prop = window.get_full_property(self.title_atom, self.utf8)
        title = prop.value.decode('utf-8', errors='replace') if prop else window.get_wm_name()
        if title and title.endswith(' — Mozilla Firefox'):
            title = title.removesuffix(' — Mozilla Firefox')
            window.change_property(self.title_atom, self.utf8, 8, title.encode('utf-8'))
            window.change_property(Xatom.WM_NAME, self.utf8, 8, title.encode('utf-8'))

    def update_class(self, wid):
        window = self.windows[wid]
        if window.get_wm_class() != ('Navigator', 'Figma'):
            self.figma.discard(wid)
            return
        if wid not in self.figma:
            window.change_property(self.icon_atom, Xatom.CARDINAL, 32, self.icons)
            self.figma.add(wid)
        self.update_title(window)

    def forget(self, wid):
        self.windows.pop(wid, None)
        self.figma.discard(wid)

    def refresh_windows(self):
        clients = self.root.get_full_property(self.client_atom, X.AnyPropertyType)
        current = {int(wid) for wid in clients.value} if clients else set()
        for wid in set(self.windows) - current:
            self.forget(wid)
        for wid in current - set(self.windows):
            try:
                window = self.connection.create_resource_object('window', wid)
                # Watching WM_CLASS also handles clients classified after mapping.
                window.change_attributes(event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
                self.windows[wid] = window
                self.update_class(wid)
            except error.XError:
                self.forget(wid)

    def process_events(self):
        while self.connection.pending_events():
            event = self.connection.next_event()
            if event.type not in (X.DestroyNotify, X.PropertyNotify):
                continue
            wid = event.window.id
            if event.type == X.DestroyNotify:
                self.forget(wid)
                continue
            if event.type != X.PropertyNotify:
                continue
            try:
                if wid == self.root.id and event.atom == self.client_atom:
                    self.refresh_windows()
                elif wid in self.windows:
                    if event.atom == Xatom.WM_CLASS:
                        self.update_class(wid)
                    elif wid in self.figma and event.atom in (self.title_atom, Xatom.WM_NAME):
                        # Read the current title; queued notifications can be stale.
                        self.update_title(self.windows[wid])
            except error.XError:
                self.forget(wid)
        self.connection.flush()


def integrate_until_exit(browser, connection, icons):
    integration = DesktopIntegration(connection, icons)
    child_fd = None
    if hasattr(os, 'pidfd_open'):
        try:
            child_fd = os.pidfd_open(browser.pid)
        except OSError:
            pass
    try:
        while browser.poll() is None:
            integration.process_events()
            readers = [connection.fileno()]
            if child_fd is not None:
                readers.append(child_fd)
            # Linux pidfds wake immediately on exit. The timeout is a portable fallback.
            ready, _, _ = select.select(readers, [], [], None if child_fd is not None else 1.0)
            if child_fd is not None and child_fd in ready:
                break
    finally:
        if child_fd is not None:
            os.close(child_fd)


def run_integration(browser, icon_path):
    connection = display.Display()
    try:
        integrate_until_exit(browser, connection, app_icon(icon_path))
    finally:
        connection.close()
