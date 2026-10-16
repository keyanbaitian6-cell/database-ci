# 開発時の確認

正本の既存チェックアウトを使う。PCの起動は `database/start.cmd` を維持し、EXEの作成は不要。

## 共通の入口

Python 3.12、Node.js 24、Flutter 3.47.1（`.metadata` の6655482ec0、Dart 3.13.1）を使用する。
Python依存は `database/requirements.txt`、Flutter依存は `pubspec.lock` のまま導入する。
空の環境では `database_android/assets/database_seed.example.json` を同じ場所の `database_seed.json` へコピーする。既存ファイルを上書きしない。

```bash
python3 -m venv database/.venv
database/.venv/bin/python -m pip install -r database/requirements.txt
cd database_android
flutter pub get --enforce-lockfile
cd ..
bash database_android/tool/check_before_build.sh
```

Windowsでは `py -3 -m venv database/.venv`、`database/.venv/Scripts/python.exe` を使い、確認スクリプトはGit Bashで実行する。通常のPC版の起動方法は変わらない。

`tool/dev_env.sh` がリポジトリのPython環境、Node、Playwrightを検出する。別の場所を使う場合は `PYTHON`、`NODE`、`PLAYWRIGHT_MODULE`（index.mjsのfile URL）、`CHROMIUM_PATH` を指定できる。Playwrightと対応Chromiumの導入は利用する開発環境で行う。LinuxのTk試験にはXサーバーが必要で、画面のない環境では `xvfb-run -a bash database_android/tool/check_before_build.sh` を使う。

クラウドでは `source /workspace/.cloud-setup/env.sh` で導入済みツールを有効化できる。ホームが読み取り専用の場合、`PUB_CACHE`、`XDG_CONFIG_HOME`、`ANALYZER_STATE_LOCATION_OVERRIDE` を書き込み可能な作業用ディレクトリへ向ける。`DASH__SUPPRESS_ANALYTICS=true` はDartがホームへ分析設定を書こうとするのを抑止する。証明書・チェックサムの検証は無効化しない。

Flutterのない環境でも `bash database_android/tool/check_before_build.sh --local` でPC・ビルド不要のJS試験を実行できる。未実行項目を列挙し、`LOCAL CHECKS PASSED` は全体ゲートの成功ではない。APKや公開用のビルドの条件は、引き続き通常実行での `ALL PASSED`。

通常実行は閲覧ページをその場で生成・ステージしてから試験する。生成に失敗した場合は古い成果物を試験しない。試験用成果物から公開はしない。

## 更新の仕様と障害時の確認

- JSON・バックアップは同じ保存先の一時ファイルへ書き、flush/fsync後に置き換える。一時ファイルは `.tmp` で同期入力のJSONに含めない。コピー・置き換え失敗時は前回の完成版を保持する。
- 明示削除は `record_deletions`（店舗・日付・機種・台番号・deleted_at）でPC/AndroidのバックアップとPC閲覧用へ運ぶ。期間外へ出た日を削除と推測しない。削除時刻より新しい取得・明示復元は許可する。復元操作の `record_updated_at` は元の取得時刻と別に記録する。
- メルヘンのGoogle同期は履歴モードで削除情報を日別原本に保持する。古いAndroid入力は削除済みの台を復活させない。旧モードで削除情報を持つAndroid入力を受けた場合は黙って捨てず停止・通知する。
- PCの重いレポート・バックアップ出力は、1本のワーカーがSQLiteの専用コピーから行う。連続要求はまとめ、GUIの操作・通知はメインスレッドで行う。終了時は保留中の出力を待つ。DB保存と出力失敗は区別して知らせる。
- 閲覧履歴の再起動読み込みは1日ずつハッシュ検査する。全期間の検索・集計用のレコードは保持する。同時更新を検出した読み出しは取り直しを求め、異なる版を混ぜない。

回帰試験は `database/tests`・`database/test_*.py`・`database_android/test`・`database_android/tool/test_*.mjs` に置く。GitHub ActionsはLinux/Windows、JST/UTCのPC試験と、Linuxの全体ゲートを実行する。実機・実Googleの動作確認とは区別する。

mainへのpushでCIが動き、GitHubの通知設定に応じて結果メールが届く。メールはジョブの成否だけを示す。全体ゲートが失敗した場合は、Actionsの `Complete pre-build gate` 内の失敗名のグループにエラー本文の末尾120行を表示する。全体ゲートのログファイルも `regression-full-logs` のartifactとして7日間保存する。`test_rainbow_today_browser` は共有／Flutter閲覧と320／393pxを個別の試験名で表示する。

一時フォルダー内のSQLiteは、フォルダーを削除する前に必ず閉じる。`with TemporaryDirectory()` 内で `addCleanup(store.close)` だけを登録すると、接続を閉じるより先にフォルダー削除が走り、Windowsで失敗する。内側の `with closing(Store(...))` または `try/finally` を使う。今回のバックアップ・削除同期の4試験には、Linuxでも同じ寿命違反を検出する `test_sqlite_fixture_cleanup.py` がある。

## GoogleとWebへの反映

ソースの修正やmainへのpushだけで既存のGoogle Apps Script・公開ページは更新されない。
`node database_android/tool/build_viewer_parts.mjs` で生成したGSを、[VIEWER_HISTORY_SYNC.md](database_android/VIEWER_HISTORY_SYNC.md) の既存デプロイ更新手順で反映する。メルヘン同期の既存設定値・履歴フラグ・フォルダ指定・プロパティを保持する。新たなGoogleプロジェクトや同期先を作らない。
PC→Google→Webで最後の1台の削除、古いバックアップの再投入、明示復元を照合する。AndroidのDrive保存→キャンセル→再起動→再保存、実iPhoneの長期容量・速度は実機確認が必要。
