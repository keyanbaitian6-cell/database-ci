# Windows検証・PC/Androidビルド（2026-10-02）

## ソースと修正

- 正本：`C:\Users\keyan\Documents\Codex\2026-09-24\a\work\database-main`、main。開始時HEAD `16bdf04`、未コミット変更なし。
- fetch後の最新main `9abd6c71e6df21d3f6fd2d94024aa92cf22bc8c8` をfast-forwardで取り込み。`86dd1af`、`9f6e24b`、`9abd6c7`がすべて祖先であることを確認。間の共通閲覧画面・末尾集計・手動印の変更も保持。
- ビルドしたソース：`31b3cbb65b72c3835765f3ec68ed07c6e64d4590`、GitHub mainへpush済み。後続の検証記録・テスト改善は配布アプリのコードを変更しない。
- Windows WebView2でHTTP403が`WebResourceResponseReceived`の後に`NavigationCompleted(IsSuccess=False, WebErrorStatus=Unknown)`も発生することを実測。HTTP拒否を通信失敗へ変更していたため本文が消える。既に検知したHTTP拒否を保持するよう修正。
- このWindowsのWebView2では`NavigateToString`がエラーHTMLの正確な`data:text/html;charset=utf-8;base64,...`をNavigationStartingへ通知した。従来のabout:blankだけの例外では元URL・エラー状態が消える。アプリ自身が生成した正確なdata URIも識別して保持するよう修正。他のサイトのURLは通常どおり扱う。
- P’s CUBEカードの最大高さがpadding/borderの22pxを含めず、Windowsの360×300疑似ページで上端が-7pxになる。高さ制限に余白を含めて修正。デザイン・ボタン・操作は維持。
- `--smoke-local <結果JSON>`という明示指定の診断だけ、各EXEを新しい一時DB・インラインページで起動できるよう追加。通常の起動経路は維持。メイン画面の既存ボタンのコールバックが両補助EXEを起動することも確認する。
- Android `date_events.dart`の不要な型変換2件を削除。APKを`0.5.18+2026100202`へ更新。既存main・同日成果物の最大連番01、接続端末のversionCode `2026100110`より大きい。

## 成功

| 検証 | 結果 |
| --- | --- |
| Python既存テスト | 174件成功 |
| P’s CUBE Python回帰 | 61件成功（追加2件含む） |
| Flutter全テスト | 417件成功 |
| 実データ303番台 | 既存seedをそのまま読み、指定テスト1件でも成功。positive=10、retention=8.62275449±0.001という既存期待値を変更していない |
| Flutter静的解析 | error/warning各0、info17件。`flutter analyze --no-pub --no-fatal-infos`成功 |
| JS表・グラフ回帰 | `test_web_extraction.mjs`成功、`test_review_extraction.mjs`15件成功 |
| JS保存・同期・採点・バックアップ | data13件、sync9件、scoring13件、viewer backup parser28件成功 |
| ローカルChromium | メルヘンCookieカード、P’s CUBE自動カード、全台スクロール、Drive bridge、共通閲覧画面の各スクリプト成功 |
| `smoke_browser_lifecycle.py` | 実WebView2のAPI初期化・終了・一時DBのバックアップ・イベント書き出し成功 |
| `smoke_auto_capture.py` | 一時DBへの表/グラフ保存、自動ON/OFF、遅延中のOFF、最小化・別ウィンドウに隠れた状態の取り込み、保存後移動成功 |
| `smoke_auto_machine_switch.py` | 別機種への移動、保存日付保持、遅延移動のOFFキャンセル、表/グラフ4保存成功 |
| `smoke_cookie_retry.py` | 両サイトの実起動関数を4プロセスで確認。専用Cookie/localStorageの再起動保持、同一URLの通信再発生、fragment保持、保存/確認中の拒否、実HTTP403でON→OFF、本文維持、接続拒否のエラー画面→同じURLへの復帰、一時SQLiteのSHA-256不変が成功 |
| `smoke_frozen_capture.py` | 新しい配布EXEで一時DBへ表/グラフ保存。内蔵browser_import/auto_capture/coreのコードが現ソースと一致 |
| `smoke_frozen_runtime.py` | 3EXEの主要内蔵モジュール、P’s CUBEの2つのJS、必要DLLを照合。メイン画面と両補助EXEが実際に起動しAPI初期化成功。通常のrootが既存`database`フォルダであることを確認 |
| 利用者データ保護 | 配布EXE検証前後に`database/data`直下13ファイルのSHA-256が一致。検証には新規一時DBと一時WebView2プロファイルのみ使用 |
| APK | releaseビルド、aaptのpackage/version確認、apksigner検証成功。接続端末の既存APKを読むだけで署名一致も確認 |

再試行でCookie/localStorage/既存DBを消さないこと、設定完了待ち、広告/別店舗/別台/過去ページのエラー除外、保存を受け付けた後の完了、バックアップ/取り消し/採点は既存Python/Flutter/JSテストを併用した。Androidの初期Cookie設定順と画面破棄時の停止はfake WebViewプラットフォームを使う画面テストによる検証であり、新APKの実機WebView確認とは区別する。

## 失敗後に解消したもの・警告

- 通常サンドボックスのPython実行は一時フォルダ権限で97エラー。Flutter初回は出力なしで待機していた。SDKのロックファイルを取得する処理を確認したが、初回待機の正確な原因はわかりません。自分の停止中テストを終了し、通常のWindows権限で再実行して成功。SDKロックファイル・利用者DBの削除はしていない。
- 小窓カード回帰は修正前に失敗し、修正後に成功。ネイティブHTTP・data URIの問題も実WebView2で再現してから修正し、両サイトで成功。
- 最初の全体analyzeは不要cast警告2件/info17件でexit1。castを修正し、infoは記録して`--no-fatal-infos`で最終検証した。標準のinfoもfatalとする実行が完全cleanになったという報告ではない。
- 追加診断スクリプトの開発中に、テスト側の属性参照、.NETの初期化順、WebView2終了直後の一時プロファイル後処理、P’s CUBE EXEに不要なcoreの照合で失敗した。テスト/診断を修正し最終成功。ロック中の一時ファイルは残る場合があるが、利用者のブラウザプロセスを強制終了しない。
- ネイティブ再読み込みで消えた旧ページへpywebviewがJS APIの返答を届けようとする`_returnValuesCallbacks`の警告がログに出た。テストの全アサーション・再試行・保存値保持は成功。フレームワークのコードは変更していない。
- 追加ローカルテストの復帰先指定漏れによりメルヘンの実サイト1ページが開かれた。停止してDEFAULT_STARTをローカルへ置き換え、外部NavigationStartingをキャンセルするガードを追加。最終検証はlocalhostだけで実施。人間認証を操作せず、大量巡回もしない。この1ページを実サイト検証成功として数えない。

## SKIP・未実施

- **SKIP**：`test_pscube_capture.mjs`。`PSCUBE_ARCHIVE_DIR`未指定。検索したDocuments/Downloads/ChatGPTプロジェクト内に必要な`pscube-machine-index-archive/main.html`、`pscube-tokyo-full-archive/main.html`、`pscube-1526-archive/main.html`が見つからなかった。非公開アーカイブの実HTML抽出は未確認。
- **未実施**：新APKのインストール・起動・実機Android WebViewでの初回Cookie設定、再起動後の認証保持、HTTP403/DNSの解消。接続端末はSM_A253C、現行アプリ0.5.16/2026100110。パッケージの署名・バージョンだけ読み取り確認した。
- **未確認**：実サイトの認証Cookie期限、サイト側拒否の原因、人間確認/同意画面の実操作、実際のDNS障害とその解消、別PCのWebView2ランタイム差。
- adb uninstall、pm clear、データ初期化、利用者Cookie消去、実サイトの自動人間認証、閲覧ページの公開は実施していない。

## 成果物・証拠

- PC配布一式：`C:\Users\keyan\Documents\Codex\2026-09-24\a\work\database-main\database\bin`
- 起動：`bin/database/database.exe`。補助：`bin/database-browser/database-browser.exe`、`bin/database-pscube/database-pscube.exe`。3フォルダと各`_internal`を一緒に扱う。data/reportsは同梱・上書きしない。ZIPは生成していない。
- PCビルド：`build_windows.ps1 -Python <既存Python runtime> -BuildTag windows-cookie-2026100202`。旧チェックアウトから借用したのはPython実行環境のみ。ビルドしたソースは正本のmain。
- EXE実動作WebView2：`154.0.4258.48`。`Python.Runtime.dll`、WebView2 Core/WinForms DLL、win-x64 WebView2Loader DLLを配布内で確認。
- APK：`C:\Users\keyan\Documents\Codex\2026-09-24\a\work\outputs\database-0.5.18-2026100202.apk`、92,686,361 bytes。
- APK SHA-256：`97E3F06B105CA822CE560D203508EAAF988DF1671634B4CA5DF84C1FEE1B3C6A`。
- APK package：`com.keyan.database_android`、versionName `0.5.18`、versionCode `2026100202`、minSDK24、targetSDK36。既存のrelease設定に従いdebug鍵署名（接続端末の既存APKと同一証明書）。
- 今回のEXE内蔵コードを現ソースと照合し、古い生成物ではないことを確認した。APKも新しいファイル名へコピーしaaptで確認。
- ログ・manifest：`C:\Users\keyan\Documents\Codex\2026-09-24\a\work\outputs`。`windows-*-20261002*.log`、`windows-artifact-manifest-2026100202.json`、`windows-main-exe-smoke-2026100202.json`、`windows-real-rack303-20261002.log`。
- ソース/テスト/この記録だけをGit管理。EXE/APK/実データ/一時プロファイルはGit対象外。

## データを消さず更新する手順

PCは本体と取り込み窓を閉じてから、上記の新しい`bin/database/database.exe`を起動する。この正本内の既存data/reportsを参照する。別の設置先へ配布する場合は、アプリを閉じた上でbin内の3アプリフォルダ一式だけを更新し、設置先のdata/reports・Cookieフォルダを残す。EXEだけの単独コピーはしない。

Androidはアンインストールせず以下で更新する。インストール自体は今回未実施。

```powershell
adb install -r "C:\Users\keyan\Documents\Codex\2026-09-24\a\work\outputs\database-0.5.18-2026100202.apk"
```

署名一致とversionCode増加は確認済み。エラーが出てもuninstall/pm clearをせず、そのエラーを確認する。データ・Cookieを残した「もう一度開く」を使用し、自動取り込みは必要時に手動で再開する。

証拠ソースはこのリポジトリのテストと出力ログ。外部サイトの原因や実機の解消を推測で確定していない。最終報告と成功/失敗/SKIP/未実施の区分を照合した。
