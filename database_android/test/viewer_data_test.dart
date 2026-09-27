import 'dart:convert';

import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> raw(
  int rack, {
  String machine = 'テスト',
  int games = 3000,
}) => const SlotRecord(
  store: 'saiwaichou',
  day: '2026-09-25',
  machine: 'テスト',
  rack: 1,
  games: 3000,
  bb: 10,
  rb: 5,
).copyWith(rack: rack, machine: machine, games: games).toJson();

void main() {
  test('閲覧ページはAndroid版と同じ規則で台をそろえ、壊れた台は飛ばす', () {
    final text = jsonEncode({
      'header': {
        'format': 'database-backup',
        'exported_at': '2026-09-26T00:33:01.668934',
        'source': 'android',
      },
      'records': [
        raw(1),
        raw(1, machine: 'テ+スト', games: 3100), // 表記ゆれの同じ台
        raw(1, machine: 'テ スト'),
        raw(2),
        {'store': 'other', 'day': '2026-09-25', 'machine': 'x', 'rack': 3},
        {'store': 'saiwaichou', 'day': '2026-02-30', 'machine': 'x', 'rack': 4},
        'broken',
      ],
      'candidates': [],
      'file': 'database-backup-android-20260926-003301.json',
      'loaded_at': '2026-09-27T07:00:00.000Z',
    });
    final data = ViewerData.parse(text);
    expect(data.records.map((r) => (r.machine, r.rack, r.games)).toSet(), {
      ('テスト', 1, 3000),
      ('テ スト', 1, 3100),
      ('テスト', 2, 3000),
    });
    expect(data.skipped, 3);
    expect(data.source, 'android');
    expect(data.exportedAt!.day, 26);
    // 採点はAndroid版と同じ関数で、その場で計算できる。
    expect(scoreRecord(data.records.first, data.records).total, isNotNull);
  });

  test('形の違うJSONは読まない', () {
    expect(() => ViewerData.parse('{"x": 1}'), throwsFormatException);
  });

  test('比較に使える前の日の数を数える（少なければ注意を出す）', () {
    SlotRecord on(String day, String store) =>
        SlotRecord.fromJson({...raw(1), 'day': day, 'store': store});
    final all = [
      on('2026-09-26', 'saiwaichou'),
      on('2026-09-25', 'saiwaichou'),
      on('2026-09-24', 'saiwaichou'),
      on('2026-08-01', 'saiwaichou'), // 30日より前
      on('2026-09-25', 'nagamachiminami'), // 別の店舗
    ];
    expect(historyDays(all, 'saiwaichou', '2026-09-26'), 2);
    expect(historyDays(all, 'saiwaichou', '2026-09-24'), 0);
  });

  group('Driveの自動読み込みと、前に読み込んだ内容を合わせる', () {
    String doc(String exportedAt, List<String> days, {String source = 'pc'}) =>
        jsonEncode({
          'header': {
            'format': 'database-backup',
            'exported_at': exportedAt,
            'source': source,
          },
          'records': [
            for (var i = 0; i < days.length; i++)
              {...raw(i + 1), 'day': days[i]},
          ],
          'date_events': [
            {'store': 'saiwaichou', 'day': days.first, 'name': '$source'},
          ],
          'file': source,
        });

    test('前に読み込んだ全期間より新しいDriveの内容なら、Driveに無い古い日を残して足す', () {
      final stored = doc('2026-09-20T10:00:00', [
        '2026-06-01',
        '2026-07-01',
        '2026-08-01',
      ]);
      final incoming = doc('2026-09-27T12:00:00+09:00', [
        '2026-07-30',
        '2026-09-27',
      ], source: 'pc-viewer');
      final merged = ViewerData.merge(stored, incoming);
      final data = ViewerData.parse(merged.text);
      expect(data.records.map((r) => r.day).toSet(), {
        '2026-06-01',
        '2026-07-01',
        '2026-07-30',
        '2026-09-27',
      });
      expect(data.keptOlder, 2);
      expect(data.source, 'pc-viewer');
      expect(merged.note, contains('2台'));
      // 古い日のイベント名も残る。
      expect(data.dateEventFor('saiwaichou', '2026-06-01')?.name, 'pc');
    });

    test('前に読み込んだ方が新しく書き出されたものなら、置き換えない', () {
      final stored = doc('2026-09-28T01:00:00', ['2026-09-27']);
      final incoming = doc('2026-09-27T12:00:00+09:00', ['2026-09-26']);
      final merged = ViewerData.merge(stored, incoming);
      expect(merged.text, stored);
      expect(merged.note, contains('置き換えていません'));
    });

    test('前に読み込んだ内容が無い・壊れているときは、Driveの内容をそのまま使う', () {
      final incoming = doc('2026-09-27T12:00:00+09:00', ['2026-09-27']);
      expect(ViewerData.merge(null, incoming).text, incoming);
      expect(ViewerData.merge('{broken', incoming).text, incoming);
    });
  });
}
