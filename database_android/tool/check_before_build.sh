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
case "${CHECK_JS_JOBS:-1}" in
  1|2) ;;
  *) echo 'CHECK_JS_JOBSは1または2を指定してください。' >&2; exit 1 ;;
esac
mkdir -p "$WORK/viewer"
printf 'stage\tresult\tseconds\n' > "$WORK/timings.tsv"
failed=()
unrun=()

run() {
  local name=$1
  shift
  local began=$SECONDS result=passed code=0
  if "$@" > "$WORK/$name.log" 2>&1; then
    echo "OK    $name"
  else
    code=1
    result=failed
    echo "FAIL  $name  （記録：$WORK/$name.log）"
    # CIの実行環境が消えても、元の失敗理由を確認できるようにする。
    echo "::group::$name failure log (last 120 lines)"
    tail -n 120 "$WORK/$name.log"
    echo '::endgroup::'
    failed+=("$name")
  fi
  printf '%s\t%s\t%s\n' "$name" "$result" "$((SECONDS-began))" >> "$WORK/timings.tsv"
  return "$code"
}

cd "$ROOT/database_android"
flutter_deps_ready=false
if ! $LOCAL_ONLY; then
  if run flutter-pub flutter pub get --enforce-lockfile; then flutter_deps_ready=true; fi
fi

cd "$ROOT/database"
# PCの試験はすべて tests/ にある（P’s CUBE・あにすろの試験も2026-11-01に直下から移した）。
run pc-tests "$PYTHON" -m unittest discover -s tests

# Timestamp serialization must also work when the host uses UTC.
run pc-event-timezone-utc bash -c 'TZ=UTC "$0" -m unittest discover -s tests -p test_event_calendar.py' "$PYTHON"

cd "$ROOT/database_android"
viewer_ready=false
if ! $LOCAL_ONLY && $flutter_deps_ready; then
  run flutter-test flutter test --no-pub
  run flutter-analyze flutter analyze --no-pub --no-fatal-infos
  if run viewer-build bash -c 'MSYS_NO_PATHCONV=1 flutter build web --no-pub -t lib/viewer_main.dart --release --base-href /database-viewer/'; then
    if run viewer-stage "$PYTHON" tool/stage_viewer.py "$WORK/viewer"; then viewer_ready=true; fi
  else unrun+=(viewer-stage); fi
else unrun+=(flutter-test flutter-analyze viewer-build viewer-stage); fi
export VIEWER_WEB_ROOT="$WORK/viewer/"
run share-stage "$PYTHON" tool/stage_share_viewer.py "$WORK/share"
export SHARE_WEB_ROOT="$WORK/share/"
# 各ファイルのプロセスとログを分けたまま、CIでは2本ずつ進める。
# 閲覧用ビルドが失敗した場合・--local時の除外規則は従来と同じ。
js_began=$SECONDS
"$NODE" tool/run_js_checks.mjs "$WORK" "$viewer_ready"
js_code=$?
if [ "$js_code" -le 1 ] && [ -f "$WORK/js-failed.txt" ] && [ -f "$WORK/js-unrun.txt" ]; then
  while IFS= read -r name; do [ -z "$name" ] || failed+=("$name"); done < "$WORK/js-failed.txt"
  while IFS= read -r name; do [ -z "$name" ] || unrun+=("$name"); done < "$WORK/js-unrun.txt"
  if [ "$js_code" -eq 1 ] && [ ! -s "$WORK/js-failed.txt" ]; then failed+=(javascript-runner); fi
else
  failed+=(javascript-runner)
fi
js_result=passed
if [ "$js_code" -ne 0 ]; then js_result=failed; fi
printf 'javascript\t%s\t%s\n' "$js_result" "$((SECONDS-js_began))" >> "$WORK/timings.tsv"
if ! "$NODE" tool/run_js_checks.mjs --summary "$WORK"; then failed+=(timing-summary); fi

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
