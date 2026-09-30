import 'package:database_android/low_activity_candidate_comparison.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord row(String day, {int games = 6000, String machine = 'M'}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: day,
      machine: machine,
      rack: 1,
      games: games,
      bb: games == 0 ? 0 : 25,
      rb: games == 0 ? 0 : 15,
      maxHold: 1000,
      capturedAt: '${day}T23:00:00+09:00',
    );
BacktestMember member(
  int rack, {
  String machine = 'M',
  double? next = 60,
  bool current = false,
}) => BacktestMember(
  rack: rack,
  machine: machine,
  index: 55,
  days: 3,
  confidence: '少',
  todayScore: 50,
  nextScore: next,
)..current = current;
ThreeDayFeature feature(double? games, double? score) =>
    (games: games, score: score, scoredDays: score == null ? 0 : 3);

void main() {
  test('exact calendar days required, not last three recording days', () {
    final target = row('2026-09-24');
    final f = threeDayFeature(target, [
      target,
      row('2026-09-22'),
      row('2026-09-21'),
    ]);
    expect(f.games, isNull);
    expect(f.score, isNull);
  });
  test(
    'observed zero games included, unscored day excluded from average score',
    () {
      final rows = [
        row('2026-09-24', games: 0),
        row('2026-09-23'),
        row('2026-09-22'),
      ];
      final f = threeDayFeature(rows.first, rows);
      expect(f.games, 4000);
      expect(f.scoredDays, 2);
      final scores = rows
          .skip(1)
          .map((r) => scoreRecord(r, rows).total!)
          .toList();
      expect(f.score, (scores[0] + scores[1]) / 2);
    },
  );
  test('one scored day is insufficient, but games feature remains', () {
    final rows = [
      row('2026-09-24'),
      row('2026-09-23', games: 0),
      row('2026-09-22', games: 0),
    ];
    final f = threeDayFeature(rows.first, rows);
    expect(f.games, 2000);
    expect(f.score, isNull);
    expect(f.scoredDays, 1);
  });
  test('machine swaps and abnormal values are not zero games', () {
    final target = row('2026-09-24');
    expect(
      threeDayFeature(target, [
        target,
        row('2026-09-23', machine: 'Other'),
        row('2026-09-22'),
      ]).games,
      isNull,
    );
    expect(
      threeDayFeature(target, [
        target,
        row('2026-09-23', games: 88888888),
        row('2026-09-22'),
      ]).games,
      isNull,
    );
  });
  test('future and post-cutoff values cannot enter available feature data', () {
    final target = row('2026-09-24');
    final full = [
      target,
      row('2026-09-23'),
      row('2026-09-22'),
      row('2026-09-25', games: 1),
    ];
    final available = availableRecords(
      full,
      target.day,
      cutoff: predictionCutoff(target.day),
    );
    expect(
      threeDayFeature(target, available),
      threeDayFeature(target, full.take(3).toList()),
    );
    full[1] = full[1].copyWith(capturedAt: '2026-09-25T00:00:00+09:00');
    expect(
      threeDayFeature(
        target,
        availableRecords(
          full,
          target.day,
          cutoff: predictionCutoff(target.day),
        ),
      ).games,
      isNull,
    );
  });
  test('variety includes low-game members; all methods obey actual baseline budget', () {
    final a = member(1, machine: 'A', current: true),
        b = member(2, machine: 'B');
    final g = selectLowActivity(
      BacktestGroup(
        'nagamachiminami',
        'バラエティ',
        '2026-09-24',
        [a, b],
        1,
        variety: true,
      ),
      {a: feature(6000, 60), b: feature(0, null)},
    );
    expect(g.selected[LowActivityMethod.lowGames], {b});
    expect(g.selected[LowActivityMethod.lowScore], {a});
    expect(g.selected[LowActivityMethod.blend], {a});
    expect(g.selected.values.every((s) => s.length <= 1), isTrue);
  });
  test('blend averages low percentiles with rack-ascending ties', () {
    final a = member(1, current: true), b = member(2), c = member(3);
    final g = selectLowActivity(
      BacktestGroup('nagamachiminami', 'M', '2026-09-24', [c, b, a], 1),
      {a: feature(1000, 60), b: feature(6000, 20), c: feature(8000, 80)},
    );
    expect(g.selected[LowActivityMethod.blend], {a});
    expect(g.selected[LowActivityMethod.lowScore], {b});
  });
  test('coverage separates abstention from selected but unscored', () {
    final a = member(1, current: true, next: null);
    final g = selectLowActivity(
      BacktestGroup('nagamachiminami', 'M', '2026-09-24', [a], 1),
      {a: feature(null, null)},
    );
    final methods =
        ((summarizeLowActivityComparison([g])['all'] as Map)['methods'] as Map);
    expect(methods['current']['selected_but_unscored_groups'], 1);
    expect(methods['current']['no_selection_groups'], 0);
    expect(methods['lowGames']['no_selection_groups'], 1);
    expect(methods['lowGames']['selected_but_unscored_groups'], 0);
    expect(methods['lowGames']['gap_vs_fixed_pool']['mean_of_days'], isNull);
  });
  test(
    'variety repetition does not connect replacement machine on same rack',
    () {
      LowActivityGroup group(String day, String machine) {
        final a = member(1, machine: machine, current: true);
        return selectLowActivity(
          BacktestGroup('nagamachiminami', 'バラエティ', day, [a], 1, variety: true),
          {a: feature(1000, 30)},
        );
      }

      final rate = lowActivityRepeatRate([
        group('2026-09-23', 'A'),
        group('2026-09-24', 'B'),
      ], LowActivityMethod.current);
      expect(rate['current_selected_on_adjacent_pairs'], 1);
      expect(rate['repeated_racks'], 0);
    },
  );
}
