# 既存版＋同じ機能のクローンAPK

利用者指定（2026-10-03）：既存のdatabaseは残し、IDと表示名だけを分けたクローンを1つ作る。
「database P’s CUBE」は用途を見分けるための名前で、メルヘンとP’s CUBEの両機能を持つ。
共通Flutter/Kotlinコード・デザイン・保存形式・採点・Cookie処理をそのまま使う。
既存版も引き続き通常どおりビルドできる。

| ビルド指定 | applicationId | ランチャー表示名 |
| --- | --- | --- |
| 環境変数なし / `original` | `com.keyan.database_android` | database |
| `DATABASE_ANDROID_CLONE=pscube` | `com.keyan.database_android.pscube` | database P’s CUBE |

GradleのProviders APIで現在のプロセスの環境変数を読む。未知の指定はビルドを拒否する。
namespaceは従来の`com.keyan.database_android`を維持。ManifestのActivity/Service名は、
別IDでも同じ既存クラスを参照するよう完全修飾名にする。
通知・FileProvider等のアプリID由来の値は生成Manifestで照合する。

## ビルド

正本最新mainを取り込み、AGENTS.mdに従いAPKビルドごとにpubspec.yamlのversionCodeを増やす。
作業場所は`database_android`。以下はクローン指定を元に戻す例（PowerShell）。

```powershell
$taskPreviousClone = $env:DATABASE_ANDROID_CLONE
try {
    $env:DATABASE_ANDROID_CLONE = 'pscube'
    flutter build apk --release --no-pub
} finally {
    $env:DATABASE_ANDROID_CLONE = $taskPreviousClone
}
```

生成`build/app/outputs/flutter-apk/app-release.apk`は通常版と同じ場所なので、
成功後に`database-pscube-clone-<versionName>-<versionCode>.apk`へコピーして区別する。
今回のクローンはversionName `0.5.21` / versionCode `2026100303`。
通常版0.5.21/2026100302は既に保存済みで、今回は通常版の再ビルドはしない。

## 利用

- クローンを追加インストールしても、既存版をアンインストールしない。
- 別IDのため、端末上のDB/Cookie/アプリ内設定は独立する。既存アプリのデータは自動で移らない。
  Cookie認証はクローン内で手動で行う。記録は必要に応じて既存のバックアップ取り込みを使う。
  APKに含まれるローカルseedは通常版と同じ内容を保持する。
- 既存版でメルヘン、クローンでP’s CUBEを開いてそれぞれ自動ONにする使い方を想定。
  各アプリ内部の取り込み画面を閉じたときの停止仕様は同じ。
- バックグラウンド・画面OFF・実サイトでの同時取り込みが安定するかは未確認。
  名前/IDだけの変更では継続動作の保証は増えない。

出典：
- https://developer.android.com/build/configure-app-module
- https://developer.android.com/training/data-storage
- https://docs.gradle.org/current/userguide/build_environment.html#sec:accessing_environment_variables

## 2026-10-03の結果

- 基準main：`95eb8955828c3740e3e38832e8da4db65fa2e5f5`。
  クローン設定：`785ac991455b37c4d0f6b3127b67834e991f270a`をmainへpushしてからビルド。
- 通常版の生成Manifestを確認：環境変数未指定で元のID・表示名・MainActivityを維持。
  `:app:processReleaseMainManifest`成功。通常版APKは再生成していない。
- クローンの`flutter build apk --release --no-pub`成功。
  aaptでID `com.keyan.database_android.pscube`、表示名 `database P’s CUBE`、
  versionName `0.5.21` / versionCode `2026100303`をAPK自体から確認。
- APK保存先：
  `C:/Users/keyan/Documents/Codex/2026-09-24/a/work/outputs/database-pscube-clone-0.5.21-2026100303.apk`
  92,686,385 bytes。SHA256 `10B3958AA099DEB705DE19FF565AD17F21D8F1E1EC0CD93A0DBF02811A7F2C3B`。
- apksignerで署名有効。証明書SHA256は通常版と同じ
  `4332fcb94ea909187733f9e8e3537d428f84d3248e39eeda2baf64387ee7a047`。
- 通常版0.5.21/2026100302との比較：assets以下47ファイルと、
  arm64-v8a / armeabi-v7a / x86_64の`libapp.so`がすべてバイト単位で一致。
  共有ユーザーIDなし。生成Providerのauthoritiesは全てクローンIDを先頭に持つ。
  apkanalyzerでAPKのDEXに元のMainActivity/AutoCaptureServiceの定義が含まれることも確認。
- ローカルseedのSHA256はビルド前後で不変。利用者のDB・Cookieを削除・変更する操作はしていない。
- 今回の変更はAndroidビルド識別情報と規則によるversionCode増加のみ。
  共通Flutter/Kotlinコードは変更していないため、直前のFlutter426件を重複実行していない。
  今回は生成Manifest・releaseビルド・APKの資産/Dart本体比較・署名・DEXを検証した。
- 端末へのインストール、実機起動、実サイト・同時取り込み・画面OFF継続は未実施。
  Gradleの既存非推奨警告は残るが、ビルドは成功。PC版は今回変更・ビルドしていない。
- ログと検証スクリプト：作業フォルダ`outputs/android-pscube-clone-*`、
  `outputs/android-clone-original-manifest-20261003.xml`、`outputs/verify_android_pscube_clone_20261003.py`。

追加インストール（アンインストール不要）：

```powershell
& "C:/Users/keyan/AppData/Local/Android/Sdk/platform-tools/adb.exe" install -r "C:/Users/keyan/Documents/Codex/2026-09-24/a/work/outputs/database-pscube-clone-0.5.21-2026100303.apk"
```
