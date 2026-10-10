import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'models.dart';
import 'scoring.dart';

class CsvExportService {
  static List<List<String>> buildLines(List<SlotRecord> records) {
    final rows = List<SlotRecord>.of(records)
      ..sort((a, b) {
        final day = b.day.compareTo(a.day);
        if (day != 0) return day;
        final store = a.store.compareTo(b.store);
        if (store != 0) return store;
        final machine = a.machine.compareTo(b.machine);
        return machine != 0 ? machine : a.rack.compareTo(b.rack);
      });
    final lines = <List<String>>[
      ['日付', '機種名', '台番号', '採点結果', 'G数', '最大持ち球', 'B', 'R', '設定情報'],
    ];
    for (final record in rows) {
      final score = scoreRecord(record, records);
      lines.add([
        record.day,
        record.machine,
        '${record.rack}',
        _scoreResult(score.total),
        '${record.games}',
        '${record.maxHold ?? ''}',
        '${record.bb}',
        '${record.rb}',
        record.confirmedSetting ?? '',
      ]);
    }
    return lines;
  }

  Future<File> create(List<SlotRecord> records) async {
    final lines = buildLines(records);
    final directory = await getTemporaryDirectory();
    final stamp = DateTime.now()
        .toIso8601String()
        .replaceAll(':', '')
        .replaceAll('.', '');
    final file = File(
      '${directory.path}${Platform.pathSeparator}database-$stamp.csv',
    );
    // UTF-8 BOM enables Japanese column names in Excel as well as Google Sheets.
    await file.writeAsString(
      '\uFEFF${lines.map((line) => line.map(_escape).join(',')).join('\r\n')}\r\n',
      flush: true,
    );
    return file;
  }

  static String _point(double? value) => value?.toStringAsFixed(1) ?? '';

  static String _scoreResult(double? total) {
    if (total == null) return '保留';
    return '${_point(total)}点';
  }

  String _escape(String value) => '"${value.replaceAll('"', '""')}"';
}
