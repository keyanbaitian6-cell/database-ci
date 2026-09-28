import 'dart:convert';
import 'dart:io';

/// 画像付きの取り消し・競合データはメモリに貯めず、一時ファイルに置く。
/// SQLiteの保存が失敗した場合はこの新しい控えだけを捨て、前の控えを保つ。
class ImportSpool {
  ImportSpool._(this.file, this._writer);
  final File file;
  final RandomAccessFile _writer;
  final _positions = <String, (int, int)>{};
  var _offset = 0;
  var count = 0;
  var _finished = false;

  static Future<ImportSpool> create(String databasePath) async {
    final dir = await Directory(
      '${File(databasePath).parent.path}/import-cache',
    ).create(recursive: true);
    final folder = await dir.createTemp('batch-');
    final file = File('${folder.path}/records.jsonl');
    return ImportSpool._(file, await file.open(mode: FileMode.write));
  }

  Future<void> add(Map<String, dynamic> value, {String? key}) async {
    final bytes = utf8.encode('${jsonEncode(value)}\n');
    await _writer.writeFrom(bytes);
    if (key != null) _positions[key] = (_offset, bytes.length);
    _offset += bytes.length;
    count++;
  }

  Future<void> finish() async {
    if (_finished) return;
    _finished = true;
    try {
      await _writer.flush();
    } finally {
      await _writer.close();
    }
  }

  Stream<List<Map<String, dynamic>>> chunks({int size = 100}) async* {
    await finish();
    var rows = <Map<String, dynamic>>[];
    await for (final line
        in file
            .openRead()
            .transform(utf8.decoder)
            .transform(const LineSplitter())) {
      rows.add(Map<String, dynamic>.from(jsonDecode(line) as Map));
      if (rows.length == size) {
        yield rows;
        rows = [];
      }
    }
    if (rows.isNotEmpty) yield rows;
  }

  Future<Map<String, dynamic>> read(String key) async {
    await finish();
    final (offset, length) = _positions[key]!;
    final reader = await file.open();
    try {
      await reader.setPosition(offset);
      return Map<String, dynamic>.from(
        jsonDecode(utf8.decode(await reader.read(length))) as Map,
      );
    } finally {
      await reader.close();
    }
  }

  Future<void> delete() async {
    await finish();
    if (await file.exists()) await file.delete();
    if (await file.parent.exists()) await file.parent.delete();
  }

  /// 片付け失敗で、成功したDB保存を失敗と表示したり元の例外を隠したりしない。
  /// 残った一時ファイルは次の起動時にも片付ける。
  Future<void> discard() async {
    try {
      await delete();
    } on FileSystemException {
      // DBの記録ではなく、再起動で不要になる取り消し・競合の一時控えだけ。
    }
  }

  static Future<void> cleanOld(String databasePath) async {
    final dir = Directory('${File(databasePath).parent.path}/import-cache');
    if (!await dir.exists()) return;
    final cutoff = DateTime.now().subtract(const Duration(days: 3));
    await for (final entry in dir.list(followLinks: false)) {
      if (entry is! Directory ||
          !entry.uri.pathSegments
              .where((s) => s.isNotEmpty)
              .last
              .startsWith('batch-')) {
        continue;
      }
      final file = File('${entry.path}/records.jsonl');
      try {
        if (await file.exists() &&
            (await file.stat()).modified.isBefore(cutoff)) {
          await file.delete();
          await entry.delete(); // 他のファイルがあれば削除しない。
        }
      } on FileSystemException {
        // 一時ファイルの片付けで起動を止めない。
      }
    }
  }
}
