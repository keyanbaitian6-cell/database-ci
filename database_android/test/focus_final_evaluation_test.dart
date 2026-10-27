import 'package:database_android/focus_final_evaluation.dart';
import 'package:database_android/focus_validation.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:flutter_test/flutter_test.dart';

BacktestMember member(int rack, double? next, {bool current = false}) =>
    BacktestMember(
      rack: rack,
      machine: 'A',
      index: 55,
      days: 5,
      confidence: '少',
      todayScore: 50,
      nextScore: next,
    )..current = current;

FocusValidationGroup group(
  String store,
  String day,
  List<double?> next, {
  required Set<int> current,
  required Set<int> primary,
  String machine = 'A',
}) {
  final members = [
    for (var i = 0; i < next.length; i++)
      member(i + 1, next[i], current: current.contains(i + 1)),
  ];
  return FocusValidationGroup(
    BacktestGroup(store, machine, day, members, current.length),
    primary,
    {},
    {},
    {for (final m in members) m.rack: 55.0},
    {for (final m in members) m.rack: 1000},
  );
}

List<String> daysFrom(String first, int count) => [
  for (var i = 0; i < count; i++) shiftDay(first, i),
];

/// 各日・両店で、主方式が現行より [gap] 点よい（翌日の点数）グループ。
List<FocusValidationGroup> period(
  int days, {
  double gap = 20,
  double nagamachiGap = 20,
}) => [
  for (final day in daysFrom('2026-09-30', days)) ...[
    group(
      'saiwaichou',
      day,
      [50 + gap, 50, 50, 50],
      current: {2},
      primary: {1},
    ),
    group(
      'nagamachiminami',
      day,
      [50 + nagamachiGap, 50, 50, 50],
      current: {2},
      primary: {1},
    ),
  ],
];

void main() {
  test('直近重視の指数が同じなら、予測日の回転数が多い台を上にする', () {
    final g = BacktestGroup('saiwaichou', 'A', '2026-09-30', [
      member(1, null),
      member(2, null),
      member(3, null),
      member(4, null),
    ], 2);
    expect(
      focusPrimaryPicks(
        g,
        {1: 60, 2: 60, 3: 60, 4: 50},
        {1: 2000, 2: 6000, 3: 4000, 4: 9000},
      ).map((m) => m.rack),
      [2, 3],
    );
  });

  test('移動ブロック：同じ入力なら同じ区間、2ブロック分に満たなければ出さない', () {
    final values = [for (var i = 0; i < 20; i++) (i % 5) - 1.0];
    final a = movingBlockBootstrap(values, 5);
    final b = movingBlockBootstrap(values, 5);
    expect(a, isNotNull);
    expect(a, b);
    expect(a!.low, lessThanOrEqualTo(a.high));
    expect(movingBlockBootstrap(values.take(9).toList(), 5), isNull);
    final constant = movingBlockBootstrap(List.filled(12, 3.0), 5)!;
    expect((constant.low, constant.high), (3.0, 3.0));
  });

  test('自己相関：交互に上下する日は負', () {
    expect(lag1Autocorrelation([1, -1, 1, -1, 1, -1])!, lessThan(0));
    expect(lag1Autocorrelation([1, 1]), isNull);
  });

  test('20日・両店とも正・区間が0より上・評価率が同じなら採用', () {
    final judgment = focusAdoptionJudgment(period(20));
    expect(judgment['adopt'], isTrue);
    expect(
      (judgment['conditions'] as Map).values.every((v) => v == true),
      isTrue,
    );
  });

  test('19日では採用しない（5日ブロックも4つに満たない）', () {
    final conditions = focusAdoptionJudgment(period(19))['conditions'] as Map;
    expect(conditions['evaluable_days_at_least_20'], isFalse);
    expect(conditions['moving_block_5_sufficient_blocks'], isFalse);
  });

  test('片方の店が負なら採用しない', () {
    final judgment = focusAdoptionJudgment(period(20, nagamachiGap: -1));
    expect(
      (judgment['conditions'] as Map)['both_stores_direct_difference_positive'],
      isFalse,
    );
    expect(judgment['adopt'], isFalse);
  });

  test('主方式の選んだ台が翌日採点できないことが増えたら採用しない', () {
    final groups = [
      ...period(20),
      for (final day in daysFrom('2026-09-30', 20))
        group(
          'saiwaichou',
          day,
          [null, 50, 50, 50],
          current: {2},
          primary: {1},
          machine: 'B',
        ),
    ];
    final judgment = focusAdoptionJudgment(groups);
    final conditions = judgment['conditions'] as Map;
    expect(conditions['evaluable_group_rate_not_worse_than_2pt'], isFalse);
    expect(conditions['evaluable_pick_rate_not_worse_than_2pt'], isFalse);
    // 採点できない台を0点にして直接差へ入れない。
    expect(focusDirectDifference(groups).values, everyElement(20.0));
    expect(judgment['adopt'], isFalse);
  });

  test('候補なし・候補減少を数え、候補なしのグループは比べる相手を残す', () {
    final groups = [
      group(
        'saiwaichou',
        '2026-09-30',
        [60, 50, 40, 30],
        current: {1},
        primary: {},
      ),
    ];
    final coverage = focusCoverage(groups, FocusMethod.primary);
    expect(coverage.withSelection, 0);
    expect(coverage.reduced, 1);
    expect(coverage.groups, 1);
    expect(focusDirectDifference(groups).values, isEmpty);
  });

  test('最終評価は10/31（日本時間）より前は実行しない、10/30の記録も要る', () {
    SlotRecord rec(String store, String day) => SlotRecord(
      store: store,
      day: day,
      machine: 'A',
      rack: 1,
      games: 1000,
      bb: 1,
      rb: 1,
    );
    final complete = [
      rec('saiwaichou', '2026-10-30'),
      rec('nagamachiminami', '2026-10-30'),
    ];
    // 10/30 23:59 JST は10/31より前。
    expect(
      focusFinalBlocker(DateTime.utc(2026, 10, 30, 14, 59), complete),
      isNotNull,
    );
    expect(
      focusFinalBlocker(DateTime.utc(2026, 10, 30, 15, 0), complete),
      isNull,
    );
    final missing = [rec('saiwaichou', '2026-10-30')];
    expect(
      focusFinalBlocker(DateTime.utc(2026, 11, 1), missing),
      contains('nagamachiminami'),
    );
    expect(
      focusFinalBlocker(
        DateTime.utc(2026, 11, 1),
        missing,
        lastLabelDayMissingOk: true,
      ),
      isNull,
    );
  });

  test('取得時刻の区分は日本時間で、締切（翌日0:00）の前後を分ける', () {
    SlotRecord at(String? capturedAt) => SlotRecord(
      store: 'saiwaichou',
      day: '2026-10-01',
      machine: 'A',
      rack: 1,
      games: 1000,
      bb: 1,
      rb: 1,
      capturedAt: capturedAt,
    );
    expect(captureBucket(at(null)), 'missing');
    expect(captureBucket(at('2026-10-01T21:59:00+09:00')), 'day_00_22');
    expect(captureBucket(at('2026-10-01T23:59:59+09:00')), 'day_22_24');
    expect(captureBucket(at('2026-10-01T15:00:00Z')), 'next_00_02');
    expect(captureBucket(at('2026-10-02T02:00:00+09:00')), 'next_02_08');
    expect(captureBucket(at('2026-10-02T07:59:00+09:00')), 'next_02_08');
    expect(captureBucket(at('2026-10-02T08:00:00+09:00')), 'next_08_later');
    expect(captureBucket(at('2026-09-30T23:00:00+09:00')), 'before_day');
  });

  test('選び方の性質：当日の上位k台と一致する割合と、無作為の期待値', () {
    final members = [
      for (var i = 1; i <= 4; i++)
        BacktestMember(
          rack: i,
          machine: 'A',
          index: 55,
          days: 5,
          confidence: '少',
          todayScore: 100.0 - i * 10,
          nextScore: null,
        )..current = i == 1,
    ];
    members.first.previousScore = true;
    final g = FocusValidationGroup(
      BacktestGroup('saiwaichou', 'A', '2026-09-30', members, 1),
      {4},
      {1},
      {},
      {for (final m in members) m.rack: 55.0},
      {for (final m in members) m.rack: 1000},
    );
    final profile = focusSelectionProfile([g]);
    expect((profile['current_all_stars'] as Map)['share_in_today_top_k'], 1.0);
    expect((profile['primary'] as Map)['share_in_today_top_k'], 0.0);
    expect(
      (profile['primary'] as Map)['random_expectation_in_today_top_k'],
      0.25,
    );
  });
}
