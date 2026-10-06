#!/usr/bin/env bash
# ビルド（APK・database/bin）の前に、これまでの修正が再発していないかをまとめて確かめる。
# 2026-10-06 利用者「一回修正したものに関しては再発がないかの確認をしてからビルドしたほうがいい」。
# 修正ごとに足した試験をすべて流す。最後に「ALL PASSED」と出たときだけビルドしてよい。
#
#   bash database_android/tool/check_before_build.sh   （Git Bash、正本フォルダのどこからでも）
#
# 閲覧ページの画面試験は、その場でビルドしたWeb版（記録を除いたステージ）を使う。
# 古い build/web のまま流すと、直した画面でも失敗・成功を誤る（2026-10-06に実際に起きた）。
# PythonとNodeの場所は、この端末の既定値。別の場所なら PYTHON・NODE・PLAYWRIGHT_MODULE で指定する。
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-'C:\Users\keyan\.codex\.chatgpt-projects\g-p-6a9e28549ca0819184c877c6b3b3749e\database\.runtime\Scripts\python.exe'}
NODE=${NODE:-'C:/Users/keyan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'}
export PLAYWRIGHT_MODULE=${PLAYWRIGHT_MODULE:-'file:///C:/Users/keyan/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs'}
WORK="$ROOT/database_android/build/check_before_build"
rm -rf "$WORK"
mkdir -p "$WORK/viewer"
failed=()

run() {
  local name=$1
  shift
  if "$@" > "$WORK/$name.log" 2>&1; then
    echo "OK    $name"
  else
    echo "FAIL  $name  （記録：$WORK/$name.log）"
    failed+=("$name")
  fi
}

cd "$ROOT/database"
run pc-tests "$PYTHON" -m unittest discover -s tests
run pc-pscube-tests bash -c '"$0" -m unittest $(ls test_*.py | sed "s/\.py$//")' "$PYTHON"

cd "$ROOT/database_android"
run flutter-test flutter test
run flutter-analyze flutter analyze --no-fatal-infos
run viewer-build bash -c 'MSYS_NO_PATHCONV=1 flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/'
run viewer-stage "$PYTHON" tool/stage_viewer.py "$WORK/viewer"
export VIEWER_WEB_ROOT="$WORK/viewer/"
for test in tool/test_*.mjs; do
  run "$(basename "$test" .mjs)" "$NODE" --test "$test"
done

if [ ${#failed[@]} -eq 0 ]; then
  echo "ALL PASSED"
else
  echo "失敗 ${#failed[@]} 件：${failed[*]} （ビルドしないで原因を調べる）"
  exit 1
fi
