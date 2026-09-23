# database

メルヘンワールド長町南店・幸町店の1000円46枚スロットを、個人利用のために端末内へ保存・採点するツールです。PC版はPython/Tkinter、Android版はFlutterで実装しています。

対象・採点・取り込み方針は[AI_COLLABORATION.md](AI_COLLABORATION.md)と[SCORING_POLICY.md](SCORING_POLICY.md)を参照してください。実サイトの自動巡回や自動保存は行いません。

## 個人データ

実データ、SQLite、バックアップ、APK、ビルド成果物はGitに登録しません。Android版をクリーン環境でビルドする場合は、`database_android/assets/database_seed.example.json`を`database_seed.json`へコピーしてください。空の記録から開始できます。

## 開発時の確認

PC版:

```powershell
cd database
python -m unittest discover -s tests
```

Android版:

```powershell
cd database_android
flutter analyze
flutter test
```
