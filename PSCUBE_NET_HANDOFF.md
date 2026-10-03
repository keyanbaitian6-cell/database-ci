# P’s CUBE 差枚取り込みの引き継ぎ（2026-10-03）

## Claudeの引き継ぎ結果（2026-10-03）

- レビュー・修正・検証のうえ main へ反映（詳細は `AI_COLLABORATION.md` の同日の項目）。
- 利用者の選択：差枚の元データが取れない（通信失敗・拒否・形式違い）ときも、台別の数値・グラフは保存して進み、
  差枚は空欄（0にしない）で「差枚は未取得」と表示する。巡回を止めない。翌日以降にその台を開けば過去6日分も埋まる。
- Androidの完了待ちは読み取りごとの番号で結果を分け、前の読み取りの遅れた結果を取り違えない。
- 古い記録の差枚：日々の巡回で各台（当たりのある台）の台別ページを開くたびに、サイトにある7日分の差枚が入る
  （数値が同じ既存記録へ付く）。差枚未取得を別に管理する仕組みは追加していない。手動でもその台別ページで再取り込みできる。
- 実WebView2（PC）で `database/tests/smoke_pscube_net_capture.py` が成功（一時DB・全通信をWebView2内で応答）。
  実サイト・Android実機での差枚取得は未確認（利用者の操作が必要）。

## 状態と目的

利用制限で作業が中断したため、Claude向けに途中の変更を保存した。
**実装途中・実機未確認。完成版ではない。**

- 正本: `imakurudev-eng/database` の最新 `main`。
- 作業開始時の main: `86df43c5d0c405aeed6cdb4506fd53b17d74c268`。
- 引き継ぎブランチ: `codex/handoff-pscube-net-pc-android-20261003`。
- 利用者の目的: **PC版とAndroid版でP’s CUBEを取り込む際、差枚も同時に保存する**。
- iPhoneショートカットの追加開発は優先対象ではない。
- 今回の作業では main への反映、APK配布、Web公開は未実施。

最初に `README.md`、ルートの構成、`AGENTS.md`、`database_android/AGENTS.md`、
`AI_COLLABORATION.md`、設定ファイルを実際に読み、最新 main と本ブランチの差分を確認すること。
本書の記述もコードで再確認する。過去の旧デザインブランチをベースにしない。

## 確認した差枚の算出方法

P’s CUBEの `Graph.src.datas.g` に日付・xField・yField、`datas.p` に元数値がある。
連続グラフの各日について、**終点のY − 始点のY** がその日の差枚。
`anjYUnit` が存在する場合は単位倍率を適用する。存在しなければ倍率1。

利用者が提供した1120番台・2026-10-02のJSONでは、始点7092、終点21210なので
差枚は **+14,118枚**。MYの14,209とは意味が異なる。
画像のピクセルや最大持玉から推定せず、元数値を使う。
この例の rack は文字列 `"1120"`。数値と数字文字列の両方を受け付ける修正を含む。

## 保存した途中の変更

1. `database_android/web/pscube/data.mjs`
   - `netMedalsOfProbe` を共通化。日付・系列・数値・順序を検証する。
   - `capturePageWithNet` を追加。台別 `nc-v06-001.php` でのみ、サイト自身の
     `jQuery.ajax` から同一オリジンの `nc-m06-003.php` にアクセスする。
   - パラメータは `cd_dai`、`YMD_biz`、`api.apikey`、`api.token._i`、`api.token._t`。
   - `Graph.src` から日ごとの差枚を計算し、対応する記録へ `net_medals` として付与する。
   - 通信失敗・不正なグラフはエラーとし、選択日の差枚がないまま成功扱いにしない。
   - 認証値・元の応答はバックアップへ保存しない。
2. `database_android/web/pscube/graph_probe.mjs`
   - 共通の算出処理を使用。数字文字列の rack に対応。
3. `database_android/tool/build_pscube_capture.mjs`
   - 通常の取り込みスクリプトを非同期化。自動巡回の検査スクリプトは同期のまま。
   - `assets/pscube_capture.js` と `assets/pscube_auto_probe.js` を再生成済み。
4. `database/pscube_import.py`
   - PCブラウザ内の取り込みがPromiseの完了を待つよう修正。
   - 通信後にもページの同一性を確認する。
5. `database_android/lib/pscube_import_page.dart`
   - WebViewで非同期処理の結果をページ内へ格納し、完了を確認してから保存する。
   - 200ms間隔・最大75回の待機。途中の画面移動・自動取り込み中止に対応。
6. テストと説明の変更
   - `database_android/tool/test_pscube_net_capture.mjs`（新規）
   - `database_android/tool/test_pscube_data.mjs`
   - `database_android/tool/test_pscube_capture.mjs`
   - `database_android/test/pscube_store_test.dart`
   - `database/PSCUBE_AUTO_CAPTURE.md`
   - `database_android/PS_CUBE_WEB_BASE.md`

## 確認済みの範囲

以下は中断前の作業環境で成功した。実サイト・実機での成功とは区別すること。

- `PYTHONPATH=database python -m unittest discover -s database -p 'test_pscube_*.py' -q`: 67件成功。
- `node --test database_android/tool/test_pscube_data.mjs`: 15件成功。
- `test_pscube_net_capture.mjs`: Chromium上の模擬サイト・模擬Graph応答で成功。
  差枚+125/-25、MY維持、認証パラメータ、HTTP403時のエラーを確認。
- `test_pscube_auto_browser.mjs`: 模擬ブラウザで成功。
- `flutter analyze --no-pub lib/pscube_import_page.dart`: 問題なし。
- Flutterのstore/browser/autoテスト計24件成功。その後storeテストを追加し、store17件成功。
  差枚とMYの区別、表を再取り込みした後の差枚保持を確認。
- `git diff --check`: 問題なし。

ブラウザテストの実行例:

```sh
PLAYWRIGHT_MODULE=/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core/index.mjs CHROMIUM_PATH=/usr/bin/chromium node database_android/tool/test_pscube_net_capture.mjs
```

既存 `test_pscube_capture.mjs` のWebアーカイブ検証は必要なフィクスチャが揃わず未実行。
PC実アプリ・Android実機・実サイト認証付き通信の確認も未実施。

## 残りの作業

1. 最新 main を確認し、本ブランチの変更をレビューする。
   ライブ応答の形式、選択日の取得、WebViewの完了待ち、ページ移動、再試行を確認する。
2. **保存済みデータの差枚を埋める導線を確認する。**
   既存の `rack_captures` が取得済みの場合、差枚が欠けていても自動的には再取得対象にならない。
   手動再取り込みで足りるか、差枚未取得の管理が必要か、既存仕様に合わせて検討・修正する。
3. **当たり0回の台は従来どおり台別ページへ行かない。**
   この経路では差枚を取得しないので、全台の差枚・店舗総差枚が揃うとは言えない。
   欠損を0と見なさず、集計するなら取得済み台数・欠損の扱いを確認する。
   利用者の許可なく当たり0回台の巡回方針・採点v12を変更しない。
4. 差枚が一覧・保存・バックアップ・再取り込みで維持されることを必要な範囲で確認する。
   既存UI、MY、採点、古いバックアップの互換性を維持する。
5. Android SDKのある環境でAPKを作成し、実機確認・配布まで進める。
   現環境では `flutter build apk --release --no-pub` が **No Android SDK found** で失敗。
   versionの一時変更は戻してあり、現在 `0.5.21+2026100303`。新しいAPKはまだない。
   APK作成前に最新 main を取り込み、AGENTSの規則に従ってversionCodeを上げる。
   既存アプリと署名が継続するか確認する。アンインストール・データ消去で解決しない。
6. 完成・検証後に正本mainへ反映し、変更点・根拠ファイル・検証結果・残る制限を利用者へ報告する。

## Web版とメルヘンの扱い

- 公開Web版: `keyanbaitian6-cell/database-viewer`。
  今回は更新していない。数字文字列rackの互換性修正を公開する場合、
  `data.mjs` と `graph_probe.mjs` を同時に更新する必要がある。
  公開は必ず `database_android/tool/stage_viewer.py` を通す。
  実データを含む `build/web` をそのまま公開しない。
- メルヘン長町南店・幸町店の差枚は現時点で取得方法を確認できていない。
  利用者は今回のメルヘン対応を見送ることを了承している。
  幸町779番台・2026-10-02の診断で、API応答の復号後も `sadama:null`、`my:1982`。
  `my` を差枚へ流用できない。長町南店の同じ復号診断の成功までは確認していない。
  スクリーンショットのグラフは枚数軸がなく、画像から正確な差枚は出せない。
  追加の空欄スクリーンショットを繰り返し依頼しない。

## 個人データ

バックアップJSON、Webアーカイブ、認証キー、SQLite、APKをGitへ登録しない。
利用者提供資料は前の作業環境内にあり、GitHubだけでは読めない。
必要になったときだけ具体的な資料を依頼する。本ブランチにはコード・模擬テスト・本書のみを保存した。
