# database_android の作業ルール

### 正本とデザインのルール（2026-09-25、利用者の指示）

- **正本は GitHub `imakurudev-eng/database` の `main` だけ**。2026-09-25に新デザイン（旧ブランチ `codex/adopt-claude-ui`）と採点v10をマージした `5e6009c` 以降がそれ。
- **Androidのデザインは新デザインの1つだけ**。9/23以前の旧デザインのコード・ブランチ・APKは使わない、復元しない、そこからビルドしない。デザインを2系統持たない。
- 作業を始める前に必ず `git fetch origin` と `git pull origin main` をして、最新の `main` から始める。別のフォルダやクローン（例：`Documents/Codex/2026-09-24/a/work/database-claude-review`）の古い状態から作業しない。
- APKは、最新の `main` を取り込んだ状態からだけビルドする。ビルドの前に `git status` と `git log origin/main..HEAD` / `git log HEAD..origin/main` で差分がないか確かめる。
- 作業が終わったらコミットして `main` へpushし、次のAIが同じ状態から始められるようにする。採点は `2026-09-25-v10`（当日500G以下は採点しない）が現行。

詳細はリポジトリ直下の `AI_COLLABORATION.md` を参照。
