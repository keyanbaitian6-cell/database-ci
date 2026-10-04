# 日付指定取り込み・上から／下から取り込む（P’s CUBE・メルヘン、PC・Android）

決定日：2026-10-04。利用者の依頼：「寝てしまって取り込み途中で日付変わって自動取り込みが使えなくなった。PC・Android版ともに、日付指定取り込みボタンが欲しい。P’s CUBEにも。上から取り込む、下から取り込むボタンもほしい」。
利用者の選択：①日付を選ぶと、その日の分だけ取り込みを続ける ②上から／下からは「機種の一覧の上から／下から」 ③日付が変わる基準は日本時間の午前2時 ④P’s CUBEとメルヘンの両方（PC・Android）。

## 画面

取り込み画面の自動取り込みボタンの下に追加（P’s CUBE・メルヘン、PC・Androidで同じ）。

- **日付指定取り込み（取り込む日）**：「指定なし（サイトの表示どおり）」と、営業日の今日から6日前までの7日。営業日は**日本時間の午前2時で切り替わる**（0〜2時はまだ前日）。画面を開いたまま午前2時を過ぎても、選択肢は自動で作り直される。選んだ日はOFFの間だけ変えられる。
- **上から取り込む／下から取り込む**：押すと、選んだ日・向きで自動取り込みをONにする（これまでの「自動取り込み：ON/OFF」ボタンも使える。向きは前回のまま）。ONの間は押せない。**PCは上から・Androidは下から**のように分ければ、2台で挟み撃ちにできる（記録は自動では合流しない：重なった機種は両方が取り込む）。
- 起動のたびに「指定なし・上から」に戻る。ONは保存しない（従来どおり）。

## 動き

- **取り込み日を指定すると**、次に開く機種・台は「その日の未取得」だけを数える（サイトの表示が新しい日に変わっても、昨日の分の続きを探す）。表示中のページの日が違えば**保存しない**（理由を表示）。自動取り込みはそのページで待つ。
- **向き**：機種を一覧の上から／下からたどる。1つの機種の中の台は、これまでどおり台番号の小さい順。
- **P’s CUBE**：全台一覧の日付は、サイトの日付タブ（本日／1日前…）でしか選べない（URLで指定できるかは**わかりません**）。サイトのボタンはアプリが押さない方針のため、全台一覧で日が違うときは「全台一覧の日付タブを◯/◯に合わせてください」と表示して待つ。手で合わせると続く。台別ページ（7日分入り）はアプリが日付つきで自動で開く。機種一覧を取り直しても、最初の機種へ戻らず、その日の未取得の先頭へ進む。その日の分がすべて済むと自動でOFFにし、取り込み日の指定を外す。
- **手動で取り込むとき（メルヘン）**：機種の台がすべて済んで機種一覧へ戻ったとき、一覧の最初から探し直さず、いま済ませた機種の**次**（一覧の並びの順）から探す。先が無いときだけ、一覧の最初から取りこぼしを探す。自動取り込みは対象外（決めた向き・日付で探す）。PCは一覧URLの `database_after`、Androidは `_afterMachine` で渡す。
- **手動で取り込むとき（P’s CUBE）**：自動取り込みがOFFのときは、保存したページの次から探す（全台一覧→その機種の台別ページ→同じ機種の次の台番→次の機種。最後まで来たら残りの取りこぼしへ最初から回る）。機種一覧を保存したあとと、自動取り込みは対象外。
- **メルヘン**：機種の表は、サイトの行を押す代わりに、日付つきのURL（`…standlist_slot/?kind_code=21&machine_name=…&target_date=日付`）で開く。行を押すと「サイトが選んでいる日付」になるため。この形は、サイトが日付を選んだときに自分で付ける形で、保存済みの取り込み元URLにもあり、行が反応しないときの予備の移動でもすでに使っていた。機種名の符号化は変えず、文字列で付け足す。行の文字から機種名を組み立てるときは、全角スペースを保つ（半角に直すと空のページになる。例：`L無職転生　NM`）。台別のグラフは、保存済みの個別台リンク（日付つき）を使う。

## 実装

- P’s CUBE PC：`pscube_import.py`（`business_day`・`recent_business_days`・`PscubeStore.import_page(expected_day, direction)`・`next_target(day, direction)`・`AutoPilot.set_target/configure`・カード）、判定スクリプト（`web/pscube/data.mjs` の `autoPageState` が選ばれた日 `day` を返す）。
- P’s CUBE Android：`pscube_store.dart`（同上）、`pscube_auto.dart`（`pscubeRecentBusinessDays`・`pscubeAutoDecision(targetDay)`）、`pscube_import_page.dart`。
- メルヘン PC：`browser_import.py`（`recent_days`・`with_target_date`・`_Bridge.set_target_day/set_auto_capture`・`_checked`・`next_unimported_machine`）、`auto_capture.py`（カード）。
- メルヘン Android：`import_day.dart`、`web_import_page.dart`。

## 確認

- PC：`test_pscube_import.py`・`test_pscube_auto.py`（P’s CUBE）、`tests/test_meruhen_day.py`（メルヘン6件）。
- Android：`pscube_store_test.dart`・`pscube_auto_test.dart`・`pscube_day_buttons_test.dart`（P’s CUBE）、`import_day_test.dart`・`meruhen_day_buttons_test.dart`（メルヘン）。
- ブラウザ：`tool/test_pscube_auto_browser.mjs`（P’s CUBEのカード）、`tool/test_meruhen_cookie_browser.mjs`（メルヘンのカード）。

## 限界・未確認

- 実サイトでの動き（日付つきの機種の表を直接開いて表示されるか、日付タブを合わせたあとの続き）は未確認。
- メルヘンAndroidの「機種の選び方」（取り込み日・向き）は、画面の部品の試験とPC版の試験で確認しており、Android実機の画面そのものの通し試験はない。
- 2台で挟み撃ちにしたときの記録の合流は自動ではない（バックアップの読み込みで合わせる）。
