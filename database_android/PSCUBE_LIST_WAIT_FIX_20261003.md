# Android P’s CUBE：各機種の全台表示を待つ・0.5.20

利用者のPCの31台中6台での停止と「毎回下までスクロール」の指定を受け、PCの修正後に
Android版の修正・ビルドも依頼された。開始main `5430505ad577925848ea7d453899685c9781af78`。

- Androidにも台数が約2秒安定すると全台表示を終える処理があったため、現在の機種URLに一致する
  保存済み設置台数を読む処理を追加。これはSELECTだけで、機種・記録・保存値を変更しない。
  別機種・貸玉・店舗の台数は流用せず、未知の台数は推測しない。
- 各機種の一覧ごとに毎回下までスクロールし、既知の設置台数未満なら短時間の安定で終了しない。
  最大70回・各350msの制限は維持。一覧のない台別ページは待機しない。
  取り込み中の画面破棄・別ページへの移動後はスクロールを続けない。
- 保存時の全台数一致、台別取得、採点・バックアップ形式・デザインは維持。P’s CUBEの初期7.1秒、
  メルヘンの初期3.5秒も維持。Cookie/利用者DBの削除・初期化処理は追加・実行しない。
- `0.5.19+2026100203` から `0.5.20+2026100301` へ更新。同日の既存APKを確認し、初回の連番01。

## 検証

- 関連21件、全Flutter425件成功。一時DBと疑似時計を使用。
  2機種で6台から3秒後に31台が揃うまで毎回待つ、70回の上限、台数不明・台別、ページ移動時の中断を確認。
  設置台数の読み取りで既存のmachines/records/stateが変わらないことも確認。
- `flutter analyze --no-pub --no-fatal-infos` 成功。error/warning0、変更箇所以外の既存info17。
- ログは作業フォルダ `outputs/android-list-wait-tests-20261003.log` と
  `android-list-wait-analyze-20261003.log`。関連検証は開始日の `android-list-wait-targeted-20261002.log`。
- 接続端末SM_A253Cの現行は0.5.19 / 2026100203。読み取りのみ。
  新APKのインストール、実機WebViewの修正後動作、実サイトの31台取得は未実施。

## ビルド成果物

mainへ反映したソース `5c6027265a2de31fd88f250082d727a2f44cfbb0` から
`flutter build apk --release --no-pub` 成功。

- 保存先：`C:\Users\keyan\Documents\Codex\2026-09-24\a\work\outputs\database-0.5.20-2026100301.apk`
- サイズ：92,686,361 bytes。
- SHA-256：`8B819E91574106732337F1E4CA3A027172B333C05FEE5B4AB1A48902EF69DDE6`。
- aapt：`com.keyan.database_android`、0.5.20 / 2026100301。
- apksigner：署名有効、前回0.5.19 APKと証明書一致。
  証明書SHA-256 `4332fcb94ea909187733f9e8e3537d428f84d3248e39eeda2baf64387ee7a047`。
- 個人seedファイルのSHA-256は検証・ビルド前後で不変。

接続端末を指定して既存アプリへ上書きする（実行は利用者）：

```powershell
& "C:\Users\keyan\AppData\Local\Android\Sdk\platform-tools\adb.exe" -s RFGL146LVVW install -r "C:\Users\keyan\Documents\Codex\2026-09-24\a\work\outputs\database-0.5.20-2026100301.apk"
```

アンインストール・データ消去は行わない。新APKのインストール・実機での修正後の取り込みは未実施。
