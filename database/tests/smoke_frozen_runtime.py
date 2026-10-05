"""Verify all three packaged apps, dependencies and local GUI entry points.

Run after build_windows.ps1: python tests/smoke_frozen_runtime.py output.json
Uses --smoke-local, which replaces all default DB paths before opening a DB.
"""
import hashlib
import json
import marshal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from smoke_frozen_capture import normalized
from PyInstaller.archive.readers import CArchiveReader


def check(output):
    output = Path(output).resolve()
    # 結果の書き出し先。2026-10-05に誤って bin/database-pscube/database-pscube.exe を渡し、EXEを結果のJSONで
    # 上書きしてしまった（P’s CUBEの凍結版が起動しなくなった）。.json 以外・bin の中は受け付けない。
    if output.suffix.lower() != '.json' or (ROOT / 'bin') in output.parents:
        raise SystemExit(f'結果の書き出し先は bin の外の .json にしてください：{output}')
    apps = {}
    for name, entry in [('database', 'app'), ('database-browser', 'browser_import'),
                        ('database-pscube', 'pscube_import')]:
        folder = ROOT / 'bin' / name
        exe = folder / (name + '.exe')
        archive = CArchiveReader(str(exe))
        bundled = archive.open_embedded_archive('PYZ.pyz')
        modules = [entry, 'pscube_connection', 'runtime_smoke', 'auto_capture']
        if name != 'database-pscube':
            modules.append('core')
        for module in modules:
            code = (marshal.loads(archive.extract(module)) if module == entry else bundled.extract(module))
            source = compile((ROOT / (module + '.py')).read_text(encoding='utf-8'), module + '.py', 'exec')
            assert normalized(code) == normalized(source), f'{name}: stale {module}'
        dependencies = ['pythonnet/runtime/Python.Runtime.dll',
                        'webview/lib/Microsoft.Web.WebView2.Core.dll',
                        'webview/lib/Microsoft.Web.WebView2.WinForms.dll',
                        'webview/lib/runtimes/win-x64/native/WebView2Loader.dll']
        assert all((folder / '_internal' / path).is_file() for path in dependencies), name
        if name == 'database-pscube':
            for asset in ('pscube_capture.js', 'pscube_auto_probe.js'):
                assert (folder / '_internal' / 'database_android' / 'assets' / asset).read_bytes() == (
                    ROOT.parent / 'database_android' / 'assets' / asset).read_bytes(), asset
        apps[name] = {'path': str(exe), 'size': exe.stat().st_size,
                      'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
                      'source_modules': modules, 'dependencies': dependencies}
    main_result = output.with_name(output.stem + '-gui.json')
    subprocess.run([str(ROOT / 'bin/database/database.exe'), '--smoke-local', str(main_result)],
                   cwd=ROOT, check=True, timeout=90)
    result = json.loads(main_result.read_text(encoding='utf-8'))
    assert result.get('passed'), result
    assert Path(result['normal_runtime_root']) == ROOT
    assert len(result['helpers']) == 2
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    output.write_text(json.dumps({'passed': True, 'verified_against_commit': revision,
                                  'apps': apps, 'local_gui': result}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: all packaged modules/assets match source; dependencies present; main launches both local WebView2 helpers; default root preserved')


if __name__ == '__main__':
    check(sys.argv[1])
