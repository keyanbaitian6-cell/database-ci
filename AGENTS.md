# ChatGPT project context

This directory is a local mirror of the ChatGPT project “LINE”.

- Treat every file under `sources/` as read-only reference material.
- Do not edit, rename, move, or delete synced project files.
- These files may be replaced the next time a task is created from this ChatGPT project.


## Project instructions

## 新規開発・他サイト対応の共通ルール（利用者指定）

- **このプロジェクトで新しいデータサイト対応、ブラウザ版、関連アプリを作るときは、既存databaseをベースにする。** 利用者の期待は「読み込むデータだけが変わるくらい」であり、デザイン・画面構成・操作・基本仕様を継承する。
- 基準は正本 `imakurudev-eng/database` の最新 `main`。ブラウザ版は既存の `database_android/lib/viewer_main.dart`・`viewer_pages.dart` と、共通の表・グラフ・日付切替・機種一覧・翌日候補の部品を使う。今回修正したP’s CUBE版も同じ共通画面を使っており、利用者のiPhoneで起動確認済み。
- 実装前に既存の画面、操作の流れ、データモデル、DB・保存形式、バックアップ、採点の仕様を確認する。新しい対応は既存の仕組みへ追加し、共通の画面・処理を再利用する。
- サイトごとに追加・変更するのは、取得・解析・入力形式の変換と、データの意味に応じた必要な差分を基本とする。例：P’s CUBEのMY値、BIG/REG信号、ノーマル／それ以外の区分。元の値の意味と保存済みデータの互換性を維持する。
- 独立したオリジナルUIを新設したり、AIの判断でデザイン・基本操作・基本仕様を変更したりしない。変更する場合は利用者が明示的に依頼した範囲に限る。
- 変更後は、対応する既存画面と見た目・操作を比較し、保存済みデータの読み込みと表・グラフ・日付切替が引き続き使えることを確認する。
- 新しいプロジェクトやリポジトリへ分ける場合も、このルールと正本の参照先をその `AGENTS.md` へ引き継ぐ。
