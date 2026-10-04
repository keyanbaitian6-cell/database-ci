/// バックアップの読み込みでファイルを選ぶと、file_picker は選んだファイルをアプリの一時置き場
/// （`cache/file_picker/<時刻>/<名前>`）へ丸ごと写す。写しは消す命令を呼ばない限り残り、読み込むたびに
/// 溜まっていた（2026-10-05、通常版のキャッシュが604.7MB）。読み終えたら写しを消す。
library;

import 'dart:io';

/// アプリが共有のために一時置き場（キャッシュの直下）へ書いたファイル（バックアップ・CSV・グラフ画像）。
/// 共有先のアプリが後から読むことがあるので、作ってから3日たってから消す。
bool isSharedTemporaryFile(String name) =>
    name.startsWith('database-backup-') ||
    name.startsWith('database-web-graph-') ||
    (name.startsWith('database-') && name.endsWith('.csv'));

/// 以前の版がキャッシュの直下に書いたまま、名前が今と違うため片付けられずに残っていたファイル
/// （2026-10-05、保存領域の内訳で見つかった：`backup_2026-09-23T005639345106.json` が1つ最大15MB・
/// 10個以上、`database-import-1789512998536.jpg`）。今の版はこの名前で作らないので、日数に関係なく消す。
bool isOldVersionLeftover(String name) =>
    RegExp(r'^backup_\d{4}-\d{2}-\d{2}T\d+\.json$').hasMatch(name) ||
    RegExp(r'^database-import-\d+\.(jpe?g|png)$').hasMatch(name);

/// [path] が file_picker の写し（`.../file_picker/<時刻>/<名前>`）なら、そのファイルと空になった
/// 時刻のフォルダを消す。写しでない（元のファイルそのもの）なら何もしない。失敗しても読み込みには関係ない。
Future<void> discardPickedCopy(String? path) async {
  if (path == null) return;
  try {
    final file = File(path);
    final folder = file.parent;
    final owner = folder.parent.path.replaceAll('\\', '/');
    if (!owner.endsWith('/file_picker')) return;
    if (await file.exists()) await file.delete();
    if (await folder.exists() && await folder.list().isEmpty) {
      await folder.delete();
    }
  } on FileSystemException {
    // 一時置き場は、起動時のまとめての片付けや、端末の空きが減ったときのOSの片付けでも消える。
  }
}
