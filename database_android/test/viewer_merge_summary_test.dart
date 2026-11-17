// Googleドライブの更新で、端末の本文（記録の中身）を読み込まず、要約から合わせる方法
// （ViewerData.prepareMergeFromSummary、2026-11-18：更新1回のメモリの山を下げる）が、本文を読んで合わせる今までの方法
// （ViewerData.prepareMerge）と、同じ保存内容・同じ表示内容になることを確かめる。要約が使えない場合は null になる。
import 'dart:convert';

import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, Object?> row(String day, int rack, {int games = 3000}) => {
  'store': 'saiwaichou',
  'day': day,
  'machine': '試験+機種',
  'rack': rack,
  'games': games,
  'bb': 10,
  'rb': 5,
  'graph_measurement': {
    'baseline_y': 100,
    'peak_y': 80,
    'trough_y': 100,
    'end_y': 80,
    'curve_index': rack,
  },
};

Map<String, Object?> header(String exportedAt) => {
  'format': 'database-backup',
  'version': 1,
  'source': 'pc-viewer',
  'exported_at': exportedAt,
};

/// 端末に保存した本文。JavaScript（web/index.html の loadSummary）が返す要約と同じ形に直す補助つき。
Map<String, Object?> stored({
  required String exportedAt,
  required List<String> days,
  List<Map<String, Object?>> events = const [],
  List<Map<String, Object?>> marks = const [],
  Map<String, Object?> extra = const {},
}) => {
  'header': header(exportedAt),
  'records': [
    for (final day in days) ...[row(day, 1), row(day, 2)],
  ],
  'candidates': const [],
  'date_events': events,
  if (marks.isNotEmpty) 'rainbow_marks': marks,
  'history_days': days,
  'file': 'Googleドライブ（自動）',
  'loaded_at': exportedAt,
  ...extra,
};

String summaryOf(Map<String, Object?> doc) {
  final records = doc['records']! as List;
  final days = {
    for (final r in records)
      if (r is Map && r['day'] is String) r['day'],
  };
  // 記録の中身だけを null に置き換えた外枠（キーの順は元のまま）。
  final shell = {...doc, 'records': List<Object?>.filled(records.length, null)};
  return jsonEncode({'envelope': jsonEncode(shell), 'days': days.toList()});
}

/// Driveから読んだ内容。web/index.html の shape（見出しを header にまとめた形）と同じ。
Map<String, Object?> fresh({
  required String exportedAt,
  required List<String> days,
  List<Map<String, Object?>> events = const [],
  bool completeDays = true,
}) => {
  'header': {
    ...header(exportedAt),
    'date_events': events,
    'machines': const [],
    'history': true,
    if (completeDays) 'history_days': days,
  },
  'records': [
    for (final day in days) ...[row(day, 1, games: 4000), row(day, 3)],
  ],
  'candidates': const [],
  'date_events': events,
  if (completeDays) 'history_days': days,
  'file': 'Googleドライブ（自動）',
  'loaded_at': exportedAt,
};

void expectSame(
  Map<String, Object?> old,
  Map<String, Object?> incoming, {
  bool light = true,
}) {
  final oldText = jsonEncode(old), incomingText = jsonEncode(incoming);
  final full = ViewerData.prepareMerge(oldText, incomingText);
  final fast = ViewerData.prepareMergeFromSummary(summaryOf(old), incomingText);
  if (!light) {
    expect(fast, isNull, reason: '要約では足りないので、本文を読む今までの方法に任せる');
    return;
  }
  expect(fast, isNotNull);
  expect(fast!.text, full.text, reason: '保存する本文が同じ');
  expect(fast.note, full.note);
  final a = fast.data, b = full.data;
  expect(
    a.records.map((r) => (r.store, r.day, r.rack, r.games)).toList(),
    b.records.map((r) => (r.store, r.day, r.rack, r.games)).toList(),
  );
  expect(a.exportedAtText, b.exportedAtText);
  expect(a.keptOlder, b.keptOlder);
  expect(
    a.dateEvents.map((k, v) => MapEntry(k, v.toJson())),
    b.dateEvents.map((k, v) => MapEntry(k, v.toJson())),
  );
  expect(
    a.rainbowMarks.map((k, v) => MapEntry(k, v.toJson())),
    b.rainbowMarks.map((k, v) => MapEntry(k, v.toJson())),
  );
}

void main() {
  const days = ['2026-11-05', '2026-11-06', '2026-11-07'];
  final oldEvent = {
    'store': 'saiwaichou',
    'day': '2026-11-06',
    'name': '端末のイベント',
    'updated_at': '2026-11-09T12:00:00+09:00',
  };
  final oldMark = {
    'store': 'saiwaichou',
    'day': '2026-11-06',
    'rack': 1,
    'on': true,
    'updated_at': '2026-11-09T12:00:00+09:00',
  };

  test('旧本文の日がすべてDriveの履歴にある：本文を読む方法と同じ結果（イベント・🌈の印も引き継ぐ）', () {
    expectSame(
      stored(
        exportedAt: '2026-11-10T00:00:00+09:00',
        days: days,
        events: [oldEvent],
        marks: [oldMark],
        extra: {'kept_older': 0},
      ),
      fresh(
        exportedAt: '2026-11-11T00:00:00+09:00',
        days: ['2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08'],
      ),
    );
  });

  test('Driveにも同じ日のイベントがあるとき（新しい入力時刻が残る）', () {
    expectSame(
      stored(
        exportedAt: '2026-11-10T00:00:00+09:00',
        days: days,
        events: [oldEvent],
      ),
      fresh(
        exportedAt: '2026-11-11T00:00:00+09:00',
        days: days,
        events: [
          {...oldEvent, 'name': 'Driveのイベント', 'updated_at': '2026-11-10T08:00:00+09:00'},
        ],
      ),
    );
  });

  test('Driveの履歴に history_days が無くても、旧本文の日がDriveの最初の日以降なら同じ結果', () {
    expectSame(
      stored(exportedAt: '2026-11-10T00:00:00+09:00', days: days),
      fresh(
        exportedAt: '2026-11-11T00:00:00+09:00',
        days: days,
        completeDays: false,
      ),
    );
  });

  test('旧本文にDriveより古い日がある：要約では足りない（null。本文を読む方法に任せる）', () {
    expectSame(
      stored(
        exportedAt: '2026-11-10T00:00:00+09:00',
        days: ['2026-11-01', ...days],
      ),
      fresh(exportedAt: '2026-11-11T00:00:00+09:00', days: days),
      light: false,
    );
    // history_days が無いときも、Driveの最初の日より前の日があれば同じ。
    expectSame(
      stored(
        exportedAt: '2026-11-10T00:00:00+09:00',
        days: ['2026-11-01', ...days],
      ),
      fresh(
        exportedAt: '2026-11-11T00:00:00+09:00',
        days: days,
        completeDays: false,
      ),
      light: false,
    );
  });

  test('旧本文の方が新しい：要約では足りない（null）', () {
    expectSame(
      stored(exportedAt: '2026-11-12T00:00:00+09:00', days: days),
      fresh(exportedAt: '2026-11-11T00:00:00+09:00', days: days),
      light: false,
    );
  });

  test('P’s CUBE・Driveに記録が無い・形が不正：null（今までの方法に任せる）', () {
    final old = stored(exportedAt: '2026-11-10T00:00:00+09:00', days: days);
    final summary = summaryOf(old);
    expect(
      ViewerData.prepareMergeFromSummary(
        summary,
        jsonEncode({'format': 'pscube-viewer', 'records': const []}),
      ),
      isNull,
    );
    expect(
      ViewerData.prepareMergeFromSummary(
        summary,
        jsonEncode({...header('2026-11-11T00:00:00+09:00'), 'records': const []}),
      ),
      isNull,
    );
    expect(ViewerData.prepareMergeFromSummary('{壊れた', '{}'), isNull);
    expect(ViewerData.prepareMergeFromSummary('{"envelope":1,"days":[]}', '{}'), isNull);
    expect(
      ViewerData.prepareMergeFromSummary(summary, '{"records":['),
      isNull,
    );
  });
}
