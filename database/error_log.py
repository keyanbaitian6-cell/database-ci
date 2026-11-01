"""続行のために捕まえた例外を、後から調べられるように記録する（2026-11-01）。

取り込み窓の見張り（0.1秒ごと）などは、失敗しても止めずに次の回でやり直す。以前はその失敗を
黙って捨てていたため、窓が閉じない・進まないときに理由を区別できなかった。

- 書き先は data フォルダーの `errors.log`（タブ区切り：時刻・場所・例外・発生行）。同期・バックアップの対象外。
- 同じ場所・同じ内容は60秒に1回だけ書く。256KiBを超えたら `errors.log.1` へ1世代だけ残す。
- 記録そのものの失敗では呼び出し元を止めない。Cookie・入力値は書かない（例外・画面に出したエラーの文字列だけ）。
- 入れ替え（新台・台番号の変更）のときに画面に出る保存・読み取りの失敗も残す（2026-11-01 利用者「毎回エラーがでているので修正に役立ちます」）。
"""
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

FILE_NAME = 'errors.log'
MAX_BYTES = 256 * 1024
REPEAT_SECONDS = 60.0
MESSAGE_LIMIT = 500

_lock = threading.Lock()
_last = {}


def _origin(error):
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    if not frames:
        return ''
    frame = frames[-1]
    return f'{Path(frame.filename).name}:{frame.lineno} {frame.name}'


def record(directory, where, error, *, detail='', clock=time.monotonic, now=None):
    """例外を `directory/errors.log` に1行足す。detail（ページのURLなど）は例外の文の後ろに添える。
    書いたらTrue（間引き・失敗はFalse）。"""
    try:
        text = type(error).__name__ + ': ' + _clean(error) + (f'（{_clean(detail)}）' if detail else '')
        return _write(directory, where, text, _origin(error), clock, now)
    except Exception:  # noqa: BLE001 - 記録の失敗で取り込みを止めない
        return False


def note(directory, where, message, *, clock=time.monotonic, now=None):
    """画面に出したエラーの文章（例外を伴わないもの）を1行足す。書いたらTrue。"""
    try:
        return _write(directory, where, _clean(message), '', clock, now)
    except Exception:  # noqa: BLE001 - 記録の失敗で取り込みを止めない
        return False


def _clean(value):
    return ' '.join(str(value).split())[:MESSAGE_LIMIT]


def _write(directory, where, text, origin, clock, now):
    key = (str(directory), where, text)
    with _lock:
        moment = clock()
        if key in _last and moment - _last[key] < REPEAT_SECONDS:
            return False
        _last[key] = moment
        path = Path(directory) / FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_name(FILE_NAME + '.1'))
        stamp = (now or datetime.now().astimezone()).isoformat(timespec='seconds')
        with path.open('a', encoding='utf-8', newline='\n') as handle:
            handle.write('\t'.join([stamp, where, text, origin]) + '\n')
    return True


def forget():
    """試験用：間引きの記憶を消す。"""
    with _lock:
        _last.clear()
