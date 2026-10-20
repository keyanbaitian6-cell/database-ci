import json
from pathlib import Path
import tempfile
import unittest

from core import Store, pull_shared_history, auto_backup, save_settings, SHARED_HISTORY_NAME, AUTO_BACKUP_NAME
from event_history_data import load_base, empty_edits, FILE_NAME
from output_worker import refresh_outputs


class SharedHistoryTests(unittest.TestCase):
    def test_worker_persists_shared_edits_before_snapshot_and_keeps_them_without_shared_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sync = root/'sync'
            sync.mkdir()
            db = Store(root/'test.db')
            try:
                shared = dict(empty_edits(), cells=[self.entry('😍','2026-10-20T00:00:00Z')])
                shared_path = sync/SHARED_HISTORY_NAME
                shared_path.write_text(json.dumps(shared), encoding='utf-8')
                save_settings(root, sync_dir=str(sync))
                refresh_outputs(db.path, root, root/'reports', backup=True)
                self.assertEqual(db.history_edits()['cells'], shared['cells'])
                shared_path.unlink()
                refresh_outputs(db.path, root, root/'reports', backup=True)
                for name, field in [(FILE_NAME,'cells'), (AUTO_BACKUP_NAME,'event_history_edits')]:
                    doc = json.loads((sync/name).read_text(encoding='utf-8'))
                    cells = doc[field] if field == 'cells' else doc[field]['cells']
                    self.assertEqual(cells, shared['cells'])
            finally:
                db.close()

    def test_shared_rejection_count_does_not_include_stored_orphans(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = Store(root/'test.db')
            try:
                old = dict(empty_edits(), cells=[dict(self.entry('😀','2026-10-19T00:00:00Z'), machine='基準外の機種')])
                with db.db:
                    db._write_history_edits(old)
                incoming = dict(empty_edits(), cells=[self.entry('😍','2026-10-20T00:00:00Z')])
                path = root/SHARED_HISTORY_NAME
                path.write_text(json.dumps(incoming), encoding='utf-8')
                self.assertEqual(pull_shared_history(db, root), (1, 0, 0, 0))
                self.assertEqual(db.history_edits_status()[1], 1)
                self.assertIn(old['cells'][0], db.history_edits_raw()['cells'])
                incoming['cells'].append(dict(incoming['cells'][0], machine='共有側の基準外'))
                path.write_text(json.dumps(incoming), encoding='utf-8')
                self.assertEqual(pull_shared_history(db, root), (0, 0, 1, 0))
            finally:
                db.close()

    def test_worker_reports_broken_shared_file_and_still_writes_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sync = root/'sync'
            sync.mkdir()
            db = Store(root/'test.db')
            try:
                shared = dict(empty_edits(), cells=[self.entry('😍','2026-10-20T00:00:00Z')])
                db.merge_history_edits(shared)
                save_settings(root, sync_dir=str(sync))
                (sync/SHARED_HISTORY_NAME).write_text('{broken', encoding='utf-8')
                result = refresh_outputs(db.path, root, root/'reports', backup=True)
                self.assertEqual(sum('共有のイベント履歴を取り込めませんでした' in n for n in result['notices']), 1)
                self.assertEqual(json.loads((sync/FILE_NAME).read_text('utf-8'))['cells'], shared['cells'])
                self.assertEqual((sync/SHARED_HISTORY_NAME).read_text('utf-8'), '{broken')
            finally:
                db.close()

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
