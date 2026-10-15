#!/usr/bin/env bash
# Source from the repository's test entry point. Overrides always take priority.
DEV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [ -z "${PYTHON:-}" ]; then
  for candidate in "$DEV_ROOT/database/.runtime/Scripts/python.exe" "$DEV_ROOT/database/.venv/bin/python" "$DEV_ROOT/database/.venv/Scripts/python.exe"; do
    if [ -x "$candidate" ]; then PYTHON=$candidate; break; fi
  done
  PYTHON=${PYTHON:-$(command -v python3 || command -v python || true)}
fi
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
  echo 'Python 3.10以上を導入するか、PYTHONに実行ファイルを指定してください。' >&2
  return 1
fi
if command -v cygpath >/dev/null 2>&1; then PYTHON_PATH=$(cygpath -u "$PYTHON"); else PYTHON_PATH=$PYTHON; fi
export PATH="$(dirname "$PYTHON_PATH"):$PATH"
export PYTHON
export NODE=${NODE:-$(command -v node || true)}
if [ -z "$NODE" ]; then echo 'Node.jsを導入するか、NODEを指定してください。' >&2; return 1; fi
if [ -z "${PLAYWRIGHT_MODULE:-}" ]; then
  PLAYWRIGHT_MODULE=$("$NODE" -e 'const p=require("node:path"),u=require("node:url");console.log(u.pathToFileURL(p.join(p.dirname(require.resolve("playwright/package.json")),"index.mjs")).href)') || {
    echo 'Playwrightを導入するか、PLAYWRIGHT_MODULEにindex.mjsのfile URLを指定してください。' >&2
    return 1
  }
fi
export PLAYWRIGHT_MODULE
export CHROMIUM_PATH=${CHROMIUM_PATH:-$(command -v chromium || command -v chromium-browser || true)}
export TZ=${TZ:-Asia/Tokyo}
