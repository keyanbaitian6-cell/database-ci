import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// 画面の小さな設定（結果画面で最後に見た店舗・日付・機種、表の確認画面を
/// 省くか）。アプリを開き直したとき、前に見ていた所から始められるように。
///
/// 記録そのものではないので、読み書きに失敗しても既定値で続ける。書き込みは
/// 1つずつ順に行い、一時ファイルに書いてから名前を変える（途中で落ちても、
/// 壊れた内容を読むことがない）。
class UiPrefs {
  UiPrefs({Future<File> Function()? file}) : _file = file ?? _defaultFile;

  final Future<File> Function() _file;
  Future<void> _tail = Future<void>.value();

  String? store;
  String? day;
  String? machine;

  /// 「表の確認画面を省く」。既定は省く（表はサイトのHTMLをそのまま読むので、
  /// 読み違いが起きない。PC版も元から確認画面なしで保存する）。
  bool skipTableReview = true;

  static Future<File> _defaultFile() async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}${Platform.pathSeparator}ui_state.json');
  }

  Future<void> load() async {
    try {
      final file = await _file();
      if (!await file.exists()) return;
      final decoded = jsonDecode(await file.readAsString());
      if (decoded is! Map) return;
      store = decoded['store'] as String?;
      day = decoded['day'] as String?;
      machine = decoded['machine'] as String?;
      skipTableReview = decoded['skip_table_review'] != false;
    } on Object {
      // 壊れていれば既定値のまま。
    }
  }

  /// 選んだ店舗・日付・機種を覚える（変わっていなければ何もしない）。
  Future<void> remember(String? store, String? day, String? machine) {
    if (store == this.store && day == this.day && machine == this.machine) {
      return Future<void>.value();
    }
    this.store = store;
    this.day = day;
    this.machine = machine;
    return _save();
  }

  Future<void> setSkipTableReview(bool value) {
    skipTableReview = value;
    return _save();
  }

  Future<void> _save() {
    // 呼ばれた時点の値ではなく、書く直前の最新の値を書く。
    final done = _tail.then((_) => _write());
    _tail = done;
    return done;
  }

  Future<void> _write() async {
    try {
      final file = await _file();
      final temp = File('${file.path}.tmp');
      await temp.writeAsString(
        jsonEncode({
          'store': store,
          'day': day,
          'machine': machine,
          'skip_table_review': skipTableReview,
        }),
        flush: true,
      );
      await temp.rename(file.path);
    } on Object {
      // 設定の保存に失敗しても、記録には影響しない。
    }
  }
}
