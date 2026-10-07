import 'dart:math';

import 'candidate_log.dart';
import 'data_checks.dart';
import 'focus_validation.dart';
import 'models.dart';
import 'next_day_backtest.dart';
import 'scoring.dart';

/// 未来の固定期間（予測日2026-09-30〜10-29）の集計。分析専用で、画面の★・
/// 採点・保存済みの候補には何も書かない。条件は
/// `NEXT_DAY_FOCUS_PLAN_20260930.md` の「5. 最終評価の集計」（2026-10-07、
/// 期間の結果を見る前に固定）。

const focusFinalBootstrapRounds = 10000;
const focusFinalBootstrapSeed = 20261007;
const focusFinalMinimumDays = 20;
const focusFinalMainBlockDays = 5;
const focusFinalSensitivityBlockDays = 10;

/// 移動ブロックの区間を判断に使うには、予測日数 ÷ ブロック日数が4以上。
const focusFinalMinimumBlocks = 4;

/// 評価できる割合の悪化として許すのは2ポイントまで（設計上の値。根拠となる
/// 外部の基準は無い）。
const focusFinalCoverageTolerance = 0.02;

enum FocusMethod { current, primary }

Set<int> focusPicks(FocusValidationGroup g, FocusMethod method) =>
    switch (method) {
      FocusMethod.current => {
        for (final m in g.baseline.members)
          if (m.current) m.rack,
      },
      FocusMethod.primary => g.primary,
    };

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

double? _r(double? value) =>
    value == null ? null : double.parse(value.toStringAsFixed(4));

List<double>? _ci(({double low, double high})? ci) =>
    ci == null ? null : [_r(ci.low)!, _r(ci.high)!];

List<double> _scores(Iterable<BacktestMember> members) => [
  for (final m in members)
    if (m.nextScore != null) m.nextScore!,
];

/// 連続する予測日の移動ブロック・ブートストラップ（重なりのあるブロック）。
/// [values] は予測日の順（評価できない日は詰める）。長さ [block] のブロックを
/// 復元抽出して n 日分つなぎ、その平均の2.5%・97.5%点を返す。区間の位置は
/// [dayBootstrap] と同じ数え方。ブロックが2つ分に満たなければ null。
({double low, double high})? movingBlockBootstrap(
  List<double> values,
  int block, {
  int rounds = focusFinalBootstrapRounds,
  int seed = focusFinalBootstrapSeed,
}) {
  final n = values.length;
  if (block < 1 || n < 2 * block) return null;
  final rng = Random(seed);
  final starts = n - block + 1;
  final means = <double>[];
  for (var i = 0; i < rounds; i++) {
    var sum = 0.0, taken = 0;
    while (taken < n) {
      final start = rng.nextInt(starts);
      for (var j = 0; j < block && taken < n; j++) {
        sum += values[start + j];
        taken++;
      }
    }
    means.add(sum / n);
  }
  means.sort();
  return (
    low: means[(rounds * 0.025).floor()],
    high: means[(rounds * 0.975).floor() - 1],
  );
}

/// 隣り合う予測日（評価できた日の並び）の差の自己相関。
double? lag1Autocorrelation(List<double> values) {
  if (values.length < 3) return null;
  final m = _mean(values)!;
  var num = 0.0, den = 0.0;
  for (var i = 0; i < values.length; i++) {
    den += (values[i] - m) * (values[i] - m);
    if (i + 1 < values.length) num += (values[i] - m) * (values[i + 1] - m);
  }
  return den == 0 ? null : num / den;
}

/// 予測日ごとの値（その日のグループを同じ重みで平均）と、その区間。
class FocusDaySeries {
  FocusDaySeries(Map<String, List<double>> byDay)
    : days = byDay.keys.toList()..sort(),
      _byDay = byDay {
    values = [for (final day in days) _mean(byDay[day]!)!];
    final day = dayBootstrap(
      values,
      rounds: focusFinalBootstrapRounds,
      seed: focusFinalBootstrapSeed,
    );
    dayCi = day == null ? null : (low: day.$1, high: day.$2);
    mainBlock = movingBlockBootstrap(values, focusFinalMainBlockDays);
    sensitivityBlock = movingBlockBootstrap(
      values,
      focusFinalSensitivityBlockDays,
    );
  }

  final List<String> days;
  final Map<String, List<double>> _byDay;
  late final List<double> values;
  late final ({double low, double high})? dayCi, mainBlock, sensitivityBlock;

  double? get mean => _mean(values);
  int blocks(int length) => values.length ~/ length;
  bool get mainBlockSufficient =>
      blocks(focusFinalMainBlockDays) >= focusFinalMinimumBlocks;

  Map<String, Object?> toJson({bool withBlocks = false}) => {
    'days': values.length,
    'mean_of_days': _r(mean),
    'median_of_days': _r(_median(values)),
    'min_day_mean': values.isEmpty ? null : _r(values.reduce(min)),
    'max_day_mean': values.isEmpty ? null : _r(values.reduce(max)),
    'positive_days': values.where((v) => v > 0).length,
    'ci95_day_bootstrap': _ci(dayCi),
    if (withBlocks) ...{
      'ci95_moving_block_5': {
        'blocks': blocks(focusFinalMainBlockDays),
        'sufficient': mainBlockSufficient,
        'ci95': _ci(mainBlock),
      },
      'ci95_moving_block_10_sensitivity': {
        'blocks': blocks(focusFinalSensitivityBlockDays),
        'sufficient':
            blocks(focusFinalSensitivityBlockDays) >= focusFinalMinimumBlocks,
        'ci95': _ci(sensitivityBlock),
      },
      'lag1_autocorrelation': _r(lag1Autocorrelation(values)),
    },
    'by_day': {
      for (var i = 0; i < days.length; i++)
        days[i]: {'groups': _byDay[days[i]]!.length, 'mean': _r(values[i])},
    },
  };
}

typedef FocusCoverage = ({
  int groups,
  int withSelection,
  int reduced,
  int evaluableGroups,
  int selected,
  int evaluable,
});

FocusCoverage focusCoverage(
  List<FocusValidationGroup> groups,
  FocusMethod method,
) {
  var withSelection = 0, reduced = 0, evaluableGroups = 0;
  var selected = 0, evaluable = 0;
  for (final g in groups) {
    final picks = focusPicks(g, method);
    final scored = _scores(
      g.baseline.members.where((m) => picks.contains(m.rack)),
    );
    if (picks.isNotEmpty) withSelection++;
    if (picks.length < g.baseline.count) reduced++;
    selected += picks.length;
    evaluable += scored.length;
    if (scored.isNotEmpty && _scores(g.baseline.members).isNotEmpty) {
      evaluableGroups++;
    }
  }
  return (
    groups: groups.length,
    withSelection: withSelection,
    reduced: reduced,
    evaluableGroups: evaluableGroups,
    selected: selected,
    evaluable: evaluable,
  );
}

double? _rate(int part, int whole) => whole == 0 ? null : part / whole;

/// 選んだ台の翌日の平均 − 判定できた台全体の翌日の平均（グループごと）。
FocusDaySeries focusGapVsPool(
  List<FocusValidationGroup> groups,
  FocusMethod method,
) {
  final byDay = <String, List<double>>{};
  for (final g in groups) {
    final picks = focusPicks(g, method);
    final scored = _scores(
      g.baseline.members.where((m) => picks.contains(m.rack)),
    );
    final pool = _scores(g.baseline.members);
    if (scored.isEmpty || pool.isEmpty) continue;
    byDay
        .putIfAbsent(g.baseline.day, () => [])
        .add(_mean(scored)! - _mean(pool)!);
  }
  return FocusDaySeries(byDay);
}

/// 主方式 − 現行（どちらも翌日に採点できた台が1台以上あるグループだけ）。
FocusDaySeries focusDirectDifference(List<FocusValidationGroup> groups) {
  final byDay = <String, List<double>>{};
  for (final g in groups) {
    double? meanOf(FocusMethod method) {
      final picks = focusPicks(g, method);
      return _mean(
        _scores(g.baseline.members.where((m) => picks.contains(m.rack))),
      );
    }

    final primary = meanOf(FocusMethod.primary);
    final current = meanOf(FocusMethod.current);
    if (primary == null || current == null) continue;
    byDay.putIfAbsent(g.baseline.day, () => []).add(primary - current);
  }
  return FocusDaySeries(byDay);
}

Map<String, Object?> _coverageJson(FocusCoverage c) => {
  'groups_total': c.groups,
  'groups_with_selection': c.withSelection,
  'no_selection_groups': c.groups - c.withSelection,
  'reduced_groups': c.reduced,
  'groups_evaluable': c.evaluableGroups,
  'evaluable_group_rate': _r(_rate(c.evaluableGroups, c.groups)),
  'selected': c.selected,
  'evaluable': c.evaluable,
  'evaluable_rate': _r(_rate(c.evaluable, c.selected)),
};

/// 両方式の成績と直接差（中間でも最終でも同じ計算）。採否の判定は含めない。
Map<String, Object?> focusOutcomeSummary(List<FocusValidationGroup> groups) {
  Map<String, Object?> part(List<FocusValidationGroup> subset) => {
    'groups': subset.length,
    'prediction_days': {for (final g in subset) g.baseline.day}.length,
    'methods': {
      for (final method in FocusMethod.values)
        method.name: {
          ..._coverageJson(focusCoverage(subset, method)),
          'gap_vs_pool': focusGapVsPool(subset, method).toJson(),
        },
    },
    'primary_minus_current': focusDirectDifference(subset)
        .toJson(withBlocks: true),
  };

  return {
    'all': part(groups),
    'by_store': {
      for (final store in storeNames.keys)
        store: part(groups.where((g) => g.baseline.store == store).toList()),
    },
  };
}

/// 事前に固定した採用条件。すべて満たしたときだけ adopt が true。
Map<String, Object?> focusAdoptionJudgment(List<FocusValidationGroup> groups) {
  final direct = focusDirectDifference(groups);
  final storeMeans = {
    for (final store in storeNames.keys)
      store: focusDirectDifference(
        groups.where((g) => g.baseline.store == store).toList(),
      ).mean,
  };
  final current = focusCoverage(groups, FocusMethod.current);
  final primary = focusCoverage(groups, FocusMethod.primary);
  bool notWorse(double? a, double? b) =>
      a != null && b != null && a - b >= -focusFinalCoverageTolerance;
  final conditions = {
    'evaluable_days_at_least_20': direct.values.length >= focusFinalMinimumDays,
    'both_stores_direct_difference_positive': storeMeans.values.every(
      (v) => v != null && v > 0,
    ),
    'day_bootstrap_ci95_above_zero':
        direct.dayCi != null && direct.dayCi!.low > 0,
    'moving_block_5_sufficient_blocks': direct.mainBlockSufficient,
    'moving_block_5_ci95_above_zero':
        direct.mainBlockSufficient &&
        direct.mainBlock != null &&
        direct.mainBlock!.low > 0,
    'evaluable_group_rate_not_worse_than_2pt': notWorse(
      _rate(primary.evaluableGroups, primary.groups),
      _rate(current.evaluableGroups, current.groups),
    ),
    'evaluable_pick_rate_not_worse_than_2pt': notWorse(
      _rate(primary.evaluable, primary.selected),
      _rate(current.evaluable, current.selected),
    ),
  };
  return {
    'conditions': conditions,
    'adopt': conditions.values.every((v) => v),
    'store_direct_difference': {
      for (final e in storeMeans.entries) e.key: _r(e.value),
    },
    // 判定には使わない：10日ブロックの感度確認、日間の自己相関。
    'sensitivity_moving_block_10': {
      'blocks': direct.blocks(focusFinalSensitivityBlockDays),
      'ci95': _ci(direct.sensitivityBlock),
    },
    'lag1_autocorrelation': _r(lag1Autocorrelation(direct.values)),
  };
}

/// 最終評価を実行できない理由（実行できるなら null）。[now] は今の時刻。
String? focusFinalBlocker(
  DateTime now,
  List<SlotRecord> full, {
  bool lastLabelDayMissingOk = false,
}) {
  final today = now
      .toUtc()
      .add(const Duration(hours: 9))
      .toIso8601String()
      .substring(0, 10);
  if (today.compareTo(focusValidationFinalOn) < 0) {
    return '最終評価日（$focusValidationFinalOn）より前です（日本時間 $today）';
  }
  final labelDay = shiftDay(focusValidationThrough, 1);
  if (!lastLabelDayMissingOk) {
    for (final store in storeNames.keys) {
      if (!full.any((r) => r.store == store && r.day == labelDay)) {
        return '$labelDay（最後の予測日の翌日）の記録が無い店舗があります：$store';
      }
    }
  }
  return null;
}

// ---- 結果を使わない集計（進捗・データ品質・選び方の性質） ----

/// 取得時刻を、記録の日付Dに対する区分に分ける（日本時間）。
String captureBucket(SlotRecord r) {
  final at = readJst(r.capturedAt);
  if (at == null) return 'missing';
  final d = DateTime.parse(r.day);
  final start = DateTime.utc(
    d.year,
    d.month,
    d.day,
  ).subtract(const Duration(hours: 9));
  final hours = at.difference(start).inMinutes / 60;
  if (hours < 0) return 'before_day';
  if (hours < 22) return 'day_00_22';
  if (hours < 24) return 'day_22_24';
  if (hours < 26) return 'next_00_02';
  return 'next_02_later';
}

const captureBuckets = [
  'missing',
  'before_day',
  'day_00_22',
  'day_22_24',
  'next_00_02',
  'next_02_later',
];

/// 店舗・日ごとの記録数と取得時刻の区分。[from] 以降の日だけ。
Map<String, Object?> focusRecordQuality(
  List<SlotRecord> full, {
  String from = '2026-09-29',
}) {
  final result = <String, Object?>{};
  for (final store in storeNames.keys) {
    final byDay = <String, Map<String, int>>{};
    var firstAfterLast = 0;
    for (final r in full) {
      if (r.store != store || r.day.compareTo(from) < 0) continue;
      final row = byDay.putIfAbsent(
        r.day,
        () => {'records': 0, for (final b in captureBuckets) b: 0},
      );
      row['records'] = row['records']! + 1;
      final bucket = captureBucket(r);
      row[bucket] = row[bucket]! + 1;
      final first = readJst(r.firstCapturedAt), last = readJst(r.capturedAt);
      if (first != null && last != null && first.isAfter(last)) {
        firstAfterLast++;
      }
    }
    result[store] = {
      'first_captured_after_captured': firstAfterLast,
      'by_day': {
        for (final day in byDay.keys.toList()..sort()) day: byDay[day],
      },
    };
  }
  return result;
}

/// 固定期間の店舗・予測日ごとの進捗（翌日の点数そのものは出さない）。
Map<String, Object?> focusProgress(
  List<FocusValidationGroup> groups,
  List<SlotRecord> full,
) {
  final keys = {for (final r in full) r.key};
  final recordDays = <String, Set<String>>{};
  final beforeCutoff = <String, Set<String>>{};
  for (final r in full) {
    recordDays.putIfAbsent(r.store, () => {}).add(r.day);
    final at = readJst(r.capturedAt);
    if (at != null && at.isBefore(predictionCutoff(r.day))) {
      beforeCutoff.putIfAbsent(r.store, () => {}).add(r.day);
    }
  }
  final result = <String, Object?>{};
  for (final store in storeNames.keys) {
    final days = <String, Object?>{};
    var evaluableDays = 0;
    for (
      var day = focusValidationFrom;
      day.compareTo(focusValidationThrough) <= 0;
      day = shiftDay(day, 1)
    ) {
      final dayGroups = [
        for (final g in groups)
          if (g.baseline.store == store && g.baseline.day == day) g,
      ];
      final members = [for (final g in dayGroups) ...g.baseline.members];
      var noRecord = 0, notScored = 0;
      for (final g in dayGroups) {
        for (final m in g.baseline.members) {
          if (m.nextScore != null) continue;
          final next =
              '$store|${shiftDay(day, 1)}|${g.baseline.machine}|${m.rack}';
          keys.contains(next) ? notScored++ : noRecord++;
        }
      }
      final labeled = _scores(members).length;
      final common = dayGroups.where((g) {
        bool has(FocusMethod method) {
          final picks = focusPicks(g, method);
          return g.baseline.members.any(
            (m) => picks.contains(m.rack) && m.nextScore != null,
          );
        }

        return has(FocusMethod.current) && has(FocusMethod.primary);
      }).length;
      if (common > 0) evaluableDays++;
      String status;
      if (!(recordDays[store]?.contains(day) ?? false)) {
        status = 'no_records_for_day';
      } else if (!(beforeCutoff[store]?.contains(day) ?? false)) {
        status = 'no_records_before_cutoff';
      } else if (!(recordDays[store]?.contains(shiftDay(day, 1)) ?? false)) {
        status = dayGroups.isEmpty ? 'no_groups' : 'next_day_not_recorded';
      } else if (dayGroups.isEmpty) {
        status = 'no_groups';
      } else {
        status = common > 0 ? 'evaluable' : 'no_common_evaluable_group';
      }
      days[day] = {
        'status': status,
        'groups': dayGroups.length,
        'eligible_racks': members.length,
        'labeled_racks': labeled,
        'unlabeled_no_record': noRecord,
        'unlabeled_not_scored': notScored,
        'current_selected': dayGroups.fold<int>(
          0,
          (n, g) => n + focusPicks(g, FocusMethod.current).length,
        ),
        'primary_selected': dayGroups.fold<int>(
          0,
          (n, g) => n + g.primary.length,
        ),
        'primary_reduced_groups': dayGroups
            .where((g) => g.primary.length < g.baseline.count)
            .length,
        'primary_no_selection_groups': dayGroups
            .where((g) => g.primary.isEmpty)
            .length,
        'common_evaluable_groups': common,
      };
    }
    result[store] = {'evaluable_days': evaluableDays, 'by_day': days};
  }
  final allDays = {
    for (final g in groups)
      if (g.baseline.members.any((m) => m.nextScore != null)) g.baseline.day,
  };
  return {
    'fixed_period': [focusValidationFrom, focusValidationThrough],
    'prediction_days_with_labeled_groups': allDays.length,
    'by_store': result,
  };
}

/// 保存済みの候補（画面に出た★の記録）の店舗・日ごとの件数。
Map<String, Object?> focusSnapshotProgress(List<CandidateSnapshot> snapshots) {
  final result = <String, Map<String, Map<String, int>>>{};
  for (final s in snapshots) {
    if (s.day.compareTo(focusValidationFrom) < 0 ||
        s.day.compareTo(focusValidationThrough) > 0) {
      continue;
    }
    final at = readJst(s.takenAt);
    final row = result
        .putIfAbsent(s.store, () => {})
        .putIfAbsent(
          s.day,
          () => {'before_cutoff': 0, 'after_cutoff': 0, 'other_method': 0},
        );
    if (s.method != nextDayMethodVersion) {
      row['other_method'] = row['other_method']! + 1;
    } else if (at != null && at.isBefore(predictionCutoff(s.day))) {
      row['before_cutoff'] = row['before_cutoff']! + 1;
    } else {
      row['after_cutoff'] = row['after_cutoff']! + 1;
    }
  }
  return {
    for (final store in result.keys.toList()..sort())
      store: {
        for (final day in result[store]!.keys.toList()..sort())
          day: result[store]![day],
      },
  };
}

/// 選び方の性質：当日の点数が高い台をどれだけ選んでいるか（翌日の結果は使わない）。
Map<String, Object?> focusSelectionProfile(List<FocusValidationGroup> groups) {
  Map<String, Object?> profile(Set<int> Function(FocusValidationGroup) pick) {
    var picked = 0, inTopToday = 0, high = 0, withScore = 0;
    var expectedTop = 0.0;
    final percentiles = <double>[];
    var eligible = 0, eligibleHigh = 0;
    for (final g in groups) {
      final picks = pick(g);
      final members = g.baseline.members;
      final scores = [
        for (final m in members)
          if (m.todayScore != null) m.todayScore!,
      ];
      final top = members.where((m) => m.previousScore).length;
      for (final m in members) {
        if (m.todayScore != null) {
          eligible++;
          if (m.todayScore! >= 80) eligibleHigh++;
        }
        if (!picks.contains(m.rack)) continue;
        picked++;
        expectedTop += members.isEmpty ? 0 : top / members.length;
        if (m.previousScore) inTopToday++;
        if (m.todayScore == null) continue;
        withScore++;
        if (m.todayScore! >= 80) high++;
        percentiles.add(percentile(m.todayScore!, scores));
      }
    }
    return {
      'picked': picked,
      'share_in_today_top_k': _r(_rate(inTopToday, picked)),
      'random_expectation_in_today_top_k': _r(
        picked == 0 ? null : expectedTop / picked,
      ),
      'share_today_80_or_more': _r(_rate(high, withScore)),
      'eligible_share_today_80_or_more': _r(_rate(eligibleHigh, eligible)),
      'mean_today_percentile_within_group': _r(_mean(percentiles)),
    };
  }

  Map<String, Object?> repeat(Set<int> Function(FocusValidationGroup) pick) {
    final lookup = {
      for (final g in groups)
        '${g.baseline.store}|${g.baseline.machine}|${g.baseline.day}': g,
    };
    var selected = 0, repeated = 0;
    for (final g in groups) {
      final b = g.baseline;
      final previous = lookup['${b.store}|${b.machine}|${shiftDay(b.day, -1)}'];
      if (previous == null) continue;
      final now = pick(g);
      selected += now.length;
      repeated += now.intersection(pick(previous)).length;
    }
    return {
      'selected_on_adjacent_pairs': selected,
      'also_selected_previous_day': repeated,
      'repeat_rate': _r(_rate(repeated, selected)),
    };
  }

  final pickers = <String, Set<int> Function(FocusValidationGroup)>{
    'current_all_stars': (g) => focusPicks(g, FocusMethod.current),
    'current_focus_star': (g) => g.focus,
    'current_long_trend': (g) => g.longTrend,
    'primary': (g) => g.primary,
  };
  final within = <double>[];
  for (final g in groups) {
    final pairs = [
      for (final m in g.baseline.members)
        if (m.todayScore != null) (m.index, m.todayScore!),
    ];
    final rho = spearmanRank(pairs);
    if (rho != null) within.add(rho);
  }
  return {
    for (final e in pickers.entries)
      e.key: {...profile(e.value), 'consecutive': repeat(e.value)},
    'index_vs_today_score_spearman_within_group_mean': _r(_mean(within)),
    'groups_with_correlation': within.length,
  };
}

/// 順位相関（同順位は平均順位）。4組未満、または片方が一定なら null。
double? spearmanRank(List<(double, double)> pairs) {
  if (pairs.length < 4) return null;
  List<double> ranks(List<double> v) {
    final order = List<int>.generate(v.length, (i) => i)
      ..sort((a, b) => v[a].compareTo(v[b]));
    final r = List<double>.filled(v.length, 0);
    var i = 0;
    while (i < order.length) {
      var j = i;
      while (j + 1 < order.length && v[order[j + 1]] == v[order[i]]) {
        j++;
      }
      for (var k = i; k <= j; k++) {
        r[order[k]] = (i + j) / 2;
      }
      i = j + 1;
    }
    return r;
  }

  final a = ranks([for (final p in pairs) p.$1]);
  final b = ranks([for (final p in pairs) p.$2]);
  final ma = _mean(a)!, mb = _mean(b)!;
  var num = 0.0, da = 0.0, db = 0.0;
  for (var i = 0; i < a.length; i++) {
    num += (a[i] - ma) * (b[i] - mb);
    da += (a[i] - ma) * (a[i] - ma);
    db += (b[i] - mb) * (b[i] - mb);
  }
  return da == 0 || db == 0 ? null : num / sqrt(da * db);
}
