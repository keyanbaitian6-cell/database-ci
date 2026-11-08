# P-STATIONの検証候補をiPhoneの閲覧ページで見る

P’s CUBEの20スロを開き、「イベントカレンダー」の下にある「検証候補」を押す。当日が最初に表示され、保存済みの別の日にも切り替えられる。対象日、元データの営業日、保存時刻、候補台番号が表示される。前日分に確定前のサイトセブン記録を使った日には、台数も表示する。

無作為は保存済みの比較基準。日付と下2桁一致は探索扱い。下2桁23の確認用候補は23日だけ表示する。5のつく日のゴーゴージャグラー仮説は機種全体の比較のため、この台番号一覧では扱わない。

## 初回の設定

1. 自分用の閲覧用Apps Scriptを `tool/viewer_drive_script.gs` の版へ更新する。プロジェクトの「スクリプト プロパティ」に `PSCUBE_VALIDATION_FOLDER_ID` を作り、Driveの「P-STATION 前向き検証」フォルダのURLにある `folders/` の後ろのIDを設定する。「デプロイを管理」から既存のウェブアプリを新バージョンにする。
2. iPhone閲覧ページは `tool/check_before_build.sh` の確認を通した版を `tool/stage_viewer.py` 経由で公開する。iPhoneでは既存の自分用閲覧URLを使う。
3. PCの前向き検証フォルダで `毎朝実行.cmd` と同じ場所に `viewer-sync-dir.txt` を作る。Driveの同期済み「P-STATION 前向き検証」フォルダの**絶対パス1行**をUTF-8で記入する。次の毎朝実行で予測を保存した後、同じフォルダに表示用JSONが出る。

既存の閲覧用URLで読み出すという利用者指定に従い、検証候補の専用合言葉は設けない。閲覧用URLを知る人は表示用JSONも取得できる。共有カレンダー用の読み取りスクリプトは対象外。

## 保存済み分だけ書き出す

リポジトリのルートで以下を実行する。例はローカルの確認用フォルダ。既に存在する出力先を指定する。

```powershell
$analysisPython = 'C:\Users\keyan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $analysisPython -B -X utf8 database/pscube_validation_export.py --records '../outputs/pstation-forward-20261108/records' --out-dir '../outputs/pstation-forward-20261108/viewer-staging'
```

出力名は `validation-candidates.json`。閲覧側が読むのは指定フォルダにあるこの名前のファイル1個だけ。検証設定と予測原本のハッシュ、同じ研究の記録かどうか、対象日午前9時前の保存かを検査する。直近31保存日分の候補だけを抽出する。BB/RB・差枚、原本の入力スナップショット、ローカルパスや結果は含めない。同じ内容は再度書き出さない。書き出しに失敗した場合も、予測の保存結果はPCに残る。

ZIPは復元用。ブラウザ表示は上記JSONから行い、ZIPを開く手間はない。
