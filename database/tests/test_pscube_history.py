import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pscube_import import PscubeStore, _record_key, latest_pscube_backup, is_pscube_backup
from test_pscube_sync import machine, record, long_graph


class CloudHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PscubeStore(self.root / 'test.sqlite3')
        self.addCleanup(self.store.close)
        self.index = self.root / 'database-viewer-parts-pscube.json'
        self.refs = []
        m = machine()
        for day in ('2025-01-01', '2026-10-14'):
            r = record(m, 1, day, graph=long_graph())
            doc = {'format': 'pscube-viewer', 'version': 1, 'machines': [m], 'records': [r],
                   'rack_captures': [_record_key(r)]}
            raw = json.dumps({'site': 'pscube', 'day': day, 'data': doc}, ensure_ascii=False).encode()
            digest = hashlib.sha256(raw).hexdigest()
            name = f'database-history-day-pscube-{day}-{digest}.json'
            (self.root / name).write_bytes(raw)
            self.refs.append(dict(day=day, hash=digest, bytes=len(raw), name=name, count=1))
        self.save_index()

    def save_index(self, **extra):
        self.index.write_text(json.dumps({'format': 'database-viewer-parts', 'version': 2, 'site': 'pscube',
            'days': [r['day'] for r in self.refs], 'cloud_days': self.refs, 'count': len(self.refs), **extra}), encoding='utf-8')

    def test_all_days_graphs_captures_and_latest_button(self):
        self.assertEqual(latest_pscube_backup(self.root), self.index)
        self.assertTrue(is_pscube_backup(self.index))
        self.assertEqual(self.store.import_backup(self.index)['added'], 2)
        payload = self.store.export_payload('backup')
        self.assertEqual(len(payload['records']), 2)
        self.assertEqual(len(payload['rack_captures']), 2)
        self.assertEqual(len(payload['records'][0]['graph']['points']), 60)
        self.assertEqual(self.store.import_backup(self.index)['added'], 0)

    def test_missing_or_corrupt_later_day_changes_nothing(self):
        (self.root / self.refs[1]['name']).write_text('{}')
        with self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.assertEqual(self.store.export_payload('backup')['records'], [])

    def test_change_after_preflight_rolls_back_earlier_days(self):
        original = Path.read_bytes
        reads = 0

        def racing(path):
            nonlocal reads
            if path.name.startswith('database-history-day-'):
                reads += 1
                if reads == 4:
                    return b'changed'
            return original(path)

        with patch.object(Path, 'read_bytes', racing), self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.assertEqual(self.store.export_payload('backup')['records'], [])

    def test_pending_migration_and_path_escape_rejected(self):
        self.save_index(history_progress={'file': {'next': 24}})
        with self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.refs[1]['name'] = '../' + self.refs[1]['name']
        self.save_index()
        with self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.assertEqual(self.store.export_payload('backup')['records'], [])

    def test_count_and_day_mismatch_rejected_before_import(self):
        self.save_index(count=999)
        with self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.save_index(days=['2020-01-01', '2020-01-02'])
        with self.assertRaises(ValueError):
            self.store.import_backup(self.index)
        self.assertEqual(self.store.export_payload('backup')['records'], [])


if __name__ == '__main__':
    unittest.main()
