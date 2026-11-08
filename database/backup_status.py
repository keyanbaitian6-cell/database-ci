"""共有フォルダへの書き出し結果。Driveへのアップロード完了とは区別する。"""
import json
from contextlib import contextmanager
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


# ---- 出力の順番（2026-11-08 保存とバックアップのレビュー1） ----
# PCの出力ワーカーと取り込み窓（別プロセス）は、どちらも「本体DBの写しを取る → 写しから書き出す」。
# 先に写しを取った方が後から書き終えると、新しい全期間・直近7日・閲覧用を古い内容で置き換えていた。
# 写しを取るときに番号（増えるだけ）を受け取り、書き出しの直前に「これより新しい番号の出力が
# もう始まっていないか」を確かめる。番号の発行と写しの取得・書き出しの開始は、
# 書き出し元（メルヘン・P’s CUBE）ごとのファイルの鍵で1つずつにする。時計は使わない
# （時刻の補正で戻ると、新しい写しを古いと誤る）。


def _order_path(data_dir, source):
    status_path(data_dir, source)  # 書き出し元の名前を確かめる
    return Path(data_dir) / f'backup-output-{source}-order.json'


def _read_order(data_dir, source):
    try:
        value = json.loads(_order_path(data_dir, source).read_text(encoding='utf-8'))
        return int(value.get('issued', 0)), int(value.get('written', 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0, 0


def _write_order(data_dir, source, issued, written):
    with atomic_writer(_order_path(data_dir, source)) as out:
        json.dump(dict(issued=issued, written=written), out)


ORDER_WAIT_SECONDS = 600


@contextmanager
def output_lock(data_dir, source, timeout=None):
    """同じ書き出し元の出力の鍵（プロセスをまたぐ）。OSが鍵を持つので、落ちたプロセスの鍵は残らない。"""
    import os
    import time
    status_path(data_dir, source)
    path = Path(data_dir) / f'backup-output-{source}.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + (ORDER_WAIT_SECONDS if timeout is None else timeout)
    with path.open('a+b') as lock:
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b'0')
            lock.flush()
        while True:
            lock.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise OSError('別の書き出しが終わらないため、順番を待ちきれませんでした。次の保存でもう一度書き出します。') from error
                time.sleep(0.2)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_UN)


def issue_ticket(data_dir, source):
    """写しの番号を1つ発行する。output_lock の中で、写しを取る直前に呼ぶ。"""
    issued, written = _read_order(data_dir, source)
    _write_order(data_dir, source, issued + 1, written)
    return issued + 1


@contextmanager
def output_turn(data_dir, source, ticket=None):
    """書き出しの順番。もっと新しい写しからの出力がもう始まっていれば False を渡す（書かずに戻る）。

    ``ticket`` は写しを取ったときの番号。本体DBをそのまま読んで書くとき（写しでない）は None で、
    鍵を取った時点の番号になる（その時点の本体は、それまでのどの写しよりも新しい）。
    """
    with output_lock(data_dir, source):
        issued, written = _read_order(data_dir, source)
        if ticket is None:
            issued += 1
            ticket = issued
        if ticket < written:
            yield False
            return
        _write_order(data_dir, source, max(issued, ticket), ticket)
        yield True
