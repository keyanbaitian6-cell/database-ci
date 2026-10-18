import threading
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from core import Store
from output_worker import OutputWorker, refresh_outputs


class OutputWorkerTests(unittest.TestCase):
    def test_pscube_output_uses_its_snapshot_without_creating_a_meruhen_database(self):
        import json
        from pscube_import import PscubeStore, ROOT_URL
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            store = PscubeStore(data / 'pscube.sqlite3')
            try:
                machine = dict(store='c740601', rate='20', machine='試験', expected_count=1,
                               url=ROOT_URL + 'cgi-bin/nc-v05-011.php?cd_ps=2&bai=20')
                row = {k: v for k, v in machine.items() if k not in ('url', 'expected_count')}
                row.update(rack=537, day='2026-10-14', games=3000, bb=10, rb=5, at_art=0, my=1000,
                           detail_url=ROOT_URL + 'cgi-bin/nc-v06-001.php?cd_dai=537#20261014')
                store.import_backup(dict(format='pscube-viewer', version=1, kind='backup', machines=[machine], records=[row]))
            finally: store.close()
            result = refresh_outputs(data / 'database.sqlite3', data, data / 'reports', pscube=True)
            self.assertFalse((data / 'database.sqlite3').exists())
            self.assertEqual(json.loads((data / 'pscube-viewer.json').read_text(encoding='utf-8'))['records'][0]['games'], 3000)
            self.assertIn('pscube_backup', result['timings'])
            self.assertTrue(result['notices'])
            with patch('pscube_import.auto_backup', return_value='バックアップに失敗（取り込みは保存済み）'):
                with self.assertRaisesRegex(OSError, 'pscube_backup'):
                    refresh_outputs(data / 'database.sqlite3', data, data / 'reports', pscube=True)

    def wait_results(self, worker, count):
        results = []
        deadline = time.monotonic() + 3
        while len(results) < count and time.monotonic() < deadline:
            results.extend(worker.poll())
            time.sleep(0.005)
        self.assertEqual(len(results), count)
        return results

    def test_ui_remains_free_and_pending_updates_coalesce_after_running_job(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def run(**flags):
            calls.append((threading.get_ident(), flags))
            if len(calls) == 1:
                entered.set(); release.wait(3)
            return len(calls)
        worker = OutputWorker(run)
        self.addCleanup(release.set); self.addCleanup(worker.finish)
        worker.request(history=True)
        self.assertTrue(entered.wait(1))
        for _ in range(20): worker.request(history=True, backup=True)
        self.assertEqual(len(calls), 1)
        self.assertNotEqual(calls[0][0], threading.get_ident())
        release.set()
        results = self.wait_results(worker, 2)
        self.assertEqual([r.value for r in results], [1, 2])
        self.assertEqual(calls[1][1], {'history': True, 'backup': True})

    def test_failed_output_is_reported_and_next_request_can_succeed(self):
        count = 0
        def run(**flags):
            nonlocal count
            count += 1
            if count == 1: raise OSError('destination unavailable')
            return 'complete'
        worker = OutputWorker(run); self.addCleanup(worker.finish)
        worker.request(backup=True)
        self.assertIsInstance(self.wait_results(worker, 1)[0].error, OSError)
        worker.request(backup=True)
        self.assertEqual(self.wait_results(worker, 1)[0].value, 'complete')

    def test_close_drains_pending_work_without_discarding_callbacks(self):
        done = lambda result: None
        worker = OutputWorker(lambda **flags: flags)
        worker.request(backup=True, done=done); worker.finish()
        result = self.wait_results(worker, 1)[0]
        self.assertEqual(result.callbacks, [done])
        worker.thread.join(1); self.assertTrue(worker.finished)
        with self.assertRaises(RuntimeError): worker.request(backup=True)

    def test_close_skips_pending_history_but_keeps_backup_and_callbacks(self):
        # PC終了時（2026-10-17）：×のあと「過去の記録」（PC内のページ、開くときに作り直す）の作り直しを
        # 10秒以上待っていた。閉じる途中は作らない。バックアップと完了通知は省かない。
        entered, release = threading.Event(), threading.Event()
        calls = []
        def run(**flags):
            calls.append(flags)
            if len(calls) == 1:
                entered.set(); release.wait(3)
            return flags
        done = lambda result: None
        worker = OutputWorker(run)
        self.addCleanup(release.set); self.addCleanup(worker.finish)
        worker.request(backup=True)
        self.assertTrue(entered.wait(1))
        worker.request(history=True, backup=True, done=done)
        worker.finish(); release.set()
        results = self.wait_results(worker, 2)
        self.assertEqual(calls[1], {'history': False, 'backup': True})
        self.assertEqual(results[1].callbacks, [done])
        worker.thread.join(1); self.assertTrue(worker.finished)

    def test_cancelled_history_writes_nothing_and_backup_still_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'data' / 'database.sqlite3'
            store = Store(path)
            store.save([dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine='試験', rack=537,
                             games=3000, bb=10, rb=5)])
            store.close()
            backups = []
            with patch('core.auto_backup', side_effect=lambda db, data, *, strict, notices=None: backups.append(len(db.rows()))):
                result = refresh_outputs(path, root / 'data', root / 'reports', history=True, backup=True,
                                         cancelled=lambda: True)
            self.assertTrue(result['history_cancelled'])
            self.assertIsNone(result['history'])
            self.assertFalse((root / 'reports' / 'database-history.html').exists())
            self.assertEqual(backups, [1], 'backup is written in full from the same snapshot')

    def test_history_report_stops_between_machines_without_writing(self):
        from core import HistoryReportCancelled, history_report
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / 'database.sqlite3')
            try:
                store.save([dict(store='saiwaichou', kind_code=21, day='2026-10-14', machine=f'試験{n}', rack=500 + n,
                                 games=3000, bb=10, rb=5) for n in range(5)])
                checks = []
                def cancelled():
                    checks.append(1)
                    return len(checks) > 3
                with self.assertRaises(HistoryReportCancelled):
                    history_report(store, root / 'reports', cancelled=cancelled)
                self.assertEqual(len(checks), 4, 'checked before reading and between machines')
                self.assertFalse((root / 'reports' / 'database-history.html').exists())
                self.assertTrue(history_report(store, root / 'reports').exists(), 'without cancel it is written')
            finally:
                store.close()

    def test_snapshot_output_does_not_skip_backup_when_report_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root / 'data' / 'database.sqlite3'
            store = Store(path); store.close()
            snapshots = []
            def backup(db, data, *, strict, notices=None):
                snapshots.append(db.path)
                self.assertTrue(strict)
                self.assertNotEqual(db.path, path)
            with patch('core.history_report', side_effect=OSError('report unavailable')), patch('core.auto_backup', side_effect=backup):
                with self.assertRaisesRegex(OSError, 'history: report unavailable'):
                    refresh_outputs(path, root / 'data', root / 'reports', history=True, backup=True)
            self.assertEqual(len(snapshots), 1)
            self.assertFalse(snapshots[0].exists(), 'snapshot connections close before cleanup on Windows too')

    def test_callbacks_are_released_on_the_ui_thread(self):
        released = []
        class Callback:
            def __call__(self, result): pass
            def __del__(self): released.append(threading.get_ident())
        worker = OutputWorker(lambda **flags: None); self.addCleanup(worker.finish)
        worker.request(backup=True, done=Callback())
        result = self.wait_results(worker, 1)
        del result
        self.assertEqual(released, [threading.get_ident()])
