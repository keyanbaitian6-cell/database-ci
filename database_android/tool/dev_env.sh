#!/usr/bin/env bash
# ビルド前チェックから読み込む。明示指定を優先し、既定はプロジェクト専用Pythonに固定する。
DEV_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [ -z "${PYTHON:-}" ]; then
  if [ -e "$DEV_ROOT/database/.venv" ]; then
    candidates=("$DEV_ROOT/database/.venv/Scripts/python.exe" "$DEV_ROOT/database/.venv/bin/python")
  else
    candidates=("$DEV_ROOT/database/.runtime/Scripts/python.exe")
  fi
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then PYTHON=$candidate; break; fi
  done
fi
if [ -z "${PYTHON:-}" ]; then
  echo '専用Pythonがありません。Windowsは database\setup_python.cmd、Linuxは python3 database/setup_python.py を実行してください。' >&2
  return 1
fi
export PYTHONUTF8=1
"$PYTHON" "$DEV_ROOT/database/setup_python.py" --check || return 1
if command -v cygpath >/dev/null 2>&1; then PYTHON_PATH=$(cygpath -u "$PYTHON"); else PYTHON_PATH=$PYTHON; fi
export PATH="$(dirname "$PYTHON_PATH"):$PATH"
export PYTHON
# デスクトップで確認済みのSDKを優先する。明示したFLUTTER_ROOTがあればその指定を使う。
if [ -n "${FLUTTER_ROOT:-}" ]; then
  if command -v cygpath >/dev/null 2>&1; then flutter_root=$(cygpath -u "$FLUTTER_ROOT"); else flutter_root=$FLUTTER_ROOT; fi
  export PATH="$flutter_root/bin:$PATH"
elif [ -n "${USERPROFILE:-}" ] && command -v cygpath >/dev/null 2>&1; then
  flutter_root=$(cygpath -u "$USERPROFILE")/flutter
  if [ -f "$flutter_root/bin/flutter.bat" ]; then export PATH="$flutter_root/bin:$PATH"; fi
fi
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
