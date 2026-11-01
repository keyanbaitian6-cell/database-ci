# databaseアプリの最近の課題・修正候補（2026-11-01、初回調査）

## 対象・調査の位置づけ

- 利用者の依頼：カメラアプリを除外し、databaseアプリの最近の課題・修正点・改善点の検討を開始する。
- PCのdatabase／P’s CUBE、Android関連コード、自分用iPhone閲覧ページ、共有カレンダーの最近の記録を確認。全機能の網羅監査・実機試験ではない。カメラアプリは調査対象外。
- 基準：手元と正本mainは `4d02b9181905311fa4fd976f3d0585a1c6623e73`、database-ci/mainは `7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`。両リモートを `git ls-remote` で確認し、後者が手元HEADの祖先であることを確認。共有FETCH_HEAD・作業ブランチは変更していない。
- 両リポジトリの未解決Issue検索は0件だった。これは未解決不具合がない証拠ではない。主な課題は共同作業記録に残っている。
- GitHub APIで [CI 41259394567](https://github.com/imakurudev-eng/database/actions/runs/41259394567) のfull・Windows・Ubuntuの3ジョブ成功を直接確認。対象618a325から調査基準までの差は共同作業記録1行のみ。既存の全体試験やCIは再実行していない。
- 製品コード・実DB・設定・Cookie・端末保存・公開物は変更していない。対象サイトへのアクセス・同期・端末操作・コミット・push・ビルド・公開はしていない。今回の変更はこの報告と共同作業記録だけ。

## 1. 修正候補：P’s CUBEの自動完了状態が、後続の手動取得にも残る

**今回の模擬状態で再現。優先度は中。**

- `AutoPilot.finished()` は自動取得で次URLが無くなると `completed` を設定する。その後の手動取得では、この値を消さない。`close_when_finished()` は保存中でなく `completed` が残っていれば窓を閉じる。
- 自動取得完了→保存中で閉じる処理を保留→自動OFFのまま手動取得の結果（次URLあり・残り3件）を渡す→保存終了、という模擬順序で、古い完了状態のまま窓を閉じる処理が1回呼ばれた。
- 既存試験は最初から手動の場合、通常の自動完了、再度自動ONにする場合を確認しているが、この順序は含まない。メルヘン側には同種の状態を消す修正868b32fがある。
- **未確認**：実WebView2でこの短い競合が起きる頻度、利用者の端末での発生。10/31に窓が閉じなかった事象の原因ではない。保存済みデータの損失は再現していない。
- **提案**：手動取得の開始時に古い完了状態を無効にし、完了判定と保存開始の競合も点検する。既存の「保存中は閉じない」「正常完了後は閉じる」を維持する。修正時には下記順序の回帰確認を追加する。

出典：[完了状態と終了処理](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/database/pscube_import.py#L1540)、[既存の終了試験](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/database/test_pscube_auto.py#L540)、[メルヘンの修正](https://github.com/imakurudev-eng/database/commit/868b32f)。

再現方法：`database/` を作業ディレクトリとし、下記Pythonを既存の `.venv/Scripts/python.exe -B -` へ標準入力で渡した。既存試験の偽の窓・時計と一時フォルダーのみを使用し、実サイト・実DBには接続しない。

```python
from test_pscube_auto import CloseWhenFinishedTests
case = CloseWhenFinishedTests('test_manual_capture_does_not_close')
case.setUp()
try:
    case.capture('review-auto-complete', None)
    case.saving = True
    assert not case.close()
    assert not case.pilot.state()['enabled']
    case.pilot.finished(result={
        'next_url': 'https://www.pscube.jp/next',
        'remaining': 3, 'kind': '台別7日分'})
    assert case.pilot.completed is not None
    case.saving = False
    assert case.close()
    assert len(case.destroyed) == 1
finally:
    case.doCleanups()
```

実行結果は終了0。これは不具合候補の状態遷移を確認するための再現であり、修正後の成功試験ではない。

## 2. 継続調査：P’s CUBEの取り込み窓が閉じなかった理由

- **確認済みの過去記録**：10/31は最後の保存から24分以上、取り込み窓が残っていた。窓の状態表示は確認していない。
- **現在のコードで確認**：自動完了だけが終了対象。機種一覧の確認待ち、通信・保存失敗、日付不一致、手動停止などは同じ終了扱いではない。自動ループには例外を記録せず継続する箇所もあり、後から停止理由を区別しにくい。
- **未確認**：当時どの状態だったか、取り込み対象をすべて取り終えていたか。窓が残ったという事実だけでは、自動終了処理の故障とは断定できない。
- **提案**：まず完了／確認待ち／失敗／利用者停止を区別できる、個人データを含まない状態・時刻・残件数の記録を検討する。一定時間保存が無いという理由だけで完了扱いにしたり、窓を閉じたりしない。
- **完了条件案**：正常完了で閉じることと、未完了で待つ場合に理由を特定できることを別々に確認する。

出典：[10/31の観察記録](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/AI_COLLABORATION.md#L4543)、[自動ループ](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/database/pscube_import.py#L1989)。

## 3. 改善候補：iPhone閲覧ページの保存量と読み込み負荷

- **利用者の画面値として記録済み**：P’s CUBEは11/1に保存領域約1,566.2MB、本体約20.5MB、日別キャッシュ94日分。メルヘンの10/31の約210.6MBと同じ保存環境かは未確認なので、1日で約1.3GB増加したとはいえない。
- **現在のコードで確認**：P’s CUBEの `write()` は本体を読み、統合した本体を `state.put(..., 'data')` で保存する。日別保存の基盤はあるが、実際の閲覧経路への切替は残っている。
- **未確認**：約1.5GBの内訳・増加原因、実Safariのメモリ限界、同じ起動方法での保存量の推移。保存領域の空きが多いことだけで、読み込み時のメモリ不足がないとは判断しない。
- **提案**：同じ起動方法・同じ画面で診断値と更新時間を比較し、予定されている11/7の段階B検討に使う。必要に応じて保存先・キャッシュの件数を追加調査する。原因未特定のままキャッシュ・本体を消さない。
- 日別保存へ移す場合は、一貫した入力、独立した虹印、イベント・明示削除、途中終了からの再開、新旧の採点・表示一致を先に確認する。期間を短くして軽くするだけの変更は提案しない。
- 診断の「途中で終わった」はクラッシュだけを表さず、ページを閉じた場合なども含む。「最後まで終わった」も処理の成功・失敗両方で加算されるため、成功率やクラッシュ率として扱わない。

出典：[利用者のP’s CUBE診断値](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/AI_COLLABORATION.md#L4627)、[本体保存処理](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/database_android/web/pscube/viewer_bridge.mjs#L27)、[移行の設計と残件](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/VIEWER_DAY_STORE.md)、[診断値の定義](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/database_android/web/storage_report.mjs#L27)。

## 4. 準備候補：候補比較を、記録点検と成績評価に分ける

- 店舗別30日比較は予測日10/26〜11/24、最終評価は11/26以降に1回という計画。10/29の記録では、入力の記録・締切時点の復元まで実装済みで、30日比較の評価処理は未実装。
- **提案**：途中成績を見ずに、転送待ち・受領の欠落・版の欠落を点検する手順と、完全性検査が止まった場合の扱いを先に整える。今の実DBに欠落があるとは確認していない。
- 別計画の「★注目」の最終評価は10/31 08:00以降が条件。今回読んだ記録では完了結果を確認できず、既に実行されたかはわかりません。1回だけという計画なので、結果・実行履歴を確認してから判断する。今回どちらの成績も算出していない。

出典：[店舗別比較計画](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/NEXT_DAY_SHADOW_PLAN_20261025.md)、[実装の現在地の記録](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/AI_COLLABORATION.md#L4007)、[★注目の別計画](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/NEXT_DAY_FOCUS_PLAN_20260930.md#L63)。

## 修正済みとして切り分けた項目・自己点検

- 共有カレンダーの重複集計、店舗別更新日時、日別集計のみの表示、空表示、小額換算、説明・文字拡大は10/31に修正・公開済みという記録がある。今回、公開版・実Safariの再試験はしていない。[対応状況](https://github.com/imakurudev-eng/database/blob/4d02b9181905311fa4fd976f3d0585a1c6623e73/SHARED_CALENDAR_REVIEW_20261031.md)
- 11/1のおすすめ画面試験の待機修正は、その後のCI成功を直接確認。月替わりの問題として再提案しない。
- 上記の優先順位と対処方針はCodexの提案。根拠はリンクしたこのアプリのコード・計画・作業記録であり、第三者が同じ優先順位を推奨したという出典はない。
- 自己点検：模擬再現と実機発生、過去の観察と現在の状態、端末保存量と実行時メモリ、修正済みと残件、2つの評価計画を分離した。確認できない因果関係は断定していない。

## 続く利用者指示と対応（2026-11-01）

以下は初回調査後の更新であり、上の未修正・原因未特定の記述を該当範囲で更新する。

- 利用者が1番の修正を選択。PCのP’s CUBE `AutoPilot.capture_started()` を追加し、保存の入口 `Bridge.submit_page()` で、自動OFFなら古い完了状態を解析・保存前に解除する。保存失敗でも古い完了には戻さない。自動ループの終了判定は保存と同じロックを非待機で取得してから行い、確認直後の保存開始との競合を防ぐ。終了処理が失敗してもfinallyで解放する。
- 2番について利用者「原因わかりました。IPではじかれていただけです」。**利用者による原因確認**として記録し、原因未特定の調査候補から外す。AIは当時のHTTP応答や端末画面を直接確認していない。今回、アクセス制限を回避する変更や、停止状態で強制終了する変更は加えない。
- 3番について利用者「毎日記録していくしかないかなと」。同じ起動方法・同じページで診断値を日ごとに記録して推移を見る方針。自動記録・予約・通知を追加したという意味ではない。記録時は日時、版、保存領域、本体、日数、起動とDrive更新の時間・終了回数をそろえ、途中終了をクラッシュ件数と同一視しない。
- 回帰確認：修正前に新規2メソッドを実行し、入口で完了状態が残る失敗と新API未実装を確認。修正後はP’s CUBE関連4モジュール86件、自動取得共通33件が成功。追加3メソッドは各成功／失敗の2条件を含み、実際のBridge入口、保存中の終了保留、終了時ロック、例外時の解放を確認する。実サイト・実DBを使用しない。
- 試験実行の訂正：P’s CUBE4モジュールと同時に `test_auto_capture` を直下モジュールとして指定したコマンドは、P’s CUBE86件成功後、存在しないモジュール指定1件で終了1になった。共通試験は実際には `tests/test_auto_capture.py` にあるため、`python -B -m unittest discover -s tests -p test_auto_capture.py` でその33件だけ追加実行し成功。成功済みの86件は繰り返さない。Windowsの試験プロセス起動前にTZ=JST-9を設定し、UTCオフセット+09:00を実測した。
- 照合版は生成スクリプト3本で `5d3f5598f3d9` に更新。12個の照合用ファイルの差は版の文字列だけ。`node --test database_android/tool/test_release_info.mjs database_android/tool/test_viewer_parts.mjs` は15件成功。Googleの貼替・Web公開は不要。実機WebView2での確認と全体ゲートは未実行。PC修正・模擬試験の範囲で、APK・Webビルドの依頼はない。

修正の一次資料：`database/pscube_import.py` と `database/test_pscube_auto.py` の今回のローカル差分。利用者の2・3への回答の一次資料は本チャット。外部URLはない。
