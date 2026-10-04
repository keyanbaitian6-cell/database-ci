# database AI共同作業メモ

## PC版「結果を見る」のHTMLをFlip7風のデザインに（Claude、2026-10-04）

- 利用者「（Flip7 Design System のmdを渡して）パソコン上でのみ適用。結果を見る際のデザインをこのmdを参考に作り上げて」。対象は、PC本体の「結果を見る」で開くHTML3種（`core.py` の `report`＝機種の結果、`summary_report`＝この日のまとめ、`history_report`＝過去の記録）。Android・閲覧ページ（iPhone）・PC本体のTk画面は変更なし。
- 作り：共通の `FLIP7_CSS` と `FLIP7_FAN`（扇形のカード）を `core.py` に置き、各ページの元のCSSの**後ろ**に足して上書き（数値・文言・注意書き・並び・機能は変えない）。配色はティール・コーラル・ゴールド・クリーム、カード24px角丸＋色つきの光る影＋左の色帯、見出しはクリーム地・濃い枠・少し傾けたリボン風＋扇形カード、節の見出しは点線の下線、点数バッジは高＝金のグラデーション・中＝ティール・低＝クリーム、まとめの1〜3位は金・銀・銅の丸（1位は王冠が揺れ、点数がゆっくり光る）、注意（グラフ未取得など）はコーラルの帯。動きを減らす設定の端末では動きを止める。
- ついでの見やすさの修正：機種の結果の表で「補完・注意の理由」列が75pxに押し込まれ、1台の行が334pxの高さになっていた（変更前から）。列に最小幅320pxを付け、行は約98pxに。
- 確認：実データの**コピー**から3ページを作り、Playwrightで表示・クリック（詳細の窓）・ページのエラーなしを確認。PC試験187件＋P’s CUBE、`smoke_frozen_capture`・`smoke_frozen_runtime` 成功。`database/bin` 再ビルド（ZIPなし）。

## 閲覧ページ（iPhone）のGoogleドライブ読み込み：出し直しと「更新の目印だけ先に確認」（Claude、2026-10-04）

- 利用者「iPhoneブラウザ版でCUBEでもメルヘンでも、開いたときにGoogleドライブからの読み込みが失敗することが増えた。改善点を検討して」→ 提案のうち**1（出し直し）と2（更新の目印）**を実装。3（失敗時の表示）は「どうでもいい」、5（メルヘンのファイルを軽くする）は「やらないで」、4（PCの書き出しを減らす）は未指示のため未実施。
- 実測（PCから同じApps Scriptへ、2026-10-04。測定の負荷で悪化した可能性あり）：P’s CUBEのファイルは毎回約3秒（圧縮後170KB）。メルヘンは圧縮後2.0MBで、1回目は5〜9秒だが、**39秒、40〜90秒かかってから404**がたびたび出た。同時に2本出すと3回中3回、どちらかが4〜6秒で成功。固まるのは1回ごとで、待っても戻らない。直接開いたときの「現在、ファイルを開くことができません」は、プライベートタブでは開けた（Safariに残るGoogleのログイン情報の影響と推測）。閲覧ページ自身の時間切れの原因は未特定。
- **1 出し直し**（`web/drive_fetch.mjs` の `hedgedFetch`）：返事が8秒来なければ同じリクエストをもう1本出し、先に成功した方を使う（負けた方は止める）。404・429・5xx・通信失敗は、少し待って（1.5・3・3秒）次を出す。最初の1本と合わせて最大4本。外からの打ち切り（無応答の時計）は、勝った1本の本文の読み込みにも届く。403などは繰り返さない。
- **2 更新の目印**（`checkVersion`・`versionStore`・`tool/viewer_drive_script.gs`）：先に `?check=1` で、中身を読まず更新時刻＋サイズの目印だけを返してもらう（新しいApps Script）。前に読んだときと目印も書き出し時刻も同じなら、ファイルを読まない。目印は読む前に確かめ、読み終えて正しいと分かってから覚える。**古いApps Scriptは `?check=1` を知らず全文を返す**ので、その全文をそのまま使う（二重に読まない）＝更新しなくても動く。**目印を使うにはApps Scriptの更新が必要**（「デプロイを管理」→ 編集 → 新バージョン、URLは変わらない）。
- 配線：メルヘン `web/index.html` の `fromRemote`、P’s CUBE `web/pscube/sync.mjs` の `fetchDrive`（`pscube/viewer_bridge.mjs` 経由）。試験用の差し込み口 `window.databaseDriveFetch`（隔離環境では `import()` が使えないため）。Dart側は変更なし。
- 確認：`test_pscube_sync.mjs` 14件、`test_viewer_backup_parser.mjs` 32件（新規：目印・古いスクリプト・出し直し・遅い404）、`test_pscube_drive_browser.mjs`（実ブラウザ・新旧スクリプト）、新規 `tool/test_viewer_built_drive.mjs`（ビルドした実物の index.html）、JS一式が成功。Apps Scriptは手元の模擬で `?check=1` の返事を確認。**実際のiPhone・実サイト・更新後のApps Scriptでの動作は未確認**。
- 追記（同日）：閲覧ページを公開（database-viewer `6f83695`、`peekBody` が細切れの返事でも目印を読めるよう修正 `b0beba7` を含む）。ビルドした閲覧ページから本物のApps Script（更新前）で、メルヘン12,377件・P’s CUBE 2,659件を読めることを確認（P’s CUBEの1回は1本目が8秒無応答→出し直しの2本目で11.8秒で成功）。利用者がApps Scriptを新バージョンで更新し、`?check=1` が目印だけを返すことを確認（Chromeで直接開くと複数アカウントのため `/macros/u/1/` に書き換わって「ファイルを開くことができません」になるが、閲覧ページの読み込みには影響しない）。**利用者がiPhoneで確認OK**（読み込みエラーなし）。
- 利用者の提案（保存したデータはそのままに、開いたときの自動読み込みをやめ、日付指定で読み込む）への見解：方向（開くたびの大きな読み込みを減らす）には賛成。ただし日付指定にしても、Apps Scriptは直近60日の1ファイルしか返せず、日付で絞れない（絞るにはPCが日付ごとのファイルを書き、閲覧ページが足りない日だけ読んで合わせる作りに変える必要があり、大きな変更）。2の「先に更新の目印だけ確認」で、変わっていなければ開くたびの読み込みは数行で済む。

## 日別の差枚：日付リストのイベント名が出ない件（行の高さ・未公開）（Claude、2026-10-04）

- 利用者がiPhoneの「日別の差枚（推定）」を見て「日付リストにイベント名が出ていない」と報告（スクリーンショットは9/22〜9/30、イベント表示なし）。データ（`database-viewer.json` の `date_events`）には長町南の9/14〜10/2のイベントがある。
- 原因は2つ。①イベント名を日付の下に出す変更（`3396152`、10:53）は、公開済みの閲覧ページ（最新の公開 `a38c8ca` ＝ 90秒の待ち時間、00:55）より後で、**まだ公開していなかった**。②日付セルが2行（日付＋イベント名）になる表で、`DataTable` の行の高さが標準の48固定のため4pxはみ出す（`daily_net_test` の失敗の原因＝前の記録の「既知」はこれ）。
- 修正：イベント名を渡す画面（`eventFor` あり）の行の高さを56に（`lib/daily_net_page.dart`）。`daily_net_test` が通る。Flutter全456件成功。閲覧ページを `flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/` でビルドし、`tool/stage_viewer.py` で `C:/Users/keyan/database-viewer` に配置（記録の誤りなし）。**公開（commit・push）は利用者の確認待ち**。
- 公開版の差分（改行の違いを除く）：`main.dart.js`、`version.json`、P’s CUBEの読み取りスクリプト `assets/assets/pscube_*.js`・`pscube/data.mjs`（`autoPageState` が選ばれた日 `day` を返す、前の記録のとおり表示には影響しない）。

## P’s CUBE：手動で取り込むときも、次の機種・台番へ進む／0.5.24（Claude、2026-10-04）

- 利用者「CUBEのほうも変えて、ビルドまで」（メルヘンの「手動のときは一覧の上から探し直さず次の機種・台番へ」と同じ）。
- 変更（手動＝自動取り込みがOFFのときだけ）：保存したページの次から探す。全台一覧を保存したら、その機種の台別ページ（台番号の小さい順）へ。台別ページを保存したら、同じ機種の次の台番、済めば次の機種（機種の並びの順。向きが「下から」なら下→上）。最後まで行って残りが無いときだけ最初へ回る（取りこぼしの機種）。自動取り込みと、機種一覧を保存したあとの動きは変更なし。
- PC：`PscubeStore.import_page(manual=)`・`next_target(after=)`、`Bridge._submit_page` が `not pilot.auto.state()['enabled']` を渡す（`pscube_import.py`）。Android：`PscubeStore.importPage(manual:)`・`nextTarget(after)`、`pscube_import_page.dart` が `!_auto.enabled` を渡す。
- 確認：`test_pscube_import.py`（飛ばした甲機へ戻らない→乙機の台→丙機の表→最後は甲機へ回る）、`pscube_store_test.dart`（同じ流れ）。PC全187件＋P’s CUBE 46件、Flutter（P’s CUBE関連32件、全体は454件が成功し1件は既知の `daily_net_test`）。**実サイト・Android実機では未確認**。
- ビルド：`database/bin` 再ビルド（ZIPなし）、`smoke_frozen_capture`・`smoke_frozen_runtime` 成功。0.5.24には上のメルヘンの2件の修正（全角スペースの機種名・手動で次の機種へ）も含む。APK 通常版 `database-0.5.24-2026100406.apk`（`com.keyan.database_android`、92,804,977 bytes、SHA-256 `CB7CB73980C0D77E8B50171265A3C709E3B07D628E23B2CA5182B3D7FE211BF2`）、クローン `database-pscube-clone-0.5.24-2026100407.apk`（`com.keyan.database_android.pscube`、92,805,001 bytes、SHA-256 `73652903B69403A749498FC1A2C1275FB8B08092EC8DEA75A0553745298E5DFC`）。aaptでID・名前・版、apksignerで署名証明書が前回（0.5.23）と同一（`4332fcb9…`）を確認。出力はどちらも `a/work/outputs/`。

## メルヘン：手動で取り込むときは、機種一覧の上から探し直さず、次の機種へ進む（Claude、2026-10-04）

- 利用者「自動で取り込んでいる場合でないとき（手動で取り込みボタンを押しているとき）は、いちいち一番上からの機種を参照しないで、次の機種・台番に飛ぶ仕様にしてほしい」。
- 以前の動き：機種の台がすべて済むと機種一覧へ戻り、一覧の**最初**から未取込の機種を探していた（途中を飛ばした機種があると、毎回そこへ戻る）。台番は従来どおり、保存した台の次（番号の小さい順、先が無ければ最小）へ進む（`_find_next_ungraphed`、変更なし）。
- 変更：手動のときだけ、いま済ませた機種の**次**（一覧の並びの順。向きが「下から」なら下→上）から探す。先に見つからないときだけ、取りこぼしを探して一覧の最初から見直し、「最後まで来たので、一覧の最初から残りを探しました。」と知らせる。自動取り込みは変更なし（決めた向きで、日付指定・取りこぼしも含めて探す）。
- PC：機種一覧のURLの断片に `&database_after=<済ませた機種>` を付け（`machine_list_url(after=)`）、手動の移動（自動の移動番号なし）のときだけ `next_unimported_machine` へ渡す（`browser_import.py`）。
- Android：`_afterMachine` を、手動で機種が済んだときに覚えて一度だけ使う。順番は `machineSearchPasses`（`import_day.dart`）で決める。
- 確認：`tests/test_meruhen_day.py`（次の機種・最初へ戻る・下から・知らない機種名の無視・URLの印）、`tool/test_meruhen_machine_url.mjs`（手動は印を渡し、自動は渡さない）、`import_day_test.dart`（順番）。PC全187件・Flutter 454件が成功。Androidの画面そのものの通し試験は無い（順番の部品の試験のみ）。**実サイトでは未確認**。PCの実行ファイルは作り直し済み。Androidは未ビルド。
- P’s CUBEは変更していない（次のページは、保存後に「その日の未取得の先頭」を探す従来のまま）。
- 既知：`database_android/test/daily_net_test.dart`「月ごとの表…」が、別コミット `3396152`（日別差枚の日付リストにイベント表示）以降、日付リストの列が4px はみ出して失敗する（今回の変更とは無関係。変更を外しても失敗）。

## メルヘン「下から取り込む」で全角スペースの機種が開かない不具合の修正（Claude、2026-10-04）

- 利用者の報告：「下から取り込む」で次の機種（L無職転生）が見つからず、「該当する台情報が見つかりませんでした」の空ページになる。上からは問題なし。
- 原因：日付を指定すると機種の表を日付つきURLで直接開くが、そのURLの機種名を、画面の行の文字から組み立てるとき `\s+` を半角スペース1つに畳んでいた。サイトの正式な機種名は全角スペースを含む（保存済みURLに `L無職転生　NM` ＝ `%25E3%2580%2580`）ため、`L無職転生 NM` という存在しない名前で開き、空ページになった。全角スペースのある機種が一覧の下の方にあったので「下から」で先に当たった（上からでも、その機種に着けば同じ）。
- 修正：URLに使う名前だけ、畳むのを改行・半角スペースに限った（全角スペースは保つ）。照合・表示用の `name` は従来どおり正規化。PC `database/browser_import.py` の `machineLinks`、Android `lib/web_import_page.dart` の `_machineLinksScript`。サイトのリンク（`a[href*=machine_name]`）から読む経路はもともと正しい。
- 確認：新規 `database_android/tool/test_meruhen_machine_url.mjs`（修正前のコードでは失敗、修正後は成功）、PC全185件、`test_meruhen_cookie_browser.mjs`、Flutter analyze・日付指定の部品試験。PCの実行ファイル（`database/bin`）を作り直し。**Androidは未ビルド**（依頼があるまで作らない）。実サイトでの再確認は利用者待ち。
- 補足：同じ規則（Python `normalize_machine_name`・Dart `normalizeMachineName`）で機種名を比べる側は、全角・半角スペースを同一視して照合するだけなので変更していない。

## 日付指定取り込み・上から／下から取り込む・P’s CUBEのスクロール修正、0.5.23（Claude、2026-10-04）

- 利用者「寝てしまって取り込み途中で日付変わって自動取り込みが使えなくなった。PC・Android版ともに日付指定取り込みボタンが欲しい（P’s CUBEにも）。上から取り込む・下から取り込むボタンも」「台数が多い機種で下へ行こうとするのが速すぎて固まる件も検討」。利用者の選択：その日の分だけ取り込みを続ける／並びは機種の一覧の上から・下から／日付が変わる基準は日本時間の午前2時／P’s CUBEとメルヘンのPC・Android。仕様と限界は `database/IMPORT_DAY_AND_DIRECTION.md`。
- **P’s CUBE**（`563bca5`）：PCのカードとAndroid画面に、取り込む日（直近7日の営業日）の選択と「上から取り込む」「下から取り込む」を追加。日付を指定すると、表示中のページの日が違えば保存せず待つ（全台一覧はサイトの日付タブを手で合わせる。URLで日付を指定できるかは未確認のため、アプリは日付タブを押さない）。次のページはその日の未取得の先頭で、機種一覧を取り直しても最初の機種へ戻らない。全部済むと自動でOFFにして日付指定を外す。判定スクリプト `autoPageState` が選ばれた日 `day` を返す。
- **P’s CUBEの下へのスクロール**：350ミリ秒ごとに毎回一番下へ飛ぶ処理が、サイトの続きの読み込み（一番下に着いたとき）を詰まらせる原因と推測（実サイトでの再現はしていない）。少しずつ進み（画面の8割）、一番下に着いたら1回だけ「最後の台を見せて一番下へ」、新しい台が出るまで待つ（押し込まない）、届いたら400msおいて続ける、4秒増えなければ少し戻って再度下へ（最大5回）、設置台数に届いたら終了（不明なら3秒増えなければ終了）、最長約90秒に変更。PC `SCROLL_SCRIPT`・Android `waitForPscubeList` で同じ規則。Chromiumの試験で、20台ずつ届く64台・遅れて届く31台・止まった一覧（着いたときの1回と再試行だけ、`scrollTo`の連打なし）を確認。
- **メルヘン**（`6f1011d`）：同じボタンをPCのカード（`auto_capture.py`）とAndroid画面（`web_import_page.dart`）に。日付を指定すると、機種の表をサイトの行を押す代わりに日付つきURL（`…standlist_slot/?kind_code=21&machine_name=…&target_date=日付`。保存済みの取り込み元URLと行が反応しないときの予備の移動ですでに使っている形）で開く。別の日のページは保存しない（PC `_checked`・Androidの確認）。向きは機種の一覧を上から／下から。
- 確認：PC一式・P’s CUBE・新規 `tests/test_meruhen_day.py`（6件）、ブラウザ・JS 70件（カードの日付選択・開始ボタン、スクロール）、Flutter全454件、変更Dartのanalyze error/warning 0。実WebView2のメルヘンの確認（`smoke_auto_machine_switch` 成功、`smoke_auto_capture` は変更前のコードでも4回中1回時間切れ＝もともとのばらつき、変更後も4回中1回）、`smoke_browser_lifecycle` 成功。**実サイト・Android実機での動作は未確認**（日付つきURLで機種の表が開くか、日付タブを合わせたあとの続き、Androidの機種の選び方の通し試験）。
- ビルド：`database/bin` 再ビルド（ZIPなし）、`smoke_frozen_capture`・`smoke_frozen_runtime` 成功。APK 通常版 `database-0.5.23-2026100404.apk`（`com.keyan.database_android`、92,804,977 bytes、SHA-256 `2509285013B45019D1060256CD2D0B50C0C55E8BF7466F3FE877EE3333469B45`）、クローン `database-pscube-clone-0.5.23-2026100405.apk`（`com.keyan.database_android.pscube`、92,805,005 bytes、SHA-256 `6D7A8AFCDEE0CD5D0256DD93FC61AE15D685466EA1FBC886DD9DB8F340EBB3BC`）。aaptでID・名前・版、apksignerで署名証明書が前回までと同一（`4332fcb9…`）を確認。スマホは未接続のため現在の版は未確認。ビルドが `Invalid depfile … kernel_snapshot_program.d` で止まり終了コード127になったため、`.dart_tool/flutter_build` を消して再実行した（古い `apk/release/app-release.apk` は前回の0.5.22のまま残っていた：コピー前に版を確認すること）。
- 閲覧ページ（iPhone）の公開：待ち時間90秒の変更はCodexが公開済み（公開リポジトリの履歴は古い土台の上に作られていたが、中身は私の最新ビルドと同一：改行の違いだけ。`flutter_build` 一式のSHAで確認）。今回の変更は閲覧ページの画面には影響しないため再公開していない（`web/pscube/data.mjs` の `autoPageState` だけ公開版と差がある）。
- 作業中にCodexの別worktree `database-viewer-efficient`（ブランチ `codex/viewer-drive-efficient-20261004`）があることを確認。触っていない。

## iPhone閲覧ページのGoogle Drive待ち時間を90秒へ延長（2026-10-04）

- 利用者から、メルヘン閲覧ページで「Googleドライブから30秒間応答がなかったため」と表示される報告を受けた。`database_android/web/index.html`の`REMOTE_IDLE_MS`を30,000msから90,000msへ変更し、表示される秒数も定数から自動計算される既存処理を維持した。
- `database_android/tool/test_viewer_backup_parser.mjs`の時間切れ・データ到着ごとの再計測・iPhoneでページを戻したときの再計測テストを90秒に合わせた。直接実行で28件成功。`node --test`はこの環境の`spawn EPERM`で起動できなかった。
- `database_android/lib/viewer_main.dart`の説明コメントも90秒へ更新。採点、MY、最大持玉、保存データ、バックアップ形式は変更していない。
- Flutter再ビルドは前回のFlutterロックが残り無出力で停止した。実行環境の承認上限によりロック解除はできなかったため、直前の同一Web成果物に生成対象の`build/web/index.html`の30秒定数だけを90秒へ反映し、必須の`tool/stage_viewer.py`で公開用ステージを作成した。seed除外とステージ内の90秒設定を確認した。ブラウザ自動テストはChrome起動の`spawn EPERM`で未実行。

## メルヘンの推定差枚（PC・Android・閲覧ページ）と「日別の差枚（推定）」、0.5.22（Claude、2026-10-04）

- 利用者「追加の通信なしの推定差枚で構わないので実装。ビルドまで」「pscube同様に差枚表記のページを作って公開まで」「デザインは一緒に」。調査（`a/work/outputs/meruhen-investigation/REPORT_20261003_claude.md`）で特定したSVGの縦軸の規則で、保存済みのグラフ座標と最大持玉から推定差枚を計算（保存しない・表示のたびに計算）。仕様と根拠・限界は `database/MERUHEN_NET_ESTIMATE.md`。
- 実装（`fe283ce`）：PC `core.meruhen_net_estimate`＋結果の表に「推定差枚」列と注記。Android・閲覧ページ `lib/meruhen_net.dart`、`SlotRecord.estimatedNetMedals`／`netValue`／`netLabel`（P’s CUBEは確定差枚・メルヘンは推定差枚）。機種の表の差枚列・この日のまとめ・台の詳細で「推定差枚」と表示。日別ページは共通化（`lib/daily_net_page.dart`、`DailyNetPage`／`dailyNet`）し、メルヘンでは見出し「日別の差枚（推定）」と推定の注記。閲覧ページのホームに「日別の差枚（推定）」ボタン（P’s CUBEと同じ位置）。確定差枚の項目（`net_medals`）・採点・MY・最大持玉・保存形式は変更なし。決まらない台は空欄（0にしない）。
- 照合：PCとDartの計算が閲覧用データ11,806件で全件一致（全座標あり・4点のみの両方）。全座標で10,270件、4点のみで6,729件を推定、両方で出た6,372件中の食い違い1件。山・谷の時刻が無い古い4点の記録は、順番が分からないので上がり幅の下限を始点→山にした（並べ替えの差でPCとDartが27件食い違ったのを修正）。テスト：PC `tests/test_meruhen_net.py` 5件・PC全体成功、Flutter全443件成功（新規 `meruhen_net_test`・`daily_net_test` のメルヘン例）、analyze error/warning 0。
- ビルド：`database/bin` 再ビルド（ZIPなし）、`smoke_frozen_capture`・`smoke_frozen_runtime` 成功（ビルド中に `pscube.sqlite3` 等が変化＝利用者のP’s CUBE巡回）。APK 通常版 `database-0.5.22-2026100403.apk`（`com.keyan.database_android`、92,788,409 bytes、SHA-256 `8EAE9D2B9261A57B9A4C90DF3C116C079CF5D97E23121AC8D435CA90FB3BF54E`）、クローン `database-pscube-clone-0.5.22-2026100402.apk`（`com.keyan.database_android.pscube`、92,788,433 bytes、SHA-256 `33B192DD6488AC11DAA7A2658495BF29E884CB5EC171185586A05460554ADCC9`）。aaptでID・名前・版、apksignerで署名証明書が前回0.5.21（通常・クローン）と同一を確認。**注意**：最初の通常版ビルドは失敗していたのに古い `app-release.apk`（前回のクローン）をコピーしてしまい、aaptで気付いて削除・再ビルド（そのため通常版は2026100403、2026100401は欠番）。ビルド前に `app-release.apk` を消し、コピー後にaaptで確かめること。
- 公開：`flutter build web` →`tool/stage_viewer.py` 全体モード（記録文字列90件で該当なし）→公開リポジトリ `1c270c9`（Pages成功）。ステージ物で `test_pscube_browser.mjs` 成功、公開 `main.dart.js` 等はステージと一致、seed 404。公開ページに手元データを入れたヘッドレス表示で「日別の差枚（推定）」を確認、JSエラー0。手元表示の例（10/1 −60,083・243/355台、10/2 −33,284・257/355台、10/3 +127,582・353/355台）。

## 閲覧ページ（iPhone）：P’s CUBEの「日別の差枚」（Claude、2026-10-03 夜）

- 利用者の依頼と見本の写真（日付・総差枚・平均差枚・評価の月別表、見出しで並べ替え、期間累計、日付から当日へ）。「評価の欄はつけなくていい」。P’s CUBEのホームの「末尾別データまとめ」の下に「日別の差枚」ボタン→ `lib/pscube_daily_net_page.dart`（`3b58295`）。月の選択、表（日付・総差枚・平均差枚・取得台数）、期間累計の行（常に最後）、日付・総差枚・平均差枚で並べ替え、日付タップでホームのその日へ。既存の共通部品（Card・DataTable・Notice・Dropdown・`shortDayLabel`）で作成。
- 集計：選んだP’s CUBEの店舗・貸玉だけ。差枚を取得できた台だけの合計・平均（平均＝合計÷取得台数、期間累計も同じ）。差枚の無い台は数えず、無い日は「—」（0にしない）。サイトの数値異常の台は除外。「店舗全体の総差枚ではない」と注記（当たり0回・沖ドキ・未取得を含まない）。
- 検証：新規テスト2件（計算・画面：月の切替、累計、並べ替え、別貸玉を混ぜない、—表示、日付でホームへ）、Flutter全437件成功、analyze error/warning 0。Web版をビルドして既存 `tool/test_pscube_browser.mjs` 成功。手元の実データ（`database/data/pscube-viewer.json`）で393×852表示を確認（横にはみ出さない）。利用者「公開してください」→ `flutter build web`（base-href `/database-viewer/`）→ `tool/stage_viewer.py` 全体モード（記録の文字列90件で確認・該当なし）→ 公開リポジトリ `8d9eb91`（Pages成功）。ステージした中身で `test_pscube_browser.mjs` 成功。公開 `main.dart.js`・`flutter_bootstrap.js`・`pscube/data.mjs` はステージと一致、seed 404。前回の公開（`c8e86c8`、別環境のビルド）は `flutter_bootstrap.js` のエンジン情報が公開中のcanvaskitと食い違っていたが、今回は手元のビルド一式で揃った（canvaskit.wasmは同一）。公開ページに手元データを入れたヘッドレス表示で「日別の差枚」を確認、JSエラー0。

## P’s CUBEの差枚をPC・Androidの取り込みで保存（PR #1 を引き継いでmainへ、Claude、2026-10-03）

- 依頼：ChatGPT/Codexが中断したPR #1（`codex/handoff-pscube-net-pc-android-20261003`）をレビュー・修正・検証してmainへ。差枚＝`Graph.src` の各日の終点Y−始点Y（×`anjYUnit`）。MYとは別。メルヘンは見送り。
- レビュー結果：差枚の計算（`web/pscube/data.mjs` の `netMedalsOfProbe`）、生成スクリプト（ソースと一致・末尾の埋め込み可）、PCのPromise待ちとページ同一性の再確認は妥当。台別ページごとに `nc-m06-003.php` へサイト自身の認証値で1回通信が増える（認証値の使い回しはiPhoneショートカットで1120番台の実績あり、PC・Android実機は未確認）。
- **利用者の選択で変更**：差枚の元データが取れない（通信失敗・拒否・形式違い・準備前）ときも、台別の数値・グラフは保存して次へ進み、差枚は空欄（0にしない）で `net_warning`「差枚は未取得：…」をPCのカード・自動の状態、Androidの状態欄に出す（途中実装は保存を止め、3回失敗でその台に待機＝夜間の巡回が止まっていた）。
- Android：完了待ちを読み取りごとの番号で分け、前の読み取りの遅れた結果を取り違えない。`pscubeNetWarning`（`lib/pscube_auto.dart`）。
- 古い記録の差枚：日々の巡回で当たりのある台の台別ページを開くたび、サイトにある7日分の差枚が数値の同じ既存記録へ入る（`_merge`）。手動でもその台別ページで「未取得を取り込む」で再取り込みできる（取り込み済みでも断らない）。差枚未取得の別管理は追加していない。当たり0回の台は従来どおり台別へ行かないので差枚は空欄のまま。
- 検証：PC本体174件・P’s CUBE（`test_pscube_*`）全件、JS関連（net/data15/auto/sync9/scoring13/drive/scroll）成功、Flutter434件成功・失敗1件は実データ（303番台seed）が必要な既存テスト（例示seedのworktreeのため）、変更Dartのanalyze問題なし。`test_pscube_capture.mjs` は非公開アーカイブが無くSKIP（未実行扱い）、`test_pscube_browser.mjs` はWeb版のビルドが必要で未実行。**実WebView2（PC）**：新規 `database/tests/smoke_pscube_net_capture.py`（一時DB、全通信をWebView2内で応答し実サイトに接続しない）で自動の一覧→全台→台別、差枚7日分（1120例+14,118）保存・MY不変、取得拒否でも台別保存＋差枚空欄を確認。`smoke_cookie_retry.py` は間隔指定60秒がランダム5〜8秒化（`7e67027`）で拒否されていたため8秒へ直して成功。
- 反映：PRブランチへpush後、mainを `e79bc22` へ早送り（GitHubでPR #1はMERGED）。`database/bin` 再ビルド（ZIPなし）、`smoke_frozen_capture.py`・`smoke_frozen_runtime.py`（`a/work/outputs/frozen-runtime-pscube-net-20261003.json`）成功。ビルド前後で `database/data` の `database.sqlite3`・`last_save.json` が変化＝22:56に利用者のメルヘン取り込み窓（22:42起動）が保存したもの。P’s CUBEのデータは不変。
- **APKは未ビルド**（利用者「Android版のビルドはお願いしてからで」「まだ修正あるかも」）。ビルド時は通常版とクローン版（`com.keyan.database_android.pscube`、端末に0.5.21/2026100303）の両方を検討。端末の通常版は0.5.21/2026100302。実サイト・Android実機での差枚取得は未確認。

## P’s CUBEの元グラフから差枚を取り込む（Codex、2026-10-03）

- 利用者がiPhoneショートカットで取得した2026-10-02・1120番台の実応答を確認。`Graph.src.datas.g`の`YMD_biz`と`xField`/`yField`で日別系列を選び、`datas.p`の先頭Y=7,092、末尾Y=21,210から差枚+14,118枚と算出。バックアップのMY=14,209とは別値。認証情報や実応答はコミットしない。
- `database_android/web/pscube/graph_probe.mjs`で元数値を検証し、既存記録の台番号・営業日と一致するものだけに`net_medals`を追加。複数店舗・貸玉で同番号のときは停止。PC/Androidバックアップの読み書きも任意フィールドとして保持する。採点式は変更しない。
- 共通閲覧画面に「差枚の元データを貼り付け」、機種表に差枚列、日別には取得済み台数付きの合計・平均を追加。除外機種と未収集台があるため「店舗全体の総差枚」とは表示しない。Safariのショートカット実証コードは`database_android/tool/pscube_graph_shortcut.js`。日付指定がなければ日本時間の前日を取得する。
- 合成データ15件、PC取り込み11件、Flutter Webビルド、公開成果物でのChromium操作（貼り付け・保存・表示を含む）が成功。公開は`tool/stage_viewer.py`を経由し、実データseedを除く。

## 機種名・台番号検索の使い勝手改善（Codex、2026-10-03）

- 利用者の作業効率化・利便性改善依頼。Android結果・履歴とメルヘン/P’s CUBE共通閲覧画面に台番号の完全一致検索を追加。全角・`123番台`・`#123`に対応し、機種数が少なくても検索欄を表示。詳細・グラフ・日付切替へ条件を引き継ぐ。
- 一部の台だけを表示中は機種全体の削除ボタンを非表示。検索は表示対象だけに適用し、採点・候補・バラエティ区分・保存形式を維持。
- 関連46件成功、全体432件成功・実データ不足の既存採点テスト1件失敗（変更前でも再現）。解析error/warningなし・既存info17。Webビルドと既存Chromium回帰、全角台番号検索の実ブラウザ操作が成功。詳細 `database_android/SEARCH_USABILITY_REVIEW_20261003.md`。
- 利用者の追加許可を受け、iPhoneブラウザ向けの公開viewerも更新。公開先 `keyanbaitian6-cell/database-viewer` の `main` は `57782a472b199ea592651314a304ce2ffe97ecf7`。Pagesビルド成功、公開 `main.dart.js`・`flutter_bootstrap.js` のSHA-256がstage済み成果物と一致、seed URLは404。既存CanvasKitを維持して共通閲覧画面のChromium回帰と全角台番号検索を確認。APK生成・実機インストールは未実施。

## Androidの同機能クローン（Codex、2026-10-03）

- 利用者指定：既存版＋クローン1つ。クローンは`database P’s CUBE` / `com.keyan.database_android.pscube`。名前だけ用途を分け、両サイトの機能は既存と同じ。アプリ内の画面・採点・保存・Cookie・自動取得コードは変更しない。
- Gradle環境変数`DATABASE_ANDROID_CLONE=pscube`でID/ラベルだけを切替。未指定は既存版のID/ラベル。Activity/Serviceは完全修飾名で元のKotlinクラスを参照する。APKごとの規則に従いpubspecは0.5.21+2026100303へ増加。
- 既存版と別のDB/Cookie領域になり、Cookieはクローン内で手動認証。既存版の削除・データ消去・自動移行はしない。実機の同時取り込みと画面OFF継続は未確認。詳細`database_android/ANDROID_CLONE_BUILD.md`。
- ソース`785ac99`からreleaseビルド成功。APK `a/work/outputs/database-pscube-clone-0.5.21-2026100303.apk`、92,686,385 bytes、SHA256 `10B3958AA099DEB705DE19FF565AD17F21D8F1E1EC0CD93A0DBF02811A7F2C3B`。aaptのID/名前/version、署名、DEXの起動/サービスクラスを確認。元APKと3 ABIのlibapp.so・assets47ファイル一致。通常ビルドの元ID/名前も生成Manifestで確認。実機インストール/同時取り込みは未実施、既存seedのSHA不変。

## P’s CUBEのPC・Androidランダム待機（Codex、2026-10-03）

- 利用者指定：固定7.1秒から5〜8秒を数万通りでランダム化。0.0001秒刻み30,001通りを待機設定ごとに抽選。PCはsecrets、AndroidはRandom.secure。UIには範囲と抽選値を表示し、間隔スライダーは表示専用。
- メルヘン・保存・Cookie・採点は維持。拒否時の停止も維持。ランダム化でIP規制が解消するかはわからない。描画・保存・100msの確認周期があるため、実際のクリック時刻が100マイクロ秒刻みになる保証はない。
- PC106件、Flutter426件、疑似ページのChromium回帰が成功。Android0.5.21+2026100302。詳細とビルド後の結果は`database/PSCUBE_RANDOM_INTERVAL_20261003.md`。
- ソース`7e67027`から3EXEとrelease APK生成。生成3EXEの内蔵コード/JS/DLLと起動・両補助アプリ呼び出し・実WebView2のランダム間隔表示が成功（一時DB/ページのみ）。APKは`a/work/outputs/database-0.5.21-2026100302.apk`、署名は従来と同じ。実サイトとAndroid実機は未実施。最終解析error/warning0、既存info17件。

## Androidの各機種の全台表示待ち・0.5.20（Codex、2026-10-03）

- 利用者がPC版を試す間のAndroid版ビルドとインストールコマンドを依頼。PCと同じく、保存済みの設置台数未満なら約2秒の安定だけでは終えず、各機種で毎回下までスクロールする修正。最大70回、台数一致の保存ガード、台別取得、P’s CUBE初期7.1秒・メルヘン3.5秒を維持。
- 関連21件・全Flutter425件成功、analyze error/warning0・既存info17。一時DB/疑似時計で2機種の遅延6→31台、上限、ページ移動中断、設置台数読取による記録不変を確認。端末の現行0.5.19/2026100203は読み取りのみ。
- ソース `5c6027265a2de31fd88f250082d727a2f44cfbb0` をmainへ反映し、`flutter build apk --release --no-pub` 成功。APK `a/work/outputs/database-0.5.20-2026100301.apk`、92,686,361 bytes、SHA-256 `8B819E91574106732337F1E4CA3A027172B333C05FEE5B4AB1A48902EF69DDE6`。aaptで0.5.20/2026100301を確認、apksignerで署名有効・前回0.5.19 APKと証明書一致。ローカルseedのSHA不変も確認。
- 接続端末 `RFGL146LVVW` は0.5.19/2026100203で、新APKのversionCodeはそれより大きい。上書きは `adb -s RFGL146LVVW install -r <上記APKの絶対パス>`。アンインストール・データ消去は不要。インストール・新APKの実機WebView/実サイトは未実施。詳細 `database_android/PSCUBE_LIST_WAIT_FIX_20261003.md`、マニフェスト `a/work/outputs/android-list-wait-artifact-20261003.json`。

## PC P’s CUBE：表示6台・設置31台で3回失敗後に待機（Codex、2026-10-02）

- 利用者のスクリーンショットで台数不一致と3回失敗の待機を確認。約2.1秒台数が変わらないとスクロールを終える処理が、3秒後に追加表示される疑似ページでは6台で終了することを修正前に再現。
- 現在の機種URLの設置台数を読み取り専用で取得し、台数未満なら既存の最大70回の範囲で待機を継続するようPCだけ修正。台数一致の保存ガード、7.1秒、台別取得は維持。利用者の取り込み窓やCookieは操作していない。
- Python65件、Chromiumの各機種（2ページ）の遅延31台保存・移動とスクロール回帰、実WebView2の遅延31台待機が成功。利用者の追加指定「毎回下までスクロール」を確認。実サイトでの修正後取得は未確認。詳細 `database/PSCUBE_LIST_WAIT_FIX_20261002.md`。
- ソース `a53e8d1` をmainへpushし、`build_windows.ps1 -BuildTag pscube-list-wait-20261002` で `database/bin` の3フォルダ一式を再ビルド。`smoke_frozen_runtime.py` で内蔵コード/JS/DLL照合、メイン→両補助EXE起動、P’s CUBEの設置台数API公開を確認。マニフェスト `a/work/outputs/pc-pscube-31-cards-manifest-20261002.json`。APK再ビルドなし。
- 起動中の利用者P’s CUBE窓はPythonソース実行で残っているため、修正反映には窓を閉じて開き直す必要がある。検証はすべて一時DB・プロファイル・疑似ページ。検証期間に利用者側P’s CUBEのDB/閲覧JSON/Drive JSONの3ファイルの更新を観測したため、実データのSHA不変とは報告しない。更新原因は特定していない。検証EXEの引数は一時DBであることをマニフェストでも再確認。

## AndroidのP’s CUBE自動取り込みも初期7.1秒・APK 0.5.19（Claude、2026-10-02 夜）

- 利用者「Android版も7.1秒にしてビルド」「Pscubeだけだからね、7.1秒は」。P’s CUBE取り込み画面だけ、初期間隔を10秒→7.1秒、スライダーを0.1秒刻み・表示を小数1桁に（PC `e25902d` と同じ、範囲5〜60秒は維持）。定数 `pscubeAutoMinTenths/MaxTenths/DefaultTenths`（`lib/pscube_auto.dart`）。メルヘン（0.1〜4.5秒・初期3.5秒）は変更なし。テスト追加（7.0秒では見ない、7.1秒で判定）。Flutter全418件・変更ファイルの静的解析成功。
- APK `0.5.19 / 2026100203`（aaptで確認）`a/work/outputs/database-0.5.19-2026100203.apk`（92,686,361 bytes、SHA-256 `1B4EC3117D4351D2A1E010D2155BAE427D0005B839C3D8A87E946A17E134C22D`）。端末は現在0.5.18（2026100202）。インストールは利用者。
- **実機確認（利用者、0.5.19／2026100203をインストール後）**：P’s CUBEの間隔7.1秒・0.1秒刻み、メルヘンの間隔3.5秒のまま、P’s CUBEの人間確認がアプリを閉じて開き直しても保持（Cookie修正 `9abd6c7`・`31b3cbb`）、メルヘンの手動取り込み・保存、P’s CUBEの台別ページが表示され自動取り込みで保存まで進む、の5項目OK。メルヘンも閉じて開き直した後に人間確認を再要求されなかった（Codex `9f6e24b` のCookie保持、Android実機で確認）。止まったときの表示とP’s CUBEバックアップのPC読み込みは未確認。

## エージェントAIのレビュー2点の再現確認（Claude、2026-10-02 夜）

- 依頼：レビューで成立未確認の2点を、最新mainの既存ガードで確認し、再現したものだけ最小修正。DB・記録・Cookie・バックアップは消さない。実サイトの巡回・人間認証の自動操作なし。台別取得とPC初期7.1秒は維持。Androidのビルドは不要。
- **1. Windows WebView2：認証・同意先へのトップレベル遷移後のHTTPエラーで本文を置き換えるか → 再現・修正（`ee43dd7`）**。一時プロファイル・127.0.0.1の疑似ページ・本番の `BrowserConnection` / `install_webview2_handlers` / `present_connection_failure` で実測（WebView2 154）。どのページでもHTTPエラーは `WebResourceResponseReceived(4xx)` →`NavigationCompleted(IsSuccess=False, Unknown)` の順。許可リスト外のページ（同じホストの同意ページ、別パスの認証ページ、対象ページからの302で着く同意ページ）では `http_error` が無視するため、完了通知が「通信」失敗になり、サイトの本文（同意ボタン）がアプリのエラー画面に置き換わっていた（自動もOFF）。修正：表示中の文書そのものにサーバーが4xx以上で答えたら記録し（`document_status`、次の遷移で消す）、その完了通知は通信失敗にしない。対象ページの403で自動OFF・本文保持、DNS・接続不可のエラー画面、別URL（広告等）の4xxは従来どおり。回帰：`test_pscube_connection.py` に2件（修正前のコードで失敗を確認）、実WebView2のopt-in `tests/smoke_consent_http_error.py`（修正前は3ケースでエラー画面、修正後は本文が残る）。メルヘン側も同じクラスなので同じ扱い。
- **2. Android WebView：同一URLの再試行後に前回分の通信エラーが届いたら新しい試行を失敗にするか → 処理としてはする／実機で起きるかは未確認、修正なし**。`PscubeConnection.networkError` はURL（fragment除く）だけで今の文書に結び付け、試行の区別がない。再試行は `start` →reload→ `onPageStarted` で再び `start`。その後に同じURLの遅延エラーが届く条件を一時テスト（コミットせず削除）で模擬すると、失敗として記録され、新しい試行が正常に終わっても `canCapture=false` のまま。メルヘン `_failDocument` もURL一致だけで判定。webview_flutter の `WebResourceError` には遷移の識別子がなく、Android WebViewが前回分のエラーを新しい `onPageStarted` の後に届けるかは**未確認**。確認には、通信失敗を起こせる手元のサーバーと、実機（または実WebViewのインストルメンテーションテスト）でコールバックの順番を記録する必要がある（Androidのビルド・インストールが必要なため今回は実施せず）。影響は誤った停止表示（自動OFF・「もう一度開く」の再押下で回復）で、データは消えない。
- 検証：PC本体174件、P’s CUBE 63件、`smoke_cookie_retry.py`（両サイト・接続不可のエラー画面と復帰を含む）成功（既知のpywebview `_returnValuesCallbacks` 警告あり）。`database/bin` 再ビルド（ソース `ee43dd7`、ZIPなし）、`smoke_frozen_capture.py`・`smoke_frozen_runtime.py`（結果 `a/work/outputs/frozen-runtime-consent-http-20261002.json`）成功、`database/data` 直下13ファイルのSHA-256不変。

## P’s CUBE：台別ページは今後も取る（利用者の決定）・7.1秒の確認（Claude、2026-10-02 夜）

- 利用者の回答：スマホのChromeでは台番号を押した先（台別ページ）も「問題なし」で表示される。「全台一覧だけで取り込む（台別ページを開かない）」案は**変えちゃだめ**＝採用しない。台別ページの取得は今の仕様のまま。代わりに「取り込む間隔7.1秒にして今夜実行してみる」（7.1秒であることを確認済み）。
- 7.1秒はCodexの `e25902d`（PCのみ、0.1秒刻み、`database/bin` 再ビルド済み）で入っていたため、追加の変更はしていない。最新mainで初期値7.1・「サイトの記録を消してやり直す」・全台表示の一番下までのスクロールが残っていること、P’s CUBEのPCテストの成功を確認。起動中のP’s CUBE取り込み窓はなく、次に開くと7.1秒で始まる。Androidは変更なし（Codexの記録どおり）。

## PCのP’s CUBE自動取り込みを初期7.1秒に変更（Codex、2026-10-02）

- 利用者指定：10秒から7.1秒へ。PCのみ対応し、Android本体・バージョン・APKは変更しない。PCの範囲5〜60秒を維持し、スライダーを0.1秒刻み、表示を小数1桁へ変更。メルヘンの初期3.5秒は維持。
- PC関連235件成功。7.0秒では待機、7.1秒で処理開始する時計のテストと、Chromiumで初期値・表示・0.1秒操作・Python APIへ7.1を渡す検証が成功。ブラウザ検証スクリプトはdatabase_android/tool内にあるが、PCのpscube_import.pyのカードを検証するもの。
- `e25902db5bfb4fccf185e4b02a6d58d915714b72`をmainへ反映し、`database/build_windows.ps1 -BuildTag pc-interval-7p1-20261002`で3EXEを再ビルド。配布先は正本`database/bin`のdatabase・database-browser・database-pscubeの3フォルダ一式（依存DLLを含む）。APK再ビルドは未実施（利用者指定）。
- 生成EXEの内蔵コード・JSをソースと照合し、メイン画面→両補助EXE→実WebView2の起動、一時DBの表/グラフ保存が成功。通常の既存data参照先を確認し、利用者data直下13ファイルのSHA-256不変。ログ/ハッシュ/マニフェストは`a/work/outputs/pc-interval-7.1-*20261002.*`と`user-data-hashes-before-interval-20261002.json`。サイト上の実際のクリック間隔の測定は未実施。取り込み窓を閉じて開き直すと初期7.1秒になる。

## 最新mainのWindows検証・EXE/APK 0.5.18（Codex、2026-10-02）

- `9abd6c7`までの最新mainを正本へ取り込み、Cookie3修正と後続の共通閲覧画面・末尾印を保持。実WebView2でHTTP403後のfailed NavigationCompletedによる本文置換と、エラーHTMLのdata URIで元URLを失う問題を修正。小窓カードの高さも修正。`31b3cbb`をmainへpushしてEXE/APKをビルド。
- PC235件、Flutter417件、303番台の既存実データ1件、JS/Chromium回帰成功。analyzeはerror/warning0・info17（`--no-fatal-infos`）。両サイトの実WebView2でCookie/localStorageの再起動保持・同URLreload・fragment・HTTP403でOFF/本文保持・接続失敗後の復帰・一時DBの不変を確認。
- 3EXEの内蔵コード/JS/DLLを照合し、メイン画面から両補助EXEの起動とAPI初期化成功。WebView2 `154.0.4258.48`。通常rootが既存databaseであることを確認し、利用者data直下13ファイルのSHA-256不変。検証は明示的`--smoke-local`で一時DB/ページへ切り替えた。
- 配布：正本`database/bin`の3フォルダ。APK `a/work/outputs/database-0.5.18-2026100202.apk`、92,686,361 bytes、SHA-256 `97E3F06B105CA822CE560D203508EAAF988DF1671634B4CA5DF84C1FEE1B3C6A`。接続端末の旧APKと署名一致、versionCode増加確認。APKインストール・新APKの実機WebViewは未実施。非公開アーカイブ抽出は資料がなくSKIP。詳細と失敗/警告は`database/WINDOWS_COOKIE_VALIDATION_20261002.md`、ログは`a/work/outputs`。


## Cookie変更の既存動作への影響を再検討・追加修正（Codex、2026-10-02）

- 利用者指定：今までの動作への影響を再検討。最新 `44ffa13` のmainを取り込み、メルヘン/P’s CUBEのAndroid・PCの通常取り込み・移動・認証・保存を確認。
- 追加修正：同一URLはネイティブReloadで強制再読み込み。現在文書のfragmentで選んだ日付を保持。HTTP本文は認証画面の可能性があるため置換せず、DNSなどだけ専用エラー画面へ。pywebviewの公開load_urlでURL/準備状態を更新してから必要なReloadを実行。
- pywebviewのbefore_loadは同期なので、PCメルヘンの再試行はUI呼び出し中にAutoCaptureのロックを持たない。再試行中のON/別の再試行/保存開始を抑止。P’s CUBEのネイティブイベントからの自動状態更新も作業スレッドへ移した。
- 回帰：Flutter416件、PCメルヘン/既存174件＋P’s CUBE59件、変更Dart6ファイルのanalyze、抽出JS15件・Chromiumカードの検証が成功。実データ303番台の既存1件は例示seedのため除外、非公開アーカイブ未指定のP’s CUBE抽出テストはSKIP。
- 実機の認証/403/DNS/Windows WebView2は未確認、APK/EXE未生成。HTTP拒否でOFF、保存/確認中の再試行拒否は意図した変更。DB/採点/バックアップ形式の変更はない。詳細 `database/COOKIE_REGRESSION_REVIEW_20261002.md`。


## P’s CUBEブラウザ：日付ごとに手動の「末尾イベ」の印（Codex、2026-10-02）

- 利用者指定：イベントの多い店のため、末尾をやっていそうな日に分かりやすい印を付けたい。末尾別データまとめに共通テーマのSwitchListTile「末尾イベの印」を追加。手動で付け外しし、共通の日付欄・日付選択肢・日別の首位一覧に表示。自動判定や公式イベントとして扱わず、採点・ランキングの計算に印を使わない。
- 印は既存IndexedDBのP’s CUBEデータに任意の `suffix_events` を追加して保存（version 1を維持）。各要素は `store/rate/day/enabled/updated_at`。解除もfalseと更新時刻を保持し、古いバックアップで復活させない。既存の印なしファイルは引き続き読める。全台・機種データや元の店舗の保存内容は変更しない。
- ブラウザの書き出しに印を含め、ブラウザへの再取り込みで復元可能。PC・Androidの現行バックアップに印がなくても、手元のブラウザの印は残す。今回の編集・表示・保存はブラウザ版のみ。PC／Android本体での印の編集・保存は未実装（そちらで書き直したバックアップから別端末へ印を転送する機能はない）。
- 印の編集はIndexedDBの1トランザクションで現在のデータから更新。取り込み・機種タイプの保存時も、同トランザクションで最新の印をマージ。並行の取り込み・複数日の印の編集で印を失わない。保存失敗は印を変えず案内。保存結果を親のホームにも反映し、末尾画面も最新データで再集計。
- 検証：静的解析（変更6ファイル）、Flutter回帰49件（最終末尾9件含む）、JSデータ13件／同期9件／採点13件。ChromiumでON→再読み込み→日付欄／日別の印、バックアップ書き出し・再取り込み、解除→古い印付きファイルで復活しない、他貸玉の編集拒否、Drive更新時の解除保持、取り込みと2日分の同時編集を確認。元の店舗保持・機種タイプ・グラフ・入出力・Driveの2ブラウザスクリプトも成功。393×852で画面を目視。iPhone実機の新しい操作は未確認。
- 公開はFlutter 3.47.1の全体ビルドを必須の `tool/stage_viewer.py` 全体モードでstageしseedを除去。P’s CUBEの7ファイルがソースと同一であることも確認。既存の `--pscube-only` はbridge内のファイル判別用の文字列 `WebMainResource` をアーカイブ混入として誤検出するため、今回そちらのモードは採用せず全体stageを使用。

## P’s CUBE：選択日の末尾順位と日別の首位を先に表示（Codex、2026-10-02）

- 利用者指定：「この日はこの末尾が良かった」がすぐ分かるよう再構成し、既存databaseのデザインは維持。共通テーマの白いカード・ScorePill・日付切替・台表／グラフを使用。
- 機種タイプの直下に選択日の首位と上位3順位を表示。順位は既存採点の平均点（採点可能な記録のみ、暫定含む）。平均MY・平均G・取得グラフのプラス終点割合・採点件数／記録件数・暫定件数を併記。表示と同じ小数1桁で同点扱いし、未採点を0点や首位にしない。
- 「日別の首位」で日付と当日の首位・平均点・採点件数を一覧表示。日付のタップで選択日の順位へ戻る。標準は過去7暦日。比較期間を7日／30日／保存分にすると期間内の日別一覧と期間集計も表示し、選択日の順位と明確に分ける。長い一覧は直近7記録日から全記録日へ展開できる。
- 8末尾の全順位は共通テーマのシート、従来の数値一覧は展開式カードへ。末尾の内訳で既存の台表／グラフを使用。末尾0・1・2・3・5・6・7・8、MYの意味、DB・取り込み・採点式・保存形式を維持。未来・他店舗・他貸玉・数値異常の除外も維持。
- 確認：変更Dartの静的解析、Flutter回帰47件、JSデータ／採点／同期31件、Chromiumの共通UI・末尾順位／日別一覧／全順位／内訳グラフ・保存データ移行・元の店舗保持・入出力・Driveの2スクリプトが成功。393×852幅の表示を画像で確認。丸め境界・同点・採点なし・履歴の日付タップ・期間切替も検証。iPhone実機での今回の新表示は未確認。
- 公開用はFlutter 3.47.1でビルドし、必須の `tool/stage_viewer.py` でseedを除去。公開対象はコンパイル済みファイルのみ。

## メルヘンのCookie処理をPC・Androidでも修正（Codex、2026-10-02）

- 利用者指定：両版のメルヘン取り込みもCookie処理を検討・実装。PCはpywebviewのプライベート設定を解除し `data/meruhen-webview` に保持。P’s CUBEのプロファイルと分離。
- AndroidはCookie/JavaScript/チャネル/NavigationDelegate設定を順に待って初回読み込み。P’s CUBEの順序処理を `browser_session.dart` に共通化。設定失敗の再試行・画面破棄後のキャンセルも確認。
- 両版でCookie・SQLiteを消さないネイティブ再読み込み。主ページのDNS/HTTP失敗でOFF、確認・保存中の再試行を拒否。PCのエラー監視・画面はP’s CUBEの実装をURL条件付きで共有。再読み込み前に古い次ページ移動通知を取り消す。
- 検証：PC173件＋P’s CUBE56件、Flutter409件成功（実データを参照する既存1件は例示seedのため除外）。変更Dart 6ファイルのanalyzeは問題なし。Chromiumの再試行・Cookie/保存値保持・エラー画面と既存の表/グラフJS回帰を確認。
- 実機の認証保持/403/DNSとWindows WebView2は未確認。APK/EXE未生成。詳細は `database/MERUHEN_COOKIE_REVIEW_20261002.md`。通常のgit pushの書き込み認証がないため、接続済みGitHubアカウント経由で同一内容をmainへ反映する。


## P’s CUBE：Cookie設定順と接続失敗時の復帰をAndroid・PCで修正（Codex、2026-10-02）

- 利用者指定：Android 0.5.16でChromeからは開けるがアプリの取得通信は403、添付画面は `ERR_NAME_NOT_RESOLVED`。Cookieを消して認証が出てもアプリからは開けない。Cookie処理の変更とPC版の編集を依頼。
- AndroidはCookie・JavaScript・NavigationDelegateの設定完了後に初回通信する。Cookie設定が失敗した場合や画面破棄後は開かない。初期化中・読み込み失敗中の取得を防ぐ。
- 両版にCookie・SQLite記録を消さないネイティブ再読み込みを追加。DNS/主ページの通信失敗と、現在の既知ページに対応するHTTP 400以上で自動取り込みを停止。広告・認証・別台の失敗は混ぜない。初回のWindows WebView2初期化前からNavigationイベントを監視する。
- エラー履歴は画面の存続中だけ最大8件、クエリやCookie値を除外。取得中の失敗はAndroidのページ世代を無効化し、保存開始前のデータを拒否。保存済み記録を削除・初期化しない。
- Cookie消去は既存の確認付き操作のみ。Androidはabout:blankの完了後、PCはWebView2停止後に消す。自動停止の案内をCookie消去から保持再試行へ変更。
- 検証：PC関連56件・既存167件成功。Flutter全体407件成功、実データ303番台を参照する既存1件は空の例示seedでは失敗（実データを補わず除外して再実行）。変更した6ファイルのanalyzeは問題なし。Chromiumで両版共用のページ判定・PCカード・Cookie/保存値保持再試行・DNSエラー画面・消去確認・保存中の操作拒否・360×300表示を確認。
- 未確認：実機AndroidのDNS差と403の解消、実際の人間認証、Windows WebView2実動作。未知APIパスの403は今回のHTTP判定対象外。APK/Windows EXEはこのLinux環境では生成していない。端末の0.5.16や既存EXEはソース変更だけでは更新されない。
- 詳細は `database/PSCUBE_ACCESS_PLAN.md` の2026-10-02追記。


## P’s CUBE：末尾別データまとめを追加（Codex）

- 利用者の指定：店の傾向を見るため、末尾0・1・2・3・5・6・7・8のデータまとめを項目追加。P’s CUBEのホームに既存と同じアウトラインボタンを追加。共通の日付切替・テーマ・台ごとの表／グラフを使う。
- 選択日、過去7暦日、過去30暦日、選択日までの保存分で集計。未来の記録・別店舗・別貸玉は混ぜず、全機種／ノーマル／それ以外を切り替え可能。台数は台番号の重複を除き、記録件数は台×日で数える。
- 表示は台数・記録件数・平均G・平均MY・平均点・採点件数・取得グラフのプラス終点割合。MYは差枚へ変換しない。数値異常を除外し、未採点を0点、グラフ未取得をマイナス扱いにしない。末尾の内訳でBB／RB／AT・ARTと日別の台表／グラフを確認できる。元の取り込み・DB・採点方式は変更していない。
- 検証：静的解析、末尾集計／画面の5件を含むFlutter回帰45件、Chromiumで末尾項目→8末尾の表→内訳→グラフと既存の保存／日付移動／入出力／Driveのブラウザテストが成功。iPhone幅393pxで確認。iPhone実機での新項目の操作は未確認。
- 作業用クラウドの接続障害により、最新mainから確認用ブランチ `codex/pscube-suffix-20261002` でGitHub Actionsを使って検証・ビルド。`stage_viewer.py`で記録を除いた公開用ビルドを作成。確認用workflow・ビルド搬送用ファイルはmainへ取り込まない。Actions成功: https://github.com/imakurudev-eng/database/actions/runs/36958468919


## 利用者指定：新しく作るものも既存databaseをベースにする

- 利用者「新しく作るときはこれをベースにするっていうルールを設けて」。恒久ルールをリポジトリ直下の `AGENTS.md` に記載し、`database_android/AGENTS.md` からも参照する。
- 関連する新規プロジェクト・他サイト対応も既存databaseのデザイン・画面・操作・基本仕様を継承。共通の閲覧画面を再利用し、サイト固有の取得・解析・入力変換と値の意味に必要な差分を追加する。プロジェクトを分ける場合は新しい `AGENTS.md` へルールを引き継ぐ。
- P’s CUBEの共通画面への修正はソース `e9d7dc1`、公開版 `c0031ca`。Pages公開成功と配信ファイルの一致を確認。利用者から「iPhoneでひらけた」と起動成功の報告あり。iPhoneでの操作全般の検証を完了したという意味ではない。

## ブラウザ版P’s CUBEの画面を既存databaseへ統一（Codex）

- 利用者の修正依頼：既存databaseとほぼ同じデザイン・仕様で、読み込むデータだけがP’s CUBEへ変わる構成。独立HTMLの一覧画面を廃止し、`viewer_main.dart`・`viewer_pages.dart`・共通の表／グラフ／日付切替／翌日候補をそのまま共用。`/pscube/`も同じFlutterビルドを起動する。
- 入力時にP’s CUBEのJSONを共通のSlotRecordへ変換。MYは`extra['my']`に保持し、メルヘンの最大持玉へ書き換えない。店舗・貸玉を区別し、ノーマル／それ以外の採点・機種タイプ変更を維持。Android／PCの収集処理は変更していない。
- 旧版のIndexedDB `database-pscube-viewer`／`state`の`data`・`meta`を読み継ぐ。元の閲覧ページでもP’s CUBE JSON／WebArchiveを読み込める。メルヘンの保存データを消さず、最後に開いたデータ種別を保存。Googleドライブは従来の`?file=pscube`、P’s CUBEバックアップ書き出しも維持。
- 確認：FlutterのP’s CUBE変換・共通画面と既存閲覧の回帰49件、JSのデータ／採点／同期31件、元のバックアップパーサ28件、静的解析成功。Chromiumで旧保存データの移行、機種表／グラフ切替、日付移動、メルヘン保存内容の保持、ファイル読み込み／書き出し／タイプ変更、失敗時の内容保持、ドライブ同期を確認。iPhone実機Safariは未確認。
- 公開は必ず`stage_viewer.py`で記録を除いたビルドを使う。`--pscube-only`は共通Flutterビルドが既に更新済みの場合だけ使用可能。

## 2026-10-02 朝：P’s CUBEで止められた件、「サイトの記録を消してやり直す」、APK 0.5.17（Claude）

- 利用者「Android版で7時間くらいあけてアクセスしたけど蹴られてる」「クロームならひらけた」「PC版もお願い」。回線ではなくアプリのCookie等と考え、Android（右上のクッキーのボタン）とPC（取り込みカード下）に「サイトの記録を消してやり直す」を追加（`ab393d4`）。確認→自動OFF→Cookie・localStorage・sessionStorage・IndexedDB・キャッシュを消す→最初のページへ。取り込んだ記録は消さない。保存中は断る。止められた気配での自動停止の案内文にこのボタンを追記。詳細は `database/PSCUBE_ACCESS_PLAN.md` の末尾。
- 確認：PC（P’s CUBE 48件・本体167件）、JS全80件（ボタンの確認・保存中は断るをブラウザ試験に追加）、Flutter全391件、静的解析。pywebview（WebView2）は `AreDefaultScriptDialogsEnabled = True` で確認ダイアログを出せる。
- ビルド：APK `0.5.17 / 2026100201`（ソース `17c0551`、Codexのバックアップ修正 `22b8840` も含む）`a/work/outputs/database-0.5.17-2026100201.apk`（92,555,289 bytes、SHA-256 `55F2ECE91F9449327A913F24507D915EBEF0DAEF7C5AC4EC0B437D6162C6D3F6`）。Windows 3アプリ再ビルド・`smoke_frozen_capture.py` 成功（ZIPなし）。インストールは利用者。
- その後の報告：記録を消すと人間確認は出直したが、台番号を押した先（台別ページ）はやはり何も表示されない。機種一覧・全台一覧は出る。Cookieではなく、台別ページだけ接続元単位で止められている可能性（推測）。利用者に、スマホのChromeで台別ページが出るかの確認と、「台別ページを開かず全台一覧だけで取り込む」（1日約350→約60ページ）を進めてよいかを質問中。

## 2026-10-02 1時：PC版P’s CUBEの自動取り込みが全台一覧で止まる件（Claude）

- 利用者「やはり今フリーズしてる。PC版」。画面は「L北斗 転生の章2」の全台一覧で「表示は6台、設置台数は7台です。全台を表示してから取り込んでください。」、自動取り込みはOFF（利用者が止めた状態）。窓自体は操作できた。PCの記録では設置台数7・この機種の台は未保存。
- 原因：サイトは続きの台を「ページの一番下まで来たとき」に読み込む。PCの全台表示 `SCROLL_SCRIPT` は最後の台を見える位置へ動かすだけで一番下まで行かず、6台のまま取り込み→台数の不一致で失敗→やり直しも同じ6台→3回失敗で「同じページで3回失敗したため待機中」になり、止まって見えた。Android版の全台表示は最初から `window.scrollTo(0, scrollHeight)` もしていたので起きない。
- 修正（`de3a756`）：PCの `SCROLL_SCRIPT` にも一番下までの移動を追加（Androidと同じ）。`tool/test_pscube_scroll.mjs` に「一番下でだけ7台目が出るページ」を追加し、修正後は7台、修正前の処理では6台のままになることを確認。PC・P’s CUBE・JS全80件成功。`database/bin` 再ビルド・`smoke_frozen_capture.py` 成功（ZIPなし）。起動中の取り込み窓は古い処理のままなので、開き直しが必要。

## 2026-10-02：Codexのバックアップ修正を点検してコミット、店舗欄の文字色、PC再ビルド（Claude）

- **点検**：Codexの差分（すぐ下の項目）を読み、テストを自分でも実行。PC 167件＋P’s CUBE 44件、Flutter全391件、JS全80件（ブラウザ試験は `PLAYWRIGHT_MODULE=file:///…/playwright/index.mjs` を指定）、変更Dartの静的解析すべて成功。`22b8840` としてコミット・push。
- **実ファイルで確認（読むだけ）**：新しい読み込みで、PCの `data/database-backup-auto.json`（6,015件）・`data/database-viewer.json`（10,030件）、同期フォルダの日別バックアップ・自動・閲覧用・P’s CUBE各ファイルを読み、どれも対象外0件。例外は同期フォルダの `backups/database-backup-2026-09-28.json` だけで、ファイル末尾が最後の台の途中で切れていて閉じ括弧もない不完全なファイル（26,556,981 bytes、6,049行目の途中まで）。切れた行は修正前の処理でも読めないため、拒否されるのは正しい。ファイルには触れていない。
- **店舗欄の文字色**（利用者「見えにくい問題があるなら文字色変えて対応して」）：読み取り専用の選択欄の文字・選択中の文字を濃い色、背景を白に固定（`da3ec33`）。選べないイベント欄は灰色。
- **PC再ビルド**：Windows 3アプリを `database/bin` に再ビルド（ソース `22b8840`）。`smoke_frozen_capture.py` 成功。ZIPは作っていない（利用者の指示どおり、頼まれたときだけ）。正本フォルダには `database/.runtime` が無いため、ビルドのPythonは旧フォルダの `.runtime\Scripts\python.exe` を指定した（旧フォルダのファイルは変更していない）。
- **未反映**：Android実機（APK未ビルド）と公開中の閲覧ページ（バージョン検査・欠測の扱い、P’s CUBEの沖ドキを一覧に出さない変更）。どちらも利用者の指示待ち。

## 2026-10-02：バックアップ読み込みの完全性・欠測・時刻比較を修正（Codex）

- 利用者の依頼：バックアップの読み込み処理を検討し、問題があれば修正。PC・Android・ブラウザのメルヘンとP’s CUBEを確認。開始時はmain `5e3db39`、fetch/pull --ff-only成功・未変更。作業中に別作業の `da3ec33`（PCの店舗選択欄の文字色のみ）がmainへ入り、バックアップ変更との重なりなし。`app.py` と参照フォルダのファイルには触れていない。
- PC `core.py`：従来の行ごとの読み込みは閉じ括弧不足・カンマ不足・余分な末尾を検査せず、全文形式ではformat/version/sourceの検査が抜け、末尾のイベントや候補を落とす経路があった。各台を個別に読み、値をnullに置いた外枠のJSONを最後まで検査する方式へ。重複項目、未対応版、閲覧用・救出用ファイル、不正なイベント／読めない候補を保存前に拒否。全文・整形・行形式で同じ検査。末尾のメタデータ、BOMつき・先頭空行も対応。イベント・台・候補の保存は既存の1トランザクションを維持。
- 欠測：PC、Android `BackupPlanner`、ブラウザ `ViewerData` でgames/BB/RBの未入力を0に変える経路、端数の台番号等を受け付ける経路を止める。不正な台は対象外として数え、正常な台の取り込みは継続。実際の0回転・当たり0回は有効な記録として保持。最大持玉等の任意項目のnullは欠測のまま。採点v12・翌日候補の式・バラエティ条件は変更なし。
- 閲覧用JS `web/index.html`：未対応・欠けたversionをどの書式でも拒否し、同じexported_atによる読み飛ばしの前にもヘッダーを検査する。PCの軽い閲覧用ファイルは閲覧ページで引き続き読める。
- P’s CUBE PC：observed_atを文字列で比べると、UTCと+09:00等で新旧が逆になり得た。Android／Webと同じく時刻を比較し、不正な更新時刻は保存前に拒否。古い時刻で新しい数値を上書きしない既存ルール、数値一致時のdailyグラフ優先は維持。
- 回帰確認：PC追加10件（合成データ・一時DB）。元のGitコードをメモリ上で実行すると9テストで失敗することを確認。修正後はPC一式167件＋P’s CUBE一式44件成功。Flutter対象71件成功、最終全391件成功。既存の取り込み成功テストが0番台を含んでいたため、意図の同じ正常な1〜5番台へ入力だけを変更。JS読み込み28件成功。変更Dartファイルの静的解析は指摘なし、git diff --check成功。
- 最終FlutterログはGit外 `database_android/build/backup-review-tests-20261002-final.jsonl`。本番の登録DBと利用者のバックアップには読み書きしていない。既存seedは既存の採点テストで読み取っただけで、変更していない。参照フォルダはarchiveブランチ・旧APK1件のみ未追跡の状態を確認し、変更していない。
- 今回はソース修正とテストまで。コミット・push・EXE/APK/Webビルド・公開・インストールは未実施。PCの指定start.cmdは次回起動から修正ソースを使う。配布EXE・Android実機・公開ブラウザへは未反映。実機でのバックアップ操作は未確認。

## 2026-10-02：PC本体でP’s CUBEを店舗として選べるように（Claude）

- 利用者「PC版でバックアップを読み込むとか諸々に全くpscubeがない。単独店舗とはいえちゃんと項目を作って」。`app.py` の「結果を見る」の店舗と「範囲を指定して書き出す」の店舗に「P’s CUBE（スロット）」を追加（`17b1545`）。結果を見る：P’s CUBEの日付・機種（沖ドキは出さない）を専用の記録から出す。イベントは選べない。「選んだ機種の結果を開く」「過去の記録を見る」はP’s CUBEの閲覧ページ（採点・翌日候補、ドライブの自動読み込み）を既定のブラウザで開く。台記録の削除・まとめて削除・設定情報はP’s CUBEでは「対象外です」と出してP’s CUBEの記録を変えない。書き出し：P’s CUBEを選ぶと全期間を `pscube-backup-pc-YYYYMMDD-HHMMSS.json` で同期フォルダ（無ければ保存先を選ぶ）へ。読み込みは前回からファイル先頭で振り分け済み。`pscube_import` に `days`・`machines_for`・`backup_file_name`・`write_backup`。
- 確認：P’s CUBE 44件・PC全テスト成功。本番と分けた別の場所（検証用のP’s CUBE 39件）で本体を起動し、結果を見るの店舗一覧に3店舗目としてP’s CUBEが出て、選ぶとP’s CUBEの日付（10/01）・機種（ﾏｲｼﾞｬｸﾞﾗｰV）になりイベント欄が無効、メルヘンへ戻すと有効に戻ること、書き出しの店舗一覧にもP’s CUBEが出ることを画面で確認（起動直後は選択中の店舗名が白く見えにくい描き方が残る。操作すると表示される）。`database/bin` 再ビルド（ZIPは作らない）。

## 2026-10-02：PC版P’s CUBEの自動取り込みが途中で止まる件（Claude）

- 利用者の報告「cubeの方も自動移り変わりで固まった（PC版）」。止まったときの表示は無く、窓は閉じられていた。PC版の記録（コピーを読み取り）では10/1の8機種まで進み、次は9機種目の全台一覧（残り52件）。URLの食い違い（メルヘンで起きたもの）はP’s CUBEでは起きない形（サイトのリンクが二重に%化され、WebView2もそのまま返す）。
- 実測：pywebview の `evaluate_js` は時間制限なしで返事を待ち、**ページの読み込み中は読み込みが終わるまで待たされる**（遅い応答3秒で最大3秒待ち、Noneが返る）。自動取り込みのタイマーが鍵を持ったまま問い合わせていたため、サイトの返事が遅い・来ないと、タイマーも保存完了の処理も止まりうる。またページ内の取り込みが途中で消えると「取り込み中」の印が外れない経路があった。原因は断定できない（止まった時の表示が無い）が、両方を直した（`9acd73e`）：問い合わせに10秒の時間制限、読み込み中（`before_load`〜`loaded`）は問い合わせない、問い合わせ中は鍵を持たない、取り込みが90秒終わらなければ印を外してやり直す（失敗として数える）、保存完了の通知は待たずに送る。テスト4件追加（P’s CUBE計43件）、PC全テスト・ブラウザ試験成功。`database/bin` を再ビルド（配布用ZIPは作らない）。

## 2026-10-01 深夜：止められた気配で自動停止、沖ドキの除外（P’s CUBE）、ビルド0.5.16（Claude）

- **止められない工夫**（利用者「負荷を最大限下げる工夫やCookieの処理を導入」→途中で「7日に1回は却下、確認画面を見分けて自動停止くらいならいい」）：判定 `autoPageState` が人間確認の画面（hCaptchaの窓・「ロボットでないこと」「約款に同意して」）を `challenge`、対象のページなのに表示がそろわない状態を `missing` として返す。確認画面ではONのまま待ち、`missing` が5回以上・1分以上続いたら止められたとみなして自動でOFF（再開は手動）。PC `AutoPilot`、Android `PscubeAutoGuard`（`df6ec58`）。7日に1回・1時間の上限・一覧だけは入れていない（`PSCUBE_ACCESS_PLAN.md` に決定を記録）。Cookieは前回の修正のまま（Androidはサードパーティ受け付け、PCは `data/pscube-webview` に保存、アプリ内にCookieを消す処理なし）。
- **沖ドキの除外**（利用者「沖ドキという名前が入っているものは取り込まない約束は反映してある？」→していなかった）：メルヘンと同じく「沖ドキ」「オキドキ」（半角の「沖ﾄﾞｷ」も）は対象外。機種一覧の取り込みで回る対象から外し、次の対象にも選ばず、全台一覧・台別ページは「対象外です。保存しませんでした」で保存しない。閲覧ページの機種一覧にも出さない（`e4e5823`）。PC版の本番P’s CUBE記録には一覧に「沖ﾄﾞｷ!GOLD-30」「沖ﾄﾞｷ!BLACK」があったが台の記録は0件で、消したものはない。
- **確認**：PC全テスト（P’s CUBE39件含む）、Flutter全366件、JS・ブラウザ試験成功。
- **ビルド**：APK `0.5.16 / 2026100110`（ソース `749ac4c`）`a/work/outputs/database-0.5.16-2026100110.apk`（92,538,749 bytes、SHA-256 `FFF553D9F96BF8C10CB90A4B0B0830CDA699B5B7F7CF471EA6D42A35B8F97801`）。Windows 3アプリ再ビルド、`smoke_frozen_capture.py` 成功、ZIP `a/work/outputs/database-windows-2026100110.zip`（150,687,987 bytes、SHA-256 `3B337C5484A26264A41236B29D66FC867A5DA57C58045B5CC2DEA4D14CFC8625`、実データなし）。インストールは利用者。閲覧ページ（沖ドキを一覧に出さない）は未公開。

## 2026-10-01 夜：PC版のCookie・メルヘン自動取り込みの停止・当たり0回・バックアップの振り分け・P’s CUBEの間隔、最終ビルド（Claude）

- **PC版P’s CUBEのCookie**（利用者「PC版も修正しておいて」）：pywebviewの初期設定はシークレットモード（起動ごとにCookieを消し、ブラウザはInPrivate）。`run_session` を `private_mode=False, storage_path=data/pscube-webview` に（`eff2f90`）。手元のテストページで、従来は再起動後にCookieが消え、修正後は残ることをWebView2で確認。`data` 配下なのでGit・ZIPに入らない。メルヘンの取り込み窓は変更なし。
- **当たり0回の台**（利用者の質問「0回転の台は取得するがグラフは取り込まない仕様は引き継いでる？」→引き継いでいなかった）：利用者の選択で、BB・RB・AT/ARTがすべて0の台（0回転を含む）は全台一覧の数値は保存し、台別7日分は取りに行かない（PC `no_hits`／Android `noHits`／閲覧 `noHits`）。グラフが無ければ採点の終点・維持は0点（メルヘンv12と同じ、一覧のグラフがあれば実測）。Codexの既存テスト「0回の台も台別を待つ」は利用者の新しい指定に合わせて書き換えた（`45fb723`）。
- **メルヘンPC版の自動取り込みが「ON・ページ切り替え待ち」で止まる**（利用者の報告：4機種目くらい、台番号を押せば動く）：pywebviewの `get_current_url` は日本語を戻した形、ページの `location.href` は%の形で返す（WebView2で実測、機種名の例4つとも食い違い）。比較が常に不一致になり抜けられなかった。`same_page_url`（両方の%を戻して比べる）に変更（`b6081df`）、再現テストは修正前に失敗・修正後に成功、WebView2のダミー試験2本も成功。
- **バックアップの振り分け**（利用者の報告：Androidの書き出しの店舗にメルヘン2店舗しかない、PCで読むと「対象外610件」）：P’s CUBEの書き出しをメルヘンの読み込みに通すと、店が合わず全台が対象外になっていた（記録の変更なし）。Androidのメイン画面の書き出しの店舗に「P’s CUBE（専用の記録・全期間）」を追加、読み込みはファイル先頭が `pscube-viewer` ならP’s CUBEへ。PC版の「バックアップを読み込む」も同じ振り分け（`f90d1f5`）。
- **P’s CUBEの間隔**（利用者の報告：放置したら人間確認なしでデータが表示されなくなった＝止められた可能性。「5分に1回発信元を書き換える」案は、制限のすり抜けになるため作らないと説明）：利用者の選択で間隔をP’s CUBEだけ5〜60秒・初期10秒（PC `AutoCapture` に範囲の引数、Android `AutoCaptureState` に範囲の引数。メルヘンは0.1〜4.5秒のまま）（`90d9cfc`）。「止められたら自動でOFF」「1回の量の上限」「一覧だけ」は今回選ばれていない。
- **確認**：PC全テスト成功（P’s CUBE36件・既存一式）、Flutter全364件、JS・ブラウザ試験成功、解析の指摘は既存のみ。
- **最終ビルド**：APK `0.5.15 / 2026100109`（ソース `c7a6e38`）`a/work/outputs/database-0.5.15-2026100109.apk`（92,538,049 bytes、SHA-256 `15944F0594CACF8A1A4C17FE1B19F84E2BC69DB85036E3FB09BC7529ECB9983C`）。Windows 3アプリ再ビルド、`smoke_frozen_capture.py` 成功、ZIP `a/work/outputs/database-windows-2026100109.zip`（150,679,814 bytes、SHA-256 `6E47E835EFB69FADA3A6B19BE99659E1769B9C25D91EB7FD44DB3832393224FD`、実データなし）。インストールは利用者。
- **閲覧ページ（iPhone）へも反映**（利用者「iPhoneブラウザ版への修正も同じように」）：メルヘンの閲覧ページでP’s CUBEのファイルを選んだとき、汎用のエラーではなくP’s CUBEのページへ案内（`136e3ee`、テスト追加で計57件成功）。`flutter build web` → `stage_viewer.py`（全体＋`--pscube-only`）で公開リポジトリ `d61bde0`、公開 `main.dart.js`・P’s CUBEの各ファイルは手元と一致、seed 404、`assets/assets/pscube_auto_probe.js`（判定スクリプト、実データなし）が新たに公開物に入った。公開ページを本物のApps Scriptで390px表示し、「表示する日付」が切れずに表示されることを画面で確認（メルヘン9,981台・10/1 23:23書き出し）、P’s CUBEのページもドライブから読み込み成功、JavaScriptエラー0件。

## 2026-10-01：実機でP’s CUBEの取り込みを確認、日付の見切れ修正、APK 0.5.13（Claude）

- 0.5.12（2026100106）を利用者が `adb install -r` で入れた。P’s CUBE画面は起動時OFF・3.5秒・「停止中」。自動取り込みONで機種一覧（残り61）→マイジャグラーV全台一覧→台別7日分を自動で保存できた（実サイト、残り92→90）。
- **人間確認**：台別ページ（`nc-v06-001.php`）へ移るたびに hCaptcha「私は人間です」が出る。利用者が毎回操作し、自動取り込みは利用者がOFFにした（不具合ではない）。**手動で1台ずつ開いて取り込んでも毎回出る**（利用者の報告）。機種一覧・全台一覧では出なかった。約款の禁止事項に「本サイト運営のシステムに負担をかけ…」がある。人間確認の自動突破はしない。取り込み方法（例：毎日は全台一覧だけ、台別7日分は必要な台だけ）の検討が必要。
- 日付の欄の見出し「表示する日付」が結果画面の上の帯で切れていた（利用者の指摘）。枠つき入力欄の見出しが枠の上線にまたがるのに上の余白が0だったため。`ViewerDateBar` に上12pxの余白・高さ80→92（`f9ebef2`）。再現テスト `test/viewer_date_bar_test.dart`（修正前は見出しが5.5pxはみ出して失敗）。Flutter全362件成功。閲覧ページ（Web）も同じ部品だが未公開。
- **人間確認が毎回出る件（利用者：Safariでは1時間に1回くらい、Cookieの保存が怪しい）**：サイトへ直接（curl）読むと403で、これ以上サイトを直接調べるのはやめた。アプリ側で2点を普通のブラウザと同じ動きにした（`cbd8d94`）：①AndroidのWebViewは初期設定でサードパーティCookieを拒否（プラグインの説明「Defaults to false」）→ P’s CUBE画面で受け付ける（人間確認のhCaptchaは別サイトの窓）、②保存後の次ページを `loadRequest`（直接開く・参照元なし）ではなくページ内の `location.assign`（リンクと同じ、PC版と同じ）で開く。人間確認の自動突破・ユーザーエージェントの偽装はしない。**利用者が0.5.14を入れて確認：台別ページで人間確認が出なくなり、自動取り込みが順調に進行。日付の見切れも直った（2026-10-01）。**APK `0.5.14 / 2026100108` `a/work/outputs/database-0.5.14-2026100108.apk`（92,472,269 bytes、SHA-256 `3718E3E378A1CE324830E7FE5D748EFC378C6258DDDEDB76C33916745572BAAA`）。
- APK `0.5.13 / 2026100107`（ソース `890aabd`、aaptで確認）`a/work/outputs/database-0.5.13-2026100107.apk`（92,406,733 bytes、SHA-256 `0B2698F9265A534F3D310021D228E2AE99D57DBA70717D3F09A4D54C321B6D64`）。インストールは利用者が行う。

## 2026-10-01：PC版を正本へ一本化（メルヘンの自動取り込みを取り込み）、P’s CUBEの自動取り込み（PC・Android）（Claude）

- **一本化（利用者の選択「正本にまとめる」）**：PC版のメルヘン自動取り込み（ChatGPTが `…\g-p-…\database` で作業し未コミットだった `auto_capture.py`・`browser_import.py` の変更・テスト・`AUTO_CAPTURE_*.md`）を、内容を変えずに正本へ取り込んだ（`183543b`）。その作業の元 `a10a1ac` 以降、正本の `browser_import.py` は変わっておらず衝突なし。PC全155件（自動取り込み26件を含む）成功、WebView2のダミーページ試験2本（`smoke_auto_capture.py`・`smoke_auto_machine_switch.py`）成功。
- **記録の引き継ぎ**：両フォルダの記録は同じ9,071台分で、もう1つのフォルダが数分新しい（06:54と06:49）。正本の `data/database.sqlite3`・`last_save.json`・`settings.json` を `data/backups/pre-merge-20261001/` に退避（旧DBのSHA-256 `15C09593…D535`）してから、もう1つのフォルダの `database.sqlite3`・`last_save.json` を複製（SHA-256一致、整合性チェックok、11,232行・最終 06:54:27）。`settings.json` は正本のまま（違いは最後に開いた店・日付・機種のみ、同期フォルダは同じ）。**今後PC版は正本フォルダ（`work\database-main\database`）の `start.cmd`／`bin` を使う。** もう1つのフォルダのファイルは消していない。
- **P’s CUBEの自動取り込み**（利用者の選択：メルヘンと同じ仕様）：仕様は `database/PSCUBE_AUTO_CAPTURE.md`。ON/OFF・間隔0.1〜4.5秒・起動時OFF・人間確認／同意／読み込み中はONのまま待つ（押さない）・ONの間は手動取り込み不可・同じページは2回保存しない・同じページで3回失敗したら待機・未取得が無くなったら自動でOFF。ページ判定は `data.mjs` の `autoPageState` から `assets/pscube_auto_probe.js` を生成しPC・Androidで共用。PCは `pscube_import.py` の `AutoPilot`（Python側タイマー）と右下カード（`overlay_script`）、Androidは `pscube_import_page.dart`（メルヘンと同じ常駐通知）と `pscube_auto.dart`。
- **確認**：PC `test_pscube_auto.py` 12件＋既存P’s CUBE20件＋全155件、Flutter全361件（新規4件）、解析の指摘8件はすべて今回触っていない既存ファイル。JS 55件、ブラウザ試験4本（新規 `test_pscube_auto_browser.mjs`：ダミーページで判定・カード表示・自動開始→保存→次ページ・二重開始なし・失敗報告・360×300、実サイトへの接続なし）。
- **Androidの最終確認（利用者の依頼：昨日の自動取り込み）**：常駐（`dataSync`、Android 14以降の権限、6時間上限時の停止、タスク終了で停止）とON/OFFのつなぎ込みに問題なし。`POST_NOTIFICATIONS` が無いため、Android 13以降（端末はAndroid 16）では「自動取り込み：ON」の通知が通知欄に出ない（動作は続く）。**利用者の決定（2026-10-01）：通知はいらない、今後も付けない。`POST_NOTIFICATIONS` と通知の許可の問い合わせは追加しないこと。**
- **ビルド**：APK `0.5.12 / 2026100106`（ソース `48ffe75`、aaptで確認、判定スクリプト同梱）`a/work/outputs/database-0.5.12-2026100106.apk`（92,406,733 bytes、SHA-256 `6A3F5457C8C03E95F038633BD20C8C799B8C624EFBADE01811733B2FC65AD26D`）。Windows 3アプリ再ビルド（P’s CUBEに判定スクリプト同梱、本体・P’s CUBEに `auto_capture`）、`smoke_frozen_capture.py` で取り込みEXEの同梱コード一致と一時DB保存を確認。ZIP `a/work/outputs/database-windows-2026100106.zip`（150,677,803 bytes、SHA-256 `2AE619F9DF22818DB80E5AFAC9710A895CE102CFD6CA6B32BBE6097E80DF8944`、実データなし）。
- **もう1つのフォルダ**（`C:\Users\keyan\.codex\.chatgpt-projects\g-p-…`、ChatGPTのプロジェクト「LINE」の写し＋Gitの古いクローン、`a10a1ac`）の未コミット変更は、mainには入れず保管用ブランチ `archive/old-folder-20261001` にコミットしてpush（メルヘン自動取り込みは取り込み済みの同内容、Claudeの88点の途中実装は `aab1823` で置き換え済み、APK本体は入れていない）。**以後、作業・起動・ビルドは正本フォルダだけで行い、このフォルダは使わない。**
- **未実施・未確認**：端末へのインストール（利用者が自分で `adb install -r` を実行する）、実サイトでのP’s CUBE自動取り込み（人間確認が出るため利用者と一緒に確認が必要）。作業中に確認用コマンドへ誤って `git stash` が入り、未コミットの8ファイルを一時退避したが、直後に `git stash pop` で復元し中身とテストを確認済み（Codexの古い退避 `stash@{0}` は未変更）。

## 2026-10-01：P’s CUBEのバックアップ・Drive同期（PC・Android・iPhoneブラウザ）と、メルヘンの取り込みボタン（Claude）

- 利用者の指示：「取り消しは付けない。PC版の自動バックアップ（名前は分ける）はそのまま、ドライブ同期をする。Android・iPhoneブラウザ版もほとんど同じ仕様」。続けて「PC本体の『ブラウザを開いて取り込む』を『メルヘンワールドを取り込む』に。メルヘンのボタンは指定のCSS（.btn-grad：#16A085→#F4D03F→#16A085、幅200%、ホバーで右端へ0.5秒、角丸10、白文字）に」。仕様は `database/PSCUBE_SYNC.md`（共有用）。
- **PC**（`pscube_import.py`）：P’s CUBEを1回保存するたびに `auto_backup`。ローカル `data/pscube-viewer.json`（全期間・種別backup・取り込み済みの印つき）、日付控え `backups/pscube-backup-YYYY-MM-DD.json`（7日分、同期フォルダが無ければ `data/backups/`）、同期フォルダ（メルヘンの `sync_dir` を共用）へ `pscube-backup-auto.json` と閲覧用の軽い `pscube-viewer-drive.json`（直近31日・グラフ最大16点。最初・最後・最高・最低点は必ず残すので採点は不変）。失敗しても取り込みは止めず、結果をボタンに表示。本体「バックアップ・同期」に「P’s CUBEの同期フォルダの最新を読み込む」を追加（`pscube-*` を更新日時順、閲覧用の軽いファイルは拒否）。統合は取り込みと同じ `_merge`（古い数値で新しい数値を上書きしない、数値が変わった台は台別取得済みを外す、自分の機種タイプ優先、消す操作なし）。メルヘン側の変更は `core.latest_backup_file` が `pscube-` で始まるファイルを読まないようにした1か所だけ。
- **Android**（`pscube_store.dart`・`pscube_import_page.dart`）：自動同期はできない（メルヘンと同じ）。右上に「バックアップを読み込む」（PC・ブラウザのバックアップを統合、不正なら何も保存しない）と「書き出す（共有）」（名前 `pscube-backup-android-YYYYMMDD-HHMMSS.json`、前の自分の書き出しは消す、共有を取りやめたら書き出し済みにしない）。最後に書き出した日時（1日以上前なら注意）を表示。取り込みのたびの書き出しはやめた。
- **iPhoneブラウザ**（`web/pscube/sync.mjs`・`app.mjs`）：開くとDriveの最新を読む。メルヘンの閲覧ページと同じApps ScriptのURL（同じブラウザの `database-viewer-remote`）に `?file=pscube`。書き出し時刻が前回と同じなら何もしない。違うファイル・エラー・時間切れは前の内容を残す。CSPの接続先に `script.google.com` と `script.googleusercontent.com` を追加。書き出しは `pscube-backup-browser-…json`（種別backup、台別グラフのある日を取り込み済みとして出す）。`tool/stage_viewer.py` の公開ファイルに `sync.mjs` を追加。
- **Apps Script**（`tool/viewer_drive_script.gs`）：`?file=pscube` のときだけ `pscube-viewer-drive.json` を返す許可リスト方式に更新（未知の値はエラー）。**利用者が「デプロイを管理→編集→新バージョン」で更新するまで、閲覧ページは「Apps Scriptを更新してください」と出して何も変えない。**
- **ボタン**：PCはTkで `GradientButton`（PhotoImageで200%幅のグラデーション、Enter／Spaceでも押せる、影は淡い背景で見えないため省略）。Androidは `lib/gradient_button.dart`（押している間に右端へ流れる。影あり）で「アプリ内ブラウザを開く」を「メルヘンワールドを取り込む」に。白文字は黄色の部分で読みにくい（指定どおり）。P’s CUBEのボタンは従来のまま。
- **確認**：PC新規13件（自動バックアップ・名前の分離・7日の控え・軽いファイルが採点に必要な点を残す・失敗時・往復・不正ファイル拒否・古い数値で上書きしない・印・最新ファイル選択・メルヘンの探索がpscubeを読まない）＋既存P’s CUBE7件・既存125件成功。Flutter全354件（新規6件）＋ボタン3件成功、変更ファイルの解析は既存のinfo1件のみ。ブラウザ：同期6件・Drive画面試験（Apps Scriptは模擬）・既存ブラウザ試験・採点12件・data9件成功。言語をまたぐ確認：PCのバックアップをAndroidが80件読み込み・軽いファイルは拒否、検証用の実DB（39件）のコピーでPCが書いたファイルをブラウザの `validateData` で検証し1227番台の点数が全体／軽いファイルとも27.4で一致。Apps Scriptは模擬環境で許可リストを確認。
- **配布物**：APK `0.5.11 / 2026100105`（ソース `82e0d7e`、aaptで確認）`a/work/outputs/database-0.5.11-2026100105.apk`（92,384,082 bytes、SHA-256 `4BC704FB6AA1DE3175E29079DEECA825BF38E55E05AC3DCB1BDBA2015406CE59`）。2026100104は同日の途中ビルドで配布・インストールしていない（成果物は削除）。Windows 3アプリを再ビルドし、検証用の別フォルダ（同期フォルダ付き）で本体を起動、新しいボタン表示と「P’s CUBEの同期フォルダの最新を読み込む」で80件取り込み・同期フォルダへの3ファイル書き出しを確認（クリックはWin32操作）。ZIP `a/work/outputs/database-windows-2026100105.zip`（150,637,796 bytes、SHA-256 `469D7DD5DF60A948E6D2440A0D85ECB367D3AAA964241C85AF60B64A775F65DA`、3フォルダ、実データ・reportsなし）。`build_windows.ps1` はWindows PowerShell 5.1で標準エラーを理由に止まっていたので、終了コードで判定するよう修正。
- **実Driveの確認（利用者の「ドライブ連携大事だから確認してね」）**：本番の同期フォルダ `G:\マイドライブ\database共有` へ、10/1の検証用実データ（61機種・39件）のコピーから `auto_backup` で3ファイル（`pscube-backup-auto.json`・`pscube-viewer-drive.json`・`backups/pscube-backup-2026-10-01.json`）を書いた。本番のP’s CUBE記録は作っていない、メルヘンのファイルは更新時刻も不変。Google ドライブ for desktop の同期情報（読み取り専用のコピー）で3ファイルにクラウドのIDが付き送信待ち0件＝アップロード済みを確認。同名の有効なファイルは各1つ（Apps Scriptの `getFilesByName` が迷わない）。ドライブ上の `pscube-viewer-drive.json` をそのまま閲覧ページの読み込み処理（`fetchDrive`）に通し、61機種・39件・1227番台27.4点、同じ書き出し時刻なら「変わっていません」を確認。Claudeのドライブ接続は別アカウントで、メルヘンのファイルも見えなかったためクラウド側の直接参照はしていない。
- **Apps Script更新後の確認**：利用者が新しいコードを貼って公開し、URLを共有（URLは記録しない）。`?file=pscube` は `pscube-viewer-drive.json`（21:00:41書き出し・61機種・39件）、指定なしは従来どおりメルヘンの `database-viewer.json`（9,576,175 bytes・9,675件）、未知の値はエラーを返し、いずれも `Access-Control-Allow-Origin: *`。公開ページと同じ `https://keyanbaitian6-cell.github.io/database-viewer/pscube/` に手元の新しいファイルを差し込んだChromium（CSPあり）で、本物のApps Scriptから2.3秒で読み込み、61機種・39件を表示、開き直すと「変わっていません」、JavaScriptエラー0件。手元の `http://127.0.0.1` から呼ぶとApps Scriptが404を返した（原因はわからない。公開ページの場所では問題なし）。
- **公開（利用者の「公開してOK」）と、見つかった不具合の修正**：`stage_viewer.py --pscube-only` で公開リポジトリ `47378db`（Pages成功）。公開した実ページで本物のApps Scriptを読むと、初回は成功したが開き直しで404。切り分けの結果、Apps Scriptの中継先（`script.googleusercontent.com/macros/echo`）がときどき404を返し、メルヘンの読み込みでも同じ（12回中2回、間隔に関係なし、クッキーなし）。P’s CUBEの `fetchDrive` に、404・429・5xx・通信失敗を1.5秒・3秒待って2回までやり直す処理を追加（テスト：成功までやり直す・3回失敗で報告・403はやり直さない・時間切れ）。差し込み確認で本物のApps Scriptを10回連続で開き直し、すべて成功。修正を公開リポジトリ `3e7cf0e` で再公開（Pages成功、公開 `sync.mjs` は正本と一致）。公開した実ページ（差し込みなし）で本物のApps Scriptを6回開き直し、初回読み込み・以後「変わっていません」ですべて成功。メルヘンの閲覧ページ（Flutter版 `web/index.html` の `fromRemote`）にも、利用者の「そのまま公開していいよ」を受けて同じやり直し（404・429・5xx・通信失敗を1.5秒・3秒で2回まで、403などはやり直さない）を入れた（`91138a5`、テスト追加で25件成功）。`flutter build web`（base-href `/database-viewer/`）→ `stage_viewer.py` で公開リポジトリ `09f1db7`。公開 `index.html` は手元と一致、`main.dart.js` は前回公開と同じSHA-256 `bc5ea073…`（本体の変更なし）、実seedは404。新たに `assets/assets/pscube_capture.js`（取り込み用の読み取りスクリプト、`pubspec.yaml` の資産。実データなし）も公開物に入った。公開ページで本物のApps Scriptから8回読み、すべて9,675件、同じ書き出し時刻ならnull（読み直し省略）。この回は404が起きず、実環境でのやり直し自体はテストでのみ確認。その後、利用者のiPhone（メルヘンの閲覧ページ、URL設定直後）で「30秒間応答がなかったため、読み込みをやめました」。21:37には読み込めていた。PCからの実測ではスクリプト実行2.5〜5秒・中継先の最初の応答1秒未満で、30秒に届く遅さは再現しない。原因は確定できない（わからない）が、iPhoneでほかのアプリへ切り替えると裏のページの通信が止まり、戻った瞬間に30秒が過ぎたと判断されうるため、両方の閲覧ページで**ページが隠れている間は待ち時間を数えない**ようにした（`49b3606`、テスト各1件追加）。公開リポジトリ `8207c8b`、公開ファイルは手元と一致、`main.dart.js` 変更なし、seed 404。修正後、利用者がiPhoneで開き直して再読み込みし「OKでした」と報告（2026-10-01）。
- **未実施・未確認**：端末への `adb install -r`（利用者の許可待ち）、iPhone実機での読み込み、Drive上の容量（31日・台数次第で数十MBの見込み、Apps Scriptの上限はわからない）。

## 2026-10-01：P’s CUBEに採点と翌日候補を追加（閲覧ページ、試験表示。Claude）

- 利用者の指示：メルヘンワールドと同じ運用（記録→採点→翌日候補）をP’s CUBEに適用。選択：「採点＋翌日候補」から着手、採点は「出玉やグラフなどのきれいさ」を考慮。設計・採用値・限界は `database/PSCUBE_SCORING.md`（共有用）。
- 実装：`database_android/web/pscube/scoring.mjs`（採点 `pscube-2026-10-01-v1`・翌日候補）、`app.mjs` に台ごとの点数と内訳、機種ごとの★/☆候補、機種一覧の候補数。`tool/stage_viewer.py` の公開ファイルに `scoring.mjs` を追加（`--pscube-only` の確認済み）。
- 配点：ノーマル（機種タイプ設定、未設定なら機種名のジャグラー・ハナハナ）はメルヘンv12と同じ60/20/10/10。それ以外はMY50・終点25・維持25（当たり頻度は使わない）。比較相手は同店・同貸玉・同機種。MYの枚数引き上げ（19,000）は貸玉20のみ。0回の台のグラフ省略（v12）はしない。★の条件（当日の情報あり・z≥1.96・当日88点未満）と並び（丸め前の指数→使用日数→最新日→台番号）はメルヘンと同じ。
- 確認：`tool/test_pscube_scoring.mjs` 12件（手計算との一致、500G以下・異常値・同日・未来・他機種・30日超の除外、グラフ向き、★条件、同点の並び）、既存のdata 9件・ブラウザ試験が成功。合成の6台×5日で画面（390px）に★2台・点数・内訳が出ること、実データ（マイジャグラーV 33台）で崩れず「候補なし（判断できた台0台）」と理由が出ることを確認。Flutter・PCのコードは変更なし。
- **未検証・未実施**：採点と候補が翌日の結果を当てるかは未検証（実データは1日分＋台別7日分のみ）。答え合わせ・候補の保存、PC／Androidの取り込み画面への表示は未実装。閲覧ページの公開は利用者の許可待ち（`tool/stage_viewer.py --pscube-only` を使う）。

## P’s CUBE保存・ビルド・実サイト確認の途中引継ぎ（2026-10-01）

- `03ffff034613abdd52ca76820ee2ebd420b08b8b` の最新mainから着手。利用者の使用量上限で中断しており、今回の修正はまだ未コミット・未push。
- PC／Androidの保存・共有・終了を直列化し、数値更新時は台別取得済みマーカーを無効化。台番号・日付・グラフ・URLの検証、Androidのページ遷移／終了競合、PCの完了通知と遅延読み込みを修正。実際の機種リンクにcd_psが無い場合を許容し、回帰テストを追加。
- テスト：PC既存125件＋P’s CUBE7件、Flutter全348件成功。最後のcd_ps省略対応後はP’s CUBE6件とDart対象3ファイル解析を再実行し成功。ブラウザdata9件、既存P’s CUBEブラウザ確認、新規DOM入れ替えスクロールテストも成功。Safari実アーカイブを必要とするテストは未実行。
- 最終Android APKは `0.5.10+2026100103`、releaseビルド・`adb install -r` 成功。端末 `RFGL146LVVW` / SM_A253C。アンインストール・データ消去は行っていない。
- 実サイト：人間認証は利用者が手動実施。最終PC exeで機種一覧61件、マイジャグラーV33台、1227番台7日分を保存し、次1228へ移動。検証用DBは61機種・39記録・取得済み台1。専用JSONは閲覧側validateDataで検証成功。Android最終版も機種一覧・33台・1227番台7日分を保存し「残り92件」、共有シートにpscube-viewer.json 1件の表示を確認。外部送信はしていない。全機種／全台巡回の完了ではない。
- メルヘンのPC本番DBのSHA-256は `15C09593959DBC7F4209379F6705EFF240F8892A563AB61FB03CEF2DBE07D535` のまま。Android上書き後は9/30の108機種・355台の表示を確認。
- Git外の成果物は親workの `outputs/database-0.5.10-2026100103.apk` と `outputs/database-windows-2026100103.zip`。APK SHA-256 `046BDC0E4A2ADECE690BE8B992445FD4DA3E8BAF5000FEFB1036C01EE6C4E7A3`、ZIP SHA-256 `FB4AE209E8E5CBC1D08E18EA5DB74497598CA77B86A8DC073F6F639CF8F08FDB`。ZIPは3つのonedirフォルダを同梱し、実data／reportsは含めていない。
- 引継ぎ後の確認（Claude、2026-10-01 20時台）：検証用PC本体（`reports/pscube-validation/launcher-smoke/database/database.exe`）で「P's CUBE（スロット）を取り込む」を押し、同じ検証用フォルダの `database-pscube.exe` が検証用の `data/pscube.sqlite3` `data/pscube-viewer.json` を引数に起動し、ウィンドウ「P’s CUBE 取り込み」が応答することを確認（実サイトは操作せず、人間認証は不要）。ZIP（SHA-256 `FB4AE209…8FDB` 一致、data／reportsなし）を `C:\Users\keyan\z1` へ展開し、本体・ブラウザ・P’s CUBEの3つが起動して応答することを確認（本体は展開先に空の `data/database.sqlite3` を作っただけ）。注意：深いフォルダ（約150文字のパス）へ展開するとnumpy内のパスが260文字を超えて展開に失敗した。短いフォルダへ展開する旨を `PSCUBE_IMPORT.md` に追記。再実行：PC既存125件・P’s CUBE7件、Flutter P’s CUBE6件・対象3ファイル解析が成功。メルヘンPC本番DBのSHA-256は `15C09593…D535`・64,032,768 bytes のまま、Android端末は 0.5.10 / 2026100103 のままメルヘン画面。コード変更なし（APK・exeの再ビルドなし）。
- 残作業：最終レビュー、commit／mainへのpush。Android共有JSONの実内容照合・実閲覧UI表示・過去日hash選択は未確認。必要な範囲を判断して検証する。
- 現在、Androidは共有シートを開いたまま（背後は次台移動後の再認証）。PCは元のP’s CUBE exeが1228、別途 `reports/pscube-validation/launcher-smoke/database/database.exe` の空データ検証用本体が起動中。詳細引継ぎは親workの `CLAUDE_HANDOFF_PSCUBE_20261001.md`。ログ・画面・専用検証DBは `database/reports/pscube-validation/` にありGitへ追加しない。

## 正本とデザインのルール（2026-09-25、利用者の指示）

- **Windowsの配布用ZIP（`a/work/outputs/database-windows-*.zip`）は、利用者に頼まれたときだけ作る**（2026-10-01 利用者の指示「お願いした時だけでいい。全部消して」。それまでの5つは削除済み）。APKの複製は引き続き作る。

- **正本は GitHub `imakurudev-eng/database` の `main` だけ**。2026-09-25に新デザイン（旧ブランチ `codex/adopt-claude-ui`）と採点v10をマージした `5e6009c` 以降がそれ。
- **Androidのデザインは新デザインの1つだけ**。9/23以前の旧デザインのコード・ブランチ・APKは使わない、復元しない、そこからビルドしない。デザインを2系統持たない。
- 作業を始める前に必ず `git fetch origin` と `git pull origin main` をして、最新の `main` から始める。別のフォルダやクローン（例：`Documents/Codex/2026-09-24/a/work/database-claude-review`）の古い状態から作業しない。
- APKは、最新の `main` を取り込んだ状態からだけビルドする。ビルドの前に `git status` と `git log origin/main..HEAD` / `git log HEAD..origin/main` で差分がないか確かめる。
- **APKをビルドするたびに `database_android/pubspec.yaml` の `version:` の `+` の後ろ（versionCode）を上げる**。形式は `年月日+2桁`（例 `2026092601`、同じ日の2回目は `2026092602`）。下げない。古いAPKを上書きで入れられないようにするため（入れようとするとAndroidが拒否する）。万一古い版がDBを開いても、DB版が新しければ起動画面で止まる。
- **`adb uninstall`・`pm clear`・アプリのデータ消去は、利用者がバックアップを書き出して中身を確かめるまで絶対にしない**。アンインストールすると端末内の記録・ゴミ箱・翌日候補の記録がすべて消える。`INSTALL_FAILED_VERSION_DOWNGRADE` が出たら、アンインストールではなく versionCode を上げてビルドし直す。
- **閲覧ページ（database-viewer）を公開・更新するときは、必ず `tool/stage_viewer.py` を通す**。`build/web` には実際の記録（`assets/database_seed.json`）が同梱されるため、そのまま公開しない。
- 作業が終わったらコミットして `main` へpushし、次のAIが同じ状態から始められるようにする。採点は `2026-09-29-v12`（当日500G以下と、サイトの数値が異常な台は採点しない。大当たり0回でグラフの無い台は終点・維持0点）が現行。

## 2026-10-01：P’s CUBEブラウザ版を公開

- 利用者の指示により、正本main `a3a5784` から `python database_android/tool/stage_viewer.py --pscube-only <公開リポジトリ>` を実行し、`pscube/` の5静的ファイルだけを追加。既存Flutter閲覧版は変更なし。実seedは正本クローンに存在せず、スクリプトの記録文字列照合は0種だった。実資料・抽出済み記録は追加していない。
- 公開コミット：`keyanbaitian6-cell/database-viewer` の `4075e54f038bf95b29192915c10f771acff80f9e`。CLIの認証はimakurudev-engで公開先へのpushが403だったため、公開先所有者の接続済みGitHubコネクターで同一treeを作り、forceなしでmainを更新。
- 公開URL：https://keyanbaitian6-cell.github.io/database-viewer/pscube/ 。[Pages run 36837404189](https://github.com/keyanbaitian6-cell/database-viewer/actions/runs/36837404189) 成功。公開5ファイルはHTTP 200・手元のSHA-256と全て一致、既存トップ200、`assets/assets/database_seed.json` は404。
- 確認：データテスト9件成功、既存Chromiumブラウザテスト成功（アーカイブ読込・保存復元・JSON往復・失敗時保護・320/390/768px）。公開URLも390pxのChromiumで表示し、タイトル・ファイル選択欄・初期状態とJavaScriptエラー0件を確認。iPhone実機Safariは未確認。

## 2026-09-30：通常候補を★注目と☆長期傾向に分離（CodexによるClaude作業の継続）

- 正本mainをpullして `a10a1ac` から開始。Claudeクラウドの途中の本番パッチはこのクローンにもorigin/mainにも無かったため、固定済みの `NEXT_DAY_FOCUS_PLAN_20260930.md` に従って本番実装を行った。新デザイン・パンダアイコン・採点v12・Driveの電池対策は維持。
- 通常機種の候補集合は機種内の上位4分の1。小数9桁の生指数、使用日数、最新使用日、台番号の順へ変更（PC/Dart一致）。方式版は `2026-09-30`。指数の表示・計算式そのものは変更なし。
- ★注目は候補集合のうち、当日情報を使用・固定された記述的な安定性z>=1.96・当日点数88未満の台だけ。88以上を含む残りは☆長期傾向。未採点を0にせず、88除外だけでは飛ばさない。バラエティの選び方は変えない。zは独立・同順位なしを仮定した目安で、検定の有意性・高設定の確率・予測精度ではない。
- カード・Android結果/機種ページ・Web機種ページの表/グラフで同じ印。候補ごとの当日使用有無/除外理由/上中下の日数/翌日最下位シナリオを表示。台詳細の折りたたみで日別寄与・押し上げた日・10日枠から抜ける日・直近3暦日の点数を確認できる。最下位シナリオは直近使用日の回転数/比較台数と他台固定を仮定し、10記録日と30暦日期限を繰り越す。★継続の予測ではないと明記。
- 答え合わせは現在の方式で再計算した★/☆/バラエティ合計であると説明を追加。分析用backtestは保存済み候補の方式版を絞り、新旧を混ぜない。過去の文書の数値は旧方式の結果で、新しいランキングで再計算した値と混同しない。
- 未来検証の主方式「半減期3日の直近重視＋当日88以上を飛ばして補充」は `lib/focus_validation.dart` の分析専用選択として実装（本番UIから呼ばない）。固定期間9/30〜10/29、最終評価10/31以降・20評価日・店舗別方向・日/移動ブロック区間・評価可能率等の採用条件は従来文書のまま。今日、採用効果を判定したり自動採用したりしない。
- 実データの読み取り専用一致確認：全期間バックアップSHA-256 `A64FBD8EFCAED572564D54DA5BD44FC4BFEA7E4CE838E9AEE8E5369EFF4EA9C2`。PC/Dart候補1,284件、指数/使用日数/注目判定の不一致0。通常1,198件、★注目110件、88以上14件は全て☆、バラエティ86件。これは実装確認であり予測精度の評価ではない。非公開照合出力は `a/outputs/focus-parity-20260930.json`、Gitには入れない。
- 確認：Flutter全338件・PC全125件・Web JSON/Drive読み込み24件成功。新しい計算/表示/分析専用選択/照合ツールへの静的解析は指摘なし。lib全体には従来の2warning/3infoが残る（今回の対象外）。
- ビルド：ソース `aab1823` とorigin/main一致・cleanからAndroid release APK成功（118.1秒、91,592,230 bytes）。aaptで `com.keyan.database_android` / 0.5.9 / 2026093004 を確認。Git外成果物 `a/outputs/database-0.5.9-2026093004.apk`、SHA-256 `14B3A419C1057F1FE339A28EC20985088D63C93584C4FD94AB4039533F3A5BAC`。端末データの消去・インストールは依頼されていないため行わない。
- 公開：同じソースからWeb release build成功（38.1秒）、`tool/stage_viewer.py` で実seed除外・記録由来90文字列の該当なし。公開リポジトリ `e4a0954` の [Pages run 36723086012](https://github.com/keyanbaitian6-cell/database-viewer/actions/runs/36723086012) 成功。公開トップ200・実seed404、JavaScript SHA-256 `BC5EA07348524E2D661CD032ED0F76AD3CBFA9E8D3B3FB164A1B5EC7881B06CE` と手元一致。HTML（改行正規化）・iPhone用180pxアイコンも一致、公開version.jsonは0.5.9/2026093004。公開差分はmain.dart.jsとversion.jsonの2ファイルのみ。iPhone/Android実機での操作確認は未実施、widgetテストと配信検証まで。

## 2026-09-30：強く出た台（当日80点以上）を翌日も推すのは適切か（調査のみ）

- 利用者の依頼：「十分に回され、右肩上がりで強く出た台を翌日もおすすめするのは適切か」。仮説は「強く出た台が翌日も良いとは限らず、同じ機種の別の台へ好成績が移る」（店の運用の仮説。80点以上＝設定6とは扱わない）。本番変更・ビルド・公開はしない。前回依頼の案1〜3の実装は、利用者の「まず報告」に従い、この報告のあとに行う。
- 分析の条件は結果の前にコミット（`21e3e84`）。データは前回と同じPCバックアップ（`a64fbd8e…`）、予測時点の見え方、翌日の点数は全記録で採点、未取得・未採点は0にしない。80点の基準は利用者の指定で固定。
- 結果：当日80点以上は190台分（採点できた台の5.0%）、全部グラフあり・終点プラス・終点÷最高点の中央値0.95。翌日の平均49.1点、80点以上を保つのは11%だが、同じ機種の他の台より翌日も +3.8［+0.1, +7.3］。当日の点数が高いほど翌日も少し高い並び（平均への戻りが大きく、運用の証拠ではない）。80点以上の台がある機種では他の台も翌日80点以上になりやすい（+4.3ポイント）が、平均点は同じで、強かった台が翌日も機種内1位になる割合は偶然と同じ。80点以上の★（77台）の翌日は他の★より +2.1（区間0を含む）。80点以上を外して補充する方式は現行より −0.42［−0.84, −0.04］。規約の「試す価値」の判定では候補に当たったが（入れ替わった台どうしの日平均が負）、グループ単位では22対24の五分で、主に試す方式にはしない。
- 追加：`database_android/lib/strong_rack_review.dart`（分析専用）、`tool/strong_rack_review.dart`、`test/strong_rack_review_test.dart`（合成5件）。出力はGit外 `a/outputs/strong-rack-review-20260930/`。詳細は `NEXT_DAY_STRONG_RACK_REVIEW_20260930.md`。

## 2026-09-30：通常★（参考候補）の選定方法の独立した再検討（調査・改善案のみ）

- 利用者の依頼：通常機種の★がほぼ毎日同じ台になる理由を、不具合・設計上の性質・データ不足に分けて調べ、改善案を少数に絞る。本番の採点・選定式・方式版、APK、公開、記録・設定・保存済み予測は変えない。正本 `089cbdc` から開始（未コミットの変更なし）。
- 分析の条件は結果を計算する前にコミットした（`762477f`）。データは前回の比較と同じPC版の全期間バックアップ（SHA-256 `a64fbd8e…`、8,787件、9/8〜29）。未来検証に固定した予測日9/30以降は使っていない。回顧的な診断で、直近重視・50超・低採点・低稼働の比較は繰り返していない。
- 結果：不具合なし（保存済みの候補850グループと再計算の★が全件一致、キャッシュ・表示の対象日もコードで確認）。同じ台が続くのは主に10記録日の重なり（連日同台率80.6%に対し、台番号を入れ替えた200回で76.9%［74.0, 79.1］）。1日の結果の効きは中央値1.45点、翌日が最下位でも残る★が20.7%。当日の情報が入っていない★が16.0%（500G未満・0G・比較相手3台未満）。境界の同点16グループ（7台は丸め前なら逆）。お店：入れ替わりの向きは両店とも無し、長町南は弱い据え置き寄り（区間0を含む）、機種単位は0付近。8予測日で見分けられる差は約±1.8点（±1点は約29予測日）。前回の77.13%を同じ定義で再現。
- 改善案（未実施）：①★ごとに理由・今日の情報の有無・外れる条件を出す（本番式は不変、最優先）、②丸めと台番号順をやめる（承認・方式版の更新が必要）、③「長期傾向」と「翌日向けに注目」を分け、根拠が弱いときは候補なし（前向き検証。予測日9/30〜10/29の主な1方式を結果の前に決める必要）、④イベント名の登録時刻を記録。
- 追加：`database_android/lib/star_review.dart`（分析専用、画面から呼ばない。★・指数はアプリの関数と毎回一致を確認）、`tool/star_review.dart`、`test/star_review_test.dart`（合成データ9件）。出力はGit外 `a/outputs/star-review-20260930/`。詳細は `NEXT_DAY_STAR_INDEPENDENT_REVIEW_20260930.md`。

## 2026-09-30：提供画像を参考にAndroid・ブラウザのアイコン変更

- 利用者指定：パンダ帽子の女の子とパンダの画像を参考にアプリアイコンを変更。対象はAndroid・ブラウザの両方。AndroidはソースだけでAPK不要。正本をfetch/pullして開始。Claudeの別途候補レビューは維持し、採点・選定・データ・画面デザインには触れない。
- 組み込み画像生成で青い星空と中央の2つの顔を主役にした正方形を作成。原画を `database_android/design/app_icon/panda_master.png` に保存し、READMEに実際の生成指示を記録。`tool/generate_app_icons.dart` でAndroid5密度とWeb6サイズへ縮小。既存Android launcher参照を維持。iPhoneのホーム画面用180pxを追加し、Webのアイコン・manifest参照は版付きURLに変更。
- 確認：原画と11アイコンの再生成一致確認成功。Android全密度・PWA manifest・iPhone/fav参照の3テスト成功、追加2 Dartファイルの解析は指摘なし。512pxと48pxの画像を目視確認。APKビルド・インストールは行わない。既存ホーム画面アイコンの実機更新は未確認。
- 公開：ソース `2709257` とorigin/main一致・clean状態からWeb release build成功。`tool/stage_viewer.py` で実seed除外、記録由来90文字列に該当なし。公開リポジトリ `9340ee6` の [Pages run 36711853616](https://github.com/keyanbaitian6-cell/database-viewer/actions/runs/36711853616) 成功。公開6アイコンのSHA-256、HTML・manifest（改行をそろえる）は手元と一致、seed404。本体main.dart.jsは前回電池対策公開と同じSHA-256 `b744c8c27e449ee19620153a230d873af945872ad5b32ce988557640f911177c`（本体の変更なし）。公開差分はアイコン6ファイルとHTML・manifestの8ファイルだけ。

## 2026-09-30：閲覧ページの電池対策（Driveの読み直し・起動時の組み立て）と、ChatGPTの参考候補の点検

- 利用者の依頼：iPhoneでWebアプリとして使うようになってから電池の減りが早い（利用者の確認では、電池の使用量はSafariにまとめて出ていて、一番多い）。検討のあと「①を直して公開、②は2分も待たなくていい、③はグラフの精度が変わらないなら直して公開してよい」。途中で「チャッピー側の作業終了してるから検閲も一緒に」。正本 `59a078b` から始め、`9ccad20`（ChatGPTの参考候補・比較分析）を取り込んだ。
- 調査（PCのChrome・実データ8,787台）：操作していない間の描画要求は5秒で0回（常時アニメーションなし）。重いのは開くたびの処理で、Driveの自動読み込みが毎回 `no-store` で8.7MBを丸ごと読み、中身が同じでも読み込み時刻（`loaded_at`）が変わるため、端末への保存し直し・合成・組み立て直し・採点のやり直しを毎回していた。読み込み中は動く進行バーで、打ち切りもなかった。起動のたびにFlutterの古いService Workerの登録→即解除も入っていた（`flutter_bootstrap.js` の既定）。データの54%はグラフの線（8,207台・295,096点）。
- ①：`web/index.html` の `fromRemote(url, known)` が、ファイル先頭行の `exported_at` が表示中の内容（`ViewerData.exportedAtText`、ファイルのままの文字）と同じなら、そこで読むのをやめて null を返す（通信も止める）。全文形式の古いファイルも同じ時刻なら null。`_refreshFromDrive` は null なら合成・保存・組み立て・採点をしない。右上の更新ボタンなど手で押したときだけ「Googleドライブの内容は変わっていません（…書き出し）。」を出す。確認した時刻を出典の欄に「・HH:MMに最新か確認」と出す。
- ②：Driveの確認中は動く進行バーをやめ、動かない文字「Googleドライブの最新を確認しています…」にした。30秒間なにも届かなければ打ち切る（届いている間は待つ。届くたびに数え直す）。`web/flutter_bootstrap.js` を置き、Service Workerを登録しない（Flutterの説明どおりの最小形）。
- ③：`GraphMeasurement.fromJson` の線を `SavedCurve`（初めて使うときに1回だけ数値の一覧へ直す）にした。直し方は以前と同じ式で、形の検査は読み込み時に行い、壊れた線は今までどおりそこで失敗する（閲覧ページではその台を飛ばす）。Android版の読み書き・`lightened()`・`toJson()` の結果は変わらない。
- 精度の確認：実データの全8,535グラフ（線あり8,207台・295,096点）で、新旧の線の数値の不一致0、描く大きさ（`curveCanvasSize`）の不一致0。閲覧ページと同じ読み込み（同じ台をそろえる処理を含む）でも不一致0（一時テスト、コミットしない）。画面でも台の詳細のグラフと5日間のグラフが保存した線から描かれることを確認。
- 効果（PCのChrome、同じ条件で交互に3回ずつ）：`?load=` で開いたときに画面が固まる時間は変更前1.16/1.05/1.12秒→変更後0.71/0.76/0.74秒。Driveの読み込みを手元のファイルに差し替えた確認用ページ（ローカルのみ、削除済み）では、変更前は毎回8.7MBを読み2.20/2.27秒、変更後は中身が同じなら約2MB（手元のサーバーは一瞬で送るため、ブラウザの先読み分）または64KBで打ち切り、0.52秒。初回（保存データなし）は8.7MBを読み0.82秒。iPhone実機・実際のDriveでは未測定。
- テスト：追加は `test/viewer_battery_test.dart` 5件と、`tool/test_viewer_backup_parser.mjs` のDrive 6件（同じ時刻で先頭行だけ・違う/不明な時刻は全部・全文形式・30秒で打ち切り・届くたびに数え直し・URL検査）。変更前の読み込み部分では新しい動きの4件が失敗することを確認。全Dartテスト308件・JS24件成功、解析は既存の8件のみ（変更ファイルへの指摘なし）。
- ChatGPTの作業（`fa83bae`〜`9ccad20`）の点検：画面の変更（答え合わせ・新規予測・台の詳細・機種ページ・候補カード）は呼び方と説明文だけで、候補の選び方・採点・保存は変わっていない。比較分析2モジュール（`reference_candidate_comparison.dart`・`low_activity_candidate_comparison.dart`）は画面に接続されておらず、翌日0:00より前の取得だけを使い、対象の台が本番と一致しなければ止まる検査、欠測を0にしない扱い、日単位のブートストラップになっていて、不具合は見つからなかった。気づいた点は1つ：候補カードの見出し「9/30（水） の参考候補（翌日向け）」が375px幅で「（翌日向」「け）」に分かれて折り返す（読みやすさのみ。直していない）。
- 公開：ソース `97c81d5`（clean、origin/mainと一致）から `--base-href /database-viewer/` でWeb release build（Git Bashでは `MSYS_NO_PATHCONV=1` を付けないと base-href がWindowsのパスに変わる）。`tool/stage_viewer.py` で実seedを除外し、記録由来90種類の文字列に該当なし。公開リポジトリ `9757566` へpush、Pages run `36708525185` 成功。公開ページ200・seed404、公開 `main.dart.js` のSHA-256 `b744c8c27e449ee19620153a230d873af945872ad5b32ce988557640f911177c` はビルドと一致、公開 `flutter_bootstrap.js` はService Workerを登録しない形。iPhone実機では未確認。

## 2026-09-30：★を参考候補として説明、直近重視・低採点・低稼働を比較

- 利用者の依頼：通常★の同じ台が続く点を検討し、表示整理と比較を行ってブラウザ公開まで。APK不要。追加指定は直近3日・低い採点結果・低G、バラエティも対象。正本 `59a078b` をfetch/pullして開始。新デザイン・採点v12・選定式・方式版・保存記録・PC取り込みは維持。
- 表・グラフ・台詳細・答え合わせの呼称を「参考候補（翌日向け）」へ整理。選択日までの履歴から翌日向けに選ぶこと、通常機種は直近10記録日の当たり順位で同台が続くこと、低G当日台も履歴から候補になり得ること、翌日の優位性は未確認であることを説明。バラエティには通常式の説明を混ぜない。
- `NEXT_DAY_REFERENCE_REVIEW_20260930.md` の固定4方式比較：直近重視は現行との共通グループで+1.0605点、95%区間-0.6720〜+3.1604。両店舗とも優位性未確認。連日同台率は77.13%→66.18%だが、精度改善とは別。本番式を変更しない。
- `CANDIDATE_LOW_ACTIVITY_REVIEW_20260930.md` の別固定4方式比較：低採点-1.9807点、低稼働+0.3900点、組み合わせ-1.4553点（全体の現行との直接差、すべて区間に0を含む）。バラエティ低G方式は翌日採点45→17台で評価率悪化。採用を支える改善なし。解析用の2モジュール/CLIを画面には接続しない。
- PCバックアップ8,787件・8予測日を使い、翌日0:00より前の取得だけを使う。欠測を0G、未採点を0点にしない。既知過去データ・少数日・複数方式・日間依存のため回顧的探索。未来検証の固定期間は規約へ記録したが、自動監視・自動採用は設定しない。実データと詳細集計はGit外。
- 検証：表示/関連49件＋直近重視11件＋低採点/低G9件＝69テスト成功。12 Dartファイルの静的解析は指摘なし。4方式集計は別担当QA、追加方式は別計算で36集計のcoverage・日平均・反復率・店舗/種別合計を検算。iPhone/Safari実機操作は今回未実施。APKビルドなし。
- 公開：最終比較レビューで負の最大持玉も3日特徴から除外し、影響する9テスト・3ファイル解析と実測を再確認（結論不変）。ソース `c02d7c3` とorigin/mainの一致・clean状態からWeb release build成功。`tool/stage_viewer.py` で実seedを除外し、記録由来90種類の文字列に該当なし。公開リポジトリ `d41bdac` へpush、[Pages run 36706506771](https://github.com/keyanbaitian6-cell/database-viewer/actions/runs/36706506771) 成功。[公開ページ](https://keyanbaitian6-cell.github.io/database-viewer/) は200、seedは404、公開main.dart.jsのSHA-256 `153a86e1ff1a6b9097957c3a506500d725c43d5ac55d674372a797d3b9610c43` は手元のビルドと一致。HTMLもCRLF/LFをそろえて一致。APKは作らず、Androidの共通表示修正はソースのみ。

## 2026-09-30：閲覧ページの追加バグレビュー

- 利用者の依頼：新しいモデルでもバグ修正・検討余地を点検。正本 `e899f5d` をfetch/pullし、ブラウザの取り込み、イベント、日付切替、スクロールを並行して確認。採点・予測式・デザイン・端末内の保存データは変更しない。APKは今回はビルドしない。
- Drive更新：古い記録を手元に残すとき、Drive側で解除した最近のイベントまで復活していた。引き継ぐイベントは今回残す古い記録の店舗・日付だけに限定。最新期間は新しいバックアップを正とする。
- 壊れた台情報：`day` が数値の1件でファイル全体の読み込みが例外になった。日付の型を先に確認し、既存仕様どおり不正な台だけを除外する。
- 新規予測の戻り先：別店舗で日付を変えて戻るとホームの店舗だけ元のままになる。候補詳細で日付を変えて戻ると新規予測の選択日だけ古いままになる。店舗・日付を一組で親へ伝え、候補詳細からの変更も新規予測へ反映する。
- 「一番上へ」：候補を「上位7台だけ表示」へ折りたたんだ場合、画面を高くした場合も、位置の補正後にボタンが残る。ScaffoldのScrollNotificationObserverを監視し、購読の差し替え・破棄も行う。
- JSON取り込み：改行なしの短いJSONの例外、後ろにあるイベント・候補情報の読み飛ばし、途中切れ・カンマ欠落・余分な末尾文字・異なるformatの誤受け入れを修正。各台をnullに置き換えた軽い文書構造を最後に検査し、画像を保持しないストリーム読み込みを維持する。エラー時はreaderをキャンセル、ロックはfinallyで解除する。
- 検証：Dartのデータ10件、スクロール8件、選択・日付切替・新規予測19件の計37件成功。取り込みの埋込JavaScriptそのものをNodeで実行した18件成功。新しい再現テストは修正前の失敗も確認。実際のiPhone/Safariでの操作確認は未実施。
- 前回公開の確認も完了：Pages run `36639992932` は成功、公開リポジトリ `cd67a10`。公開ページ200・seed404、公開main.dart.jsと手元のSHA-256 `cc1677442476bb2c5b1505b516819e56ce522fd18b2c83fb3dc41f5d574679c7` は一致。
- 今回の公開：変更したDart7ファイルの静的解析は指摘なし。ソース `5e34629` とorigin/mainの一致を確認してWeb release build成功。`tool/stage_viewer.py` で実記録を除外し、記録由来の90種類の文字列も該当なし。公開リポジトリ `9f2b507` へpush、Pages run `36672406039` 成功。ページ200・seed404、公開main.dart.jsのSHA-256 `9513becfbb399b82531ca53a7b4fec03e8b354294c1565b04aeebd42750fa10c` はビルドと一致。HTMLはGitのCRLF/LF差をそろえて完全一致（LF化SHA-256 `869d14d9b2b3777c0802186f64dd3357812a59b35855edc1e1baa3291778bd2a`）。

## 2026-09-30：閲覧ページの「一番上へ」を再確認して公開

- 利用者の依頼：Claudeの変更が完了したため、確認して問題がなければ公開。正本 `de1b705` をfetch/pullして点検。
- 追加検証で1件再現：新規予測の長い一覧を下へスクロールしてから候補なしの日へ変えると、位置は600px以下になるのにボタンが残る。リストの高さ変更による位置補正ではScrollControllerの通知が来ない場合がある。
- 修正：`ScrollTopButton` の初回・親の更新後に、レイアウト完了後の実際の位置でも表示可否を更新。破棄後のコールバックはmountedで除外。採点・予測式・保存データは変更しない。
- 確認：追加した新規予測のテストは修正前に失敗、修正後は成功。ボタン6件・Android日付切替7件・ブラウザ日付切替8件の計21テスト成功。変更ファイルの静的解析は問題なし。Claudeの既存実ブラウザ確認の記録は参照したが、iPhone実機確認は今回も行っていない。

## 2026-09-30：閲覧ページに「一番上へ」ボタン（Android版の結果タブと同じ）

- 利用者の依頼：ブラウザ版にも、Android版のように右下へ「一番上に戻る」ボタンを出す。正本 `eab0f4b` を fetch/pull して開始し、途中で `7648117`（Android 0.5.8）を取り込んだ。ChatGPTが同時にAndroid版を作業していたので、Androidの `main.dart` には触れていない。
- 追加：`shared_widgets.dart` の `ScrollTopButton`。見た目と動きはAndroid版の結果タブの右下ボタンと同じ（600pxより下で表示、黒80%の丸に白の上向き矢印、押すと350msで一番上へ）。Scaffold の floatingActionButton に置くので、メッセージ（SnackBar）が出ている間はその上へよける。
- 付けた画面（閲覧ページだけ）：ホーム、機種ページ（バラエティを含む）、答え合わせ、新規予測、台の詳細。台の詳細はAndroid版と共通の `SavedGraphPage` なので、`scrollTopButton: true` を渡したとき（閲覧ページ）だけ出す。Android版の見た目・動きは変更なし。
- 機種ページは日付を変えるとリストを一番上から作り直すので、ボタンも日付をキーにして隠した状態へ戻す。各画面の下の余白を88px（Android版と同じ）にして、最後の行がボタンに隠れないようにした。
- 確認：追加5件（ホーム、機種ページの日付切替、台の詳細の閲覧ページ／Android版の指定なし、答え合わせ）。変更前のコードでは4件が失敗し（Android版の指定なしの1件は変更前でも成功するのが正しい）、日付のキーを外すと機種ページの1件が失敗することを確認。全テスト成功。解析は既存の9件のみで、変更したファイルへの指摘なし。Web release build 成功。375×812で実データ（`database-viewer.json` の一時コピー、確認後に削除）を読み、ホーム・バラエティの機種ページ・日付切替・台の詳細で、ボタンの表示、一番上への移動、最後の行が隠れないことを確認。iPhone実機では未確認。公開は利用者の許可待ち。

## 2026-09-30：Android日付切替の再点検と0.5.8ビルド

- 利用者の依頼：Androidを先に確認・検討・ビルドし、その後ブラウザ版の追加機能を確認。fetch/pull時点の正本は `eab0f4b` のまま。利用者から「Claudeはまだ作業中」と回答があったため、ブラウザ版は完了後に別途確認する。
- 日付切替・イベント表示・Controller通知・非同期読み込みを再点検し、この範囲では新しい不具合は見つからなかった。本体コードの追加修正はなし。
- 追加検証：日付を素早く戻した後の遅い計算で別日の内容に上書きされないこと、イベント更新が反映されること、読み込み中に画面を閉じても例外にならないこと。追加2件を含む日付切替7テスト成功。`android_record_page.dart` と該当テストの静的解析は問題なし。前回成功した他の関連テストは、本体コードが変わっていないため繰り返していない。
- APK版を `0.5.8+2026093003` に更新。端末データ・採点・予測式は変更しない。実機へのインストールは今回行わない。
- ビルド：`0ae2ebd` と origin/main の一致を確認して `flutter.bat build apk --release --no-pub` 成功。APK実体のversionName `0.5.8`・versionCode `2026093003` をaaptで確認。配布用 `outputs/database-0.5.8-2026093003.apk`（91,424,206 bytes、SHA-256 `29afa75327de378820a617a11684abdd2a3600b815ecd7086ee9993c874f076c`）。実機動作・インストールは未確認。

## 2026-09-30：Android版にも日付切替・イベント表示（当時はビルド待ち）

- 利用者の依頼：ブラウザ版と同様、各データ表示に日付切替とイベント名を追加。正本 `f483529` を fetch/pull して開始。途中で「まだ修正があるのでビルド不要」と指定されたため、APKは作らずバージョンも変更しない。
- 結果画面：ブラウザ版の `ViewerDateBar` を再利用し、前後の記録日ボタン・日付一覧・イベント名を画面上部に固定。候補・機種一覧・グラフ一覧をスクロール中も切替可能。従来のスクロール内の日付欄は重複するため外し、店舗選択とイベント編集は残した。
- 過去の記録の機種詳細：同じ日付バーを追加。グラフ表示の選択を保ち、選んだ日の全店候補と一致する★を表示する。
- 台の詳細：`AndroidRecordPage` を追加し、結果の候補・まとめ・機種別の表/グラフ・履歴詳細から接続。同じ店舗・機種・台番号を保って切替。機種入替や未取得の日は「この日の記録はありません」とし、別機種の台を混ぜない。Controllerの変更を監視して削除・イベント編集を反映し、非同期計算中やエラー時に前の日のデータを出さない。詳細内の切替は親画面の日付を変更しない。
- 確認：追加5件を含むAndroid日付切替・バラエティ表示・履歴・一覧・候補カードの28テスト成功。既存ブラウザ日付切替8テストも成功。対象3ファイルの静的解析は既存の `DropdownButtonFormField.value` 非推奨info 1件のみ。採点・予測式・保存形式・ブラウザ版コードは変更なし。実機確認・インストール・APKビルドは未実施。

## 2026-09-30：Android版のバラエティ表示を点検・修正

- 利用者の依頼：ブラウザ版と同様にAndroid版を検討・修正。正本 `ce67fc1` を fetch/pull して開始。
- 結果画面：検索欄を実際の機種数で判定し、バラエティにまとめても検索可能にした。店舗・日付変更後も入力中の検索語を解除できる。検索で絞った表・グラフの「★翌日向け」は表示中の台だけ数える。
- 過去の記録の詳細：検索・種別で絞られたバラエティの★台数を表示中の台にそろえた。詳細を開いたまま記録が変わり、機種が4台以上から3台以下になった場合も、当日の全候補と同じ★を表示する。
- 日付欄：393px幅で日付の折り返しにより24pxはみ出すことを確認。選択済み欄は日付1行にし、イベントはその下へ表示。日付一覧の各行にはイベント名を残し、長い名前は省略表示する。
- 確認：検索と候補表示の4件が修正前に失敗することを確認。追加5件を含む結果・履歴・一覧・候補カード・バラエティの関連30テスト成功。対象ファイルの解析は既存の `DropdownButtonFormField.value` 非推奨info 1件のみ（未変更箇所）。端末内データ・採点・予測式・PC・ブラウザ版のコードは変更なし。APKは `0.5.7+2026093002`。端末へのインストールは今回行わない。

- ビルド：main `999b988` と origin/main の一致を確認して `flutter.bat build apk --release --no-pub` 成功。APKの実体をaaptで確認し、versionName `0.5.7`・versionCode `2026093002`。配布用 `outputs/database-0.5.7-2026093002.apk`（91,407,802 bytes、SHA-256 `ee6c2be9667f66492411eabaf4521742a4bf9471bb3767b7e640ab977675e7c4`）。Android実機へのインストール・操作確認は未実施。

## 2026-09-30：閲覧ページのみ、バラエティ対応の確認と表示修正

- 利用者の依頼：Claudeが公開したブラウザ版の変更を確認し、問題があれば修正・公開する。正本 `33682e5` を fetch/pull して開始。Android・PCの計算や取り込み、APKは今回の変更対象外。
- 修正1：設置機種一覧の検索欄を「まとめた後の行数」で出していたため、1〜3台の機種が多数あっても検索できない場合があった。実際の機種数で判定し、日付・店舗を変えて機種数が減っても入力済みの検索語を解除できるようにした。
- 修正2：バラエティを機種名で絞って開いた画面で、見出しの「★翌日向け」が隠れた台も含む数だった。表示中の台に付く★の数と一致させた。
- 修正3：通常の機種ページで日付を変え、その日には1〜3台の機種になった場合、その機種だけからバラエティ候補を選び直していた。ホームと同じ店舗・日付の全台から候補を計算し、表示中の台にだけ★を付けるようにした。候補の選び方自体は変更していない。
- 確認：上記3件の回帰テストが修正前に失敗することを確認。修正後は日付切替・バラエティ・候補カード・新規予測・設定2候補の関連29テスト成功。変更した3ファイルの静的解析は問題なし。Web release build 成功。
- ローカルブラウザ確認：PCバックアップ6,015台を端末内で読み、393px幅でバラエティ候補5台、機種名検索、絞り込み後の「1台・★翌日向け1台」、表とグラフの切替を確認。iPhone実機では未確認。
- 公開：ソース `6e56139` のWebビルドを `tool/stage_viewer.py` で実データ除外後、公開リポジトリ `3341d66` へpush。Pages run `36594936140` 成功。公開 `main.dart.js` とビルドのSHA-256はともに `80bd225b878302554aabdff8e43ac58f49b27c0ae16b7671a26c58668b0f5590`、ページ200・seed404を確認。

## 2026-09-29〜30：バラエティ（1〜3台の機種）をまとめて翌日候補に入れる

利用者の依頼：各店の1機種1台の機種を店ごとに「バラエティ」1つにまとめて処理し、翌日予想に入れる。「バラエティの中でも何個かは設定が良い台があるだろう、ということでデータを見る」ので、プロのスロッターの見方で選ぶ。表示は「501番台　機種名（バラエティ）」の形（501は例）。

- 利用者に確認して決めたこと：対象は1〜3台の機種（2〜3台の機種も今の方式では候補になれない）／設置機種一覧でも「バラエティ（N機種）」1行にまとめる／翌日候補は店ごとに狙い方を変え、各店5台。
- 選び方（`NEXT_DAY_CANDIDATES_VALIDATION_20260929.md` の「9.」）：前日3000G以上回った台だけを見て、長町南は「回ったのに凹み（マイナス終了）」→「回ってプラス」、幸町は「回ってプラス」→「回ったのに凹み」の順、同じ組では当たりがその台の普段（同じ機種の前の30日）より軽い順、次に回転数の順で5台。別の機種の台どうしの当たり確率は比べない（機種ごとに1/19〜1/354と違う）。
- 途中で「今の指数の比べる相手をその台の過去に替えたもの」を作ったが、利用者の「プロの見方で」で置き換えた（配布・公開していない。PC版の記録にもその版のバラエティの記録は無いことを確認）。
- 表示：Android版の結果画面・閲覧ページの設置機種一覧でバラエティを1行にまとめ（最後に置く。開くと台ごとに機種名の列・グラフに機種名。検索は機種名でも当たり、その機種の台だけに絞る。バラエティの欄には「まとめて削除」を出さない）、翌日候補のカードでは4台以上の機種の候補の後ろに「バラエティ（1〜3台の機種）から5台」を最初から全部出す。答え合わせ・台の詳細・PC版の機種のまとめ（HTML）も同じ見方の説明に。
- 候補の記録：機種名「バラエティ」で店・日ごとに1件（方式の版 `2026-09-29`）。1〜3台の機種ごとの記録は作らない（以前に候補が出ていた機種だけ「候補なし」に更新）。台数が変わってバラエティに入る・出るときは両方を記録し直す。
- 検証ツール：`variety_cutoff_0000` を追加（バラエティの5台と全台の比較）。2026-09-29の検証の集計は1桁も変わらないことを確認。7日分の成績は両店 +5.25［+0.95, +9.79］だが、選び方を決めたのと同じ期間なので後知恵を含む。9/29以降の予測で、店ごと14日たまったら確かめる（基準は文書に先に書いた）。
- 確認：PC 121テスト、Android 249テスト成功。Dart静的解析は既存のinfo 9件のみ。PC版とAndroid版の候補が全期間で1,102台一致。閲覧ページを手元で開いて、候補カードのバラエティ欄と「バラエティ（67機種）」の画面を確認。
- 別件の確認：9/29分の沖ドキ・オキドキの記録（長町南17台・幸町19台）は、Android版（対象外にする前のAPK）で取り込んだもの（時刻の形式で確認、利用者も確認）。PC版の対象外は効いている。記録は消していない。
- Android版の「過去の記録」タブも、日付ごとの一覧で1〜3台の機種を店ごとの「バラエティ（N機種）」1行にまとめた（その店の最後。開くとバラエティの画面、機種名で検索するとその機種の台だけ、「バラエティ」で検索すると全台）。利用者の指定「今はブラウザ版だけでいい、次に作るときはAndroidにも入れる」により、**0.5.6のAPKには入っていない。次のAPKのビルドで入る**（mainには入れ済み）。閲覧ページには「過去の記録」タブが無く、日付の欄で過去の日を選ぶと、すでにバラエティで表示される。
- ビルド（利用者の依頼、2026-09-30）：`0ff0f22` の上で版だけ `0.5.6+2026093001` に上げ、`C:\Users\keyan\flutter\bin\flutter.bat build apk --release`。ビルド前に、手元とGitHubの差分なし・`database-claude-review` の作業がすべてmainに入っていることを確認。aaptで versionCode `2026093001`・versionName `0.5.6` を確認。配布用 `outputs/database-0.5.6-2026093001.apk`（91,391,418 bytes、SHA-256 `426e6d2d511941753d7f9c94212027948793218d55dda7c2884099a92fdca727`）。インストールは利用者が `adb install -r` で行う（アンインストール・データ消去はしない）。
- 公開（利用者の許可、2026-09-30）：`27c6818` から閲覧ページを組み立て（`--base-href /database-viewer/`）、`tool/stage_viewer.py` を通して `keyanbaitian6-cell/database-viewer` の `e5ec755` に公開。GitHub Pagesの反映完了、公開中の `main.dart.js` のSHA-256が組み立てたものと一致（`9fd4397e…`）、記録ファイルは404、ページは200を確認。

## 2026-09-29：取り込みの改善（沖ドキを対象外・大当たり0回はグラフ省略、採点v12）

利用者の依頼：Android版・PC版とも、(1)「沖ドキ」を含む機種は全角・半角を問わず長町南・幸町とも対象外、(2) 表を取り込んだ時点で大当たり回数が0の台は、0のデータは取り込むがグラフは取らない。

- 実データ（PC版7,863件）を見て2点を利用者に確認した。サイトの表記は「沖ドキ」（長町南「S/沖ﾄﾞｷ!GOLD/LS」）とカタカナの「オキドキ」（幸町「L／オキドキデュオ2／FR」、長町南「L/ｵｷﾄﾞｷﾃﾞｭｵ2/FR」）の両方がある → **オキドキも対象外**。大当たり0回で501G以上の台は採点されるため、グラフが無いと中立点で補って点が高めになる → **すべて省略し、採点では終点・維持を0点扱い**（採点版を v12 に上げる）。
- 対象外：既存の「データ非公開の機種」（長町南のジャグラー・幸町のブラックボード）と同じ仕組みに両店共通の「沖ドキ」「オキドキ」を追加（Androidは半角表記も並べる、PCはNFKC）。次の機種の候補にせず、機種一覧の印は「対象外」。加えて、対象外の機種の表・グラフのページで取り込みボタンを押しても保存せず「…は取り込みの対象外です。保存しませんでした。」と出す（ジャグラー・ブラックボードも同じ扱いになる）。「コードギアス」「ドキドキ」は巻き込まない。**既存の沖ドキの記録は消していない**（閲覧・結果にはこれまでの分が残る）。
- 大当たり0回：「BB+RBが0」をグラフ不要とする（表の列はBB/BIGとRB/REGだけを読んでいる）。判定は保存した数値からその都度行うので、表を取り込み直して当たりが付けば、また取る対象に戻る。次の台・残り台数・進み具合・機種一覧の印（済 n/n）・日の完了・まとめの「グラフ未取得」から除き、表の保存時に「大当たり0回のn台はグラフを省略します。」と出す。台のスランプ枠は「大当たり0回（グラフ省略）」。Android `SlotRecord.graphNotNeeded`／`graphDone`、PC `core.graph_not_needed`／`graph_done`。
- 採点 v12（`SCORING_POLICY.md` の「v12での変更」）：大当たり0回でグラフの無い台は終点0点・維持0点。0回550件のうち終点がプラスだったのは24Gの1件だけ、という観察に基づく補完。既存の記録で新たにこの扱いになる13件はすべて500G以下（採点なし）なので、**既存の点数は1件も変わらない**（翌日候補の検証（v11固定）の結果もそのまま）。幸町の0回の台は最大持玉が欠測のまま（中立で補う）。
- 確認：PC 114テスト、Android 239テスト成功。Dart静的解析は既存のinfo 9件のみ（今回触っていないファイル）。PC版7,863件でPython/Dartの採点一致（v12）。APKのビルド・閲覧ページの公開は、利用者の指示待ち。

## 2026-09-29：新しい選び方の探索と、閲覧ページの「新規予測」（試験）

利用者の依頼：検証とは別に、新しい選び方を探索として試し、閲覧ページ（ブラウザ版）に「新規予測」という項目を作る。閲覧ページの基本的なスタイルは崩さない。PC版・Android版の画面は変えない。

- 結果を見る前に、試す4案（前日の点数が高い台／指数と前日の点数の組み合わせ／直近5日の平均点／前日の点数が低い凹み台）と理由、選び方（選ぶ期間9/21〜9/24でいちばん良い案、確かめる期間9/25〜9/27の成績はそのまま報告）を `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md` の「8. 探索」に書いてpushした（`893108f`）。
- 結果（翌日0:00締切）：選ぶ期間では組み合わせが最良（+2.24、現行より +2.98）で、これを選んだ。確かめる期間では現行との差 −0.07（−2.44〜+1.96）で、良さは再現しなかった。凹み台は選ぶ期間で悪かった（−4.22）が確かめる期間は +0.70。締切9:00の補足では前日の点数が高い台が選ばれ、締切の時刻で結論が変わる。どの案も安定して良いとは言えない。
- 実装：`lib/exploratory_candidates.dart`（4案の計算。候補にできる台と台数は現行と同じ）、`lib/exploratory_page.dart`（閲覧ページの新規予測。翌日候補（仮）と同じカードの見た目、日付バー・イベント名つき、台を押すと台の詳細）、`viewer_main.dart` のホームに答え合わせと同じ形のボタン。検証ツールにも同じ関数で探索の集計を追加（既存の集計は1桁も変わらないことを確認）。
- テスト：`test/exploratory_candidates_test.dart`（5件：台数が現行と同じ、検証の計算と同じ台、凹み台の並び、直近5日の条件、未来の記録で変わらない）、`test/exploratory_page_test.dart`（2件）。Android全236件成功。手元で組み立てた閲覧ページ（スマホ幅・実データ）で、ボタン・カード・成績の説明・台の詳細への移動を確認した。
- 公開：利用者の許可を得て、`6c12383` から `tool/stage_viewer.py` を通して `keyanbaitian6-cell/database-viewer` の `060089f` に公開。GitHub Pagesの反映完了、公開中の `main.dart.js` のSHA-256が組み立てたものと一致（`1bfa0b07…`）、記録ファイルは404、ページは200を確認。APKは今回ビルドしていない（Android版の画面は変わらないため）。
- 今後：新規予測は探索中の試験表示。日数がたまったら（「今後の検証」）、現行の翌日候補と同じ方法であらためて評価し、続けるか外すかを決める。

## 2026-09-29：翌日候補（仮）の計算方法の検証（現行を維持）

利用者の依頼：今の「過去の傾向から翌日候補を選ぶ」計算でよいか検証し、裏付けのある改善だけを実装する。詳細・数値・再実行手順は `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md`。

- 翌日の点数を見る前に、比べ方と「方式を変える条件」を文書にしてpushした（`d808a70`）。比べたのは、2026-09-26に決めていた「現行」と「前日の点数（v11）が高い台」、それに無作為の期待値だけ。正解は翌日のv11合計点。9/26（v10）の数値とは混ぜない。
- データ：PC版の自動バックアップ（9/29 00:32、SHA-256 `d40d6eec…`、7,863件・21日・候補の保存履歴807件）。主評価は翌日0:00（日本時間）締切で、`captured_at` が締切前の記録だけを使った（`first_captured_at` はPC版で取り込み時刻が入るものがあるので使わない。イベント名は登録時刻が無いので使わない）。7予測日（9/21〜9/27）・198グループ。
- 結果：現行の候補の翌日の点数は、候補にできる台全体と差が無かった（−0.23点、日単位95%区間 −1.98〜+1.36）。前日の点数が高い台 − 現行は +0.86（−1.48〜+3.40）で、条件を満たさない。最初の7台、データ量の少/中、指数と翌日の点の順位相関（機種内0.06・機種をまたいで0.05）も差や関係は確認できなかった。締切9:00・時刻を無視・書き込み記録で補う補足の検証でも、向きは条件によって変わった。保存済みの予想（当時の画面の候補）は2日分だけで判断材料にならない（再計算との一致85%）。
- 変更（計算式・候補の選び方・採点は変えない）：候補カード（Android・閲覧ページ共通）に選択日と対象日、検証の結果、「データ量は当たりやすさではない」を書いた。答え合わせは「今の式で計算し直した候補で、当時の画面と違うことがある」と書いた。保存する候補の記録に計算方式の版 `method`（`2026-09-27`。Android `nextDayMethodVersion`・PC `NEXT_DAY_METHOD_VERSION`）を残す。
- 検証ツール：`lib/next_day_backtest.dart`・`tool/backtest_next_day.dart`（アプリの関数をそのまま呼ぶ）、`database/export_earlier_values.py`、`database/check_candidate_parity.py`（PC版とAndroid版の候補は全データ1,026台で一致）。実データ・台ごとの結果はコミットしていない。
- テスト：Android 229件成功（検証の計算7件・カード2件・候補の記録の版を追加）、PC 111件成功。以前Claudeが書いた `startup_and_queue_test.dart` の1件が、候補の計算の別Isolate化（`a955bf6`）後にタイミング次第で失敗していたので、決まった時間ではなく知らせが出るまで待つように直した（6回連続で成功）。
- 今後：1点程度の差を見分けるには、締切前に全台を取り込んだ予測日が現行で約24日、前日点との比較で約51日必要な見込み（日ごとのばらつきからの推測）。
- ビルド：`9d74df2` の上で `C:\Users\keyan\flutter\bin\flutter.bat build apk --release`。aaptで versionCode `2026092901`・versionName `0.5.5` を確認。配布用 `outputs/database-0.5.5-2026092901.apk`（91,227,578 bytes、SHA-256 `d849a2b4e802e70bc6915198cd085eb10c3fbb5a28897bd7a5787227160c55c8`）。端末へのインストールは依頼が無いので未実施。
- 公開：閲覧ページを `tool/stage_viewer.py` を通して `keyanbaitian6-cell/database-viewer` の `294e2ba` に公開。GitHub Pagesの反映完了、公開中の `main.dart.js` のSHA-256が組み立てたものと一致（`72035649…`）、記録ファイルは404、ページは200を確認。手元で組み立てた閲覧ページ（スマホ幅・実データ）で、候補カードの選択日・対象日・検証結果の説明、答え合わせの説明、日付の切り替えを確認した。

## 2026-09-29：閲覧ページの日付一覧にイベント名

- 利用者の依頼：日付を選ぶ一覧（ドロップダウン）の各日にもイベント名を出す。以前は選んだ日のイベント名を日付バーの下に1つ出すだけだった。
- `ViewerDateBar` に `eventFor` を追加し、一覧の各日付の下にその日のイベント名を小さく出す（`_DayItem`）。選んだ後の欄は `selectedItemBuilder` で日付だけにし、日付バーの高さは変えない。ホーム・機種ページ・台の詳細・答え合わせのすべての日付バーに渡した（答え合わせは `AnswerCheckPage.eventFor`）。
- テスト：`viewer_navigation_test.dart` に1件追加。Android全220件成功。手元で組み立てた閲覧ページ（スマホ幅・実データ）で、一覧に「超探す楽しみ」「4台構成」などが出ることを確認。
- 利用者の許可を得て閲覧ページの公開を更新（`keyanbaitian6-cell/database-viewer` の `e372adc`）。公開中の `main.dart.js` が組み立てたものと一致し、記録ファイルが無いこと（404）を確認した。

## 2026-09-29：閲覧ページ（iPhone版）のジャグラー・ハナハナ推定設定を2候補表示に

利用者がChatGPTに依頼した作業を、ChatGPTの利用制限のためClaudeが引き継いでコミット・公開した。計算・表示・検証はChatGPTが実装したもの（詳細は `SETTING_ESTIMATION_REVIEW_20260929.md`）。

- 推定の基本式（BB・RB・非当選の多項尤度、各設定同じ事前重み）は変えていない。全設定の重みを未丸めのまま並べ、上位2つを「推定2候補」（左が1位）として出す。残りの設定の重み（候補外）も詳細に出し、2つだけで100%にしない。500G以下は「少数G・参考」、候補外の合計が上位2つ以上なら「候補外も大きい」と表示する。手入力の設定情報があればそちらを優先する。
- 2候補表示は閲覧ページ（`ViewerApp` を `SettingEstimatePresentation` で包む）だけ。Android版・CSVの従来表示（中央80%の範囲）、採点・保存データは変えていない。
- ChatGPTの検証：独立したPython実装と336パターンで一致。メーカー公表確率で作った模擬データ（各設定同数）では、8,000Gで正解設定が2候補に入る割合は機種別に約55〜65%で、中間設定は外れやすい。これは模擬の結果で、実際の店での的中率はわからない（設定の正解データが無いため）。REGだけ・BBだけ・合算だけの方式より、現行の式の方が高かった。
- Claudeの引き継ぎ確認：変更内容とテスト（`test/setting_top_two_test.dart`）を読んで確認。未pushだった `5d1fb90`（日付切り替え）と合わせてAndroid全219件成功。手元で組み立てた閲覧ページ（スマホ幅）で、ニューキングハナハナVの表に「推定2候補」（例「V／4 参考」「4／3 候補外も大きい」）、台の詳細に「設定V 29.4%・設定4 26.2%／候補外 44.5%」が出ることを実データで確認した。
- 利用者の許可を得て閲覧ページの公開を更新（`keyanbaitian6-cell/database-viewer` の `04dce30`、ChatGPTが公開した日付切り替え `4950d38` の上）。`tool/stage_viewer.py` を通し、公開中の `main.dart.js` が組み立てたものと一致し、記録ファイルが無いこと（404）を確認した。

## 2026-09-28：iPhone閲覧ページの各画面で日付を切り替える

- 閲覧ページの上部に「前の記録日／日付一覧／次の記録日」を固定表示。ホームの機種一覧・翌日候補、機種別の表・グラフ一覧、台の詳細で使える。イベント名も選択日に合わせて表示する。答え合わせにも日付選択を追加し、従来の「すべての日付」表示を残した。
- `viewer_pages.dart` に閲覧専用の日付バー・機種ページ・台詳細ページを分離。同じ店舗・機種・台番号を保って切り替え、該当記録が無い日は「記録なし」にする（同じ台番号の別機種・別店舗を代用しない）。グラフ表示の選択は、記録なしの日を挟んでも保持する。詳細で日付を変えた後は、戻った機種ページ・ホームにも日付を反映する。
- 新デザイン・採点式・保存データ・Android側の操作は変更しない。共通の `SavedGraphPage` には省略可能な日付バーだけ追加した。
- 検証：スマホ幅393pxでの日付一覧・両端の矢印・欠損日・グラフ表示保持・同一台の判定・採点更新・スクロール中の日付操作・答え合わせの日付絞り込みを含む関連テスト16件成功。Webリリースビルド成功。iPhone実機での操作確認は未実施。
- 公開には必ず `tool/stage_viewer.py` を使用し、実データを除外する。APKは今回ビルドしない。

## 2026-09-28：起動時の機種名統一を「済んだ変更」に含める（「3」の残り1件）

Codexの確認で残っていた1件を、正本クローン（`database-main`、`a955bf6` の上）でClaudeが直した。

- 問題：起動時の `_loadNormalizedRecords()` は「読む → 表記ゆれがあれば `normalizeMachineNames()` でDBをそろえる → 読み直す」の順。そろえる書き込みが確定した後で読み直しだけ失敗すると、DBは変わっているのに `startupChanges` に入らず、`startupFailureText()` が「記録は変更していません」などと事実と違う説明を出しえた。
- 修正：`_loadNormalizedRecords({onChanged})` にし、`normalizeMachineNames()` がまとめた書き込み（トランザクション）を終えて1台以上そろえたときだけ、読み直しの前に `onChanged` へ説明を渡す。失敗・ロールバックした場合、そろえる台が無かった場合は渡さない。`onChanged` を渡すのは起動時（`initialize`）だけで、引っ張って更新（`reload`）や多い片付けの確認（`confirmLargeCleanup`）の読み直しでは起動時の説明に入れない。`initialize` の最初で `startupChanges` を空にし、前の起動の説明が残ったり重複したりしないようにした。時間切れ書き込みの追跡・大量バックアップ対策・非同期採点・通信待ちの処理は変えていない。
- 検証（実際のSQLite、`test/startup_and_queue_test.dart` に3件追加）：
  - そろえた直後の読み直しだけを失敗させる → 起動は止まり、説明は「次のことだけは済んでいます・機種名の表記ゆれがある2台を…まとめました」。DBの実際も、そろえた名前の台だけになり、画像・設定の記録（confirmedSetting）・イベント名・設定情報（app_state）・翌日候補の記録が残っていることを確認（説明とDBが一致）。
  - そろえる書き込みの途中で失敗させる（SQLiteのトリガー）→ まとめた書き込みごと元に戻り、`startupChanges` は空、説明は「記録は変更していません」。DBの表記ゆれの台・画像もそのまま。
  - 起動し直すと前の説明は消え、`reload` で表記ゆれをそろえても起動時の説明には入らない。
  - 修正前のコードでは、追加したテストのうち2件が失敗することを確かめた（ロールバックのテストは修正前も正しい動き）。Android全206件成功。`flutter analyze` のエラーなし（警告2件は以前からある `date_events.dart` の不要なキャスト）。
- 利用者の依頼でリリースAPK `0.5.4+2026092802` をビルド（`87afdfc` の上で版だけ上げた）。aaptで versionCode `2026092802`・versionName `0.5.4` を確認。配布用は `outputs/database-0.5.4-2026092802.apk`（91,211,194 bytes）。インストールは `adb install -r`（アンインストール・データ消去はしない）。

## 2026-09-28：「2」データ量・通信遅延への対応（Android）

- `f1a19f0` までのmain（Claudeの時間切れ追跡・起動説明、iPhoneの答え合わせを含む）に統合。新デザイン・v11の計算式は維持。
- バックアップ取り込みの画像付き取り消し控えと競合記録を `ImportSpool` の一時ファイルに保存する。メモリ上の競合一覧は画像なし。競合の確認・適用は50件ずつで、選んだ分だけ画像を読む。取り消しも分割して読み、DBへの復元は1トランザクション。控えの書き込みをコミット前に完了させ、失敗時はDBを戻し、以前の取り消し控えを保持する。不要な控えは片付け、異常終了で残った分は3日後の起動時に削除。
- 候補履歴は読み込み・書き出しを分割し、画面用には店舗・日付・機種ごとの最新分だけ保持する。既存の保存期間ルールは維持し、今回のメモリ削減のためにDB内の履歴を削除しない。画像以外の台情報・キー一覧は引き続き台数に比例する。旧書式の丸ごと読み込み上限64MBも維持する。
- 結果画面・履歴画面の採点と保存時の候補計算を `compute` で別Isolateへ移す。表示用計算は順番待ちにして、日付切り替えで多数のIsolateが同時起動しないようにした。キャッシュは記録の更新で無効化し、FutureBuilderは選択中の結果だけを表示する。
- 内部ブラウザはページ完了・jQuery通信待ち・表示中のローダー・表/グラフ/機種一覧の内容の安定を確認する。時間切れで取り込み可能にはしない。機種一覧が1件届いただけで次の機種や「完了」を判断しない。メイン文書の通信・HTTPエラーも表示し、その文書の遅れて届いた完了通知では取り込みを再開しない。サイト側の将来の更新すべてを保証する仕組みではなく、実サイトの遅い通信での端末試験は未実施。
- 検証：統合後のFlutterテスト203件成功（画像付き350台の取り込み・取り消し、120件の競合、652件の候補履歴、採点一致、遅い通信・空一覧・ページ遷移のテストを追加）。埋込JavaScriptの抽出・準備判定、既存のPC/Android抽出テスト15件も成功。
- リリースAPK `0.5.3+2026092801` のビルド成功、aaptで版を確認。配布用は `outputs/database-0.5.3-2026092801.apk`（正本クローンの2階層上のoutputs、91,211,194 bytes、SHA-256 `53E51B7327D5E290B8580D24E5BDF494C83AB3B2CD0E0D83D02ACF26B4DD2B50`）。静的解析はエラーなし、既存の警告・info計9件。実機へのインストール・閲覧ページの再公開は実施していない。
- Claudeの「3」もコードと既存テストを確認。時間切れ後の成功/失敗通知・新規書き込み拒否、起動時の任意の片付け失敗の扱いはテスト成功。**残る確認事項**：`_loadNormalizedRecords` は機種名統一をDBへ保存してから再読込するが、その保存を `startupChanges` に記録しない。再読込だけが失敗すると、起動エラーの「記録は変更していません／ほかの記録は変更していません」が実際と合わない。今回は「3」は確認のみの依頼なので修正せず記録する。

## 2026-09-28：閲覧ページ（iPhone版）に「答え合わせ」

利用者の依頼：「答え合わせ」ページで、前日の翌日予想に挙げた台のうち、実際に60点以上を記録した台の一覧を出す。

- `lib/answer_check.dart`（新規）：`answerCheckFor(all, store, day)` は、暦の前日（`day`の1日前）の記録から `dayCandidates` で翌日候補を出す。そのうち、`day` に同じ店舗・同じ機種・同じ台番号の記録があり、`scoreRecord` の合計点が60点以上の台を返す。候補数と「翌日に点数が出た台数」も返す（取り込んでいない台・機種が入れ替わった台・500G以下などで採点しなかった台は、点数が出た台に数えない）。翌日候補は前日までの記録しか使わないので、あとから計算しても前日の結果画面に出ていた候補と同じになる（テストで確認）。暫定の点数も含め、「暫定」と表示する。
- `AnswerCheckPage`：店舗の切り替え、全期間の合計（候補・点数が出た台・60点以上と割合）、日ごとのカード（60点以上の台を点数順に並べ、押すと台の詳細）。Webでは計算が画面と同じ処理で動くため、1日ずつ計算して、できた日から表示する。閲覧ページの日付選択の下に「答え合わせ（前の日の候補の結果）」ボタンを置いた。
- 実データ（9/28 07:50書き出しの閲覧用ファイル、6,939台）で確認：長町南は19日分・候補218台・点数が出た193台・60点以上54台（28%）、幸町は12日分・候補470台・439台・135台（31%）。手元で組み立てた閲覧ページでも同じ数字が出て、台の詳細も開くことを確認した。
- テスト：`test/answer_check_test.dart`（4件）。Android全195件成功。
- 利用者の許可を得て閲覧ページの公開を更新（`keyanbaitian6-cell/database-viewer` の `b8da129`）。公開中の `main.dart.js` が組み立てたものと一致し、記録ファイルが無いこと（404）を確認した。

## 2026-09-28：ChatGPTの点検の⑥⑦（時間を超えた書き込み・起動途中の説明）

利用者がChatGPTに依頼した点検のうち、未着手だった2件をClaudeが直した。ChatGPTは同じ時期に `database-main` のクローンで別の修正を未コミットのまま進めていたため、その変更と同じ行には触れていない。改行コードを揃えて3方向マージを試し、衝突が無いことを確認済み。

- ⑥ `WriteQueue`：以前は、60秒を超えると呼んだ側へ時間切れを返し、処理は裏で続けたまま、その後の追跡をしていなかった。今回から、開始済みの処理が時間を超えたら「続いている」（`overdue`）として覚える。その間の新しい書き込みは、待たせずに断る（同じ操作が2回行われるのを防ぐため）。処理が終わったら（成功・失敗とも）`onLateFinish` で知らせ、`AppController` が画面の知らせと、どの画面でも見えるSnackBarで結果を出す（`main.dart` の `messengerKey`）。時間切れの文言も「開き直して確かめて」から「続いているので終わったら知らせる」に変えた。
- ⑦ 起動（`AppController.initialize`）：以前は、途中で失敗すると、済んだ段階に関係なく一律「記録は変更していません」と出していた。今回から次のように分けた。
  - 後回しにできる片付け（イベント名の初期値の保存、古い記録の片付け、ゴミ箱の古い分の削除）は `_startupStep` で行う。失敗しても起動は止めず、注意（`startupWarnings`）を出す。どの片付けも1回でまとめて行うので、失敗すれば何も変わらない。
  - 済んだ変更は `startupChanges` に記録する。必須の読み込み（設定・状態・記録）で失敗したときは、`startupFailureText` がその内容を書く（何も無ければ従来どおり「記録は変更していません」）。`purgeTrash` は消した件数を返すようにした。
- テスト：`test/startup_and_queue_test.dart` を新しく追加（6件）。Android全191件成功。APKは未ビルド（ChatGPTの未コミットの変更が入っていないため）。

## 2026-09-28：PC版の見出しの整理と、取り込みブラウザの配置の保存

- 利用者の指示で、PC版メイン画面の見出し下の「長町南店・幸町店｜1000円46枚スロット」を削除した（`app.py`）。対象外ページでの注意文は残している。
- 利用者の指示「ブラウザを起動したら、オーバーレイ・ウィンドウサイズ・表示位置をすべて今の状況に」：以前は毎回1280×900で中央に開き、オーバーレイは右上に戻っていた（pywebviewの既定はプライベートモードで、オーバーレイの位置・倍率を入れていたlocalStorageが閉じると消えるため）。
  - 最初の配置 `DEFAULT_BROWSER_LAYOUT`（`browser_import.py`）は、利用者が開いていたブラウザから読み取った値：窓 x=1231・y=481・573×495（枠を含む外側の論理ピクセル）、オーバーレイ left=213・top=84・倍率1.6。1920×1080・表示倍率100%の画面。同じ値でテスト窓を開き、窓は完全に一致、オーバーレイは1〜2ピクセル以内であることをスクリーンショットで確認した。
  - その後に窓やオーバーレイを動かす・大きさを変えると、`data/browser_layout.json` に保存し、次回はその配置で開く（オーバーレイはドラッグ・－＋のたび、窓は閉じたとき）。最小化中の位置や範囲外の倍率は保存しない。保存した窓が今の画面の外になる場合（モニターを外したときなど）は、以前どおり1280×900で中央に開く。
  - テスト：PC 111件成功（配置の保存・読み込み・不正値のテストを追加）。

## 2026-09-28：閲覧ページでグラフの線を描く（利用者の選択：曲線・60日分）

- 閲覧用ファイル `database-viewer.json` に、グラフの曲線（サイトのSVGの線。画像の約6分の1の大きさ）を残すようにした（`core.export_viewer`。画像は今までどおり入れない）。閲覧ページのJavaScript（`web/index.html`）も、手で選んだバックアップから曲線を捨てずに残す。
- 閲覧ページは、曲線がある台は線を描き（`machine_sections.dart` の `CurveGraphPainter`・`curveCanvasSize`）、無い台（約5%）は今までの4点の概略図。台の詳細・5日間のスランプ・機種のグラフ表示のどれも同じ。Android版は画像を持つので変わらない。
- 曲線の座標は画像と同じ座標系で、ふつうは保存した幅・高さに収まる。PC版の取り込みの一部は曲線の方が広いので、幅を曲線に合わせ、高さも同じ割合で広げる（縦横比は画像と同じ）。
- 大きさ：実データ6,939台（21日分）で閲覧用ファイルが3.2MB→約7.0MB。60日分で約20MBの見込み（推計）。Googleのスクリプトが一度に返せる大きさの上限は未確認（大きくなって読めなくなったら、曲線を直近の日数に絞る）。
- 検証：Androidテスト185件・PCテスト成功。手元のブラウザで実データの閲覧用ファイルを読み、台の詳細と5日間のスランプに線が描けることを確認。
- 利用者の許可を得て閲覧ページの公開を更新（`keyanbaitian6-cell/database-viewer` の `3453fe1`、記録ファイルが無いこと（404）を確認）。Driveの `database-viewer.json` も曲線入りで作り直した（6,939台・7.0MB）。

## 2026-09-27：妥協点の見直しと修正（Android・PC・閲覧ページ）

利用者の依頼で、これまでの実装の妥協点（エラー処理の省略・データ量で破綻する所・状態管理の辻褄合わせ）を洗い出し、指示された項目を直した（3-6「アイコン長押し起動の0.5秒待ち」は利用者の判断で対象外）。

- **バックアップ済みの印（Android）**：書き出しただけでは印を付けない。共有を取りやめたら何もしない。全期間の書き出しは「バックアップを保存できましたか？」で「保存できた」を押したときだけ、書き出しを始めた時刻で `last_full_backup_export` を付ける（`AppController.confirmBackupSaved`。古い印には戻さない）。60日より前の台の片付けはこの印で決まるので、印を付ける経路を増やさないこと。
- **保存期間の基準日（Android）**：`retentionAnchor` ＝ 最新の取り込み日と今日の早い方。未来の日付の台があっても基準がずれない。明日より先の日付は保存しない（表・グラフの保存、バックアップの取り込みでは対象外に数える）。バックアップ済みの台を一度に500台超かつ全体の半分超片付けることになったら止め、結果画面で確かめてから片付ける。
- **バックアップの取り込み（Android）**：2回読む。1回目は確かめるだけ（壊れた行・同じ台の違う記録の重複でここで止まる）、2回目に1つのトランザクション（`DatabaseService.writeTransaction`）で保存。途中で失敗したら何も残らず、取り消しの控えも前のまま。進み具合を表示する。PC版の取り込みも、イベント名・台・翌日候補の記録を1回で書くようにした。
- **読めない記録（Android・PC）**：壊れた・形の違う記録が1件あっても起動・表示・採点を止めない（その台だけ飛ばし、DBには残す。Androidは結果画面に件数を出す）。書き出しでは、JSONとして壊れた行を `{"unreadable_record": 元の文字列}` に包む（取り込みでは対象外）。Androidが起動できないときは、起動エラー画面の「記録を書き出す（非常用）」でDBを読むだけで開いてバックアップを作れる（DBが新しい版でも可）。
- **失敗を黙って捨てない（Android）**：翌日候補の記録を読めなかったら結果画面に出す。バックアップの翌日候補の記録は画面用の一覧ではなくDBから書く。グラフ画像の読み込み失敗は覚えず次に読み直す。ページのURLが取れないときの取り込みは止める（押し直せばよい）。店舗・日付・機種名の欠けた表は既定値で埋めずに止める。
- **速さ（Android）**：翌日候補の計算を店舗・機種ごと・日ごとにまとめた（結果は旧版と2万台で全件一致を確認、約2〜3倍速い）。結果画面の1日ぶんの採点は `AppController.dayView` が記録の版（`revision`）ごとに使い回す（タブを切り替えても計算し直さない）。画像の読み込み（1枚平均3.3KB）は問題が無かったので変えていない。
- **翌日候補の記録（Android）**：端末には180日分だけ残す（利用者の了承）。それより古く、全期間バックアップに入れた後のものを起動時に片付ける。PC版とバックアップには全期間残る。共有用の一時ファイルは3日たったら起動時に消す。
- **状態管理（Android）**：`AppController` を `lib/app_controller.dart` に移し、画面の設定（`UiPrefs`：一時ファイル→名前変更で保存）、書き込みの順番待ち（`WriteQueue`）、画像の読み込み（`GraphPreviews`、アプリが持ち `GraphPreviewScope` で渡す）、取り消しの控え（`UndoLog`）を分けた。**書き込みは必ず `_write`（`WriteQueue`）の中で行う**。中から入り直すと止まらずに失敗し、`_commit` などを外から呼ぶと失敗する。`records` は変更できない一覧で、入れ替えるたびに `revision` が進む（画面の使い回しは `identityHashCode` ではなくこれで判定）。画面の組み立て（build）の中ではファイルに書かない。操作の結果の知らせ（`message`）は閉じるかタブを切り替えると消える。
- **内部ブラウザの取り込み画面**：状態を `lib/capture_flow.dart`（`CaptureFlow`）にまとめた（読み込み中・処理中（入れ子可）・ページの世代・次のページでの予定）。処理中に次のページが読み終わったときの待ちは、0.05秒ごとの見張りではなく処理が終わる知らせで待つ。決め打ちの待ち時間（20秒・3秒・0.35秒×30回）は今回は変えていない（利用者の指示外）。
- **閲覧ページ**：Driveの自動読み込みは、前に読み込んだ内容より古ければ置き換えない。新しければDriveの内容を使い、Driveに無い古い日（手で全期間を読み込んだ分）は残して足す（`ViewerData.merge`）。
- 使われていなかった旧確認画面（`TableReview`・`GraphReview`）・`autoConfirmGraph`・`graph_gate.dart` を削除。スクリーンショットのOCR（`ImportService.analyze`）も呼ばれていないが、依存関係の整理を伴うので今回は残した。
- 検証：Androidテスト158件・PCテスト110件成功、`flutter analyze` でエラーなし、PC版とAndroid版の採点一致（5,792台、v11）。
- 実機（利用者、0.5.1・versionCode 2026092706）：表の取り込み・グラフの取り込み・次の機種への自動移動はOK。全期間の書き出しで「保存できましたか？」が出て、Googleドライブに全期間（6,031台・20日分・翌日候補の記録269件）が保存されたことを確認。1日分だけの書き出しでは確認は出ない（仕様）。
- 閲覧ページは利用者の許可を得て公開を更新（`keyanbaitian6-cell/database-viewer` の `c76d554`、公開ページで版0.5.1と、記録ファイルが無いこと（404）を確認）。

## 2026-09-27：結果画面の★の意味を明示

- 選択日をDとすると、★はDまでの保存済み記録から現在計算したD+1向け候補（仮）。D-1時点で選んだD向け候補ではない。過去の日付を開いた場合も同じ。
- AndroidとiPhone閲覧ページで共通の機種一覧・表・候補カードに、この日付関係を明記した。採点や候補の計算は変更していない。

## 2026-09-27：PCブラウザの停止修正・cmd起動へ切り替え

- 実行中の旧EXEを読み取り専用で調査し、pywebviewのAPI列挙が `window.native.CreateParams` の取得で待機していることを確認。バックアップ処理に入る前に停止していた。
- `_Bridge` の内部属性をすべて `_` 始まりにし、ネイティブ画面や子プロセスをJavaScript APIの再帰列挙から外した。実際のページURLとの照合は維持。
- 利用者の希望によりPC版は正本クローンの `database/start.cmd` から起動する。ローカルの `.runtime` がなければ `py -3` を使用し、取り込みブラウザも同じPythonで正本のソースを起動する。今後のPC更新ではEXEの再ビルドは不要。
- このPCの既存DB・設定を `Documents/Codex/2026-09-24/a/work/database-main/database/data` へ引き継いだ。移行前DBの控えは同じ作業フォルダの `outputs/pre-cmd-switch-20260927`。6,015件を含む全テーブルと既存設定の一致、SQLite整合性を確認。旧保存先のDBは残し、停止していた旧ブラウザプロセスだけ終了した。今後は新しい `start.cmd` を使う（旧起動先とDBを混在させない）。
- イベントを出力できない旧PC版のJSONも原因だったため、正本の出力処理でDriveの自動バックアップ・閲覧用JSONを更新した。全バックアップのイベント14件、閲覧用は最新記録日9/26までの13件を含む。
- 検証：PCテスト108件成功。`py tests/smoke_browser_lifecycle.py` は実WebView2のローカル空ページでAPI準備→閉じる→バックアップ→イベント出力まで成功（実サイト・実データ不使用）。移行済みDBでメイン画面の初期化・正常終了も確認。

## 2026-09-27：店舗・日付別イベント名

- Android版・PC版で、日付ごとのイベント名を店舗別に設定できる（定型5種＋自由記載、解除可能）。結果・履歴・閲覧用ページの日付に表示し、採点・翌日候補の計算には使わない。
- イベントは1日1店舗につき1件の独立データで、共有バックアップと閲覧用JSONにも含める。取り込み時は未登録だけ追加し、既存イベント名と異なる場合は既存値を保持して件数を知らせる。
- 初期値：長町南店 2026-09-14〜20「4台構成」、2026-09-21〜27「超探す楽しみ」。

## 2026-09-27：閲覧ページがGoogleドライブの最新を自動で読む（利用者の選択：Googleのスクリプト）

- PC版は自動バックアップのたびに、同期フォルダ（「database共有」）へ閲覧用の軽いファイル `database-viewer.json` を書く（`core.export_viewer`：直近60日・画像と曲線なし・閲覧に使う項目だけ。実データ5,784台で2.6MB、60日分で約25MBの見込み）。
- `database-viewer.json` はバックアップではない（画像が無い）。PC版の「同期フォルダの最新を読み込む」の候補から外し、PC版・Android版とも取り込もうとすると止める（見出しの `source: pc-viewer`）。
- Google Apps Script（`database_android/tool/viewer_drive_script.gs`）が、利用者のDriveの `database-viewer.json` の中身を返すだけのウェブアプリになる（実行ユーザー：自分、アクセス：全員）。URLを知っている人は中身を読める（利用者が選んだ方式）。閲覧ページは、そのURL（`https://script.google.com/macros/s/…/exec` の形だけ許可）を端末に覚え、開くと前回の内容を出してからDriveの最新を読む。
- 設定手順は `database_android/README_ANDROID.md` の「iPhoneで見る」。利用者が `imakurudev@gmail.com`（PCのGoogleドライブと同じアカウント）でスクリプトを作ってデプロイし、iPhoneの閲覧ページに設定して動作を確認した（2026-09-27）。スクリプトの応答は `Access-Control-Allow-Origin: *` 付きのJSONで、公開ページから5,792台（19日分）を約3.7秒で読めた。スクリプトのURLは記録に残さない（URLを知る人は中身を読めるため）。

## 2026-09-27：実機での確認結果（利用者の報告）

- **Android版0.5.0（versionCode 2026092703）**：利用者が実機で動作確認し、問題なし（v11採点・60日保存・ゴミ箱・閲覧ページと共通の画面部品を含む版）。インストール済みの版はadbで確認した。
- **iPhoneの閲覧ページ**：GoogleドライブのJSONを「ファイル」アプリから選べるようになり（種類の絞り込みをやめた後）、全期間のバックアップ（PC版の `database共有/database-backup-auto.json`）で問題なく動いた。
- 最初に「60点が多い」と見えたのは、Android版で日付を1日に絞って書き出したファイル（9/26の924台だけ）を読んだため。比べる過去の記録がないと当たり・持玉が中立点になり、9/26は60.0点が37台（全期間では1台）になった。閲覧ページは、前の30日に記録がある日が3日未満だと注意を出すようにした。
- iPhoneで読むのは全期間のファイル（PC版の `database-backup-auto.json`、またはAndroid版の「すべての店舗・すべての日付」の書き出し）。

## 2026-09-27：iPhoneで見るための閲覧ページ（Web）

- 利用者の主な端末はiPhone 16で、Androidアプリ（A25）はサブ機。DriveにあるバックアップJSONをiPhoneで見られるよう、閲覧専用のWebページを作った（`database_android/lib/viewer_main.dart`、`flutter build web -t lib/viewer_main.dart`）。取り込み・保存はしない（iPhoneのSafariではサイトに取り込み用の処理を差し込めないため）。
- 採点・翌日候補・表・グラフの部品はAndroid版と同じコードを使う。共有するため、表示部品を `main.dart` から `shared_widgets.dart` へそのまま移した（動作は変えていない）。
- 読み込みは、ページの「バックアップを読み込む」から「ファイル」アプリ経由でDriveのJSONを選ぶ（利用者の選択）。ページ内のJavaScript（`web/index.html` の `databaseViewer`）が1行ずつ読み、グラフの画像と曲線を捨てて端末の IndexedDB に覚える。記録はどこにも送らない。グラフは4点からの概略図（利用者の選択）。9/26のバックアップ22.6MBが2.7MBになった。
- 公開は「見る専用ページのコンパイル済みファイルだけを入れた別の公開リポジトリ」＋GitHub Pages（利用者の選択。今のリポジトリは非公開で、無料のPagesは公開リポジトリのみ）。記録・ソースは公開しない。`noindex` 付き。
- 公開先：https://keyanbaitian6-cell.github.io/database-viewer/ （公開リポジトリ `keyanbaitian6-cell/database-viewer`、利用者の許可を得て作成）。
- **公開の手順（必ずこの順）**：`database_android` で `flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/` → `python tool/stage_viewer.py <database-viewer の clone>` → その clone でコミットしてpush。clone は `gh repo clone keyanbaitian6-cell/database-viewer C:/Users/keyan/database-viewer` のような短いパスに作る（長いパスだとgitの片付けが失敗する）。Flutterは `assets/database_seed.json`（実際の記録110件）もWeb用に同梱するため、`stage_viewer.py` がそれを外し、記録にしか無い文字列が残っていないか確かめる（残っていれば止まる）。`build/web` を直接公開しない。Git Bash で `--base-href /database-viewer/` を渡すとWindowsのパスに書き換えられてビルドが止まるので、PowerShellで実行する（または `MSYS_NO_PATHCONV=1` を付ける）。
- 初回表示は、日本語フォントをGoogleのフォント配信から読むまで数秒、文字が□になることがある。
- Android 129件成功。手元のブラウザで、読み込み・候補・台の詳細・機種の表とグラフ・保存と読み戻しを確認。iPhone実機とファイル選択は未確認。

## 2026-09-27：Android版は端末に60日分だけ残す（利用者の決定）

- 端末の容量・起動の負担を増やし続けないため、Android版は最新の取り込み日から数えて60日分だけ端末に残す（`retentionDays`）。採点は前の30日分と比べるので、直近30日分はPC版と同じ点数になる。PC版とバックアップには全期間が残る（PC版は変更なし）。
- 片付けは起動時。消すのは「すべての店舗・すべての日付」のバックアップを書き出した時刻（`last_full_backup_export`）より前に保存した台だけで、書き出していなければ消さない。画像ごと消し、ゴミ箱には入れない（バックアップにあるため）。片付けたら結果画面の上に知らせる。
- 全期間のバックアップを3日以上書き出していない（または一度も無い）と、結果画面の上に注意と「バックアップを書き出す」を出す。メニューの「前回」は全期間の書き出し日時。
- 60日より古い台をバックアップから読み込んだときは一時的な取り込みとし（`temporary_records`、DB版5）、次の起動時に片付ける。
- Android 127件成功。

## 2026-09-27：PC版の自動バックアップを内部ブラウザを閉じたときに／EXE作り直し

- 利用者の指示。PC版は表・グラフを1回保存するたびに全データを書き出していた（`auto_backup`）。記録に比例して重くなり、取り込み中に待たされるため、内部ブラウザを閉じたときに1回だけ取るようにした（`browser_import.backup_after_session`）。閉じた時点で確認画面が開いていれば、その保存が終わるのを待ってから取る。メイン画面の操作（取り込み・削除・取り消しなど）の後の自動バックアップは、回数が少ないので従来どおり。
- `bin` のEXE（`database.exe`・`database-browser.exe`）をPyInstaller 6.22.3で作り直した（9/23版にはこの数日の修正が入っていなかった）。ビルドは `build/pyinstaller/*.spec` を別フォルダへ出力し、中身に新しい処理が入っていることを確認してから差し替えた。古いEXEはごみ箱。
- PCテスト106件成功。

## 2026-09-27：粗探し（2回目）の4件の修正（Android・PC）

- **データ量で起動・バックアップが落ちる**：Androidは起動・読み直しのたびに全記録を画像込みで一度に読み（sqflite はページ分けしないと全行をJavaのメモリに溜める）、バックアップも全件を1つの文字列にしていた。→ DB版4でグラフの画像・曲線を別の列 `graph_blob` へ分け、画面用の一覧には載せない（表示する画面だけ `GraphPreviews` が読む）。一覧は300行ずつ読む。バックアップは1行1台で書き出し、1行ずつ読む（以前の1行だけの形は64MBまで丸ごと読む）。実データ5,091件で版3→4の移行を試し、全件が画像込みで元と一致、起動時に読む量は22.6MB→2.9MB。PC版も、開くときにキーだけ読む（0.059秒→0.010秒）、書き出し・読み込みを1行ずつにした。
- **消した記録を戻せない**：Androidに自動控えがなく、取り消しは1回分・メモリ上だけだった。→ Androidにゴミ箱（`trash` 表、7日間、上のバーのバックアップメニューから戻せる）。削除のほか、表の取り込み直しで外れるグラフ・グラフの取り込み直し・バックアップの競合上書きの前の内容も入る。メニューに前回の書き出し日時を表示。PC版は削除の前に、消す台を読み込めるバックアップの形で `backups/deleted/` に7日間残す。
- **ページからの偽データ**：Androidのページ連携は全フレームから呼べ（`addJavascriptInterface`）、照合番号が連番、店舗・日付をページの返事のまま信じていた。→ 照合番号を推測できない乱数に、保存前に実際のURL（店舗・`target_date`・`database_day`・`rack_no`）と照合（`pageMismatch`）、グラフが外れる表は「確認なし」の設定でも確認画面へ。PC版も実際のウィンドウのURLと照合（`page_mismatch`）。URLが取れないときは止めない（使えなくしない）。
- **候補の記録が黙って欠ける**：台の保存と候補の記録が別の処理で、失敗も見えなかった。→ Androidは `DatabaseService.applyChanges` で台・ゴミ箱・候補の記録・状態を1つのトランザクションで書く。候補の計算に失敗したら台は保存し、回数を `app_state` に残して画面とバックアップ完了の表示に出す。PC版も保存・削除・取り消しと同じトランザクションで候補を記録し（Androidと同じ形）、バックアップに含める。
- テスト：Android 124件（本物のSQLiteで動かすテストを追加、`sqflite_common_ffi` は開発用のみ）、PC 105件。

## 2026-09-26：粗探し（QA監査）で見つけた4件の修正

- **古いAPKによる記録の消失**：versionCode が `+1` のままで、古いAPKを `adb install -r` で入れられた。sqflite は `onDowngrade` が無いとDB版を黙って下げて開く（`sqflite_common` の `database_mixin.dart`）。さらに `SlotRecord` が知らない項目を保存し直しで落としていた。→ versionCode を `2026092601` に上げ、`onDowngrade` で起動を止めて理由を表示（`DatabaseTooNewException`）、知らない項目は `extra` に残して書き戻す。
- **機種名の表記ゆれによる二重登録**：揃える処理が起動時だけで、バックアップ取り込みと読み直しでは素通りだった。PC版DBの `+` 区切り8件（9/15長町南）がAndroidへ取り込まれ、同じ台が2件になっていた。→ `normalizeMachineName` を `models.dart` へ移し、取り込み・読み直し・候補の記録でも揃える。PC版も保存と取り込みで揃え、既存の `+` 区切りは開いたときに一度だけ統合する（統合前に `database.pre-machine-name-fix.sqlite3` を残す）。実データのコピーで試し、4,868件→4,860件、台の欠落0、数値の変化なし（`+` 側の `source_image` だけが引き継がれる）を確認した。
- **読み直しと保存の行き違い**：引っ張って更新（`reload`）が書き込みの順番待ちの外で動き、保存直後の一覧を古い一覧で上書きし得た。その後の表の取り込み直しや設定情報の保存が、古い一覧を元にグラフ・設定情報を消し得た。→ `reload` を順番待ちに入れ、表・グラフ・設定情報の保存と取り消しの控えは、画面の一覧ではなくDBの今の内容から作る（`DatabaseService.loadByKeys`）。
- **取得時刻の9時間ずれ**：時差付き（`+09:00`）の `captured_at` を世界標準時のまま表示し、23:30の取得を「14:30・早めの取得」と出していた（バックアップ4,614件中1,498件が該当）。→ 端末の時刻に直して表示する。
- 検証：Android 100件、PC 99件成功。行き違いのテストは、修正前の `reload` では失敗することを確かめた。

## 2026-09-26：翌日候補の独立検証と、検証用の記録

- 利用者提供のAndroidバックアップ（2026-09-26 00:33書き出し、5,099件）だけで、翌日候補（仮）が翌日のv10採点を予測できるか読み取り専用で検証。候補ロジックはPythonへ移植し、Dart実装を直接実行して採点5,091件・候補905件の全件一致を確認した。
- 主結果（翌日0:00までに取得済みの記録だけ）：予測日4日・62グループ。翌日採点できた候補187件の平均45.9、候補外573件の平均47.0。同じ店舗・機種・予測日内の差は−1.8点（ブートストラップ95%区間−5.9〜+2.3）。候補の翌日点の平均百分位は0.501でランダムと同じ。9:00締切でも、取得時刻を無視した探索（後知恵を含み得る）でも差は区間内に0を含む。
- 前回の候補外484件・平均47.9は「過去傾向を計算できた候補外台」だけの集計と一致。採点可能数4,270件（前回4,278件）は、9/15長町南の機種名 `+` 区切りの重複8件をアプリの正規化（`main.dart` `_normalizeRecords`）どおりに統合したため。
- 改良案（1位だけ・履歴2日に緩和・前日v10点が高い台・低い台・過去v10点平均）は、選定期間（取得時刻を無視、予測日9/22以前）と評価期間（0:00締切、9/23・9/24）を分けて比較。事前に決めた規則で選ばれた「1位だけ」は評価期間で−2.8点で、改善は再現しなかった。どの案も改善とは言えない。候補の選び方は変えず、データを待つ。
- 検証を後知恵なしで繰り返せるよう、Android版に次の記録を追加（採点・候補の選び方・画面は変更なし）。
  - `first_captured_at`：その台を最初に保存した時刻（時差付き）。取り込み直しで動かない。以前の記録は不明のまま空。PC版も新規保存時に付け、バックアップ取り込みでは早い方を残す。
  - `candidate_snapshots`（新テーブル、DB version 3）：一覧・グラフの保存、削除、取り消しのたびに、その機種・日付（と30日以内の後の日）の翌日候補を計算し、前回と中身が変わったときだけ時刻付きで追記する（`candidate_log.dart`）。Androidのバックアップに `candidate_snapshots` として入る。PC版はこのキーを読まずに無視する。
- 次回の検証方法：予測日Dの店舗・機種ごとに、`taken_at` が翌日0:00より前の最後の記録を「そのとき画面に出ていた候補」とする。台の入力可否は `first_captured_at` で判定する。比べる案は、事前に決めた「現行」と「前日のv10点が高い台」の2つだけ。9/26以降に0:00前に全台を取り込んだ予測日が10日前後たまってから行う（必要日数は推測）。CSVは不要で、バックアップJSONだけでよい。

## 2026-09-23：正解記録なしの運用とAndroidビルド

- 利用者の確認により、BB/RB設定候補は**正解記録なしでOK**と `SETTING_ESTIMATION.md` に明記。手入力の設定情報は任意であり、未入力を低設定ラベルにしない。正解がないため的中率は検証できない。
- AndroidリリースAPKを実SDKで `flutter build apk --release --no-pub` して成功。`database_android/build/app/outputs/flutter-apk/app-release.apk`（90,030,538バイト、2026-09-23 12:58:45、SHA-256 `B363BF5D989FA082A1DB5E4C2C966FAAD6219BB36E2EFDD0420E6160387D1A9A`）。ビルド前の変更はこの節の仕様書追記のみで、コードは前節のPC84件・Android64件成功時と同じ。実機インストールは未実施。

## 2026-09-23：BB/RB設定推測の再点検と表示修正

- 既存のメーカー確率表と、BB・RB・非当選の3分類尤度計算は維持。設定配分、実際の設定、サイトのG/ボーナス計上の一致は未確認であり、正解設定確率としては扱えない。
- 保存済みDBを読み取り専用で点検。対応機種の有効489件中、最多設定のモデル内相対重み50%以上は12件、80%以上は0件。単一番号を「推測設定」と主表示するのは過度に断定的なので、PC/Androidの一覧ではモデル内中央80%の候補範囲を先に表示し、全設定が残るときは「BB/RBでは絞り込めず」と表示する。詳細では最多適合設定とそのモデル内相対重みを補足。CSV列名もこの区別に合わせた。
- 旧「重み上位から80%」は100G・BB/RB 0回でも設定1〜6の1つを機械的に除外したため、設定順の10%〜90%分位点を含む中央範囲に変更。少ない観測量で全設定が残ることを回帰テストで確認。
- 機種名の部分一致では将来の類似型式にも既存スペックを誤適用し得たため、保存済み8表記を正規化後に6型式の完全一致で認識する。既存の有効489件はすべて引き続き認識。新しい表記・型式は資料を確認してから追加する。
- PC `python -m unittest discover -s tests` は84件成功。Androidは実SDK `C:\Users\keyan\flutter\bin\flutter.bat test --no-pub --reporter expanded` で64件成功。実SDKの `analyze --no-pub` は既存のinfo 8件、error/warningなし（infoにより終了コード1）。`flutter` だけでは0バイトの別ファイルを解決してしまう環境なので、検証時は実SDKの絶対パスを使う。
- 手入力の設定情報、100点採点、翌日候補、DBの内容は変更しない。APKビルド・インストールは今回依頼されていないため実施しない。

## 2026-09-23：ジャグラー・ハナハナの推測設定（BB/RBのみ）

- `SETTING_ESTIMATION.md` に、対応6機種のメーカー一次資料、機種別BB/RB表、計算式と解釈上の限界を記載。
- PC `database/setting_estimate.py` と Android `database_android/lib/setting_estimate.dart` に、同じ表・同じ3分類尤度計算を実装。各設定の事前重みは同一という仮定で、最も適合する設定とモデル内80%候補集合を表示。ニューキングハナハナVはメーカー表どおり設定Vで扱う。
- PCの結果・履歴・日のまとめ、Androidの結果カード・履歴・グラフ詳細・CSV共有に推測設定を追加。手入力の確定設定、既存の100点採点、翌日候補、保存済みDBは変更しない。未対応機種や0Gでは表示しない。
- PC `python -m unittest discover -s tests` は84件成功（テスト用SQLiteへの権限が必要なためサンドボックス外）。Android `flutter test` は64件成功。`flutter analyze` は既存の info 8件のみで error/warning はなし。APKのビルド・インストールは未実施。
- 公開確率とホール表示G/BB/RBの計上方法が完全一致するか、店の設定配分、実際の設定は未確認。表示は実設定の確率や翌日の予測ではない。

更新日: 2026-09-23

## 目的と対象範囲

`database` は、メルヘンワールド長町南店とスーパーメルヘンワールド幸町の **1000円46枚スロット** を、個人利用のために端末内へ保存・採点するツールです。

- 長町南店: https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info
- 幸町店: https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info
- 1000円92枚・500円92枚スロットは対象外です。
- 外部サービスへ画像・台データを送信しません。
- アクセス制限の回避、IP変更、自動操作の偽装は実装しません。

主に使うのは Android 版です。PC版もAndroid版と同じ方式（アプリ内ブラウザでの表・グラフ直接取り込み）だけをUIに残しています。スクリーンショットOCR（`screenshot_import.py`）とSelenium自動収集（`collector.py`）はPC版のメイン画面から削除済みで、モジュールとテストのみ残っています（`collector.py`はコマンドラインから単独実行可能）。

## フォルダ構成

| パス | 内容 |
| --- | --- |
| `database_android/` | Flutter製Androidアプリ。本番相当の開発対象。 |
| `database_android/lib/main.dart` | アプリの画面、履歴、取り込み後の保存処理。 |
| `database_android/lib/web_import_page.dart` | アプリ内ブラウザでの表・グラフ取り込み。 |
| `database_android/lib/scoring.dart` | 100点満点の採点ロジック。 |
| `database_android/lib/database_service.dart` | SQLite保存と機種名正規化・履歴処理。 |
| `database_android/lib/csv_export_service.dart` | CSV共有。 |
| `database_android/tool/test_web_extraction.mjs` | WebView抽出JavaScriptの回帰テスト。 |
| `database/` | Python/Tkinter製PC版。 |
| `database/browser_import.py` | PC版のブラウザ直接取り込み（表・グラフ抽出のロジックと`pywebview`セッション）。 |
| `database/graph_review.py` | スクリーンショット/ブラウザ共通の4点確認ダイアログ。 |
| `database/chrome_extension/` | 2店舗の対象画面をフルページ撮影するローカルChrome拡張（PC版アプリはもう自動取り込みしません）。 |
| `database_android/lib/backup_service.dart` | Android版のバックアップJSON書き出し/読み込み（PC版`core.py`の`export_backup`/`import_backup`と共通形式）。 |

## Android版の現在の利用手順

1. アプリで店舗を選ぶ。
2. アプリ内ブラウザで対象機種と評価日を開く。
3. 一覧ページで「この表を取り込む」を押し、OCR結果を確認して保存する。
4. 同じブラウザ内で各台のグラフを開き、「このグラフを取り込む」を押す。
5. 自動検出したゼロ線・最高点・最低点・終点を必要時だけ補正し、「採点を確定」を押す。
6. 確定後は同じ台のブラウザ画面へ戻るため、次の台へ進める。

表とグラフの取得日は、URL中の `target_date` を優先します。画面をまたいだ日付ずれを起こさないことが必須です。

PC版（`database/browser_import.py`）もほぼ同じ手順ですが、一覧の取り込みに確認画面はありません（HTML直読みのため）。表は「この表を取り込む」を押した時点でそのまま保存され、グラフだけ「このグラフを取り込む」→4点確認画面→ウィンドウ右上の「採点を確定」で保存します。

表・グラフ抽出用のJavaScriptはAndroid版のWebView抽出と同じ考え方（見出し一致での表検出、`.path-slump`/`.back-line-middle`でのSVG抽出）で書かれていますが、実装は別（Dart側は`web_import_page.dart`、Python側は`browser_import.py`の`TABLE_EXTRACT_BODY`/`GRAPH_EXTRACT_BODY`）です。ロジックを変更する場合は両方を確認してください。

**PC版の確認ダイアログは、ブラウザ（`pywebview`）と同じプロセスの別スレッドでは絶対に開かないこと。** メイン画面（`app.py`）の「ブラウザを開く」から起動される`browser_import.py`のセッションは、`pywebview`の内蔵ネイティブループをメインスレッドで動かします。当初はその中でTkinterの確認ダイアログをワーカースレッドとして開いていましたが、実機で「クリックは反応するが確認ウィンドウが一切表示されず、そのままハングする」不具合が発生しました。原因を実機で直接再現・特定した結果、`tk.Tk()`のrootを`.withdraw()`（または`.iconify()`）した状態で子`Toplevel`が`.transient(root)`を呼ぶと、このWindows/Tk環境では**ウィンドウの生成自体は成功するのに二度と描画されない**という組み合わせでした（`messagebox`など`.transient()`を使わないダイアログは問題なく表示される）。
現在は、表・グラフの確認ダイアログを`browser_import.py`が`subprocess.Popen`で都度起動する**完全に別のプロセス**（`--confirm-table`/`--confirm-graph`引数、`app.py`本体と同じ「Tkinterだけが動く1プロセス」という実績のある構成）に切り出して解決しています。ブラウザ側は受け取ったデータを一時JSONに書き出してこの別プロセスを起動するだけで、自分はすぐ次のクリックを待てる状態に戻ります。`_stub_root()`（`browser_import.py`）が、その別プロセス内でも親ウィンドウを「隠す」のではなく「1×1・枠なしのまま表示状態を保つ」ことで、上記の`.transient()`問題を避けています。Tkinterの確認ダイアログをどこかに追加する場合、このパターン（親を`withdraw()`しない）を踏襲してください。

## 採点仕様（2026-09-21-v9）

現在の最終仕様は [SCORING_POLICY.md](SCORING_POLICY.md)。利用者の最終決定・実装依頼に基づく変更。
過去の変更履歴にあるv5〜v7の配点や「設定示唆」「翌日の参考指数」の説明より、v9を優先する。

- 当たり頻度60点・最大持玉20点・終点10点・維持10点。回転数の直接加点なし。
- 同店・同機種の過去30日、回転数が近い台だけで比較。当日・未来を除外。
- 比較順位を `(G/(G+1500) * n/(n+20) * d/(d+3))^(1/3)` で中立へ縮約（v9で積から相乗平均へ）。係数は設計値で設定確率ではない。
- 最大持玉は、枚数による点（19,000枚のコンプリート上限で満点）が順位を上回ればそちらを採る。引き上げ専用。
- 欠測項目は内訳を未評価のまま合計だけ中立補完し、暫定点と欠測幅を表示。0Gは未稼働。
- 「信頼度」の断定をやめ、観測量・比較件数・日数を併記。過去傾向は当たり頻度の同日内順位を日ごとに集約。
- 採点は都度再計算。保存データ・画像・旧レポートは削除しない。Androidは変更済みソースのみ、ビルドとインストールは利用者が指示するまで行わない。
- PC60テスト、Android24テスト成功。659件の共通形式入力で両採点エンジンを照合済み。勝率や設定推定の妥当性の検証ではない。

## 実装上の重要事項

- 機種名では `+` と空白を同じ扱いに正規化します。既存データ移行時に別機種として重複させないでください。
- 表から存在しない台番号を作らないこと。同じ台番号の異なる内容を発見した場合は、黙って削除・統合せず利用者へ確認できる状態にします。
- 連続する台の数値が同じでも、別台として保存します。未稼働台を自動削除してはいけません。
- グラフの自動検出は、まず利用者が確認してから保存します。検出・採点ロジックを変えた場合は、複数の上昇・下降・未稼働グラフで確認します。
- WebViewの表抽出はJavaScript channel `DatabaseExtraction` 経由です。非同期の `fetch` 結果を `runJavaScriptReturningResult` だけで受け取る実装に戻さないでください。
- URLによる取得対象は2店舗だけです。対象外のURLを許可しないでください。
- 共有機能はCSVの端末共有シートを使います。データの自動送信やメール自動送信は実装しません。
- PC版とAndroid版のデータ共有は、`database-backup`形式のJSONファイルを介した手動共有（Google Driveの同期フォルダやAndroidのファイル選択経由）です。どちらのアプリもGoogle Drive APIやOAuthには接続しません。バックアップ取り込みで店舗・日付・機種・台番号が一致し、かつ総回転数/BB/RB/最大持玉のいずれかが既存記録と異なる場合は、自動で上書きせず利用者の確認画面（PC版`BackupConflictsDialog`／Android版`BackupConflictsPage`）に必ず出してください。

## 検証

Android版は `database_android` を作業ディレクトリにして実行します。

```powershell
node tool/test_web_extraction.mjs
flutter test
flutter analyze --no-pub
flutter build apk --debug --no-pub
```

`flutter test` は採点ロジックに加え、`test/backup_service_test.dart` でバックアップの新規追加・数値競合の非自動上書き・グラフのみ追加・対象外行のスキップ・PC版形式の読み取りを検証します。

実機へ入れる場合は、接続済み端末を確認したうえで、生成された `build/app/outputs/flutter-apk/app-debug.apk` を `adb install -r` で更新します。実機確認では、表取り込み・グラフ取り込み・日付・機種名・台番号・採点・履歴・CSV共有・バックアップの共有/読み込みを確認します。

PC版のテストは `database` を作業ディレクトリにして実行します。

```powershell
python -m unittest discover -s tests -v
```

このテストは表抽出・グラフ抽出・`target_date`優先・機種名引き継ぎ・未稼働台/同一値連続台の非削除・重複台番号エラー・バックアップの書き出し/読み込み（新規追加・数値競合の非自動上書き・グラフのみ追加・対象外行のスキップ）の検証を含みますが、`pywebview`で実サイトを開く部分（利用規約同意・実際のHTML/SVG構造との一致）と、実際のGoogle Driveフォルダ経由でのファイル共有操作はカバーしません。そこは人が対象サイト・Google Driveを操作して確認してください。

## 共有するときに含めるもの

共有元にはこのファイル、`database/`、`database_android/` のソースを含めます。次は共有から除外します。

- `database_android/build/`、`.dart_tool/`、`.idea/`
- `database_android/*.png` の動作確認スクリーンショット
- `database_android/*.sqlite3` の実機から取得した履歴データ
- `database/.runtime/`、`database/.venv/`、`database/__pycache__/`
- `database/data/`、`database/reports/`、`database/tmp*/` のローカル生成物

スクリーンショット・SQLite・CSVには利用者の保存済みデータが含まれうるため、共有する場合は利用者が内容を確認して判断します。

## 現在の状態

2026-09-17時点で、Android実機にデバッグAPKを更新済みです。表取り込みとグラフ取り込みの修正後、利用者が動作を確認しました。2026-09-18には、履歴の台番号タップからスランプグラフを開く画面を追加しました。以後に保存するグラフは縮小画像と4点座標を保存し、既存の画像未保存記録は4点から復元した概略グラフを表示します。

2026-09-18、PC版にもAndroid版と同じ「アプリ内ブラウザで表・グラフを直接取り込む」方式を追加しました（`database/browser_import.py`、`database/graph_review.py`、`database/core.py`の`measurement_preview`系、`database/app.py`の「ブラウザで取り込む（推奨）」ボタン）。表抽出・グラフ抽出・`target_date`優先・機種名引き継ぎ・重複/未稼働台の扱いに関する単体テストを追加し、`python -m unittest discover -s tests -v`は29件全て成功しています。ただし`pywebview`で実際に対象サイトを開いての取り込み（利用規約同意画面や実際のDOM/SVG構造との一致）は今回未確認です。スクリーンショットOCR・Chrome拡張・Selenium自動収集は互換用としてそのまま残しています。

同じく2026-09-18、PC版とAndroid版の間でデータを共有するバックアップ機能を追加しました。両アプリともGoogle Drive APIやOAuthには接続せず、`database-backup`形式のJSONファイルをGoogle Driveの同期フォルダ経由などで手動共有する方式です（PC版`core.py`の`export_backup`/`import_backup`、Android版`lib/backup_service.dart`、PC版`app.py`の「バックアップ（Google Driveなどで共有）」、Android版AppBarの雲アイコンメニュー）。店舗・日付・機種・台番号が一致しても総回転数/BB/RB/最大持玉のいずれかが食い違う記録は自動で上書きせず、PC版`BackupConflictsDialog`・Android版`BackupConflictsPage`で個別に確認してから反映します。PC版は`python -m unittest discover -s tests -v`が35件全て成功、Android版は`flutter test`が8件全て成功、`flutter analyze --no-pub`はエラーなし（既存の軽微なlint infoのみ）、`flutter build apk --debug --no-pub`も成功を確認しています。ただしGoogle Driveフォルダを介した実際のファイル共有操作（Drive for Desktopでの同期、AndroidのファイルピッカーからのDriveファイル選択）は今回未確認です。

2026-09-18、利用者の実機テストでPC版ブラウザ取り込みが「クリックは反応するが確認ウィンドウが出ずそのままハング」する不具合が見つかりました。`computer-use`で実機を直接操作して再現・特定した結果、原因は上記「PC版の確認ダイアログ」の節に記載した`root.withdraw()`＋`Toplevel.transient()`の組み合わせでした。`browser_import.py`を確認ダイアログごとに別プロセスを起動する構成に作り直し（`_confirm_table`/`_confirm_graph`/`_stub_root`）、実機で表・グラフとも取り込みが成功することを確認しました。あわせて、利用者からのフィードバックを反映：

- 表の取り込みは確認画面なしでそのまま保存（HTML直読みでOCRのような誤読がないため）。旧`TableReview`クラス（screenshot経由の確認用）はPC版UIから削除したOCR/Selenium系ハンドラと合わせて`app.py`から削除しました（`screenshot_import.py`/`collector.py`モジュール自体と既存テストは維持）。
- グラフ確認ダイアログの「採点を確定」ボタンをウィンドウ右上へ移動（`graph_review.py`）。ブラウザ側の取り込みボタンも右上にあり、往復距離を短くするため。
- PC版メイン画面（`app.py`）から「スクリーンショットから取り込む」「ブラウザ自動取得（試験中）」のUIセクションと対応するハンドラ関数（`begin_table`/`begin_graph`/`save_table`/`table_file`/`table_clipboard`/`graph_file`/`graph_clipboard`/`process_next_download`/`watch_downloads`/`collect`など）を削除し、「ブラウザで取り込む」「バックアップ」「結果・履歴」の3セクションのみに簡略化しました。`GRAPH_DOWNLOAD_RE`/`LIST_DOWNLOAD_RE`/`decode_machine_token`は既存テストのために`app.py`に残しています。

PC版は`python -m unittest discover -s tests -v`が35件全て成功。実機での表・グラフ取り込み成功と、新UIレイアウトの表示は`computer-use`で目視確認済みです。

2026-09-18、PC版のブラウザ直接取り込みに、店舗を切り替える導線がまったく無いことが判明しました（`browser_import.py`の内蔵ブラウザは`DEFAULT_START`で長町南店に固定され、`pywebview`のウィンドウ自体にアドレスバーが無いため、幸町店へ移動する手段がコード上どこにもありませんでした）。`OVERLAY_JS`のカード上部に、現在と反対の店舗を開く切り替えボタンを追加しました（`STORE_URLS`/`STORE_LABELS`をJSへ埋め込み、`location.href`で遷移するだけ）。

続けて、利用者が実際に幸町店の一覧で「この表を取り込む」を試したところ、以下の順で問題が見つかり修正しました（いずれも実サイトのDOMに対する動作はunittestの対象外だったため、実機テストで初めて発覚）：

1. **見出し行の不一致**：幸町の一覧表は列見出しに並び替え用の▲▼が付いており（同じセル内、または矢印だけの別行として）、`TABLE_EXTRACT_BODY`の「1行目が`HEADERS`と完全一致」という前提が崩れて一覧ごと弾かれていました。矢印・空白を除去してから比較し、見出し行を「1行目固定」ではなく「内容が一致する行を探す」方式に変更。矢印だけの行はデータ行として扱わないようにしました。
2. **列数そのものが違う**：上記を直しても幸町だけ失敗が続いたため、失敗時にページの構造（表ごとの行数・列数・見出し一致・`<a>`/`<button>`数・先頭行の内容）をエラーメッセージに含める診断ログを追加。これにより、**幸町店の一覧には「最大持玉」列が構造的に存在しない**（長町南は7列、幸町は6列）ことが判明しました。`collector.py`に`HEADERS_NO_MAX_HOLD`（末尾の最大持玉を除いた6列）を追加し、`parse_table`がどちらの列構成でも受け付け、無い場合は`max_hold=None`として保存するように変更（個別グラフページ側の`.info_max_mochidama`から後で補われる想定）。
3. **`max_hold`キー自体が無い行でのKeyError**：`Store.save()`はNone値のフィールドをマージ対象から除外するため、`max_hold=None`で保存した行はDB上で`max_hold`キー自体を持ちません。`core.py`の`report()`が`r['max_hold']`と直接アクセスしていた箇所（一覧表の素データ列）でKeyErrorが発生。`r.get('max_hold')`を使い、無ければ「—」を表示するよう修正しました。

`tests/test_database.py`に、6列ヘッダーの受理（`test_table_without_max_hold_column_is_accepted`）と、`max_hold`キーが無い行での`report()`実行（`test_report_handles_a_row_with_no_max_hold_at_all`）のテストを追加。`python -m unittest discover -s tests -v`は37件全て成功しています。またJS抽出ロジック自体は、幸町の実構造（矢印付き6列見出し）を模した疑似HTMLをブラウザで実行して`matrix`/`build_table_rows`まで正しく通ることを確認済みです。上記の一連の修正後、利用者が実機で幸町18台の取り込みに成功したことを確認しました。

2026-09-18、PC版の結果ページ（`core.py`の`report()`、「選んだ機種の結果を開く」で開く画面）が「見づらい」との指摘を受け、利用者から提示されたApple系デザイントークン（`C:\Users\keyan\amazon\Apple.md`：Frost背景`#f5f5f7`、Carbonテキスト`#1d1d1f`、Apple Blue`#0071e3`は塗り潰しボタン・選択状態専用、Link Blue`#0066cc`はテキスト/アウトライン用、980pxの完全ピル、8px角丸カード、影なし・ヘアラインボーダー`#d2d2d7`）を参照してデザインを刷新しました。上部にKPIカード（台数・合計点確定・平均・最高）を追加し、15列の生表はヘアラインで「表示データ／得点内訳／総合／参考」をグループ見出しでまとめ、合計点は緑/黄/赤の信号色ではなく「80点以上＝塗り潰し青バッジ、60点以上＝アウトライン青バッジ、それ以外＝グレーバッジ」という青一色の濃淡だけで表現。状態・注意はピル型タグに、グラフはクリックで拡大するモーダル表示に変更しました。実データ（幸町18台）で生成したHTMLをブラウザで目視確認済み、既存テスト37件も成功しています。この見た目変更は`report()`のみが対象で、`history_report()`（過去の記録を見る）は未着手です。

続けて、同じApple系デザインをAndroid版にも適用しました。`database_android/lib/theme.dart`を新規作成し、上記と同じ配色トークン（`AppColors`）と`ThemeData`（`buildAppTheme()`：Card/AppBar/入力欄/ボタン/Chip/NavigationBar/Checkbox/SnackBarを一括でFrost背景・ヘアラインボーダー・完全ピル・影なしに統一）、および得点バッジ用の`ScorePill`ウィジェット（`scoreTier()`で80/60点を境に高=青塗り、中=青アウトライン、低=グレーを判定）を追加。`main.dart`の`ScoreCard`（結果一覧の各台カード）をこの`ScorePill`に置き換え、`MetricCard`/`Notice`/`EmptyState`/`EditableRowCard`/グラフ再構成キャンバスに残っていた旧配色（teal系シード色、`Colors.blueGrey`、黄色い注意書き背景など）を新トークンに統一。`web_import_page.dart`の通知テキスト色も旧teal色からLink Blueに変更しました。4点ピッカー（ゼロ線・最高点・最低点・終点）の識別用マーカー色（赤・黄・水色・緑）は機能上の区別が必要なため意図的に維持しています。グラフ確認画面自体のレイアウト・グループ化（PC版で行った日付単位のバックアップ確認画面など）はAndroid側には移植しておらず、あくまで配色・形状のデザイン統一のみです。`flutter analyze --no-pub`は既存の軽微なlint infoのみでエラーなし、`flutter test`は8件全て成功、`flutter build apk --debug --no-pub`も成功を確認しています。実機での見た目確認は今回未実施です。

2026-09-18、利用者がAndroid版の実機で幸町の一覧を試し、「PC版で直した最大持玉なし問題がAndroid側では直っていない」との指摘を受けました。PC版とAndroid版は表・グラフ抽出のロジックが別実装（`database/browser_import.py` vs `database_android/lib/web_import_page.dart`）のため、PC側の修正はAndroidには反映されていませんでした。Android側で以下を修正：

- `web_import_page.dart`の`_extractTableScript`（一覧抽出JS）が見出し行に「最大持玉」列を必須としていたため（`index.max_hold === undefined) continue;`）、幸町の6列一覧はテーブル自体を検出できずにいました。最大持玉を必須列から外し、無ければ`max_hold: null`のまま行を採用するように変更。台番号・BB・RB・総回転数のみを必須に。
- `_extract()`の`item['max_hold'] as int`（非null前提のキャスト）を`as int?`に変更。これを直さなければ、たとえJS側が直っても保存時に型エラーで落ちていました。
- `EditableRow.maxHold`（`import_service.dart`）・`SlotRecord.maxHold`（`models.dart`）を`int`から`int?`へ変更し、`SlotRecord.fromJson`/`toJson`をnull許容に更新（`toJson`は値がある時だけキーを出力、PC版の`export_backup`と同じ「無ければキー自体を書かない」形式に合わせた）。
- `scoring.dart`の`scoreRecord`を、当該行および比較対象（reference/provisionalReference）の`maxHold`がnullの場合を除外して計算するよう修正（PC版`core.py`の`score()`と同じ「値が無ければ比較データ不足の理由を付けて保留」というロジック）。
- `backup_service.dart`の競合判定（`differs`）で、`maxHold`は両側に値がある場合のみ比較するよう修正（片方がnullなだけで誤って「食い違い」と判定しないように、PC版`plan_backup_import`と同じガード）。
- `csv_export_service.dart`・`main.dart`内の`最大持玉`表示箇所で、null時に文字列`"null"`がそのまま表示されないよう`?? '—'`等でガード。
- グラフ確認画面（`GraphReview.save()`／`AppController.saveGraph()`）の`maxHold`必須入力はそのまま維持（一覧に無くても個別グラフページの表示から埋められる、またはユーザーが手入力できるため、PC版より寛容な設計として意図的に維持）。
- 旧スクリーンショットOCR用の`TableReview`/`RowControllers`（`main.dart`、現在UIから到達不能な死んだコード）も型整合のため合わせて更新。

`test/scoring_test.dart`に最大持玉なしでもクラッシュせず得点計算できることを確認するテストを、`test/backup_service_test.dart`に片方だけ最大持玉が無い場合は競合と判定されないことを確認するテストを追加。`flutter test`は10件全て成功、`flutter analyze --no-pub`は既存の軽微なlint infoのみでエラーなし、`flutter build apk --debug --no-pub`も成功を確認しています。実機での動作確認（幸町の一覧が実際に保存できるか）は利用者による再確認待ちです。

2026-09-18、バックアップの書き出し範囲について確認・要望がありました。従来はPC版が日付のみ指定可能で店舗は常に両店舗まとめて書き出し、Android版は日付・店舗いずれの指定も無く常に全件（全店舗・全日付・全機種）を無条件に書き出す仕様でした。両OSに店舗・日付の両方を指定できるよう変更：

- PC版（`app.py`）：「バックアップを書き出す」の隣に「店舗」プルダウン（すべての店舗／長町南店／幸町店）を追加し、既存の「日付」プルダウンと合わせて2軸で絞り込めるようにしました。店舗を切り替えると日付候補もその店舗のものに絞り込まれます（`core.py`の`Store.days_for(store)`を再利用）。`export_backup(db, path, location=location, day=day)`のように両方渡すよう変更。
- Android版（`main.dart`）：「バックアップを共有（書き出し）」を押した際に、店舗・日付を選ぶダイアログ（`_BackupExportDialog`）を新規追加してから書き出すように変更（従来は確認なしで即座に全件書き出していました）。`AppController.exportBackup({String? store, String? day})`で`records`を絞り込んでから`BackupService.export()`に渡します。

`flutter analyze --no-pub`・`flutter test`（10件）・`flutter build apk --debug --no-pub`、PC版`python -m unittest discover -s tests -v`（37件）いずれも成功。両OS間の相互互換性（PC↔Android、最大持玉あり/なし混在データ含む）は本日別途、実データのバックアップJSONをAndroid側のロジックに直接読み込ませて確認済みです。

2026-09-18、利用者から「グラフを1台ずつ取り込む作業が大変なので、マウス操作のマクロ（人並みの速度に抑えれば問題ないはず）をPythonで組んでほしい」という依頼がありました。**これは実装していません。** 幸町店の利用規約に「(16) 当社及び株式会社プロテラスがスクレイピングと判断し、またはスクレイピングに類すると判断し、不当にデータを収集したりアクセスする行為」という禁止条項があることを確認済みで、速度を人間並みに抑えても「人が都度クリックする」から「プログラムが連続操作する」への変化そのものは解消されないと判断したためです。むしろ検出を避けるために速度を人間に似せる設計は、意図的な自動化検知の回避（detection evasion）に当たるため、このプロジェクトが一貫して守ってきた「同意操作の自動化はしない」「取り込みは1クリック＝1回の明示的な人の操作」という原則に反すると利用者に説明し、了承を得ています。今後この方向の依頼が来た場合も、同じ理由で自動巡回・自動連打の実装は避けてください。

代わりに、人の操作を都度必要としたまま摩擦だけを減らす2点を実装しました：

1. `database/graph_review.py`の`PointsPickerDialog`に、Enterキーで「採点を確定」、Escキーで「キャンセル」のショートカットを追加（マウスをボタンまで運ぶ手間を減らすだけで、クリック自体は引き続き人が行う）。
2. `database/browser_import.py`のオーバーレイに「次の未取り込み台へ」ボタンを追加。`_Bridge.next_ungraphed_rack()`が、既に取り込んだ一覧の中からグラフ未取得の台を探し、**サイト自身が発行したその台のリンク（`detail_url`、一覧取り込み時に保存済み）**を返す。押すたびに1台分だけ移動し、取り込みボタンは別途ユーザーが押す必要がある（自動連打はしない）。サイト側の「<279番台 280番台>」ページャーを何度もクリックする手間だけを省く設計。

`tests/test_database.py`に`test_next_ungraphed_rack_skips_graphed_racks_and_wraps_around`を追加（既取得台のスキップ・末尾からの折り返し・該当なしの3パターン）。`python -m unittest discover -s tests -v`は38件全て成功。オーバーレイJSの新ボタンも、モックした`window.pywebview.api`に対してブラウザ上で実際にクリックし、正しいURLへ遷移することを確認済みです。

2026-09-18、上記に続けて、利用者から更なる時短の要望があり、以下4点を追加実装しました（いずれも「1台ごとに人が確認・確定する」という原則は変えていません）：

1. **確認ウィンドウのフォーカス強制**：`browser_import.py`に`_bring_to_front()`を追加。グラフ・表の確認ウィンドウは別プロセスとして開くため、Windowsの仕様で前面に来ずキーボード操作（先日追加したEnter/Escのショートカット含む）が効かないことがあった。`-topmost`を一時的に立てる定番の回避策で強制的に前面へ出すようにした。
2. **保存後の「保存しました」ポップアップを廃止**：`_confirm_table`/`_confirm_graph`とも、判断を伴わない成功通知のOKクリックをなくし、`_write_advance_signal()`で非同期にブラウザ側のオーバーレイへメッセージを渡す方式に変更（詳細は3を参照）。
3. **確認後の自動遷移**：グラフを確定した瞬間、自動でそのラック向け「次の未取り込み台」のページへブラウザが移動するようにした。技術的には、確認ダイアログは別プロセスなので、`_write_advance_signal()`が一時ファイル（`database-browser-advance-signal.json`、OS一時フォルダ）へ`{message, next_url}`を書き込み、`run_session()`内の新しいバックグラウンドスレッド（`webview.start(func=watch_advance_signal, ...)`）が0.35秒間隔でこれを監視し、見つけたら`window.evaluate_js()`でメッセージをそのページの`localStorage`に積んでから`window.load_url(next_url)`を呼ぶ。**変わらない点**：グラフ1枚ごとに「取り込みボタンを押す」「4点を目で確認する」「Enterで確定する」という人の判断は今まで通り必須。変わったのは、確定した直後に発生していた「次の未取り込み台へ」ボタンを押す一手間が自動化されただけ（これは判断を伴わない機械的な画面遷移のため）。
4. **進捗表示**：`_Bridge.next_ungraphed_rack()`のレスポンスに`remaining`（未取得台数）を追加。「次の未取り込み台へ」ボタン・自動遷移のどちらでも「◯番台へ移動します（残り◯台）」を表示する。ページ遷移をまたぐメッセージ表示は、`localStorage`の`database-last-status`キーに書き込み→次のページの`install_overlay`実行時に読み出して消費、という仕組み（同一オリジン内のナビゲーションでは`localStorage`がそのまま引き継がれることを利用）。

なお、この一連の依頼の直前に、利用者から「グラフ取り込みをマウスマクロで完全自動化してほしい（速度を人間並みに抑えれば大丈夫では）」という依頼がありましたが、**これは実装していません**。幸町店の利用規約に「(16) 当社及び株式会社プロテラスがスクレイピングと判断し、またはスクレイピングに類すると判断し、不当にデータを収集したりアクセスする行為」という禁止条項があること、および速度を人間に似せる設計はサイト側の自動化検知を意図的に回避する行為（detection evasion）に当たり、速度を落としても「人が都度クリックする」から「プログラムが連続操作する」という性質自体は解消されないことを理由に断り、利用者の了承を得ています。上記4点はいずれも「1台ごとに人が明示的に判断・確定する」という一線を保ったまま、機械的な手順（フォーカス移動・ページ遷移・ボタンクリック）だけを削減する設計です。今後同種の「自動巡回してほしい」という依頼が来た場合も、この一線は動かさないでください。

`python -m unittest discover -s tests -v`は引き続き38件全て成功。JS側は、`localStorage`経由のステータス引き継ぎ（別ページへの遷移後にメッセージが正しく表示され、1回読んだら消えること）と「次の未取り込み台へ」ボタンの遷移を、モックした`window.pywebview.api`に対してブラウザで実際に動かして確認。Python側も`_write_advance_signal`/`_advance_signal_path`の書き込み・読み取り往復を確認済みです。ただし`run_session()`内の実際のバックグラウンドスレッド（`webview.start(func=...)`）とpywebviewの実ブラウザ間の統合動作は、表示環境が必要なため今回unittestではカバーしておらず、実機での確認が必要です。

2026-09-18、利用者から自動遷移（上記の3番目の項目）が実機で動かないという報告があり、原因を調査しました。`browser_import.py`の`watch_advance_signal()`（バックグラウンドスレッド）が`window.load_url(next_url)`を呼んでいましたが、`webview`のedgechromiumバックエンド（`.runtime/Lib/site-packages/webview/platforms/edgechromium.py`）を確認したところ、`evaluate_js()`は`self.webview.Invoke(...)`でUIスレッドへ安全にマーシャリングしているのに対し、`load_url()`は`self.webview.Source = Uri(url)`とWebView2部品のプロパティへ**スレッドをまたいで直接**書き込んでいました。バックグラウンドスレッドからのUI部品直接操作はWinForms/WPFの原則違反で、例外も出さずに黙って何も起きません（コンソールにエラーが出ない、という報告と一致）。修正として、`load_url()`の代わりに`window.evaluate_js('location.href = ' + json.dumps(next_url))`でスレッド安全な経路から同じ遷移を行うよう変更しました。利用者からは「取り込みボタンの位置改善で困っていないので急がなくてよい」との回答があり、優先度は下げつつ修正は反映済みです。実機での再検証は利用者判断待ちです。

2026-09-18、利用者から「採点方法を見直すべきか、プロスロッターとして再検討してほしい」という依頼を受け、配点を見直しました。検討の要点：

- 当初提案した「終点マイナス時のペナルティ強化」は、利用者から「今の遊技環境では高設定でも普通に負ける日がある。回転数が伸びていること自体が結果によらず高設定を示唆する」という指摘を受けて撤回しました。
- 代わりに、このツールの主目的を「(a) この台番号は高設定っぽいか＝また狙う価値があるか」（設定示唆）と「(b) 今日この台を打ったら実際どうだったか」（実戦結果）のどちらに寄せるか利用者に確認したところ、**(a) 設定示唆**という回答でした。
- (a)の場合、終点・維持（当日の結果のみで、他の台・他の日との順位比較を一切していない）が5指標の中で最も設定示唆として信頼性が低いという結論になり、比重を下げました。

新配点（100点満点）：回転数50点（変更なし）・最大持玉20点（変更なし）・**当たり頻度10→20点**・**終点10→5点**・**維持10→5点**。PC版`core.py`にMAX_GAMES_SCORE等の定数を新設し、`VERSION`を`2026-09-15-v5`から`2026-09-18-v6`へ更新（既存データとの計算版の違いが分かるように）。Android版`scoring.dart`にも同じ定数（`maxHitsScore`等）を追加し、両OSで配点を一致させました。`report()`の説明文・列見出し、Android版のスコアチップ表示（`main.dart`）も新配点に合わせて更新。

既存テストの期待値も再計算して更新：PC版`tests/test_database.py`（`test_graph_linear_ratio_and_quantization`、`test_provisional_score_uses_same_day_and_shrinks_rank`）、Android版`test/scoring_test.dart`（暫定点テスト、303番台の実データテスト）。手計算ではなく実際にテストを流して出た実測値を期待値として採用しています。PC版`python -m unittest discover -s tests -v`は38件、Android版`flutter test`は10件、`flutter analyze --no-pub`はエラーなし、`flutter build apk --debug --no-pub`も成功を確認済みです。実データでの新配点の見た目（結果ページ・履歴ページでの実際の点数感）は、利用者による確認待ちです。

### 「次の未取り込み台へ」が1台目で「未取り込みなし」と出る不具合の修正

原因は2つ。(1) グラフページURLに`machine_name`が無い場合に機種を特定できず、対象0件になっていた。`_Bridge.next_ungraphed_rack()`は機種が空なら台番号から機種を逆引きするようにした。(2) 古い取り込み（スクショOCR・Android由来）の行には`detail_url`が無く、次の台が分かっても移動先が無かった。この場合は`reason: 'no_link'`を返し、オーバーレイと`_confirm_graph`の通知で「個別台リンクがないので機種別一覧から開いてください」と正直に表示する（移動したようには見せない）。`no_link`のテストを追加。PC版38件・Android版10件パス。反映にはブラウザウィンドウの開き直しが必要。

### 手間削減4点（同期フォルダ・自動バックアップ・前回選択の復元・この日のまとめ）

- PC版`core.py`：`load_settings`/`save_settings`（`data/settings.json`）、`auto_backup`（同期フォルダへ固定名`database-backup-auto.json`を上書き。未設定・失敗時は何もせず例外も出さない）、`latest_backup_file`（自動コピー自身は除外して最新のバックアップJSONを返す）、`summary_report`（両店舗の上位5台と取り込み状況のHTML）。
- PC版`app.py`：「同期フォルダ」欄（指定／最新を読み込む）、書き出しは同期フォルダ設定時はダイアログなしでそこへ保存、店舗・日付・機種の選択を`settings.json`に記憶、「この日のまとめ（両店舗）」ボタン。`browser_import.py`は表・グラフ保存後と`app.py`の取り込み・削除後に`auto_backup`を呼ぶ。
- Android版`main.dart`：結果画面の店舗・日付・機種を`ui_state.json`（アプリ文書フォルダ）に記憶、結果画面に`DaySummaryCard`（上位5台と保留・暫定・グラフ未取得の数。行タップでその機種へ移動）。AndroidはDriveの特定フォルダを直接読めないため、同期は従来どおり共有シート／ファイル選択のまま。
- テスト：PC版39件、Android版10件パス、`flutter build apk --debug`成功。GUIは利用者確認待ち。

### Android「この日のまとめ」の台タップで詳細表示

`DaySummaryCard`の行タップは、機種切替ではなく`SavedGraphPage(record, score)`を開く。新設`RackStats`が合計点・当たり回数（BB+REG）・当たり確率（1/総回転÷当たり）・総回転・BIG/REG/最大持玉・点数内訳を表示し、その下に保存済みグラフ（未保存なら案内）を出す。`flutter analyze`/`test`（10件）/デバッグAPKビルドOK。PC版`summary_report`も同様に、行クリックで当たり回数・当たり確率・点数内訳・グラフのモーダルを表示（`data-detail`属性に詳細HTMLを埋め込み）。テスト39件OK。

### 取り込み漏れ一覧と「グラフ確認画面を省く」設定

- 取り込み漏れ：PC版`core.missing_graphs`（日付・店舗ごとに、一覧はあるがグラフ未取得の台を機種別に列挙。`detail_url`が無い台数も返す）を「この日のまとめ」HTMLに`グラフ未取得の台`として表示し、リンクが無い台には「機種別一覧を取り込み直すと『次の未取り込み台へ』が使える」と案内。Android版は`DaySummaryCard`に同名の折りたたみ欄を追加（機種別の台番号）。
- 確認画面の省略（PC版のみ・既定オフ）：`app.py`のチェックボックス→`settings.json`の`auto_confirm_graph`。有効時、`browser_import._confirm_graph`が`graph_auto_save_blockers()`で次を全て確認し、1つでも外れたら従来の確認ダイアログ（理由をcaptionに表示）：保存済みグラフなし／一覧と詳細画面の数値が一致／総回転数1以上／点10個以上／曲線の開始がゼロ線±2／最終xが幅の80%以上／終点がゼロ線±1より離れている。通過時は`graph_measurement_result()`（ダイアログと同形式）で保存し、通知に回転数・BIG・REG・終点の向きを表示。しきい値の根拠は`observed_graphs.json`の実測14台（開始yはゼロ線から0.5、最終x=幅いっぱい）で、全台が通過することをテストで固定。Android版のグラフ確認画面は未変更。
- 検証：PC版43件（自動保存のON/OFF・ゲート失敗時にダイアログが出て保存されない・成功時は保存されダイアログが出ないことを`_confirm_graph`実行で確認）、Android版10件、デバッグAPKビルドOK。実サイトでの動作は利用者確認待ち。

### 「次の未取り込み台へ」が常に「すべて取り込み済み」になる不具合（真因）

先の「古いデータにリンクがない」という説明は不正確だった。真因は、`_confirm_table`が保存行を作り直す際に`detail_url`を渡していなかったこと（`parse_table`は返していたが保存されず、実DBの幸町・長町とも全行で欠落）。あわせて、機種別一覧ページのURLに`target_date`が無いと日付がnullになり`unknown_page`が返るが、JSのelse節が「すべて取り込み済み」と表示していた。修正：`detail_url`を保存／JSで日付をURL→一覧内リンク→日付選択欄の順に取得／メッセージを理由別に分離（`all_done`のときだけ「取り込み済み」）。テスト追加（表保存でリンクが残り、`next_ungraphed_rack`が移動先を返す）。PC版44件OK。既存の保存済み行にはリンクが無いので、機種ごとに一覧を取り込み直す必要がある（数値が変わっていれば既存グラフは無効化される既存仕様）。

### Android版「グラフの確認画面を省く」設定

`lib/graph_gate.dart`（`graphAutoSaveBlockers`、PC版と同じ条件・しきい値）と、取り込み画面のスイッチ（既定オフ、`ui_state.json`の`auto_confirm_graph`に保存）。ONで、SVGから読んだ線データ（`GraphDetection.curve/baselineY`を追加）が全条件を通れば`saveGraph`で直接保存しスナックバーに回転数・BIG・REG・終点の向きを表示。外れた台は従来の確認画面の上に理由を表示。スクリーンショット由来のグラフは常に確認画面。`test/graph_gate_test.dart`が`../database/observed_graphs.json`の実測14台の通過と、疑わしい場合の拒否を検証。flutter test 13件・デバッグAPKビルドOK。実機での確認は利用者待ち。

### Android版「次の未取り込み台へ」と保存後の自動移動

- `SlotRecord.detailUrl`（バックアップJSONの`detail_url`）を追加。表取り込みのJS（`web_import_page.dart`）が各台の行にあるサイト自身の`rack_no`付きリンクを取得し、Dart側でもサイト内・同一店舗・台番号一致のものだけ採用して保存（確認画面・再取り込み・グラフ保存・重複統合でも保持）。日付はURL→一覧内リンク→本文の順。
- `AppController.nextUngraphed`（PC版`_find_next_ungraphed`/`next_ungraphed_rack`と同じ理由コード）と、ブラウザ画面の「次の未取り込み台へ」ボタン。グラフ保存後は自動で次の台へ移動（取り込みボタンを押すのは人。リンクはサイトが出したものだけ）。移動後の案内は`onPageFinished`で表示。
- バックアップ：PC版`plan_backup_import`とAndroid版`BackupService.plan`に`link_only`（数値が同じでリンクだけ足りない行の補完）を追加し、グラフ追加・競合上書きでも手元のリンクを失わない。
- 検証：Android版15件（`next_ungraphed_test.dart`追加）、PC版45件、デバッグAPKビルドOK。JS（表のリンク取得・日付取得）は実際のブラウザ上の疑似ページで動作確認済み。実機のWebViewでの確認は利用者待ち。

### Android版：台番号の取り違え（ずれ）バグの修正

実機のDBを調べて判明。グラフ取り込みJS（`web_import_page.dart`）は台番号を本文の最初の「N番台」から取っていたが、サイトのページャー（前後の台へのリンク）を拾い、1つ前の台番号になることがあった。その結果、実際は286番台のグラフ・数値が285番台として保存され（285番台の数値が286番台の一覧と同一だった）、一覧に無い284番台が新規作成された。自動保存が「一覧が未取り込み」で外れたのはこのため。修正：URLの`rack_no`を正本にし、無いときだけ本文から取る（PC版と同じ方針）。既に保存された誤データ（2026-09-18・長町南・頭文字D2nd YRの284/285番台）は利用者が履歴で削除して取り直す必要がある。

### 手間削減5点（表保存後の自動移動・異常データ警告・取り消し・進捗表示と完了時まとめ・機種一覧への案内）

共通の考え方：取り込みボタンを押すのは人。移動先はサイト自身が出したリンク（＋サイト自身の機種一覧ページ`rack_info_kt/?kind_code=21`）だけ。
- **表保存後の自動移動**：PC版`_confirm_table`、Android版`_extract`が保存後に最初のグラフ未取得の台へ移動。判断は`_next_step`（PC）／`nextUngraphed`（Android）に集約（kind: next / machine_done / no_link / no_rows）。
- **機種が終わったら機種一覧へ**：`machine_done`（all_done）でサイトの機種一覧ページへ移動。PC版は「次の未取り込み台へ」ボタンも同様。
- **異常データ警告**：同じ機種で回転・BIG・REGが完全一致する台（0G除く）を台番号ずれの疑いとして、保存直後のメッセージ・まとめ（PC HTML／Android `DaySummaryCard`）に表示（PC `core.suspicious_duplicates`、Android `data_checks.dart`）。
- **直前の保存を取り消す**：保存直前の内容を1回分だけ控え（PC `data/last_save.json`＝`remember_for_undo`/`undo_last_save`、Android `AppController._undoEntries`）、既存台は元の内容へ、新規台は削除。PCはオーバーレイ＋メイン画面のボタン、Androidはブラウザ画面のボタン。
- **進捗表示・完了時のまとめ**：「日付　長町南 42/80台・幸町 18/60台」をオーバーレイ／ブラウザ画面に表示。PC版は、機種が終わった時点でその日の一覧の台が全てグラフ取り込み済みなら「この日のまとめ」を自動で開く（メイン画面のチェックで無効化可、`auto_open_summary`）。**→ 2026-09-20に削除済み（下の「まとめを自動で開く機能の削除」参照）。**Android版は機種一覧への移動を優先するため、ウィンドウは開かず案内文で「結果」タブのまとめへ誘導。
- 検証：PC版47件、Android版17件、デバッグAPKビルドOK。オーバーレイJSは擬似ページでボタン動作を確認。Androidの取り消し（DB操作）は単体テスト対象外。実機・実サイトでの確認は利用者待ち。

### 機種一覧の取り込み状況の印・起動時の自動同期（PC）・台ごとの推移

- **機種一覧ページの印**：サイトの機種一覧（`rack_info_kt`）の各機種リンクの横に「済 8/8」「5/18」「未取込」を表示。PC版はオーバーレイJS（`markMachines`）＋`_Bridge.machine_status`＋`core.machine_progress`、Android版は`_machineLinksScript`/`_markMachinesScript`＋`AppController.machineStatuses`。機種名は空白・`+`の違いを無視して照合、日付はURL→リンク→日付選択欄→保存済みの最新日の順。クリックの挙動は変えない（印を付けるだけ）。
- **起動時の自動同期（PC版のみ）**：`app.py`の`auto_sync_on_start`。同期フォルダの最新バックアップ（自動コピーを除く）が前回読んだもの（`settings.json`の`last_synced`＝名前＋更新時刻）より新しければ、確認なしで取り込み。競合だけは従来の確認ダイアログ。チェックで無効化可。**Android版は不可**：AndroidからDriveの特定フォルダを直接読めないため、従来のファイル選択のまま。
- **台ごとの推移**：同じ店舗・台番号・機種の直近7日（機種が変わった日で打ち切り）の合計点・回転・当たり確率と平均点。PC版は`core.rack_trend`を「この日のまとめ」の台詳細モーダルに、Android版は`rackTrend`（`data_checks.dart`）を台詳細ページの`RackTrend`に表示（履歴の台タップからも）。
- 検証：PC版48件、Android版19件、デバッグAPKビルドOK。印のJSは擬似ページで動作確認済み（Android側のスクリプトは同じ内容だがWebViewでは未確認）。

### 採点の見直し（v7）と取得時刻・線データの保存、翌日の参考指数

他のAI（ChatGPT・Gemini）の意見と利用者の判断を踏まえた変更。**設定別確率は利用者が「今は関係ない」として不要としたため、設定推測（事後確率）は実装しない。点数は「設定示唆」ではなく「当日の出玉の傾向の目安」と位置づけ直した。**
- 配点：当たり頻度50・回転数20（500G→4点、3500G→20点）・最大持玉20・終点5・維持5（PC `core.py`のMAX_*と`spin_score`、Android `scoring.dart`を一致）。回転数は打たれた量（人気・取得時刻の影響）で設定の証拠ではないため下げ、当たり頻度を上げた。
- 保存する新項目（後から補えないため先に実装）：`captured_at`（表・グラフ保存時の時刻。PC/Android共通、バックアップに含む）、`graph_measurement.curve`（SVG線の座標列。今は4点だけ採点に使うが将来の指標用）。
- 表示：台の詳細に「データ量（回転数）による信頼度」（低/中/高）と取得時刻（20時前は「早めの取得」注記）。
- 翌日の参考指数（おまけ）：同じ機種での過去（最大10日）の総合点が、その日の同機種平均よりどれだけ高かったかの平均を、日数が少ないほど0へ縮約して50を中心にした指数（PC `next_day_index`、Android `nextDayIndex`）。3日未満は「データ不足」。翌日の設定を示すものではない旨を併記。
- 差枚の推定は見送り：実データ（296台）で最大持玉とグラフのピーク高さの相関は0.55、換算係数は9〜55倍でばらつき、グラフの縦軸が自動スケールと分かったため（最大持玉は差枚ではなく持玉で、投資分も含む）。
- 検証：PC版49件、Android版20件（回転数・当たり頻度の新配点の期待値は手計算で確認）、デバッグAPKビルドOK。

### Android：下部のシステムバーに最後の行が隠れる問題

実機の画面で確認（台の詳細ページの最後の説明文が、下の3ボタンバーの下に隠れていた）。原因は、`SafeArea`で囲っていない`Scaffold`のListViewが、下部バーの高さ分の余白を持たなかったこと。台の詳細（`SavedGraphPage`/`_SavedGraphBody`）、バックアップ不一致画面、一覧データ確認画面のListViewの下余白に`MediaQuery.of(context).viewPadding.bottom`を加えた。他の画面は`SafeArea`済み。

### 5日間のスランプグラフ表示

同じ店舗・台番号・機種で、グラフを保存した日が5日以上あるとき、台の詳細に直近5日の保存済みグラフを左（古い）から右（新しい）へ並べて表示（PC `core.slump_days`/`slump_strip_html`＝「この日のまとめ」の台詳細モーダル、Android `slumpDays`＋`SlumpStrip`＝台の詳細ページ）。「この台の推移」は残している。各日のグラフは日ごとに縦軸が自動調整される相対形状なので（実データで確認済み、差枚は換算不可）、日をまたいだ差枚合計の一本線にはせず、日ごとのグラフを並べる形にして、その旨を画面に明記。画像が無い古い記録は4点からの復元で描く。テスト：PC版50件、Android版21件、デバッグAPKビルドOK。

### PC版メイン画面のデザイン刷新

機能が増えて1枚に縦積みで分かりにくくなったため、`app.py`を3タブに整理：「取り込み」（大きな青いボタン＝ブラウザを開いて取り込む、3行の手順、設定2つ、「この日のまとめ」「過去の記録」「取り消し」）、「結果を見る」（店舗・日付・機種の選択と結果系ボタン）、「バックアップ・同期」。記録欄は下端に固定。`apply_style()`でApple風（淡いグレー背景・青は主ボタンのみ・細い罫線）に統一（ttkの`clam`テーマ）。ロジック（関数・保存項目）は変更なし。自動保存の長い条件文は「条件を見る」ボタンのダイアログへ移動。テストのアプリ画面組み立て（GUI構築）と全体テスト50件OK。実機での操作感は利用者確認待ち。

### Androidアイコン長押しメニュー

`quick_actions`パッケージ（pubspecに追加）で、アプリのアイコンを長押しすると「取り込みを始める」「結果を見る」を出す。「取り込みを始める」は取り込みタブを開いてアプリ内ブラウザまで直接開く（`ImportPage.openBrowser`にボタンの処理を切り出して共用、`MaterialApp.navigatorKey`経由）。コールドスタート時は最初の画面ができるまで0.5秒待つ。ビルド・既存テストOK。ショートカットが実機のランチャーに出るかは未確認（入れ直し後に長押しで確認）。

### バックアップの世代管理（PC版）

`core.py`の`auto_backup`が、保存のたびに、既存の`database-backup-auto.json`（上書き）に加えて、日付つきのバックアップ`backups/database-backup-YYYY-MM-DD.json`（その日の最後の状態）も書く（`snapshot_backup`）。**7日より古いものは自動削除**（`SNAPSHOT_KEEP_DAYS=7`、今日と7日前まで残る）。保存先は、同期フォルダ設定時はその中の`backups/`、未設定時は`data/backups/`。「バックアップ・同期」タブの「過去のバックアップから戻す」で日を選び、`restore_backup`がその日の内容へ戻す：通常の取り込み（新規・グラフ・リンク）に加え、数値やグラフが食い違う台はその日の内容で上書き。**その後に追加した台は削除しない**。Android版は未対応（Driveの特定フォルダへ自動で書けないため）。テスト51件OK（7日超の削除・対象外ファイルを触らない・数値とグラフの復元・後から追加した台が残ることを確認）。

### 「機種が終わったらまとめを自動で開く」機能の削除（PC版、2026-09-20）

利用者の依頼で、PC版の「その日の取り込み済みの台がすべて終わったら『この日のまとめ』を自動で開く」を削除した。他のAIによる採点修正（v8）の完了後に、変更後のファイルを読み直してから実施。
- 削除：`browser_import.py`の`_maybe_open_summary`と`summary_report`のimport、`app.py`の「取り込み」タブのチェック（設定`auto_open_summary`は参照されなくなる。設定ファイルに残っていても無害）。
- 残したもの：日の全グラフが揃い、かつ機種が終わったときの案内文「この日の取り込み済みの台はすべて完了しました。」（ウィンドウは開かない。`core.day_fully_graphed`は案内の判定に使用）。Android版はもともとウィンドウを開かず、案内文（`NextGraphTarget.dayComplete`）はそのまま。「この日のまとめ」ボタンも従来どおり。
- テスト：`test_confirm_graph_reports_progress_and_heads_to_machine_list_without_opening_a_window`が、案内文が出ること・`os.startfile`が呼ばれないこと（ウィンドウを開かないこと）を確認。PC版60件、Android版24件、いずれも成功。採点（v8）の内容には触れていない。
- 上の「手間削減5点」の項にある「PC版は…まとめを自動で開く」の記述は、この変更で無効。

### 動作の軽快化（2026-09-20）

実データ（659台）で計測してから修正。
- **PC**：`Store.references()`が、台ごとに同機種の全行を読み直してJSONを復号していた（履歴レポート1.2秒、まとめ0.9秒）。同機種の行を`Store._machine_rows`で1回だけ復号して再利用（書き込み系メソッドで破棄）→ 履歴レポート171ms、まとめ365ms。
- **PC**：グラフ・表の保存のたびに`report()`を呼び、`reports/`に時刻つきのHTML・JSONを2つずつ増やしていた（4日で962ファイル・85MB）。保存時には作らないよう削除（結果は開いたときに作られるため不要）。既存のレポートは削除していない。
- **PC**：自動バックアップが全データを2回書き出していたのを、日付つきバックアップを1回書き出して同期フォルダへ複製する形に（`auto_backup`）。
- **Android**：保存のたびに全データをDBから再読込・復号していた（次の台への移動前の待ち）。`AppController._mergeRecords`で保存した分だけメモリ上で差し替え。
- **Android**：結果画面が、機種のプルダウンを変えるたびに全台の得点を計算し直していたのを、データ・店舗・日付が変わったときだけ再計算（`_ResultsPageState._scoredByKey`）。
- 計測：PC 1保存あたり約0.25秒（うちTk起動0.08秒）。Android（デスクトップVMでの参考値）：659台の読込復号70ms、最新日43台の採点143ms。実機では未計測。
- 検証：PC版62件、Android版25件、デバッグAPKビルドOK。

### 動作の軽快化 第2段（2026-09-20、実データ659台で計測）

前段の続き。計測 → 修正 → 再計測し、採点結果が変わっていないことを`audit_scoring.py`＋`tool/check_scoring_parity.dart`（659件のPython/Dart一致）で毎回確認した。

- **PC・バックアップ**：`export_backup`が、保存済みJSONを復号して同じ内容を再符号化していた（payloadの約8割はグラフ画像のbase64）。`Store.raw_payloads()`で保存文字列をそのまま連結して書き出す方式に変更（72→33ms）。出力は従来と同一の記録（整形のみ非インデント）で、空・日付指定でも正しいJSONになることをテスト。
- **PC・まとめ**：`rack_trend`/`slump_days`/`next_day_index`が、台ごとに**店舗全体**の行を読み直していた。いずれも同一機種で絞るので`Store._machine_rows`（機種単位のキャッシュ）に統一。**この日のまとめ 920→30ms**。
- **PC・保存のたびのTkウィンドウ**：自動保存時は画面を何も出さないのに、毎回Tkのrootを作って約80ms払っていた。`_OnDemandRoot`で、ダイアログや失敗通知が必要になった時だけ作るように変更。**1台あたりの自動保存 252→約75ms**（履歴レポート1208→156ms、結果ページ24→7msは前段から継続）。
- **Android・採点**：`comparisonPool`が比較のたびに`DateTime.parse`していた（台数の二乗回）。日付は'YYYY-MM-DD'固定なので文字列比較へ（PC版と同じ比較方法）。さらに店舗＋機種で仕分けた索引（`Expando`。一覧が作り直された時と件数が変わった時に再構築）を追加し、全件走査をやめた。**結果画面 143→7ms、全659台 1409→36ms**。約2か月後を想定した5272台でも345ms（索引なしなら約3.6秒の見込み）。索引ありと素朴な絞り込みが全件一致することをテストで固定（`test/scoring_pool_test.dart`）。
- **Android・過去の記録**：画面を組み立て直すたびに全記録を採点し直していたのを、データと絞り込みが変わった時だけに（結果画面と同じ方式）。
- 回帰テスト追加：PC`test_machine_row_cache_never_serves_stale_rows`（追加・上書き・設定情報・削除の後に古い行が残らない）。PC63件・Android28件成功、デバッグAPKビルド成功。

**未対応（利用者の判断待ち）**
- `database/reports/` に962ファイル・85MB。前段で「保存のたびに結果HTMLを作る」のをやめたので今後は増えないが、既存分は残したまま。
- `days`テーブルの更新履歴`observations`が1469行・4.1MB（`days`本体3.5MBより大きい）。画像込みで保存され、どの画面からも読まれていない。放置すると増え続ける。
- 「過去の記録」のHTMLが3.6MB（全台のグラフ画像を埋め込むため）。毎日増えるので、ブラウザで開くのが徐々に重くなる。日数を絞る等は表示内容が変わるため未実施。

### 溜まったファイルの整理・履歴の日数制限・AndroidのUI修正（2026-09-20）

前段で挙げた「未対応（利用者の判断待ち）」に、利用者の承認を得て対応した。

**整理（利用者の承認のうえ一度だけ実行）**
- `database/reports/` の生成物961件を削除（85.7MB → 0.42MB）。採点照合に使う `reports/scoring-v8-audit/` は残した。フォルダの中身は結果ページを開けば作り直される。
- `days`テーブルの更新履歴`observations`の1469行（4.1MB）を削除し`VACUUM`（DB 8.4MB → 3.9MB）。台データ659件は変化なし。
- 今後の再発防止：`Store._log_observation()`が、履歴にはグラフ画像（1件の約8割）を入れず、`OBSERVATION_KEEP_DAYS = 30`より古い行を書き込みのたびに消す。この履歴はどの画面からも読まれない（追跡用）。

**「過去の記録」の日数制限**
- PC版`history_report(store, folder, days=HISTORY_REPORT_DAYS)`。既定14日。各台のグラフ画像をページに埋め込むため、取り込み1日あたり約0.4MB増えていた。**古い日付は消さず**、ページ上部に「直近◯日分（日付範囲）を表示しています。これより前の◯日分も保存されています…」と明記する。
- Android版は日付を隠さず、`ListView.builder`で画面に出ている分だけ組み立てる方式に変更（`_HistoryPageState._group()`を切り出し）。件数が増えても開く速さが変わらない。

**AndroidのUI（実機の画面を見て修正）**
- 「この日のまとめ」で台番号が「710…」と切れていた。機種名側を縮め、台番号は必ず出す。
- 店舗と日付のプルダウンを1行に（画面の縦を約130px節約）。機種は下に幅いっぱい。
- 「最高」カードだけ2行で高さがずれていた。台番号を小さな補足（`MetricCard.note`）に移し、`IntrinsicHeight`で3枚の高さをそろえる。
- 数字が何の範囲か分からなかったので、「この機種の結果　◯台」の見出しを追加（上の「この日のまとめ」はその日の全機種）。
- 台の並べ替え（台番号順／点数順）を追加。既定は台番号順（サイトの一覧と見比べやすいため）。点数なしの台は最後。

検証：PC63件・Android28件のテスト成功、`flutter analyze`は既存のinfoのみ、Python/Dart採点一致659件、実機にインストールして画面（並べ替え・まとめ・過去の記録）を確認済み。

### Android「一覧データを確認」の保存ボタンを下に固定（2026-09-20）

「この表を取り込む」後の確認画面（`WebTableReviewPage`）は、保存ボタンが台数分の入力欄の一番下にあり、直すところが無くても最後までスクロールしないと押せなかった。`Scaffold.bottomNavigationBar`に移して常に見える位置へ固定し、AppBarにも「保存」を追加（グラフ確認画面の「採点を確定」と同じ置き方）。入力欄の並びは変えていない。
テスト28件・`flutter analyze`・APKビルド・実機インストールまで確認したが、この画面は実際にサイトで表を取り込まないと出ないため、**表示の最終確認は利用者の次回の取り込み時**（取り込み操作は利用者が行う方針のため、こちらではサイトを操作しない）。

### Android「表の確認画面を省く」（2026-09-20）

利用者の依頼で、一覧の取り込みもPC版と同じく確認なしで保存できるようにした（表はサイトのHTMLをそのまま読むので、OCRのような読み違いが起きない）。
- 取り込みタブのスイッチ「表の確認画面を省く」。**既定はON**、`ui_state.json`の`skip_table_review`に保存（`false`のときだけ確認画面を出す）。
- **安全装置**：`canSaveWithoutReview(extraction)`（`web_import_page.dart`のトップレベル関数）が、店舗・日付・機種名のそろった表だけ直接保存を許す。ひとつでも欠けていれば、設定がONでも確認画面を開き「店舗・日付・機種名を読み取れなかったので、確認画面を開きます。」と伝える。欠けたまま保存すると今日の日付や空の機種名で保存されてしまうため（PC版`build_table_rows`は同じ場合にエラーにして保存しない）。
- 保存後は従来どおり、最初のグラフ未取得の台へ自動で移動する。
- あわせて、確認画面を出す場合の保存ボタンは下に固定済み（前項）。
- 検証：`test/table_review_test.dart`（そろっている表だけ直接保存・欠けたら確認画面）、テスト30件成功、APKビルド・実機インストール済み。**実際の取り込み動作の確認は利用者**（サイトの操作はこちらでは行わない方針）。

### 採点v9：縮約を相乗平均へ・最大持玉の枚数評価（2026-09-21）

利用者の指摘「19,000枚出してコンプリートしている台ですら61点は厳しすぎる」から。詳細は [SCORING_POLICY.md](SCORING_POLICY.md) の「v9での変更」。

- **診断**：その台（幸町2026-09-16・623番台）は当たり頻度・最大持玉とも順位1.000（比較対象で1位）で、**61.7点はその台の満点**だった。縮約の積が `0.874 × 0.200 × 0.250 = 0.044` で、結果が効くのは4.4%だけ。本番659件で調べると、全項目1位でも80点に届く台は0台、70点にも届かない台が82%、「その台の満点」の中央値は63.5点（比較対象の中央値4台・1日）。100点満点が実質60〜76点に潰れていた。
- **利用者が選んだ対応**（4案を数値付きで提示して選択）：`adjusted_rank`の重みを積から**相乗平均**へ。あわせて`absolute_hold_score`（`20*min(1, 持玉/19000)`）を追加し、最大持玉は順位と枚数の**高い方**を採る（引き上げ専用。比較相手がいない場合は従来どおり欠測＝中立10点）。19,000枚は利用者の記録（19,008枚で打ち止め）から採用した値で、規則の条文は未確認。
- **結果**：623番台 61.7→80.6点。稼働613台の平均47.2・中央値44.9・最小13.5・最大84.6（v8は47.3／46.9／26.5／72.7）。真ん中はほぼ動かず上下に広がった。「その台の満点」中央値83.3点。
- PC `core.py`・Android `scoring.dart` の両方を同じ式に更新（`VERSION`/`scoringVersion` = `2026-09-21-v9`）。
- テストは手計算で検算して更新（`.2^(1/3)=.584804` → 当たり47.5441・持玉15.8480・合計83.4）。コンプリート台が持玉満点になること、枚数では点を下げないことを両OSで固定。
- 検証：PC64件・Android31件のテスト成功、659件のPython/Dart採点一致、`flutter analyze`は既存info9件、APKビルド・実機インストール済み。**実機での見え方の確認は利用者待ち。**

### Androidバックアップの共有ファイル名（2026-09-21）

利用者の依頼で、Android版のバックアップ共有時に表示される名前（共有シートの「タイトル」＝一部の共有先はここを保存ファイル名として使う）が日本語混じりで分かりにくかったのを直した。

- `backup_service.dart`の`export()`：実ファイル名を`database-backup-<日時>.json`→**`backup_<日時>.json`**へ（全角なし・半角のみ）。
- `main.dart`の`_shareBackup`：`ShareParams`の`title`/`subject`にハードコードした日本語文字列（`'databaseのバックアップ'`等）を渡すのをやめ、**実際のファイル名（`file.uri.pathSegments.last`）をそのまま使う**ように変更。共有シートに出る名前と、実際に保存されるファイル名を常に一致させた。
- PC版・バックアップJSON内部の`"format": "database-backup"`（Android・PC間の互換用フォーマット識別子）はファイル名と無関係のため変更していない。PC版の書き出しファイル名（`app.py`の`default_name`）はダイアログで利用者が確認・入力する方式のため、この問題の対象外で変更していない。
- 検証：Android版`flutter test`31件・`flutter analyze --no-pub`エラーなし・`flutter build apk --debug --no-pub`成功。実機にインストールし、**利用者が動作確認済み**（問題なし）。

### 「翌日候補（仮）」の表示を読めるようにした（2026-09-21）

別AIが追加した「翌日候補（仮）」について、利用者から「UIがとてもわかりづらい」との指摘。**計算（`next_day_index` / `nextDayIndex` / `provisional_next_day_candidates`）は一切変更せず、表示の言葉と形式だけ**を直した。

- **指数の出し方**：`63 / 100`のような素の値をやめ、**「平均より +13」**という差分表記に統一した。この指数は50が中立だが画面のどこにもそう書いていなかったため、数字だけ見ても「高いのか低いのか」「どちらが良いのか」が読み取れなかった。PC `core.py`に`signed_index()`、Android `main.dart`に`signedIndex()`を追加（同じ出力・同じ丸め）。マイナス記号は全角混じりを避けて**半角`-`**で統一。
- **何の数字かを先に書く**：カード冒頭に「この機種で、過去に当たりが周りの台より軽かった台です。明日どの台から見るかの参考用で、今日の合計点には影響しません。」を置き、見出しに**「試験中」**のタグを付けた。
- **各台の行**：「当たりの軽さ 平均より +13・過去5日分」。根拠（同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差）は一覧の下に注記として1回だけ書く。
- **出せないときの文面**：単なる「データ不足」ではなく「傾向を出せた台が◯台中◯台です（4台以上で表示）。同じ台・同じ機種のデータが3日分たまると傾向を出せます」と、**あと何が必要か**が分かる文面へ。
- **台ごとの推移（詳細画面・要約モーダル）**も同じ言い回しに揃え、「翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）」という但し書きを両方に残した。
- 変更ファイル：`database/core.py`（`signed_index`・候補セクションを`<ul class="candidate-list">`へ・対応CSS追加・要約モーダルの文面）、`database/tests/test_database.py`、`database_android/lib/main.dart`、`database_android/test/next_ungraphed_test.dart`。
- 検証：PC `python -m unittest discover -s tests` 64件成功、Android `flutter test` 31件成功、`flutter analyze --no-pub`は既存info9件でエラーなし、`flutter build apk --debug --no-pub`成功。**実機・PC画面での見え方の確認は利用者待ち。**

### 機種一覧（行クリック形式）対応の照合と、見つかった不具合の修正（2026-09-22）

別のAIが入れた「機種一覧の行クリック形式（`tr.teram2-link-block`／`.wrap-machine-name`）対応」を実コードと照合し、ページ遷移・欠損・遅延のエラーを洗い出した。

**照合して問題なしと確認したもの**
- PCのオーバーレイは、一覧がXHRで遅れて届く場合に空のまま失敗扱いにしない（疑似ページで一覧を1.2秒遅らせて押し、「機種一覧の読み込みを待っています…」の後に1回だけ送信することを確認）。旧リンク形式・行クリック形式の両方から機種名・台数・機種別URLを組み立てる。
- グラフ完了後に機種一覧へ戻るURLは、PC・Androidとも `#database_next_machine=1&database_day=<日付>` を持ち、別日を参照しない。保存する日付はページ自身（URL・台リンク）から取り、このフラグメントは使わない。
- Androidの取り込みボタンは読み込み中（`_loading || _reading`）は押せない。

**実データで確認したこと（読み取り専用）**：PCのDB 1403行で、保存日とサイト自身のURLの`target_date`の食い違いは照合できた1445項目中0件。同じ台が別の日に同じ回転・BIG・REGになっている組も0組。直近4日は表の全行に`detail_url`があり、機種別の表は現行サイトでも台ごとの日付入りリンクを持つ（行クリック化は機種一覧だけ）。ただし長町南の196行は`source_url`が`standlist_slot?kind_code=21`で日付を照合できない（Android由来と推定）。

**修正した不具合（すべて失敗するテスト／疑似ページで再現してから修正）**
1. **Android：前日のデータを翌日の日付で保存しうる**（「9/15を9/16で保存」の経路）。`_extractTableScript`・`_extractGraphScript`が、URLにも台リンクにも日付が無いとき**本文の最初の日付**を使っていた。本文先頭には「更新日時」（翌朝の日付）があるため、疑似ページで修正前は9/15を`2026-09-16`と読んだ。サイトの日付選択欄（`select option:checked`）を使うよう変更し、読めなければ`null`（推測しない。表は保存せず確認画面、グラフは自動保存しない）。優先順位は URL → 台リンク → 日付選択欄 → null。PCは元から本文を使わない。
2. **PC・Android：減台後に前日分を取り込むと、同じ機種へ戻し続けて後ろの機種へ進めない**。「一覧の台数 ≠ 保存台数」で取り込み直しを案内していたが、一覧は今の設置台数で、取り込み直しても台は上書きされるだけで消えない。**一覧の方が多いときだけ**案内するよう変更（PC `next_unimported_machine`、Android `listedCountNeedsReimport`）。
3. **PC・Android：低貸し（kind_code=10・5）の機種一覧から、低貸しの機種へ移動していた**（保存時には21以外を拒否するので不正データは入らないが、対象外の表へ案内していた）。画面の種別が明示的に21以外なら移動しない。機種URLも、種別が明示されていて21以外なら候補から外す（旧リンク形式は種別を持たないことがあるので、無いものは通す）。PCはJSから`kind_code`を渡すよう変更、Androidは`isTargetKindUrl`。
4. **Android：JavaScriptの結果が null・空文字・`{error}` のとき、Dartの型エラーになり利用者に意味が分からなかった**。`decodeJavaScriptResult`（トップレベル関数）で日本語の理由付きで失敗させる。`Completer<Object?>`に変更。`rows`・`machines`・`url`の強制型変換もやめ、既存の分かりやすい案内に回す。
5. **PC・Android：機種一覧が空のときの文言**を「読み取れませんでした」から「機種一覧が表示されるのを待ってから、もう一度押してください」へ（多くは読み込み中のため）。

**テスト**：PC `test_machine_list_does_not_loop_when_fewer_racks_are_listed_than_saved`・`..._reimports_when_more_racks_are_listed_than_saved`・`..._refuses_non_46mai_kind_code`・`..._empty_result_says_it_may_still_be_loading`（先に失敗を確認）。Android `test/javascript_result_test.dart`（5件）・`test/machine_list_test.dart`（3件）。PC70件・Android39件成功、採点のPython/Dart一致1403件、`flutter analyze`は既存info9件のみ、全JavaScript（Android 6本＋PCオーバーレイ）をブラウザのJSエンジンでコンパイル確認。

**未確認・残っている懸念（コードは変えていない）**
- 実サイト（行クリック形式の機種一覧、XHRの遅延の実際、同意・保護ページ）での動作。サイトは操作しない方針のため、疑似ページでのみ確認。
- Androidの表取り込みの台数照合（`expectedCount`）は、`rack_info_kt`を`fetch`して旧形式の`a[href*="machine_name"]`を探すため、行クリック形式＋XHRで一覧を埋める現行サイトでは**働いていない見込み**（照合できないときは黙って飛ばす作り）。直すにはXHRの取得先を知る必要がある。
- PCの`install_overlay`は、許可外のURLを開くと長町南へ戻す。同意・保護ページが店舗パスの外にあると、同意できずに戻され続ける可能性がある（日常的に使えているので現状は店舗パス内か、同意が保存されていると推定）。
- 機種一覧の取込状況バッジ・進捗は、日付が読めない初回表示では「保存済みの最新日」の状況を出す（別日の可能性）。表示のみで、保存や次の機種の選択には使っていない。
- 長町南の日付照合できない196行が、Android経由で誤った日付になっていないか（上記の数値重複チェックでは痕跡なし。Android端末のDBは未確認）。
- APKは未ビルド・未インストール（利用者の指示待ち）。

### PC：機種一覧で「Converting circular structure to JSON」（2026-09-22）

利用者の実機で、幸町の機種一覧で「この画面を取り込む」を押すと `TypeError: Converting circular structure to JSON ... HTMLTableRowElement ... __reactFiber ... stateNode closes the circle` が出て先へ進めなかった。原因は、オーバーレイの`moveToNextMachine`が`machineLinks()`の結果（バッジ表示用に各行のDOM要素`element`を含む）をそのまま`JSON.stringify`していたこと。実サイトはReactで描画されており、DOM要素が`__reactFiber`経由で自分自身を参照するため変換できない。直前の検証で使った疑似ページはReactを使っておらず、この失敗を再現できていなかった（見落とし）。送信前に`{name, url, count}`だけへ絞るよう修正。疑似ページの要素に同じ自己参照を付けて、修正前は同じエラー、修正後は正しく送信されることを確認。Android版は機種一覧スクリプトが元から`{name, url, count}`だけを返すため影響なし。PC70件成功。反映にはブラウザ取り込みの開き直しが必要（APK不要）。

### PC：機種一覧から移動した先が「該当する台情報がありません」になる（2026-09-22）

循環参照エラーを直した後、機種一覧から次の機種へは移動できたが、移動先の機種別ページが空（「該当する台情報がありません」、表の検出エラー「ページに<table>が1つもありません」）になった。以前サイト自身のリンクから保存した`source_url`を調べると、機種別ページのURLには必ず`target_date=`が付いており、機種名の表記も`+`区切り・空白区切りが混在していた。一方、行クリック形式の一覧から組み立てていたURLには日付が無い。サイトの正しい表記を確定できないため、**URLを組み立てるのをやめ、サイト自身の行（旧形式ならリンク）をクリックして移動する**方式に変更（日付・表記はサイトが自分で付ける）。Pythonの`next_unimported_machine`は表へ移動する応答（`table`・`need_day`）に機種名`machine`を含め、JSがその名前の行を探して`click()`する。見つからない場合は従来どおりURLへ。3秒たっても移動しなければ「行を押しても移動しませんでした。一覧の機種名を直接押してください」と案内。移動だけで、取り込みは利用者がボタンを押したときだけ。疑似ページ（行クリックで日付入りURLへ移動するサイトの動きを再現）で、組み立てたURLではなくサイトの移動先へ進むこと、移動しない場合の案内を確認。PC70件成功。**Android版は同じくURLを組み立てて開いているため同じ不具合がある見込み**（PCの実サイト確認後に同じ方式へ直す予定、未修正）。

### PC・Android：長町南店のジャグラーを「次の機種へ移動」の対象外に（2026-09-22）

利用者指定：長町南店はジャグラーシリーズのデータを公開していないため、機種名に「ジャグラー」を含む機種を次の機種の候補から外す。長町南だけが対象で、幸町（SマイジャグラーVKDなど）は従来どおり対象。長町南は機種名が半角カナのことがあるため、PCはNFKCで全角へそろえて判定し、AndroidはNFKCが無いため「ジャグラー」「ｼﾞｬｸﾞﾗｰ」の両方で判定する（PC`is_excluded_machine`／Android`isExcludedMachine`）。除外対象は、未取込機種の選択・日付確認用に最初に開く機種の選択の両方で飛ばし、一覧の印は「対象外」と表示。一覧に出ている機種がすべて対象外なら「読み込み待ち」ではなく「未取り込みの機種・グラフはありません（長町南店のジャグラーはデータ非公開のため対象外）」と案内。保存済みデータ・スコア計算には触れていない（既に保存されたジャグラーの行は削除しない）。テスト：PC72件、Android40件成功、`flutter analyze`は既存のinfo9件のみ。実サイト未確認。PCはブラウザ取り込みの開き直しで反映、AndroidはAPKビルドが必要（利用者の指示待ち）。

### PC・Android：機種一覧の見出し行を「次の機種」に選んでいた（2026-09-22）

利用者の実機（長町南）で「機種名台数通常順ピックアップ順 の行を押しても移動しませんでした」と表示された。実サイトは一覧の見出し行も機種の行と同じ`tr.teram2-link-block`で描画しており、見出しを機種名「機種名 台数 通常順 ピックアップ順」（台数なし・未取込）として拾い、最初の未取込機種に選んでいた（一覧の見出しにも「未取込」の印が出ていた）。修正：JSで`<th>`を含む行を除き、`.wrap-machine-name`を持つ行があるときはその行だけを機種とする（PCオーバーレイ`machineRows`、Androidの機種一覧・印の両スクリプト。印の番号がずれないよう同じ選び方）。念のためPython`is_list_header`／Dart`isListHeaderName`でも見出し名を候補から除く。疑似ページ（見出しが`<td>`の場合・`<th>`の場合）で、PC・Androidとも見出しが除かれ2機種だけ拾うこと、印が正しい行に付くことを確認。テスト：PC73件、Android41件成功。実サイトの見出し行の正確なHTMLは未確認。

### Android：内部ブラウザでYouTube動画を表示しない（2026-09-22）

利用者指定：内部ブラウザでYouTubeを再生することはないので表示しない。PC版の行クリック移動は利用者の実機で動作確認済み（見出し行の修正後、次の機種へ移動できた）。`web_import_page.dart`に`_hideYouTubeScript`を追加し、ページ読み込み完了時（`_afterPageFinished`）に実行。src／data-src／dataがYouTube（youtube.com・youtube-nocookie.com・youtu.be とそのサブドメイン）のiframe・embed・objectを`about:blank`にしてから取り除き、動画だけを包んでいた空の枠は非表示にする。後から差し込まれる動画はMutationObserverで消す。表・グラフや他のiframeには触れない。Dart側の同じ判定`isYouTubeUrl`にテストを追加（名前にyoutubeを含むだけの別ドメインは対象外）。疑似ページで、YouTubeのiframe2つと後から追加した1つが消え、他のiframe・表・説明文は残ることを確認。テスト：Android42件成功、analyzeは既存info9件のみ。実サイトでの動画の埋め込み方法は未確認（リンクやサムネイル画像だけの場合は消えない）。PC版は変更なし。APKビルドが必要（利用者の指示待ち）。

### Android：機種一覧から機種別の表へは行クリックで移動（2026-09-22）

PC版の行クリック移動が利用者の実機で動いたため、Android版も同じ方式へ変更。`_moveToNextMachine`の表へ移動する3か所（日付確認用の最初の機種・グラフ再開のための表の更新・未取込／台数変更の機種）を、URLを組み立てて`loadRequest`する代わりに`_openMachineTable`でサイト自身の行（旧形式ならリンク）を押す。押す処理`_clickMachineRowScript`は見出し行を除く同じ行の選び方で、名前は`+`と空白を無視して照合し、応答を返した後に`setTimeout`で押す（移動で応答が失われないように）。行が見つからない場合は従来どおりURLを開く。3秒たってもページ読み込みが始まらずURLも変わらなければ、読み込み中の表示を解除して「◯◯ の行を押しても移動しませんでした。一覧の機種名を直接押してください。」と案内。グラフ（個別台）への移動は保存済みのURLのまま。疑似ページで、半角カナ・`+`・空白の違いがある名前の行を押せること、見出し行・存在しない名前は押さずfalseを返すこと、旧形式のリンクも押せること、押すのが応答の後であることを確認。Android42件成功、analyzeは既存info9件のみ。実機・実サイトは未確認。APKビルドが必要（利用者の指示待ち）。変更前の控え：scratchpadの`web_import_page.before_rowclick.dart`。

- 2026-09-22 20:26 利用者の指示でAndroid版を`flutter build apk --debug --no-pub`でビルド（成功、`database_android/build/app/outputs/flutter-apk/app-debug.apk`）。ジャグラー除外・見出し行修正・YouTube非表示・行クリック移動を含む。実機へのインストールは未実施（指示待ち）。

### Android：一覧で次の機種へ進まない・取り込み後に読み込み中のまま止まる（2026-09-22）

利用者の実機報告：(1)機種一覧（1000円46枚）で「この画面を取り込む」を押しても未取り込みの機種へ行かない、(2)台を取り込んで戻ると読み込み中（くるくる）が続く。adbの画面取得で、機種一覧でボタンが無効（読み込み中）のまま・印も無い状態を確認。内部ブラウザはデバッグ無効でPCから中を調べられず、原因は**コードから推定**（実機では未確認）。
- (2)の推定原因：グラフ完了後に一覧へ戻ると`_afterPageFinished`が自動で`_moveToNextMachine(automatic)`を呼び、そのまま`return`する。移動しない結果（一覧の行がまだ出ない・残りなし・対象外のみ等）では`_loading`を戻す処理が無く、くるくるが回り続けボタンが押せなかった。修正：`_moveToNextMachine`で移動を始めたか（`moved`）を記録し、移動しなければ最後に`_loading=false`。`_openMachineTable`は移動を始めたかを返す。安全装置として、ページ読み込み開始から20秒たっても完了通知が来ず読み込み中のままなら表示を外す。一覧の行を待つ時間を約4秒→約10秒に延長。
- (1)の推定原因：一覧を初めて開いたときは日付が分からず、日付確認のために先頭の機種（既に取り込み済みの沖ドキ等）を開いていた。修正：この店で最後に取り込んだ日の状況で、未取込（または途中）の機種を優先して開く（該当が無ければ従来どおり先頭）。
- 調査用：デバッグ版だけ`AndroidWebViewController.enableDebugging(true)`（`kDebugMode`時のみ。リリース版は無効）。次回はUSB接続でPCから内部ブラウザを調べられる。`pubspec.yaml`に`webview_flutter_android: ^4.13.0`を直接依存として追加（既にロック済みの版、オフラインで取得）。
- テスト：Android42件成功、analyzeは既存info9件のみ（不要になった`dart:typed_data`のimportを削除）。変更前の控え：scratchpadの`web_import_page.before_stuck.dart`・`pubspec.before_stuck.yaml`。APK未ビルド。

- 2026-09-22 21:31 利用者の指示でAndroid版を`flutter build apk --debug --no-pub`でビルド（成功）。読み込み中で止まる件・日付確認で未取込の機種を優先・デバッグ版の内部ブラウザ調査を含む。インストールは利用者が行う。

- 2026-09-22 21:41 **注意**：利用者の端末に入っていたのは`app-release.apk`（18:49ビルド、SHA1一致で確認）で、この日のAndroid修正（ジャグラー除外・見出し行・YouTube非表示・行クリック移動・読み込み中の解除）はどれも入っていなかった。利用者は`app-release.apk`をインストールしているため、以後は**リリース版もビルドする**こと。`flutter build apk --release --no-pub`でビルド（成功、`build/app/outputs/flutter-apk/app-release.apk`）。リリース版では内部ブラウザのPCからの調査は無効。

### Android：保存の通知を上部へ・YouTubeのサムネイル形式も非表示（2026-09-22）

利用者の実機でリリース版（21:41）の正常動作を確認済み。追加の要望2点。
- 「◯番台を保存しました（…G・BIG…・REG…・終点…）」がSnackBarで画面下に出て取り込みボタンに重なっていた。`main.dart`の成功時SnackBarをやめ、`web_import_page.dart`で同じ内容を`_moveToNext`の`saved`に含めて、取り込み画面上部の通知欄に出す（移動先の読み込み後に表示）。読み取り失敗時のSnackBar（「保存しません」）は従来どおり下。
- YouTubeがまだ表示されていた（adb画面取得で確認：サムネイルと赤い再生ボタン）。動画本体ではなく「サムネイル＋再生ボタン」だけを置き、押したときに動画を差し込む形式と推定。`_hideYouTubeScript`を拡張：src・style・href等の属性にyoutube.com／youtube-nocookie.com／youtu.be／ytimg.comを含む要素、classやidにyoutube・yt、data-*属性名にyoutubeを含む要素を隠し、動画だけを包む枠（再生ボタン・黒背景を含む、文字4字以下・表や日付選択や他の画像を含まない、最大4段）までさかのぼって隠す。表・select・入力欄を含む枠は隠さない。属性の書き換え（src後付け）も監視（200ms間引き、隠した要素は印を付けて再処理しない）。疑似ページで、サムネイル形式・背景画像形式・YouTubeへのリンク・iframe・後からsrcを付けたiframeが隠れ、日付選択を含むカード・表・他の画像・文字は残ること、監視が無限に回らないことを確認。実サイトの動画部分のHTMLは未確認。Android42件成功、analyzeは既存info9件のみ。APK未ビルド。

### PC・Android：機種ごと・日付ごとのまとめて削除（2026-09-22）

利用者の要望：取り込みミスなどのため、台ごとの削除に加えて機種ごと・日付ごとにまとめて消したい（確認ダイアログがあれば一括でよい。例：2026-09-22を一挙削除）。消す範囲は3つ：①この機種だけ（店舗・日付・機種）②この店舗のこの日すべて ③両店舗のこの日すべて。機種だけの指定（店舗なし）は別店舗の同名機種を巻き込むので受け付けない。
- PC：`core.py`に`Store.delete_group(day, store, machine)`と`delete_records(store, data_dir, day, location, machine)`。消す前の内容を`remember_for_undo`の控え（`last_save.json`）に残すので「直前の保存を取り消す」で1回分戻せる（取り消しの確認文も「保存またはまとめて削除」に変更）。削除後に`auto_backup`。`app.py`の結果欄に「まとめて削除…」ボタン：範囲を台数付きで選ぶダイアログ（0台の範囲は選べない）→警告付きの確認（既定は「いいえ」）→削除、ログに台数。
- Android：`data_checks.dart`に`recordsInGroup`（PC と同じ範囲）、`database_service.dart`に`deleteRecords`（トランザクション）、`AppController.deleteGroup`（取り消し控えに消す前の記録を残す）。結果画面の一番下に「まとめて削除…」→範囲を台数付きで選ぶシート→赤い「削除」の確認→削除後のSnackBarに「元に戻す」（取り込み画面の「直前の保存を取り消す」でも戻せる）。
- 注意：取り消しは1回分だけで、保存・取り込みの取り消しと共通。削除のあとに何か保存すると、その削除は取り消せなくなる。
- テスト：PC74件（まとめて削除と取り消しのテストを追加）、Android46件（`test/bulk_delete_test.dart`4件追加）成功。analyzeは既存のinfoのみ（10件：`dart format lib test`で整形されたため既存の波括弧なしif 1件が数に加わった。`backup_service`・`csv_export_service`・`import_service`・`models`・`scoring`と一部テストは空白・改行の整形のみで動作の変更なし）。PCの画面・Android実機での操作は未確認。APK未ビルド。変更前の控えはscratchpadの`*.before_bulkdelete.*`。

- 2026-09-22 21:56 利用者の指示でAndroid版リリース版をビルド（`flutter build apk --release --no-pub`成功、`app-release.apk` 85.8MB）。保存通知の上部表示・YouTubeサムネイル形式の非表示・まとめて削除を含む。インストールは利用者が行う。

- 2026-09-22 利用者が21:56ビルドのリリース版を実機にインストールし、**動作確認OK**（保存通知の上部表示・YouTube非表示・まとめて削除を含む）。

### PC・Android：機種一覧の印は「今日」で判定し、日付を付ける（2026-09-22）

利用者の報告：今日（9/22）途中まで取り込んだ分をまとめて削除したのに、機種一覧で沖ドキが「済」のまま。原因：サイトの機種一覧ページには日付が無く、印（済・途中・未取込）と進み具合の行は「その店舗で保存済みの最新日」で判定していた。9/22を消したので最新日が9/21に戻り、9/21の「済 16/16」が出ていた（表示だけの問題で、取り込みは移動先ページの日付で保存される）。利用者が案3を選択：
- 日付が分からないときは**今日**で判定（サイトの日付選択の初期値と同じ）。PC`browser_import.today_iso()`、Android`todayIso()`／`AppController.today`（テストで差し替え可能）。対象は印（PC`machine_status`・Android`machineStatuses`）、進み具合（今日の分が無ければ「2026-09-22　まだ取り込みがありません」）、日付確認のために開く機種（今日まだ済んでいない機種を優先。PCも同じ規則に変更）。
- 印に日付を付ける：「9/22 済 16/16」「9/22 3/16」「9/22 未取込」（「対象外」は日付なし）。
- PC：`browser_import.py`の関数内`import re`（2か所）をモジュール先頭へ移動（日付確認の処理で`re`を先に使うため）。
- テスト：PC75件（今日で判定・前日の「済」を出さない・日付確認で未済を優先・今日の分が無いときの表示）、Android46件（既存テストの「最新日」の期待を「今日」に変更）成功。analyzeは既存のinfo10件のみ。疑似ページで印の文字（PC・Android）を確認。実サイト・実機は未確認。APK未ビルド。

- 2026-09-22 22:08 利用者の指示でAndroid版リリース版をビルド（成功、`app-release.apk` 85.8MB）。機種一覧の印を今日で判定・日付付きを含む。インストールは利用者が行う。

- 2026-09-22 利用者がPC版・Android版（22:08ビルドのリリース版）ともに**動作確認OK**（機種一覧の印を今日で判定・日付付きを含む）。

### 締めの見直し（2026-09-22）

利用者の依頼「今後バグが想定される箇所を検討し修正」。
- Android：表の取り込み（`_extractTableScript`）で、台数照合のために裏で`rack_info_kt`を毎回`fetch`していたのを削除。今のサイトは一覧をXHRで後から描画するため取得HTMLに行が無く、照合は常に空振り（expectedCountは常にnull）。取り込みのたびに最大5秒待ち、利用者の操作と別に通信が1回増えていた。表示中の表だけを読む（候補が複数あれば最も行数の多い表、従来の空振り時と同じ動作）。Dart側の台数照合の仕組みは残しているが、現在は使われない。
- Android：取り消し（`undoLastSave`）を1台ずつのDB書き込みから、削除・保存それぞれ1回のまとめ処理へ（まとめて削除の取り消しで百台以上になるため）。
- PC：まとめて削除のダイアログの初期選択を「台数がある範囲の最初」に（機種が無い日に無効な範囲が選ばれたまま進むと、何も起きずに終わっていた）。
- テスト：PC75件、Android46件成功、analyzeは既存info10件のみ。テストが途中で失敗すると`database/tmp*`が残ることがある（今回は0個）。
- 検討したが変更しなかった点：深夜0時すぎは一覧の印が全機種「未取込」（日付付きで判別可）／取り消しは1回分で保存と共通／行クリック後3秒で移動が始まらないと「移動しませんでした」と出る（通信が極端に遅い場合は誤表示の可能性）／ページ読み込み開始から20秒で読み込み中を解除するため、極端に遅い通信では表示途中のページで取り込みボタンが押せる。
- APK未ビルド（Androidの上2点を反映するにはビルドが必要）。PCは開き直しで反映。

### PC・Android：幸町店のブラックボードも対象外（2026-09-23）

利用者指定：幸町店はブラックボードのデータを公開していない。長町南のジャグラーと同じく、次の機種の候補から外し、一覧の印は「対象外」。PC`EXCLUDED_MACHINE_WORDS['saiwaichou']=('ブラックボード',)`（NFKCで半角も一致）、Android`excludedMachineWords['saiwaichou']=['ブラックボード','ﾌﾞﾗｯｸﾎﾞｰﾄﾞ']`。「対象外しか残っていない」ときの案内は店舗別の呼び方に（`EXCLUDED_MACHINE_NOTES`／`excludedMachineNotes`）。長町南のブラックボード、長町南の「ｽｰﾊﾟｰﾌﾞﾗｯｸｼﾞｬｯｸ」・幸町の「スーパーブラックジャック」は対象のまま（テストで確認）。保存済みの幸町「Sブラックボード」9/22の8台は消していない（不要なら利用者が「まとめて削除」で消せる）。
- 直前のChatGPTの点検修正（上の項目）の上に重ねて変更。PC78件・Android57件すべて成功、analyzeは既存info8件のみ。ChatGPTの実行で残った`database/tmp*`（空フォルダ42個）を削除。
- APK未ビルド。ChatGPTの記録にあるFlutterのlockfileの件は、次のビルド時に確認する。

- 2026-09-23 00:22 利用者の指示でAndroid版リリース版をビルド（成功、`app-release.apk` 85.8MB）。ChatGPTの点検修正と幸町ブラックボード除外を含む。この時点でGit Bash・PowerShellから`flutter`を直接呼ぶと何も出力せずに終わる状態だったため、`cmd /c "C:\Users\keyan\flutter\bin\flutter.bat build apk --release --no-pub"`で実行した（lockfileは残っていたが実行を妨げなかった）。インストールは利用者が行う。

### PC・Android：「今日」は深夜2時で切り替え（2026-09-23）

利用者指定：深夜2時までは当日扱い（9/22の26時＝9/23 1:59 までは9/22）。
- PC`browser_import.today_iso(now=None)`：現在時刻から2時間引いた日付（`BUSINESS_DAY_CUTOFF_HOUR = 2`）。機種一覧の印・進み具合・日付確認で開く機種の判定に使う。
- Android`todayIso([now])`：同じ規則（`businessDayCutoffHour = 2`）。機種一覧の印・進み具合に加え、確認画面・保存で日付が分からないときの初期値（従来は暦の今日を`DateFormat`で作っていた3か所）も`todayIso()`にそろえた。不要になった`intl`のimportを削除。
- 変えていないもの：日付入りバックアップのファイル名（暦の日付）、旧`collector.py`、取得時刻の記録。サイトの表・グラフのページから日付が読める場合は常にそちらが優先（URLのtarget_date等）。
- テスト：PC79件（2時の境目・月末・年末）、Android58件（同じ境目）成功。analyzeは既存info8件のみ。APK未ビルド。

- 2026-09-23 00:30 利用者の指示でAndroid版リリース版をビルド（成功、`app-release.apk` 85.8MB、`cmd /c flutter.bat build apk --release --no-pub`）。深夜2時切り替えを含む。インストールは利用者が行う。

### PC・Android：保存するグラフ画像を小さくする（2026-09-23）

利用者の依頼で容量削減を検討。実データ（PCのDB 19.6MB・2096台）を読み取り調査した結果、`graph_measurement.preview_image`が12.2MB（全体の約88%、1819枚・中央値2KB）で、ほかは`curve`1.1MB・その他1MB。削減対象は画像だけ。実データ120枚で再圧縮を比較した（元比／1枚あたり）：PNG32色31.8%/9ms、WebP品質70が20.5%/21ms、半分に縮小＋PNG32色が17.4%/6ms。利用者が「半分に縮小＋PNG32色」「既存データは変換せず今後の保存分だけ」を選択。
- PC`screenshot_import.encode_preview_image`：画素を1/2に縮小し32色PNG（`PREVIEW_PIXEL_SCALE=2`・`PREVIEW_COLORS=32`）。**返す幅・高さは従来どおり座標の大きさ**（4点・曲線と同じ座標系。画素数を返すと点が半分ずれる）。ブラウザ取り込みとスクリーンショット取り込みの両方が通る共通関数。
- Android`import_service.encodePreviewPng`：同じ規則（`copyResize`＋`quantize(32色)`＋`encodePng(level:9)`）。`detectGraph`のcropと、ブラウザのSVGから作るプレビューの両方で使う。`GraphDetection.width/height`は座標の大きさのまま。
- 既存の保存データは変換していない（利用者の指定）。表示側は画像を幅・高さに引き伸ばして描くため、新旧が混在しても点の位置はずれない。
- 試算：今後の保存分は画像が元の24%（実データを新方式で作り直した場合12.2MB→3.0MB相当）。既存も変換すればDBは19.6MB→約10MB。
- テスト：PC80件（座標の大きさは変えず画素だけ半分・32色以下・幅420クランプ後に半分）、Android60件（`test/preview_image_test.dart`。処理時間はPC上14.2ms/枚、実機はこれより遅い見込み）。analyzeは既存info8件のみ。
- 未確認：実機での保存時間、実際の見た目（拡大したときのぼやけ具合）。APK未ビルド。

- 2026-09-23 11:01 利用者の指示でAndroid版リリース版をビルド（成功、`app-release.apk` 85.8MB）。グラフ画像の圧縮（半分に縮小＋32色）を含む。インストールは利用者が行う。

### PC：内部ブラウザでYouTubeを表示しない（2026-09-23）

利用者の指摘：PC版の取り込みブラウザでもYouTubeが出てクリックの邪魔になる。Android版で使っている非表示スクリプトをそのままPC版にも入れた（`browser_import.HIDE_YOUTUBE_JS`。Android`web_import_page.dart`の`_hideYouTubeScript`と同一文字列で、`OVERLAY_JS`の末尾に連結してページごとに実行）。動画本体（iframe・embed・object）と、サムネイル＋再生ボタンだけを置く形式（i.ytimg.com の画像、class・id・data-*にyoutube／ytを含む要素、style中のytimg等）を隠し、動画だけを包む枠は最大4段さかのぼって隠す。表・select・入力欄を含む枠には手を出さない。後から差し込まれる分・src書き換えはMutationObserverで対応（200ms間引き）。
- テスト：PC81件成功（両アプリのスクリプトが同一であること・括弧の対応・「表やselectを含む枠は隠さない」条件の存在を確認。文字列が食い違うとテストが落ちるので、今後どちらかだけ直すことを防げる）。
- 疑似ページ（オーバーレイ全体を読み込み）で、サムネイル形式・YouTubeリンク・iframeと、それらを包む黒い枠が消え、機種一覧の表・日付の選択・他の画像・文字・オーバーレイのボタンは残ることを確認。実サイトでは未確認。
- PCはブラウザ取り込みの開き直しで反映（APK不要。Android版は変更なし）。

### PC：取り込みオーバーレイの大きさを変えられるように（2026-09-23）

利用者の要望。オーバーレイのつまみ（ドラッグ部分）の右端に「－」「＋」を追加し、カード全体を`zoom`で0.7〜2.0倍（0.15刻み）に変える。倍率は`localStorage['database-overlay-size']`に残るので、ページ移動後も同じ大きさ。
- 位置の扱いを「画面に見えている座標」に統一した。`zoom`を掛けた要素はCSSの`left/top`が見た目の1/zoomになるため、`place()`は`getBoundingClientRect()`で大きさを測り、代入時に`sizeScale`で割る。ドラッグ後に覚える位置も`getBoundingClientRect`の値にした（従来は`card.style.left`で、拡大時にずれる）。
- 大きさを変えたときは、そのときの画面上の位置を保ったまま、はみ出す場合だけ画面内に寄せる。「－」「＋」はドラッグ開始と重ならないよう`mousedown`を止めている。
- 検証：疑似ページでオーバーレイを読み込み、0.7〜2.0で頭打ちになること、拡大しても画面内に収まること、ドラッグした位置と倍率がページ再読み込み後も復元されることを確認。PC81件成功。実サイトは未確認。
- PCはブラウザ取り込みの開き直しで反映（Android版は変更なし）。

### 共有フォルダを1か所に集約（2026-09-23）

利用者の要望で、アプリ間のデータ共有用フォルダを専用に用意した。
- 場所：`G:\マイドライブ\database共有`（GドライブはGoogleドライブ本体なので、このフォルダだけがDriveと同期される）。
- PC版の同期先（`data/settings.json`の`sync_dir`）を`G:/マイドライブ/data`からここへ変更。保存のたびに`database-backup-auto.json`が上書きされ、日付ごとの控えは`backups/`に7日分（`SNAPSHOT_KEEP_DAYS=7`、1ファイル約14MB）。変更前の設定はscratchpadの`settings.before_share.json`。
- フォルダに`このフォルダについて.txt`を置き、PC版の書き出しとAndroid版の読み込み手順を記載。
- Gドライブ直下に散らばっていた古いバックアップ（旧`data/`フォルダ48MB、Android書き出し2件、CSV1件、直下のJSON3件）を削除。**削除前に全ファイルの記録キー（店舗・日付・機種・台番号）を現在のDB2098件と突き合わせ、「今のDBに無い記録」が0件であることを確認済み**。Googleドライブのゴミ箱には30日残る。
- コード変更なし（設定と実データ側の整理のみ）。`PROJECT_STATUS.md.gdoc`は残した。

### Android：バックアップの名前を共有フォルダに合わせる（2026-09-23）

利用者から「固定名にして上書きにする？」という相談。共有メニュー（「ドライブに保存」）経由の保存は上書きにならず`(1)(2)`の枝番が付くだけで、真の上書きにはDrive APIとログイン連携が必要（方針上とらない）。PC版の`latest_backup_file`は名前ではなく更新日時の新しい順に読むため、固定名の利点は小さい。相談の結果、日時入りで分かりやすい名前にすることにした。
- `backup_service.dart`に`backupFileName(now, {source})`を追加：`database-backup-android-20260923-114005.json`。半角英数字とハイフンのみ（共有シートの件名がそのまま保存名になる先があるため）。差出元の文字列は英数字以外を除き、空なら`app`。
- 旧：`backup_2026-09-23T114012345.json`（一時ファイル名のまま共有していた）。
- テスト：`test/backup_name_test.dart`を追加（Android61件成功、analyzeは既存info8件のみ）。
- 共有フォルダ`G:\マイドライブ\database共有`には、PC版の`database-backup-auto.json`とこのファイルが並ぶ。古いAndroid分はたまるので、時々Drive側で削除する運用。
- APK未ビルド。

### Android：「過去の記録」に種別（ノーマルタイプ）の絞り込みを追加（2026-09-23）

利用者の要望。ChatGPTが入れた設定推測（ジャグラー2機種・ハナハナ4機種）を見比べやすいよう、「過去の記録」で系列ごとに表示できるようにした。
- `lib/normal_type.dart`（新規）：`NormalSeries`（juggler／hanahana）と`normalSeriesOf(machine)`、`recordsOfSeries`、`normalTypeRecords`、画面用の`HistoryType`（ノーマルタイプ／ジャグラーシリーズ／ハナハナシリーズ、`matches(machine)`）。機種名だけで判定し、半角カナ（`ｼﾞｬｸﾞﾗｰ`・`ﾊﾅﾊﾅ`）も見る。設定推測が対応していない同系列の機種もここには含まれる。
- `lib/main.dart`の`_HistoryPageState`に「種別」のプルダウンを追加（店舗・機種の隣、既定は「すべての種別」）。選ぶと機種のプルダウンもその種別だけに絞られ、選択中の機種が外れる場合は「すべての機種」に戻す。得点の計算をやり直す判定（`_scoredFor`）にも種別を含めた。
- テスト：`test/normal_type_test.dart`（4件）を含めAndroid68件成功、analyzeは既存info8件のみ。PC版は変更なし（84件成功）。
- 実機での見た目は未確認。APKはこのあとビルド。

### Android：結果タブと過去の記録を見やすくする（2026-09-24）

利用者の要望：「取り込みはやりやすくなったが、結果タブと過去の記録がとても見づらい」。困りごとは機種の切り替え・台一覧が長い・過去の記録のカード（スロットの機種が多いことが原因。端末の違いではない）。
- 結果タブ：機種のプルダウンをやめ、機種を選んでいないときは**機種一覧**（1機種1行：機種名・台数・最高点・グラフ未取得・平均点）を出す。7機種以上なら機種名の検索欄。機種を選ぶと、戻る（←、端末の戻るボタンも一覧へ戻る`PopScope`）・前後の機種（‹ ›）・「17 / 20機種」を上に出す。店舗・日付を変えると一覧へ戻る。店舗は短い名前（長町南・幸町）にして日付が「2026-09」で切れないようにした。
- 台は1台1枚の`ScoreCard`（展開式、削除）から、**1台1行の表**`RackTable`（台・回転・BIG・REG・持玉・点）へ。設定推測・設定情報・グラフ未取得は、ある台だけ2行目に小さく。暫定点は表の上に1回だけ断る。タップで`SavedGraphPage`（得点の内訳を含む）。翌日候補（仮）は表の下へ移した。
- 過去の記録：日付・店舗・機種ごとの大きな展開カードから、**日付の見出し（曜日付き・機種数・台数）→機種ごとの1行（店舗の短い名前・台数・設定情報の台数・平均点）**へ。タップで`HistoryGroupPage`（同じ表、台番号順／点数順）。設定情報の記録・削除は各行のアイコンから**長押しのメニュー**へ移した（画面に案内あり）。以前は得点を渡さずにグラフ画面を開いていたが、今は内訳も出る。
- 絞り込み：店舗・種別を1行、機種はプルダウンから**文字検索**へ（`list_views.machineMatches`：ひらがな→カタカナ、半角カナ→全角、全角英数→半角、大小文字・空白・`+`を無視）。半角カナの変換は`setting_estimate.foldHalfWidthKana`へ切り出して共用（設定推測の動作は変更なし）。
- 新規`lib/list_views.dart`（検索・機種ごとの集計`summarizeMachines`・日付ごとのまとめ`groupHistoryByDay`・`dayWithWeekday`）と`test/list_views_test.dart`（5件）。`ScorePill`に小さい版`compact`。
- テスト：Android 73件中72件成功。失敗1件は変更前から失敗している`scoring_test.dart`「303番台…」（Git管理外の実データ`assets/database_seed.json`が必要。空の例データでは該当行が無い）。analyzeは既存info8件のみ。Flutter 3.47.1（Linux）で実行。
- 見た目は、`observed_tables.json`の機種名などをもとにした架空データ（2店舗×3日、28機種）を360×780dpで描画して確認（撮影用テストはコミットしていない）。実データ・実機は未確認。Googleドライブの実データは、作業環境のネットワーク制限で取得できなかった。APK未ビルド。

### Android：結果タブをアナスロ型に（機種ごとのデータ表示／グラフ表示）（2026-09-24）

利用者がアナスロの機種別データ（スクリーンショット2枚。サイト本体は作業環境のネットワーク制限で未確認）を理想として提示。「機種ごとにデータタブ・グラフタブがあるのが見やすい。そこに推定設定・点数などのオリジナルを加えたい。翌日候補（仮）の一覧をとても分かりやすく」。利用者の選択：全機種を縦に並べる／表の列は確率3種・最大持玉・推定設定・点数／グラフ下はアナスロ同様＋点数。
- 結果タブ：店舗・日付 → **翌日候補（仮）** → この日のまとめ → **設置機種一覧**（タップでその機種の位置へスクロール）→ 全機種を縦に並べる。各機種の下に「設置機種一覧へ戻る」と「まとめて削除…」。一定量スクロールすると右下に「一番上へ」。前回選んだ機種があれば開いたときにその位置へ。機種を開く1機種ずつの表示（前の版）と点数順の並び替えは廃止（アナスロと同じ台番号順）。
- 新規`lib/machine_sections.dart`：`MachineSection`（見出し＋データ表示／グラフ表示のタブ）、`MachineDataTable`（台番号の列を固定し他は横スクロール。列：G数・BB・RB・合成確率・BB確率・RB確率・最大持玉・推定設定・点数。行は交互に色、最下行に緑の平均行。手入力の設定情報があれば推定設定の欄に優先表示）、`GraphGrid`（2列のカード：台番号・★・点数、グラフ、G数・BB・RB・合成、推定設定）、`NextDayCandidatesCard`（「9/24（木）の候補（仮）」：順位・台番号・機種・棒・「平均より+11」・過去何日分／データ量、上位10台＋すべて表示、判定できた機種数）。候補の台は表・グラフにも★。
- `SlumpTile`（旧`_SlumpTile`）・`ReconstructedGraphPainter`・`signedIndex`を`machine_sections.dart`へ移動（`main.dart`から`signedIndex`を再公開し、既存テストの参照はそのまま）。`RackTable`・`ProvisionalCandidatesCard`は置き換えて削除。
- `list_views.dart`に`hitRate`（当たり0は`1/0.0`ではなく`—`）、`rackAverages`（平均行：数は台の平均、確率は合計回転÷合計当たり）、`nextDayLabel`、`dayCandidates`（機種ごとの`provisionalNextDayCandidates`を集めて「平均より」の大きい順。同じ店舗・機種の記録に絞ってから渡し、全記録の走査を避ける）。候補の選び方・指数の計算自体は変更なし。
- 過去の記録：機種を開いた画面も`MachineSection`（データ／グラフのタブ、★、長押しで設定情報・削除）。
- テスト：`test/list_views_test.dart`に4件追加（計9件）。Android 77件中76件成功（失敗は従来どおり実データ前提の303番台1件）、analyzeは既存info8件のみ。架空データ（2店舗×6日、グラフ付き）を360×780dpで描画して確認。テスト描画では影の代わりに黒枠が出る（`debugDisableShadows`）ため「一番上へ」の見た目は実機で要確認。実データ・実機は未確認。APK未ビルド。

### Android：結果タブの見直し（速さ・操作感）（2026-09-24）

利用者の依頼で再点検。架空データ（2店舗×30日×20〜28機種、11,220台）で測ると、結果タブを開くのにテスト環境（PC・デバッグ実行）で約4.3秒かかっていた。内訳は画面の組み立て約3.5秒（全機種・全台の表を一度に作っていた）、翌日候補0.6秒、採点0.07秒。
- 結果タブを`ListView.builder`にし、機種は画面に近い分だけ組み立てる（先読み1200px、`scrollCacheExtent`）。機種一覧から未作成の機種へ飛ぶときは、表の行の高さが固定なのを使って`MachineSection.estimateHeight`で位置を見積もって`jumpTo`し、作られた近くの機種を起点に見積もり直して（最大5回）、最後に`ensureVisible`で合わせる。「設置機種一覧へ戻る」は先頭へ移ってから一覧に合わせる。データ／グラフの切り替えは画面外に出ても消えないよう結果タブ側で覚える（`MachineSection.graph`・`onGraphChanged`）。
- `nextDayIndex`の日付の絞り込みを`DateTime.parse`から文字列の比較へ（`YYYY-MM-DD`なので結果は同じ）。翌日候補0.63秒→0.09秒。
- 過去の記録の検索：機種名の判定を記録ごとから機種ごと1回へ。1文字あたり0.69秒→0.15秒。
- 表のマスを`Container`から`Ink`へ（下に白の`Material`）。行をタップしたときの波紋が見えるように。機種ごとに出る「まとめて削除…」を灰色に。
- 結果：開くまで約1.0〜1.3秒（テスト環境、フォント読み込みを含む）。機種一覧から最後の機種・途中の機種への移動と一覧へ戻る操作を、描画して位置が正しいことを確認。実機（リリース版）での速さは未計測。
- テスト：Android 77件中76件成功（失敗は従来どおり実データ前提の303番台1件）、analyzeは既存info8件のみ。APK未ビルド。

### Android：タブ名の色・機種名の全角表示・翌日候補7台（2026-09-24）

利用者の指示。
- 下のタブ：選んだタブの名前が白字（白い背景に溶けて見えなかった。以前からの不具合）→ `AppColors.carbon`。アイコンは青い丸の上なので白のまま（`theme.dart`）。
- 機種名：画面に出す箇所だけ半角カナを全角にそろえる（`list_views.displayMachineName`。機種一覧・機種の見出し・翌日候補・この日のまとめ・過去の記録・台の詳細・削除や設定情報の確認文・バックアップの重複確認）。保存している名前・取り込み画面の入力欄・照合・検索・削除の範囲は変えない。並び順も表示する名前の順に（`compareMachineNames`。半角カナの機種が漢字の機種より後ろに回っていた）。
- 翌日候補：最初に出すのを上位10台→7台。
- 確率の丸め：変更なし（四捨五入）。アナスロは 275.25 を 1/275.2 と表示（ちょうど半分のときの丸め方が違うと推測）。台の詳細画面など既存の表示も四捨五入なので、アプリ内の表示をそろえることを優先。違いはちょうど.x5になる台の表示0.1のみで、点数・推定設定・翌日候補には影響しない。
- 計算方法の変更の検証（変更前のコードをGitから取り出して比較、日本時間）：`nextDayIndex`は約2.4万台＋4日おきにしかない台112件で差0、翌日候補は540日分で一致、推定設定の機種判定は3,018件で一致。平均行はアナスロのスクリーンショット（12台）と一致。夏時間の考慮は不要（日本に夏時間はない、利用者判断）。
- テスト：`list_views_test.dart`に2件追加。Android 79件中78件成功（失敗は従来どおり303番台1件）、analyzeは既存info8件のみ。APK未ビルド。

### PC：翌日候補（仮）の答え合わせスクリプト（2026-09-24）

利用者の依頼「翌日候補の導き方が、予想→結果で合っていたか検討したい」。実データ（17.5MBのバックアップ）は作業環境から取得できないため、利用者の手元で動かす読み取り専用スクリプトを追加。
- `database/backtest_candidates.py`：PCの`data/database.sqlite3`を読み取り専用で開く（または`--csv`でAndroidの「CSVを共有」、`--json`でバックアップ）。各店舗・機種・日Dについて、D+1のデータがあれば、アプリと同じ`provisional_next_day_candidates`／`next_day_index`（D以前のデータのみ）で候補を出し、同じ台のD+1を答え合わせ。
- 物差し：D+1の当たりの軽さの順位（同じ機種・回転数が半分〜2倍の台の中、0〜100。指数と同じ定義）、上位4分の1に入った割合、D+1の合計点（CSVの「合計点」、PCのDBでは未計算）。候補と候補外（判定できた台）を比較し、同じ日・同じ機種の中で候補の印を入れ替える並べ替え検定（既定5000回）でp値。指数と翌日の順位の順位相関、比較用に「今日の当たりの軽さだけ」の順位相関。店舗別・データ量（少／中）別の内訳。出力は集計のみ（台ごとの結果は`--details`で`reports/`へ、Git対象外）。
- 検証方法そのものの確認（`tests/test_backtest_candidates.py`）：本当に当たりが軽い台がある架空データでは差+10超・p<0.01を検出、差のない架空データでは差が0付近。差のない架空データ80回で差の平均+0.07、p<0.05の割合5%（p値が正しく出ている）。未来の日の数字を変えても候補と指数が変わらない（未来の混入なし）。
- リポジトリ内の唯一の実データ（`observed_tables.json`、1機種14台×6日）では、比べられた候補12件・候補外29件で、翌日の順位は候補39.9／候補外53.6（差−13.6、p=0.91）。件数が少なすぎて結論は出せない。
- テスト：PC 21件中20件成功（`test_database`はこの作業環境に`tkinter`が無く読み込めない。変更前から同じ）。

プロジェクト全体はGit管理されていません。複数AIで継続作業する場合は、このファイルを更新し、変更前後の検証結果を追記してください。

### Git管理を開始（2026-09-23）

- private repository `https://github.com/imakurudev-eng/database.git` をコード・テスト・設計資料用の保管先として初期化した。
- 2026-09-23に初回コミット`d04d9b9`を`main`へpush済み。GitHub上で共同作業を始められる。
- 実データと端末固有の成果物はコミット対象外：`database/data/`、`database/reports/`、`.runtime/`、仮想環境、Android端末SQLite、実データ入りの`assets/database_seed.json`、APK・`build/`、および`sources/`。
- 新しい環境でAndroid版を起動する場合は、`database_android/assets/database_seed.example.json`を`database_seed.json`へコピーして空の初期データを用意する。既存端末のSQLiteとバックアップは別途保持する。
- Claudeを含む共同作業者は、変更前に`git pull --ff-only`、変更後に対象テストを実行してからコミット・pushする。実データはGitへ追加しない。

### PC版Windows EXEを生成（2026-09-23）

利用者の依頼で、PC版がEXEとして配布できるかを確認し、PyInstaller 6.22.3でメイン画面とブラウザ取り込み補助をそれぞれビルドした。PC版はブラウザ取り込みを別プロセスで起動する設計のため、1本に無理に結合せず、`database.exe` と `database-browser.exe` の2本を含む`database/bin/`配布とした。利用者は`database/bin/database/database.exe`を起動する。
- `app.py`と`browser_import.py`の凍結実行時のルート解決を修正し、`database/bin/database/`または`database/bin/database-browser/`から起動しても、既存の`database/data/`と`database/reports/`を参照するようにした。
- `app.py`は補助EXEを`database/bin/database-browser/database-browser.exe`から起動し、通常のPython実行時は従来どおり`browser_import.py`を起動する。ブラウザ側の確認プロセスも凍結EXE自身を再利用する。
- 生成物：`database/bin/database/database.exe`、`database/bin/database-browser/database-browser.exe`。WebView2・pythonnetの依存DLLを含むことを確認した。生成物・ビルドフォルダは`.gitignore`でGit対象外。
- テスト：`cd database && .runtime\Scripts\python.exe -m unittest discover -s tests`、84件すべて成功。PyInstallerの2本のビルドも成功。
- 未確認：実サイトを使った規約同意・HTML/SVG取り込み、別PCでのWebView2環境差。EXEが起動できることと既存DBを参照する処理は静的に確認済みだが、利用者環境での実操作確認が必要。

## 参考資料

- Flutter: https://docs.flutter.dev/
- webview_flutter: https://pub.dev/packages/webview_flutter
- sqflite: https://pub.dev/packages/sqflite
- Android Debug Bridge: https://developer.android.com/tools/adb
- 個別の配点・対象範囲・線形グラフ前提: 利用者指定（出典不明）

### バグ点検・追加修正（2026-09-22）

利用者の依頼により、既存機能のバグ候補を点検し、新機能は追加していない。実サイトへの接続・自動巡回・端末DBの変更は行っていない。

- Androidの抽出要求を`web_extraction_channel.dart`の1本のキューに統一し、ページ遷移・破棄・応答ID不一致・送信失敗・タイムアウト後に旧応答が次の要求へ混ざらないことを確認した。
- Androidの一覧・グラフ抽出で、日付の優先順をURLの`target_date` → 台リンクの`target_date` → 選択中の日付欄 → 未確定（保存拒否）に統一した。本文の更新日時は使わない。PCの抽出も同じ順序にした。実在しない日付（例2026-02-30）と日時を含む日付はAndroidバックアップ・確認画面で受け付けない。
- PC・Androidの表/グラフ抽出で、欠けた数値やゼロ線を0として捏造せず、欠損またはエラーとして扱う。低貸しのkind_code（5・10）は拒否する。機種名の行クリックはNFKC正規化後に`+`・空白を無視して照合する。
- Androidの再取り込みで既存の最大持玉・前日最終ゲーム・設定注記・グラフを失わないようにし、数値が変わった場合は古いグラフを無効化する。保存・削除・バックアップ取り込み・設定注記・取り消しを直列化し、取り消しのDB復元はトランザクションで行う。PCも保存/削除が失敗したときに既存の取り消し控えを上書きしないよう、成功後に控えを書き込む。
- AndroidのYouTube非表示で、表・日付選択・入力・SVG・canvasを含む枠を隠さず、隠した要素に対するMutationObserverの再処理を抑えた。

検証：PCの既存75件に追加の回帰テストを加えた（期待78件）。Androidは全テスト56件、抽出JS疑似ページ15件を実行し成功した。Flutter analyzeは新しいエラーなし（既存infoのみ）。PC全件は一時SQLiteの作成/後処理がこの実行環境の権限エラーになり、今回の再実行は未完了（追加テストを含む完全な78件成功は未確認）。前回までのPC75件成功記録は保持する。

未確認：実サイトのHTML変更・極端な通信遅延・実機WebViewの実ページ遷移・PCの複数プロセス同時操作。既知の仕様上の制限（深夜0時の日付表示、1回分のみの取り消し、極端な遅延時の案内）は変更していない。

APK：今回の変更を含むrelease APKは、Flutterの古い`C:\\Users\\keyan\\flutter\\bin\\cache\\lockfile`が残り、実行環境の承認利用上限でロック削除と再ビルドが拒否されたため未生成。既存の22:08 APKは今回の変更を含まない。
