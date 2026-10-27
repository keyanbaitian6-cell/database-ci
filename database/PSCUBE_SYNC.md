# P’s CUBE バックアップ・Drive同期の仕様

決定日：2026-10-01（利用者の指示：「取り消しは付けない。PC版の自動バックアップをそのまま、名前を分けて。
ドライブ同期をする。Android版・iPhoneブラウザ版もほとんど同じ仕様」）。
メルヘンワールドの仕組み（`core.auto_backup`・`database-viewer.json`・Apps Script・閲覧ページの自動読み込み）を
P’s CUBE用に移したもの。**メルヘンの記録・設定・ファイルは変更しない。** コードの変更はメルヘン側1か所だけ：`core.latest_backup_file`（同期フォルダの最新バックアップを探す処理）が `pscube-` で始まるファイルを読まないようにした（形式が違い大きいので、読もうとして時間がかかるのを防ぐ。テストあり）。

## ファイル（同期フォルダ＝メルヘンと同じ「database共有」）

| ファイル | 書く人 | 内容 |
| --- | --- | --- |
| `pscube-backup-auto.json` | PC（保存のたび上書き） | 全期間のバックアップ（グラフも全点） |
| `backups/pscube-backup-YYYY-MM-DD.json` | PC（保存のたび、その日の最新で上書き） | 日付ごとの控え。7日より古いものは消す |
| `pscube-viewer-drive.json` | PC（保存のたび上書き） | 閲覧ページ用の軽いファイル：直近31日・グラフは最大16点（最高・最低・終点・ゼロ線を必ず残す）。バックアップではない |
| `pscube-backup-android-YYYYMMDD-HHMMSS.json` | Android（共有から手で保存） | 全期間のバックアップ |
| `pscube-backup-browser-YYYYMMDD-HHMMSS.json` | iPhoneブラウザ（書き出し） | 閲覧ページに入っている内容 |
| `pscube-day-android-YYYY-MM-DD.json` | Android→自分用スクリプト（自動取り込みを終えたとき） | その日の記録だけ（下の「当日分の自動送信」） |

メルヘンの `database-backup-auto.json`・`database-viewer.json`・`backups/database-backup-????-??-??.json` とは
名前が重ならず、メルヘン側の「7日より古い控えを消す」処理にもかからない
（`pscube-` で始まるため）。同期フォルダはメルヘンの設定（`data/settings.json` の `sync_dir`）をそのまま使う。
`sync_dir` が無いときは、控えだけ `data/backups/` に作り、Driveへは出さない。

## 形式

従来の `pscube-viewer`（version 1）に、次の項目を足す（古いファイルは項目が無いだけで読める。
読み手は知らない項目を無視する）。

- `exported_at`：書き出した時刻（`+09:00` など時差つき）
- `source`：`pc`／`android`／`browser`
- `kind`：`backup`（全期間・復元に使える）／`viewer`（軽い。復元には使えない）
- `rack_captures`：台別7日分を取り込み済みの印（`backup` のみ）
- `date_events`：日付ごとのイベント名（自由記入、2026-10-06。`backup`・`viewer` とも）。
  `{store, rate, day, name, updated_at}`。`name` は1〜60文字（前後の空白は除く、改行などの制御文字は不可）、
  `null` は「イベントを消した」印で、古いバックアップを読んでも消したイベントが戻らないよう残す。
  同じ店舗・貸玉・日付は `updated_at` が新しい方（同じなら読み込んだ方）を残す（PC `merge_date_events`・
  Android `mergePscubeDateEvents`・閲覧 `mergeDateEvents`）。PC・Androidは記録のある貸玉それぞれに同じ名前を
  付け、閲覧ページは表示中の店舗・貸玉に付ける。入力欄のプルダウンは、今イベントが付いている名前（新しく
  使った順）。全部の日から消した名前は候補から外れる（打ち間違いが残らない）。
  以前の閲覧ページの末尾イベの印 `suffix_events`（`enabled`）は「末尾イベ」という名前（外した印は `null`）に
  読み替え、書き出しは `date_events` だけにする。保存場所：PC・Androidは記録の `state` 表の `date_events`、
  閲覧ページは端末のIndexedDB。採点・候補には使わない（表示だけ）。

## 動き

**2026-10-13追加：PC不要の自動反映**。専用Apps Scriptを一度設定すると、Androidからマイドライブ直下または同じ共有フォルダへ保存したバックアップをGoogle側で統合し、既存の `pscube-viewer-drive.json` を更新できる（30分おき＋手動実行）。出力は共有フォルダにまとめ、全期間の統合結果は `pscube-backup-cloud.json` に残す。既存の自分用・共有用スクリプト、閲覧URL、APKの変更は不要。不正なバックアップが混ざっても、そのファイルだけ取り消してほかは反映する（2026-10-13）。スマホからの設定・日々の操作・帰宅後のPC同期は [PSCUBE_CLOUD_SYNC.md](../database_android/PSCUBE_CLOUD_SYNC.md) を参照。以下の従来の動作は、この専用スクリプトを設定していない場合のもの。

- **PC**：取り込みを1回保存するたびに、保存の後で上記3つを書く（失敗しても取り込みは止めない。結果に
  「バックアップ済み／同期フォルダ未設定／失敗」を出す）。書きかけがDriveへ上がらないよう、ローカルで
  書いてから複製する。「バックアップ・同期」タブに「P’s CUBEの同期フォルダの最新を読み込む」を足す
  （Android・ブラウザのバックアップをPCへ取り込む。`pscube-backup-*` を更新日時の新しい順に見る。
  `kind: viewer` は止める）。
- **Android**：自動の同期はできない（メルヘンのAndroidと同じ）。「バックアップを書き出す」（共有→ドライブへ保存）と
  「バックアップを読み込む」（PC・ブラウザのバックアップを統合）。最後に書き出した時刻を画面に出す。
- **iPhoneブラウザ**：開くとDriveの最新を読む。メルヘンの閲覧ページと同じ Apps Script のURL
  （同じブラウザの `database-viewer-remote`）を使い、`?file=pscube` を付ける。書き出した時刻が前回と同じなら
  何もしない。ファイルの読み込み・書き出しは従来どおり。
  Apps Scriptの中継先はときどき404を返す（実測でメルヘン・P’s CUBEとも12回中2回）ので、404・429・5xx・通信失敗は
  1.5秒・3秒待って2回までやり直す。
- **統合の規則（PC・Android・ブラウザ共通）**：台ごとに、数値が同じなら台別グラフ（daily）を優先、
  数値が違えば取得時刻の新しい方（時刻が無ければ回転数の多い方）を採り、古い数値で新しい数値を
  上書きしない（従来の取り込みの `_merge` と同じ）。数値が変わった台は台別7日分の印を外す。
  機種タイプは自分の設定を優先。**消す操作はない**（Drive側で消えた台を端末から消さない）。

## 当日分の自動送信（2026-10-26）

利用者「取り込んだ当日分のデータだけ送る。送るのはpscubeのみ」「押さなくてもドライブに上げた時点でどうにかなったりない？」。
翌日候補の比較の記録（`NEXT_DAY_SHADOW_PLAN_20261025.md`、`database/input_versions.py`）は、PCに入った時刻で残る。
スマホで取り込んだ日も、締切（翌日08:00 JST。2026-10-26に02:00→03:00、2026-10-28に03:00→08:00へ変更、`NEXT_DAY_SHADOW_PLAN_20261025.md`）までにPCへ入るようにする。当日分のファイルを読むのはPC版だけ（P-STATION自動同期のスクリプトは読まない）なので、締切に間に合わせるにはPC版を起動しておく。

- **Android**（`lib/pscube_day_upload.dart`）：自動取り込みが「◯/◯の分をすべて取り込みました」で止まったら、
  その日の記録だけ（`PscubeStore.dayBackup`：その日の記録・台別7日分の印と、その記録の機種だけ。形は普通の
  `backup`）を、自分用スクリプトへ `{file: 'pscube-day', key, day, backup}` でPOSTする。取り込み画面の
  雲のボタンで、スクリプトのURL（…/exec）・合言葉・自動のON/OFFを入れ、今の日の分を手で送れる。設定は
  端末の `state` 表の `day_upload` に持ち、バックアップには入れない。最後の送信の結果は `day_upload_last`
  に残して画面に出す。送れなくても取り込みは済んでいる（手で送り直すか、従来どおり全期間を共有で保存する）。
- **Apps Script**（`tool/viewer_drive_script.gs` の `postPscubeDay`）：スクリプト プロパティ `PSCUBE_UPLOAD_KEY`
  （合言葉、利用者の選択で必須）と一致するときだけ、`pscube-viewer-drive.json` と同じフォルダの
  `pscube-day-android-YYYY-MM-DD.json` に書く（同じ日は上書き）。形・日付・件数（記録2万・機種5千）・容量（20MB）
  だけ検査し、細かい検査はPC版が読むときにする。台の記録を書くので、合言葉が未設定・違う送信は断る。
- **PC**（`app.poll_pscube_from_sync`、`pscube_import.android_sync_files`・`android_sync_due`）：起動の15秒後と
  2分おきに同期フォルダを見て、`pscube-day-android-*.json` と `pscube-backup-android-*.json` の新しい版
  （名前と更新時刻が前に読んだものと違い、書かれてから10秒以上たったもの）を古い順に読み込む。読めたものを
  `data/settings.json` の `pscube_android_synced` に覚える。初めて使うときは、その時点のファイルを読み込み済み
  として扱う（古いバックアップを読み直さない）。失敗したファイルは覚えず、次の確認でやり直す（同じ失敗は記録欄に
  1回だけ書き、画面には出さない）。PC版が起動していなければ読めない。
- 利用者の作業（1回）：スクリプトを貼り直して「新バージョン」でデプロイし、スクリプト プロパティに
  `PSCUBE_UPLOAD_KEY` を足す。アプリの雲のボタンで、同じURL・合言葉を入れる。
- 試験：`tool/test_viewer_drive_script.mjs`（合言葉・形式・上書き）、`test/pscube_day_upload_test.dart`
  （当日分の中身・送る内容・失敗・合言葉をバックアップに出さない）、`database/test_pscube_android_sync.py`
  （読むファイルの選び方・初回・書きかけ待ち・当日分の統合）。実Driveへの送信・実機での確認は利用者の環境で行う。

## Apps Script（利用者の作業が1回必要）

`database_android/tool/viewer_drive_script.gs` を、`?file=pscube` のときだけ `pscube-viewer-drive.json` を返す
ように更新した。既存のURLを使うには、Apps Scriptの「デプロイを管理」→ 編集 → 「新バージョン」で
更新する（URLは変わらない）。更新前のスクリプトは `?file=` を無視してメルヘンの閲覧用ファイルを返すので、
閲覧ページは「P’s CUBEのファイルではありません」と出して何も変えない。
URLを知っている人はファイルの中身を読める（メルヘンと同じ。利用者が選んだ方式）。URLは記録に残さない。

## 限界

- **容量は見込みで、実Driveでは未確認**：実データ（39件）で1件あたり約1.2KB（グラフは12〜17点）。1日に取り込む台数×31日で増える（例：800台なら約30MB）。Apps Scriptが返せる大きさの上限はわかりません（メルヘンの閲覧用ファイルは25MB見込みで動いている）。読めなくなったら、日数を減らす。
- 閲覧ページが読める記録は10万件まで（`validateData`）。全期間のバックアップがそれを超えたら、閲覧ページの上限を上げる必要がある。
- AndroidからDriveへの自動書き出しはない（手で共有）。上記の専用スクリプトを設定した場合は、その後の統合・閲覧用出力をGoogle側で自動化できる。
- 閲覧用の軽いファイルのグラフは最大16点の概略（採点に使う終点・最高点・ゼロ線は変わらない）。
- 31日より前の記録は閲覧ページに自動では入らない（全期間は手でバックアップを読み込む）。
- 実Driveへの書き込み・Apps Scriptの更新・iPhone実機での読み込みは、利用者の環境でないと確認できない。
  確認した範囲は `AI_COLLABORATION.md` に分けて書く。

## Googleドライブ読み込みの出し直しと更新の目印（2026-10-04）

- Apps Script（`database_android/tool/viewer_drive_script.gs`）の返事は、ときどき固まり、30〜90秒たってから404を返す。閲覧ページ（メルヘン・P’s CUBE共通、`database_android/web/drive_fetch.mjs`）は、8秒返事がなければ同じリクエストをもう1本出し、先に成功した方を使う（最大4本）。
- `?check=1`（P’s CUBEは `?file=pscube&check=1`）を付けると、新しいApps Scriptは中身を読まず `{"format":"drive-check","version":"<更新時刻>-<サイズ>"}` だけを返す。閲覧ページは、前に読んだときと目印も書き出し時刻も同じなら、ファイルを読まない。古いApps Scriptは全文を返すので、そのまま使う。
- 目印を使うには、Apps Scriptを更新する（「デプロイを管理」→ 編集 → 新バージョン。URLは変わらない）。更新しなくても閲覧ページは動く。
