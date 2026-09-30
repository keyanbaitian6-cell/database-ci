import 'dart:math';

import 'models.dart';
import 'next_day_backtest.dart';
import 'scoring.dart';

/// Analysis only. Do not connect these alternatives to an app candidate list.
/// Fixed protocol: NEXT_DAY_REFERENCE_REVIEW_20260930.md.
enum ReferenceMethod { current, currentGate, recent, recentGate }

const referenceHalfLifeDays = 3;
const referenceBootstrapSeed = 20260930;
const referenceScoringVersion = '2026-09-29-v12';

/// Same usable recording days, peers and per-day contribution as nextDayIndex.
/// Calendar decay also changes shrinkage through the smaller weight sum.
/// Return the unrounded index so neither
/// ranking nor the >50 gate introduces a rounding-dependent tie.
({int days, double? index, double weightSum}) recentReferenceIndex(
  SlotRecord record,
  List<SlotRecord> all,
) {
  DateTime utcDay(String day) {
    final d = DateTime.parse(day);
    return DateTime.utc(d.year, d.month, d.day);
  }

  final target = utcDay(record.day);
  final first = target
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final byDay = <String, List<SlotRecord>>{};
  for (final r in machineHistory(all, record.store, record.machine)) {
    if (r.day.compareTo(first) >= 0 &&
        r.day.compareTo(record.day) <= 0 &&
        r.games >= 500 &&
        r.bb >= 0 &&
        r.rb >= 0 &&
        !hasImplausibleNumbers(r)) {
      byDay.putIfAbsent(r.day, () => []).add(r);
    }
  }
  final days = [
    for (final entry in byDay.entries)
      if (entry.value.any((r) => r.rack == record.rack)) entry.key,
  ]..sort((a, b) => b.compareTo(a));
  var n = 0, weightedSum = 0.0, weightSum = 0.0;
  for (final day in days.take(10)) {
    final mine = byDay[day]!.firstWhere((r) => r.rack == record.rack);
    final peers = byDay[day]!
        .where((r) => r.games >= mine.games / 2 && r.games <= mine.games * 2)
        .toList();
    if (peers.length < 3) continue;
    final rank = percentile(
      (mine.bb + mine.rb) / mine.games,
      peers.map((r) => (r.bb + r.rb) / r.games).toList(),
    );
    final contribution =
        (100 * rank - 50) * mine.games / (mine.games + shrinkGames);
    final age = target.difference(utcDay(day)).inDays;
    final weight = pow(2.0, -age / referenceHalfLifeDays).toDouble();
    n++;
    weightedSum += weight * contribution;
    weightSum += weight;
  }
  return (
    days: n,
    index: n < 3 ? null : 50 + weightedSum / (weightSum + 5),
    weightSum: weightSum,
  );
}

class ReferenceComparisonGroup {
  ReferenceComparisonGroup(this.baseline, this.selected, this.recentIndices);

  final BacktestGroup baseline;
  final Map<ReferenceMethod, Set<int>> selected;
  final Map<int, double> recentIndices;

  List<BacktestMember> picks(ReferenceMethod method) => [
    for (final m in baseline.members)
      if (selected[method]!.contains(m.rack)) m,
  ];
}

/// Current runBacktest determines the complete, fixed population. Gates never
/// remove groups or members from that population, even when no rack is chosen.
List<ReferenceComparisonGroup> buildReferenceComparison(List<SlotRecord> full) {
  if (scoringVersion != referenceScoringVersion) {
    throw StateError(
      'This protocol requires scoring $referenceScoringVersion.',
    );
  }
  final baseline = runBacktest(full, cutoffFor: predictionCutoff);
  final availability = <String, List<SlotRecord>>{};
  final result = <ReferenceComparisonGroup>[];
  for (final g in baseline.groups) {
    final available = availability.putIfAbsent(
      g.day,
      () => availableRecords(full, g.day, cutoff: predictionCutoff(g.day)),
    );
    final history = machineHistory(available, g.store, g.machine);
    final rows = {
      for (final r in history)
        if (r.day == g.day) r.rack: r,
    };
    final recentIndices = <int, double>{};
    for (final member in g.members) {
      final tendency = recentReferenceIndex(rows[member.rack]!, history);
      if (tendency.index == null || tendency.days != member.days) {
        throw StateError(
          '${g.store} ${g.day} ${g.machine}: eligibility changed',
        );
      }
      recentIndices[member.rack] = tendency.index!;
    }
    final recentOrder = [...g.members]
      ..sort((a, b) {
        final byIndex = recentIndices[b.rack]!.compareTo(
          recentIndices[a.rack]!,
        );
        return byIndex != 0 ? byIndex : a.rack.compareTo(b.rack);
      });
    final current = {
      for (final m in g.members)
        if (m.current) m.rack,
    };
    final recent = {for (final m in recentOrder.take(g.count)) m.rack};
    result.add(
      ReferenceComparisonGroup(g, {
        ReferenceMethod.current: current,
        ReferenceMethod.currentGate: {
          for (final m in g.members)
            if (m.current && m.index > 50) m.rack,
        },
        ReferenceMethod.recent: recent,
        ReferenceMethod.recentGate: {
          for (final rack in recent)
            if (recentIndices[rack]! > 50) rack,
        },
      }, recentIndices),
    );
  }
  return result;
}

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

double? _median(List<double> values) {
  if (values.isEmpty) return null;
  final sorted = [...values]..sort();
  final mid = sorted.length ~/ 2;
  return sorted.length.isOdd
      ? sorted[mid]
      : (sorted[mid - 1] + sorted[mid]) / 2;
}

double? _rounded(double? value) =>
    value == null ? null : double.parse(value.toStringAsFixed(4));

/// A day, rather than a rack or group, is the unit resampled. Within each day
/// every evaluable store/machine group has equal weight; days have equal weight.
Map<String, Object?> referenceDaySummary(
  Map<String, List<double>> byDay, {
  int bootstrapRounds = 10000,
}) {
  final days = byDay.keys.toList()..sort();
  final values = [for (final day in days) _mean(byDay[day]!)!];
  final ci = dayBootstrap(
    values,
    rounds: bootstrapRounds,
    seed: referenceBootstrapSeed,
  );
  return {
    'days': values.length,
    'mean_of_days': _rounded(_mean(values)),
    'median_of_days': _rounded(_median(values)),
    'min_day_mean': values.isEmpty ? null : _rounded(values.reduce(min)),
    'max_day_mean': values.isEmpty ? null : _rounded(values.reduce(max)),
    'ci95': ci == null ? null : [_rounded(ci.$1), _rounded(ci.$2)],
    'positive_days': values.where((v) => v > 0).length,
    'by_day': {
      for (final day in days)
        day: {
          'groups': byDay[day]!.length,
          'mean': _rounded(_mean(byDay[day]!)),
          'median': _rounded(_median(byDay[day]!)),
          'min': _rounded(byDay[day]!.reduce(min)),
          'max': _rounded(byDay[day]!.reduce(max)),
        },
    },
  };
}

List<double> _scores(Iterable<BacktestMember> members) => [
  for (final m in members)
    if (m.nextScore != null) m.nextScore!,
];

Map<String, Object?> _evaluate(
  List<ReferenceComparisonGroup> groups,
  ReferenceMethod method, {
  required int bootstrapRounds,
}) {
  final gaps = <String, List<double>>{};
  final chosen = <double>[], comparedPool = <double>[];
  var selected = 0, evaluable = 0, selectedGroups = 0, evaluableGroups = 0;
  for (final g in groups) {
    final picks = g.picks(method);
    selected += picks.length;
    if (picks.isNotEmpty) selectedGroups++;
    final scores = _scores(picks);
    evaluable += scores.length;
    final pool = _scores(g.baseline.members);
    if (scores.isEmpty || pool.isEmpty) continue;
    evaluableGroups++;
    chosen.addAll(scores);
    comparedPool.addAll(pool);
    gaps
        .putIfAbsent(g.baseline.day, () => [])
        .add(_mean(scores)! - _mean(pool)!);
  }
  return {
    'groups_total': groups.length,
    'groups_with_selection': selectedGroups,
    'selection_group_rate': groups.isEmpty
        ? null
        : _rounded(selectedGroups / groups.length),
    'no_selection_groups': groups.length - selectedGroups,
    'selected_but_unscored_groups': selectedGroups - evaluableGroups,
    'groups_evaluable': evaluableGroups,
    'evaluable_group_rate': groups.isEmpty
        ? null
        : _rounded(evaluableGroups / groups.length),
    'selected': selected,
    'evaluable': evaluable,
    'evaluable_rate': selected == 0 ? null : _rounded(evaluable / selected),
    'selected_without_label': selected - evaluable,
    // Pooled rack averages are descriptive; the primary gap is mean_of_days.
    'chosen_mean_pooled': _rounded(_mean(chosen)),
    'pool_mean_in_evaluable_groups_pooled': _rounded(_mean(comparedPool)),
    'chosen_p60': chosen.isEmpty
        ? null
        : _rounded(chosen.where((v) => v >= 60).length / chosen.length),
    'gap_vs_fixed_pool': referenceDaySummary(
      gaps,
      bootstrapRounds: bootstrapRounds,
    ),
  };
}

Map<String, Object?> _paired(
  List<ReferenceComparisonGroup> groups,
  ReferenceMethod method, {
  required int bootstrapRounds,
}) {
  final byDay = <String, List<double>>{};
  var commonGroups = 0;
  for (final g in groups) {
    final current = _scores(g.picks(ReferenceMethod.current));
    final other = _scores(g.picks(method));
    if (current.isEmpty || other.isEmpty) continue;
    commonGroups++;
    byDay
        .putIfAbsent(g.baseline.day, () => [])
        .add(_mean(other)! - _mean(current)!);
  }
  return {
    'common_evaluable_groups': commonGroups,
    ...referenceDaySummary(byDay, bootstrapRounds: bootstrapRounds),
  };
}

/// Fraction of today's selected racks also selected on the preceding calendar
/// day. Only pairs where both days have a baseline group enter the denominator.
/// A no-selection preceding day contributes zero reused racks; a no-selection
/// current day contributes zero selected racks, not a fabricated success/fail.
Map<String, Object?> referenceRepeatRate(
  List<ReferenceComparisonGroup> groups,
  ReferenceMethod method,
) {
  final lookup = {
    for (final g in groups)
      '${g.baseline.store}|${g.baseline.machine}|${g.baseline.day}': g,
  };
  var adjacentPairs = 0, denominator = 0, repeated = 0, bothSelectedPairs = 0;
  final byDay = <String, ({int selected, int repeated})>{};
  for (final g in groups) {
    final b = g.baseline;
    final previous = lookup['${b.store}|${b.machine}|${shiftDay(b.day, -1)}'];
    if (previous == null) continue;
    adjacentPairs++;
    final now = g.selected[method]!, before = previous.selected[method]!;
    if (now.isNotEmpty && before.isNotEmpty) bothSelectedPairs++;
    final reused = now.intersection(before).length;
    denominator += now.length;
    repeated += reused;
    final day = byDay[b.day] ?? (selected: 0, repeated: 0);
    byDay[b.day] = (
      selected: day.selected + now.length,
      repeated: day.repeated + reused,
    );
  }
  return {
    'definition': "Today's selected racks also selected on the previous calendar day / today's selected racks, on adjacent baseline group pairs. This differs from previous-day retention; do not compare directly with earlier diagnostic retention rates.",
    'adjacent_baseline_group_pairs': adjacentPairs,
    'both_days_selected_group_pairs': bothSelectedPairs,
    'current_selected_on_adjacent_pairs': denominator,
    'repeated_racks': repeated,
    'repeat_rate': denominator == 0 ? null : _rounded(repeated / denominator),
    'by_day': {
      for (final day in byDay.keys.toList()..sort())
        day: {
          'selected': byDay[day]!.selected,
          'repeated': byDay[day]!.repeated,
          'rate': byDay[day]!.selected == 0
              ? null
              : _rounded(byDay[day]!.repeated / byDay[day]!.selected),
        },
    },
  };
}

Map<String, Object?> summarizeReferenceComparison(
  List<ReferenceComparisonGroup> groups, {
  int bootstrapRounds = 10000,
}) {
  Map<String, Object?> part(List<ReferenceComparisonGroup> subset) {
    final population = [for (final g in subset) ...g.baseline.members];
    return {
      'fixed_population': {
        'groups': subset.length,
        'prediction_days': {for (final g in subset) g.baseline.day}.length,
        'eligible_racks': population.length,
        'labeled_racks': _scores(population).length,
        'pool_mean_pooled': _rounded(_mean(_scores(population))),
      },
      'methods': {
        for (final method in ReferenceMethod.values)
          method.name: {
            ..._evaluate(subset, method, bootstrapRounds: bootstrapRounds),
            'minus_current_on_common_evaluable_groups': _paired(
              subset,
              method,
              bootstrapRounds: bootstrapRounds,
            ),
            'current_on_groups_with_method_selection': _evaluate(
              [
                for (final g in subset)
                  if (g.picks(method).isNotEmpty) g,
              ],
              ReferenceMethod.current,
              bootstrapRounds: bootstrapRounds,
            ),
            'current_on_method_evaluable_groups': _evaluate(
              [
                for (final g in subset)
                  if (_scores(g.picks(method)).isNotEmpty) g,
              ],
              ReferenceMethod.current,
              bootstrapRounds: bootstrapRounds,
            ),
            'current_on_common_evaluable_groups': _evaluate(
              [
                for (final g in subset)
                  if (_scores(g.picks(method)).isNotEmpty &&
                      _scores(g.picks(ReferenceMethod.current)).isNotEmpty)
                    g,
              ],
              ReferenceMethod.current,
              bootstrapRounds: bootstrapRounds,
            ),
            'consecutive_repeat': referenceRepeatRate(subset, method),
          },
      },
    };
  }

  return {
    'all': part(groups),
    'by_store': {
      for (final store in storeNames.keys)
        store: part(groups.where((g) => g.baseline.store == store).toList()),
    },
  };
}
