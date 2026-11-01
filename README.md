# database

個人利用のために端末内へ保存・採点するツールです。PC版はPython/Tkinter、Android版はFlutterで実装しています。

対象・採点・取り込み方針は[AI_COLLABORATION.md](AI_COLLABORATION.md)と[SCORING_POLICY.md](SCORING_POLICY.md)を参照してください。

## 自動取り込み

メルヘン・P’s CUBEの取り込み画面には「自動取り込み」があります（PC版・Android版）。

- 起動時は必ずOFFで、利用者がONにしたときだけ動きます。ON状態は保存しません。
- 利用者が開いた取り込み画面の中で、表示中のページを読んで保存し、次の未取得ページへ進みます。保存・バックアップ・同期は手動の取り込みと同じ処理です。
- 間隔はメルヘンが0.1〜4.5秒（初期3.5秒）、P’s CUBEが15〜25秒のランダムです。
- 人間確認・利用規約の同意・読み込み中の画面では、押さずに待ちます。P’s CUBEでは、止められたとみなせる状態（確認画面ではないのにデータが出ない状態が5回以上・1分以上）が続くと自動でOFFになります。
- Android版のP’s CUBEには、取り込み画面を開いたままにしておくと毎日0時に自動取り込みを始める予約（切り替え式）があります。

詳しい決まりは [database/PSCUBE_AUTO_CAPTURE.md](database/PSCUBE_AUTO_CAPTURE.md) と [database/PSCUBE_ACCESS_PLAN.md](database/PSCUBE_ACCESS_PLAN.md) を参照してください。

## 個人データ

実データ、SQLite、バックアップ、APK、ビルド成果物はGitに登録しません。Android版をクリーン環境でビルドする場合は、`database_android/assets/database_seed.example.json`を`database_seed.json`へコピーしてください。空の記録から開始できます。

## 開発時の確認

共通の試験入口とLinux・Windowsの準備は [DEVELOPMENT_CHECKS.md](DEVELOPMENT_CHECKS.md) を参照してください。

PC版:

Windowsでは初回に `database/setup_python.cmd` を実行して専用Pythonを用意します。通常の起動は `database/start.cmd` のままです。

PC版の試験は2か所にあります。`database/tests/` と、`database/` 直下の `test_*.py`（P’s CUBE・あにすろなど）です。両方を流してください。

```powershell
cd database
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m unittest discover -s . -p "test_*.py"
```

2行目は `database/` 直下のファイルだけを拾います（`tests/` は含みません）。APK・PC・Web公開のビルド前には、PC・Android・閲覧ページの全試験をまとめて流す `bash database_android/tool/check_before_build.sh` を使います。最後に「ALL PASSED」と出たときだけビルドします。

Android版:

```powershell
cd database_android
flutter analyze
flutter test
```
