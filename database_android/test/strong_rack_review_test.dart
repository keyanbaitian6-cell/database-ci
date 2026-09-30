import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/strong_rack_review.dart';
import 'package:flutter_test/flutter_test.dart';

// 当日80点以上の台を翌日候補から外す方式（分析専用、2026-09-30の規約
// NEXT_DAY_STRONG_RACK_REVIEW_20260930.md）の決まりを合成データで確かめる。

BacktestMember member(int rack, double index, double? today, {double? next}) =>
    BacktestMember(
      rack: rack,
      machine: 'テスト機種',
      index: index,
      days: 5,
      confidence: '少',
      todayScore: today,
      nextScore: next,
    );

BacktestGroup group(List<BacktestMember> members, int count) =>
    BacktestGroup('nagamachiminami', 'テスト機種', '2026-09-28', members, count);

void main() {
  test('80点以上の★を飛ばし、現行の順位（指数の大きい順・台番号）で補充する', () {
    final g = group([
      member(5, 60.0, 85), // 1位だが当日85点 → 外す
      member(3, 58.0, 70), // 2位
      member(9, 57.0, 20), // 3位（補充）
      member(1, 57.0, 40), // 同じ指数なら台番号の小さい1番台が先
      member(7, 50.0, 90),
      member(8, 49.0, 30),
      member(2, 48.0, 30),
      member(4, 47.0, 30),
    ], 2);
    expect([for (final m in currentOrder(g)) m.rack], [5, 3, 1, 9, 7, 8, 2, 4]);
    expect([for (final m in excludeStrong(g)) m.rack], [3, 1]);
  });

  test('ちょうど80点も外す。点数の無い台（500G以下など）は外さない', () {
    final g = group([
      member(1, 60.0, 80.0),
      member(2, 59.0, null),
      member(3, 58.0, 79.9),
      member(4, 57.0, 30),
    ], 2);
    expect([for (final m in excludeStrong(g)) m.rack], [2, 3]);
  });

  test('補充できる台が足りなければ候補は減り、候補なしもあり得る', () {
    final few = group([
      member(1, 60.0, 90),
      member(2, 59.0, 88),
      member(3, 58.0, 20),
      member(4, 57.0, 81),
    ], 2);
    expect([for (final m in excludeStrong(few)) m.rack], [3]);
    final none = group([
      member(1, 60.0, 90),
      member(2, 59.0, 88),
      member(3, 58.0, 85),
      member(4, 57.0, 81),
    ], 1);
    expect(excludeStrong(none), isEmpty);
  });

  test('候補数は現行が上限（多く選ばない）', () {
    final g = group([
      for (var rack = 1; rack <= 12; rack++) member(rack, 70.0 - rack, 30),
    ], 3);
    expect(excludeStrong(g).length, 3);
    expect([for (final m in excludeStrong(g)) m.rack], [1, 2, 3]);
  });

  test('グラフの終わり方：ゼロ線より上はプラス、未取得は「グラフなし」（右肩上がりとは扱わない）', () {
    SlotRecord rec({GraphMeasurement? graph, int bb = 10}) => SlotRecord(
      store: 'nagamachiminami',
      day: '2026-09-28',
      machine: 'テスト機種',
      rack: 1,
      games: 5000,
      bb: bb,
      rb: 0,
      graph: graph,
    );
    const up = GraphMeasurement(
      baselineY: 200,
      peakY: 50,
      troughY: 210,
      endY: 60,
    );
    const down = GraphMeasurement(
      baselineY: 200,
      peakY: 150,
      troughY: 260,
      endY: 250,
    );
    expect(endState(rec(graph: up)), EndState.plus);
    expect(endState(rec(graph: down)), EndState.dented);
    expect(endState(rec()), EndState.none);
    expect(endState(rec(bb: 0)), EndState.dented); // 大当たり0回はグラフを取らない
    expect(endState(null), EndState.none);
    expect(endToPeak(rec(graph: up)), closeTo(140 / 150, 1e-9));
    expect(endToPeak(rec()), isNull);
  });
}
