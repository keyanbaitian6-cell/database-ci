import hashlib
import json
from pathlib import Path
import re
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import app
from core import Store, save_settings
from pscube_import import PscubeStore
from pscube_report import build_report, has_external_day, read_records
from test_pscube_sync import machine, record, put


def seed(path, external=True):
    m = machine('テスト</script><script>alert(1)</script>')
    db = PscubeStore(path)
    put(db, m, [record(m, 101, '2026-08-01', games=0, my=None,
                       source_site='anaslo' if external else 'pscube', net_medals=None),
                record(m, 101, '2026-08-02', my=1234)])
    db.close()
    return m['machine']


class LocalReportTests(unittest.TestCase):
    def test_read_only_data_and_script_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'pscube.sqlite3'
            name = seed(path)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(has_external_day(path, '2026-08-01'))
            self.assertFalse(has_external_day(path, '2026-08-02'))
            output = build_report(path, root / 'reports', '2026-08-01', name)
            text = output.read_text(encoding='utf-8')
            data = json.loads(re.search(r'id="data">(.*?)</script>', text, re.S)[1])
            self.assertEqual(data['day'], '2026-08-01')
            self.assertEqual(data['machine'], name)
            self.assertNotIn(name, text)
            self.assertEqual(data['records'][0]['games'], 0)
            self.assertIsNone(data['records'][0]['my'])
            self.assertIsNone(data['records'][0]['net'])
            self.assertEqual(data['records'][0]['source'], 'アナスロ（補完）')
            self.assertEqual(data['records'][1]['my'], 1234)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            with self.assertRaises(ValueError):
                build_report(path, root, '2026-08-03')

    def test_net_column_shows_real_net_or_a_marked_estimate(self):
        from pscube_report import net_text
        self.assertEqual(net_text({'net_medals': -120}), '-120')
        self.assertEqual(net_text({'net_medals': 0, 'net_estimate': {'value': 50, 'sure': True, 'method': 'x'}}), '+0')
        site777 = {'source_site': 'site777', 'net_medals': None}
        self.assertEqual(net_text({**site777, 'net_estimate': {'value': -700, 'sure': True, 'method': 'site777-axis-pixels-v1'}}), '推定 -700')
        self.assertEqual(net_text({**site777, 'net_estimate': {'value': 1500, 'sure': False, 'method': 'site777-axis-pixels-v1'}}), '推定 +1,500※')
        anaslo = {'source_site': 'anaslo', 'net_medals': None}
        self.assertEqual(net_text({**anaslo, 'net_estimate': {'value': 300, 'sure': True, 'method': 'anaslo-graph-v1'}}), '推定 +300')
        # 方式と出典が合わない・形が違う推定は出さない（MY などを差枚にしない）。
        self.assertIsNone(net_text({**site777, 'net_estimate': {'value': 300, 'sure': True, 'method': 'anaslo-graph-v1'}}))
        self.assertIsNone(net_text({**site777, 'my': 6915}))

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'missing.sqlite3'
            self.assertEqual(read_records(path), [])
            with self.assertRaises(ValueError):
                build_report(path, Path(tmp))
            self.assertFalse(path.exists())

    def test_actual_app_routes_supplements_to_local_database(self):
        self.check_routes(external=True)

    def test_actual_app_keeps_native_result_and_history_routes(self):
        self.check_routes(external=False)

    def check_routes(self, external):
        with tempfile.TemporaryDirectory() as tmp:
            root_path = Path(tmp)
            data = root_path / 'data'
            db = Store(data / 'database.sqlite3')
            db.close()
            name = seed(data / 'pscube.sqlite3', external)
            save_settings(data, auto_sync_on_start=False, sync_dir='', last_store=app.PSCUBE_KEY,
                          last_day='2026-08-01', last_machine=name)
            original_tk = tk.Tk
            roots = []

            def widgets(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from widgets(child)

            def make_root():
                root = original_tk()
                roots.append(root)
                root.withdraw()
                def mainloop():
                    root.update()
                    def click(label):
                        next(w for w in widgets(root) if isinstance(w, ttk.Button)
                             and w.cget('text') == label).invoke()
                    click('この日のまとめ')
                    self.assertEqual(start.call_count, 1)
                    report = Path(start.call_args.args[0])
                    self.assertTrue(report.is_file())
                    self.assertIn('2026-08-01', report.read_text(encoding='utf-8'))
                    click('選んだ機種の結果を開く')
                    click('過去の記録を見る')
                    self.assertEqual(start.call_count, 3 if external else 1)
                    self.assertEqual(browser.call_count, 0 if external else 2)
                    info.assert_not_called()
                root.mainloop = mainloop
                return root

            try:
                with patch.object(app, 'ROOT', root_path), patch.object(app, 'DATA_DIR', data), \
                     patch.object(app.tk, 'Tk', make_root), \
                     patch.object(app.os, 'startfile') as start, \
                     patch('webbrowser.open') as browser, \
                     patch.object(app.messagebox, 'showinfo') as info:
                    app.main()
            finally:
                for root in roots:
                    root.destroy()


if __name__ == '__main__':
    unittest.main()
