"""別のPythonを選ぶ再発と、依存不足を見逃す再発を防ぐ。"""

from importlib import metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

import setup_python


ROOT = Path(__file__).resolve().parents[2]


class DependencyCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='python-check-')
        self.addCleanup(temporary.cleanup)
        self.requirements = Path(temporary.name) / 'requirements.txt'
        self.requirements.write_text('selenium==4.49.0\npillow==12.3.0\n', encoding='utf-8')

    def test_missing_dependency_reports_package_before_running_tests(self):
        with patch.object(metadata, 'version', side_effect=metadata.PackageNotFoundError('selenium')), \
                patch.object(setup_python.importlib, 'import_module'):
            errors = setup_python.environment_errors(self.requirements)
        self.assertTrue(any('selenium==4.49.0 が入っていません' in e for e in errors), errors)

    def test_wrong_dependency_version_is_an_error(self):
        with patch.object(metadata, 'version', return_value='0.0.0'), \
                patch.object(setup_python.importlib, 'import_module'):
            errors = setup_python.environment_errors(self.requirements)
        self.assertTrue(any('必要 4.49.0、現在 0.0.0' in e for e in errors), errors)

    def test_unloadable_library_is_an_error_even_when_version_matches(self):
        def load(name):
            if name == 'PIL.Image':
                raise OSError('native library unavailable')
        with patch.object(metadata, 'version', side_effect=['4.49.0', '12.3.0']), \
                patch.object(setup_python.importlib, 'import_module', side_effect=load):
            errors = setup_python.environment_errors(self.requirements)
        self.assertTrue(any('PIL.Image を読み込めません' in e for e in errors), errors)

    def test_installed_packages_and_standard_libraries_are_loaded(self):
        with patch.object(metadata, 'version', side_effect=['4.49.0', '12.3.0']), \
                patch.object(setup_python.importlib, 'import_module') as load:
            errors = setup_python.environment_errors(self.requirements)
        self.assertEqual(errors, [])
        for name in ('selenium', 'PIL.Image', 'sqlite3', 'ssl', 'tkinter'):
            load.assert_any_call(name)

    def test_setup_does_not_overwrite_an_unrelated_directory(self):
        target = self.requirements.parent / '.venv'
        target.mkdir()
        keep = target / 'keep.txt'
        keep.write_text('keep', encoding='utf-8')
        with patch.object(setup_python, 'ROOT', self.requirements.parent), \
                patch.object(setup_python.subprocess, 'run') as run:
            self.assertEqual(setup_python.setup(), 1)
        run.assert_not_called()
        self.assertEqual(keep.read_text(encoding='utf-8'), 'keep')


@unittest.skipUnless(shutil.which('bash'), 'Git BashまたはBashが必要')
class InterpreterSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='project Python test ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / 'database'
        self.tool = self.root / 'database_android' / 'tool'
        self.database.mkdir()
        self.tool.mkdir(parents=True)
        shutil.copy(ROOT / 'database_android/tool/dev_env.sh', self.tool / 'dev_env.sh')
        shutil.copy(ROOT / 'database/setup_python.py', self.database / 'setup_python.py')
        # 環境選択だけを検証する。実際の依存一式は専用環境の構築時に別途確認する。
        (self.database / 'requirements.txt').write_text('', encoding='utf-8')

    def create_environment(self, name):
        target = self.database / name
        venv.EnvBuilder(with_pip=False, symlinks=os.name != 'nt').create(target)
        return target

    def run_selection(self, python=None, flutter_root=None):
        env = dict(os.environ)
        env.pop('PYTHON', None)
        env.pop('FLUTTER_ROOT', None)
        env.pop('USERPROFILE', None)
        env['NODE'] = shutil.which('node') or 'node'
        env['PLAYWRIGHT_MODULE'] = 'file:///unused-in-selection-test.mjs'
        env['PYTHONUTF8'] = '1'
        if python is not None:
            env['PYTHON'] = str(python).replace('\\', '/')
        if flutter_root is not None:
            env['FLUTTER_ROOT'] = str(flutter_root).replace('\\', '/')
        return subprocess.run(['bash', '-c',
                               'source database_android/tool/dev_env.sh || exit 1; '
                               '"$PYTHON" -c "import sys; print(\'SELECTED=\' + sys.prefix)"; '
                               'if [ -n "${FLUTTER_ROOT:-}" ]; then command -v flutter; fi'],
                              cwd=self.root, env=env, capture_output=True, encoding='utf-8', timeout=30)

    def test_missing_project_environment_does_not_pick_up_system_python(self):
        result = self.run_selection()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('専用Pythonがありません', result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)

    def test_project_venv_is_selected_in_a_path_with_spaces(self):
        target = self.create_environment('.venv')
        # 旧環境の入口が存在しても、新しい専用環境を優先する。
        legacy = self.database / '.runtime' / 'Scripts'
        legacy.mkdir(parents=True)
        old_python = legacy / 'python.exe'
        old_python.write_text('#!/usr/bin/env bash\nexit 9\n', encoding='utf-8')
        old_python.chmod(0o755)
        result = self.run_selection()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = next(line.removeprefix('SELECTED=') for line in result.stdout.splitlines()
                        if line.startswith('SELECTED='))
        self.assertEqual(Path(selected).resolve(), target.resolve())

    def test_broken_venv_does_not_fall_back_to_another_python(self):
        (self.database / '.venv').mkdir()
        result = self.run_selection()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)

    def test_explicit_python_override_remains_supported(self):
        self.create_environment('.venv')
        result = self.run_selection(python=sys.executable)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SELECTED=' + sys.prefix, result.stdout)

    def test_invalid_explicit_python_does_not_fall_back(self):
        self.create_environment('.venv')
        result = self.run_selection(python=self.root / 'missing-python')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)

    def test_missing_dependency_stops_environment_selection(self):
        self.create_environment('.venv')
        (self.database / 'requirements.txt').write_text('database-missing-test-package==0\n', encoding='utf-8')
        result = self.run_selection()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('database-missing-test-package==0 が入っていません', result.stderr)
        self.assertNotIn('SELECTED=', result.stdout)

    def test_flutter_root_with_spaces_selects_the_configured_sdk(self):
        sdk = self.root / 'Flutter SDK'
        (sdk / 'bin').mkdir(parents=True)
        flutter = sdk / 'bin' / 'flutter'
        flutter.write_text('#!/usr/bin/env bash\nexit 0\n', encoding='utf-8')
        flutter.chmod(0o755)
        result = self.run_selection(python=sys.executable, flutter_root=sdk)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Git BashはWindowsの絶対パスを /c/... の形で返す。
        self.assertTrue(result.stdout.rstrip().endswith('/Flutter SDK/bin/flutter'), result.stdout)


if __name__ == '__main__':
    unittest.main()
