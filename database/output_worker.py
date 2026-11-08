"""One background writer; queued refreshes are combined, never run in parallel."""
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Condition, Thread


def refresh_outputs(database_path, data_dir, reports_dir, *, history=False, backup=False, pscube=False, cancelled=None):
    """共有編集を本体DBへ取り込み、隔離したSQLiteの写しから出力する。

    ``cancelled`` (PC版を閉じている途中なら true) stops the local history page;
    backups and the viewer files are still written in full."""
    import sqlite3
    import tempfile
    from contextlib import closing, contextmanager
    from pathlib import Path
    from time import perf_counter
    from core import HistoryReportCancelled, Store, auto_backup, sync_shared_history, history_report

    @contextmanager
    def snapshot_store(path, factory, source_name):
        with tempfile.TemporaryDirectory(prefix='database-output-') as directory:
            snapshot = Path(directory) / 'snapshot.sqlite3'
            try:
                # 写しを取る間だけ出力の鍵を持ち、写しの番号を付ける。取り込み窓など別プロセスの出力と
                # 書き終わりの順が入れ替わっても、古い写しで新しい出力を上書きしない（backup_status.output_turn）。
                from backup_status import issue_ticket, output_lock
                with output_lock(data_dir, source_name):
                    ticket = issue_ticket(data_dir, source_name)
                    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(snapshot)) as destination:
                        source.backup(destination)
                store = factory(snapshot, recording=False)
                store.output_ticket = ticket
            except Exception as error:
                if source_name == 'pscube':
                    from backup_status import BackupStatus
                    from core import load_settings
                    BackupStatus(data_dir, source_name, load_settings(data_dir).get('sync_dir')).finish(
                        'failed', f'保存済みの記録の読み取り：{error}')
                raise
            try:
                yield store
            finally:
                store.close()

    timings, errors, notices = {}, [], []
    result = {'timings': timings, 'history': None, 'pending_marks': 0, 'notices': notices}
    def run(name, task):
        started = perf_counter()
        try:
            return task()
        except Exception as error:
            errors.append(f'{name}: {error}')
            if name == 'meruhen' and backup:
                from backup_status import BackupStatus
                from core import load_settings
                BackupStatus(data_dir, 'meruhen', load_settings(data_dir).get('sync_dir')).finish(
                    'failed', f'共有用ファイルの書き出し準備：{error}')
        finally:
            timings[name] = perf_counter() - started
    def meruhen_output():
        if backup:
            # 共有の取り込みは必ず本体へ保存してから写す。写しだけへの合流は次回の出力で失われる。
            if not Path(database_path).is_file():
                raise FileNotFoundError(database_path)
            # 本体DBを開けない（ロック中など）ときも、取り込みだけ諦めてバックアップは書く。
            try:
                with closing(Store(database_path)) as source:
                    sync_shared_history(source, data_dir, notices)
            except (OSError, sqlite3.Error) as error:
                notices.append(f'共有のイベント履歴を取り込めませんでした（元の記録は保持）：{error}')
        with snapshot_store(database_path, Store, 'meruhen') as store:
            if history:
                def build_history():
                    try:
                        return history_report(store, reports_dir, cancelled=cancelled)
                    except HistoryReportCancelled:
                        result['history_cancelled'] = True
                result['history'] = run('history', build_history)
            if backup:
                value = run('backup', lambda: auto_backup(store, data_dir, strict=True, notices=notices, import_shared=False))
                if value is None and not errors:
                    notices.append('同期フォルダ未設定：PC内のバックアップのみ更新しました。')
            result['pending_marks'] = len(store.pending_rainbow_marks())
    if history or backup:
        run('meruhen', meruhen_output)
    if pscube:
        import pscube_import
        def pscube_output():
            with snapshot_store(Path(data_dir) / 'pscube.sqlite3', pscube_import.PscubeStore, 'pscube') as store:
                status = pscube_import.auto_backup(store, Path(data_dir) / 'pscube-viewer.json')
                if '失敗' in status:
                    raise OSError(status)
                if '未設定' in status:
                    notices.append(status)
        run('pscube_backup', pscube_output)
    if errors:
        raise OSError('、'.join(errors))
    return result


@dataclass
class OutputResult:
    value: object
    error: Exception | None
    callbacks: list


class OutputWorker:
    def __init__(self, run):
        self.run = run
        self.condition = Condition()
        self.pending = {}
        self.callbacks = []
        self.callback_map = {}
        self.callback_serial = 0
        self.results = Queue()
        self.thread = None
        self.closing = False

    def request(self, *, history=False, backup=False, pscube=False, done=None):
        with self.condition:
            if self.closing:
                raise RuntimeError('Output worker is closing')
            self.pending['history'] = self.pending.get('history', False) or history
            self.pending['backup'] = self.pending.get('backup', False) or backup
            if pscube:
                self.pending['pscube'] = True
            if done:
                # Keep Tk closures on the calling thread. Worker results contain
                # only integer IDs, including after the UI consumes the result.
                self.callback_serial += 1
                self.callback_map[self.callback_serial] = done
                self.callbacks.append(self.callback_serial)
            if self.thread is None:
                self.thread = Thread(target=self._work, name='database-output', daemon=True)
                self.thread.start()
            self.condition.notify()

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.closing)
                if not self.pending:
                    return
                # Combine consecutive UI requests without delaying the UI thread.
                if not self.closing:
                    self.condition.wait(timeout=0.05)
                options, callbacks = self.pending, self.callbacks
                self.pending, self.callbacks = {}, []
                if self.closing:
                    # 「過去の記録」はPC内だけのページで、開くときに必ず作り直す。閉じる途中では作らない
                    # （実データ規模で10秒以上、×を押してから閉じるまで待たせていた。2026-10-17）。
                    # バックアップ・閲覧用ファイルは省かない。
                    options['history'] = False
            try:
                result = OutputResult(self.run(**options), None, callbacks)
            except Exception as error:
                result = OutputResult(None, error, callbacks)
            self.results.put(result)

    def poll(self):
        while True:
            try:
                result = self.results.get_nowait()
                callbacks = [self.callback_map.pop(key) for key in result.callbacks]
                yield OutputResult(result.value, result.error, callbacks)
            except Empty:
                return

    def finish(self):
        with self.condition:
            self.closing = True
            self.condition.notify()

    @property
    def finished(self):
        return self.closing and (self.thread is None or not self.thread.is_alive())
