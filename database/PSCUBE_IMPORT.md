# P’s CUBE スロット取り込み

PC版のホーム画面「P’s CUBE（スロット）を取り込む」、または
`python database/pscube_import.py` から開く。Android版は「取り込み」画面の
「P’s CUBE を開く」から開始する。認証は表示されたサイト内で人が行う。
その後「スロット機種一覧」→「未取得を取り込む」を押すたびに、
機種一覧、機種別の全台一覧、台別7日分を保存し、次のページへ移動する。
認証を自動で回避する処理はない。

既存のメルヘンワールド記録には混ぜず、PCは `database/data/pscube.sqlite3`、
Androidは専用の `pscube.sqlite3` に保存する。PCの
`database/data/pscube-viewer.json` とAndroidの共有ボタンで出力した
`pscube-viewer.json` はiOSブラウザ版の「ファイルを選択」で読み込める。
MYを最大放出数として保存する。機種タイプはブラウザ版で
「ノーマル／その他」を設定できる。

PC配布版に組み込む場合、`database-pscube.exe` を既存の
`database-browser.exe` と同じ配布フォルダに置く。例：

```powershell
python -m PyInstaller --onefile --name database-pscube `
  --add-data "database_android/assets/pscube_capture.js;database_android/assets" `
  database/pscube_import.py
```

取り込み用JavaScriptは `node database_android/tool/build_pscube_capture.mjs` で
ブラウザ版のパーサーから再生成する。保存済みのSafariアーカイブによる
読み取りテストは `test_pscube_capture.mjs`、PC保存順序のテストは
`python -m unittest test_pscube_import.py`。実サイトでの認証後の操作と
Android実機ビルドは別途確認する。
