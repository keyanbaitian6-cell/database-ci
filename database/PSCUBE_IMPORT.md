# P’s CUBE スロット取り込み

PC版のホーム画面「P’s CUBE（スロット）を取り込む」、または
`python database/pscube_import.py` から開く。Android版は「取り込み」画面の
「P’s CUBE を開く」から開始する。認証は表示されたサイト内で人が行う。
その後「スロット機種一覧」→「未取得を取り込む」を押すたびに、
機種一覧、機種別の全台一覧、台別7日分を保存し、次のページへ移動する。
認証を自動で回避する処理はない。

接続に失敗したら、Android・PCとも「もう一度開く」でCookieと取り込んだ記録を保持して再試行できる。
DNSエラーや対象ページのHTTP 403などを検出した場合、自動取り込みはOFFにする。
Androidでは「通信エラーの記録」、PCではエラー画面から直近8件の時刻・コード・接続先を確認できる。
「サイトの記録を消してやり直す」は別操作で、確認後にCookieなどを消す。DNSや403が解消する保証はない。

沖ドキ（「沖ドキ」「オキドキ」、半角の「沖ﾄﾞｷ」も）はメルヘンと同じく取り込みの対象外で、機種一覧から回る対象にせず、表・グラフも保存しない（2026-10-01反映）。当たりが1回もない台（0回転を含む）と、500G以下の台（2026-11-05から。採点の下限と同じ）は台別7日分を取りに行かない。台別ページを1つ取り込むと、その台の7日分すべてを取り込み済みにする（2026-11-05、`PSCUBE_AUTO_CAPTURE.md`）。

既存のメルヘンワールド記録には混ぜず、PCは `database/data/pscube.sqlite3`、
Androidは専用の `pscube.sqlite3` に保存する。PCの
`database/data/pscube-viewer.json` とAndroidの共有ボタンで出力した
`pscube-viewer.json` はiOSブラウザ版の「ファイルを選択」で読み込める。
MYを最大放出数として保存する。機種タイプはブラウザ版で
「ノーマル／その他」を設定できる。

PC配布版は次のスクリプトで3つのアプリをまとめてビルドする。
PyInstaller・pywebviewを入れたPython環境を指定する。リポジトリ直下で実行する例：

```powershell
.\database\build_windows.ps1 -Python 'Python環境\Scripts\python.exe'
```

`database/bin` に `database`、`database-browser`、`database-pscube` の
3フォルダができる。各フォルダのexeと`_internal`を一緒に配布し、
3フォルダを同じ親フォルダに置いて `database/database.exe` から起動する。
exeだけを抜き出さない。展開先のパスが長いと同梱ライブラリ（numpy等）の
ファイルが260文字制限で展開できないため、`C:\Users\<名前>\` 直下など短いフォルダへ展開する。
既存の `data` と `reports` を消したり、
配布物のデータで置き換えたりしない。

P’s CUBEの書き出しは専用の `pscube-viewer` 形式。
既存メルヘンワールドのバックアップに混ぜず、このJSONも別途保管する。
同時に保存・共有しないよう処理を直列化し、数値が更新された台は
台別7日分を再取得する。部分的な全台一覧や不正なグラフ・日付は保存を拒否する。

取り込み用JavaScriptは `node database_android/tool/build_pscube_capture.mjs` で
ブラウザ版のパーサーから再生成する。保存済みのSafariアーカイブによる
読み取りテストは `test_pscube_capture.mjs`、PC保存順序のテストは
`python -m unittest test_pscube_import.py`。実サイトでの認証後の操作と
Android実機ビルドは別途確認する。

採点・翌日候補（閲覧ページの試験表示）は `PSCUBE_SCORING.md`、バックアップ・Drive同期は `PSCUBE_SYNC.md` を参照。
自動取り込み（PC・Android、メルヘンと同じON/OFF・間隔・確認画面では待つ）は `PSCUBE_AUTO_CAPTURE.md` を参照。
