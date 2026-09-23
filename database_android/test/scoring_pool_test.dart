import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';

SlotRecord rec({
  required String day,
  required int rack,
  String store = 'saiwaichou',
  String machine = 'M',
  int games = 3000,
}) => SlotRecord(
  store: store,
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: 10,
  rb: 5,
  maxHold: 1000,
);

/// 店舗・機種で仕分けた索引を使う前の、素朴な絞り込み。
List<SlotRecord> naivePool(SlotRecord row, List<SlotRecord> all) {
  final first = DateTime.parse(row.day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final target = row.games < 500 ? 500 : row.games;
  final lowest = target / 2 < 500 ? 500 : target / 2;
  return all
      .where(
        (r) =>
            r.store == row.store &&
            r.machine == row.machine &&
            r.day.compareTo(first) >= 0 &&
            r.day.compareTo(row.day) < 0 &&
            r.games >= lowest &&
            r.games <= target * 2,
      )
      .toList();
}

void main() {
  final all = <SlotRecord>[
    for (var i = 0; i < 40; i++)
      rec(
        day: DateTime(
          2026,
          9,
          20,
        ).subtract(Duration(days: i)).toIso8601String().substring(0, 10),
        rack: 300 + (i % 4),
        games: 400 + i * 200,
      ),
    for (var i = 0; i < 10; i++)
      rec(day: '2026-09-1${i % 10}', rack: 700 + i, machine: '別機種'),
    for (var i = 0; i < 10; i++)
      rec(day: '2026-09-1${i % 10}', rack: 300 + i, store: 'nagamachiminami'),
  ];

  test('店舗・機種の索引を使っても、比較相手は素朴な絞り込みと同じ', () {
    for (final row in all) {
      expect(
        comparisonPool(row, all).map((r) => r.key).toSet(),
        naivePool(row, all).map((r) => r.key).toSet(),
        reason: '${row.store} ${row.machine} ${row.day} ${row.rack}番台',
      );
    }
  });

  test('30日より前・当日・未来の台は比較に入れない', () {
    final row = rec(day: '2026-09-20', rack: 1);
    final pool = comparisonPool(row, [
      rec(day: '2026-08-20', rack: 2), // ちょうど31日前 → 入れない
      rec(day: '2026-08-21', rack: 3), // ちょうど30日前 → 入れる
      rec(day: '2026-09-20', rack: 4), // 当日 → 入れない
      rec(day: '2026-09-21', rack: 5), // 未来 → 入れない
      row,
    ]);
    expect(pool.map((r) => r.rack), [3]);
  });

  test('一覧が空でも、件数が変わっても正しく数え直す', () {
    expect(comparisonPool(rec(day: '2026-09-20', rack: 1), const []), isEmpty);
    final live = [rec(day: '2026-09-19', rack: 2)];
    final row = rec(day: '2026-09-20', rack: 1);
    expect(comparisonPool(row, live).length, 1);
    live.add(rec(day: '2026-09-18', rack: 3));
    expect(comparisonPool(row, live).length, 2); // 追加後は索引を作り直す
  });
}
