# Androidバックアップの保存先（0.5.37以降）

通常版・P’s CUBE版とも、バックアップの書き出しでAndroid標準の保存画面を開く。
初回はメニューから **Google Drive → imakurudev@gmail.com → マイドライブ → database共有** を選び、元のファイル名のまま保存する。
3店舗分は同じ「database共有」直下へ保存する。メルヘン2店の `database-backup-android-…json` とP-STATIONの `pscube-backup-android-…json` は従来どおり別ファイル。

書き込みが成功した保存場所を端末内に覚え、次回の保存画面の初期表示に指定する。
通常版とP’s CUBE版の設定は別なので、それぞれ初回の選択が必要。
Google Drive側が初期表示の指定に対応しない場合や、前回のファイルを移動・削除した場合は再選択が必要になることがある。
「database共有」へ強制的・自動的にアップロードする方式ではない。フォルダIDやログイン情報をAPKに埋め込まない。

保存をキャンセルした場合・書き込みに失敗した場合は、バックアップ済みにしない。
端末内の元ファイルを残し、大きなファイルもストリームでコピーする。
全期間のメルヘンバックアップでは、従来の「保存できた」の確認を残す。Driveへのアップロードが完了したことを確認してから押す（その印は古い記録の整理に使われる）。
保存画面にDriveが出ない場合はDriveアプリのインストール・ログイン状態を確認する。

出典：Android公式 [Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files)、[EXTRA_INITIAL_URIの仕様](https://android.googlesource.com/platform/frameworks/base/+/01ad0c7e403794b272494f187d91f57bdfa07c9d/core/java/android/provider/DocumentsContract.java)。初期表示は保存先のプロバイダ次第であり、Google Drive実機での動作は別途確認が必要。
