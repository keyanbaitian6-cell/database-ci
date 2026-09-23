import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/data_checks.dart';
import 'package:database_android/models.dart';

SlotRecord rec(
  int rack, {
  String store = 'nagamachiminami',
  String day = '2026-09-22',
  String machine = 'テスト',
}) => SlotRecord(
  store: store,
  day: day,
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
);

void main() {
  final records = [
    rec(1),
    rec(2),
    rec(3, machine: '別機種'),
    rec(4, store: 'saiwaichou'),
    rec(5, store: 'saiwaichou', machine: 'テスト'),
    rec(6, day: '2026-09-21'),
  ];
  List<int> racks(List<SlotRecord> rows) => [for (final r in rows) r.rack];

  test('機種ごと：同じ店舗・日付のその機種だけ（別店舗の同名機種・別日は残す）', () {
    expect(
      racks(
        recordsInGroup(
          records,
          day: '2026-09-22',
          store: 'nagamachiminami',
          machine: 'テスト',
        ),
      ),
      [1, 2],
    );
  });

  test('店舗の日付ごと：その店舗のその日の全機種', () {
    expect(
      racks(
        recordsInGroup(records, day: '2026-09-22', store: 'nagamachiminami'),
      ),
      [1, 2, 3],
    );
  });

  test('両店舗の日付ごと：その日の両店舗すべて。別日は残す', () {
    expect(racks(recordsInGroup(records, day: '2026-09-22')), [1, 2, 3, 4, 5]);
    expect(recordsInGroup(records, day: '2026-09-01'), isEmpty);
  });

  test('店舗なしで機種だけの指定は受け付けない', () {
    expect(
      () => recordsInGroup(records, day: '2026-09-22', machine: 'テスト'),
      throwsArgumentError,
    );
  });
}
