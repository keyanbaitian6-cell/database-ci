# 改善点の対応と、台番の末尾の印（2026-11-05）

利用者「全部直して」（`DATABASE_REVIEW_20261105.md` の高1〜低5）。作業中に「機能追加依頼」（末尾の印と、機種一覧の各台の差枚の点）。点は一度作ったが、利用者「みてて気持ち悪いからやっぱりいらない。PC版、スマホ版もろもろいらないです」で3画面とも取り除いた（コード・試験・試験データ・CSSとも残していない）。

## 改善点の対応

| 項目 | 対応 | 場所 |
|---|---|---|
| 高1 P’s CUBEの取り戻しのさかのぼり | 起点を今回最初に済ませた日に固定（メルヘンと同じ）。サイトの7日（今の営業日を含む）より古い日は見ない | Android `pscube_auto.dart` `pscubeGapCandidateDays`、`pscube_import_page.dart` `_gapDay` |
| 高2 同期スクリプトの方式の取り違え | スクリプトのプロパティ `meruhenCloudMode`／`pscubeCloudMode` に前回の方式を覚え、定数と違えば閲覧用ファイルを書かずに止める。覚えていないときも、閲覧用の一覧が履歴方式（v2）なのに false なら止める。本当に切り替えるときは `changeMeruhenCloudMode`／`changePscubeCloudMode` を実行してから同期 | `tool/viewer_history_adapters.js` `vhModeProblem`、`meruhen_cloud_sync.gs`、`pscube_cloud_sync_runtime.js`（→ 生成 `pscube_cloud_sync.gs`） |
| 高3 メルヘンの取り戻し条件① | 「記録が1台も無い日」は、前の日と次の日をこの端末で取り込んでいるときだけ抜けとみなす（PCで取り込んだ日をサイトから読み直さない）。2日続けて抜けた日はその回には見つけず、片方を取り込むと次の回に見つかる | Android `app_controller.dart` `meruhenGapDay` |
| 中1 Androidのメルヘンの失敗の記録 | 画面に出した失敗の文を `errors.log` の `meruhen.error` に残す（`_error` に文が入るたび）。自動取り込みの開始・見張りの失敗も `meruhen.auto.start`・`meruhen.auto.tick` | Android `web_import_page.dart` |
| 中2 結果の通知の音 | 音・振動なし（`IMPORTANCE_LOW`）の新しいチャンネル `database_capture_result_quiet` に移し、11/4の音ありのチャンネルは消す（作った後のチャンネルの重要度はアプリから下げられないため） | Android `MainActivity.kt` |
| 中3 CIの時間の上限 | 各ジョブに `timeout-minutes: 45`（直近は pc 1〜5分、full 約16分） | `.github/workflows/regression.yml` |
| 中4 版番号だけのコミットでCIが動く | 運用の決まりを `AGENTS.md` の GitHub Actions の節に追加（版上げはコードと一緒に1回で送る） | `AGENTS.md` |
| 中5 P’s CUBE一覧の読み直しの上限 | 変えていない。値（60回・3回に1回読み込み直し）は、次の0時の `errors.log`（`pscube.list`・`pscube.index`）で実際の回数を見てから利用者と決める | — |
| 中6 ウィジェットの計算 | メルヘンの自動取り込みの間は計算せず、止めたときに1回（`homeWidgetCapturing`）。計算の失敗は `errors.log` の `widget` | Android `home_widget.dart`・`main.dart`・`web_import_page.dart` |
| 低1 通知を出せなかったこと | 許可が無くて出せなかったときは `notice.blocked` を残す | Android `capture_notice.dart` `noteCaptureNoticeShown` |
| 低2 当時の候補が届く範囲 | 文書に追記 | `ADDITIONS_20261104.md` |
| 低3 試験の一時フォルダー | 変えていない。最初のリポジトリ（9/23）からの書き方で、理由の記録が無く、十数か所を変えると試験の前提が崩れる恐れがある。`.gitignore` 対象で、今は残り物も無い | — |
| 低4 残った作業ツリー | `git worktree remove` で2つ外した（どちらも未コミットの変更なし）。Codexの未取り込みのコミット `e55606a` はブランチ `codex/viewer-drive-efficient-20261004` に残る | — |
| 低5 共有記録の伸び | 月の半ばに前半分を `ai_collaboration/2026-11-01_15.md` へ移す（AGENTS.md の決まりどおり。今は何もしない） | — |

Googleの貼り替えが要るもの：高2（`meruhen_cloud_sync.gs`・`pscube_cloud_sync.gs`）。貼り替えるときは利用者の設定行（履歴方式 true など）を残す。貼り替え後の最初の同期で、その時点の方式を覚える。

## 末尾の印（差枚の一覧 → 機種の一覧）

利用者「差枚一覧の上で台番の末尾（0〜9）を1つ選べるように」「同じ店舗・日付の機種一覧へ移動しても、選択と印を引き継いで」「全台を表示したまま」「『末尾7 ×』で解除でき、店舗または日付を切り替えたときは選択を解除」。出す画面は利用者が選んだ：共有カレンダー・iPhone閲覧ページ・PC。**Androidアプリには出さない**。

| 画面 | 末尾を選ぶ所（差枚の一覧） | 引き継ぐ先（機種の一覧） | 解除 |
|---|---|---|---|
| 共有カレンダー | 日の画面の「TOP50」の上（0〜9のボタン） | TOP50の台を押して開く機種の「台一覧」、「全機種の台一覧」 | 「末尾7 ×」（日の画面・機種の台一覧・全機種の台一覧）、日付を変える、シートを閉じる（店を変える） |
| iPhone閲覧ページ | 「全機種の台一覧」（差枚で並べ替えられる表）の上 | 「この日の機種一覧」から開く1機種の表（グラフ表示でも） | 「末尾7 ×」（どちらの表でも）、日付・店を変える |
| PC | 「機種一覧」タブの上の「末尾」（なし・0〜9） | 同じタブの「機種」で1機種にしたとき | 「末尾7 ×」ボタン、店舗・日付を変える |

- 印は台番の横の小さな「末7」（共有：青い小さな札、閲覧ページ：表の台番号の欄とグラフのカードの見出し、PC：台番の欄の文字）。台は絞らず全部出す。
- 元の日に戻しても、解除したまま（覚え直さない）。
- コード：共有 `share_viewer/app.mjs`（`suffixPicker`・`suffixMark`・`openDay` の `suffix`）、`data.mjs` `rackSuffix`、`index.html` のCSS。閲覧ページ `lib/rack_suffix.dart`（`viewerSuffixPick`。ViewerHome が用意し、Android版では null）、`machine_sections.dart`（`suffixDigit`）、`viewer_pages.dart`、`viewer_main.dart`。PC `database/machine_list.py`。

## 試験

- 改善点：Android `pscube_auto_test.dart`（`pscubeGapCandidateDays`）、`meruhen_gap_day_test.dart`、`meruhen_browser_test.dart`（`meruhen.error`・ウィジェットの計算の止め方）、`home_widget_test.dart`（`notice.blocked`）。JS `test_meruhen_cloud_sync.mjs`（方式の取り違えで止まる・切り替え）。
- 末尾：JS `tool/test_share_viewer_suffix_mark_browser.mjs`（共有カレンダーを実際のブラウザで、320/393px）。Flutter `test/rack_suffix_test.dart`、`test/viewer_navigation_test.dart`（ViewerHome から全機種の台一覧→機種の表→解除・日付の切り替え）。PC `tests/test_machine_list.py`（`SuffixMarkTests`）。
