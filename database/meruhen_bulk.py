"""メルヘン2店舗の一括取り込みの親画面側（2026-11-28 利用者「メルヘン2店舗を一括取り込み」）。

1回押すと「長町南・上 → 長町南・下 → 長町南・10機種目から → 幸町の同じ3つ」の順に取り込み窓（browser_import.py）を
6つ（1店舗3窓）開く（2026-11-28 利用者「上から10機種目から取り込むを実装してほしい。つまり一店舗3画面」）。
対象の営業日は押したときに1回だけ決め（深夜3時までは前日）、全窓に同じ日を渡す。窓が開いたあとに3時をまたいでも、
窓は渡された日のまま取り込む。同じ店・営業日・向きの窓が動いている間は、もう1度押してもその窓は開かない。
窓の中の段取り（店の入口 → 機種一覧 → 上から／下から取り込む、確認画面での待機）は browser_import.BulkStart。
ここは起動・二重起動の防止・親画面に出す状態（準備中／人間認証待ち／取り込み中／完了／中断）だけを受け持つ。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import browser_import as bi


class BulkWindow:
    def __init__(self, store, day, direction, window_id, process):
        self.store, self.day, self.direction = store, day, direction
        self.window_id, self.process = window_id, process
        self.label = bi.bulk_label(store, direction)
        self.finished = None  # 親画面が受け取った完了の文（自分で閉じたとき）

    @property
    def key(self):
        return self.store, self.day, self.direction

    def alive(self):
        return self.process.poll() is None

    def status(self, data_dir):
        """(状態の名前, 表示の文)。窓が閉じたあとは、完了の知らせがあれば完了、無ければ中断（×・停止など）。"""
        if not self.alive():
            if self.finished or bi.finished_path(data_dir, self.window_id).exists():
                return 'done', self.finished or ''
            report = bi.read_bulk_status(data_dir, self.window_id) or {}
            reason = report.get('message') if report.get('state') == 'stopped' else ''
            return 'stopped', reason or '窓が閉じられました'
        report = bi.read_bulk_status(data_dir, self.window_id)
        if not report or report.get('state') not in bi.BULK_STATE_LABELS:
            return 'preparing', '取り込み窓を開いています'
        return report['state'], report.get('message') or ''

    def text(self, data_dir):
        state, message = self.status(data_dir)
        line = f'{self.label}　{bi.BULK_STATE_LABELS[state]}'
        if message and state != 'done':
            line += f'（{message.replace("ON・", "")}）'
        return state, line


class BulkLauncher:
    """一括取り込みの窓（1店舗3窓・計6窓）の起動と見張りの台帳。command_for(window_id) は1窓分の起動コマンド（店・日・向きは足す）。"""

    def __init__(self, data_dir, command_for, popen, today=bi.today_iso):
        self.data_dir = Path(data_dir)
        self.command_for = command_for
        self.popen = popen
        self.today = today
        self.windows: list[BulkWindow] = []

    def running(self, key):
        return any(w.key == key and w.alive() for w in self.windows)

    def launch(self):
        """足りない窓だけを順に開く。戻り値：(開いた窓, 開いていたので飛ばした窓の名前, 開けなかった (名前, 例外))。"""
        day = self.today()  # 全窓で共有する営業日。ここで1回だけ決める
        started, skipped, failed = [], [], []
        for slot, (store, direction) in enumerate(bi.BULK_ORDER):
            key = (store, day, direction)
            if self.running(key):
                skipped.append(bi.bulk_label(store, direction))
                continue
            window_id = uuid.uuid4().hex[:12]
            command = list(self.command_for(window_id)) + [
                '--store', store, '--day', day, '--direction', direction, '--slot', str(slot)]
            try:
                process = self.popen(command)
            except OSError as error:
                failed.append((bi.bulk_label(store, direction), error))
                continue
            window = BulkWindow(store, day, direction, window_id, process)
            self.windows.append(window)
            started.append(window)
        return started, skipped, failed

    def rows(self):
        """親画面に出す行（店・向きごとに最後に開いた窓。開いたことがなければ出さない）。"""
        rows = []
        for store, direction in bi.BULK_ORDER:
            latest = [w for w in self.windows if (w.store, w.direction) == (store, direction)]
            if latest:
                rows.append(latest[-1])
        return rows
