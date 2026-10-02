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
実サイトとAndroid実機は未実施。Windows生成EXEとAPKの結果はビルド後に追記する。

Androidは同日2回目、`0.5.21+2026100302`。ビルド生成物はGit管理外。

出典：
- https://docs.python.org/3/library/secrets.html
- https://api.dart.dev/dart-math/Random/Random.secure.html
- 自動取得仕様：`PSCUBE_AUTO_CAPTURE.md`。検証ログは作業フォルダの`outputs/pscube-random-*`。

別件のPython Playwright再試行サンプルはリポジトリ外の`a/work/playwright_resilient_sample/`。
指数バックオフ・ジッター・Retry-After・Windows DPAPI暗号化JSONを独立実装し、
実ChromiumとローカルHTTPサーバーで11件成功。本番Cookieの移行やプロキシ切替は含まない。
