import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/reference_candidate_comparison.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(
  String day,
  int rack, {
  int? hits,
  int games = 6000,
  String machine = 'M',
  String? at,
}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: hits ?? 60 - rack * 5,
  rb: 0,
  maxHold: 1000,
  capturedAt: at ?? '${day}T23:00:00+09:00',
);

List<SlotRecord> fixture({bool tied = false}) => [
  for (var d = 20; d <= 24; d++)
    for (var rack = 1; rack <= 8; rack++)
      rec('2026-09-$d', rack, hits: tied ? 30 : null),
];

ReferenceComparisonGroup prediction(
  List<SlotRecord> rows, [
  String day = '2026-09-23',
]) =>
    buildReferenceComparison(rows)
        .singleWhere((g) => g.baseline.day == day && g.baseline.machine == 'M');

ReferenceComparisonGroup manualGroup(
  String day,
  List<double?> scores, {
  String machine = 'M',
  bool gate = true,
  Set<int> picks = const {1},
}) {
  final members = [
    for (var i = 0; i < scores.length; i++)
      BacktestMember(
        rack: i + 1,
        machine: machine,
        index: gate ? 60 : 50,
        days: 4,
        confidence: '少',
        todayScore: 40,
        nextScore: scores[i],
      )..current = picks.contains(i + 1),
  ];
  return ReferenceComparisonGroup(
    BacktestGroup('nagamachiminami', machine, day, members, picks.length),
    {
      ReferenceMethod.current: picks,
      ReferenceMethod.currentGate: gate ? picks : {},
      ReferenceMethod.recent: picks,
      ReferenceMethod.recentGate: gate ? picks : {},
    },
    {for (final m in members) m.rack: m.index},
  );
}

Map allReport(List<ReferenceComparisonGroup> groups) =>
    summarizeReferenceComparison(groups, bootstrapRounds: 200)['all'] as Map;

void main() {
  test('fixed current population and current selections exactly match production backtest', () {
    final full = fixture();
    final before = runBacktest(full, cutoffFor: predictionCutoff);
    final comparison = buildReferenceComparison(full);
    expect(comparison.length, before.groups.length);
    for (var i = 0; i < before.groups.length; i++) {
      final a = before.groups[i], b = comparison[i];
      expect(
        (b.baseline.store, b.baseline.day, b.baseline.machine),
        (a.store, a.day, a.machine),
      );
      expect(
        b.baseline.members.map((m) => (m.rack, m.index, m.nextScore)),
        a.members.map((m) => (m.rack, m.index, m.nextScore)),
      );
      expect(b.selected[ReferenceMethod.current], {
        for (final m in a.members)
          if (m.current) m.rack,
      });
      expect(b.selected[ReferenceMethod.recent]!.length, a.count);
      for (final method in ReferenceMethod.values) {
        expect(
          b.selected[method]!.every((r) => a.members.any((m) => m.rack == r)),
          isTrue,
        );
      }
    }
    expect(scoringVersion, referenceScoringVersion);
    final g = prediction(full);
    for (final m in g.baseline.members) {
      final truth = full.singleWhere(
        (r) => r.day == '2026-09-24' && r.rack == m.rack,
      );
      expect(m.nextScore, scoreRecord(truth, full).total);
    }
  });

  test('3-day half-life uses calendar age despite missing dates', () {
    final all = [
      for (final day in ['2026-09-01', '2026-09-04', '2026-09-10'])
        for (var rack = 1; rack <= 4; rack++)
          rec(day, rack, hits: [60, 45, 30, 15][rack - 1]),
    ];
    final target = all.firstWhere((r) => r.day == '2026-09-10' && r.rack == 1);
    final index = recentReferenceIndex(target, all);
    expect(index.days, 3);
    expect(index.weightSum, closeTo(1 + .25 + .125, 1e-12));
    expect(index.index, closeTo(50 + 30 * 1.375 / 6.375, 1e-12));
    expect(index.index, isNot(double.parse(index.index!.toStringAsFixed(1))));
  });

  test('future records never alter past candidates or raw recent indexes', () {
    final first = prediction(fixture());
    final later = prediction([
      ...fixture(),
      for (var rack = 1; rack <= 8; rack++)
        rec('2026-09-25', rack, hits: rack * 10),
    ]);
    expect(later.selected, first.selected);
    expect(later.recentIndices, first.recentIndices);
  });

  test('cutoff excludes exact midnight and unknown captured_at values from population', () {
    final full = [
      for (final r in fixture())
        if (!(r.day == '2026-09-23' && r.rack <= 2)) r,
      rec('2026-09-23', 1, at: '2026-09-24T00:00:00+09:00'),
      rec('2026-09-23', 2).copyWith(capturedAt: 'invalid'),
    ];
    final g = prediction(full);
    expect(g.baseline.members.map((m) => m.rack), isNot(contains(1)));
    expect(g.baseline.members.map((m) => m.rack), isNot(contains(2)));
    expect(g.baseline.members, hasLength(6));
  });

  test('neutral ties pick low rack numbers, gates select none without dropping groups', () {
    final g = prediction(fixture(tied: true));
    expect(g.selected[ReferenceMethod.current], {1, 2});
    expect(g.selected[ReferenceMethod.recent], {1, 2});
    expect(g.selected[ReferenceMethod.currentGate], isEmpty);
    expect(g.selected[ReferenceMethod.recentGate], isEmpty);
    final report = (allReport([g])['methods'] as Map)['recentGate'] as Map;
    expect(report['groups_total'], 1);
    expect(report['no_selection_groups'], 1);
    expect(report['selected_but_unscored_groups'], 0);
    expect(report['selected'], 0);
    expect(report['evaluable_rate'], isNull);
    expect((report['gap_vs_fixed_pool'] as Map)['mean_of_days'], isNull);
  });

  test('recent rankings use raw values when rounded scores would tie', () {
    final full = [
      for (var day = 20; day <= 24; day++) ...[
        rec('2026-09-$day', 1, hits: 30),
        rec('2026-09-$day', 2, hits: 31, games: 6200),
        rec('2026-09-$day', 3, hits: 20),
        rec('2026-09-$day', 4, hits: 15),
      ],
    ];
    final g = prediction(full);
    expect(g.recentIndices[2], greaterThan(g.recentIndices[1]!));
    expect(
      g.recentIndices[2]!.toStringAsFixed(1),
      g.recentIndices[1]!.toStringAsFixed(1),
    );
    expect(g.selected[ReferenceMethod.current], {2});
    expect(g.selected[ReferenceMethod.recent], {2});
  });

  test('history uses at most 10 recording days with the same eligibility as current', () {
    final full = [
      for (var day = 1; day <= 14; day++)
        for (var rack = 1; rack <= 4; rack++)
          rec('2026-09-${day.toString().padLeft(2, '0')}', rack),
    ];
    final g = prediction(full, '2026-09-13');
    for (final m in g.baseline.members) {
      final row = full.singleWhere(
        (r) => r.day == '2026-09-13' && r.rack == m.rack,
      );
      expect(recentReferenceIndex(row, full).days, m.days);
      expect(m.days, 10);
    }
  });

  test('selected but unscored differs from abstention; labels are never zero-imputed', () {
    final full = [
      for (final r in fixture())
        if (!(r.day == '2026-09-24' && r.rack <= 2)) r,
      rec('2026-09-24', 1, games: 400),
    ];
    final g = prediction(full);
    expect(
      g.baseline.members
          .where((m) => m.rack <= 2)
          .every((m) => m.nextScore == null),
      isTrue,
    );
    final current = (allReport([g])['methods'] as Map)['current'] as Map;
    expect(current['selected'], 2);
    expect(current['evaluable'], 0);
    expect(current['groups_total'], 1);
    expect(current['no_selection_groups'], 0);
    expect(current['selected_but_unscored_groups'], 1);
    expect(current['evaluable_group_rate'], 0);
    expect(current['chosen_mean_pooled'], isNull);
  });

  test(
    'equal-weight day mean differs from pooled rack mean; CI seed is fixed',
    () {
      final groups = [
        manualGroup('2026-09-21', [50, 30, 40, 40], machine: 'A'), // gap +10
        manualGroup('2026-09-21', [70, 30, 30, 30], machine: 'B'), // gap +30
        manualGroup('2026-09-22', [30, 50, 40, 40]), // gap -10
      ];
      final current = (allReport(groups)['methods'] as Map)['current'] as Map;
      final gap = current['gap_vs_fixed_pool'] as Map;
      expect(gap['mean_of_days'], 5);
      expect(gap['median_of_days'], 5);
      expect(gap['min_day_mean'], -10);
      expect(gap['max_day_mean'], 20);
      expect(current['chosen_mean_pooled'], 50);
      expect(current['pool_mean_in_evaluable_groups_pooled'], 40);
      final ci = dayBootstrap(
        [20, -10],
        rounds: 200,
        seed: referenceBootstrapSeed,
      )!;
      expect(gap['ci95'], [ci.$1, ci.$2]);
      expect((gap['by_day'] as Map)['2026-09-21'], {
        'groups': 2,
        'mean': 20.0,
        'median': 20.0,
        'min': 10.0,
        'max': 30.0,
      });
    },
  );

  test('gate coverage and current performance on retained/common groups are explicit', () {
    final groups = [
      manualGroup('2026-09-21', [50, 30, 40, 40], machine: 'A'),
      manualGroup('2026-09-21', [70, 30, 30, 30], machine: 'B'),
      manualGroup('2026-09-22', [30, 50, 40, 40], gate: false),
    ];
    final report = allReport(groups);
    final gate = (report['methods'] as Map)['currentGate'] as Map;
    expect((report['fixed_population'] as Map)['groups'], 3);
    expect(gate['groups_total'], 3);
    expect(gate['groups_with_selection'], 2);
    expect(gate['no_selection_groups'], 1);
    expect(gate['evaluable_group_rate'], closeTo(2 / 3, .0001));
    expect((gate['gap_vs_fixed_pool'] as Map)['mean_of_days'], 20);
    final retained = gate['current_on_groups_with_method_selection'] as Map;
    expect((retained['gap_vs_fixed_pool'] as Map)['mean_of_days'], 20);
    final paired = gate['minus_current_on_common_evaluable_groups'] as Map;
    expect(paired['common_evaluable_groups'], 2);
    expect(paired['mean_of_days'], 0);
    expect(paired['days'], 1);
    expect(
      paired['ci95'],
      isNull,
    ); // One day is not a useful uncertainty interval.
  });

  test('repeat denominator is current-day picks and does not bridge missing calendar days', () {
    final groups = [
      manualGroup('2026-09-20', [50, 30, 40, 40]),
      manualGroup('2026-09-22', [50, 30, 40, 40]),
      manualGroup('2026-09-23', [50, 30, 40, 40], picks: {1, 2}),
    ];
    final repeat = referenceRepeatRate(groups, ReferenceMethod.current);
    expect(repeat['adjacent_baseline_group_pairs'], 1);
    expect(repeat['current_selected_on_adjacent_pairs'], 2);
    expect(repeat['repeated_racks'], 1);
    expect(repeat['repeat_rate'], .5);
  });
}
