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
    this.exportedAtText,
    this.source,
    this.loadedAt,
    this.skipped = 0,
    this.keptOlder = 0,
  });

  final List<SlotRecord> records;
  final Map<String, DateEvent> dateEvents;
  final String? file;
  final DateTime? exportedAt;

  /// 書き出した時刻の、ファイルに書かれていたままの文字。Driveの自動読み込みで
  /// 「前回と同じファイルか」を見分けるのに使う（時刻に直すと表記が変わるため）。
  final String? exportedAtText;
  final String? source;
  final DateTime? loadedAt;

  /// 形が合わず読み飛ばした台の数。
  final int skipped;

  /// Driveの内容に合わせて残した、前に読み込んだ古い日の台の数（[merge]）。
  final int keptOlder;

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
      exportedAtText: header['exported_at'] is String
          ? header['exported_at'] as String
          : null,
      source: header['source'] as String?,
      loadedAt: DateTime.tryParse(decoded['loaded_at'] as String? ?? '')
          ?.toLocal(),
      skipped: skipped,
      keptOlder: (decoded['kept_older'] as num?)?.toInt() ?? 0,
    );
  }

  DateEvent? dateEventFor(String store, String day) =>
      dateEvents['$store|$day'];

  /// Driveから自動で読んだ内容 [incoming] と、端末に覚えていた内容 [stored] を
  /// 合わせる（どちらも閲覧ページのJSON）。
  ///
  /// * 覚えていた方が新しく書き出されたもの（手で新しいバックアップを読み込んだ
  ///   直後など）なら、置き換えずに覚えていた方を使う。
  /// * そうでなければDriveの方を使い、Driveの内容より前の日の台（手で全期間の
  ///   バックアップを読み込んでいた分）は残して足す。Driveの閲覧用ファイルは
  ///   直近60日分だけなので、そのまま置き換えると古い日が消えてしまうため。
  ///
  /// 返す [text] を表示・保存に使う。[note] は利用者への知らせ（無ければ null）。
  static ({String text, String? note}) merge(String? stored, String incoming) {
    Map<String, dynamic>? decode(String? text) {
      if (text == null) return null;
      try {
        final value = jsonDecode(text);
        return value is Map && value['records'] is List
            ? Map<String, dynamic>.from(value)
            : null;
      } on FormatException {
        return null;
      }
    }

    DateTime? exportedAt(Map<String, dynamic> doc) {
      final header = doc['header'];
      return header is Map
          ? DateTime.tryParse(header['exported_at'] as String? ?? '')
          : null;
    }

    String when(DateTime at) {
      final local = at.toLocal();
      String two(int v) => v.toString().padLeft(2, '0');
      return '${local.month}/${local.day} ${two(local.hour)}:${two(local.minute)}';
    }

    final old = decode(stored);
    final fresh = decode(incoming);
    if (old == null || fresh == null) return (text: incoming, note: null);
    final oldAt = exportedAt(old);
    final freshAt = exportedAt(fresh);
    if (oldAt != null && freshAt != null && oldAt.isAfter(freshAt)) {
      return (
        text: stored!,
        note:
            '前に読み込んだ内容（${when(oldAt)}書き出し）の方が、Googleドライブの内容'
            '（${when(freshAt)}書き出し）より新しいので、置き換えていません。',
      );
    }
    String? dayOf(Object? item) {
      final day = item is Map ? item['day'] : null;
      return day is String && isValidRecordDay(day) ? day : null;
    }

    final freshRecords = fresh['records'] as List;
    final freshDays = [for (final item in freshRecords) ?dayOf(item)];
    if (freshDays.isEmpty) return (text: incoming, note: null);
    final first = freshDays.reduce((a, b) => a.compareTo(b) <= 0 ? a : b);
    final older = [
      for (final item in old['records'] as List)
        if (dayOf(item) case final day? when day.compareTo(first) < 0) item,
    ];
    if (older.isEmpty) return (text: incoming, note: null);
    final events = <String, Object?>{};
    // 最新の対象期間ではイベントの解除も反映する。手元のイベントを
    // 引き継ぐのは、今回残した古い記録の店舗・日付だけ。
    final keptDays = {
      for (final item in older)
        if (item is Map) '${item['store']}|${item['day']}',
    };
    for (final list in [old['date_events'], fresh['date_events']]) {
      if (list is! List) continue;
      for (final item in list) {
        final event = DateEvent.tryFromJson(item);
        if (event != null &&
            (identical(list, fresh['date_events']) ||
                keptDays.contains(event.key))) {
          events[event.key] = item;
        }
      }
    }
    return (
      text: jsonEncode({
        ...fresh,
        'records': [...freshRecords, ...older],
        'date_events': events.values.toList(),
        'kept_older': older.length,
      }),
      note:
          'Googleドライブの最新に、前に読み込んだ${first.substring(5).replaceAll('-', '/')}より前の'
          '${older.length}台を合わせて表示しています。',
    );
  }

  static SlotRecord? _record(Object? item) {
    if (item is! Map) return null;
    final raw = Map<String, dynamic>.from(item);
    final kind = raw['kind_code'];
    final machine = raw['machine'];
    final day = raw['day'];
    if (!storeNames.containsKey(raw['store']) ||
        (kind != null && kind != 21) ||
        !hasValidRecordNumbers(raw) ||
        machine is! String ||
        machine.trim().isEmpty ||
        day is! String ||
        !isValidRecordDay(day)) {
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
