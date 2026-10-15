import json
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from file_io import atomic_copy, atomic_writer
from core import Store, auto_backup, save_settings, AUTO_BACKUP_NAME


class AtomicBackupTests(unittest.TestCase):
    def test_interrupted_copy_preserves_previous_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.json', root / 'backup.json'
            source.write_bytes(b'new completed backup')
            target.write_bytes(b'previous completed backup')
            def interrupt(input_file, output_file):
                output_file.write(input_file.read(3))
                raise OSError('disk full')
            with patch('file_io.shutil.copyfileobj', side_effect=interrupt):
                with self.assertRaises(OSError):
                    atomic_copy(source, target)
            self.assertEqual(target.read_bytes(), b'previous completed backup')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['backup.json', 'source.json'])

    def test_failed_replace_and_fsync_leave_valid_previous_json(self):
        for operation in ('os.replace', 'os.fsync'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'backup.json'
                target.write_text('{"version": 1}')
                with patch('file_io.' + operation, side_effect=OSError('unavailable')):
                    with self.assertRaises(OSError):
                        with atomic_writer(target) as out:
                            json.dump({'version': 2}, out)
                self.assertEqual(json.loads(target.read_text()), {'version': 1})
                self.assertEqual(list(target.parent.iterdir()), [target])

    def test_shared_backup_failure_keeps_last_copy_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); shared = root / 'shared'; shared.mkdir()
            data = root / 'data'
            with closing(Store(data / 'database.sqlite3')) as store:
                store.save([dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537, games=3000, bb=10, rb=5)])
                save_settings(data, sync_dir=str(shared))
                auto_backup(store, data)
                target = shared / AUTO_BACKUP_NAME; previous = target.read_bytes()
                def interrupt(source, out):
                    out.write(source.read(30))
                    raise OSError('interrupted')
                with patch('file_io.shutil.copyfileobj', side_effect=interrupt):
                    self.assertIsNone(auto_backup(store, data))
                    with self.assertRaises(OSError):
                        auto_backup(store, data, strict=True)
                self.assertEqual(target.read_bytes(), previous)
                self.assertEqual(len(store.rows()), 1)
