import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'models.dart';
import 'scoring.dart';

class CsvExportService {
  Future<File> create(List<SlotRecord> records) async {
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
      [
        '店舗',
        '日付',
        '機種名',
        '台番号',
        '総回転数',
        'BIG',
        'REG',
        '最大持玉',
        '設定情報（手入力）',
        '持玉点',
        '当たり点',
        '終点点',
        '維持点',
        '合計点',
        '状態',
        '比較件数',
        '比較日数',
        '持玉比較件数',
        '評価可能配点',
        '欠測幅下限',
        '欠測幅上限',
        '採点版',
        '注意',
      ],
    ];
    for (final record in rows) {
      final score = scoreRecord(record, records);
      final status = score.total == null
          ? '保留'
          : score.provisional
          ? '暫定'
          : '参考';
      lines.add([
        storeNames[record.store] ?? record.store,
        record.day,
        record.machine,
        '${record.rack}',
        '${record.games}',
        '${record.bb}',
        '${record.rb}',
        '${record.maxHold ?? ''}',
        record.confirmedSetting ?? '',
        _point(score.maxHold),
        _point(score.hits),
        _point(score.positive),
        _point(score.retention),
        _point(score.total),
        status,
        '${score.referenceCount}',
        '${score.referenceDays}',
        '${score.holdReferenceCount}',
        '${score.coverage}',
        _point(score.missingLow),
        _point(score.missingHigh),
        scoringVersion,
        score.reasons.join('・'),
      ]);
    }
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

  String _point(double? value) => value?.toStringAsFixed(1) ?? '';

  String _escape(String value) => '"${value.replaceAll('"', '""')}"';
}
