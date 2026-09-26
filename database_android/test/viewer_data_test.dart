import 'dart:convert';

import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/viewer_data.dart';
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
}
