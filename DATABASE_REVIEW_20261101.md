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

## 全体の見直し（2026-11-01 12時、Claude）

- 依頼：利用者「database全体をみて改善点がないかどうか検討を」。上のCodexの4件（最近の不具合・運用）と重ならない、構造・試験・文書・作業環境の改善点を探した。調査と提案のみ。
- 基準：手元main `0787314`（正本mainより1コミット先。そのコミットはCodexのP’s CUBE修正で、未push）。製品コード・試験・DB・設定は変更していない。試験・ビルド・CIは実行していない（読むだけの調査のため）。対象サイトへのアクセスなし。
- 見た範囲：コードの量と大きいファイル、PC・Android・閲覧ページ・共有ページの計算の重複、試験の置き場所と `check_before_build.sh`・CIの対象、README・文書の量、作業フォルダーの残り物、秘密情報の混入（追跡中のファイルに鍵・トークン・デプロイIDの形は見つからなかった）。全行の精読・実機確認はしていない。

### 優先度：高

**A. 採点・翌日候補の「PCとAndroidで同じ結果か」を、毎回の試験で確かめていない**
- メルヘンの採点はPC `database/core.py`（`VERSION = '2026-09-29-v12'`、`score`・`day_candidates`）と Android `database_android/lib/scoring.dart`（`scoringVersion = '2026-09-29-v12'`）の2つの実装。P’s CUBEはさらにJS `database_android/web/pscube/scoring.mjs` がある。
- それぞれ単体の試験はある（`database/tests/test_database.py` など、`database_android/test/scoring_test.dart` など）が、**両者を同じ入力で比べる照合**は `check_candidate_parity.py`・`tool/check_scoring_parity.dart`・`tool/check_focus_parity.dart` だけで、どれも実バックアップや `database/reports/` の出力を引数に取る手動ツール。`check_before_build.sh` にもCIにも入っていない（grepで確認）。
- 片方だけ係数や条件を直すと、表示する点数・候補がPCと閲覧ページで食い違い、気づきにくい。
- 提案：メルヘンの純益照合（`database_android/test/fixtures/meruhen_net_parity.json` をPC・Androidの両試験が読む方式）と同じく、**合成データの照合用fixture** を1つ作り、PC（unittest）とAndroid（flutter test）の両方で同じ期待値を確かめる。実データは使わない。採点の仕様は変えない。
- 費用：コード変更なのでpush時にCIが1回動く（約23分）。

### 優先度：中

**B. メルヘンの読み取りスクリプトがPCとAndroidで別々に書かれている**
- P’s CUBEは `tool/build_pscube_capture.mjs` が1つの元から `assets/pscube_capture.js` を作り、PC（`pscube_import.py` の `CAPTURE`）とAndroidが同じファイルを使う。
- メルヘンは、PCが `database/browser_import.py` 内の文字列、Androidが `database_android/lib/web_import_page.dart` 内の文字列（`_extractGraphScript`・`_extractTableScript`・`_pageIdentityScript` など約400行）で、別々に保守している。AGENTS.mdの「同じページか」の件のように、片方だけ直す事故が起きやすい形。
- 提案：次にメルヘンの読み取りを直す機会に、P’s CUBEと同じく1つのJSファイルから両方が読む形へ寄せる。大きな作り替えなので単独では急がない。

**C. 試験の置き場所が2か所あり、READMEの手順では一部しか流れない**
- PC試験は `database/tests/`（約60ファイル）と `database/test_*.py`（15ファイル、P’s CUBE・あにすろ関係）に分かれている。CIと `check_before_build.sh` は両方を流すが、`README.md` の手順は `unittest discover -s tests` だけで、15ファイルが抜ける。11/1にもCodexがモジュール指定を誤っている（上の記録）。
- 提案（すぐできる）：READMEに両方を流すコマンドを書く（.mdだけなのでCIは動かない）。ファイルを `tests/` へ移すのは、CIの手順も変わるので急がない。

**D. READMEの記述が現状と合わない**
- `README.md`「実サイトの自動巡回や自動保存は行いません」とあるが、現在はP’s CUBE・メルヘンの自動取得（`auto_capture.py`、`pscube_import.py` の `AutoPilot`、`PSCUBE_AUTO_CAPTURE.md`）がある。
- 提案：現在の動き（利用者が開いた取り込み窓での自動取得、間隔、対象サイトへのアクセスを増やさない方針）に合わせて書き直す。

**E. 共有記録と文書が大きくなりすぎている**
- `AI_COLLABORATION.md` は約1.35MB・4,699行（見出しは10月だけで164件）。ルートの `.md` は43個、`database/`・`database_android/` にさらに29個。日付入りの見直し文書（`*_REVIEW_2026xxxx.md` など）がルートに並ぶ。
- AIが毎回全体を読むことはできず、古い記録や取り消した方針を読み落とす原因になる。
- 提案：AGENTS.mdの「細かく書く」は保ったまま、`AI_COLLABORATION.md` を月ごとの保管ファイル（例：`notes/2026-10.md`）へ分け、本体には今月分と「今も効いている決定」の索引を残す。日付入りの見直し文書も同じ保管先へ移す。.mdだけの移動なのでCIは動かない。ただし他の文書からの相対リンクを直す必要があり、Codexと同時に動かすと競合するので、利用者の了承とCodexとの段取りが要る。

### 優先度：低（片付け・ついで）

**F. 作業フォルダーの残り物**
- `database/` に試験用の一時フォルダー7個（`tmp16je9s5y` など。10/20〜22作成、`test.db` 入り）。`.gitignore` 対象なので誤ってコミットはされない。後片付けの試験 `tests/test_sqlite_fixture_cleanup.py` は10/26にWindows向けに直されており、それ以前の残りの可能性が高い（未確認）。
- ルートに未追跡の `rows.json`（10/18、キャラ名の一覧）、`screen-now.png`、`debug.log`（WebView2のログ）、`review_packages/`、`CLAUDE_HISTORY_VIEW_HANDOFF_20261022.md`。`git add .` で混ざる恐れがある。
- 使い終わった作業ツリー：`.claude/worktrees/charming-carson-f7762b`（リポジトリ内、約92MB）、`../ci-bash-fix-20261021`、`../event-history-next-rack` はmainに取り込み済み。`../database-viewer-efficient`（`codex/viewer-drive-efficient-20261004`）は未取り込みのコミットが1つ残っている。
- 提案：利用者の了承を得てから、取り込み済みの作業ツリーと一時フォルダーを片付ける。未取り込みの1件と、未追跡ファイルを残すか消すかは利用者が決める。今回は何も消していない。

**G. エラーを黙って捨てる箇所**
- Androidの `lib/` に `catch (_) {}` が23か所（多くは埋め込みJS内のURL解析・localStorageで妥当）、PCに `except ...: pass` が9か所。Codexの2番（停止理由が後から分からない）と同じ種類の問題。
- 提案：一括では直さない。取り込み・保存・同期の経路にあるものだけ、次に触るときに記録を残す形に変える。

**H. 大きいファイル**
- `database/core.py` 3,573行（関数178）、`web_import_page.dart` 2,591行、`main.dart` 2,560行（クラス20）。作り替えの危険が大きいので、まとめて分割はしない。触るときに、関係する部分だけ別ファイルへ出す。

### 今回確かめていないこと

- 試験・ゲート・CIは流していない。上の指摘はコードと文書を読んだ結果で、不具合の再現ではない。
- Aの「PCとAndroidの採点が今食い違っているか」は確かめていない（照合の仕組みが毎回ない、という指摘）。
- 実機・公開ページ・Googleスクリプトの動作は見ていない。

## 追加の洗い出し（Codex 2回目）

### 基準・今回の結論

- 調査日：2026-11-01（日本時間）。正本 `imakurudev-eng/database/main` と手元mainは **`1b0943b3011778cfca5458ebd45029fe1ee1597a`**、`keyanbaitian6-cell/database-ci/main` は **`7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`**。両方を実際にfetchし、`git merge-base --is-ancestor 7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c HEAD` が終了0。正本と手元のSHA一致も確認した。以下のソースリンク・行番号はこの基準版。
- **追加候補は4件**。1・3は今回参照した既存記録に同じ指摘を見つけなかった。2・4は近い対策が既出なので、その対策が届いていない別経路と今回の再現に限定した。「誰も検討したことがない」とまでは確認できず、記録外の検討の有無はわかりません。
- 製品コード・既存試験・実DB・設定・Cookie・Google・公開物は変更しない。対象サイトへの接続、同期実行、実機操作、CI起動、ビルドはしない。変更は本報告と `AI_COLLABORATION.md` への追記のみ。試験は下記の一時DB・合成入力・模擬Driveだけ。
- 重要度・手間・提案はCodexの判断。手間は実装と関係する回帰確認の概算で、公開・Google貼替・利用者による実機確認の待ち時間を含めない。実運用の発生頻度・被害は4件とも未確認。

### 1. 自分用と共有用から同時に保存すると、成功した🌈を後の書き込みが消せる

- **種類／優先度**：不具合の候補／高。
- **対象の画面**：iPhone閲覧ページ・共有カレンダー・Google。PCは共有ファイルを読む側として影響を受けうる。
- **確認済みの根拠**：自分用と共有用は別のApps Scriptプロジェクトとして設置する指示がある（[viewer_drive_script_readonly.gs:1–20](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database_android/tool/viewer_drive_script_readonly.gs#L1)）。それでも同じ `database-rainbow-shared.json` を読み、統合し、全文を書き戻す。排他はどちらも `getScriptLock()`（[自分用:148–185](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database_android/tool/viewer_drive_script.gs#L148)、[共有用:109–146](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database_android/tool/viewer_drive_script_readonly.gs#L109)）。Google公式ではこのロックの範囲は当該スクリプトであり、別プロジェクトをまとめて排他しない（[LockService公式資料](https://developers.google.com/apps-script/reference/lock/lock-service#getScriptLock())）。
- **今回の再現**：実際の2本の `.gs` を別々のJavaScript実行環境で読み、同じ模擬Driveファイルとプロジェクト別ロックを与えた。自分用が旧内容を読んだ直後、共有用が538番の🌈を保存し、その後に自分用が537番を保存。**両方の返答は `ok:true` だが、最終ファイルは537番だけ**になった（1件、終了0）。同じ台の新旧判定では防げない、別の台同士の消失。
- **影響／未確認**：保存成功と表示された印が共有側から失われる。同じ読み込み→全文保存の形は履歴記号にもある（[event_history_drive.js:34–66](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database_android/tool/event_history_drive.js#L34)）が、今回の動的再現は🌈だけ。実Googleでの競合発生・頻度、消えた印が端末の保持分から再送されるかは未確認。台データ本体の消失を確認したものではない。
- **直す手間の目安**：中〜大、2〜4日。権限・接続先を維持する設計とGoogle側の移行確認が必要。
- **提案**：自分用・共有用の権限を区別したまま、共有編集の保存を1つの書き込み担当へ集約する案を先に設計する。別プロジェクトのまま `getUserLock()` へ変更するだけでは解決しない。単に読んだ版を保存直前に再確認するだけでも、確認と保存の間の競合が残る。既存の模擬試験へ「2プロジェクトで別々の台を同時保存して両方残る」を加える案。Google貼替・URL変更の要否は設計後に確認する。

### 2. PCの「この日に戻す」が、途中で失敗しても一部だけ反映済みになる

- **種類／優先度**：不具合の候補／高。
- **対象の画面**：PC（メルヘンのバックアップ・同期画面）。
- **既出との区別**：**既出：通常のバックアップ取り込みを一括確定する対策**。9/27「妥協点の見直しと修正」、10/2「バックアップ読み込みの完全性・欠測・時刻比較を修正」で通常取り込みを修正済み。今回の新しい根拠は、それを呼んだ後に上書きする **`restore_backup` の復元操作全体** が別々に確定する点。
- **確認済みの根拠**：[core.py:1735–1753](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/core.py#L1735) はまず `import_backup()` を呼ぶ。同関数は[2536–2587付近](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/core.py#L2536)で新規台・イベント等をトランザクション確定し、その後で `restore_backup` が競合台を `store.save(forced)` で上書きする。後半の例外は画面で「戻せません」となる（[app.py:1287–1304](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/app.py#L1287)）。
- **今回の再現**：一時DBに537番＝3000G、復元ファイルに537番＝4000Gと新規538番＝3000Gを用意。後半の `store.save` に保存失敗を注入したところ、復元は例外になったが、**新規538番は追加済み、537番は3000Gのまま**だった（PC模擬確認1）。通常取り込みの一括保存試験や、復元成功時の試験だけではこの境界を確かめられない（[既存試験:1386](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/tests/test_database.py#L1386)、[1858](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/tests/test_database.py#L1858)）。
- **影響／未確認**：失敗時に「何も変わらなかった」と判断できず、新規台・イベント等と競合台の復旧状態が混在しうる。強制終了・容量不足・DBロックそれぞれの実機再現はしていない。今回確認した混在は合成した保存失敗時のみ。
- **直す手間の目安**：中、1〜2日。
- **提案**：読み込み・分類・競合上書き・削除印からの明示復元までを、復元用の1トランザクションで確定する。既存の `import_backup` を外から `with db` で囲むだけで済むと決めつけず、内部の確定境界を整理する。後半の保存失敗で復元前と同じ状態に戻ることを一時DBで試験する。現在の「その後に追加した台を消さない」仕様は維持する。

### 3. PCの設定JSONが読めないと、次の選択操作で原文が上書きされる

- **種類／優先度**：不具合の候補／中。
- **対象の画面**：PC（店舗・日付選択、バックアップ・同期設定）。
- **確認済みの根拠**：[core.py:1673–1688](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/core.py#L1673) の `load_settings` はファイル不存在・読込失敗・不正JSON・辞書以外をすべて空の辞書にする。`save_settings` はその戻り値へ今回の項目だけを足し、同じファイルへ保存する。[app.py:729–745](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/app.py#L729)では店舗・日付・機種の選択変更がその保存を呼ぶ。
- **今回の再現**：一時フォルダーの `settings.json` を閉じ括弧が欠けた合成JSONにし、`load_settings` → `save_settings(last_day=...)` を実行。エラーにならず、**原文が日付だけの正常JSONで置き換わる**ことを確認（PC模擬確認2）。既存の原子的なファイル書換えは、書く途中の破損対策であり、読めない旧原文の保護とは別。
- **影響／未確認**：同期先 `sync_dir`、読込済みの目印、保存した選択などが失われ、同期の設定し直しや調査が必要になる。台のDBそのものを消す動作ではない。利用者の実設定が壊れているとは確認しておらず、破損原因・発生頻度はわかりません。これは既出Gの取り込み例外のログ追加とは異なる、設定原文の保持の問題。
- **直す手間の目安**：小〜中、半日〜1日。
- **提案**：「初回でファイルが無い」と「存在するが読めない」を区別する。後者では旧原文を保持して上書きせず、復旧・再設定を利用者が選べるようにする。設定値や合言葉をログへ丸ごと出さない。不正JSON・読込失敗・正常な初回作成を合成ファイルで確認する。

### 4. PCの手動バックアップには、同じ時点のDBを読む保護が届いていない

- **種類／優先度**：不具合の候補／中。
- **対象の画面**：PC。出来上がったファイルを取り込むAndroid等にも内容の不整合が伝わりうる。
- **既出との区別**：**既出：自動出力のスナップショット利用**。10/17「PC版を閉じるのに10〜15秒かかる」等に記録があり、[output_worker.py:20–25、65–74](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/output_worker.py#L20) はSQLiteの写しから出力する。この保護を未実装と再提案しない。新しい根拠は、手動経路がその処理を通らないこと。
- **確認済みの根拠**：[app.py:1020–1024](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/app.py#L1020) の手動保存は本体DBを開き、そのまま `export_backup` を呼ぶ。[core.py:1425–1432、1451–1468](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/core.py#L1425) はイベント・削除印等を先に読み、後から台をSELECTする。関数内で全読み取りを同一時点に固定しない。取り込み窓を閉じた後の別プロセスにも本体を直接読む呼び出しが残る（[browser_import.py:2574–2590](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/database/browser_import.py#L2574)）。
- **今回の再現**：一時DBの削除印を読んだ後、台を読む前に、別の実SQLite接続から537番を削除。**バックアップは台0件・削除印0件**となった。削除前の正しい状態（台1件）でも削除後の正しい状態（削除印1件）でもない。このファイルを同じ台がある別の一時DBへ通常取り込みすると、その台は消えず残った（PC模擬確認3）。
- **影響／未確認**：処理が成功して読めるJSONでも、その時点の変更を再現できない。通常の背景出力全体が危険という指摘ではない。手動保存中などに別接続が更新することが条件で、実運用の頻度・実Androidでの読込結果は未確認。PCの同時操作をファイル更新時刻から推定していない。
- **直す手間の目安**：中、1〜2日。
- **提案**：手動保存も既存のSQLiteの写しを使う方式へそろえるか、読み取り全体を1つのスナップショットにする。取り込み窓の直接呼び出しも対象にする。書き込みを長時間止めないことを確認し、バックアップには削除前か削除後の完全な組だけが入る試験を追加する。

### 除外・確認の限界・試験の扱い

- 依頼の除外1〜15を再提案していない。初回4件、Claude A〜H、11/1の利用者の決定、10/31の共有カレンダー7項目を先に照合した。採点・翌日候補の方式や成績評価、カメラアプリは扱わない。
- 追加で、過去記録の0時予約の開始位置・再試行上限、PC同期で壊れた入力が後続を妨げる件、Google処理版の表示のずれ、Googleの破損原本停止・時間枠による日別再開などを既出として外した。版表示だけの差をGoogle貼替の必要性と混同しない。
- Androidは `backup_service.dart`・`backup_destination.dart`・`database_service.dart`・`app_controller.dart` のバックアップ周辺、`pscube_store.dart` の書出し周辺、`pscube_day_upload.dart`、`pscube_import_page.dart` の0時予約周辺、`AutoCaptureService.kt`・`MainActivity.kt` のサービス接続を確認。通常版の書き込み順番待ちや一時ファイル清掃は既存実装があり、それを「無い」とは扱わない。実機の容量・WebView状態・常駐サービスの停止は未検証。
- Googleは閲覧用2本、メルヘン統合GS、P’s CUBE統合の生成元、日別履歴の共通処理を確認。公開物への実データ除外は `stage_viewer.py` と資産定義を点検したが、今回ステージ・ビルド・公開物の走査はしていない。PCの起動入口・出力ワーカー・固定依存・ゲート・CI定義も点検したが、依存の最新性・脆弱性監査はしていない。「安全」「最新」とは断定しない。
- **新規の調査用模擬確認は計4件、すべて終了0**（Python 3件、Node 1件）。これは問題状態が起きることをassertした結果であり、修正後の成功試験ではない。製品・既存試験ファイルに追加していない。Pythonは起動前 `TZ=JST-9`・`PYTHONUTF8=1`、プロセス内のUTCオフセット+09:00を確認。既存の全体試験を再実行していない。
- 文書2ファイルを実行・試験・ビルド・公開処理が読み込む箇所は今回の検索で見つからなかった（コメント・試験中の名前の例は除く）。既存 [.github/workflows/regression.yml:5–12](https://github.com/imakurudev-eng/database/blob/1b0943b3011778cfca5458ebd45029fe1ee1597a/.github/workflows/regression.yml#L5) のMarkdown除外を使い、CI定義・ジョブ・マトリクスは変更しない。無料枠や料金の削減額を算出していない。今後修正する場合の再現試験は既存の発見範囲へ入れ、別ジョブの追加は提案しない。
- 自己点検：別プロジェクト間の競合と同じ台の時刻比較、通常取り込みと日付復元、原子的な書換えと破損原文の保護、自動出力と手動出力を分けた。実Google・実機での発生を模擬確認から断定していない。上記の優先順位を第三者が推奨した出典はない（Codexの提案）。

### 模擬確認の再現方法（基準版のコードを使用）

以下は今回実行したコード。ネットワーク接続を行わず、実DB・実設定を開かない。Pythonは `database/` でコードを標準入力へ渡し、`$env:TZ='JST-9'; $env:PYTHONUTF8='1'; ... | ./.venv/Scripts/python.exe -B -` として実行した（3件、終了0）。`recording=False` は一時DBの検証履歴の作成を無効にする既存の引数。

```python
import json, tempfile
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from datetime import datetime, timedelta
from core import Store, restore_backup, export_backup, import_backup, save_settings, load_settings
assert datetime.now().astimezone().utcoffset() == timedelta(hours=9)
print("UTCオフセット確認: +09:00")
row = dict(store='saiwaichou',kind_code=21,day='2026-10-14',machine='合成試験',rack=537,games=3000,bb=10,rb=5)
with tempfile.TemporaryDirectory(prefix='database-review2-') as tmp:
    root=Path(tmp)
    with closing(Store(root/'restore.sqlite3',recording=False)) as db:
        db.save([row],log_candidates=False)
        incoming=dict(row,games=4000)
        added=dict(row,rack=538)
        source=root/'restore.json'
        source.write_text(json.dumps(dict(format='database-backup',version=1,records=[incoming,added])),encoding='utf-8')
        with patch.object(db,'save',side_effect=OSError('合成した保存失敗')):
            try: restore_backup(db,source)
            except OSError: pass
            else: raise AssertionError('保存失敗が起きていない')
        got={r['rack']:r['games'] for r in db.rows()}
        assert got == {537:3000,538:3000},got
        print('確認1 復元途中失敗: 新規538番だけ確定、537番の修復は未反映',got)
    settings=root/'settings-case'
    settings.mkdir()
    target=settings/'settings.json'
    broken='{"sync_dir":"合成の同期先",'
    target.write_text(broken,encoding='utf-8')
    assert load_settings(settings)=={}
    save_settings(settings,last_day='2026-10-14')
    assert load_settings(settings)=={'last_day':'2026-10-14'}
    assert target.read_text(encoding='utf-8')!=broken
    print('確認2 不正設定の次回保存: 原文が失われ、last_dayだけになった')
    with closing(Store(root/'export.sqlite3',recording=False)) as reader:
        reader.save([row],log_candidates=False)
        with closing(Store(root/'export.sqlite3',recording=False)) as writer:
            original=reader.history_edits_raw
            def concurrent_delete():
                writer.delete(row['store'],row['day'],row['machine'],row['rack'])
                return original()
            target=root/'mixed.json'
            with patch.object(reader,'history_edits_raw',side_effect=concurrent_delete):
                export_backup(reader,target)
            doc=json.loads(target.read_text(encoding='utf-8'))
            assert doc['records']==[] and doc['record_deletions']==[],doc
            assert len(writer.record_deletions())==1
            with closing(Store(root/'peer.sqlite3',recording=False)) as peer:
                peer.save([row],log_candidates=False)
                import_backup(peer,target)
                assert len(peer.rows())==1
            print('確認3 書出し中の別接続による削除: 台0件・削除印0件、読込先の台は残った')
print('模擬確認3件終了、すべて想定した問題状態を確認（修正後の成功ではない）')
```

Nodeはリポジトリ直下で次のコードを `node --input-type=module -` の標準入力へ渡した（1件、終了0）。ロックとDriveだけを模擬し、保存処理は2本の実GSを使用する。

```javascript
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
let text=JSON.stringify({format:'database-rainbow',version:1,marks:[]});
let interleave=null, secondReply;
const mark=rack=>({store:'saiwaichou',day:'2026-10-14',rack,on:true,updated_at:'2026-10-14T23:00:00+09:00'});
const file={
  isTrashed:()=>false,getLastUpdated:()=>new Date(1),
  getBlob:()=>({getDataAsString(){
    const snapshot=text;
    if(interleave){const run=interleave;interleave=null;run();}
    return snapshot;
  }}),
  setContent:value=>{text=value;}
};
const locks=[];
function context(filename){
  const state={held:false}; locks.push(state);
  const ctx=vm.createContext({
    DriveApp:{getFilesByName(name){
      const list=name==='database-rainbow-shared.json'?[file]:[];let i=0;
      return {hasNext:()=>i<list.length,next:()=>list[i++]};
    }},
    LockService:{getScriptLock:()=>({
      waitLock(){assert.equal(state.held,false);state.held=true;},
      releaseLock(){state.held=false;}
    })},
    ContentService:{MimeType:{JSON:'json'},createTextOutput:body=>({body,setMimeType(){return this;}})}
  });
  vm.runInContext(fs.readFileSync(filename,'utf8'),ctx);
  return ctx;
}
const mine=context('database_android/tool/viewer_drive_script.gs');
const shared=context('database_android/tool/viewer_drive_script_readonly.gs');
interleave=()=>{
  assert.equal(locks[0].held,true);
  secondReply=JSON.parse(shared.postRainbow([mark(538)]).body);
  assert.equal(secondReply.ok,true);
  assert.deepEqual(JSON.parse(text).marks.map(m=>m.rack),[538]);
};
const firstReply=JSON.parse(mine.postRainbow([mark(537)]).body);
assert.equal(firstReply.ok,true);
assert.deepEqual(JSON.parse(text).marks.map(m=>m.rack),[537]);
assert.ok(locks.every(s=>!s.held));
console.log('模擬確認1件: 両方ok:trueなのに先に保存された538番の印が失われ、537番だけ残った');
```

### 追記：利用者の決定・Claudeの対応とCI確定（2026-11-01）

- 上の4件は調査時点（`1b0943b`）の記録。以後の扱いは本項を優先する。
- **1は仕様として維持、修正・再提案しない**。利用者の決定を `RAINBOW.md`「共有ページから付ける」に記載済み。**2も対応しない**（利用者がほとんど使わないため）。
- **3・4はClaudeが `6936b9d` で修正済み**。3は不正な設定の原文を `settings.json.broken-日時` に保管してから保存し直し、開けないときは保存を見送る。4は手動保存と取り込み窓を閉じたときのバックアップをSQLiteの写しから出す。`delete_records`・`undo_last_save` の即時バックアップ、P’s CUBEの書き出しは今回の変更範囲に含めない。
- Codexが再開時に両mainを取得。正本と手元は `4fb1ee1232549e52aedb48a4b20e2f9c76e89278`、database-ciは `7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c` で、後者の包含を確認。Claudeの変更差分・共有記録・仕様の追記を確認した。
- **CI [41274330798](https://github.com/imakurudev-eng/database/actions/runs/41274330798) は full・pc (windows-latest, UTC)・pc (ubuntu-latest, UTC) の全3ジョブ成功**。CodexがGitHub接続ツールのジョブ一覧で直接確認し、fullの `Complete pre-build gate` 段も成功。ClaudeのローカルPC759件成功の記録と、このCIの直接確認を区別する。Codexはローカル試験・CIを再実行していない。
- 旧模擬コードは調査時点の問題を説明する履歴であり、現在の修正後コードで同じ結果になるとは扱わない。追加の製品修正・Google変更・実機操作・ビルド・公開は行っていない。根拠：[修正コミット](https://github.com/imakurudev-eng/database/commit/6936b9d)、`AI_COLLABORATION.md`「Codex 2回目の4件への利用者の決定と、3・4の修正（PC）」。
