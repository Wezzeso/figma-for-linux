from pathlib import Path
import argparse
import importlib.util
import os
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('launcher', ROOT / 'app/launch.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_figma_urls_keep_file_queries(self):
        url = 'https://www.figma.com/design/key/Project?node-id=1-2#section'
        self.assertEqual(launcher.valid_url(url), url)

    def test_rejects_other_origins_schemes_credentials_and_ports(self):
        for url in ('file:///etc/passwd', 'javascript:alert(1)', 'http://figma.com',
                    'https://figma.com.evil.example', 'https://evilfigma.com',
                    'https://figma.com@evil.example', 'https://user@figma.com',
                    'https://figma.com:8443', 'https://figma.com:invalid', '--profile'):
            with self.subTest(url=url), self.assertRaises(argparse.ArgumentTypeError):
                launcher.valid_url(url)

    def test_profile_has_only_shipped_templates_on_first_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile = launcher.prepare_profile(Path(temporary) / 'data')
            actual = {str(p.relative_to(profile)) for p in profile.rglob('*') if p.is_file()}
            expected = {str(p.relative_to(ROOT / 'profile-template'))
                        for p in (ROOT / 'profile-template').rglob('*') if p.is_file()}
            self.assertEqual(actual, expected)
            self.assertFalse((profile / 'cookies.sqlite').exists())
            self.assertEqual(profile.stat().st_mode & 0o777, 0o700)

    def test_profile_upgrade_preserves_personal_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'data'
            profile = launcher.prepare_profile(state)
            personal = profile / 'cookies.sqlite'
            personal.write_bytes(b'private-test-fixture')
            launcher.prepare_profile(state)
            self.assertEqual(personal.read_bytes(), b'private-test-fixture')

    def test_data_path_is_not_tied_to_original_user(self):
        with patch.dict(os.environ, {'FIGMA_DATA_DIR': '/tmp/figma-isolated-test'}):
            self.assertEqual(launcher.data_directory(), Path('/tmp/figma-isolated-test'))

    def test_no_injected_filters_in_headless_browser(self):
        with patch.dict(os.environ, {'MOZ_HEADLESS': '1'}, clear=True):
            env = launcher.browser_environment(Path('/tmp/figma-test/profile'))
            self.assertNotIn('LD_PRELOAD', env)
            self.assertEqual(env['FIGMA_NATIVE_PROFILE'], '/tmp/figma-test/profile')

    def test_launch_passes_profile_and_url_and_propagates_exit_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            fake = temporary / 'firefox'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 7\n')
            fake.chmod(0o755)
            env = {**os.environ, 'FIGMA_FIREFOX': str(fake),
                   'FIGMA_DATA_DIR': str(temporary / 'state'), 'MOZ_HEADLESS': '1'}
            url = 'https://www.figma.com/design/test/Fixture'
            result = subprocess.run(['python3', str(ROOT / 'app/launch.py'), url],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 7)
            log = (temporary / 'state/last-launch.log').read_text()
            self.assertIn(str(temporary / 'state/profile'), log)
            self.assertIn(url, log)
            self.assertNotIn(str(Path.home()), log)

    def test_sigterm_exits_without_waitpid_deadlock(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            ready = temporary / 'browser-ready'
            fake = temporary / 'firefox'
            fake.write_text('#!/usr/bin/python3\nfrom pathlib import Path\nimport time\n'
                            f'Path({str(ready)!r}).touch()\ntime.sleep(60)\n')
            fake.chmod(0o755)
            env = {**os.environ, 'FIGMA_FIREFOX': str(fake),
                   'FIGMA_DATA_DIR': str(temporary / 'state'), 'MOZ_HEADLESS': '1'}
            process = subprocess.Popen(['python3', str(ROOT / 'app/launch.py')], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
                process.terminate()
                process.communicate(timeout=5)
                self.assertEqual(process.returncode, 143)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == '__main__':
    unittest.main()
