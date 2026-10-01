# PC版・機種切替でONのまま止まる問題への修正（2026-10-01）

利用者から、作業フォルダの `start.cmd` で起動したPC版が、ON表示のまま次の機種一覧で停止するとの報告があった。実サイトは自動操作していないため、現地で起きた直接原因は未確認。

従来のダミー試験は1機種の保存と機種一覧への復帰で終了し、2機種目へ進む経路を検証していなかった。コード上は、機種一覧の行クリックが反応しないと案内文を出すだけで `moveCommitted` を保持し、ONのタイマーから再試行できない停止経路があった。

`browser_import.py` と `auto_capture.py` を修正した。行クリック後も一覧URLが変わらない場合、Python側の定期実行から同じ画面を再確認し、保存済みの対象日を付けた同一店舗・1000円46枚スロットの機種別一覧URLへ進む。JavaScriptの遅延タイマーには依存しない。OFF後は古い移動を破棄し、確認画面・読み込み中はONのまま待つ。日付が確定できない場合は推測して保存せず、日付の選択待ちにする。

検証はlocalhostのダミーページと一時SQLiteだけを使った。

- PC全体のユニットテスト147件成功。
- `tests/smoke_auto_machine_switch.py`：2機種目の行クリックを意図的に無効化。Windows WebView2を最小化したまま、1機種目の表・グラフから2機種目の表・グラフまで4回保存し、機種一覧へ復帰した。遅延移動前にOFFにすると移動せず、再びONにすると再開した。
- `tests/smoke_auto_capture.py`：既存の確認画面待機、最小化、別窓の裏、旧自動移動との競合、サイズ確認が成功。
- Python構文、`git diff --check` 成功。
- 最終ステージングEXEに同梱された `browser_import`・`auto_capture`・`core` のコンパイル済みコードが現行ソースと一致。`tests/smoke_frozen_capture.py` で一時DBへの表・グラフ保存を確認。

`start.cmd` は同じフォルダのPythonソースを起動するので、修正を使うには現在の取り込みブラウザを閉じて開き直す。配布版は補助プログラムだけに変更があるため、`bin/database/` はそのまま、`bin/database-browser/` を同梱ランタイムごと更新した。旧フォルダは `bin/previous-20261001-machine/database-browser/` に退避した。最終ステージングは `C:\Users\keyan\amazon\database-build-staging-20261001-machine-final/database-browser/`。正式フォルダの全1303ファイルとステージングをSHA-256照合し、一致した。新 `database-browser.exe` のSHA-256は `68306310F3EE5A612DD7292CC340D8D1F3006FCCBD70DD59481F7D85A433009F`。

配置後の正式 `bin/database-browser/database-browser.exe` に対しても `tests/smoke_frozen_capture.py` を実行し、同梱コードの一致と一時DBへの表・グラフ保存を確認した。

既存の `data`・`reports` と採点コードは変更していない。実サイト、利用者の実データ、長時間の連続運転では未検証。実サイトで報告された停止がこの修正で解消するかは、利用者の次回確認が必要。
