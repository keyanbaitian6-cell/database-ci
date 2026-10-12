# Android 0.5.36（2026-10-09）

ジャグラーオンラインの取り込み（お試し、JUGGLER_ONLINE.md。通常版だけ）、カレンダーの各日の差枚、P’s CUBEのカレンダー（取り込み画面）を含む版。

| 種類 | APK | versionCode | アプリID | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026100901.apk | 2026100901 | com.keyan.database_android | 38bfe12 | cb4f033c854b2c1904aa85261c27a11ccbe79beb5c36f71de7156531d3dd83a2 | 93924905 |
| P’s CUBEクローン | database-pscube-clone-0.5.36-2026100902.apk | 2026100902 | com.keyan.database_android.pscube | eec1e9a | 53e0457b0cab1029e754c5ab9e42ce15a9555c5ed272f5b3e09ffef332d07854 | 93924929 |

- 各ビルド前に check_before_build.sh ALL PASSED（ログ checks-normal/・checks-clone/）。
- 証明書SHA-256は両方 4332fcb94ea909187733f9e8e3537d428f84d3248e39eeda2baf64387ee7a047（従来と同じ）。
- 取込ボタン（JugglerCaptureService）は通常版で enabled=true、クローンで enabled=false。

```powershell
$adb = 'C:\Users\keyan\AppData\Local\Android\Sdk\platform-tools\adb.exe'
$apkDir = 'C:\Users\keyan\Documents\Codex\2026-09-24\a\work\database-main\database_android\build\releases\0.5.36'
& $adb -s RFGL146LVVW install -r "$apkDir\database-0.5.36-2026100901.apk"
& $adb -s RFGL146LVVW install -r "$apkDir\database-pscube-clone-0.5.36-2026100902.apk"
```

## 追加：通常版 0.5.36+2026101001（2026-10-10、取込ボタンが出ない不具合の修正）

| 種類 | APK | versionCode | アプリID | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101001.apk | 2026101001 | com.keyan.database_android | 4806293 | f63e04380d0d426bd12798466b6d6e4a6d6ded394206d9ba7e9ef219718fdcde | 94023209 |

- ビルド前に check_before_build.sh ALL PASSED（ログ checks-normal-1001/）。証明書SHA-256 4332fcb9…a047（従来と同じ）。取込ボタン enabled=true。

```powershell
& 'C:\Users\keyan\AppData\Local\Android\Sdk\platform-tools\adb.exe' -s RFGL146LVVW install -r 'C:\Users\keyan\Documents\Codex\2026-09-24\a\work\database-main\database_android\build\releases\0.5.36\database-0.5.36-2026101001.apk'
```

## 追加：通常版 0.5.36+2026101002（2026-10-10、取り込めなかった台を作る・店舗/日付の読み取り）

| 種類 | APK | versionCode | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101002.apk | 2026101002 | aed9cec | f90c83495793bb60bb5c4f979eedc2d2c6b758ad544dde112fed06cf6d35c837 | 94023209 |

- ビルド前に ALL PASSED（checks-normal-1002/）。証明書 4332fcb9…a047。

## 追加：通常版 0.5.36+2026101003（2026-10-10、取込ボタンで表を自動で撮る）

| 種類 | APK | versionCode | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101003.apk | 2026101003 | 6ddf04a | ebf24bca8ad4d78d6cf3c82226ab9c0ba8631358536584104b890ce9c1d860f6 | 94056049 |

- ビルド前に ALL PASSED（checks-normal-1003/）。証明書 4332fcb9…a047。サービス設定に canPerformGestures=true。

## 追加：通常版 0.5.36+2026101004（2026-10-10、全機種表示）

| 種類 | APK | versionCode | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101004.apk | 2026101004 | 07e8e42 | 0285f1f7cad259b8e9af30eaebc955d9ef3c6d6bacdfe0153e6422551927ef46 | 94056049 |

- ビルド前に ALL PASSED（checks-normal-1004/）。証明書 4332fcb9…a047。

## 追加：通常版 0.5.36+2026101005（2026-10-10、機種名の比べ方）

| 種類 | APK | versionCode | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101005.apk | 2026101005 | 815c826 | 3393588e00c6bfb0b8b37264c34c4a854c0a696de7008fbe6b5c3665ae511a6d | 94056049 |

- ビルド前に ALL PASSED（checks-normal-1005/）。証明書 4332fcb9…a047。

## 追加：通常版 0.5.36+2026101101・P’s CUBEクローン 0.5.36+2026101102（2026-10-11）

1279番台の聖闘士星矢（稼働停止）を取り込まない・表示しない、この台の推移（日付を押すとその日・差枚の列）、採点の「暫定」をやめる、ほか10/10〜11の変更。

| 種類 | APK | versionCode | アプリID | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101101.apk | 2026101101 | com.keyan.database_android | 66a0e76 | 4a0588534c3d9af18b9a22f6b08578461d4d44c71bf3539c21a99507dcfaf8d0 | 94056049 |
| P’s CUBEクローン | database-pscube-clone-0.5.36-2026101102.apk | 2026101102 | com.keyan.database_android.pscube | 2ea05ad | a975c8f4c4aeef4f4662ee08540235708fdcafdce0eaf356909cdc238948e6e8 | 94056073 |

- 各ビルド前に check_before_build.sh ALL PASSED（35項目、ログ checks-normal-1101/・checks-clone-1102/）。証明書 4332fcb9…a047（従来と同じ）。取込ボタンは通常版 enabled=true、クローン enabled=false。ML Kitの部品（VisionCommonRegistrar の <init>）は残っている。

```powershell
$adb = 'C:\Users\keyan\AppData\Local\Android\Sdk\platform-tools\adb.exe'
$apkDir = 'C:\Users\keyan\Documents\Codex\2026-09-24\a\work\database-main\database_android\build\releases\0.5.36'
& $adb -s RFGL146LVVW install -r "$apkDir\database-0.5.36-2026101101.apk"
& $adb -s RFGL146LVVW install -r "$apkDir\database-pscube-clone-0.5.36-2026101102.apk"
```

## 追加：通常版 0.5.36+2026101201・クローン 0.5.36+2026101202（2026-10-12、進み具合に対象外の機種を数えない）

| 種類 | APK | versionCode | ソースコミット | SHA-256 | bytes |
| --- | --- | --- | --- | --- | --- |
| 通常版 | database-0.5.36-2026101201.apk | 2026101201 | addb430 | cdae3fecdf7689a40a90f131700b00b31389542ec5325376b6f3173190354653 | 94138037 |
| P’s CUBEクローン | database-pscube-clone-0.5.36-2026101202.apk | 2026101202 | addb430 | 6a34be104d0a5a79ee0e231efe3d2d33b745b029f80a1f5acc6a27f8c065c138 | 94138065 |

- ビルド前に check_before_build.sh ALL PASSED（checks-normal-1201/・checks-clone-1202/、同じ確認。versionCodeを変えただけ）。証明書 4332fcb9…a047（両方）。
