"""Check packaged save subprocesses without opening a browser or real DB."""
import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalized(code):
    if not isinstance(code, types.CodeType):
        return code
    return code.replace(co_filename='', co_consts=tuple(normalized(c) for c in code.co_consts))


def check(executable):
    from PyInstaller.archive.readers import CArchiveReader
    from core import Store, graph_done
    from collector import HEADERS, HOST
    archive = CArchiveReader(str(executable))
    bundled = archive.open_embedded_archive('PYZ.pyz')
    for name in ('browser_import', 'auto_capture', 'core'):
        code = marshal.loads(archive.extract(name)) if name == 'browser_import' else bundled.extract(name)
        expected = compile((ROOT / (name + '.py')).read_text(encoding='utf-8'), name + '.py', 'exec')
        assert normalized(code) == normalized(expected), 'stale compiled module: ' + name
    with tempfile.TemporaryDirectory(prefix='tmp-frozen-capture-', dir=ROOT) as folder:
        folder = Path(folder)
        db_path, signal = folder / 'dummy.sqlite3', folder / 'signal.json'
        # The host is only a validation string: --confirm never opens a browser.
        url = f'https://{HOST}/saiwaichou/standgraph/?rack_no=710&target_date=2026-09-30'
        table = dict(store='saiwaichou', machine='Dummy', target_date='2026-09-30', kind_code='21',
            matrix=[HEADERS, ['710', '10', '5', '3000', '1/200', '0', '500']], links=[url])
        graph = dict(store='saiwaichou', rack=710, target_date='2026-09-30',
            points=[[x, 75-x/10] for x in range(0,301,30)], baseline_y=75, width=300, height=150,
            games=3000, bb=10, rb=5, max_hold=500, source_url=url)
        for kind, payload in (('table', table), ('graph', graph)):
            source = folder / (kind + '.json')
            source.write_text(json.dumps(payload), encoding='utf-8')
            subprocess.run([str(executable), '--confirm-' + kind, str(source), str(db_path), str(folder / 'reports')],
                env={**os.environ, 'DATABASE_ADVANCE_SIGNAL': str(signal)}, timeout=30, check=True)
            assert signal.exists(), 'missing session-specific completion signal'
            signal.unlink()
        db = Store(db_path)
        try:
            rows = db.rows('2026-09-30', 'Dummy', 'saiwaichou')
            assert len(rows) == 1 and graph_done(rows[0])
        finally:
            db.close()
    print('PASS: packaged browser_import/auto_capture/core match source; frozen table + graph save and private signals')


if __name__ == '__main__':
    check(Path(sys.argv[1]).resolve())
