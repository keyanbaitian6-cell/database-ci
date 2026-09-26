# database_android の作業ルール

### 正本とデザインのルール（2026-09-25、利用者の指示）

- **正本は GitHub `imakurudev-eng/database` の `main` だけ**。2026-09-25に新デザイン（旧ブランチ `codex/adopt-claude-ui`）と採点v10をマージした `5e6009c` 以降がそれ。
- **Androidのデザインは新デザインの1つだけ**。9/23以前の旧デザインのコード・ブランチ・APKは使わない、復元しない、そこからビルドしない。デザインを2系統持たない。
- 作業を始める前に必ず `git fetch origin` と `git pull origin main` をして、最新の `main` から始める。別のフォルダやクローン（例：`Documents/Codex/2026-09-24/a/work/database-claude-review`）の古い状態から作業しない。
- APKは、最新の `main` を取り込んだ状態からだけビルドする。ビルドの前に `git status` と `git log origin/main..HEAD` / `git log HEAD..origin/main` で差分がないか確かめる。
- **APKをビルドするたびに `database_android/pubspec.yaml` の `version:` の `+` の後ろ（versionCode）を上げる**。形式は `年月日+2桁`（例 `2026092601`、同じ日の2回目は `2026092602`）。下げない。古いAPKを上書きで入れられないようにするため（入れようとするとAndroidが拒否する）。万一古い版がDBを開いても、DB版が新しければ起動画面で止まる。
- **`adb uninstall`・`pm clear`・アプリのデータ消去は、利用者がバックアップを書き出して中身を確かめるまで絶対にしない**。アンインストールすると端末内の記録・ゴミ箱・翌日候補の記録がすべて消える。`INSTALL_FAILED_VERSION_DOWNGRADE` が出たら、アンインストールではなく versionCode を上げてビルドし直す。
- **閲覧ページ（database-viewer）を公開・更新するときは、必ず `tool/stage_viewer.py` を通す**。`build/web` には実際の記録（`assets/database_seed.json`）が同梱されるため、そのまま公開しない。
- 作業が終わったらコミットして `main` へpushし、次のAIが同じ状態から始められるようにする。採点は `2026-09-27-v11`（当日500G以下と、サイトの数値が異常な台は採点しない）が現行。

詳細はリポジトリ直下の `AI_COLLABORATION.md` を参照。
