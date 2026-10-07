import 'package:database_android/candidate_log.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

const plusGraph = GraphMeasurement(
  baselineY: 200,
  peakY: 100,
  troughY: 250,
  endY: 150,
);
const minusGraph = GraphMeasurement(
  baselineY: 200,
  peakY: 180,
  troughY: 260,
  endY: 230,
);

/// 1台の台。[day] は9月の日。
SlotRecord rec(
  String machine,
  int rack,
  int day,
  int hits, {
  int games = 3000,
  GraphMeasurement? graph = plusGraph,
  String store = 'saiwaichou',
}) => SlotRecord(
  store: store,
  day: '2026-09-${day.toString().padLeft(2, '0')}',
  machine: machine,
  rack: rack,
  games: games,
  bb: hits,
  rb: 0,
  graph: graph,
);

/// 9/21〜9/24 の普段（3000G・当たり10・12・14・16回）と、9/25 の [today]。
List<SlotRecord> withPast(SlotRecord today) => [
  for (final (i, hits) in [10, 12, 14, 16].indexed)
    rec(today.machine, today.rack, 21 + i, hits, store: today.store),
  today,
];

/// 1台の機種8つ（9/25）。店は [store]。
List<SlotRecord> varietyDay(String store) => [
  ...withPast(rec('A', 1, 25, 20, store: store)), // 回ってプラス・当たり100
  ...withPast(rec('B', 2, 25, 8, store: store)), // 回ってプラス・当たり0
  ...withPast(rec('C', 3, 25, 20, graph: minusGraph, store: store)), // 凹み・100
  ...withPast(rec('D', 4, 25, 13, graph: minusGraph, store: store)), // 凹み・50
  ...withPast(rec('E', 5, 25, 20, games: 2000, store: store)), // 3000G未満
  ...withPast(rec('F', 6, 25, 13, graph: null, store: store)), // グラフ未取得
  rec('G', 7, 25, 30, games: 8000, store: store), // 回ってプラス・過去なし
  ...withPast(rec('H', 8, 25, 17, games: 4000, store: store)), // 回ってプラス・50
];

List<SlotRecord> onDay(List<SlotRecord> all, int day) => [
  for (final r in all)
    if (r.day == '2026-09-${day.toString().padLeft(2, '0')}') r,
];

void main() {
  test('終わり方：3000G以上回ってプラス／凹み、3000G未満、グラフ未取得', () {
    expect(varietyState(rec('X', 1, 25, 10)), VarietyState.plus);
    expect(varietyState(rec('X', 1, 25, 10, graph: minusGraph)), VarietyState.dented);
    // ゼロ線から1ピクセル以内は、プラスとは見ない（採点の終点と同じ）。
    const flat = GraphMeasurement(baselineY: 200, peakY: 150, troughY: 220, endY: 199);
    expect(varietyState(rec('X', 1, 25, 10, graph: flat)), VarietyState.dented);
    // 大当たり0回（グラフを取らない台）は凹み。
    expect(varietyState(rec('X', 1, 25, 0, graph: null)), VarietyState.dented);
    expect(varietyState(rec('X', 1, 25, 10, graph: null)), VarietyState.unknown);
    expect(varietyState(rec('X', 1, 25, 10, games: 2999)), VarietyState.quiet);
    expect(varietyState(rec('X', 1, 25, 10, games: 3000)), VarietyState.plus);
  });

  test('当たりの普段比：その台の前の30日と比べる（別の機種とは比べない）', () {
    final a = withPast(rec('A', 1, 25, 20));
    final d = withPast(rec('D', 4, 25, 13));
    // 20回は普段の4日（10・12・14・16）のどれより多い → 100。
    expect(varietyHitPercent(a.last, a), (percent: 100.0, refs: 4));
    // 13回は2日より多く2日より少ない → 50。
    expect(varietyHitPercent(d.last, d), (percent: 50.0, refs: 4));
    // 当たりの重い機種と軽い機種を並べても、互いには比べない。
    final both = [...a, for (final r in withPast(rec('重い', 9, 25, 2))) r.copyWith(bb: r.bb ~/ 5)];
    expect(varietyHitPercent(a.last, both).percent, 100.0);
    // 比べる記録が3件未満なら出さない。
    final short = [rec('S', 1, 24, 10), rec('S', 1, 25, 12)];
    expect(varietyHitPercent(short.last, short), (percent: null, refs: 1));
  });

  test('幸町：回ってプラスの台を先に、当たりの普段比・回転数の順で5台', () {
    final all = varietyDay('saiwaichou');
    final result = varietyNextDayCandidates(onDay(all, 25), all);
    // E（3000G未満）とF（グラフ未取得）は判断しない。
    expect((result.total, result.eligible), (8, 6));
    expect([for (final c in result.candidates) c.record.machine], [
      'A', // プラス・100
      'G', // プラス・比べる記録なし（50扱い）・8000G
      'H', // プラス・50・4000G
      'B', // プラス・0
      'C', // 凹み・100
    ]);
    final g = result.candidates[1];
    expect((g.index, g.days, g.confidence, g.variety), (50.0, 0, '比較なし', true));
  });

  test('長町南：回ったのに凹んだ台を先に選ぶ', () {
    final all = varietyDay('nagamachiminami');
    final result = varietyNextDayCandidates(onDay(all, 25), all);
    expect([for (final c in result.candidates) c.record.machine], [
      'C', // 凹み・100
      'D', // 凹み・50
      'A', // プラス・100
      'G',
      'H',
    ]);
  });

  test('未来の記録を足しても、その日の候補は変わらない', () {
    final all = varietyDay('saiwaichou');
    final more = [
      ...all,
      for (final r in onDay(all, 25)) r.copyWith(day: '2026-09-26', bb: 99),
    ];
    List<(String, double)> picks(List<SlotRecord> source) => [
      for (final c in varietyNextDayCandidates(onDay(source, 25), source).candidates)
        (c.record.machine, c.index),
    ];
    expect(picks(more), picks(all));
  });

  /// 1台の機種8つと、4台の機種R（3日分）。
  List<SlotRecord> store() => [
    ...varietyDay('saiwaichou'),
    for (var day = 23; day <= 25; day++)
      for (var k = 0; k < 4; k++) rec('R', 10 + k, day, 10 + 3 * k),
  ];

  test('その日の候補：4台以上の機種の候補（平均より順）の後ろにバラエティの5台', () {
    final all = store();
    final result = dayCandidates(onDay(all, 25), all);
    expect((result.machines, result.judged), (2, 2));
    expect(
      [for (final c in result.candidates) (c.record.machine, c.variety)],
      [
        ('R', false),
        ('A', true),
        ('G', true),
        ('H', true),
        ('B', true),
        ('C', true),
      ],
    );
  });

  test('候補の記録：1〜3台の機種はバラエティとして記録し、機種ごとには記録しない', () {
    final all = store();
    final now = DateTime.parse('2026-09-25T23:30:00+09:00');
    final saved = [
      ...onDay(all, 25).where((r) => r.machine == 'C'),
      ...onDay(all, 25).where((r) => r.machine == 'R'),
    ];
    final changed = changedCandidateSnapshots(
      saved: saved,
      all: all,
      latest: const {},
      now: now,
    );
    expect(
      {for (final s in changed) s.groupKey},
      {'saiwaichou|2026-09-25|R', 'saiwaichou|2026-09-25|バラエティ'},
    );
    final variety = changed.firstWhere((s) => s.machine == varietyGroupName);
    expect((variety.total, variety.eligible, variety.method), (8, 6, '2026-10-07'));
    expect([for (final c in variety.candidates) c.rack], [1, 7, 8, 2, 3]);
    // 同じ中身なら記録し直さない。
    final latest = latestCandidateSnapshots(changed);
    expect(
      changedCandidateSnapshots(saved: saved, all: all, latest: latest, now: now),
      isEmpty,
    );
    // 1台だった機種が4台になると、バラエティから出る（両方を記録し直す）。
    final grown = [
      ...all,
      for (var k = 0; k < 3; k++) rec('A', 40 + k, 25, 10),
    ];
    final after = changedCandidateSnapshots(
      saved: [rec('A', 40, 25, 10)],
      all: grown,
      latest: latest,
      now: now,
    );
    expect(
      {for (final s in after) s.groupKey},
      {'saiwaichou|2026-09-25|A', 'saiwaichou|2026-09-25|バラエティ'},
    );
    expect(after.firstWhere((s) => s.machine == varietyGroupName).total, 7);
  });
}
