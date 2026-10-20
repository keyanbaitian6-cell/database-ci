import json
from pathlib import Path
import tempfile
import unittest

from core import Store, pull_shared_history, auto_backup, save_settings, SHARED_HISTORY_NAME, AUTO_BACKUP_NAME
from event_history_data import load_base, empty_edits, FILE_NAME


class SharedHistoryTests(unittest.TestCase):
    def test_merge_locks_before_reading_history(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder)/'test.db')
            try:
                statements = []
                db.db.set_trace_callback(statements.append)
                db.merge_history_edits(dict(empty_edits(), cells=[self.entry('😀','2026-10-20T00:00:00Z')]))
                begin = next(i for i, s in enumerate(statements) if s == 'BEGIN IMMEDIATE')
                read = next(i for i, s in enumerate(statements) if 'SELECT value FROM app_state' in s)
                self.assertLess(begin, read)
                self.assertFalse(db.db.in_transaction)
            finally:
                db.close()

    def entry(self, value, at, device='shared'):
        base = load_base()
        w = base['weeks'][0]
        return dict(store=base['store'], type=w['type'], week=w['from'], machine=w['machines'][0]['name'],
                    day=w['from'], value=value, updated_at=at, device=device)

    def test_shared_symbols_keep_newest_and_allow_blank(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = Store(root/'test.db')
            try:
                for value, at, expected in [('😀','2026-10-20T00:00:00.123456Z','😀'),
                                            ('😍','2026-10-20T00:00:00.123455Z','😀'),
                                            ('','2026-10-20T00:00:00.123457Z','')]:
                    raw = dict(empty_edits(), cells=[self.entry(value, at)])
                    (root/SHARED_HISTORY_NAME).write_text(json.dumps(raw), encoding='utf-8')
                    pull_shared_history(db, root)
                    self.assertEqual(db.history_edits()['cells'][0]['value'], expected)
                    self.assertEqual(db.history_edits()['cells'][0]['device'], 'shared')
                self.assertEqual(pull_shared_history(db, root)[0], 0)
                self.assertEqual(db.db.execute('SELECT COUNT(*) FROM days').fetchone()[0], 0)
            finally:
                db.close()

    def test_shared_file_cannot_change_week_or_machine_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = Store(root/'test.db')
            try:
                before = db.history_edits_raw()
                for field in ['weeks', 'links']:
                    raw = dict(empty_edits(), **{field:[{}]})
                    (root/SHARED_HISTORY_NAME).write_text(json.dumps(raw), encoding='utf-8')
                    with self.assertRaises(ValueError):
                        pull_shared_history(db, root)
                    self.assertEqual(db.history_edits_raw(), before)
                (root/SHARED_HISTORY_NAME).write_text('{broken', encoding='utf-8')
                with self.assertRaises(ValueError):
                    pull_shared_history(db, root)
                self.assertEqual(db.history_edits_raw(), before)
            finally:
                db.close()

    def test_outputs_import_shared_before_writing_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sync = root/'sync'
            sync.mkdir()
            db = Store(root/'test.db')
            try:
                shared = dict(empty_edits(), cells=[self.entry('😍','2026-10-20T00:00:00Z')])
                (sync/SHARED_HISTORY_NAME).write_text(json.dumps(shared), encoding='utf-8')
                save_settings(root, sync_dir=str(sync))
                auto_backup(db, root, strict=True)
                for name, field in [(FILE_NAME,'cells'), (AUTO_BACKUP_NAME,'event_history_edits')]:
                    doc = json.loads((sync/name).read_text(encoding='utf-8'))
                    cells = doc[field] if field == 'cells' else doc[field]['cells']
                    self.assertEqual(cells[0]['value'], '😍')
                later = dict(empty_edits(), cells=[self.entry('😀','2026-10-20T00:00:01Z','pc')])
                db.merge_history_edits(later)
                auto_backup(db, root, strict=True)
                self.assertEqual(db.history_edits()['cells'][0]['value'], '😀')
            finally:
                db.close()
