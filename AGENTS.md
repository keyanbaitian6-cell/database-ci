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

## 「同じページか」の判定（再発防止、2026-10-06 利用者指示「同じような過ち繰り返してるから今後間違えないようにして」）

URLを文字列のまま `==` / `!=` で比べたせいで、「ページが切り替わりました」「表示中のURLと読み取り結果が一致しません」と誤って止まる不具合が繰り返し起きた。例：メルヘンPCの日本語機種名（`b6081df`、%エンコードの違い）、P’s CUBE Androidの一覧ページで#以降のスクロール位置が変わっただけで保存できない（2026-10-06）。

- **表示中のページと取り込み開始時・読み取り結果のページを比べるときは、URLを直接比べない。** サイトごとの判定関数を1つだけ用意し、開始前・読み取り中・保存直前・保存処理（Store）のすべての確認でそれを使う。確認ごとに違う比べ方をしない。
  - P’s CUBE：Android `pscubeSamePage`（`database_android/lib/pscube_store.dart`）、PC `same_page`（`database/pscube_import.py`、保存処理）と `identity`（同ファイルの取り込みカード、location.href同士）。一覧ページは#以降（サイトが書くスクロール位置）を無視し、台別ページ `nc-v06-001.php` の#以降（履歴の日付）は完全一致。%を戻して比べる（WebView2は日本語の機種名を元の文字で返す）。
  - メルヘン：%を戻してから比べる。#以降（取り込む日付）は比べる。Android `meruhenSamePageUrl`（`database_android/lib/capture_flow.dart`）、PC `same_page_url`（`database/browser_import.py`、`b6081df`）。
- 判定を変えるときは **PC・Androidの両方** を同じ規則にそろえ、片方だけ直さない。
- 「サイトがURLを書き換える（#・%エンコードなど）が、同じページ」の例と、「本当に別のページ・別の日」の例の両方をテストに入れる。
