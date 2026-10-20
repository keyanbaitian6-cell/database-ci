"""プロジェクト専用Pythonの作成と、ビルド前の依存関係の確認。"""

import argparse
import importlib
from importlib import metadata
import platform
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / 'requirements.txt'
IMPORTS = {
    'selenium': 'selenium',
    'rapidocr': 'rapidocr',
    'onnxruntime': 'onnxruntime',
    'pillow': 'PIL.Image',
    'pywebview': 'webview',
}


def environment_errors(requirements=REQUIREMENTS):
    """版だけでなく、必要なライブラリと標準ライブラリを実際に読めるか調べる。"""
    errors = []
    if sys.version_info < (3, 10):
        errors.append('Python 3.10以上が必要です。')
    if sys.platform == 'win32' and sys.maxsize <= 2**32:
        errors.append('Windowsでは64ビット版のPythonが必要です。')
    modules = ['sqlite3', 'ssl', 'tkinter']
    for line in requirements.read_text(encoding='utf-8').splitlines():
        line = line.partition('#')[0].strip()
        if not line:
            continue
        name, separator, expected = line.partition('==')
        if not separator:
            errors.append(f'版が固定されていない依存関係です：{line}')
            continue
        try:
            actual = metadata.version(name)
        except metadata.PackageNotFoundError:
            errors.append(f'{name}=={expected} が入っていません。')
            continue
        if actual != expected:
            errors.append(f'{name} の版が異なります：必要 {expected}、現在 {actual}')
            continue
        if name in IMPORTS:
            modules.append(IMPORTS[name])
    for module in modules:
        try:
            importlib.import_module(module)
        except Exception as exc:
            errors.append(f'{module} を読み込めません：{exc}')
    return errors


def check():
    print(f'使用するPython：{sys.executable}（{platform.python_version()}）', flush=True)
    errors = environment_errors()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print('Windowsは database\\setup_python.cmd、Linuxは python3 database/setup_python.py を実行してください。',
              file=sys.stderr)
        return 1
    print('Pythonの依存関係：確認済み', flush=True)
    return 0


def setup():
    if sys.version_info < (3, 10) or (sys.platform == 'win32' and sys.maxsize <= 2**32):
        print('Python 3.10以上（Windowsは64ビット版）でセットアップを実行してください。', file=sys.stderr)
        return 1
    target = ROOT / '.venv'
    executable = target / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if target.exists() and not (target / 'pyvenv.cfg').is_file():
        print(f'{target} は既存の仮想環境ではありません。上書きせず停止しました。', file=sys.stderr)
        return 1
    if not target.exists():
        print(f'専用Pythonを作成します：{target}\n作成元：{sys.executable}', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(target)], check=True)
    if not executable.is_file():
        print(f'専用Pythonが壊れているか、別OSで作成されています：{executable}', file=sys.stderr)
        return 1
    # 毎回のビルドではインストールしない。初回と依存関係の更新時だけ、この入口を使う。
    subprocess.run([str(executable), '-m', 'pip', '--require-virtualenv', 'install', '--disable-pip-version-check',
                    '--no-input', '--retries', '1', '--timeout', '30',
                    '-r', str(REQUIREMENTS)], check=True)
    subprocess.run([str(executable), '-m', 'pip', 'check'], check=True)
    subprocess.run([str(executable), str(Path(__file__).resolve()), '--check'], check=True)
    print('専用Pythonの準備が完了しました。通常の起動とビルド前チェックがこの環境を使います。', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='現在のPythonを検査し、インストールは行わない')
    args = parser.parse_args()
    try:
        return check() if args.check else setup()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'専用Pythonの準備・確認に失敗しました：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
