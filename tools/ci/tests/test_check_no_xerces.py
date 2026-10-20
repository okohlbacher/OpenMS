"""Exercise the CI removal guard against source and binary regressions."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('check_no_xerces', Path(__file__).resolve().parents[1] / 'check_no_xerces.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class RemovalGuardTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='XERCES Replacement ')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ['src/openms/CMakeLists.txt', 'cmake/cmake_findExternalLibs.cmake']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('')
        (self.root / 'vcpkg.json').write_text('{"dependencies":["libxml2"]}')

    def run_guard(self, *args):
        with patch.object(sys, 'argv', ['guard', '--source-dir', str(self.root), *args]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                check.main()
            except SystemExit as error:
                return error.code
        return 0

    def test_product_source_and_manifest_regressions(self):
        self.assertEqual(self.run_guard(), 0)
        header = self.root / 'src/consumer.h'
        header.write_text('#include <xercesc/dom/DOM.hpp>\n')
        self.assertEqual(self.run_guard(), 1)
        header.unlink()
        (self.root / 'vcpkg.json').write_text('{"dependencies":[{"name":"xerces-c"}]}')
        self.assertEqual(self.run_guard(), 1)

    def test_dependency_names_not_workspace_directory(self):
        build = self.root / 'build'
        build.mkdir()
        library = build / 'libOpenMS.dylib'
        library.touch()
        clean = str(library) + ':\n /opt/lib/libxml2.16.dylib (compatibility version 16.0)\n'
        with patch.object(check.subprocess, 'check_output', return_value=clean):
            self.assertEqual(self.run_guard('--build-dir', str(build)), 0)
        for dependency in ['libxerces-c-3.3.so', 'libxerces-c.dylib', 'xerces-c_3_3.dll']:
            with self.subTest(dependency=dependency), patch.object(check.subprocess, 'check_output', return_value=clean + '/lib/' + dependency):
                self.assertEqual(self.run_guard('--build-dir', str(build)), 1)

    def test_missing_build_output_fails(self):
        self.assertEqual(self.run_guard('--build-dir', str(self.root / 'missing')), 1)

    def test_checkout_parent_does_not_exclude_product_sources(self):
        original = self.root
        for parent in ['data', 'extern', 'thirdparty']:
            with self.subTest(parent=parent):
                self.root = original / parent / 'OpenMS'
                (self.root / 'src/openms').mkdir(parents=True)
                (self.root / 'cmake').mkdir()
                (self.root / 'src/openms/CMakeLists.txt').write_text('')
                (self.root / 'cmake/cmake_findExternalLibs.cmake').write_text('')
                (self.root / 'vcpkg.json').write_text('{"dependencies":["libxml2"]}')
                (self.root / 'src/consumer.h').write_text('#include <xercesc/dom/DOM.hpp>\n')
                self.assertEqual(self.run_guard(), 1)
        self.root = original

    def test_dependency_inspector_failure_is_reported(self):
        build = self.root / 'build'
        build.mkdir()
        (build / 'libOpenMS.dylib').touch()
        for error in [FileNotFoundError('missing dependency inspector'),
                      check.subprocess.CalledProcessError(1, ['inspector'])]:
            with self.subTest(error=error), patch.object(check.subprocess, 'check_output', side_effect=error):
                self.assertEqual(self.run_guard('--build-dir', str(build)), 1)


if __name__ == '__main__':
    unittest.main()
