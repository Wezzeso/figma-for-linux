from pathlib import Path
import ctypes
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class Image(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in
                ('version', 'size', 'width', 'height', 'xhot', 'yhot', 'delay')]
    _fields_.append(('pixels', ctypes.POINTER(ctypes.c_uint32)))


@unittest.skipUnless(shutil.which('gcc'), 'GCC is needed for the native cursor check')
class CursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        library = Path(cls.directory.name) / 'cursor.so'
        subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fPIC', '-shared', '-o', str(library),
                        str(ROOT / 'app/cursor-anchor.c'), '-ldl', '-lm'], check=True)
        cls.library = ctypes.CDLL(str(library))
        cls.patch = cls.library.figma_patch_cursor
        cls.patch.argtypes = [ctypes.POINTER(Image), ctypes.POINTER(Image),
                              ctypes.POINTER(ctypes.c_uint32)]
        cls.patch.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_ordinary_cursor_is_untouched(self):
        pixels = (ctypes.c_uint32 * 1024)(*[0xffffffff] * 1024)
        image = Image(1, 32, 32, 32, 4, 4, 0, pixels)
        output = (ctypes.c_uint32 * 1024)()
        self.assertEqual(self.patch(ctypes.byref(image), ctypes.byref(Image()), output), 0)
        self.assertTrue(all(value == 0 for value in output))

    def test_resize_shape_gets_stable_hotspot(self):
        pixels = (ctypes.c_uint32 * 1024)()
        for y in range(14, 18):
            for x in range(4, 28):
                pixels[y * 32 + x] = 0xffffffff
        image = Image(1, 32, 32, 32, 16, 16, 0, pixels)
        patched = Image()
        output = (ctypes.c_uint32 * 1024)()
        self.assertEqual(self.patch(ctypes.byref(image), ctypes.byref(patched), output), 1)
        self.assertEqual((patched.xhot, patched.yhot), (4, 4))
        self.assertTrue(any(output))


if __name__ == '__main__':
    unittest.main()
