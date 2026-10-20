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
source "$ROOT/database_android/tool/dev_env.sh" || exit 1
LOCAL_ONLY=false
if [ "${1:-}" = '--local' ]; then LOCAL_ONLY=true; elif [ "$#" -gt 0 ]; then echo 'Usage: check_before_build.sh [--local]' >&2; exit 2; fi
# 長い試験の後でSDK不足に気づかないよう、先に確認する。ローカル限定の試験では不要。
if ! $LOCAL_ONLY && ! command -v flutter >/dev/null 2>&1; then
  echo 'Flutterが見つかりません。FLUTTER_ROOTに既存SDKの場所（binの親）を指定してください。' >&2
  exit 1
fi
WORK=${CHECK_BUILD_WORK:-"$ROOT/database_android/build/check_before_build"}
# 同じ確認を重ねて実行するとstage・ログが混ざる。専用の一時フォルダを指定すれば並行作業とも分離できる。
# 初期化は下で作る確認用ディレクトリだけに限定する。リポジトリや広いディレクトリは拒否する。
case "$WORK" in
  ''|'/'|"$ROOT"|"$ROOT/database_android"|"$ROOT/database_android/build")
    echo '確認用ディレクトリが広すぎます。CHECK_BUILD_WORKを専用ディレクトリにしてください。' >&2
    exit 1
    ;;
esac
mkdir -p "$WORK/viewer"
failed=()
unrun=()

run() {
  local name=$1
  shift
  if "$@" > "$WORK/$name.log" 2>&1; then
    echo "OK    $name"
  else
    echo "FAIL  $name  （記録：$WORK/$name.log）"
    # Hosted runners disappear after the job. Keep the actual error in the
    # Actions output as well as the per-test file, with bounded log volume.
    echo "::group::$name failure log (last 120 lines)"
    tail -n 120 "$WORK/$name.log"
    echo '::endgroup::'
    failed+=("$name")
    return 1
  fi
}

cd "$ROOT/database"
run pc-tests "$PYTHON" -m unittest discover -s tests
run pc-pscube-tests bash -c '"$0" -m unittest $(ls test_*.py | sed "s/\.py$//")' "$PYTHON"

# Timestamp serialization must also work when the host uses UTC.
run pc-event-timezone-utc bash -c 'TZ=UTC "$0" -m unittest discover -s tests -p test_event_calendar.py' "$PYTHON"

cd "$ROOT/database_android"
viewer_ready=false
if ! $LOCAL_ONLY; then
  run flutter-test flutter test
  run flutter-analyze flutter analyze --no-fatal-infos
  if run viewer-build bash -c 'MSYS_NO_PATHCONV=1 flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/'; then
    if run viewer-stage "$PYTHON" tool/stage_viewer.py "$WORK/viewer"; then viewer_ready=true; fi
  else unrun+=(viewer-stage); fi
else unrun+=(flutter-test flutter-analyze viewer-build viewer-stage); fi
export VIEWER_WEB_ROOT="$WORK/viewer/"
run share-stage "$PYTHON" tool/stage_share_viewer.py "$WORK/share"
export SHARE_WEB_ROOT="$WORK/share/"
for test in tool/test_*.mjs; do
  # Never test an old build after a failed build or a local-only invocation.
  if ! $viewer_ready && "$PYTHON" -c 'import pathlib,sys; t=pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"); sys.exit(0 if "VIEWER_WEB_ROOT" in t or "build/web" in t else 1)' "$test"; then
    echo "UNRUN $(basename "$test" .mjs) (fresh Flutter build required)"
    unrun+=("$(basename "$test" .mjs)")
    continue
  fi
  run "$(basename "$test" .mjs)" "$NODE" --test "$test"
done

if [ ${#failed[@]} -gt 0 ]; then
  echo "失敗 ${#failed[@]} 件：${failed[*]} （記録：$WORK、ビルドしないで原因を調べる）"
  exit 1
elif $LOCAL_ONLY; then
  echo "LOCAL CHECKS PASSED （未実行 ${#unrun[@]} 件：${unrun[*]}。全体ゲートの成功ではありません）"
elif [ ${#unrun[@]} -gt 0 ]; then
  echo "未実行 ${#unrun[@]} 件：${unrun[*]} （ビルドしない）"
  exit 1
else
  echo "ALL PASSED"
fi
