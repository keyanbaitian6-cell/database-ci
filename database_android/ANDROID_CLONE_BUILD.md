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

ビルド・APK検証結果は完了後に追記する。
