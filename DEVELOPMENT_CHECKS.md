# 開発時の確認

正本の既存チェックアウトを使う。PCの起動は `database/start.cmd` を維持し、EXEの作成は不要。

## 共通の入口

クラウド・CIではPython 3.12、Node.js 24、Flutter 3.47.1（`.metadata` の6655482ec0、Dart 3.13.1）を使用する。
デスクトップでは既存のPythonからプロジェクト専用の `database/.venv` を作り、その実行ファイルを使い続ける。Pythonは3.10以上、Windowsは64ビット版。既存の3.14を3.12へ入れ替える必要はない。
Python依存は `database/requirements.txt` の固定版、Flutter依存は `pubspec.lock` のまま導入する。
空の環境では `database_android/assets/database_seed.example.json` を同じ場所の `database_seed.json` へコピーする。既存ファイルを上書きしない。

```bash
python3 database/setup_python.py
bash database_android/tool/check_before_build.sh
```

### Windowsで一度だけ行う準備

正本を更新して `database/setup_python.cmd` をダブルクリックする。既存の `.runtime`、なければ `py -3` を作成元にして `.venv` を作り、固定版の依存を入れ、`pip check` と実際のライブラリ読み込みを確認する。既存の `.venv` があれば作り直さず再利用する。セットアップをもう一度実行するときも同じ入口を使う。DB・設定・同期先・既存の `.runtime` は変更しない。

以後は普段どおり `database/start.cmd` から起動する。起動とビルド前チェックは `.venv` を優先し、まだ作成していない既存環境では `.runtime` を引き継ぐ。`.venv` が存在するのに壊れているときは、別のPythonへ自動で切り替えず停止する。無関係なシステムの `python` や `python3` は自動で選ばない。

AIがPCでPythonを直接実行するときも `database/.venv/Scripts/python.exe` を指定する。クラウドの実行ファイルや「Python 3.12を使う」という記述を、デスクトップの実行先として扱わない。Pythonの不調時は、再インストールや版の変更を始める前に、次の検査で選んだ実行ファイルと不足項目を確認する。

```powershell
database\.venv\Scripts\python.exe database\setup_python.py --check
```

ビルド前チェックはGit Bashで実行する。必要なパッケージの固定版・Tkinter・SQLite・SSLと実際のライブラリ読み込みを試験の前に確認し、不足時はセットアップの入口を案内して停止する。毎回の起動・ビルドで依存をインストールし直さない。

`tool/dev_env.sh` がリポジトリのPython環境、Node、Playwrightを選ぶ。意図的に別の場所を使う場合は `PYTHON`、`NODE`、`PLAYWRIGHT_MODULE`（index.mjsのfile URL）、`CHROMIUM_PATH` を指定できる。明示した `PYTHON` が使えなくても別のものへは切り替えない。

Flutterは既存のSDKを使う。`FLUTTER_ROOT` にSDKの場所（`bin` の親）を指定できる。未指定のWindowsでは、以前確認した `%USERPROFILE%/flutter/bin` にSDKがあればそこを優先する。通常のビルド前チェックはFlutterコマンドの有無も試験の前に確認する。この処理はSDKのインストールや版の変更を行わない。

Playwrightと対応Chromiumの導入は利用する開発環境で行う。LinuxのTk試験にはXサーバーが必要で、画面のない環境では `xvfb-run -a bash database_android/tool/check_before_build.sh` を使う。

クラウドでは `source /workspace/.cloud-setup/env.sh` で導入済みツールを有効化できる。ホームが読み取り専用の場合、`PUB_CACHE`、`XDG_CONFIG_HOME`、`ANALYZER_STATE_LOCATION_OVERRIDE` を書き込み可能な作業用ディレクトリへ向ける。`DASH__SUPPRESS_ANALYTICS=true` はDartがホームへ分析設定を書こうとするのを抑止する。証明書・チェックサムの検証は無効化しない。

Flutterのない環境でも `bash database_android/tool/check_before_build.sh --local` でPC・ビルド不要のJS試験を実行できる。未実行項目を列挙し、`LOCAL CHECKS PASSED` は全体ゲートの成功ではない。APKや公開用のビルドの条件は、引き続き通常実行での `ALL PASSED`。

通常実行は閲覧ページをその場で生成・ステージしてから試験する。生成に失敗した場合は古い成果物を試験しない。試験用成果物から公開はしない。

## 更新の仕様と障害時の確認

- P’s CUBEの差枚は日ごとに検査する。空・1点だけ・片側欠損・不正座標の日は差枚不明のままにし、正常日の正負・0枚を残す。日付・系列の重複や不正な単位など対応を確定できない応答は全体を拒否する。選択日が欠測でもPC/Androidの取り込みは正常な過去日を保存する。手動貼り付けの選択日確認は維持する。`test_pscube_net_days.mjs` と生成済み取得スクリプトの実ブラウザ試験で確認する。自動再試行や追加のサイト通信は行わない。
- JSON・バックアップは同じ保存先の一時ファイルへ書き、flush/fsync後に置き換える。一時ファイルは `.tmp` で同期入力のJSONに含めない。コピー・置き換え失敗時は前回の完成版を保持する。
- 明示削除は `record_deletions`（店舗・日付・機種・台番号・deleted_at）でPC/AndroidのバックアップとPC閲覧用へ運ぶ。期間外へ出た日を削除と推測しない。削除時刻より新しい取得・明示復元は許可する。復元操作の `record_updated_at` は元の取得時刻と別に記録する。
- メルヘンのGoogle同期は履歴モードで削除情報を日別原本に保持する。古いAndroid入力は削除済みの台を復活させない。旧モードで削除情報を持つAndroid入力を受けた場合は黙って捨てず停止・通知する。
- PCの重いレポート・バックアップ出力は、1本のワーカーがSQLiteの専用コピーから行う。連続要求はまとめ、GUIの操作・通知はメインスレッドで行う。終了時は保留中の出力を待つ。DB保存と出力失敗は区別して知らせる。
- 閲覧履歴の再起動読み込みは1日ずつハッシュ検査する。全期間の検索・集計用のレコードは保持する。同時更新を検出した読み出しは取り直しを求め、異なる版を混ぜない。
- iPhone閲覧ページの手動JSONは `web/backup_stream.mjs` で台ごとに解析する。改行なし・整形JSONでも画像入りの全文を一括解析しない。外枠も末尾まで検査してから保存し、途中の結果をIndexedDBへ書かない。
- 手動読み込み・Drive更新・自動読み込み設定の切り替えは重ねない。手動読み込み時の旧イベントは、保存済みJSONから台の値を組み立てずに取り出し、別タブの入力も引き継ぐ。`skipRecordValues` はこの保存済みメタデータの読み出し専用であり、未検査ファイルの受け入れには使わない。
- `ViewerData.preparePicked` / `prepareMerge` は解析済みの内容から表示モデルを作り、同じ全文の再解析を避ける。保存成功後に表示を切り替え、解析・保存の失敗では旧データを保持する。`test_viewer_import_browser.mjs` はメルヘン・P’s CUBEで競合、別タブのイベント、破損JSON、IndexedDBの明示中断を実際の生成物で確認する。iPhone Safari実機の容量限界は別途確認が必要。

回帰試験は `database/tests`（PCの試験はすべてここ。2026-11-01に直下の `test_*.py` を移した）・`database_android/test`・`database_android/tool/test_*.mjs` に置く。GitHub ActionsはLinux/Windows、JST/UTCのPC試験と、Linuxの全体ゲートを実行する。実機・実Googleの動作確認とは区別する。

コードを含むmainへのpushでCIが動き、GitHubの通知設定に応じて結果メールが届く。**push前に日本時間の日付を確認し、1〜15日は `imakurudev-eng/database`、16日〜月末は `keyanbaitian6-cell/database-ci` だけへ送る。** 正本の指定は変えず、両リポジトリの履歴を1本に保つ。送り先にだけある変更を取得・統合してから送る。期間外へのpush、CI失敗の原因を調べない再実行、強制pushは行わない。詳しくは `AGENTS.md` の10/20の規則を参照する。

メールはジョブの成否だけを示す。全体ゲートが失敗した場合は、Actionsの `Complete pre-build gate` 内の失敗名のグループにエラー本文の末尾120行を表示する。全体ゲートのログファイルも `regression-full-logs` のartifactとして7日間保存する。`test_rainbow_today_browser` は共有／Flutter閲覧と320／393pxを個別の試験名で表示する。

一時フォルダー内のSQLiteは、フォルダーを削除する前に必ず閉じる。`with TemporaryDirectory()` 内で `addCleanup(store.close)` だけを登録すると、接続を閉じるより先にフォルダー削除が走り、Windowsで失敗する。内側の `with closing(Store(...))` または `try/finally` を使う。Storeの初期化中に例外が起きた場合は、コンストラクター自身が接続を閉じる。バックアップ・削除同期と壊れたDBからの再出力の6試験には、Linuxでも同じ寿命違反を検出する `test_sqlite_fixture_cleanup.py` がある。

## 試験を省かずに実行時間を短くする（D）

GitHubのfullジョブは `CHECK_JS_JOBS=2` でJSファイルを2本ずつ実行する。PCのUbuntu/UTC・Windows/UTCと、fullの日本時間という条件は維持する。Windowsのローカル確認にも同じ実行制御を使うため、新しい制御の7試験だけはWindowsでも確認し、UbuntuのPCジョブには重ねない。

手元の既定は従来どおり1本ずつ。クラウドで2本ずつ動かす場合は次を使う。設定は1または2だけを受け付ける。Flutterの試験・解析・ビルドを同時に動かす変更ではない。

```bash
CHECK_JS_JOBS=2 bash database_android/tool/check_before_build.sh
```

試験の一覧は毎回 `tool/test_*.mjs` から全件集める。各ファイルを1回だけ、従来と同じ独立したNodeプロセスで実行し、ログもファイルごとに残す。並行中の失敗・起動失敗も集約する。新しい閲覧ビルドが無い場合の未実行を成功へ置き換えない。診断用の画面試験は別ポート・別のブラウザ保存領域、保存を伴う試験は固有の一時フォルダーを使う。取得元サイトへの通信を増やさない。

通常のゲートはAndroidプロジェクトのディレクトリで `flutter pub get --enforce-lockfile` を1回実行し、以後のtest・analyze・buildには `--no-pub` を渡す。依存解決に失敗したら、古い依存設定によるFlutter確認・閲覧ビルドは実行しない。lockfileとSDKの固定版は変更しない。CIのfullでもPCジョブと同じpipキャッシュ指定を使う。SDK・ブラウザ・ビルド済みの閲覧画面は今回キャッシュしない。

ログの隣に `timings.tsv`（工程別の結果と秒）、`js-results.json`（全JSファイルの結果・実時間・実測同時数）、`timings.md`（表示用の要約）を出す。CIの概要に要約を表示し、`regression-timings` artifactに7日間保存する。これらは実行時に生成する出力であり、リポジトリのMarkdownを試験の入力にはしない。失敗時の完全なログと末尾120行の表示は維持する。

時間を比較するときは、ジョブ全体の時間と実行条件を合わせる。以前のCIでは依存解決がゲートの外、現在はゲート内の `flutter-pub` なので、「Complete pre-build gate」だけの前後比較はしない。Windowsの2倍とジョブ単位の分の切り上げも考慮し、実行時間の短縮と無料枠の削減を区別する。

2026-10-25の比較では、GitHubのfullジョブが14分10秒→10分57秒、Windowsを2倍・ジョブごとの分の切上げを含む概算が22分→19分。手元のJS部分は189.21秒→111.18秒だった。基準実行 `40095966372`、改善後 `40117213308`（`cf0fe74`）、いずれも3ジョブ成功。1回ずつの実測で、負荷・キャッシュにより変動する。JSは従来67ファイルを残して1ファイル追加し、成功349→358件、従来からの保存例未配置によるスキップ1件は両方とも未確認のまま。

## GoogleとWebへの反映

ソースの修正やmainへのpushだけで既存のGoogle Apps Script・公開ページは更新されない。
`node database_android/tool/build_viewer_parts.mjs` で生成したGSを、[VIEWER_HISTORY_SYNC.md](database_android/VIEWER_HISTORY_SYNC.md) の既存デプロイ更新手順で反映する。メルヘン同期の既存設定値・履歴フラグ・フォルダ指定・プロパティを保持する。新たなGoogleプロジェクトや同期先を作らない。
PC→Google→Webで最後の1台の削除、古いバックアップの再投入、明示復元を照合する。AndroidのDrive保存→キャンセル→再起動→再保存、実iPhoneの長期容量・速度は実機確認が必要。
