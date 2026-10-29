"""Publish complete local files without truncating the last good copy."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile


@contextmanager
def atomic_writer(path, *, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb' if binary else 'w', **({} if binary else {'encoding': 'utf-8', 'newline': '\n'})) as out:
            yield out
            out.flush()
            os.fsync(out.fileno())
        # Same-directory rename: a reader sees the previous or the complete new file.
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_copy(source, destination):
    with Path(source).open('rb') as source_file, atomic_writer(destination, binary=True) as out:
        shutil.copyfileobj(source_file, out)
    return Path(destination)


def write_notice(path, message):
    """取り込み窓（別プロセス）から親画面への1回だけの知らせ。書けなくても例外を出さず False を返す。"""
    import json
    from datetime import datetime
    try:
        with atomic_writer(path) as out:
            json.dump({'message': message, 'at': datetime.now().astimezone().isoformat(timespec='seconds')},
                      out, ensure_ascii=False)
        return True
    except OSError:
        return False


def take_notice(path):
    """`write_notice` の文を読んで消す。無い・読めないときは None（読めないファイルも消す）。"""
    import json
    path = Path(path)
    try:
        message = json.loads(path.read_text(encoding='utf-8')).get('message')
    except (OSError, ValueError, AttributeError):
        message = None
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return message if isinstance(message, str) and message else None
