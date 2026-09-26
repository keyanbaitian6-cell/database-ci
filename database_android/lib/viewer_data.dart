import 'dart:convert';

import 'date_events.dart';
import 'models.dart';

/// 閲覧ページで読んだバックアップ（画像を除いた軽い形）。
///
/// ページ内のJavaScript（web/index.html）が1行ずつ読んで作ったJSONを受け取り、
/// Android版と同じ規則（機種名の表記ゆれをそろえ、同じ台は1件にまとめる）で
/// 台の一覧にする。採点・翌日候補は、Android版と同じ関数でその場で計算する。
class ViewerData {
  const ViewerData({
    required this.records,
    this.dateEvents = const {},
    this.file,
    this.exportedAt,
    this.source,
    this.loadedAt,
    this.skipped = 0,
  });

  final List<SlotRecord> records;
  final Map<String, DateEvent> dateEvents;
  final String? file;
  final DateTime? exportedAt;
  final String? source;
  final DateTime? loadedAt;

  /// 形が合わず読み飛ばした台の数。
  final int skipped;

  static ViewerData parse(String text) {
    final decoded = jsonDecode(text);
    if (decoded is! Map || decoded['records'] is! List) {
      throw const FormatException('databaseのバックアップファイルではありません。');
    }
    final header = decoded['header'] is Map ? decoded['header'] as Map : {};
    final merged = <String, SlotRecord>{};
    final dateEvents = <String, DateEvent>{};
    final rawEvents = decoded['date_events'];
    if (rawEvents is List) {
      for (final item in rawEvents) {
        final event = DateEvent.tryFromJson(item);
        if (event != null) dateEvents[event.key] = event;
      }
    }
    var skipped = 0;
    for (final item in decoded['records'] as List) {
      final record = _record(item);
      if (record == null) {
        skipped++;
        continue;
      }
      final current = merged[record.key];
      merged[record.key] = current == null
          ? record
          : mergeSameRack(current, record);
    }
    final records = merged.values.toList()
      ..sort((a, b) {
        final day = b.day.compareTo(a.day);
        if (day != 0) return day;
        final store = a.store.compareTo(b.store);
        if (store != 0) return store;
        final machine = a.machine.compareTo(b.machine);
        return machine != 0 ? machine : a.rack.compareTo(b.rack);
      });
    return ViewerData(
      records: records,
      dateEvents: dateEvents,
      file: decoded['file'] as String?,
      exportedAt: DateTime.tryParse(header['exported_at'] as String? ?? '')
          ?.toLocal(),
      source: header['source'] as String?,
      loadedAt: DateTime.tryParse(decoded['loaded_at'] as String? ?? '')
          ?.toLocal(),
      skipped: skipped,
    );
  }

  DateEvent? dateEventFor(String store, String day) =>
      dateEvents['$store|$day'];

  static SlotRecord? _record(Object? item) {
    if (item is! Map) return null;
    final raw = Map<String, dynamic>.from(item);
    final kind = raw['kind_code'];
    final machine = raw['machine'];
    if (!storeNames.containsKey(raw['store']) ||
        (kind != null && kind != 21) ||
        raw['rack'] is! num ||
        machine is! String ||
        machine.trim().isEmpty ||
        !isValidRecordDay(raw['day'] as String?)) {
      return null;
    }
    try {
      final record = SlotRecord.fromJson(raw);
      return record.copyWith(machine: normalizeMachineName(record.machine));
    } on Object {
      return null;
    }
  }
}
