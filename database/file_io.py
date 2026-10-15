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
