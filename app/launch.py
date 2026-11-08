#!/usr/bin/env python3
"""Run the dedicated Figma Firefox workspace without sharing browser profiles."""
from pathlib import Path
import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def data_directory():
    override = os.environ.get('FIGMA_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return base / 'figma-for-linux'


def valid_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme == 'https' and
                (host == 'figma.com' or host.endswith('.figma.com')) and
                not parsed.username and not parsed.password and
                parsed.port in (None, 443)):
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Use an https://figma.com/ link.')


def prepare_profile(state):
    """Copy only the shipped, non-personal configuration into a fresh profile."""
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    profile = state / 'profile'
    profile.mkdir(mode=0o700, exist_ok=True)
    template = ROOT / 'profile-template'
    for source in template.rglob('*'):
        if source.is_file():
            target = profile / source.relative_to(template)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Do not rewrite unchanged files while another invocation is running.
            if not target.exists() or target.read_bytes() != source.read_bytes():
                shutil.copyfile(source, target)
    return profile


def cinnamon_available():
    try:
        from gi.repository import Gio
        schemas = Gio.SettingsSchemaSource.get_default()
        return schemas is not None and schemas.lookup('org.cinnamon.gestures', True) is not None
    except (ImportError, ValueError):
        return False


def browser_environment(profile):
    env = os.environ.copy()
    # This build's window integration and input fixes target X11 / XWayland.
    env['MOZ_ENABLE_WAYLAND'] = '0'
    env['MOZ_APP_REMOTINGNAME'] = 'figma'
    env['FIGMA_NATIVE_PROFILE'] = str(profile)
    filters = []
    if os.environ.get('DISPLAY') and not os.environ.get('MOZ_HEADLESS'):
        if os.environ.get('FIGMA_DISABLE_CURSOR_FIX') != '1':
            filters.append(ROOT / 'app/cursor-anchor.so')
        if os.environ.get('FIGMA_DISABLE_PINCH') != '1' and cinnamon_available():
            filters.append(ROOT / 'app/pinch-gtk.so')
            env['FIGMA_NATIVE_PINCH'] = '1'
    active = [str(path) for path in filters if path.is_file()]
    if active:
        env['LD_PRELOAD'] = ':'.join(active + ([env['LD_PRELOAD']] if env.get('LD_PRELOAD') else []))
    return env


def stop_child(child):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def main(argv=None):
    version = (ROOT / 'VERSION').read_text().strip()
    parser = argparse.ArgumentParser(description='Figma for Linux: a dedicated Firefox workspace.')
    parser.add_argument('--version', action='version', version=f'Figma for Linux {version}')
    parser.add_argument('--diagnostics', action='store_true', help='Show installation details without opening Figma')
    parser.add_argument('urls', nargs='*', type=valid_url, help='Figma HTTPS links to open')
    args = parser.parse_args(argv)
    state = data_directory()
    firefox = Path(os.environ.get('FIGMA_FIREFOX') or ROOT / 'firefox/firefox')
    if args.diagnostics:
        print(json.dumps({
            'version': version, 'firefox': str(firefox),
            'firefox_exists': firefox.is_file(), 'data_directory': str(state),
            'display': os.environ.get('DISPLAY'),
            'cinnamon_pinch_available': cinnamon_available(),
        }, indent=2))
        return 0
    if not firefox.is_file() or not os.access(firefox, os.X_OK):
        parser.exit(1, 'Bundled Firefox was not found. Install a release package or run scripts/build.py.\n')
    if not os.environ.get('DISPLAY') and not os.environ.get('MOZ_HEADLESS'):
        parser.exit(1, 'This build needs an X11 or XWayland desktop session (DISPLAY is unset).\n')
    state.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (state / 'launch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # Never open the same profile twice. Let Firefox forward new URLs
            # to this app's existing process; otherwise just focus the window.
            if args.urls:
                return subprocess.run([
                    str(firefox), '--profile', str(state / 'profile'),
                    '--new-tab', args.urls[0], *args.urls[1:],
                ], env=browser_environment(state / 'profile'), check=False).returncode
            if shutil.which('wmctrl'):
                subprocess.run(['wmctrl', '-x', '-a', 'Navigator.Figma'], check=False)
            return 0
        profile = prepare_profile(state)
        with (state / 'last-launch.log').open('w') as log:
            browser = None
            guard = None
            old_signals = {}

            def handle_signal(_number, _frame):
                # Do not call wait() from a signal handler: it can interrupt an
                # existing Popen.wait() while its internal waitpid lock is held.
                if browser is not None:
                    browser.terminate()

            try:
                for number in (signal.SIGTERM, signal.SIGINT):
                    old_signals[number] = signal.signal(number, handle_signal)
                browser = subprocess.Popen([
                    str(firefox), '--new-instance', '--class', 'Figma', '--name', 'Figma',
                    '--profile', str(profile), *args.urls,
                ], stdout=log, stderr=log, env=browser_environment(profile))
                interactive = os.environ.get('DISPLAY') and not os.environ.get('MOZ_HEADLESS')
                if interactive and os.environ.get('FIGMA_DISABLE_INPUT_GUARD') != '1' and shutil.which('setxkbmap'):
                    guard = subprocess.Popen([
                        sys.executable, str(ROOT / 'app/input-guard.py'), str(browser.pid),
                    ], stdout=log, stderr=log)
                if interactive:
                    try:
                        from desktop import run_integration
                        run_integration(browser, ROOT / 'assets/figma-for-linux.svg')
                    except Exception as exc:
                        print(f'Desktop integration: {exc}', file=log, flush=True)
                result = browser.wait()
                if result:
                    print(f'Figma exited with code {result}. Log: {state / "last-launch.log"}', file=sys.stderr)
                return result if result >= 0 else 128 - result
            finally:
                stop_child(browser)
                # Ask the guard to restore keyboard settings before it exits.
                stop_child(guard)
                for number, previous in old_signals.items():
                    signal.signal(number, previous)


if __name__ == '__main__':
    raise SystemExit(main())
