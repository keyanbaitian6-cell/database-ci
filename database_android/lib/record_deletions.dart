import 'models.dart';

/// Explicit record operations, independent of retention windows. Old backups
/// without this optional field remain valid and cannot revive a deleted row.
class RecordDeletion {
  const RecordDeletion(
    this.store,
    this.day,
    this.machine,
    this.rack,
    this.deletedAt,
  );
  final String store, day, machine;
  final int rack;
  final DateTime deletedAt;
  String get key => '$store|$day|${normalizeMachineName(machine)}|$rack';
  Map<String, dynamic> toJson() => {
    'store': store,
    'day': day,
    'machine': machine,
    'rack': rack,
    'deleted_at': deletedAt.toUtc().toIso8601String(),
  };
}

DateTime? recordOperationTime(Object? value) {
  if (value is! String) return null;
  // Source timestamps without an offset have always represented Japan time.
  return DateTime.tryParse(
    RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(value) ? value : '$value+09:00',
  );
}

List<RecordDeletion> readRecordDeletions(Object? raw) {
  if (raw == null) return [];
  if (raw is! List) throw const FormatException('削除記録の形式が不正です。');
  return [for (final m in raw) _read(m)];
}

RecordDeletion _read(dynamic m) {
  if (m is! Map ||
      !storeNames.containsKey(m['store']) ||
      m['machine'] is! String ||
      (m['machine'] as String).trim().isEmpty ||
      m['rack'] is! int ||
      m['rack'] < 1 ||
      m['day'] is! String ||
      !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(m['day']) ||
      m['deleted_at'] is! String ||
      !RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(m['deleted_at'])) {
    throw const FormatException('削除記録が不正です。');
  }
  final day = DateTime.tryParse('${m['day']}T00:00:00Z');
  final at = recordOperationTime(m['deleted_at']);
  if (day == null ||
      day.toIso8601String().substring(0, 10) != m['day'] ||
      at == null) {
    throw const FormatException('削除記録の日付が不正です。');
  }
  return RecordDeletion(
    m['store'],
    m['day'],
    normalizeMachineName(m['machine']),
    m['rack'],
    at,
  );
}

Map<String, RecordDeletion> mergeRecordDeletions(
  Iterable<RecordDeletion> marks,
) {
  final result = <String, RecordDeletion>{};
  for (final mark in marks) {
    if (!result.containsKey(mark.key) ||
        mark.deletedAt.isAfter(result[mark.key]!.deletedAt)) {
      result[mark.key] = mark;
    }
  }
  return result;
}

bool recordSurvivesDeletion(dynamic row, Map<String, RecordDeletion> marks) {
  if (row is! Map || row['machine'] is! String) {
    return true; // Normal import validation reports malformed rows.
  }
  final key =
      '${row['store']}|${row['day']}|${normalizeMachineName(row['machine'])}|${row['rack']}';
  final mark = marks[key];
  if (mark == null) return true;
  return [row['record_updated_at'], row['captured_at']].any(
    (value) => recordOperationTime(value)?.isAfter(mark.deletedAt) ?? false,
  );
}

RecordDeletion deletionForRecord(SlotRecord row) {
  var at = DateTime.now().toUtc();
  for (final value in [row.extra['record_updated_at'], row.capturedAt]) {
    final previous = recordOperationTime(value);
    if (previous != null && !at.isAfter(previous)) {
      at = previous.add(const Duration(milliseconds: 1));
    }
  }
  return RecordDeletion(row.store, row.day, row.machine, row.rack, at);
}

SlotRecord restoreDeletedRecord(SlotRecord row, RecordDeletion mark) {
  var at = DateTime.now().toUtc();
  if (!at.isAfter(mark.deletedAt)) {
    at = mark.deletedAt.add(const Duration(milliseconds: 1));
  }
  return row.copyWith(
    extra: {...row.extra, 'record_updated_at': at.toIso8601String()},
  );
}
