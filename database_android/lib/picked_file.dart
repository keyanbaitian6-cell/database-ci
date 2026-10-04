/// バックアップの読み込みでファイルを選ぶと、file_picker は選んだファイルをアプリの一時置き場
/// （`cache/file_picker/<時刻>/<名前>`）へ丸ごと写す。写しは消す命令を呼ばない限り残り、読み込むたびに
/// 溜まっていた（2026-10-05、通常版のキャッシュが604.7MB）。読み終えたら写しを消す。
library;

import 'dart:io';

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
