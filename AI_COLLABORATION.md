# database AI共同作業メモ

## この記録の使い方（2026-11-01 月別に分割）

- 今月（2026年11月）の記録だけをこのファイルに、日付の古い順で置く。新しい記録は**末尾に足す**（上へ差し込まない）。
- 過去の記録は月ごとのファイルにある：[2026年9月](ai_collaboration/2026-09.md)、2026年10月は大きいので [1〜15日](ai_collaboration/2026-10-01_15.md) と [16〜31日](ai_collaboration/2026-10-16_31.md)。最初の全体メモ（目的と対象範囲・フォルダ構成・Android版の利用手順・採点仕様v9・実装上の重要事項・検証・現在の状態・参考資料。2026-09-17ごろから書かれたもの）は [ai_collaboration/overview-2026-09.md](ai_collaboration/overview-2026-09.md)。今も効いている決まりは `AGENTS.md` が正で、過去の記録の決まりと食い違うときは `AGENTS.md` に従う。
- 月が替わったら、前月分を `ai_collaboration/YYYY-MM.md` へ移し、上の一覧に足す。1か月分が約500KBを超えるときは、10月と同じく1〜15日・16〜末日に分ける。中身は変えない。CIは `.md` だけの変更では動かない。
- 他の文書にある「AI_COLLABORATION.md の〇〇の項」という参照は、見出しの文字で月別ファイルを検索する。GitHubのコミット固定リンク（`.../blob/<コミット>/AI_COLLABORATION.md#L…`）は分割前の版を指すので、そのまま読める。
- 分割で並べ替えた：もとは9/23〜10/28の記録が新しい順で上に差し込まれ、10/19以降の記録が古い順で下に足され、その間に最初の全体メモがあった。月別ファイルでは見出しの日付の古い順に並べ直した（同じ日の中は元の順）。見出しに日付が無い記録は、元の並びで直前（上）の記録の日付に合わせた。各記録の本文は変えていない。

## 【新しいアプリの設計：カメラで釘の間隔を推定する nail_gauge（設計のみ）】2026-11-01 Claude

- 依頼：利用者が設計依頼の文を貼り付け（末尾に「メモよう」）。Flutter・Androidで、盤面の写真に写るパチンコ玉（基準直径 初期11.0mm、公称と実測を区別）を基準に、ヘソ・ワープ周辺の釘の間隔を「約○mm（画像からの推定）」と出すアプリ。今回は設計書だけで、アプリ本体は実装しない。基準コミットは `7a9df13`（`database-ci` の main。Codexの共有カレンダーの3コミットを fast-forward で取り込んだあと）。
- 置き場所（AIの仮定、利用者は未確認）：このリポジトリの `nail_gauge/` に、`database_android` とは別のFlutterアプリとして作る。カメラ計測は既存の画面に対応するものが無いため。既存の作法（`theme.dart` の配色、`ChangeNotifier`、`sqflite`、`flutter_lints`、日本語の文言）は引き継ぐ。
- 作ったファイル（`.md` だけ。CIは動かない）：
  - `nail_gauge/docs/design.md`：製品仕様（段階1〜3、初期版の完成条件、対象外、未検証の仮説H1〜H8）、画面設計（Mermaidの遷移図、各画面の表示・操作・失敗時の戻り先）、計測処理（基本式、指標P/G/S/Eの区別、ヘソの測定位置の定義 `heso_head_inner`／`heso_head_center`／`free_two_point`、奥行き差・斜め・球の楕円化・歪み・ガラス・ぶれ・頭と軸の誤差の式と限界、無効・注意のコード、複数枚の集計、EXIF 1〜8と表示・拡大の座標変換、自動・手動共通の点の形式）、Flutter構成、保存形式（sqfliteのテーブル・JSON例・再計算・削除）。
  - `nail_gauge/docs/measurement-validation.md`：検証V0（合成画像）〜V6（実機）、調整用と検証用の分離、仮の目標と検証済み性能の書き分け、精度不足のときの分かれ道（条件の制限・相対比較・比だけの表示）。
  - `nail_gauge/docs/implementation-plan.md`：T0〜T13のタスクと完了条件、最初の作業、単体試験・実機確認、段階3へ進む条件。
- 設計で決めたこと：状態管理は `ChangeNotifier`（既存アプリと同じ、追加パッケージなし）。保存する点は「EXIFの向きを当てたあとの元解像度の画像座標（連続値）」だけ。画像は再圧縮せず保存し、位置情報は取らない（端末の画像にGPSがあれば除いて保存し直す）。精度・信頼度の数値は、検証が済んだ条件以外では出さない。
- 最大の不確実性（未検証）：①盤面上の玉を、測る釘の近く・同じ奥行きで、ぶれずに撮れるか（遊技していなければ玉は無く、遊技中は動いている）。②玉の中心と釘頭の奥行きの差（盤面からの釘頭の高さが不明）による倍率のずれ。③正面写真の釘頭の間隔と、玉が通る軸の間隔の違い（頭と軸の太さ・釘の傾き）。
- 未決：**実装を始める前に（T0）、`nail_gauge/` のコードをpushすると既存の全試験（約23分）が流れるため、`regression.yml` の `paths-ignore` に `nail_gauge/**` を足すか、別リポジトリにするかを利用者に聞く。** 仮の目標（0.1mm・0.2mm・0.3mm）は「何mmの違いを見分けたいか」を利用者と決めて見直す。店舗の撮影ルールに従う前提を画面に出す。
- 試験・ビルド：設計だけなので流していない。flutter create・実装・APK作成はしていない。
- push：日本時間 2026-11-01 00:05 で、送り先は正本 `imakurudev-eng/database`。正本の main（`e8d2fa0`）はこのコミットより196コミット遅れていて、その中にコード（.md 以外）がある。`tools/push_ci.py` の決まりで、日本時間の1日9時ごろまでは正本へコードを送れないため、**このコミットは手元だけで、9時以降に `py -3 tools/push_ci.py` で送る**（その送信で正本のCIが1回動くのは正しい）。

## 【nail_gauge を別リポジトリ keyanbaitian6-cell/nail-gauge へ移した】2026-11-01 Claude

- 利用者「別リポジトリに分ける」（前項の未決T0への回答）。非公開リポジトリ `keyanbaitian6-cell/nail-gauge` を作り（2026-11-01、`gh repo create --private`。表示は PRIVATE を確認）、設計書3つを `docs/` に移して push した（`73071d1`）。手元は `C:\Users\keyan\Documents\Codex\2026-09-24\a\work\nail-gauge`。
- 移すときに、置き場所の説明（design.md §0、implementation-plan.md §2・T0・§7、measurement-validation.md の1か所）を別リポジトリ前提に直した。中身の設計は前項から変えていない。新しいリポジトリには、このAGENTS.md から日本語・共有記録・試験とpush・撮影のルールを引き継いだ `AGENTS.md` と、`README.md`・`AI_COLLABORATION.md` を置いた。CI（GitHub Actions）は置いていない。
- このリポジトリからは `nail_gauge/` を消した。前項の `8a52ca1` には設計書の初版が入ったまま残る（未pushの手元の履歴で、書き換えはしない）。以後、このアプリの記録は nail-gauge の `AI_COLLABORATION.md` に書く。
- push：このコミットも `8a52ca1` と同じく、正本へは日本時間 11/1 9時以降に `py -3 tools/push_ci.py` で送る（正本が196コミット遅れていてコードを含むため）。

## 【11月のpush先切り替えを調査】2026-11-01 Codex

- 利用者「11月になりました。月代わりでpush先が変わりますが、不具合など起きないかどうか検討」。調査のみ。基準は手元main `92a68c3`、正本main `e8d2fa069f637661b94917c6b4da2df2937c395a`、database-ci/main `7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`。GitHub接続ツールと実Gitの `ls-remote` のSHAが一致。両mainは手元HEADの祖先（`git merge-base --is-ancestor` ともに終了0）。手元は正本より198コミット・最終差分271ファイル、database-ciより2コミット・最終差分AI_COLLABORATION.mdのみ先行。
- 実 `py -3 tools/push_ci.py --dry-run`：日本時間11/1 00:48に送り先を正本と正しく判定。両main包含を通過後、1日9時前のコード送信保護で意図どおり停止（終了1）。直近2コミットが文書でも、正本への未反映分にコードがあるので停止する。GitHubへの送信・設定変更はなし。制限内のDNS失敗を認証切れと混同せず、ネットワーク許可後のGit取得は両方成功。
- 残る弱点2点：`tools/push_ci.py` は開始時に一度だけ日付と送り先を決め、送信直前に再判定しない。また両mainを各1回確認した後の非送信側の同時更新は検知しない。時刻取得・Git操作を置換した模擬確認で2点を検証（実通信・送信なし）。1日/16日の0時をまたいだ実行や、Codex・Claudeの同時pushでは期間外への送信・履歴分岐の可能性がある。提案は送信直前の日付/両main再確認と、送信作業を重ねない運用。再確認だけで2リポジトリ間の競合を完全に排除できるとは扱わない。スクリプトは未修正。
- origin・main追跡先は正本のまま。11月前半には合うが、16日以降も裸の `git push` は正本へ送るため、既存指示どおりpush_ci.pyを使う。正本から新規複製した環境は、同期前にはtools/自体がない点にも注意。
- 最新コード `0e973ce` のCI https://github.com/keyanbaitian6-cell/database-ci/actions/runs/41188954889 は今回APIで3ジョブsuccessを確認。製品コード・既存送信スクリプト・CI定義はdatabase-ci/main以降変化なし。同じ全体試験・CIは再実行していない。CI定義に所有者固定条件・secret参照・公開処理はなく、正本の最初の同期は回帰ワークフロー1回・通常3ジョブを想定する。
- 公式 https://docs.github.com/en/billing/concepts/billing-cycles で従量利用の周期は月初00:00 UTC（日本時間9時）と確認。契約プラン・残枠・予算状態は未確認、金額算出なし。両mainのAPI保護状態はprotected:false。後半側Actionsはenabled:true、正本のActions設定取得は404・両rulesetsは403のため、正本のActions有効状態や全制限は確定できない。
- 詳細報告：`../outputs/push-switch-review-20261101/検討結果.md`。コード・全体AGENTS・Git設定・実データ・公開物は変更せず、この共有記録だけ追記。コミット・push・CI起動・公開・Google更新・APK作成/導入はなし。次の送信は日本時間9時以降に最新両main・正本利用枠を再確認し、利用者の明示承認後に1回だけ行う。日付境界・同時更新の改善は今回の依頼では提案にとどめる。

## 【月替わり送信の直前確認を実装】2026-11-01 Codex

- 続く利用者指示「では問題点について改善をお願いします」により、前項の2点を実装。基準main `92a68c3`。変更は `tools/push_ci.py`・`database/tests/test_push_ci.py` とこの記録のみ。前項の調査記録もこのチャットの変更として保持。
- 送信前に両mainを `ls-remote` で再照会。初回の取得SHAから変わっていれば、更新・削除・新設を含め停止する。照会失敗は空mainとして扱わず停止。追加は1実行につき各リポジトリへの1回の照会だけで、定期実行・ポーリング・CI起動は追加しない。
- 最終通信後に日本時間を取得し直し、送り先の期間または年月が変わっていたら停止。時計補正などで同じ送り先のまま1日9時前に戻った場合もコード送信を止める。確認モードにも同じ直前確認を適用。実運用は毎回実時計を読む。既存試験用の固定nowを維持し、新規試験はclockで時刻推移を与える。
- 通常の非強制push・両main包含確認・MarkdownのみのCI除外・月初9時前の制限・当日送り先の規則を維持。Git設定や全体AGENTS.mdは変更しない。最終照会後の非送信側更新や、実際のpush通信中の日付境界を原子的に禁止する仕組みではないため、別環境/AIとの同時pushと境界直前の開始は避ける。スクリプト説明にも同時pushの制約を追記。
- 検証：`py -3 -m unittest discover -s database/tests -p test_push_ci.py -v` が **14件成功、39.697秒**。既存7件を維持し7件追加。月初・16日・年末・翌月への中断（1試験内4ケース）、月初9時前への時計逆戻り、fetch後の送信先/非送信先更新、非送信側main削除、最終照会失敗、dry-run正常時と期間変化時を確認。Gitは一時ローカルbareリポジトリだけを使い、外部pushなし。両側の既存コミットが維持されることを検証した。
- 実GitHubの確認：`py -3 tools/push_ci.py --dry-run` を日本時間11/1 00:56に実行。正本を正しく選び、両main取得/包含確認後、9時前の保護で終了1。ここでは新しい最終確認まで到達しないため、その部分の動作根拠は上記ローカルGit試験。実際の送信成功を確認したとは扱わない。
- `git diff --check` 成功。アプリ・UI・CI定義に変更はなく、ビルド/公開の依頼もないため、Flutter・ブラウザ・全体ゲートを追加実行していない。現在の正本の利用枠・Actions設定は引き続き未確認。GitHubへのpush・CI起動・公開・Google更新・APK作成/導入は未実施。変更をローカルコミットへ保存し、pushは利用者の明示承認後に行う。

## 【保存診断：利用者のiPhoneでのP’s CUBE版の値（共有カレンダーでまとめて消した後）】2026-11-01 Claude

- 利用者がiPhoneのP’s CUBE版の閲覧ページの「更新・差枚の取得状況」の画面写真を送付（端末の時刻 8:56）。「今日共有カレンダーで誤入力してしまったからまとめて消してたあとの状況です」。以下は**利用者の画面の値**（AIは端末を直接確かめていない）。「Googleドライブの更新」の行は写真の外で読めない。
  - 保存領域 約1,566.2MBを使用／上限の目安 約39,321.6MB。保存の保護なし。
  - 本体（P’s CUBE）約20.5MB（21,498,013文字）。本体の保存先（`database-viewer`）：まだありません。P’s CUBEの保存先：2項目。日別キャッシュ 94日分（接続先1件・旧形式0件）。新しい日別保存：未使用。localStorage 609文字。
  - 起動時の読み込み：最後まで終わった1回・前回0.5秒・途中で終わった0回。
- 読み取り（Claudeの判断、未確認を含む）：
  - **メルヘン版（10/31）とは別の保存の箱らしい**：同じ配信元なのに、メルヘンの本体の保存先が「まだありません」、localStorage が609文字（メルヘン版は373,328文字）。iPhoneのホーム画面に置いたWebアプリは、Safariやほかのホーム画面アプリと保存が分かれるため、と考えると合う（利用者がそれぞれをホーム画面から開いているかは未確認）。そのため10/31の約210.6MBと今回の約1,566.2MBは同じものの増減ではない。
  - 約1.5GBは、中身の大きさ（本体約20.5MB＋日別キャッシュ94日分）に比べてかなり大きい。上限の約4%で容量の問題ではなく、ディスクの使用量なのでメモリ（落ちる原因）とも直接は別。原因は未特定。候補：P’s CUBEの本体は更新のたびに約20MBの構造化データを丸ごと書き直す（`web/pscube/viewer_bridge.mjs` の `write`）ので、Safari内部の保存ファイルに古い領域が残っている、キャッシュ（Cache Storage）など。今の診断は件数しか数えず、保存先ごとの大きさは出せない（Safariは内訳を出さない）。
  - 共有カレンダーでまとめて消したことが、この箱の使用量に関係するかは不明（共有カレンダーを同じホーム画面アプリの中で開いていなければ、別の箱）。
- 次の手順：数日おきに同じ画面の「保存領域」を見て、更新のたびに増えるか（例：約20MBずつ）を確かめる。増えるなら、P’s CUBEの本体の書き方（丸ごと書き直し）を段階Bと合わせて見直す。必要なら診断にキャッシュ（`caches.keys()`）の数を足す。
- GitHubへの反映：**保留**。11/1の手元のmainに、別のセッションの未送信コミット3件（`8a52ca1`・`92a68c3`・`187b74d`、nail_gauge の文書と `tools/push_ci.py` の変更）があり、このコミットを送るとそれも正本へ送ることになるため、このセッションでは送っていない。database-ci/main は `7a9df13`。

## 【9時以降の確認と取得結果の取り違え対策】2026-11-01 Codex

- 利用者「9時になりました」を受け、日本時間09:34に確認モードを実行。明示的なpush承認ではないため送信はしていない。初回は正本の初期取得値が `7a9df13`、最終照会が `e8d2fa0` と異なり、追加した保護で停止。直後の実ls-remoteでは正本 `e8d2fa0`・database-ci `7a9df13` のままだった。
- 原因調査：既存のremote_mainはfetch後の共有 `FETCH_HEAD` を読み、別fetchが割り込むと別リポジトリのSHAを返せる。一時ローカルGitで「正本fetch後に別fetchがFETCH_HEADを書き換える」再発試験を追加し、修正前は期待する正本SHAと異なり失敗することを確認。今回実際に割り込んだ書き込み元は特定できず、特定のAIや操作のせいとは断定しない。
- 修正：ls-remoteで得たSHA自体を `git fetch --quiet --no-tags --no-write-fetch-head <url> <SHA>` で取得し、そのSHAを返す。共有FETCH_HEADを読まず書かない。直前の両main再照会・時刻確認・非強制pushは維持。
- 再検証：`py -3 -m unittest discover -s database/tests -p test_push_ci.py -v` は **15件すべて成功、37.142秒**（既存14件＋取得取り違え1件）。修正により前回の14件の結果だけでは足りないため再実行した。全試験のGit送信先は一時ローカルリポジトリで、GitHubへのpushなし。
- 実GitHubの確認モードは09:35に成功（終了0）。正本を選び、両main包含・直前の再照会・現在時刻確認を通過、正本との差分271ファイル。確認中にClaudeの文書コミット `6af9a29` が手元へ追加されていたため、その履歴を保持して追加修正をコミットする。コード差分は本修正2ファイルだけ。
- この追加修正と記録をローカルへ保存。既存アプリコードの変更・ビルド・公開はなし。GitHubの利用枠残量・正本Actions設定は未確認。正本への送信は、後半の未反映履歴とnail_gauge/保存診断の文書・今回の改善を含むため、確定コミットを示して明示承認を得てから1回だけ行う。コード変更のCI想定は回帰1回・通常3ジョブ。

## 【Codex分を正本へ送信、Claudeへ引き継ぎ】2026-11-01 Codex

- 利用者「いまclaudeで未コミットのものがあります。とりあえずcodexのほうを終わらせましょう。その後claudeへの指示プロンプトを」により、直前に確認を求めたCodex分の送信を承認。日本時間09:38、`py -3 tools/push_ci.py 3f5e3b06b78d7ef43f27e49d699288ad9030817a` で正本mainを `e8d2fa0..3f5e3b0` へ非強制で1回更新した。database-ciには送っていない。
- 送信には10月後半の履歴・nail_gaugeの文書・保存診断記録6af9a29・今回の送信保護187b74d/3f5e3b0を含む。確認時点の追跡済みファイルに未コミット/ステージ済み差分はなく、既存の未追跡ファイル5件はそのまま保持。別環境やその後のClaude作業まで存在しないとは判断しない。reset/clean/stash・Claudeの変更のコミットは行っていない。
- 正本CI **41257657501** は対象 **3f5e3b06b78d7ef43f27e49d699288ad9030817a** で開始、初回確認はin_progress： https://github.com/imakurudev-eng/database/actions/runs/41257657501 。成功と未確定の状態を混同しない。試験15件はローカル成功済み、CI再実行なし。
- Claudeへの引き継ぎプロンプトは `../outputs/push-switch-review-20261101/Claudeへの指示プロンプト.md`。未コミット変更の保護、両mainの確認、送信済み範囲、残る同時更新の制約、同じCI実行の結果確認、次のpush承認範囲を明記した。Claudeへメッセージを直接送信していない。Web公開・Google更新・APK作成/導入なし。

## 【11/1 9:34の取得結果の取り違え：書き込み元はClaudeのfetchとみられる】2026-11-01 Claude

- 前項のCodex記録「9時以降の確認と取得結果の取り違え対策」で「今回実際に割り込んだ書き込み元は特定できず」とした件。Claudeのこのセッションの操作と時刻・値が一致するので記録する。
- Claudeが同じ作業コピー（database-main）で実行したもの：日本時間09:33に `python tools/push_ci.py --dry-run`（P’s CUBE版の保存診断の記録を送れるか確かめるため。表示「日本時間 2026-11-01 09:33 → 送り先 正本」、送信なし）。続けて09:34ごろ、手元の新しいコミットの出どころを調べるため `git fetch -q https://github.com/keyanbaitian6-cell/database-ci main`（共有の `FETCH_HEAD` を database-ci/main `7a9df13` で上書き）。同じころ記録コミット `6af9a29` を作成。
- Codexの09:34の確認モードは「正本の初期取得値が `7a9df13`」で停止しており、正本をfetchしてから `FETCH_HEAD` を読むまでの間に、Claudeのfetchが `7a9df13` を書いたと考えると値と時刻が合う。Claudeはこのとき、Codexが同じ作業コピーで送信の準備をしていることを知らなかった。実害はなし（Codexの追加した直前の再照会で停止し、何も送られていない）。
- Codexの修正 `3f5e3b0`（`ls-remote` のSHAを `fetch --no-write-fetch-head <url> <SHA>` で取得し、共有の `FETCH_HEAD` を読まない）は原因に合っている。このPCのGit 2.55.0.windows.2 が `--[no-]write-fetch-head` に対応することを確認（`git fetch -h`）。
- 残る問題と運用の提案：2つのAIが同じ作業コピーで同時にGitを触ること自体（確認中のコミットの割り込み、`index.lock` の衝突、相手の作業中ファイルの巻き込み）は `push_ci.py` の中では防げない。**一方のAIが送信の準備（取得・確認・送信）をしている間、もう一方は fetch・commit・push（確認モードも含む）をしない**。Claudeは今後、別のAIが作業中と分かっているときはGitの状態を変える操作をしない。利用者からCodexの作業中と聞いた後の確認は `git ls-remote`・`git log`・`gh` など、作業コピーに書かない操作だけで行った。
- 正本CI https://github.com/imakurudev-eng/database/actions/runs/41257657501 （対象 `3f5e3b0`）：この記録の時点で pc (ubuntu) 成功、full と pc (windows) は実行中。再実行はしていない。
- GitHubへの反映：このコミットは手元のみ。手元のmainには、Codexの引き継ぎ記録 `8c7d94a`（未送信、Codexは無断送信しないよう依頼）が先にあり、このコミットを送るとそれも正本へ入るため、利用者の承認を得てから `tools/push_ci.py` で送る（どちらも .md だけでCIは動かない）。

## 【正本CI 41257657501（3f5e3b0）の full 失敗の調査：試験の時間切れ・再実行なし】2026-11-01 Claude

- 結果：https://github.com/imakurudev-eng/database/actions/runs/41257657501 は pc (windows) 成功・pc (ubuntu) 成功・**full 失敗**。再実行していない。
- 落ちたのは `test_recommendations_browser` の「viewer・393px」1件だけ（同じ試験の share 3幅・viewer 320px/1280px は成功）。`tool/test_recommendations_browser.mjs:57` で「長町南のイベント履歴」を押したあと、`getByRole('button', {name: /4台構成/})` が30秒以内に出ず `TimeoutError`。失敗時の画面の文字は元の画面（「Googleドライブから自動で読み込み：82台・09:50に最新か確認」を含む）のままで、イベント履歴の画面に切り替わっていなかった。
- 日付（11/1）が原因ではないと判断した根拠：①閲覧ページのコード（`database_android/lib`・`web`）は、ゲートが通った `fda78db` から `3f5e3b0` まで変わっていない（変わったのは `share_viewer/` だけ）。②日本時間11/1 10時ごろ、手元でゲートの閲覧ページ（`/c/w/cbw-diag1/viewer`）と今の `share_viewer/` を使って同じ試験を流し、6件すべて成功（閲覧ページは1件9〜12秒。CIでは29〜37秒）。③同じ日付で、viewer の320px・1280px は CI でも成功。
- 原因の見当（未確定）：「長町南のイベント履歴」は `_openEventHistory` で必ず画面を積む（押せない状態は無い）。押したのに切り替わっていないので、押した瞬間にGoogleドライブの更新（`_refreshFromDrive`。試験はDriveの応答を模擬しており、開いた直後に更新が走る）の「更新中」表示の出入りで配置がずれ、ボタンの外を押した競合とみられる。CIの実行がふだんより遅く、393pxだけで当たった。直近 database-ci・正本の約40回のCIでこの試験が落ちたのは今回が初めて。10/31の保存診断（`fda78db`）で `_start`・`_refreshFromDrive` に記録の区切りの待ち（`markViewerPhase`）を足しており、更新が終わる時刻がわずかに遅れて競合が起きやすくなった可能性は否定できない（同じ変更を含む database-ci の `d5fb892` では full 成功）。
- 対処の案：試験側で、開いた直後のDriveの更新が終わる（「最新か確認」の表示が出る）のを待ってから「長町南のイベント履歴」を押す。製品の動作は変えない。コードの変更なのでCIが1回動く（正本、約23分）。利用者の判断待ち。full のログでは86段のうち85段が OK、失敗はこの1件だけ（集計「失敗 1 件：test_recommendations_browser」）。full 全体としては失敗のまま扱う。
- このコミットは手元のみ（.md）。次に送るときに一緒に送る。

## 【4大オススメの画面試験の競合を修正（正本CI 41257657501 の full 失敗への対処）】2026-11-01 Claude

- 依頼：前項の調査に、利用者「試験を直す」。変更は試験だけ（`database_android/tool/test_recommendations_browser.mjs`、コミット `00ef938`）。製品の動作・照合版は変わらない（試験ファイルは照合版の計算の対象外）。
- 変更：閲覧ページを開いたあと、「Googleドライブの最新を確認しています…」が消え、「〜に最新か確認」が出るまで待ってから「長町南のイベント履歴」を押す（`driveSettled`、最初に開くときとリロード後に開くときの2か所）。
- 手元の確認：ゲートの閲覧ページ（`/c/w/cbw-diag1/viewer`、`fda78db` と同じ閲覧ページのコード）と今の `share_viewer/` で、この試験を2回流し、2回とも6件すべて成功（閲覧ページ1件9.6〜12.1秒）。元の競合をわざと再現しての確認（CPUを遅くするなど）はしていない。全体ゲートは流していない（試験1ファイルだけの変更で、ビルドもしないため。CIの full で確かめる）。
- 送信：`tools/push_ci.py` で正本へ1回（このコミットと前項の記録 `81181cc` を含む）。CIの結果は次の追記。
- 追記（CI）：`618a325`（試験の修正 `00ef938` を含む）は正本 https://github.com/imakurudev-eng/database/actions/runs/41259394567 で full・pc (windows)・pc (ubuntu) の3ジョブとも成功。full は86段すべて OK（ALL PASSED）、`test_recommendations_browser` も成功。再実行なし。前回 41257657501 の full 失敗は、この修正後の実行で解消した。

## 【databaseアプリの最近の課題の初回調査・カメラ対象外】2026-11-01 Codex

- 依頼：カメラアプリは対象外として、databaseアプリの最近の課題・修正点・改善点の検討を始める。調査・提案のみ。基準は手元＝正本main `4d02b9181905311fa4fd976f3d0585a1c6623e73`、database-ci/main `7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`。`ls-remote` と祖先確認で両履歴を含むことを確認し、共有FETCH_HEAD・ブランチは変更しなかった。
- 詳細は `DATABASE_REVIEW_20261101.md`。直近CI 41259394567の3ジョブsuccessをGitHub APIで直接確認。618a325以降の差は記録1行だけ。両リポジトリのopen Issueは検索0件だが、不具合なしとは扱わない。
- 新しい修正候補：P’s CUBEの自動完了後に手動取得が入ると、古い `completed` が残り、残り3件でも窓を閉じる処理が呼ばれる。既存 `CloseWhenFinishedTests` の偽窓・時計・一時フォルダーを使い、`database/.venv/Scripts/python.exe -B -` で模擬順序を1回実行し確認（終了0）。実データ・実サイトは不使用。再現コードは報告に掲載。実WebView2での頻度は未確認。10/31の「窓が閉じなかった」観察とは別の問題で、そちらの原因は未特定。
- 継続候補：P’s CUBEの停止理由を区別できる記録、iPhoneの保存量・更新時間の同条件での観察と日別保存への段階移行、候補比較の入力完全性点検と評価準備。iPhoneの約1.5GBの原因、10/31と11/1の保存環境の同一性は未確認。診断の終了回数は成功回数・クラッシュ回数ではない。11/7の段階B検討予定を尊重し、今回移行しない。店舗別比較の途中成績は算出せず、11/26以降の1回評価の計画を維持。別の★注目最終評価は実行済みか不明のため、再実行しない。
- 共有カレンダー7項目は後続の修正・公開記録を参照して修正済みと区別。利用者に再び同じ修正を勧めない。今回の公開版・実機再確認は無し。
- 製品コード、DB・設定・Cookie・端末保存、Google・公開物は変更していない。実機操作・同期・本番接続・コミット・push・CI起動・ビルド・公開・APK作成/導入なし。変更は報告とこの記録のみ。既存成功試験は再実行せず、新規の模擬再現のみ。記録は手元のみで、GitHubへ未反映。

## 【P’s CUBEの自動完了後の手動保存で古い完了状態を解除】2026-11-01 Codex

- 利用者が前の検討の1番を選択。基準は引き続き手元・正本main `4d02b91`、database-ci/main `7a9df13`。両mainを読み取り専用で再照会して変更がないことを確認。詳細は `DATABASE_REVIEW_20261101.md` 末尾。
- `database/pscube_import.py`：保存の入口で `capture_started()` を呼び、自動OFFの手動保存なら古いcompletedを解析・保存前に解除。保存が失敗しても解除を維持。終了判定と保存開始は同じcapture_lockで直列化し、保存中は終了判定を飛ばす。終了失敗時もfinallyでロックを解放。正常な自動完了の終了条件は維持。
- `database/test_pscube_auto.py`：新規3メソッド（各成功／失敗の2条件）。実際のBridge保存入口での解除、手動保存後に残り3件でも閉じない、保存中に終了判定しない、終了時にロック保持・例外時も解放を模擬確認。修正前の入口試験は古い完了が残り失敗した。
- 確認：P’s CUBE関連4モジュール86件＋自動取得共通33件成功。最初の統合コマンドは共通試験のモジュール指定を誤り、86件成功後に読込エラー1件で終了1。パスを正して共通33件のみ実行し成功（成功済み86件の再実行なし）。TZ=JST-9、実測UTC+09:00。照合版5d3f5598f3d9を既存生成スクリプト3本で生成し、12ファイルは版の文字だけ変更。JSの版・配布一致15件成功。Google貼替・Web公開は不要。
- 利用者から2番の原因は「IPではじかれていた」と判明したとの報告。利用者確認として記録し、10/31の窓が残った原因調査候補は解決扱いに更新。AIによる当時の応答・画面確認はない。3番は毎日同条件で診断値を記録する方針。実装・予約を追加せず、移行も開始しない。
- 実DB・設定・Cookie・端末保存は変更なし。対象サイト接続・実機操作・同期・CI起動・push・ビルド・公開・Google更新・APK作成/導入なし。実機での再現頻度・修正確認は未実施。全体ゲートは今回のPCソース修正・模擬試験の範囲では実行せず、公開・ビルド時には規定のゲートを通す。

## 【database全体の改善点の見直し（調査のみ）】2026-11-01 Claude

- 依頼：利用者「database全体をみて改善点がないかどうか検討を」。同日朝のCodexの調査（最近の不具合4件）と重ならない、構造・試験・文書・作業環境を見た。基準は手元main `0787314`（Codexの未pushのP’s CUBE修正を含む）。
- 詳細は `DATABASE_REVIEW_20261101.md` 末尾「全体の見直し（Claude）」。要点：A 採点・翌日候補のPC（`core.py`）とAndroid（`scoring.dart`）の照合が毎回の試験に無い（照合ツールは実データを使う手動のみ）→ 合成fixtureで両側を確かめる案、B メルヘンの読み取りJSがPCとAndroidで二重、C PC試験の置き場所が2か所でREADMEの手順では15ファイル抜ける、D READMEの「自動巡回・自動保存はしない」が現状と不一致、E `AI_COLLABORATION.md`（約1.35MB）と日付入り文書の肥大→月別保管の案、F 一時フォルダー・未追跡ファイル・取り込み済み作業ツリーの残り、G 例外の握りつぶし、H 大きいファイル。
- 変更は上の2つの.mdだけ。製品コード・試験・DB・設定は変更なし。試験・ゲート・CI・ビルド・公開・対象サイトへのアクセスなし。ファイル・作業ツリーの削除もしていない（利用者の了承待ち）。
- 秘密情報：追跡中のファイルで鍵・トークン・デプロイIDの形を検索し、該当なし。

## 【READMEの試験手順と自動取り込みの説明を直す（全体見直しのC・D）】2026-11-01 Claude

- 依頼：前項の全体見直しのうち、利用者「C・DのREADMEを直す」。変更は `README.md` だけ（.mdなのでCIは動かない）。
- C：PC試験の手順に `database/` 直下の `test_*.py` を足した（`.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"`）。ビルド前は `check_before_build.sh` の「ALL PASSED」が条件であることも書いた。確認：`database/.venv/Scripts/python.exe` で `TestLoader().discover` を使い、試験を実行せず読み込みだけで数えた。`-s . -p "test_*.py"` は直下の15モジュール・239件（`tests/` に `__init__.py` が無いため `tests/` は含まない）、`-s tests` は501件。読み込みエラーなし。試験そのものは流していない。
- D：「実サイトの自動巡回や自動保存は行いません」を削除し、「自動取り込み」の節を追加。内容は `database/PSCUBE_AUTO_CAPTURE.md` から：起動時OFF・利用者がONにしたときだけ・ON状態は保存しない、開いた取り込み画面で読んで保存し次の未取得へ、間隔（メルヘン0.1〜4.5秒・初期3.5秒、P’s CUBE15〜25秒ランダム）、人間確認・同意・読み込み中は押さずに待つ、P’s CUBEの自動OFF条件、Android版P’s CUBEの0時予約。仕様は変えていない。
- 製品コード・試験・DB・設定は変更なし。対象サイトへのアクセスなし。

## 【共有記録を月別に分割（全体見直しのE）】2026-11-01 Claude

- 依頼：利用者「その前にAIコラボレーションを分割化しましょう」（全体見直しのE。Aの照合試験より先に）。
- 分割前：`AI_COLLABORATION.md` は約1.35MB・4,713行・見出し387件。9/23〜10/28の記録は新しい順で上に差し込まれ、10/19以降は古い順で下に足され、間に最初の全体メモ（目的と対象範囲〜参考資料の9節）があった。
- 分割後：`AI_COLLABORATION.md`（11月分14件と使い方、約37KB）、`ai_collaboration/2026-09.md`（42件）、`ai_collaboration/2026-10.md`（322件、約1.08MB）、`ai_collaboration/overview-2026-09.md`（最初の全体メモ9節）。各月は見出しの日付の古い順（同じ日は元の順）。見出しに日付の無い11件は、元の並びで直前の記録の日付に合わせた（10/2が3件、10/16が2件、10/17が1件、10/25が5件）。
- 方法：スクラッチの使い捨てスクリプト（リポジトリに入れていない）で、コードブロックの外の `## ` 見出しごとに記録を切り出し、分割後に全ファイルから切り出し直した記録の集合が分割前と完全に一致することを確かめた（387件）。改行はCRLFのまま。
- 途中の誤り：最初の実行では、作業ツリーの一部の行がLF（私が heredoc で足した記録など）だったため、CRLFだけで行を切ったところ11/1の2件（nail_gauge）が見出しと認識されず10月の記録の本文に入った。月の境目の確認で気づき、元に戻して改行をそろえてから分け直した。上の件数は直した後のもの。
- あわせて変更：`AGENTS.md` の共有記録の節に「今月分だけを置き、末尾に足す。月が替わったら最初に作業したAIが前月分を移す」を追加。`database_android/AGENTS.md` の参照先に `ai_collaboration/` を追加。他の文書の「AI_COLLABORATION.md の〇〇の項」という参照は書き換えず、冒頭の使い方に「見出しで月別ファイルを検索」と書いた。GitHubのコミット固定リンク（`DATABASE_REVIEW_20261101.md` の `#L4007` など）は分割前の版を指すのでそのまま有効。
- `.md` だけの変更なのでCIは動かない（`push_ci.py` の `docs_only` は拡張子で判定し、新しいフォルダーの `.md` も対象）。製品コード・試験・DBは変更なし。
- 残る課題：10月分は約1.08MBと大きいまま。必要なら月の前半・後半に分けられる（利用者の判断）。
- 追記（同日）：利用者「10月分は分割してください」。`ai_collaboration/2026-10.md` を `2026-10-01_15.md`（151件、約427KB）と `2026-10-16_31.md`（171件、約654KB）に分けた。見出しに日付の無い記録は、分割時と同じ判定（分割前の版 `32ab5f4` での直前の記録の日付）で振り分けた。並びは変えず、2つを合わせた記録の集合が元の322件と一致することを確かめた。冒頭の使い方と `AGENTS.md` の案内も更新（約500KBを超える月は半月ごとに分ける）。

## 【全体見直しのB・C・F・G・Aの対応と、Android 0.5.49のビルド】2026-11-01 Claude

- 依頼：利用者「Bについて…なぜふたつあるのか」「Cは…まとめて大丈夫そうなのであればまとめて」「Fは問題なさそうなのであれば片づけて」「G、エラーは記録報告修正改善お願いします」「Ｈ…ご教授ください」、続けて「この間にandroid用ビルドしておこうか」「その間にAを終わらせるか」。基準は手元main（正本 `4d02b91`・database-ci `7a9df13` の両方を含むことを `ls-remote` と祖先確認で確認）。
- B（回答のみ・コード変更なし）：メルヘンの読み取りは、最初のリポジトリ（`d04d9b9`、9/23）からPC `browser_import.py` とAndroid `web_import_page.dart` に別々にある。Android版が先にあり、9/18にPC版へ同じ方式を書き写したため。P’s CUBE（10/1）は後から作ったので最初から1つの生成元（`build_pscube_capture.mjs`）にした。Android側のメルヘン取り込みは、PCを起動していないときにAndroid→Driveバックアップ→Google（`meruhen_cloud_sync.gs`）→閲覧ページ・共有へ届ける経路の入口でもある。削除や統合は利用者の判断待ち。
- C：`database/test_*.py` の15ファイルを `database/tests/` へ移した（`git mv`）。`__file__` からの相対パス5か所（html_converter・Androidのfixture・`test_tk_threads` の作業フォルダー）を直し、`test_tk_threads` の子プロセスには `PYTHONPATH` に tests/ を足した（移した直後の全体試験で、この1件だけ他の試験ファイルを読めず失敗→修正後成功）。CI（`regression.yml`）と `check_before_build.sh` の「直下を流す」手順を削除（ゲートの `pc-pscube-tests` 段も無くなり `pc-tests` に統合）。README・DEVELOPMENT_CHECKS・AGENTS・PSCUBE_SYNC・Dart/JSのコメントの置き場所の記述を更新。
- F：ごみ箱へ移した（復元可能）：ルートの `rows.json`（10/18 誕生日抽出の作業用元データ）・`debug.log`（10/14 WebView2のログ）・`screen-now.png`（10/27）・`review_packages/`（10/25の試験ログ）、`database/tmp*` 7個（試験の一時DB。10/20〜22）、mainに取り込み済みの作業ツリー `../ci-bash-fix-20261021`・`../event-history-next-rack`。取り込み済みのブランチ6本を `git branch -d` で削除（fix/windows-project-python-bash-20261021、event-history-next-rack、event-calendar、feat/variety-face-insert、fix/pscube-anaslo-count、focus-final-evaluation）。`CLAUDE_HISTORY_VIEW_HANDOFF_20261022.md` は10月の記録から参照されているので、消さずに `ai_collaboration/` へ移してコミット。
- F（残したもの）：`.claude/worktrees/charming-carson-f7762b`（取り込み済み・未コミットの変更なし）は「別のプロセスが使用中」でごみ箱へ移せなかった。別のClaudeセッションが開いている可能性があるため触らない。`../database-viewer-efficient`（`codex/viewer-drive-efficient-20261004`、10/4のCodexの未取り込みコミット `e55606a`、`git cherry` で未反映）は残した。`../outputs/share-android-release-20261014/source`（共有ページのAndroid版の配布元、取り込み済み）は outputs 内の配布物なので残した。
- G：PCに `database/error_log.py` を追加。取り込み窓の見張り・表示の処理で黙って捨てていた7か所（P’s CUBE：表示の差し込み・自動の1回分・終了判定、メルヘン：自動表示・URL読み取り・表示の差し込み・自動の1回分・終了判定）を、`data/errors.log` に「時刻・場所・例外・発生行」を残してから続ける形にした。同じ場所・同じ内容は60秒に1回、256KiB超で1世代だけ残す。記録の失敗では止めない。Cookie・入力値は書かない。動作（続ける・止める）は変えていない。Androidは自動取り込みの常駐を止める処理の失敗3か所を `debugPrint` で端末ログに残す形にした。埋め込みJS内のURL解析・localStorageの `catch` と、PCの前面表示・YouTube遮断の登録失敗は、データに関係しないので変えていない。画面への表示は追加していない（表示に出すなら対象画面を利用者に確認する）。試験 `tests/test_error_log.py` 5件。
- 照合版：`build_release_info.py`→`build_viewer_parts.mjs`→`build_event_history_share.mjs` で `e65ab3afdebc`。`build_pscube_capture.mjs` も実行し、生成済みの `assets/pscube_capture.js`・`pscube_auto_probe.js` が10/27の版 `09e2c8670954` のままだったのを更新（差は版の1行のみ）。Googleの4本の `.gs` も版の文字列だけ変わる。処理は変わっていないので貼替は不要（版表示が「Google処理の版」と食い違うだけ）。
- ゲート：`60fdb6b` の内容（版の資産2行を除く）で `bash database_android/tool/check_before_build.sh` を実行し **ALL PASSED**。PC 745件（統合後の1段）、UTC条件27件、Flutter 750件、analyze は情報28件（エラー・警告0。変更した2ファイル単体は0件）、JS 77本。`TZ=JST-9`、ログ `/c/w/gate-g1101.log`・`/c/w/cbw-g1101/`。ゲート後に再生成した資産2行に関係する `test_release_info`・`test_pscube_net_capture`・`test_pscube_absent_tab_auto`・PCの `test_pscube_auto*` を再実行し成功。
- APK：`DATABASE_ANDROID_CLONE=original` で通常版 `0.5.49+2026110101`、versionCodeを上げて `pscube` で P’s CUBE版 `0.5.49+2026110102` を作成（`flutter build apk --release --no-pub`）。`database_android/build/releases/0.5.49/` に `database-0.5.49-2026110101.apk`（96,522,277バイト、`com.keyan.database_android`、表示名 database、SHA-256 `ec846d87f412f0a424ce8205f4409da1001812768e49f62fea825950fae3e2d8`）、`database-pscube-0.5.49-2026110102.apk`（96,522,301バイト、`com.keyan.database_android.pscube`、表示名 database P’s CUBE、SHA-256 `5da41a564c042a4fb444fd78139c723f1fab73161d881188165f2fc813d84736`）。aapt2で版・ID・表示名、apksignerで署名を確認（証明書SHA-256 `4332fcb9…a047`、0.5.48と同じ）。`SHA256SUMS.txt`・ビルドログを同じフォルダーに保存。版番号のコミット `45bead3`。端末 `RFGL146LVVW` は読み取りのみ：両方とも0.5.48（2026102704／2026102705）で、新しい版番号の方が上。インストールはしていない（利用者が行う）。0.5.47・0.5.48のAPK4本をごみ箱へ移した。
- A：`database/tests/test_scoring_parity.py`（PC）と `database_android/test/scoring_parity_test.dart`（Android）を追加。乱数の種を固定した合成データ（2店舗×16日×18台＝576台×日、実データではない。未稼働・500G以下・88888888・グラフ無し・最大持ち玉無し、4台以上の機種とバラエティを含む）から、PCで採点（`score`）と翌日候補（`day_candidates`）を計算して `database_android/test/fixtures/scoring_parity.json` に保存（採点あり493、候補147）。PCは保存した期待値を自分で再計算して一致、Androidは `scoreRecord`・`dayCandidates` で同じ期待値と一致（PC 3件・Flutter 3件成功）。捕まえられるかの確認：Dartの `shrinkGames` を1500→1501にするとAndroid側が失敗、PCの `SHRINK_GAMES` を同様に変えるとPC側が失敗（どちらも `git checkout` で元に戻した）。仕様を意図して変えたときは `database/` で `python tests/test_scoring_parity.py --write`。照合版の計算には試験・fixtureは含まれないので、APKとの差は無い。A自体の全体ゲートは未実行（追加は試験2本とfixtureだけ。CIの full で流れる）。
- H：回答のみ（大きいファイルは一度に分けず、触るときに関係する部分だけ切り出す方針を説明）。
- push：未実施。手元の未push分はCodexの `0787314` を含む。送るとCI（正本、約23分）が1回動く。利用者の判断待ち。

## 【全体見直しの利用者の決定（B・H）と、入れ替え時のエラー記録の範囲】2026-11-01 Claude

- 利用者の決定：B「そのまま残してください」→ メルヘンの読み取りはPC・Androidの2つのまま（統合・削除しない）。H「大きくても問題がないなら分割やめよう」→ `core.py`・`main.dart` などの大きいファイルは分割しない。
- G：利用者「PC版は特に気を付けよう。取り込みのメインだしね。今後も新台追加とか台番号が変わったときに毎回エラーがでているので修正に役立ちます。ちなみに明日も入れ替えがあるから気を付けよう。11/1の取り込みまでは大丈夫」。11/1分の取り込みが問題なかったことは利用者の報告（AIは未確認）。**11/2に入れ替えがある**（店舗は未確認）。
- 確認した範囲（コードを読んだだけ）：60fdb6bの `errors.log` は、見張り処理で以前黙って捨てていた例外だけを残す。入れ替えのときに画面に出るエラーは残らない。P’s CUBEは保存の入口 `Bridge.submit_page` の例外と読み取り途中の `capture_failed` が画面表示と `AutoPilot.finished(error=...)` だけ、メルヘンは保存の子プロセス（`--confirm-*`）の例外が `traceback.print_exc()` とエラー窓だけ。これらも `errors.log` に残すかは利用者に確認中。
- PC版はこのフォルダーのソースを `start.cmd` から起動し、取り込み窓は開くたびに新しいプロセスなので、60fdb6b（errors.log）とCodexの0787314は、次に取り込み窓を開いたときから使われる（どちらも全体ゲートALL PASSEDの内容）。
- A（回答のみ）：当日の実績点（v12、9/29決定）は、その日の結果を同じ機種の過去30日と比べた記録の物差しで、予測ではない。実際の設定という正解が無いので的中率で検証する対象ではなく、今すぐ見直す根拠は今回見当たらない。ただし翌日候補の★注目（`next_day_focus`）は当日の実績点を材料に使う。翌日候補を見直すときは点の使い方が検討対象になりうる（採点そのものを変えるかは別の判断）。P’s CUBEの採点（`web/pscube/scoring.mjs`）は別の実装で、今回は見ていない。

## 【入れ替えの日に出る失敗・警告もPCの errors.log に残す（11/2の入れ替え前）】2026-11-01 Claude

- 依頼：前項の質問に利用者「今日のうちに足す」。途中で利用者「新台入れ替え後に何回か出た前回までの失敗をちゃんと把握できているんだよね？」→ その時点では把握していなかった（コードの出どころだけ調べていた）と回答し、共有記録から過去の入れ替え後の失敗を洗い出してから範囲を決め直した。
- 過去の入れ替え後の失敗（どれも修正済み）：10/5 P’s CUBE 新台の空の過去列で「数値が未表示か不正です」で停止／10/11 メルヘン「該当する台情報が見つかりませんでした」で停止／10/19〜22 P’s CUBE 新台の全台一覧に取り込み日のタブが無く自動が待ったまま／10/21・10/23 P’s CUBE 新台の空のグラフ系列で差枚が未取得（全日・巻き添え）／10/27 P’s CUBE 機種一覧が前回より少なく読めた。
- 変更（PCのみ・動作は変えない）：`error_log.note()`（画面に出した文だけを残す）と `record(..., detail=)`（例外の後ろにページURLを添える）を追加。P’s CUBE：保存の入口 `Bridge.submit_page` の例外を `pscube.save`（URL付き・発生行付き）、読み取り途中の `capture_failed` を `pscube.read`、保存できた結果のうち差枚未取得 `pscube.net_missing`・タブなしで飛ばした `pscube.skipped`・機種一覧の開き直し `pscube.index_retry`・その日の数値なしの台 `pscube.missing_racks` を残す（`capture_notes`、日付とURL付き）。問題のない保存は書かない。メルヘン：保存の確認画面の「取り込みできません」5か所（パチンコ2か所を含む）を `_show_error` 経由で `meruhen.save.table/graph`・`pachinko.save.*`、「予期しないエラー」2か所を `meruhen.save.unexpected`（発生行付き）、台情報なしで飛ばした機種を `meruhen.no_racks` に残す。書き先はいずれも `database/data/errors.log`（同じ内容は60秒に1回、256KiB超で1世代）。
- 試験：`tests/test_pscube_auto.py` に実際の保存入口（`run_session` の Bridge、模擬webview）を通して6種類の行が順に残り、問題のない保存は書かないことを確かめる試験、`tests/test_meruhen_no_racks.py` に飛ばした機種の行、`tests/test_error_log.py` に detail・note・確認画面の表示と記録の試験を追加。PC全体 752件成功（TZ=JST-9）。照合版を `bf06b391c37f` に再生成（生成スクリプト4本）、`test_release_info`・`test_viewer_parts` 15件成功。全体ゲートは未実行（PCのソースと試験だけの変更。CIで流れる）。
- 0.5.49のAPKには前の照合版 `e65ab3afdebc` が入っている。Androidのコードは今回変えていないので、動作の差は無い（版の表示だけ違う）。
- PC版はこのフォルダーのソースから起動するので、取り込み窓を次に開いたときから記録される。入れ替えの日（11/2）の取り込み後に `database/data/errors.log` を読めば、どの台・どのページで何が出たかが分かる。
- 気づいたこと（未対応）：`tests/test_meruhen_no_racks.py` は一時フォルダーを `database/` 直下に作る（`dir=parents[1]`）。Windowsで後片付けに失敗すると `database/tmp*` が残る原因になりうる（Fで片づけた7個の出どころの候補、未確認）。
- 送信（同日）：利用者「pushして」。`python tools/push_ci.py` で正本 `imakurudev-eng/database` の main を `4d02b91..4258f1b` へ1回送った（日本時間12:58、月前半の送り先。Codexの `0787314` と今日のClaudeの分をまとめて含む）。CI [41271243233](https://github.com/imakurudev-eng/database/actions/runs/41271243233) が `4258f1b` で開始（送信直後は queued）。結果は未確認で、次の記録で確定させる。`database-ci` へは送っていない（月前半）。

## 【Codexへ「まだ検討していない課題」の洗い出しを依頼するプロンプトを作成】2026-11-01 Claude

- 依頼：利用者「その間に今度はCODEXにそれ以外の検討課題あらい出してもらおうかな。プロンプトお願いします。すでに検討した事項は除くような指示を」。プロンプトは本チャットで利用者へ渡した（このリポジトリには置いていない）。
- 除外として明記した検討済み事項：Codexの11/1朝の4件（`DATABASE_REVIEW_20261101.md` 前半）、Claudeの全体見直しA〜Hと利用者の決定（同ファイル末尾と本ファイル11/1の各項）、採点の見直しそのものと翌日候補の見直し（別手順・必読資料あり）、10/31の共有カレンダー7項目、カメラアプリ（nail-gauge）。
- 依頼した成果物の置き場所：`DATABASE_REVIEW_20261101.md` の末尾へ「Codex 2回目」として追記し、本ファイルにも記録。調査のみ（製品コード・DB・設定・Google・公開物は変更しない、対象サイトに接続しない、CIを起動しない）。基準は正本main `37d8d40`（4258f1bのCI 41271243233は送信時点で実行中）。

## 【追加の洗い出し（Codex 2回目）：調査・提案のみ】2026-11-01 Codex

- 依頼：databaseのPC・Android・iPhone閲覧ページ・共有カレンダー・Google同期で、未検討の課題を調べる。製品修正なし。成果物は `DATABASE_REVIEW_20261101.md` 末尾の「追加の洗い出し（Codex 2回目）」と本項だけ。利用者はこの2つの記録のコミットと `tools/push_ci.py` での送信を明示的に指示している。
- 基準：正本main＝手元main **`1b0943b3011778cfca5458ebd45029fe1ee1597a`**、database-ci/main **`7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`**。両方をfetchし、後者の祖先確認が終了0。最初の制限内のGit通信はDNS失敗、ネットワーク許可後は取得成功。未コミット差分なしから開始。過去の手元記録の「未push」を現状と混同せず、実リモートで確認した。
- 先に読んだもの：全体・ルート・AndroidのAGENTS、本日のレビュー全文（初回4件・後続回答・Claude A〜H）、AI_COLLABORATIONの11月分。月別記録は `ai_collaboration/2026-09.md`、`2026-10-01_15.md`、`2026-10-16_31.md`、`overview-2026-09.md` をバックアップ・復元・設定・同期・予約・ロック等の見出し／語で検索し、該当節を読む。特に9/27「妥協点の見直し」、10/2「バックアップ読み込みの完全性」、10/17「PC版を閉じるのに」、10/25「別の視点からの改善」、10/26「①〜⑤ 保存・同期・版の照合」「営業日の切り替え」「今日のClaude作業の再レビュー」、10/31「最近の修正の問題点」「前の検討への利用者の回答」を照合。`SHARED_CALENDAR_REVIEW_20261031.md`、`RELIABILITY_HARDENING.md`、`database_android/VIEWER_HISTORY_SYNC.md`、クラウド同期手順、ゲート・CI・起動・公開stageのソースも関連範囲を確認。
- 除外：利用者指定1〜15全部（初回4件、A〜H、採点・翌日候補の見直し、共有カレンダー7項目、カメラ）。加えて、既出の0時予約の修正・PC同期の不正入力保留・Google処理版だけのずれ・時間枠による日別再開・原本破損時の停止を新しい提案に数えない。
- 結果は重要順に4件。①自分用／共有用GSの別プロジェクトのロックでは、同じ🌈ファイルの同時保存を排他できず、両方成功でも片方の印を落とす。②通常取り込みの一括確定は既出だが、PCの `restore_backup` は新規分の確定と競合上書きが別で、後半失敗時に一部反映が残る（新しい経路）。③PCの読めない設定を空扱いし、次の選択保存で原文を失う。④自動出力の写し利用は既出だが、手動バックアップ等の本体直読には届かず、別接続の削除と重なると台も削除印も無いファイルになる（新しい経路）。
- 根拠・ファイル行番号・影響・概算手間・提案・再現コードは報告へ記載。Googleロックの範囲は公式 https://developers.google.com/apps-script/reference/lock/lock-service#getScriptLock() を確認。記録に無い過去の検討まで「誰も検討していない」と断定しない。
- 実行：`database/` で `TZ=JST-9`・`PYTHONUTF8=1` を設定して `./.venv/Scripts/python.exe -B -` へ報告内のPythonを渡す（実測UTC+09:00、一時DB・合成設定、3件、終了0）。ルートで `node --input-type=module -` へ報告内のJavaScriptを渡す（実GS2本・模擬Drive・別ロック、1件、終了0）。**4件は問題状態の再現確認で、修正後の試験成功ではない**。既存試験・全体ゲート・CI・ビルドは実行していない。
- 未確認：4件の実環境での発生頻度・被害、実Googleの現在の配備構成、実機WebView／常駐サービス／容量、依存の最新性・脆弱性。履歴記号の同時保存はコード上の同型までで、再現は🌈のみ。手動バックアップをAndroidで実際に読ませてはいない。実データの診断や端末操作を別途行ったと解釈しない。
- 保護：製品コード・既存試験・実DB・設定・Cookie・Google・公開物を変更せず、対象サイトへの接続・同期実行・実機操作・CI起動・ビルド・公開・APK作成／導入なし。調査用のDB・設定は一時フォルダーのみ、Nodeはメモリ内だけ。実データや認証情報を報告・コミットに含めない。
- 送信方針：日本時間11/1は正本 `imakurudev-eng/database` が対象。送信直前にも `tools/push_ci.py` で両main包含・日付を確認し、文書2ファイルだけをまとめて送る。既存Markdown除外の適用と、これらの文書を処理が読まないことを確認したため、回帰CIを追加起動する変更はない。送信結果と確定コミットは完了報告で示す。今回の提案の実装・Google変更は未承認であり、続けて修正しない。
- 追記（Claude、同日）：Codexは上の記録と報告を書き終えたあと、`tools/push_ci.py --dry-run` の実行が自動レビューで拒否され、続けて利用上限で停止した（利用者が貼った画面による）。利用者「ここでとまっちゃった」を受け、Claudeが作業ツリーの差分（この項と `DATABASE_REVIEW_20261101.md` の「追加の洗い出し（Codex 2回目）」だけ、計184行追加、ほかの変更なし）を読み、実データ・認証情報が含まれないことを確かめてから、その2ファイルだけをコミットし `tools/push_ci.py` で正本へ送った。Codexの模擬確認4件はClaudeが再実行していない（Codexの記録のとおり）。
- CIの結果（Claude確認）：`4258f1b` の [41271243233](https://github.com/imakurudev-eng/database/actions/runs/41271243233) は full・pc (windows-latest, UTC)・pc (ubuntu-latest, UTC) の3ジョブとも success。再実行なし。

## 【Codex 2回目の4件への利用者の決定と、3・4の修正（PC）】2026-11-01 Claude

- 利用者の決定：「１についてはそのままでいい。これは仕様ですっていうことにしておいて。修正の必要性なし」「２もいらない。あんまり戻さないから」「3、４くらいは直しておこうか」。
- 1（自分用と共有用からの🌈の同時保存で片方が消える）：仕様として `RAINBOW.md` の「共有ページから付ける」節に追記。直さない。消えた印は、付けた端末に残っていれば次の付け外しで全部の印と一緒に送り直される（既存の送信仕様）。イベント履歴の記号も同じ形。
- 2（PCの「この日に戻す」の途中失敗で一部反映）：対応しない（利用者がほとんど使わないため）。
- 3（読めない settings.json の上書き）：`core._read_settings` で「無い／開けない／壊れている」を区別。壊れている（JSON不正・UTF-8でない・辞書でない）ときは、上書きの前に原文を `settings.json.broken-日時` へそのまま残し、`errors.log` に `settings.broken` を書いてから保存し直す。原文を残せなければ保存しない。開けない（PermissionError等、同期ソフトの一時的なロックを想定）ときは正しい原文を消さないよう保存を見送り `settings.locked` を書く。`load_settings` の戻り値（読めなければ空）は従来どおり。画面の表示は変えていない。
- 4（手動バックアップ等が本体DBを直接読む）：`core.snapshot_store`（SQLiteのバックアップ機能で本体を一度に一時フォルダーへ写し、その写しのStoreを渡す）と `core.backup_from_snapshot`（共有編集は本体へ取り込み、バックアップは写しから `auto_backup(import_shared=False)`。自動出力 `output_worker` と同じ順番）を追加。PCの「バックアップを書き出す」（`app.py`）と取り込み窓を閉じたときのバックアップ（`browser_import.backup_after_session`）をこれに切り替えた。`delete_records`・`undo_last_save` の即時バックアップは同じプロセスの書き込み直後のため今回は変えていない。P’s CUBEの書き出しも今回の対象外。
- 試験：`tests/test_settings_and_backup_snapshot.py` 7件（壊れた設定の原文保存・UTF-8でない／配列・開けない設定を上書きしない・初回と通常の保存、Codexの再現と同じ順番の同時削除でも削除前の完全な組になる・次の書き出しは削除後の完全な組で取り込み先からも消える・写しへの変更が本体に及ばない・窓を閉じたときのバックアップが写しから書かれる）。PC全体 759件成功（TZ=JST-9）。照合版 `52f50a24d3c6`（生成スクリプト4本）、`test_release_info`・`test_viewer_parts` 15件、PCの版の試験も成功。全体ゲートは未実行（PCのソースと試験・文書だけ。CIのfullで流れる）。
- PC版は次に起動したときから新しい処理になる（設定の保存・手動バックアップは本体のプロセス、窓を閉じたときのバックアップは取り込み窓のプロセス）。
- 送信（同日）：利用者「pushして」。`tools/push_ci.py` で正本へ `dd6305c..6936b9d` を1回送った（日本時間13:45）。CI [41274330798](https://github.com/imakurudev-eng/database/actions/runs/41274330798) が `6936b9d` で開始（送信直後は in_progress）。結果は未確認。

## 【Codexへの引き継ぎメッセージを作成（利用上限の解除後に利用者が渡す）】2026-11-01 Claude

- 依頼：利用者「使用制限解除後にclaudeへのメッセージ作成お願いします。ここからここまでやってこうなってるよと」。Codexが利用上限で止まった後（`1b0943b` の時点）から `9393827` までの経過と現状をまとめた文を本チャットで渡した。内容は本ファイルの11/1の各項と同じ（新しい事実は無い）。送信時点で `6936b9d` のCI 41274330798 は実行中（結果未確認）。

## 【Codex再開：引き継ぎ確認と6936b9dのCI成功を確定】2026-11-01 Codex

- 依頼：利用者がClaudeの続行結果と決定事項を引き継ぎ、正本 `4fb1ee1` 以降の取得とCI 41274330798の結果確認を指示。調査報告の送信はClaudeが `dd6305c` で完了済みであり、元の184行を再コミットしない。
- 両mainを `git fetch --no-tags --no-write-fetch-head` で取得。正本＝手元 `4fb1ee1232549e52aedb48a4b20e2f9c76e89278`、database-ci `7a9df132001c1e80fdbd1d6d964ca695cd3b5a1c`。祖先確認は終了0、開始時の作業ツリーは変更なし。追加のmergeは不要。
- 共有記録末尾、`RAINBOW.md` の仕様、`6936b9d` の変更差分を確認。1・2は利用者の決定どおり対応せず、再提案しない。3・4は修正済みとして引き継ぐ。4の変更範囲外（delete_records・undo_last_saveの即時バックアップ、P’s CUBE出力）を修正済みと拡大解釈しない。
- **[CI 41274330798](https://github.com/imakurudev-eng/database/actions/runs/41274330798) の結果をGitHub接続ツールで直接確認：full・pc (windows-latest, UTC)・pc (ubuntu-latest, UTC) の全3ジョブが completed/success**。fullの `Complete pre-build gate` 段も成功。対象は前項で送信した `6936b9d`。これにより、前の「実行中・結果未確認」を更新する。ローカルPC759件・新規7件の実行根拠はClaudeの記録で、Codexが実行したものではない。
- 変更は本項と `DATABASE_REVIEW_20261101.md` 末尾の現在状況の追記だけ。ローカル試験・CI・ビルドは再実行せず、製品コード・DB・設定・Cookie・Google・公開物・端末を変更しない。実機での修正確認、11/2の入れ替え後のログは今回未確認。Android 0.5.49の導入や11/2の監視を始める依頼とは扱わない。
- 許可済みの文書2ファイルの範囲で記録を正本へ送る。既存のMarkdown除外を維持し、新たな回帰CIは起動しない。実際の送信結果・コミットは完了報告に示す。

## 【バラエティを回転数でも並べ替える（PC・共有カレンダー・iPhone閲覧ページ）】2026-11-01 Claude

- 依頼：利用者「幸町のバラエティとかPC上で開く際に、差枚でソートはできるけど、回転数とかでもソートできるようにしておいてほしい」。AGENTS.mdの「表示に関わる機能は、出す画面を着手前に確かめる」に従い質問：対象＝「PCだけ」「共有カレンダーにも」「iPhone閲覧ページにも」、並べる列＝「回転数」「台番・機種・最終🌈も見出しで」。調べたところ共有カレンダーは回転数を表示しておらず、iPhone閲覧ページにはPCのような一覧表が無かったため、その場で再質問：共有＝「並べ方に回転数を足す」、iPhone＝「台の並べ方を切替に」。Androidアプリは変えていない。
- PC（`database/variety_rainbow.py`）：並べ方に「回転数の多い順・少ない順」を追加（回転数の無い台＝本日の未取得は両方とも最後、同じ回転数は台番号順）。一覧の見出し 台番・機種・回転数・推定差枚・最終🌈 を押すと並べ替え（回転数・推定差枚は押すたびに多い順⇔少ない順、選んでいる見出しに ▼／▲）。7日表（ローテーション表）でも同じ並べ方が使える。試験 `tests/test_variety_rainbow.py` に見出しを実際に押す試験を追加。
- 共有カレンダー（`share_viewer/`）：🌈の記録の「並べ方」に「回転数の多い順（7日表）」「回転数の少ない順（7日表）」を追加（`data.mjs` の `ROTATION_SORTS`・`rotationOrder`、表示中の日の回転数、記録の無い台は最後）。回転数で並べたときだけ台名の下に「5,000G」のように回転数を出す。台番号を押したときは元の並びの位置で台を引く（並べ替えで台を取り違えない）。並べ方は端末に覚える（既存の `database-share-variety-sort`）。試験 `tool/test_share_viewer_rainbow_browser.mjs` に並べ替え・回転数の表示・320/393pxではみ出さない・押した台が正しい・覚えるを追加。
- iPhone閲覧ページ（`database_android/lib/viewer_pages.dart` の `ViewerMachinePage`、バラエティのときだけ）：台のカードの上に「並べ方：台番号順／回転数の多い順／回転数の少ない順／機種順」（`sortVarietyEntries`、端末に覚える `variety-sort`）。Androidアプリからこの画面に来る経路（イベント履歴）は具体的な機種名なので切替は出ない。試験 `test/viewer_navigation_test.dart` に2件。
- 照合版 `b68edbfca0f0`（生成スクリプト4本）。全体ゲート **ALL PASSED**（PC 760件・UTC 27件・Flutter 755件・analyze 情報28件・JS 77本、`TZ=JST-9`、`/c/w/gate-sort1101.log`・`/c/w/cbw-sort1101/`）。
- 公開：未公開（利用者に画像を見せて承認をもらってから、ゲートの `viewer/`・`share/` stage を公開する予定）。
- 公開（同日、利用者「公開して」）：コード `b10f70b` を `tools/push_ci.py` で正本へ送信（`2f8b2af..b10f70b`。`2f8b2af` は14:38にCodexがこのフォルダーで記録した文書で、履歴は1本）。CI [41311162933](https://github.com/imakurudev-eng/database/actions/runs/41311162933) は確認時点で実行中（結果未確認）。前の `6936b9d` の CI 41274330798 は success。
- 共有カレンダー：`database-share` へ `37407e8`（公開版 `d742103e6abf`、source `b10f70b`）。ゲートの `share/` stage を `outputs/variety-sort-20261101/public-share` に写した。実際の差は9ファイル（並べ替えと版の文字列）。Pages [41311284285](https://github.com/keyanbaitian6-cell/database-share/actions/runs/41311284285) 成功。配信中の app.mjs・data.mjs・index.html・sw.js は改行をそろえると stage と一致。公開URLに対して `test_share_viewer_rainbow_browser.mjs` を実行し成功（320/393px、回転数の並べ替えを含む。Googleは試験内の偽物）。
- iPhone閲覧ページ：`database-viewer` へ `831c96d`（照合版 `b68edbfca0f0`、版 0.5.49+2026110102、source `b10f70b`）。ゲートの `viewer/` stage（`stage_viewer.py` で実データ除去・検査済み）を `outputs/variety-sort-20261101/public-viewer` に写した。実際の差は6ファイル。Pages [41311289219](https://github.com/keyanbaitian6-cell/database-viewer/actions/runs/41311289219) 成功。配信中の main.dart.js・version.json・viewer_parts.mjs が stage とバイト一致。実機Safariでの表示は未確認（利用者がページを開き直すと反映）。
- 利用者の確認（同日）：公開後に利用者「確認OK」。どの画面・端末で確かめたかの詳細は聞いていない（利用者による確認として記録し、AIが実機Safariで確かめた結果とは区別する）。`b10f70b` の CI 41311162933 は、記録時点で pc (windows)・pc (ubuntu) が success、full は実行中。

## 【全機種の台一覧と並べ方（PC・Android・iPhone閲覧ページ・共有カレンダー）】2026-11-01 Claude

- 依頼：利用者「今回バラエティだけこのような感じでソートできるようにしたけど、そのほかの機種一覧として同じように見えるようにしてほしい。ちなみに媒体は全てです」、続けて「PCの結果を読むの作りはあまり好きではないので、今バラエティを表示しているような作りで見たいです。バラエティ以外の他の機種を一覧でだしつつ、機種だけみたいときはタブで切り替えられるように」。質問への回答：切り替え＝「タブじゃなかったプルダウンでした」、「結果を見る」（HTML）＝「ブラウザでHTML開くことはないから端っこにおいておいて」、PCの列＝合計点・設定候補・翌日候補の★☆・🌈の印、ほかの媒体＝「PCと同じ全機種の一覧も作る」。途中で「共有カレンダーには採点はいらないよ」。基準コミット `7be9f19`（正本 main と同じ。手元は clean から開始）。
- バラエティの範囲：各媒体のバラエティの画面に出る機種を「バラエティ」とし、その残りを全機種の一覧に出す。PC・共有カレンダーはバラエティ🌈と同じ（幸町は1台だけの機種、長町南は1〜3台）。Android・閲覧ページは結果のバラエティと同じ `varietyMachines`（幸町1〜2台、長町南1〜3台）。そのため幸町の2台の機種は、PC・共有では全機種の一覧に、Android・閲覧ページではバラエティに出る（媒体ごとに、どちらか一方には必ず出る）。
- PC（新規 `database/machine_list.py`、`database/app.py`）：タブ「機種一覧」を「取り込み」の右に追加し、「結果を見る」を右端へ移した（中身は変えていない。カレンダー・イベント履歴から開くHTMLの結果もそのまま）。店舗・日付・機種（すべての機種＋その日の各機種のプルダウン）・並べ方。列は🌈・台番（★注目／☆長期傾向）・機種・回転数・BB・RB・推定差枚・設定候補（BB/RB。手入力の設定情報を優先）・合計点。点数・候補・差枚は「結果を見る」と同じ関数（`scored_rows`・`provisional_next_day_candidates`・`rack_net`）。見出し 台番・機種・回転数・推定差枚・合計点を押すと並べ替え（数値は押すたびに多い順⇔少ない順、▼／▲、数値の無い台は最後）。🌈の列を押すと付け外し（記録のある台だけ。保存はその場、閲覧・共有ページへの反映はバラエティ🌈と同じくまとめて＝ボタン・タブを離れるとき）。幸町は1日500台ほどで採点に約5秒かかる（写しのDBで計測：幸町10/31 148機種532台＝採点3.8秒＋候補1.0秒、長町南11/1 126台＝0.4秒）ため、読み込みは別の糸で行い「読み込んでいます…」を出す。
- Android・閲覧ページ（`lib/machine_sections.dart` の `MachineSection`）：すべての台の表（1機種・バラエティ・全機種）に「並べ方」（台番号順・回転数・差枚・点数の多い順／少ない順、機種が混ざる画面だけ機種順）。数値の無い台（異常・差枚なし・保留）は最後。並べ方は端末に覚える（閲覧ページはブラウザに、Androidアプリは開いている間だけ。名前は 1機種 `machine-sort`・バラエティ `variety-sort`（既存）・全機種 `all-machines-sort`）。全機種 `allMachinesName` のときは機種のプルダウンも出し、見出しの台数・平均・★☆の数は絞った台で数える。閲覧ページはホームの「この日の機種一覧」の上、Androidは結果の「設置機種一覧」の下に「全機種の台一覧」ボタン（`ViewerMachinePage`・`HistoryGroupPage` を全機種で開く）。先の閲覧ページのバラエティ専用の並べ方（`sortVarietyEntries`）はこの共通部品へ移した。
- 共有カレンダー（`share_viewer/app.mjs`・`data.mjs`）：日のまとめのいちばん下に「全機種の台一覧」（`nonVarietyRacks`・`allRacksOrder`・`ALL_RACKS_SORTS`）。機種・並べ方（台番号順・回転数・差枚の多い順／少ない順・機種順）の選択欄。点数は出さない。台番・🌈・機種・BB/RB・差枚・回転数。並べ方は端末に覚える（`database-share-all-racks-sort`）。台を押すと台のデータ、前後の台は一覧の並びで送る。
- 試験：PC `tests/test_machine_list.py`（6件：バラエティを入れない・プルダウンと見出しの並べ替え・数値なしは最後・🌈の保存・異常の台・タブを開くまでDBを読まない）、`tests/test_app_startup.py` にタブの並び。Flutter `viewer_navigation_test.dart`（全機種・1機種の並べ方・点数の分からない台は最後を追加、既存のバラエティの試験は共通の名前へ）、`android_variety_review_test.dart`（結果→全機種）。JS 新規 `tool/test_share_viewer_all_racks_browser.mjs`（320/393px）。既存の `test_share_viewer_browser.mjs` は日のまとめの行が1つ増えた分と「強かった機種」の選び方を直し、`record_search_navigation_test.dart` はボタンで一覧が下へずれた分、押す前に画面内へ送るよう直した（1回目の全体ゲートで P’s CUBE=true の1件が押し外しで失敗→この修正）。
- 照合版 `fdd9db07aee1`（生成スクリプト4本。初めに作った `3c6f6e0bb608` はPC一覧の文言修正の前のもので、2回目のゲート後に気づいて作り直した）。画像（確認用）：`outputs/all-machines-20261101/`（PC：写しのDBで幸町10/31、全機種51機種435台を合計点順・Sマイジャグラー VKD 28台を回転数順。共有：試験データ393/320px）。
- 全体ゲート（2回目）**ALL PASSED**（`/c/w/gate-allm1101b.log`）。照合版を `fdd9db07aee1` に直したあとの3回目も **ALL PASSED**（PC 766件・UTC 27件・Flutter 759件・analyze 情報28件・JS 78本、`TZ=JST-9`、`/c/w/gate-allm1101c.log`・`/c/w/cbw-allm1101c/`。公開するときはこの `viewer/`・`share/` stage を使う）。1回目（`/c/w/gate-allm1101.log`）は上の `record_search_navigation_test.dart` の1件だけ失敗。
- 送信・公開：未（利用者に画像を見せて承認をもらってから、正本への送信と、ゲートの `viewer/`・`share/` stage の公開を行う予定）。Android APK は未作成（作るかは利用者に確認）。
- 公開（2026-11-02 0時台、利用者「送って公開して」）：`04179aa`・`86c562f` を `tools/push_ci.py` で正本へ1回で送信（`7be9f19..86c562f`、日本時間11/2＝前半）。CI [41321124535](https://github.com/imakurudev-eng/database/actions/runs/41321124535) は記録時点で pc (ubuntu) success、pc (windows)・full は実行中（結果未確認）。
- 共有カレンダー：`database-share` へ `1a3d77c`（照合版 `fdd9db07aee1`、source `86c562f`）。3回目のゲートの `share/` stage を `outputs/all-machines-20261101/public-share` に写した。実際の差は9ファイル（app.mjs・data.mjs と版の文字列）。Pages 41321230183 成功。配信中の app.mjs・data.mjs・index.html・sw.js は改行をそろえると stage と一致。公開URLに対して `test_share_viewer_all_racks_browser.mjs` を実行し成功（320/393px。Googleは試験内の偽物）。
- iPhone閲覧ページ：`database-viewer` へ `444d8ae`（照合版 `fdd9db07aee1`、版 0.5.49+2026110102 のまま、source `86c562f`）。3回目のゲートの `viewer/` stage（`stage_viewer.py` で実データ除去・検査済み）を `outputs/all-machines-20261101/public-viewer` に写した。実際の差は6ファイル（main.dart.js・アイコンのフォント・版の文字列）。Pages 41321235615 成功。配信中の main.dart.js・version.json・viewer_parts.mjs が stage と一致（改行をそろえて比較）。実機Safariでの表示は未確認。
- Android APK：未作成（利用者「今はいい」、同日）。Androidアプリには並べ方・全機種の台一覧はまだ届いていない。PC版は `start.cmd` から起動し直すと機種一覧のタブが出る（利用者の確認は未）。

## 【P-STATION自動同期のスクリプトがスマホの当日分（pscube-day-android）も読む】2026-11-02 Claude

- 依頼：利用者「今日androidで予約取り込みやったんだけどやっぱりPCひらかないとデータに反映されないんだね」→ 閲覧ページ・共有カレンダーとも11/1（0時予約の分）が出ていない。利用者が貼った `showPscubeCloudStatus`（7:04）は「正常に完了（2026-11-01T22:02:18Z）・履歴を日別に保存・24日更新」「次回に回したファイル：2」、実行数の画面は30分おきの `syncPscubeCloud` がすべて完了（3:00 108秒・4:00 315秒・7:00 110秒、ほかは数秒）。基準 `9ac34d1`。
- **AIの誤り（訂正済み）**：最初に「予約・自動取り込みのあとはドライブへ自動では書き出さない（書き出しはボタンだけ）」と答えた。手動の `_share` だけを読み、10/26に入れた当日分の自動送信（`lib/pscube_day_upload.dart`、自分用スクリプトの `postPscubeDay` が「database共有」に `pscube-day-android-YYYY-MM-DD.json` を書く）を見落としていた。利用者「予約機能を入れたときに自動で書き出すって指示をだしたはずでは？」で記録（2026-10-16_31.md「P’s CUBEの当日分をスマホから自動でDriveへ送り…」）を確かめ、訂正した。
- 原因：10/26の仕様（`database/PSCUBE_SYNC.md`「当日分の自動送信」）で「当日分のファイルを読むのはPC版だけ（P-STATION自動同期のスクリプトは読まない）」としていた。`pscube_cloud_sync_runtime.js` の `pscubeCloudListInputs` は `title contains 'pscube-backup-'` と名前の正規表現で `pscube-backup-…` だけを拾う。PCを開くと `app.poll_pscube_from_sync` が当日分を読み、PCが閲覧用ファイルを書き直すので、そこで初めて出ていた。
- 変更：`pscubeCloudListInputs` の検索を `(title contains 'pscube-backup-' or title contains 'pscube-day-android-')`、名前の正規表現に `pscube-day-android-\d{4}-\d{2}-\d{2}` を足した（通常・日別の履歴の両方がこの一覧を使う）。中身はその日だけの普通の backup（`kind: backup`・`source: android`）で、`pscubeCloudRead` の検証をそのまま通る。読む順は古い順のまま（当日分を先にする案は、機種タイプが「後で処理した入力の指定を優先」なので採らなかった）。生成 `pscube_cloud_sync.gs`、照合版 `3d9b9cf3ad30`（生成スクリプト4本。ほかの `.gs` は版の文字列だけ変わり貼替不要）。文書 `database/PSCUBE_SYNC.md`・`database_android/PSCUBE_CLOUD_SYNC.md`。
- 試験：`tool/test_pscube_cloud_sync.mjs` の模擬Driveの検索を新しい条件に合わせ、2件を追加（履歴=false/true：当日分だけで閲覧用に出る・`-copy` 付きや別フォルダは読まない・変わらなければ読み直さない・送り直し（上書き）は読み直す・元ファイルを書き換えない）。49件すべて成功。
- 貼り替え用：`outputs/pscube-day-sync-20261102/gs/`（`pscube_cloud_sync.gs`＝配布元の `PSCUBE_HISTORY_VIEWER` だけ true・改行LF、SHA-256 `f03b5b96…8e45`、`スクリプトをコピー.html`（中身がファイルと一致することを確認）、`手順.md`）。P-STATIONの同期プロジェクトに1本だけ貼り、`syncPscubeCloud` を実行。デプロイ不要。
- 未確認：実際の「database共有」にある当日分のファイル（このPCの G: の一覧が2回とも返らず読めなかった。Googleドライブの接続は別アカウントでP’s CUBEのファイルが見えない）、Googleの実環境での動作、4:00の回が315秒（上限360秒）かかった理由。
- 全体ゲート **ALL PASSED**（PC 766件・UTC 27件・Flutter 759件・analyze 情報28件・JS 78本、`TZ=JST-9`、`/c/w/gate-dayup1102.log`・`/c/w/cbw-dayup1102/`）。貼り替え・Googleでの実行は利用者の作業（未）。

## 【PCの機種一覧にP’s CUBE（P-STATION）を足す（点数なし）】2026-11-02 Claude

- 依頼：利用者「PC版で今昨日追加した機種一覧開こうとしたけどP-STATIONの分がないのはなぜ？」。11/1の実装で、店舗の選択肢をバラエティ🌈と同じメルヘン2店舗だけにし、P’s CUBEを入れるかを確かめていなかった（AGENTS.md「表示に関わる機能は、出す画面を着手前に確かめる」の趣旨に反する。AIの判断の誤り）。PC版にはP’s CUBEの採点が無い（`pscube_report.py`「No scoring」、点数・推定設定・翌日候補はスマホ・閲覧ページだけ）と説明し、選択肢「点数なしで足す／点数も出したい」→ 利用者「点数なしで足す」。基準 `bd0a95e`。
- 変更（`database/machine_list.py`・`database/app.py`）：店舗の選択肢に `P’s CUBE（スロット）`（app.py の `PSCUBE_LABEL`、「結果を見る」と同じ名前）。選ぶと `data/pscube.sqlite3` を読む（`pscube_list_rows`。`PscubeStore(recording=False)`、日付は `days()`）。沖ドキ（`is_excluded_machine`）は除く。数値異常はカレンダー（`PscubeEvents.day_records`）と同じ基準で「異常」。貸玉が複数ある日は機種名の前に「20スロ」など。PC版にP’s CUBEのバラエティ🌈は無いので全機種を入れる。列：差枚＝元グラフの確定差枚（見出し「差枚」）、MYの列（P’s CUBEのときだけ表示）、🌈・設定候補・合計点は「—」（🌈の列を押しても何もしない）。並べ替え・機種のプルダウンはメルヘンと同じ。
- 試験：`tests/test_machine_list.py` に1件（最新の日・沖ドキ除外・台数の少ない機種も入る・差枚とMY・—の列・差枚の無い台は最後・🌈を押しても変わらない・メルヘンへ戻すとMYが隠れる）。PC 9件（機種一覧7＋起動2）成功。写しのDB（`data/pscube.sqlite3`、読むだけ）で表示：最新の日 10/31・59機種・295台を差枚の多い順（`outputs/all-machines-20261101/pc-pscube.png`）。
- 気づいたこと（未調査）：このPCの `data/pscube.sqlite3` の最新の日は10/31（6:53更新）。スマホの11/1の当日分はPCがまだ読んでいない。PCの当日分の自動読み込み（`app.poll_pscube_from_sync`）はPC版が起動している間だけ動く。
- 照合版 `6dea1a0a6a15`（生成スクリプト4本）。
- 全体ゲート **ALL PASSED**（PC 767件・UTC 27件・Flutter 759件・analyze 情報28件・JS 78本、`TZ=JST-9`、`/c/w/gate-mlps1102.log`・`/c/w/cbw-mlps1102/`）。閲覧ページ・共有カレンダーは変えていないので公開なし。PC版は起動し直すと反映。
- 利用者の確認（11/2、上の2件の後）：P-STATION自動同期の貼り替え後の `syncPscubeCloud` 実行と閲覧ページ・共有カレンダーの11/1について結果を尋ねた返事として、利用者「OKだったよ」（1715行の版を貼ったことは利用者が行数で確認済み）。どの画面で何を確かめたかの詳細は聞いていない。利用者による確認として記録し、AIがGoogle・実機で確かめた結果とは区別する。

## 【PC版：Googleドライブのドライブ文字が変わっても同期フォルダを目印で探し、画面の上で知らせる】2026-11-03 Claude

- 依頼：利用者「何度目かわからないけどまたグーグルドライブのドライブレター変わってるのに気づかず取り込み終えてしまった。いまGになおした」。AIが確かめたこと（読むだけ）：`data/backup-output-meruhen.json` は 11/3 06:39 に `unavailable`「同期フォルダが見つかりません」（最後の成功 11/2 06:53、取り込んだ11/2の記録は本体DBにある）。P’s CUBEは11/2 06:54の成功が最後。今は `G:` が「Google Drive」で `G:\マイドライブ\database共有` がある。設定 `sync_dir` は G: のまま。10/26（G:→E:）と同じ現象で、そのとき出した対策案は未実装だった。案「自動で探して知らせる／知らせるだけ」→ 利用者「自動で探して知らせる」「別のアカウントで文字つかってるときはこっちはEになるね」。基準 `3ad4f72`。
- 変更（`database/core.py`）：同期フォルダに目印 `database-sync-folder.json`（`{"id": 番号}`）を置き、番号を `settings.json` の `sync_mark` に覚える（`write_sync_mark`）。`resolve_sync_dir`：設定の場所が使え、目印が無いか番号が一致すればそこ（目印が無ければ付ける）。別の番号の目印があるフォルダは使わない。設定の場所が無い（アクセス拒否も含む）ときは、ほかのドライブ文字（C〜Z）の同じ場所で番号が一致するものだけに切り替え、`sync_dir` を書き換えて `sync_moved`（old・new・時刻）と errors.log に残す。目印の無いフォルダ・別の番号のフォルダ（もう一方のアカウントのドライブ）には切り替えない。設定を読んで同期フォルダを使っていた所をすべてこの関数に通した（core の共有履歴・日別控え・全期間/閲覧用の書き出し、`pscube_import.sync_folder`、`pachinko.py`、`app.py` の起動時読み込み・P’s CUBE当日分の2分おきの読み込み・手動の読み込み/書き出し・共有イベント等）。設定の場所に別の番号の目印があるときは、書き出し結果に理由を残す。
- 画面（`database/app.py`）：タブの上に帯。書き出せていない（`backup-output-*.json` が `unavailable`）間は赤い帯「Googleドライブの同期フォルダ（…）が見つからず、…の書き出しがドライブへ届いていません。取り込んだ記録はPCに残っています…」と「共有用ファイルを更新」ボタン、同じ失敗について知らせの窓を1回。別のドライブ文字へ切り替えたときは黄色い帯と「わかった」（`sync_moved` を消す）。30秒おき（`SYNC_BANNER_INTERVAL_MS`）に出し直し、同期フォルダが戻った・見つかったら、止まっていた書き出しを1回自動でやり直す（`reexport_shared`、サイトへのアクセスなし）。「同期フォルダを指定」で選び直すと、そのフォルダに目印を付け、切り替えの知らせを消す。
- 試験：新規 `tests/test_sync_folder_mark.py` 6件（初回に目印・番号一致の別ドライブへ切り替えて設定と記録・目印が無い/違うフォルダへは切り替えない・切り替え先へ全期間バックアップを書き出して成功・見つからなければ unavailable で設定の場所を残す・ドライブ文字の組み立て（Linuxでも同じ））。`tests/test_app_startup.py` に1件（赤い帯と窓は1回・黄色い帯と「わかった」で消える）。`tests/test_pscube_sync.py` の同期フォルダの中身に目印を足した（全試験で落ちたのはこの1件だけで、目印のファイルが増えた想定どおりの差）。
- 照合版 `902d927d1185`（生成スクリプト4本）。
- 利用者のPCへの反映：PC版を起動し直すと、G: に目印が付き、起動の約3秒後に赤い帯が出て、G: が見つかるので止まっていた11/3 6:39の書き出しを自動でやり直す（見込み。実PCでは未確認）。Googleドライブのアプリの設定でアカウントごとにドライブ文字を固定するのが根本的な予防（利用者側の設定）。
- 全体ゲート **ALL PASSED**（PC 774件・UTC 27件・Flutter 759件・analyze 情報28件・JS 78本、`TZ=JST-9`、`/c/w/gate-syncmark.log`・`/c/w/cbw-syncmark/`）。閲覧ページ・共有カレンダーは変えていないので公開なし。

## 【新台の点数：画面の表示だけ、同じ日の同じ機種のほかの台と比べる（v13）】2026-11-03 Claude

- 依頼：利用者がiPhone閲覧ページの長町南 11/2 の210番台（L聖闘士星矢黄金十二宮TG、BIG45・REG6・2107G・1/41.3・推定差枚+4,017）の合計点59.7の理由を質問。PCのDB（読むだけ）でこの機種の長町南の記録は11/2の7台（205〜211）だけ＝新台で、比較0件のため当たり（60）・持玉（20）が中立30・10、実際に評価できたのは終点10.0・維持9.7だけ（評価可能配点20/100）と説明。利用者「新台については比較せず出しても良いのでは？」→ 機種ごとに当たりの重さが違うので比べずに良し悪しは決められないと説明し、案「1 同じ日の同じ機種のほかの台と比べる（おすすめ）／2 表示だけ変える」→ 利用者「1」。途中で「Androidアプリは今はビルドしなくていいからね」。基準 `7735024`。
- 注意して決めたこと：採点版 v12 は、事前に固定した検証（`focus_validation.dart`・`reference_candidate_comparison.dart`・`low_activity_candidate_comparison.dart` の `referenceScoringVersion`）が一致を確かめて動く。バラエティは入れ替えで翌日の同じ台番号が新台になることがあり、翌日の点（結果）が変わると固定済みの検証の結果も変わる。そのため新しい扱いは**画面に出す点数だけ**にし、翌日候補・固定済みの検証・監査・CSVは v12 のまま（版の定数 `VERSION`／`scoringVersion` は変えず、新しい扱いの点だけ `NEW_MACHINE_SCORING_VERSION`／`newMachineScoringVersion` = `2026-11-03-v13`）。同じ日の台と比べる仕組みは最初のコミット（`d04d9b9`）で「deliberately gone」とされていたが、理由の記録は見つからなかった。
- 規則：新台＝同じ店・同じ機種の、評価日の30日前〜前日の回転数のある記録が1件も無い（過去の記録があって回転数の幅で0件になった台は新台ではない）。新台のときだけ、同じ日の同じ機種のほかの台（自分を除く、回転数の幅・数値異常の除外は今までと同じ）を比較相手にする。式は同じで、比較が1日分なので強く中立へ寄り、必ず暫定。理由の先頭に「新台（過去30日の記録なし）：同じ日の同じ機種N台と比べた点」。
- 変更：PC `database/core.py`（`new_machine_peers`、`score(..., same_day=)`、`scored_rows`（結果のHTML・機種一覧・まとめ）と台の過去の点（`rack_trend` 相当）で same_day を渡す）。Dart `lib/scoring.dart`（`newMachinePeers`・`_scoringPool`、`scoreRecord(..., sameDayForNew:)`、P’s CUBEの `_scorePscube` も同じ）と、画面の呼び出し（`viewer_pages.dart` の機種・台の画面、`viewer_main.dart` のホームの点数、`record_analysis.dart` のAndroidの結果の点数（候補は `dayCandidates` が今までどおり）、`shared_widgets.dart` の台の過去の点）。文書 `SCORING_POLICY.md`「新台の比較相手」、`database/PSCUBE_SCORING.md`。
- 実データの写し（読むだけ）での効果：長町南 11/2 の聖闘士星矢7台（v12→v13）：210番台 59.7→72.6、208番台 55.9→65.2、207番台 40.0→42.3、205番台 40.0→34.2、206番台 40.0→29.6、209番台 40.0→34.3、211番台 40.0→36.5。
- 試験：新規 `tests/test_new_machine_scoring.py` 3件（初日は画面だけ同じ日の台と比べる・過去の記録があれば新台でない・30日より前と回転数0の記録は数えない・`scored_rows`）。一致の試験 `tests/test_scoring_parity.py`／`test/scoring_parity_test.dart` に `display_scores`（合成データの初日22台だけ変わる）と版を追加。期待値ファイルの今までの `scores`・`candidates`・`rows` は作り直し前と完全に一致（比較済み）。
- 照合版 `59bb757bf66d`（生成スクリプト4本）。Android APK は作らない（利用者指定）。閲覧ページは公開が必要（未）。PC版は起動し直すと反映。
- 全体ゲート **ALL PASSED**（PC 777件・UTC 27件・Flutter 761件・JS 78本、`TZ=JST-9`、`/c/w/gate-newm.log`・`/c/w/cbw-newm/`）。analyze が情報29件（前回28件）で、増えた1件は追加した試験の `for` に波かっこが無い指摘 → 直して `flutter analyze` 28件・`scoring_parity_test.dart` 5件成功を確認（試験ファイルだけの変更のため全体ゲートは流し直していない。公開する閲覧ページの `viewer/` stage はこのゲートのもの）。
- 公開（同日、利用者「公開して」）：iPhone閲覧ページ `database-viewer` へ `15b4c2f`（照合版 `59bb757bf66d`、source `2c4f26d`）。ゲート `/c/w/cbw-newm/viewer/` の stage（`stage_viewer.py` で実データ除去・検査済み）を `outputs/all-machines-20261101/public-viewer` に写した。実際の差は5ファイル（main.dart.js と版の文字列）。Pages 41539122099 成功。配信中の main.dart.js・version.json・viewer_parts.mjs が stage と一致（改行をそろえて比較）。実機Safariでの表示は未確認。共有カレンダーは点数を出さないので変更なし。CI（`2c4f26d`）は記録時点で結果未確認。

## 【P’s CUBE：途中で止まった機種一覧を「すべて取り込みました」にしない（Android・PC）】2026-11-03 Claude

- 依頼：利用者「pscubeまた完了したとかいってるのに全機種読み込めてないな。今回はipで蹴られたりもしてない」→ 原因と案を説明し、利用者「直して（APKはまだ）」。基準 `df05073`。対象サイトは開いていない。
- AIが確かめたこと（PCの `data/pscube.sqlite3` を読むだけ）：10/25〜10/31は毎日59機種・295台。**11/1は19機種・205台、11/2は38機種・264台**（11/2の38機種のうち6機種は10/31に無い入れ替えの新台）。取得時刻はどちらもその日の23時台。サイトの機種一覧は一番下で20件ずつ届くとみられ、沖ドキ（対象外）を除くと19・38は1回目・2回目の区切り。PCの state の `last_day` は 10/31（スマホの当日分をPCが読んだ分）。
- 原因（コードと 10/27 の記録 `ai_collaboration/2026-10-16_31.md` で確認）：10/27の修正で、自動取り込みは「前回の機種一覧より少ない一覧は開き直し、同じ集合なら受け付ける」（撤去の日のため）。記録の「限界」に「同じ途中一覧が開き直し後も2回続けて返れば区別できない」とあった。途中で止まった19機種が2回とも同じに返って受け付けられ、`active_machine_keys` が19機種になったため、11/2の38機種は「増えた」扱いで確認すらされなかった（このままだと毎晩続く見込み）。
- もう1つ見つけたこと：PC版 `SCROLL_SCRIPT` には 10/28 に「動かすたびに scroll の通知を出す」修正（窓が裏に回ると jquery.inview が位置を取り直さず続きが出ない）が入っていたが、**Android の `_showFullList` には入っていなかった**。0時予約は画面を暗くして待つ。スマホで実際にこれが原因かは未確認。
- 変更：
  - **いつもの機種数**（記録のある直近14日で、1日にそろった機種（対象外を除く）のいちばん多い数。途中までの日があっても下がらない。新しい設定は作らず毎回記録から数える）の **8割に満たない機種一覧は、自動では開き直して同じでも受け付けない**。Android `pscube_store.dart`（`pscubeIndexShortRatio`・`pscubeUsualIndexDays`・`_usualMachineCount`、`PscubeIndexRetry(shown:, usual:)`）、PC `pscube_import.py`（`INDEX_SHORT_RATIO`・`USUAL_INDEX_DAYS`・`_usual_machine_count`、`PscubeIndexRetry(keys, shown, usual)`、途中の一覧は `index_confirmation` に覚えない）。開き直しは今までどおり3回まで（数えは同じページの失敗）で、3回目は「ON・機種一覧が途中までしか読めていません（いつものN機種に対してM機種）。3回開き直しても同じでした。待機中（一覧を一番下まで表示して手動で取り込むか、OFF→ONで再開）」。「すべて取り込みました」にも、当日分の自動送信にも進まない。8割以上で減った一覧（撤去の日）は今までどおり2回目で受け付ける。手動の取り込みは受け付ける。
  - Android の一覧のスクロールで、動かすたびに `window.dispatchEvent(new Event('scroll'))`（PC版と同じ）。
  - 台数不明の一覧（機種一覧）の件数が**ちょうど20の倍数で止まったときは、少し戻って着き直す回数を2回→3回**（Android `pscubeListChunk`・`pscubeUnknownListChunkNudges`、PC `SCROLL_SCRIPT`）。そのぶん長い一覧（試験の140機種）が上限に掛かったため、**台数不明の一覧だけ上限を90秒・360回→120秒・480回**（Android `pscubeIndexListTimeout`・`pscubeIndexListMaxTicks`、PC `SCROLL_SCRIPT`）。同じページの中で下へ送るだけで、サイトへのアクセスは増えない。設置台数が分かる全台一覧は90秒のまま。
- 試験：Android `pscube_store_test.dart` 1件（10機種そろった日の記録で、7機種の一覧は3回同じでも受け付けない・8機種は2回目で受け付ける・手動は受け付ける）、`pscube_auto_flow_test.dart` 1件（模擬WebViewで、同じ途中の一覧に3回で止まり「途中までしか読めていません（いつもの3機種に対して2機種）」、「すべて取り込みました」は出ない、機種の並びは上書きしない）、`pscube_list_wait_test.dart` 1件（20件で止まって3回目の到着まで続きが始まらない一覧も61件まで読む・ちょうど40件の一覧も上限内で終わる）と、上限を変えた2件の期待値。PC `tests/test_pscube_import.py` 1件（AutoPilot を通して同じ7機種が3回→待機、短い一覧の知らせ、`completed` が無い、バックアップしない、8機種・手動の扱い）、`tool/test_pscube_scroll.mjs` 1件（3回目の到着まで続きが始まらない61件）と上限の期待値。新しい20件区切りの試験は、着き直しを2回に戻すと「61件のはずが20件」で落ちることを確認した。Android P’s CUBE 関連 81件・PC P’s CUBE 関連 140件成功。
- 照合版 `dd271700ea5c`（生成スクリプト4本）。Android APK は作らない（利用者指定）＝スマホでは未反映。11/1・11/2の抜けた機種を後から取り直せるかは未確認。
- 全体ゲート（`/c/w/gate-pslist.log`・`/c/w/cbw-pslist/`、`TZ=JST-9`）：PC 778件・UTC 27件・Flutter 764件・analyze 情報28件・JS 77本は成功、**`test_pscube_auto_browser` の1件だけ失敗**。原因はこの試験が `SCROLL_SCRIPT` の文字 `90000 * scale` を `1` に置き換えて時間切れを作っていたこと（今回 `limit * scale` に変えたため置き換えが効かず、30秒待って時間切れ）。試験の置き換え先を `limit * scale` に直し、単独で成功を確認（試験ファイルだけの変更のため全体ゲートは流し直していない）。ほかに同じ置き換えをする試験は無い（grep で確認）。

## 【Android 0.5.50 のAPK作成（P’s CUBEの途中の機種一覧を受け付けない修正などを含む）】2026-11-03 Claude

- 依頼：利用者「APKビルドお願いします」。基準 `fae1565`（正本 main と同じ）。0.5.49（11/1）以降のAndroidの変更（全機種の一覧・並べ方、新台の点数 v13、P’s CUBEの途中の機種一覧を受け付けない・scrollの通知・20件区切りの着き直し）がスマホに入る。
- 版：`pubspec.yaml` を `0.5.50+2026110302` に上げた。照合版は `dd271700ea5c` のまま（生成スクリプト4本と最後の `build_release_info.py` で変わらないことを確認。版番号は照合版の計算に入らない）。
- ゲート：版を上げた状態で `bash database_android/tool/check_before_build.sh` を実行し **ALL PASSED**（`TZ=JST-9`、ログ `/c/w/gate-apk1103.log`・`/c/w/cbw-apk1103/`）。PC 778件、UTC条件27件、Flutter 764件、analyze 情報28件（エラー・警告0）、JS 78本。前回（fae1565）だけ失敗していた `test_pscube_auto_browser` も今回の全体で成功。
- APK：`flutter build apk --release --no-pub --build-name 0.5.50` で、`DATABASE_ANDROID_CLONE=original`（`--build-number 2026110301`）と `pscube`（`2026110302`）。`database_android/build/releases/0.5.50/` に
  - `database-0.5.50-2026110301.apk`（96,669,769バイト、`com.keyan.database_android`、表示名 database、SHA-256 `decb096160729700f1b3f679bb899a2a6cf5bc747ad1bd4b443d508b44897f73`）
  - `database-pscube-0.5.50-2026110302.apk`（96,669,793バイト、`com.keyan.database_android.pscube`、表示名 database P’s CUBE、SHA-256 `fdb1fc03f77659055e16ba83cda73d3bee17d51bd5971132ef8d1a841d11b101`）
  - aapt2で版・ID・表示名、apksigner（`JAVA_HOME` は Android Studio の `jbr`）で署名を確認（証明書SHA-256 `4332fcb9…a047`、0.5.49と同じ）。`SHA256SUMS.txt`・ビルドログ2本を同じフォルダーに保存。
- 端末：`adb devices` に端末が無く（USB未接続）、入っている版は読めていない。インストールはしていない（利用者が行う）。
- 0.5.49のAPK2本と `build/app/outputs/apk/release/app-release.apk` をごみ箱へ移した。
- 未確認：スマホでの動作（今夜の0時予約で機種一覧を全部読めるか、途中で止まったときに待機の知らせが出るか）。11/1・11/2の抜けた機種の取り直し。

## 【P’s CUBE Android：0時に機種一覧で3回止まった件の記録・知らせの保持・同じページでの読み直し】2026-11-04 Claude

- 経緯：0.5.50（11/3 23:46に利用者が導入。adbの `dumpsys package` で確認）で、11/4 0時の予約（11/3の分）が機種一覧で3回止まり、「ON・同じページで3回失敗したため待機中」になった（AIがadbの画面読み取りで確認。「完了」とは出ず、途中の一覧は受け付けていない）。利用者「止まったみたいな表記出てない？」「なぜこうなるの？」「直接操作していいよ」。
- AIが確かめたこと（利用者の許可でスマホをadbで操作。サイトのページを新しく開いたのはOFF→ONの1回だけ）：
  - 止まった後の画面の機種一覧を手で下まで送ると「Lうみねこのなく頃に2」で終わった。PCの `pscube.sqlite3` の `active_machine_keys`（60機種）でも最後の機種。止まった時点で48番目あたりは表示されていた。どちらの理由（いつもの8割未満／前回より少なく毎回違う）で止まったかは、知らせが上書きされて分からない。
  - 0:41にOFF→ONすると、機種一覧は1回目（16秒）で60機種そろって保存され（「残り60件」）、11/3の分の取り込みが進んだ（01:06時点で残り57件、1ページ約25秒）。完了は未確認。
  - 0.5.48→0.5.49でP’s CUBEの読み込み方の変更は無い（`git diff cbf109c 45bead3`：常駐を止める失敗の `debugPrint` だけ）。
  - Androidには失敗を残す仕組みが無かった（logcatは常駐を止める失敗の3か所だけ。端末のlogcatも起動の1行のみ）。
- 利用者「次のビルドでそれをいれよう」「ちょっとスクロールするだけで出てくるなら自動読み込みも頑張ってもらいたいものだね」→ 実装（APKは作っていない。次のビルドで入る）：
  - `database_android/lib/error_log.dart`（新規）：PC `error_log.py` と同じ形の `errors.log`。書き先 `/sdcard/Android/data/com.keyan.database_android.pscube/files/errors.log`（`getExternalStorageDirectory`、PCから `adb pull` で読める。Android 16の端末で `/sdcard/Android/data/` を読めることを確認。フォルダーは初めて書いたときに作られる）。60秒間引き・256KiBで1世代。
  - `pscube_import_page.dart`：記録する所＝機種一覧の表示件数と秒数（`pscube.list`）、少なかった回ごとの件数（`pscube.index`）、保存の失敗（`pscube.save`）、見張りの失敗（`pscube.auto.tick`）、止まった知らせ（`pscube.auto.stop`）。3回目の失敗の知らせを `_autoHeld` に覚え、次の確認でも一般の文で上書きしない。開き直しの知らせに件数を出す。機種一覧が足りないときの1回目は開き直さず、次の回に同じページのまま下まで送り直して読み直す（2回目は開き直し、3回目で待機。続きの機種はサイトが最初に受け取ったデータから足すため通信は増えない＝10/28の調査）。
  - `pscube_store.dart`：`PscubeIndexRetry` に `previous`（前回の機種数）を足し、減った一覧でも件数を渡す。
  - PC版は変えていない（PCでは起きていない）。文書 `database/PSCUBE_AUTO_CAPTURE.md` に 2026-11-04 の節。
- 試験：`test/error_log_test.dart` 4件（新規）。`test/pscube_auto_flow_test.dart`：上書きしないこと・件数・記録の行、同じページの読み直しでそろえば開き直さず保存（新規1件）、開き直し回数の期待値を変更（1→0、2→1）。上書きに戻すと3件、読み直しを外すと4件落ちることを確認。Flutter全769件成功、analyze 情報28件（エラー・警告0、前からの指摘だけ）、照合版 `a60fd18e46df`（生成スクリプト4本）で `test_release_info`・`test_pscube_capture`・`test_pscube_auto_browser`・`test_pscube_net_capture`・`test_pscube_absent_tab_auto`・PCの `test_pscube_auto*`・`test_release*` 成功。全体ゲートはAPKを作るときに流す（今回は未）。
- 未確認：0時に機種一覧が止まる原因そのもの。次のビルドを入れた後の0時の `errors.log` で調べる（`adb pull /sdcard/Android/data/com.keyan.database_android.pscube/files/errors.log`）。
- 追加（同日、利用者「進まない場合は停止じゃなくて読み込み直ししてスクロール作業するようにしてね」）：Androidの自動取り込みで、一覧が進まない（機種一覧が足りない＝`PscubeIndexRetry`・一覧の読み込みの時間切れ＝`pscubeListTimeoutMessage`）ときは、3回で止めない。`_listRetries` で `_autoFailures` と分けて数え、見張りの回ごとに同じページで下まで送り直して読み直し、3回に1回だけページを読み込み直す（`pscubeListReloadEvery = 3`）。60回（約20分、`pscubeListMaxRetries`）で待機（知らせは件数つきで保持）。読み込み直しは約1分に1回（ふだんの取り込みは1分に約3ページ）。台別ページなど一覧以外の失敗は3回で待機のまま。PC版は変えていない。上限の数（60回・3回に1回）はAIが決めた値で、利用者の確認は未。
  - 試験：`pscube_auto_flow_test.dart` の減った一覧・途中の一覧の2件を「60回まで読み直し、読み込み直しは19回、上限の後は読まずに待つ」に書き換え、時間切れの読み直しの1件を新規（模擬ブラウザに `listTimeouts`）。時間切れの扱いを外すと落ちることを確認。Flutter全770件成功、analyze 情報28件（前からの指摘だけ）。照合版 `541fd63e6aa4` で `test_release_info`・`test_pscube_capture`・`test_pscube_auto_browser`・`test_pscube_net_capture`・`test_pscube_absent_tab_auto`・`test_pscube_scroll`・PCの `test_pscube*`・`test_release*` 成功。APKは未作成（次のビルドで入る）。全体ゲートは未（ビルド時に流す）。
- 利用者の報告（11/4）：「Androidでの取り込みうまくいってました」＝0:41にAIがOFF→ONした11/3分のP’s CUBEの取り込みが、最後まで終わった（AIは01:06の残り57件までを見ただけで、完了は利用者の報告）。

## 【取り込みの通知・抜けた日の取り戻し・答え合わせ・ひとこと・ウィジェット】2026-11-04 Claude

- 依頼：利用者「今の取り込み不具合がなおれば…神アプリにしたい」→ AIの5案から「12346実装へ！」。出す画面は利用者の選択（答え合わせ＝閲覧ページ、ひとこと＝閲覧ページ・共有カレンダー、1・2＝P’s CUBEとメルヘン両方、ウィジェット＝通常版・P’s CUBE版）。条件「デザインバランス悪くなったりするのはやめてね」「4については吟味に吟味を重ねて文章作るようにしてね」。利用者「答え合わせのページの質が悪かったから助かります」。基準 `b01b12d`。
- 仕様の詳細はリポジトリ直下の `ADDITIONS_20261104.md`（各機能の規則・ファイル・試験）。答え合わせは着手前に `../outputs/normal-reassessment-20261023/報告.md` の①⑥⑦を読み、「当時の候補と再計算の候補を混ぜない」「全台と並べる」「判定できない台を示す」「設定・利益の保証と書かない」を反映した。候補の選び方・採点は変えていない。
- コミット（手元→今回まとめて送信）：`6d968c6`（P’s CUBEの通知・取り戻し、ネイティブの通知）、`fbb85dc`（メルヘンの通知・取り戻し）、`2cf6868`（ウィジェット）、`a4dd525`（当時の候補での答え合わせ、PCの書き出し、Googleの引き継ぎ）、`a5b86ae`（ひとこと）、最後に解析の指摘2件・照合版・文書・この記録。
- 見た目の確認（AIが撮影。数字はすべて撮影用の偽データ）：共有カレンダーは月の集計の下に同じ枠・左寄せで「ひとこと」（最初は説明文と同じ中央寄せにしたが、4行の文が読みにくかったので枠に入れた）。閲覧ページは店舗の選択の下にカード、答え合わせは既存のカードのまま文と目安を足した。撮影手順は `/c/w/dc/shot_share.mjs`・`shot_viewer.mjs`（作業用、リポジトリ外）。
- ゲート：`bash database_android/tool/check_before_build.sh` **ALL PASSED**（`TZ=JST-9`、`/c/w/gate-spice.log`・`/c/w/cbw-spice/`）。PC 781件、UTC条件27件、Flutter 795件、JS 79本。analyze はこのとき30件（情報のみ）で、増えた2件（`day_comment.dart`・`pscube_import_page.dart` の書き方）をゲート後に直して28件に戻し、`day_comment_test`・`pscube_auto_flow_test`（32件）、照合版の作り直し後の `test_release_info`・`test_pscube_capture`・`test_pscube_auto_browser`・`test_meruhen_cloud_sync`・`test_pscube_cloud_sync`・PC `test_release*` を流し直して成功。Kotlin はデバッグ用ビルド（`flutter build apk --debug`）で組み立てを確認（配布用APKではない）。照合版 `5a38593d6fa4`。
- 未実施・未確認：APK作成（Androidの1・2・6はAPKを入れるまで届かない）。閲覧ページ・共有カレンダーの公開（利用者の確認待ち）。Googleのメルヘン同期スクリプト `meruhen_cloud_sync.gs` の貼り替え（当時の候補を閲覧ページへ届けるのに必要。貼り替え前は「計算し直した候補」で動く）。実機での通知・ウィジェット・0時の取り戻し、実データでのひとことの文面。PCのメルヘンの取り戻しは作っていない。
- 公開（同日、利用者「公開して」）：送った版 `c2f539a` で全体ゲートをもう一度流して **ALL PASSED**（`/c/w/gate-pub.log`・`/c/w/cbw-pub/`。PC 781件、Flutter 795件、analyze 情報28件、JS 79本、照合版 `5a38593d6fa4`）。その stage を `outputs/all-machines-20261101/public-viewer|public-share` に写した（ファイル一覧は一致、差は閲覧ページ6ファイル・共有9ファイル）。iPhone閲覧ページ `database-viewer` `6c09bf3`（Pages 41732465711 成功）、共有カレンダー `database-share` `2beff1e`（Pages 41732470941 成功）。配信中の main.dart.js・version.json・viewer_parts.mjs・app.mjs・data.mjs・index.html・sw.js が stage と一致（改行をそろえて比較）。公開URLに対して `test_share_viewer_browser.mjs` 成功。実機Safariでの表示は未確認。
- Googleのメルヘン同期スクリプトの貼り替え（利用者）：**AIの誤り**で、最初にリポジトリのまま（`MERUHEN_HISTORY_VIEWER = false`）の全文を渡し、利用者はフォルダIDの有無を確かめずに上書きした。7:26に古い方式で1回実行（利用者のログ：閲覧用に60台を反映、48,297件・38.1MB）。直した版（16行目だけ `true`、`outputs/additions-20261104/gs/meruhen_cloud_sync.gs`）を渡し、利用者が貼り直して7:29に履歴方式で実行（ログ：66,385件・29.7MB、6日更新・差分0パーツ）。AIが同期フォルダの `database-viewer-parts-meruhen.json` を読んで、v2（履歴方式）・66,385件のまま・処理版 `5a38593d6fa4` を確認。フォルダIDは自動実行ではスクリプトのプロパティ（`meruhenCloudFolder`）を使うので空欄でも影響なし。今後は貼り替え用ファイルで利用者の設定行（履歴方式 true）を残す（AIの覚え書きに記録）。
- 利用者がPC版を起動し直して「共有用ファイルを更新」（7:33）：`database-viewer.json`（手元と同期フォルダ）に `answer_candidates` が載ったことをAIが確認（9/26〜11/3の店・日66件、例 幸町11/3は121台）。Googleの次の実行で一覧の見出しへ引き継がれる見込み（未確認）。
- APK（同日、利用者「apkビルドしておいて」）：`pubspec.yaml` を `0.5.51+2026110402`。ビルド前の全体ゲートを始めたが、利用者「追加した分の確認だけで良いよ」で止めた（同じコード `c2f539a` は7:35のゲートで ALL PASSED 済み。変えたのは版番号だけで、照合版にも入らない）。追加分の試験だけ流して成功：Flutter analyze 情報28件、Flutter 105件（pscube_auto_flow・pscube_list_wait・pscube_store・meruhen_gap_day・home_widget・answer_check・viewer_answer_candidates・day_comment・error_log・meruhen_browser）、PC `test_pscube_import`・`test_answer_candidates`（`unittest discover -s tests` で。`-m unittest tests.…` の呼び方では別の試験ファイルを読めず4件エラーになるので注意）、JS `test_day_comment`・`test_meruhen_cloud_sync`・`test_pscube_scroll`・`test_share_viewer_browser`・`test_pscube_auto_browser`・`test_release_info`。止めたゲートのPCの試験の処理も止めた（利用者のPC版の処理には触れていない）。
  - `database_android/build/releases/0.5.51/`：`database-0.5.51-2026110401.apk`（96,869,325バイト、`com.keyan.database_android`、表示名 database、SHA-256 `64bfb32afa86f22a2708052229110f14b020756fe28cf98d85fc3b0692c7d0de`）、`database-pscube-0.5.51-2026110402.apk`（96,869,341バイト、`com.keyan.database_android.pscube`、表示名 database P’s CUBE、SHA-256 `4d6f26cbb4a558d382c62b5fee981177e26a7f8e85bbf0ae721b81b4e44f56fb`）。aapt2で版・ID・表示名、apksignerで署名（証明書 `4332fcb9…a047`、前と同じ）を確認。`SHA256SUMS.txt`・ビルドログ2本を同じフォルダーに保存。0.5.50のAPK2本と `build/app/outputs/apk/release/app-release.apk` をごみ箱へ。インストールはしていない（利用者が行う）。
- 利用者の報告（同日）：「通知ONにしました」。AIが `adb shell dumpsys package` で確認：2本とも 0.5.51 が入っている（通常版 2026110401、P’s CUBE版 2026110402）。通知の許可は **P’s CUBE版が許可済み**（`POST_NOTIFICATIONS: granted=true, USER_SET`）、**通常版はまだ**（`granted=false`。通常版で自動取り込みをONにしたときに聞かれる）。ウィジェットの見え方・通知の実際の表示・今夜0時の取り戻しと `errors.log` は未確認。
  - 続き：利用者「メルヘンもＯＮにしてある」。AIが確認し直すと、通常版も `POST_NOTIFICATIONS: granted=true, USER_SET` になっていた（先の確認は許可する前だったと思われる）。2本とも通知は許可済み。

## 2026-11-04 改善点の検討用プロンプトの作成（Claude）

- 依頼：「databaseについての改善点を検討させるプロンプト」。基準 `1c994bb`（手元main＝origin/main）。
- 作ったもの：会話で渡したプロンプトのみ（ファイルには保存していない）。読ませる資料は AGENTS.md・AI_COLLABORATION.md・DATABASE_REVIEW_20261101.md（既出の課題）・ADDITIONS_20261104.md（11/4の追加）・SCORING_POLICY.md など。調査は読むだけ（コード・DB・公開物は変えない、対象サイトへ接続しない、ビルド・同期・公開しない）とし、4画面（PC・Android 通常／P’s CUBE・閲覧ページ・共有カレンダー）ごとに、根拠・再現・影響・手間・優先度と「確認済み／推測」を分けて書かせる形。カメラアプリ（nail-gauge）は対象外。
- 確かめていないこと：プロンプトを実際に流した結果はまだ無い。コード・試験・CIには触れていない。

## 【databaseアプリ全体の改善点の検討（調査と提案のみ）】2026-11-05 Claude

- 依頼：利用者が貼った検討用プロンプト（前項で作ったもの）。PC／Android 通常版／Android P’s CUBE版／iPhone閲覧ページ／共有カレンダーの5画面について、不具合・再発・使い勝手・性能・保守性・11/4の追加分の未確認点を調べる。コード・DB・設定・公開物・端末は変えない、対象サイトに接続しない、CIを動かすpushはしない、カメラアプリは対象外、採点・翌日候補の精度は扱わない。
- 基準：正本main＝手元 `6102848`、database-ci main `7a9df13`（手元の祖先）。両方を取得して確認。最後のALL PASSEDの `c2f539a` から基準までのコードの差は `pubspec.yaml` の版番号だけ。
- 報告：リポジトリ直下の `DATABASE_REVIEW_20261105.md`（一覧・根拠の行番号・確かめ方の区別・11/1の課題の今の状態・未確認・最初の3件）。
- 要点：**高1** P’s CUBE（Android）の抜けた日の取り戻しが、取り戻した日を起点に次の6日を探すため（`pscube_import_page.dart:981-1003`・`:1300-1319`。メルヘンは `web_import_page.dart:667` で起点を固定）、新台・台数の変わった機種があると過去の日が毎回「未取得あり」に見え、記録の最初の日まで1日ずつさかのぼってサイトの7日より古い日の全台一覧も開く恐れ（1ページずつ開いてタブなしで飛ばす）。今夜11/5 0時が0.5.51の初回。**高2** 同期スクリプトの履歴方式の定数を取り違えても止まらない（11/4に実際に起きた）。**高3** Android通常版のメルヘンの取り戻し条件①「記録が1台も無い日」が、PCで取り込んだ日も抜けとみなしうる（Androidは手動の `importBackup` 以外でPCの記録を読まない）。中：Androidのメルヘン取り込みの失敗がerrors.logに残らない、結果の通知が音の鳴る重要度、CIに時間の上限が無い、版番号だけのコミットでCIが動く（11月16回中3回）、P’s CUBE一覧の読み直し上限が未確認の値、ウィジェットの計算が取り込み中も走る。低は報告を参照。
- 流したもの：`database_android/` で、リポジトリ外の一時フォルダーに置いた模擬 `review_gap_test.dart` を `TZ=JST-9 flutter test --no-pub` で実行（合成DBのみ）。1回目は期待値の書き方の誤りで失敗、直して1件成功。新台を機種一覧に足すと、完了していた10/1の未取得が0件→1件（新台の全台一覧）、9/25〜9/30も1件ずつ増えることを確認。続けて起点をずらす部分（画面の処理）は動かしていない（コード読み）。ほかの試験・全体ゲート・CIは流していない（コードが版番号以外変わっていないため）。`gh run list`・`git log` は読むだけ。
- 未確認：実機の通知・ウィジェット・0時の取り戻しの実際の動き・端末の `errors.log`、端末のP’s CUBEの記録の最初の日と新台の数、利用者がAndroidでメルヘンを自動取り込みする頻度、Googleの実スクリプト。
- 変更はこの記録と報告の2つの.mdだけ（CIは動かない）。`tools/push_ci.py` で正本へ送る（日本時間11/5＝前半）。

## 【改善点を全部直す・台番の末尾の印（共有カレンダー・閲覧ページ・PC）】2026-11-05 Claude

- 依頼：前項の報告に利用者「全部直して」。作業中に利用者が「機能追加依頼」（差枚一覧で選んだ末尾を機種一覧でも追える・機種一覧の平均差枚の横に各台の差枚の点。共有カレンダー・iPhoneブラウザ版・PC版。スマホ幅で確認。pushは承認後）。基準 `c0ac745`（正本 main と同じ）。
- 出す画面の確認（AGENTS.md）：「差枚一覧」「平均差枚つきの機種一覧」という名前の画面が無かったので質問。利用者の回答：対応は「共有：日の画面のTOP50→機種の台一覧、閲覧ページ：全機種の台一覧→1機種の表、PC：機種一覧タブ」、**Androidアプリには入れない**。
- **各台の差枚の点は取りやめ**：一度3画面に作ったが、利用者「みてて気持ち悪いからやっぱりいらない。PC版、スマホ版もろもろいらないです」「機能消したあとのゴミみたいなものが残らないように」。関数・定数・CSS・画面の部品・試験・共通の試験データ（net_dot_cases.json）をすべて消し、「強かった機種10選」「この日の機種一覧」の行と既存の試験（`test_share_viewer_browser` の期待）は元に戻した。`git grep` で残りが無いことを確認（この記録を除く）。
- 仕様・ファイル・試験の詳細はリポジトリ直下の `ADDITIONS_20261105.md`。要点：高1 P’s CUBEの取り戻しの起点を最初の日に固定＋サイトの7日の範囲、高2 同期スクリプトに前回の方式を覚えて取り違えなら止める（`vhModeProblem`、Googleの貼り替えが要る）、高3 メルヘンの取り戻し①を前後の日が端末にある日だけ、中1 Androidのメルヘンの失敗を `meruhen.error`、中2 結果の通知を音なしのチャンネルへ、中3 CIに `timeout-minutes: 45`、中4 版番号だけのpushをしない決まりを AGENTS.md に、中6 メルヘンの自動取り込み中はウィジェットの計算を止める、低1 `notice.blocked`、低2 文書、低4 作業ツリー2つを外した（ブランチ `codex/viewer-drive-efficient-20261004` は残す）。中5・低3は理由を書いて変えていない。末尾の印は共有 `app.mjs`・閲覧ページ `rack_suffix.dart`・PC `machine_list.py`。
- 途中の誤り：①共有カレンダーの既存の画面試験（`test_share_viewer_browser`）を一度「成功」と読んだが、出力の読み取りの誤りで、実際は点を足した行の文の変化で落ちていた（裏で流した1回目のゲートで発覚。点を取りやめたので期待は元に戻った）。②自作の試験の期待値の誤り（23番も末尾3、長町南は3台以下がバラエティ）を直した。どれも製品のコードの誤りではない。
- 1回目の全体ゲート（改善点だけの段階、`/c/w/gate-fixall1105.log`）：上の①の1件だけ失敗、ほかは成功。2回目（点を含む段階）は点を取りやめたため途中で止めた。
- 照合版 `0ab1c21a4ec7`（生成スクリプト5本：build_release_info.py・build_viewer_parts.mjs・build_event_history_share.mjs・build_pscube_capture.mjs・build_pscube_cloud_sync.mjs）。
- 確認（点を取りやめたあと。利用者「ゲートは流しなおす必要があるところだけやってね」で全体ゲートは流し直さず、変えた所に関係するものだけ）：Flutter analyze 情報28件（前と同じ、エラー・警告0）、Flutter 126件（rack_suffix・viewer_navigation・pscube_auto・pscube_auto_flow・meruhen_gap_day・meruhen_browser・home_widget・error_log・pscube_store・pscube_list_wait）成功。JS `test_release_info`・`test_viewer_parts`・`test_meruhen_cloud_sync`・`test_pscube_cloud_sync`・`test_pscube_capture`・`test_pscube_auto_browser`・`test_share_viewer_suffix_mark_browser`・`test_share_viewer_browser`・`test_share_viewer`・`test_share_viewer_all_racks_browser`・`test_share_viewer_suffix_browser` 成功。PC `test_machine_list`（9件）・`test_app_startup`・`test_release*`・`test_push_ci` 成功（`TZ=JST-9`）。Androidは通知の Kotlin の変更を `flutter build apk --debug` で組み立てられることを確認（配布用APKではない、端末には入れていない）。ほかは push 後の CI（full を含む3ジョブ）で確かめる。
- スマホ幅の確認：共有カレンダーは上の画面試験を 320/393px で（日の画面で末尾7→TOP50の17・27番に「末7」→機種の台一覧へ引き継ぎ・全台のまま→「末尾7 ×」で解除→全機種の台一覧へ引き継ぎ→日付を変えると解除、横へのはみ出しなし）。閲覧ページは閲覧ページをその場でビルドし（`flutter build web` と `stage_viewer.py`、`/c/w/cbw-sfx/viewer`）、合成データで 320/393px を作業用の手順（リポジトリ外）で開いて撮影：全機種の台一覧で末尾3→3・13・23・33番に「末3」→戻って「北斗」の表に「末尾3 ×」と3・13・23番の印（全6台のまま）→「末尾3 ×」で消える、はみ出しなし。画像 `/c/w/shots1105/`。Web版の読み上げ用の情報では0〜9のボタンが1つにまとまる（押すのは画面の位置で行った）。PCは試験だけで確かめた（画面の撮影はしていない）。
- 公開・Google・APK：未。閲覧ページ・共有カレンダーの公開、Googleの2本（高2）の貼り替え、Android APK（高1・高3・中1・中2・中6・低1と末尾は閲覧ページだけなのでAndroidの変更は改善点だけ）はまだ。

## 【次にGoogleの同期スクリプトを貼り替えるときの覚え書き（貼り間違いで止まる仕組み）】2026-11-05 Claude

- 利用者「スクリプト貼り直すのか」→ 今は貼り直さない（今のスクリプトのままで同期は動く）。利用者「その時にその行入れるように覚えておいてね」「共同作業だから覚書は大事なことは書くの」。**CodexもClaudeも、次の貼り替えのときに必ず守る。**
- **まだGoogleに入っていないもの**：`5511c49` の「貼り間違いで止まる仕組み」（`vhModeProblem`、`changeMeruhenCloudMode`／`changePscubeCloudMode`）。対象は `database_android/tool/meruhen_cloud_sync.gs` と `pscube_cloud_sync.gs` の2本（閲覧用の `viewer_drive_script*.gs` 2本は版の文字だけの違いで貼り替え不要）。
- **次にこの2本のどちらかを貼り替えることになったら**（ほかの修正のためでも）、その時点のリポジトリの最新から貼り替え用ファイルを作り、この仕組みが入っていることを利用者に伝える。
- **利用者の設定行を必ず残す**：実運用は履歴方式。`MERUHEN_HISTORY_VIEWER = true`・`PSCUBE_HISTORY_VIEWER = true`（リポジトリの版は false のまま）。11/4にリポジトリのまま（false）を渡して、利用者が上書きしてしまった。貼り替え用ファイルは `outputs/<作業名>/gs/` に置き、リポジトリの版との差がこの設定行だけであることを確かめてから渡す（`tools/prepare_google_updates.py` を使ってもよい）。フォルダーIDの行は空でも自動実行には影響しない（スクリプトのプロパティを使う）。
- 貼り替えた後の最初の同期で、その時の方式（履歴方式）がスクリプトのプロパティ `meruhenCloudMode`／`pscubeCloudMode` に記録される。その後に false の版を貼ってしまうと、閲覧用ファイルを書き換えずに止まり、ログに理由が出る。方式を本当に変えるときだけ `changeMeruhenCloudMode`／`changePscubeCloudMode` を実行してから同期する。

## 【Claudeの覚え書きにしか無かった決まり・約束を AGENTS.md と DEVELOPMENT_CHECKS.md へ移した】2026-11-05 Claude

- 利用者「あのね。共同作業だから覚書は大事なことは書くの」「共同作業の覚書に片方が書いて片方が書かなかったらまずいことになるとかわかってる？」。Claudeの覚え書き（このPCのClaudeだけが読める）を見直し、共有の文書に無い・過去の月の記録に埋もれていたものを移した。
- `AGENTS.md`：共有記録の節に「大事な覚え書きはAI自身のメモだけに置かない」と「今後の予定・約束」（段階Bの見直し11/7ごろ・開始の期限2027-01-05ごろ、店舗別の候補比較の評価11/26以降1回、直近高成績の除外の判定2027-02-01以降1回、次のGoogle同期スクリプト貼り替えの注意）。新しい節「同じフォルダーでの作業・配布・公開の決まり」（自分のファイルだけコミット、表示を変えたら公開か未公開と報告、古いAPKはごみ箱、adbはコマンドプロンプト用、共有ページのアンケートの回答シート）。
- `DEVELOPMENT_CHECKS.md`：このPCで全体ゲートを流すときの PYTHON・NODE・PLAYWRIGHT_MODULE・Flutter・短い CHECK_BUILD_WORK。
- 中身は既存の記録・利用者の過去の指示と同じで、新しく決めたことは「大事な覚え書きは共有に書く」だけ。Codexのメモに共有記録に無い大事なことがあれば、Codexも同じように移してほしい（利用者の指示の趣旨）。

## 【5511c49 のCIの結果】2026-11-05 Claude

- [CI 41862972266](https://github.com/imakurudev-eng/database/actions/runs/41862972266)（対象 `5511c49`、改善点の修正と台番の末尾の印）：full・pc (windows-latest, UTC)・pc (ubuntu-latest, UTC) の3ジョブとも success（日本時間 07:01 に `gh run view` で確認）。再実行なし。前の「CIは実行中・結果未確認」をこれで確定する。
- 利用者の指示で、送信後にPCをスリープにした（01:05ごろ〜07:00ごろ）。その間、PC版の当日分の読み込みが止まっていた可能性がある（店舗別の候補比較の11/4の分の締切は11/5 03:00）。影響は確かめていない。
- 未実施のまま：閲覧ページ・共有カレンダーの公開（末尾の印はまだiPhone・共有に出ていない）、Googleの2本の貼り替え（次に貼り替えるときに入れる）、Android APK。

## 【11/5 0時のP’s CUBE（スマホ）がHTTP 403で止まった：errors.logの読み取り】2026-11-05 Claude

- 利用者「今朝は取り込み失敗してて早々に中断されてた」「スマホだけね」。AIは対象サイトを開いていない。スマホ（RFGL146LVVW、0.5.51）の `errors.log` を `adb pull` で読み出しただけ（端末の操作・アプリの設定変更はしていない）。通常版には `errors.log` が無かった（記録する出来事が無かった）。
- 記録（P’s CUBE版）：00:00:45 機種一覧を60件まで表示（26秒）→ 00:00:46 `pscube.index` 1回目：前回の60機種に対して58機種 → 同じページで読み直し（読み込み直しなし）→ 00:01:06 60件まで表示（20秒）で受け付け、11/4の分へ → **00:18:17 `notice` 通信エラー：サイトがアクセスを拒否（HTTP 403）、自動取り込みを止めた**（`pscube.auto.stop`）。
- 分かること：約17分（1ページ約25秒で40ページほど）で拒否された。`pscube.gap` が無いので、抜けた日の取り戻しは始まっていない（昨夜の報告の高1は今回の原因ではない）。機種一覧の読み直しは1回だけで、ページの読み込み直しは無かった。403で止まるのは既存の決まりどおり。拒否の理由はサイトが示さないので分からない（10/6・10/31と同じ形）。
- 未確認：11/4の分がどこまで入ったか、今もアクセスが拒否されているか（確かめるにはサイトを開く必要があるので、AIはしない）。
- 気をつけること：スマホの0.5.51にはまだ高1の修正（取り戻しのさかのぼり防止）が入っていない。今夜の0時に11/5の分が済むと、11/4（途中）・11/2・11/1の取り戻しと、新台による過去の日へのさかのぼりで、ふだんよりアクセスが増える恐れがある。今夜までに修正を入れたAPKを入れるか、今夜は0時の予約を止めるのがよい（利用者の判断待ち）。AGENTS.mdのとおり、弾かれたときはPC・スマホ・AIのブラウザで対象サイトのページをすべて閉じて待つ。回線を変えて避けることは勧めない。

## 【Android 0.5.52 のAPK作成（取り戻しのさかのぼり防止などの改善点を含む）】2026-11-05 Claude

- 依頼：今朝のP’s CUBEの403の報告のあと、利用者「APKを作って」（今夜0時の取り込みの前に、取り戻しのさかのぼり防止＝高1をスマホに入れるため）。基準 `6621405`（正本 main と同じ。database-ci の `7a9df13` を含む）。
- ゲート：コードは `5511c49` から変わっていない（その後は .md だけ、`git diff --stat 5511c49 HEAD`）。`5511c49` の [CI 41862972266](https://github.com/imakurudev-eng/database/actions/runs/41862972266) の full ジョブの `Complete pre-build gate`（`check_before_build.sh` と同じ全体ゲート）が success なので、それを使い、手元で流し直していない（利用者「ゲートは流しなおす必要があるところだけやってね」）。版番号は照合版の計算に入らない（照合版 `0ab1c21a4ec7` のまま）。
- 版：`pubspec.yaml` を `0.5.52+2026110502`。`flutter build apk --release --no-pub --build-name 0.5.52` で `DATABASE_ANDROID_CLONE=original`（`--build-number 2026110501`）と `pscube`（`2026110502`）。
- `database_android/build/releases/0.5.52/`：
  - `database-0.5.52-2026110501.apk`（97,033,165バイト、`com.keyan.database_android`、表示名 database、SHA-256 `753c5aa9e1f0d285c8e304fd837c2d65cc2a0c90f4a55b94a4e2fa801e1b598f`）
  - `database-pscube-0.5.52-2026110502.apk`（97,033,181バイト、`com.keyan.database_android.pscube`、表示名 database P’s CUBE、SHA-256 `54cd79f4a8ccad396af1d900ef11d0bb4a9bde63b1c5e7e2a66c2cd9ff4e96ab`）
  - aapt2で版・ID・表示名、apksignerで署名（証明書SHA-256 `4332fcb9…a047`、0.5.51と同じ）を確認。`SHA256SUMS.txt`・ビルドログ2本を同じフォルダーに保存。
- 0.5.51のAPK2本と `build/app/outputs/flutter-apk/` の `app-release.apk`・`app-debug.apk`（11/5の確認用ビルド）をごみ箱へ移した。
- 端末（読むだけ）：2本とも 0.5.51（2026110401／2026110402）。新しい版の方が上なので上書きで入る。インストールは利用者が行う（未）。
- スマホに入る変更（11/5の改善点のうちAndroid分）：P’s CUBEの取り戻しの起点固定とサイトの7日の範囲（高1）、メルヘンの取り戻し①の条件（高3）、メルヘンの失敗の `meruhen.error`（中1）、結果の通知を音なしのチャンネルへ（中2）、メルヘンの自動取り込み中はウィジェットの計算を止める（中6）、`notice.blocked`（低1）。末尾の印はAndroidには出さない（利用者の指定）。
- 未確認：スマホでの動作（今夜0時の取り込みと取り戻しの範囲、通知が鳴らないこと）。今朝の403の拒否が解けているか。
- 送信：版番号の行の変更なので、送るとCIが1回動く（AGENTS.md「版番号だけのコミットを単独でpushしない」）。手元でコミットし、送るかは利用者に確認する。
- 追記（07:10）：利用者「今画面みえる？またエラーでてる」。AIが `adb exec-out screencap`（画面を写すだけ）と `errors.log` の読み出しで確認：**07:08:21 にも同じHTTP 403**（`notice`・`pscube.auto.stop`）。7:08ごろにページを開き直した（利用者の「もう一度開く」かアプリの開き直し。AIは端末を操作していない）ときもまだ拒否されていた。画面の0時の予約は「11/6 0:00に11/5の分を開始」、11/4の分の残り65件。利用者には、しばらくページを開かない・数時間空けて「もう一度開く」を1回だけ・0.5.52を入れた後に取り込み画面を開くとアクセスが1回増える・夕方もまだ403なら今夜は予約を止める、と伝えた。

## 【P’s CUBEのアクセス拒否（403）を減らす方法の検討（調査のみ）】2026-11-05 Claude

- 依頼：利用者「直す方法ないか検討して。頻繁にアクセス→アクセス拒否／スクロールしないと全体表示されないから取り込みエラー→まあこれは改善したっぽい？」。利用者はこの時、PCで11/4の分を取り込み中。AIはサイトを開いていない。PCの `data/pscube.sqlite3` を読むだけ（`mode=ro`）とコードを読んだだけ。
- 1晩のページ数（PCのDB、10/29〜11/3）：1日295台・59〜60機種。台別ページを読む台（当たりのある台）285〜294台。**1晩およそ 機種の全台一覧60＋台別ページ約290＝約350ページ**（15〜25秒おきで約2時間）。そのうち500G以下の台は1日19〜24台。
- 分かったこと（コード）：
  1. 台別ページ1枚には、その台の**7日分のグラフと数値**が入る（`assets/pscube_capture.js` のグラフは最大7日分、保存側は7日分の履歴を確かめる）。なのに「取り込み済み」の印（`rack_captures`）は、そのページの日の分だけに付ける（Android `pscube_store.dart:682-686`、PC `pscube_import.py:907`）。そのため、抜けた日の取り戻し・同じ日をもう一度取り込むとき・PCとスマホの両方で同じ日を取り込むときに、すでに後の日のページで入っている日の台別ページを1台ずつ読み直す。スマホはPCの取り込みを知らないので、今夜0時（0.5.52）に11/5の分のあと、11/4（PCで取り込み中）・11/2・11/1 などを台別ページから読み直す恐れがある。
  2. サイトのページには、開いているだけで定期的に通信する仕組み（`jquery.netcube.alive.js`、10/6に問題になったもの）がある。Androidは自動取り込みが止まった後も、0時の予約を待つ間も、取り込み画面にサイトのページを読み込んだまま（11/5 07:10の画面写真でもページが出ていた）。PC版も取り込みが終わった後、窓にページを開いたまま（10月後半の記録）。アプリにもPC版にも、この通信を止める処理は無い（`alive` で検索して該当なし）。通信の頻度と403との関係は未確認。
- 一覧のスクロール（2つ目の点）：11/5 0時は、機種一覧が58件→同じページで読み直して60件（ページの読み込み直しなし）で受け付けた。11/3・11/4の修正（いつもの機種数の8割・20件区切りの着き直し・同じページでの読み直し）が効いている。残る点：読めない夜は一覧ページの読み込み直しが最大約20回（60回の読み直しのうち3回に1回、11/4にAIが決めた値）になりうる。
- 提案（どれも未実装）：
  - A（高）：待っている間・止まった後・すべて取り込んだ後は、サイトのページを空白にする（Android：取り込み画面、0時の予約の待機中も。PC：取り込み窓）。0時に始めるときにどのみち機種一覧を開くので、取り込みのページ数は変わらない。何時間も続く定期通信を無くす。
  - B（高）：台別ページの7日分の履歴で、前の6日も「取り込み済み」にする（PC・Androidを同じ規則で。数値が変わったら印を外す既存の決まりは残す）。取り戻し・取り直しの日は台別ページをほぼ読まなくなる（数十〜数百ページ減）。ふだんの夜のページ数は変わらない。
  - C（中）：一覧の読み込み直しの上限を下げる（例：読み込み直しは3回まで、あとは同じページで読み直すだけ）。
  - D（利用者判断）：500G以下の台は台別ページを読まない（1晩約20ページ、6%減）。その台のグラフと差枚が無くなり、日の総差枚にも入らなくなる。採点v12は500G以下を採点しないので点数は変わらない。
  - E（運用）：同じ日をPCとスマホの両方で取り込まない。403が出たら数時間空ける。回線を変えて避けない（AGENTS.md）。
- 未確認：403の本当の理由（サイトが示さない）、定期通信の間隔、1ページあたりの通信の数。これらはサイトを開かないと測れないので、AIは測っていない。
- 利用者の決定（同日）：利用者「スマホ読み取りは緊急用にしてやはりメインはPCにするべきか」→ AIは「どちらでもアクセスの量はほぼ同じで、大事なのは1日分を1台だけで取り込むこと。毎朝PCを使えるならPCメイン・スマホ緊急用がよい。その場合は今夜からスマホの0時の予約をOFFに、0.5.52は取り込み画面を開かずに入れるだけでよい」と比較を示し、利用者「そうだね」。**以後、P’s CUBEはPCがメイン（朝に前の日の分）、スマホは緊急用（手動）、スマホの0時の予約はOFF。** AGENTS.md に節を追加。予約をOFFにする操作は利用者が行う（AIは端末を操作していない。OFFにしたかは未確認）。

## 【P’s CUBEのアクセスを減らす修正 A〜D（PC・Android）】2026-11-05 Claude

- 依頼：前項の検討に利用者「ABCD実装。Eはそうするから大丈夫」「403はどう考えてもアクセス拒否と同じとみていい」。基準 `a8d2398`（正本 main と同じ）。対象サイトは開いていない。仕様の詳細は `database/PSCUBE_AUTO_CAPTURE.md` 末尾「2026-11-05：サイトへのアクセスを減らす」（`PSCUBE_IMPORT.md` も1行）。
- A：止まった後・待っている間はサイトのページを開いたままにしない（定期通信 `jquery.netcube.alive.js`）。
  - Android `pscube_import_page.dart`：`_park`（about:blank）を、自動取り込みが止まった・すべて取り込んだ・一覧で待機、のときに呼ぶ。`_parkWhenIdle`：OFFのまま5分（`pscubeIdlePark`）ページを開かず取り込まなければ空白に。利用者のOFF・手で開いていたときの通信エラーはすぐには空白にしない。空白のページは開いたページに数えない（止まった理由が残る）。「もう一度開く」は空白なら機種一覧から。
  - PC `pscube_import.py`：`AutoPilot._stop_and_close` を足し、自動取り込み中の通信エラー・止められた・同じページで3回失敗・機種一覧が3回とも足りない、のときに自動取り込みを止め、理由の文（「サイトのページは閉じました。時間を空けてから、Cookieを消さずに取り込み窓を開き直してください」）を残して窓を閉じる（既存の `close_when_finished`）。手で開いていたときの通信エラーでは閉じない。`BLOCKED_MESSAGE` の文をこれに合わせて短くした。
- B：台別ページの7日分（選んだ日とそれより前）すべてに `rack_captures` の印（Android `pscube_store.dart`、PC `import_page`）。数値が変わった日は印を外す決まりのまま。前の日の記録にもMY・回数・グラフ・差枚が入ることをPCのDB（読むだけ）で確認（10/25〜11/3の当たりのある台2,829件すべてにMY、差枚2,825件）。
- C：Androidの一覧の読み込み直しは3回に1回・最大3回（`pscubeListMaxReloads`）。60回まで同じページで読み直す決まりは同じ。
- D：500G以下の台は台別ページを読まない（Android `PscubeStore.skipsRackPage`、PC `skips_rack_page`／`RACK_PAGE_MIN_GAMES`、共通JS `skipsRackPage`）。採点の下限（`minScoredGames`／`MIN_SCORED_GAMES`）と同じ500で、PCの試験で一致を確かめる。回転数が分からない台は読む。取得状況の表示の文は変えていない（当たり0回の台と同じ「未取得（理由未記録）」）。
- 試験（足した・直したもの）：Android `pscube_store_test.dart`（7日分の印・500Gの境目。書き出しの印は1→7）、`pscube_auto_flow_test.dart`（すべて取り込んだら空白・5分で空白にして0時は機種一覧から・読み込み直しは3回まで）。PC `test_pscube_import.py`（7日分の印・500Gの境目と採点の下限の一致・機種一覧が足りないときは止めて窓を閉じる）、`test_pscube_auto.py`（自動取り込み中の通信エラー・3回失敗で窓を閉じる文、手で開いていたときは閉じない）。
- 照合版 `c70b463093b1`（生成スクリプト5本）。Googleの .gs 4本は版の文字だけの違い（貼り替え不要）。
- 全体ゲート **ALL PASSED**（`TZ=JST-9`、`/c/w/gate-abcd1105.log`・`/c/w/cbw-abcd1105/`）：PC 787件、UTC条件 27件、Flutter 805件、analyze 情報28件（前と同じ）、JS 80本（失敗・未実行なし）。
- 今動いていたPCの取り込み窓（19:04起動）は前のコードのまま。新しい決まりは次に窓を開いたときから。Android の分は APK を入れるまで届かない（APKは未作成。スマホは緊急用なので急がない）。
- 利用者の依頼で、Codexにこの修正の指摘を検討してもらうプロンプトを作って渡した（会話の中だけ。差分は `git diff a8d2398`、読むだけ・コードは直さない・対象サイトに接続しない・記録は自分のファイルだけコミット）。
- 送信：未（コードの変更なので送るとCIが1回動く。利用者に確認する）。

## 【PCのP’s CUBEの自動取り込みが何度もOFFになった件・取り込み窓を閉じた】2026-11-05 Claude

- 利用者「さっきからちょこちょこ自動取り込みがoffになる」「何も出てなかった気がする」（止まった理由の文は見ていない、という利用者の記憶）。AIが読んだもの（読むだけ）：取り込み窓（`pscube_import.py`）は19:04起動で、`7e445b9` の前のコードのまま。`data/errors.log` のP’s CUBEの記録は 19:05 `pscube.index_retry`（機種一覧が前回より少ないため開き直し）だけ。`data/pscube.sqlite3` の最後の書き込みは 20:03、11/4の分は7機種・46台（台別ページ済み43台）。前のPC版は自動取り込みがOFFになった理由を errors.log に残さないので、理由は分からない。
- **19:28〜19:42 にAIが同じPCで全体ゲート（ビルド・ブラウザの試験を含む重い処理）を流していた。** PCが重いとページの表示が遅れ、前のコードは「サイトがデータを表示しない状態が続いた（止められた可能性）」でOFFにしうる。ただしOFFは20:03ごろまで続いたとのことで、これだけが原因とは言えない（確かめていない）。今後、利用者が取り込み中のときは、重い処理（全体ゲート・ビルド）を同じPCで流す前に利用者に確かめる。
- 利用者「一回閉じて」→ AIが 20:4x に取り込み窓へ通常の閉じる操作（`CloseMainWindow`、×ボタンと同じ）を送り、取り込み窓のプロセスが終わったことを確認。保存中ではなかった（最後の書き込みは20:03）。PC版本体（app.py）はそのまま。
- 次に取り込み窓を開くと `7e445b9` の新しいコードで動き、エラー・止められた可能性で止まったときは窓を閉じて理由をPC版の親画面に知らせとして出す。止まった理由を errors.log にも残す変更は未（提案のみ）。

## 【PCのP’s CUBE：止まった理由とON/OFFを errors.log に残す】2026-11-05 Claude

- 利用者「いれる」（前項で提案した、PCの自動取り込みが止まった理由を errors.log に残す変更）。`database/pscube_import.py` だけ。
  - 窓を閉じる止まり方（完了・通信エラー・止められた・3回失敗・機種一覧が足りない）は `close_when_finished` が `pscube.auto.stop` にその理由を残す。
  - 画面のボタンでON/OFFしたら `pscube.auto.switch`（ON/OFF・取り込み日）。
  - それ以外でOFFになったら、見張り（`auto_loop`）が `pscube.auto.off` にその時の表示の文を残す（今日の「何も出ずにOFFになった」を追うため）。
- 試験：`tests/test_pscube_auto.py` の窓を閉じる試験で `pscube.auto.stop` の行を確かめる。PCのP’s CUBE 144件・`test_error_log`・`test_release*` 成功。照合版 `547648247513`（生成スクリプト5本。.gs は版の文字だけ、貼り替え不要）、`test_release_info`・`test_viewer_parts`・`test_pscube_capture` 成功。全体ゲートは流していない（PCの1ファイルと試験だけ。CIのfullで流れる）。
- 送信：未（コードの変更。次に送るときに一緒に）。

## 【7e445b9 のCI full 失敗の原因と試験の直し・PC版の起動し直し】2026-11-05 Claude

- CI [42014916445](https://github.com/imakurudev-eng/database/actions/runs/42014916445)（`7e445b9`）：pc (ubuntu)・pc (windows) は成功、**full が失敗**（利用者がエラーメールの画面を共有）。`gh run view --log-failed` で、落ちたのは `test_viewer_event_calendar_browser` の1件だけ（`saved name is shown with no late mark`、試験の150行目、日本時間20:14ごろ）。ほかの段は成功。再実行はしていない。
- 原因（試験の書き方）：イベント名を保存したあと `waitForTimeout(500)` で0.5秒だけ待ち、表示・保存を1回だけ確かめていた（3か所）。CIの機械が重いと間に合わない。試験の時計は 2026-10-17 に固定なので日付は関係ない。`7e445b9` の変更（P’s CUBE）はこの画面に関係しない。同じ試験は手元のゲート（19:28〜19:42）とそれまでのCIでは成功していた。
- 直し（試験だけ）：`database_android/tool/test_viewer_event_calendar_browser.mjs` の3か所を、ファイルにある `waitSeen`（表示が出るまで最大15秒）・`waitFor`（保存されたイベントが期待どおりになるまで最大20秒）に置き換えた。手元で、ゲートの閲覧ページ（`/c/w/cbw-abcd1105/viewer`）に対して2回流し、2回とも成功。
- PC版：利用者「start.cmdから起動し直して、pscubeの自動取り込みまでonにして」。AIがPC版本体に通常の閉じる操作を送って閉じ、`start.cmd` から起動し直した（20:42起動を確認）。取り込み窓を開いて自動取り込みをONにする画面の操作は、操作の許可がスマホのRemote Controlからは出せず（許可の画面はPCにだけ出る）、利用者が戻ってきて「もういいや」。取り込み窓は利用者が開く。新しい取り込み窓は `498c952` までのコード（止まったら窓を閉じて理由を知らせる・errors.log に残す）で動く。
- 送信：`498c952`（errors.log）とこの試験の直しは手元のみ。送るとCIが1回動く。
