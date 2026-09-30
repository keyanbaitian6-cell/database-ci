import 'models.dart';
import 'next_day_backtest.dart';
import 'reference_candidate_comparison.dart';
import 'scoring.dart';

/// Offline exploration only; never used by app selection or snapshot storage.
enum LowActivityMethod { current, lowScore, lowGames, blend }

typedef ThreeDayFeature = ({double? games, double? score, int scoredDays});

ThreeDayFeature threeDayFeature(SlotRecord target, List<SlotRecord> available) {
  final rows = <SlotRecord>[];
  for (var age = 0; age < 3; age++) {
    final day = shiftDay(target.day, -age);
    final matches = available
        .where(
          (r) =>
              r.store == target.store &&
              r.machine == target.machine &&
              r.rack == target.rack &&
              r.day == day,
        )
        .toList();
    if (matches.length != 1 ||
        matches.single.games < 0 ||
        matches.single.bb < 0 ||
        matches.single.rb < 0 ||
        (matches.single.maxHold ?? 0) < 0 ||
        hasImplausibleNumbers(matches.single)) {
      return (games: null, score: null, scoredDays: 0);
    }
    rows.add(matches.single);
  }
  final scores = <double>[
    for (final row in rows)
      if (scoreRecord(row, available).total case final double score) score,
  ];
  return (
    games: rows.fold<double>(0, (sum, r) => sum + r.games) / 3,
    score: scores.length < 2 ? null : _mean(scores),
    scoredDays: scores.length,
  );
}

class LowActivityGroup {
  LowActivityGroup(this.baseline, this.features, this.selected);
  final BacktestGroup baseline;
  final Map<BacktestMember, ThreeDayFeature> features;
  final Map<LowActivityMethod, Set<BacktestMember>> selected;
}

/// Exposed for deterministic tests. Selection is bounded by baseline k.
LowActivityGroup selectLowActivity(
  BacktestGroup baseline,
  Map<BacktestMember, ThreeDayFeature> features,
) {
  final both = baseline.members
      .where((m) => features[m]!.score != null && features[m]!.games != null)
      .toList();
  final scores = [for (final m in both) features[m]!.score!];
  final games = [for (final m in both) features[m]!.games!];
  double blend(BacktestMember m) =>
      (2 -
          percentile(features[m]!.score!, scores) -
          percentile(features[m]!.games!, games)) /
      2;
  Set<BacktestMember> order(
    Iterable<BacktestMember> members,
    double Function(BacktestMember) value,
  ) {
    final sorted = members.toList()
      ..sort((a, b) {
        final comparison = value(a).compareTo(value(b));
        if (comparison != 0) return comparison;
        final rack = a.rack.compareTo(b.rack);
        return rack != 0 ? rack : a.machine.compareTo(b.machine);
      });
    return sorted.take(baseline.count).toSet();
  }

  return LowActivityGroup(baseline, features, {
    LowActivityMethod.current: baseline.members.where((m) => m.current).toSet(),
    LowActivityMethod.lowScore: order(
      baseline.members.where((m) => features[m]!.score != null),
      (m) => features[m]!.score!,
    ),
    LowActivityMethod.lowGames: order(
      baseline.members.where((m) => features[m]!.games != null),
      (m) => features[m]!.games!,
    ),
    LowActivityMethod.blend: order(both, (m) => -blend(m)),
  });
}

List<LowActivityGroup> buildLowActivityComparison(List<SlotRecord> full) {
  if (scoringVersion != referenceScoringVersion) {
    throw StateError('Protocol requires $referenceScoringVersion');
  }
  final run = runBacktest(full, variety: true, cutoffFor: predictionCutoff);
  final result = <LowActivityGroup>[];
  final availability = <String, List<SlotRecord>>{};
  for (final g in [...run.groups, ...run.varietyGroups]) {
    final available = availability.putIfAbsent(
      g.day,
      () => availableRecords(full, g.day, cutoff: predictionCutoff(g.day)),
    );
    final byKey = {for (final r in available) r.key: r};
    final features = <BacktestMember, ThreeDayFeature>{};
    for (final member in g.members) {
      final target =
          byKey['${g.store}|${g.day}|${member.machine}|${member.rack}'];
      if (target == null) throw StateError('Baseline member not available');
      features[member] = threeDayFeature(target, available);
    }
    result.add(selectLowActivity(g, features));
  }
  return result;
}

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

double? _round(double? v) =>
    v == null ? null : double.parse(v.toStringAsFixed(4));
List<double> _scores(Iterable<BacktestMember> rows) => [
  for (final r in rows)
    if (r.nextScore != null) r.nextScore!,
];

Map<String, Object?> _evaluate(
  List<LowActivityGroup> groups,
  LowActivityMethod method,
) {
  var selected = 0, labeled = 0, selectedGroups = 0, evaluableGroups = 0;
  final byDay = <String, List<double>>{};
  final allChosen = <double>[], allPool = <double>[];
  for (final g in groups) {
    final picks = g.selected[method]!;
    selected += picks.length;
    if (picks.isNotEmpty) selectedGroups++;
    final chosen = _scores(picks), pool = _scores(g.baseline.members);
    labeled += chosen.length;
    if (chosen.isEmpty || pool.isEmpty) continue;
    evaluableGroups++;
    allChosen.addAll(chosen);
    allPool.addAll(pool);
    byDay
        .putIfAbsent(g.baseline.day, () => [])
        .add(_mean(chosen)! - _mean(pool)!);
  }
  return {
    'groups_total': groups.length,
    'groups_with_selection': selectedGroups,
    'no_selection_groups': groups.length - selectedGroups,
    'selected_but_unscored_groups': selectedGroups - evaluableGroups,
    'groups_evaluable': evaluableGroups,
    'selection_group_rate': groups.isEmpty
        ? null
        : _round(selectedGroups / groups.length),
    'evaluable_group_rate': groups.isEmpty
        ? null
        : _round(evaluableGroups / groups.length),
    'selected': selected,
    'evaluable': labeled,
    'selected_without_label': selected - labeled,
    'evaluable_rate': selected == 0 ? null : _round(labeled / selected),
    'chosen_mean_pooled': _round(_mean(allChosen)),
    'pool_mean_in_evaluable_groups_pooled': _round(_mean(allPool)),
    'chosen_p60': allChosen.isEmpty
        ? null
        : _round(allChosen.where((s) => s >= 60).length / allChosen.length),
    'gap_vs_fixed_pool': referenceDaySummary(byDay),
  };
}

Map<String, Object?> _paired(
  List<LowActivityGroup> groups,
  LowActivityMethod method,
) {
  final byDay = <String, List<double>>{};
  var common = 0;
  for (final g in groups) {
    final a = _scores(g.selected[method]!);
    final b = _scores(g.selected[LowActivityMethod.current]!);
    if (a.isEmpty || b.isEmpty) continue;
    common++;
    byDay.putIfAbsent(g.baseline.day, () => []).add(_mean(a)! - _mean(b)!);
  }
  return {'common_evaluable_groups': common, ...referenceDaySummary(byDay)};
}

Map<String, Object?> lowActivityRepeatRate(
  List<LowActivityGroup> groups,
  LowActivityMethod method,
) {
  final lookup = {
    for (final g in groups)
      '${g.baseline.store}|${g.baseline.machine}|${g.baseline.day}': g,
  };
  String id(BacktestMember m) => '${m.machine}|${m.rack}';
  var pairs = 0, denominator = 0, repeated = 0;
  for (final g in groups) {
    final b = g.baseline;
    final previous = lookup['${b.store}|${b.machine}|${shiftDay(b.day, -1)}'];
    if (previous == null) continue;
    pairs++;
    final before = previous.selected[method]!.map(id).toSet();
    final now = g.selected[method]!.map(id).toSet();
    denominator += now.length;
    repeated += before.intersection(now).length;
  }
  return {
    'adjacent_baseline_group_pairs': pairs,
    'current_selected_on_adjacent_pairs': denominator,
    'repeated_racks': repeated,
    'repeat_rate': denominator == 0 ? null : _round(repeated / denominator),
  };
}

Map<String, Object?> summarizeLowActivityComparison(
  List<LowActivityGroup> groups,
) {
  Map<String, Object?> part(List<LowActivityGroup> subset) {
    final members = [for (final g in subset) ...g.baseline.members];
    final features = [for (final g in subset) ...g.features.values];
    return {
      'fixed_population': {
        'groups': subset.length,
        'prediction_days': {for (final g in subset) g.baseline.day}.length,
        'eligible_racks': members.length,
        'labeled_racks': _scores(members).length,
      },
      'missing_features': {
        'three_day_games': features.where((f) => f.games == null).length,
        'three_day_score': features.where((f) => f.score == null).length,
        'either_feature': features
            .where((f) => f.games == null || f.score == null)
            .length,
      },
      'methods': {
        for (final method in LowActivityMethod.values)
          method.name: {
            ..._evaluate(subset, method),
            'minus_current_on_common_evaluable_groups': _paired(subset, method),
            'current_on_groups_with_method_selection': _evaluate(
              subset.where((g) => g.selected[method]!.isNotEmpty).toList(),
              LowActivityMethod.current,
            ),
            'current_on_common_evaluable_groups': _evaluate(
              subset
                  .where(
                    (g) =>
                        _scores(g.selected[method]!).isNotEmpty &&
                        _scores(g.selected[LowActivityMethod.current]!)
                            .isNotEmpty,
                  )
                  .toList(),
              LowActivityMethod.current,
            ),
            'consecutive_repeat': lowActivityRepeatRate(subset, method),
          },
      },
    };
  }

  return {
    'all': part(groups),
    'normal': part(groups.where((g) => !g.baseline.variety).toList()),
    'variety': part(groups.where((g) => g.baseline.variety).toList()),
    'by_store': {
      for (final store in storeNames.keys)
        store: {
          'all': part(groups.where((g) => g.baseline.store == store).toList()),
          'normal': part(
            groups
                .where((g) => g.baseline.store == store && !g.baseline.variety)
                .toList(),
          ),
          'variety': part(
            groups
                .where((g) => g.baseline.store == store && g.baseline.variety)
                .toList(),
          ),
        },
    },
  };
}
