"""Catch Windows-only fixture cleanup failures on every CI operating system."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_atomic_backup as atomic_fixtures
import test_record_deletions as deletion_fixtures


class SqliteFixtureCleanupTests(unittest.TestCase):
    def test_backup_and_deletion_fixtures_close_connections_before_removing_files(self):
        cases = [
            atomic_fixtures.AtomicBackupTests('test_shared_backup_failure_keeps_last_copy_and_database'),
            deletion_fixtures.RecordDeletionTests('test_last_row_deletion_is_exported_and_old_backup_cannot_resurrect_it'),
            deletion_fixtures.RecordDeletionTests('test_deletion_roundtrip_preserves_unrelated_rows_and_explicit_restore'),
            deletion_fixtures.RecordDeletionTests('test_invalid_deletion_rejects_whole_input'),
        ]
        connect, cleanup = sqlite3.connect, tempfile.TemporaryDirectory.cleanup
        connections = []

        def track_connect(database, *args, **kwargs):
            connection = connect(database, *args, **kwargs)
            # Keep references so a GC run cannot hide missing explicit closes.
            connections.append((connection, Path(database).resolve()))
            return connection

        def check_cleanup(folder):
            inside = [connection for connection, path in connections
                      if path.is_relative_to(Path(folder.name).resolve())]
            try:
                for connection in inside:
                    with self.assertRaises(sqlite3.ProgrammingError,
                                           msg='SQLite must close before temporary files are removed'):
                        connection.execute('SELECT 1')
            finally:
                # Leave no locked files even when checking the broken fixture.
                for connection in inside:
                    connection.close()
                cleanup(folder)

        result = unittest.TestResult()
        with patch('sqlite3.connect', side_effect=track_connect), \
             patch.object(tempfile.TemporaryDirectory, 'cleanup', check_cleanup):
            unittest.TestSuite(cases).run(result)
        self.assertEqual(result.testsRun, len(cases))
        self.assertFalse(result.errors + result.failures, result.errors + result.failures)
