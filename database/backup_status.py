"""共有フォルダへの書き出し結果。Driveへのアップロード完了とは区別する。"""
import json
from datetime import datetime
from pathlib import Path

from file_io import atomic_writer


def status_path(data_dir, source):
    if source not in ('meruhen', 'pscube'):
        raise ValueError('書き出し元が不正です。')
    return Path(data_dir) / f'backup-output-{source}.json'


def read_status(data_dir, source):
    try:
        value = json.loads(status_path(data_dir, source).read_text(encoding='utf-8'))
        return value if (isinstance(value, dict) and value.get('version') == 1
                         and value.get('source') == source
                         and isinstance(value.get('products'), dict)
                         and isinstance(value.get('stores'), list)) else {}
    except (OSError, ValueError):
        return {}


class BackupStatus:
    """自動取り込み・手動再出力の双方から、完成した処理だけを記録する。"""

    def __init__(self, data_dir, source, folder=None):
        self.data_dir, self.source = data_dir, source
        self.folder = str(folder) if folder else None
        self.step = '書き出しの準備'
        self.completed = {}
        self.problems = []
        self.stores = []

    def done(self, product):
        self.completed[product] = datetime.now().astimezone().isoformat()

    def finish(self, state, message=''):
        # 終了時に読み直し、別プロセスが直前に完了した成功時刻を失わない。
        old = read_status(self.data_dir, self.source)
        same_folder = old.get('folder') == self.folder
        success = old.get('last_success_at') if same_folder else None
        products = dict(old.get('products', {})) if same_folder else {}
        products.update(self.completed)
        at = datetime.now().astimezone().isoformat()
        value = dict(version=1, source=self.source, folder=self.folder,
                     state=state, at=at, message=message, stores=self.stores,
                     last_success_at=at if state == 'success' else success,
                     products=products, completed=list(self.completed))
        try:
            with atomic_writer(status_path(self.data_dir, self.source)) as out:
                json.dump(value, out, ensure_ascii=False)
            return True
        except OSError:
            # 状態記録の失敗で、本来のバックアップ処理や取得結果を失敗させない。
            return False


def status_text(data_dir, source, folder):
    label = '長町南・幸町' if source == 'meruhen' else 'P’s CUBE'
    status = read_status(data_dir, source)
    if not folder:
        return f'{label}：同期フォルダ未設定'
    if not Path(folder).is_dir():
        return f'{label}：同期フォルダが見つかりません（ドライブ・接続を確認してください）'
    if not status or status.get('folder') != str(folder):
        return f'{label}：この同期フォルダへの書き出し結果は未確認'

    def when(value):
        try:
            return datetime.fromisoformat(value).astimezone().strftime('%m/%d %H:%M:%S')
        except (TypeError, ValueError):
            return '時刻不明'

    state = {'success': '共有フォルダへ書き出し成功', 'partial': '一部の書き出しに失敗',
             'failed': '書き出し失敗', 'unavailable': '書き出し先を確認してください'}.get(status.get('state'), '結果は未確認')
    lines = [f'{label}：{state}（{when(status.get("at"))}）']
    if status.get('message'):
        lines.append(str(status['message']))
    if status.get('state') != 'success' and status.get('last_success_at'):
        lines.append(f'前回の成功：{when(status["last_success_at"])}')
    if status.get('state') == 'success':
        for item in status.get('stores', []):
            lines.append(f'{item["name"]}：最新の記録日 {item.get("day") or "なし"}・保存済み{item["count"]}件')
    for key, name in [('backup', '全期間バックアップ'), ('viewer', '閲覧用ファイル'),
                      ('history', 'イベント履歴'), ('recent', 'Android用の直近7日分')]:
        if key in status['products']:
            lines.append(f'{name}の最終書き出し：{when(status["products"][key])}')
    return '\n'.join(lines)
