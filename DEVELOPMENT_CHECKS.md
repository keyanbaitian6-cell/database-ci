# 開発時の確認

正本の既存チェックアウトを使う。PCの起動は `database/start.cmd` を維持し、EXEの作成は不要。

## 共通の入口

クラウド・CIではPython 3.12、Node.js 24、Flutter 3.47.1（`.metadata` の6655482ec0、Dart 3.13.1）を使用する。
デスクトップでは既存のPythonからプロジェクト専用の `database/.venv` を作り、その実行ファイルを使い続ける。Pythonは3.10以上、Windowsは64ビット版。既存の3.14を3.12へ入れ替える必要はない。
Python依存は `database/requirements.txt` の固定版、Flutter依存は `pubspec.lock` のまま導入する。
空の環境では `database_android/assets/database_seed.example.json` を同じ場所の `database_seed.json` へコピーする。既存ファイルを上書きしない。

```bash
python3 database/setup_python.py
cd database_android
flutter pub get --enforce-lockfile
cd ..
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

- JSON・バックアップは同じ保存先の一時ファイルへ書き、flush/fsync後に置き換える。一時ファイルは `.tmp` で同期入力のJSONに含めない。コピー・置き換え失敗時は前回の完成版を保持する。
- 明示削除は `record_deletions`（店舗・日付・機種・台番号・deleted_at）でPC/AndroidのバックアップとPC閲覧用へ運ぶ。期間外へ出た日を削除と推測しない。削除時刻より新しい取得・明示復元は許可する。復元操作の `record_updated_at` は元の取得時刻と別に記録する。
- メルヘンのGoogle同期は履歴モードで削除情報を日別原本に保持する。古いAndroid入力は削除済みの台を復活させない。旧モードで削除情報を持つAndroid入力を受けた場合は黙って捨てず停止・通知する。
- PCの重いレポート・バックアップ出力は、1本のワーカーがSQLiteの専用コピーから行う。連続要求はまとめ、GUIの操作・通知はメインスレッドで行う。終了時は保留中の出力を待つ。DB保存と出力失敗は区別して知らせる。
- 閲覧履歴の再起動読み込みは1日ずつハッシュ検査する。全期間の検索・集計用のレコードは保持する。同時更新を検出した読み出しは取り直しを求め、異なる版を混ぜない。
- iPhone閲覧ページの手動JSONは `web/backup_stream.mjs` で台ごとに解析する。改行なし・整形JSONでも画像入りの全文を一括解析しない。外枠も末尾まで検査してから保存し、途中の結果をIndexedDBへ書かない。
- 手動読み込み・Drive更新・自動読み込み設定の切り替えは重ねない。手動読み込み時の旧イベントは、保存済みJSONから台の値を組み立てずに取り出し、別タブの入力も引き継ぐ。`skipRecordValues` はこの保存済みメタデータの読み出し専用であり、未検査ファイルの受け入れには使わない。
- `ViewerData.preparePicked` / `prepareMerge` は解析済みの内容から表示モデルを作り、同じ全文の再解析を避ける。保存成功後に表示を切り替え、解析・保存の失敗では旧データを保持する。`test_viewer_import_browser.mjs` はメルヘン・P’s CUBEで競合、別タブのイベント、破損JSON、IndexedDBの明示中断を実際の生成物で確認する。iPhone Safari実機の容量限界は別途確認が必要。

回帰試験は `database/tests`・`database/test_*.py`・`database_android/test`・`database_android/tool/test_*.mjs` に置く。GitHub ActionsはLinux/Windows、JST/UTCのPC試験と、Linuxの全体ゲートを実行する。実機・実Googleの動作確認とは区別する。

コードを含むmainへのpushでCIが動き、GitHubの通知設定に応じて結果メールが届く。**push前に日本時間の日付を確認し、1〜15日は `imakurudev-eng/database`、16日〜月末は `keyanbaitian6-cell/database-ci` だけへ送る。** 正本の指定は変えず、両リポジトリの履歴を1本に保つ。送り先にだけある変更を取得・統合してから送る。期間外へのpush、CI失敗の原因を調べない再実行、強制pushは行わない。詳しくは `AGENTS.md` の10/20の規則を参照する。

メールはジョブの成否だけを示す。全体ゲートが失敗した場合は、Actionsの `Complete pre-build gate` 内の失敗名のグループにエラー本文の末尾120行を表示する。全体ゲートのログファイルも `regression-full-logs` のartifactとして7日間保存する。`test_rainbow_today_browser` は共有／Flutter閲覧と320／393pxを個別の試験名で表示する。

一時フォルダー内のSQLiteは、フォルダーを削除する前に必ず閉じる。`with TemporaryDirectory()` 内で `addCleanup(store.close)` だけを登録すると、接続を閉じるより先にフォルダー削除が走り、Windowsで失敗する。内側の `with closing(Store(...))` または `try/finally` を使う。今回のバックアップ・削除同期の4試験には、Linuxでも同じ寿命違反を検出する `test_sqlite_fixture_cleanup.py` がある。

## GoogleとWebへの反映

ソースの修正やmainへのpushだけで既存のGoogle Apps Script・公開ページは更新されない。
`node database_android/tool/build_viewer_parts.mjs` で生成したGSを、[VIEWER_HISTORY_SYNC.md](database_android/VIEWER_HISTORY_SYNC.md) の既存デプロイ更新手順で反映する。メルヘン同期の既存設定値・履歴フラグ・フォルダ指定・プロパティを保持する。新たなGoogleプロジェクトや同期先を作らない。
PC→Google→Webで最後の1台の削除、古いバックアップの再投入、明示復元を照合する。AndroidのDrive保存→キャンセル→再起動→再保存、実iPhoneの長期容量・速度は実機確認が必要。
