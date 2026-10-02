# P’s CUBEのランダム待機（2026-10-03）

利用者指定により、PC・AndroidのP’s CUBE自動取り込みを固定7.1秒から、
5.0000〜8.0000秒、0.0001秒刻みの30,001通りの抽選へ変更。
メルヘンの固定間隔・採点・保存形式・Cookie・バックアップは変更しない。

- PCは`secrets.randbelow(30001)`、Androidは`Random.secure().nextInt(30001)`。
  毎回の待機設定で抽選し、通常の期限確認で抽選し直さない。同じ値の連続も許容する。
  起動直後のOFF表示は6.5秒、ONや読み込み完了で抽選する。
- 間隔表示をランダム範囲と抽選値へ変更。既存スライダーは抽選値の表示専用。
- OFF・保存中・読み込み中・同意画面の待機・古いページの無効化・重複保存拒否を維持。
  429/403等の既存停止処理も維持。拒否の自動再試行はこのアプリへ追加しない。
- スケジューラは100ms周期で確認する。実際の取得・ページ移動時刻は描画・保存待ちも含むため、
  100マイクロ秒精度のクリック時刻を保証しない。無条件に5〜8秒ごとにサイトを押す機能ではない。
  一様分布の平均は6.5秒。IP規制の原因・解除条件、ランダム化の有効性はわからない。

検証：PC Python106件成功、Android全体426件成功。共通スケジューラの最終小修正後は
関連テストを再実行。PCカードはChromiumの疑似応答でON/OFF・4桁表示・遅延全台表示・保存・
次ページ移動・Cookie保持の再試行を確認。30,001通りの両端と刻みを両言語のテストで確認。
実サイトとAndroid実機は未実施。

Androidは同日2回目、`0.5.21+2026100302`。ビルド生成物はGit管理外。

## ビルド結果

- 基準main：`a43c7038c53371fa690b0a82b8039ee8b770cbab`。
  追加修正：`7e67027e240db2645758d2bcb860bb8ed58d8f7a`をmainへpushしてからビルド。
- PCは`build_windows.ps1 -Python <既存Python3.14 runtime> -BuildTag pscube-random-20261003`で3EXE成功。
  配布一式：`C:/Users/keyan/Documents/Codex/2026-09-24/a/work/database-main/database/bin`
  の`database`・`database-browser`・`database-pscube`フォルダ。
- `smoke_frozen_runtime.py`成功：3EXE内のコード/JSとmainソースの一致、依存DLL、
  メインから両補助EXEを起動。実WebView2 `154.0.4258.48`でランダム表示と抽選値の一致を確認。
  通常rootは既存databaseフォルダ。検証のDB/プロファイルは一時フォルダへ変更。
  `smoke_frozen_capture.py <生成メルヘンEXE>`成功：一時DBの表・グラフ保存と保存結果の通知。
  最初の保存検証コマンドはEXE引数欠落で未実行となり、正しい引数を指定して成功。
- APKはreleaseビルド成功。保存先：
  `C:/Users/keyan/Documents/Codex/2026-09-24/a/work/outputs/database-0.5.21-2026100302.apk`。
  aaptでversionName `0.5.21` / versionCode `2026100302`、署名検証成功。
  92,686,361 bytes、SHA256 `72AD7AC71A402DAE9E0158256594B2F7ED042BD2636178A949AF43AF7F7730B2`。
  証明書SHA256は従来と同じ`4332fcb94ea909187733f9e8e3537d428f84d3248e39eeda2baf64387ee7a047`。
  ローカルseedのSHA256はビルド前後で不変。
- 最終静的解析：`flutter analyze --no-pub --no-fatal-infos`終了0、error/warning0、既存info17件。
  今回のinfo1件は修正。最終共通待機/P’s CUBEテスト11件成功。
- EXEハッシュと起動結果：`a/work/outputs/pscube-random-frozen-runtime-20261003.json`。
  APKインストール、Android実機、実サイトの拒否解除と取り込み再開は未実施。

更新：PCはアプリを閉じて3フォルダ一式を更新し、既存`data`・`reports`を保持して起動。
ソース起動ではP’s CUBE窓を閉じて開き直すと反映する。
Androidは同じ署名・増加したversionCodeのAPKを`adb install -r`で更新。
アンインストール・Cookie削除・データ消去は行わない。

出典：
- https://docs.python.org/3/library/secrets.html
- https://api.dart.dev/dart-math/Random/Random.secure.html
- 自動取得仕様：`PSCUBE_AUTO_CAPTURE.md`。検証ログは作業フォルダの`outputs/pscube-random-*`。

別件のPython Playwright再試行サンプルはリポジトリ外の`a/work/playwright_resilient_sample/`。
指数バックオフ・ジッター・Retry-After・Windows DPAPI暗号化JSONを独立実装し、
実ChromiumとローカルHTTPサーバーで11件成功。本番Cookieの移行やプロキシ切替は含まない。
