import 'dart:convert';
import 'dart:io';

import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/star_review.dart'
    show daySummary, indexBreakdown;
import 'package:database_android/strong_rack_review.dart';

/// 当日80点以上の台を翌日も推すのは適切か（読み取り専用）。事前に固定した
/// 条件と結果は `NEXT_DAY_STRONG_RACK_REVIEW_20260930.md`。
///
/// 使い方（database_android で）：
///   dart run tool/strong_rack_review.dart --json <全期間のバックアップ.json>
///       --out <出力フォルダ（リポジトリの外）>
///
/// 実データ・台ごとの出力はリポジトリに入れない。
const seed = 20260930;

double _r(num v, [int digits = 4]) => double.parse(v.toStringAsFixed(digits));

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

double _quantile(List<double> sorted, double q) {
  final i = (sorted.length - 1) * q;
  final lo = i.floor(), hi = i.ceil();
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

Map<String, Object?> _quantiles(Iterable<double> values) {
  final sorted = values.toList()..sort();
  if (sorted.isEmpty) return {'n': 0};
  return {
    'n': sorted.length,
    'min': _r(sorted.first),
    'p25': _r(_quantile(sorted, .25)),
    'median': _r(_quantile(sorted, .5)),
    'p75': _r(_quantile(sorted, .75)),
    'max': _r(sorted.last),
    'mean': _r(_mean(sorted)!),
  };
}

double? _share(Iterable<bool> flags) {
  final list = flags.toList();
  return list.isEmpty ? null : _r(list.where((f) => f).length / list.length);
}

/// 店舗ごと・全体の日単位の要約。[values] は（店舗, 日, 値）。
Map<String, Object?> _byStoreDays(List<(String, String, double)> values) {
  Map<String, List<double>> collect(String? store) {
    final byDay = <String, List<double>>{};
    for (final (s, d, v) in values) {
      if (store == null || s == store) byDay.putIfAbsent(d, () => []).add(v);
    }
    return byDay;
  }

  return {
    'all': daySummary(collect(null), seed: seed),
    for (final store in storeNames.keys)
      store: daySummary(collect(store), seed: seed),
  };
}

void main(List<String> args) {
  String? option(String name) {
    final i = args.indexOf(name);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final jsonPath = option('--json'), outDir = option('--out');
  if (jsonPath == null || outDir == null) {
    stderr.writeln('--json <バックアップ> --out <出力フォルダ> が必要です');
    exit(64);
  }
  final doc = jsonDecode(File(jsonPath).readAsStringSync()) as Map;
  final full = normalizeForBacktest([
    for (final raw in doc['records'] as List)
      if (raw is Map && !raw.containsKey('unreadable_record'))
        SlotRecord.fromJson(Map<String, dynamic>.from(raw)),
  ]);
  final lastDay = full
      .map((r) => r.day)
      .reduce((a, b) => a.compareTo(b) >= 0 ? a : b);
  if (lastDay.compareTo('2026-09-29') > 0) {
    stderr.writeln('2026-09-30以降の記録を含むデータは使わない（未来検証の期間）');
    exit(65);
  }
  final summary = <String, Object?>{};

  // ---- 主対象の全台（予測時点の見え方） ----
  final rackDays = buildRackDays(full);
  final byGroup = <String, List<RackDay>>{};
  for (final r in rackDays) {
    byGroup.putIfAbsent(r.groupKey, () => []).add(r);
  }
  final scored = rackDays.where((r) => r.score.total != null).toList();
  final strong = rackDays.where((r) => r.strong).toList();
  final predictionDays = {for (final r in rackDays) r.record.day}.toList()
    ..sort();
  summary['population'] = {
    'prediction_days': predictionDays.length,
    'first_day': predictionDays.first,
    'last_day': predictionDays.last,
    'rack_days': rackDays.length,
    'machine_days': byGroup.length,
    'scored_rack_days': scored.length,
    'strong_80_plus': strong.length,
    'strong_over_90': strong.where((r) => r.score.total! > 90).length,
    'strong_share_of_scored': _r(strong.length / scored.length),
    'strong_by_store': {
      for (final s in storeNames.keys)
        s: strong.where((r) => r.record.store == s).length,
    },
    'strong_by_day': {
      for (final d in predictionDays)
        d: strong.where((r) => r.record.day == d).length,
    },
  };

  // ---- 当日の出方（翌日の結果は使わない） ----
  double groupMedianGames(RackDay r) {
    final games = [
      for (final x in byGroup[r.groupKey]!) x.record.games.toDouble(),
    ]..sort();
    return _quantile(games, .5);
  }

  final withGraph = strong.where((r) => r.record.graph != null).toList();
  summary['strong_today'] = {
    'games': _quantiles([for (final r in strong) r.record.games.toDouble()]),
    'games_vs_machine_median': _quantiles([
      for (final r in strong)
        if (groupMedianGames(r) > 0) r.record.games / groupMedianGames(r),
    ]),
    'provisional_share': _share(strong.map((r) => r.score.provisional)),
    // 6.の条件案に当たる割合（当日の値だけ。翌日の結果は使わない）。
    'proposal_end_to_peak_at_least_0_9': _share(
      strong.map((r) => (endToPeak(r.record) ?? 0) >= 0.9),
    ),
    'proposal_games_3000_and_1_5x_machine_median': _share(
      strong.map(
        (r) =>
            r.record.games >= 3000 &&
            groupMedianGames(r) > 0 &&
            r.record.games / groupMedianGames(r) >= 1.5,
      ),
    ),
    'graph_present_share': _share(strong.map((r) => r.record.graph != null)),
    'end_plus_share_among_graph': _share(
      withGraph.map((r) => endState(r.record) == EndState.plus),
    ),
    'end_to_peak_among_graph': _quantiles([
      for (final r in withGraph) ?endToPeak(r.record),
    ]),
    'positive_points': {
      '10': strong.where((r) => r.score.positive == 10).length,
      '0': strong.where((r) => r.score.positive == 0).length,
      'none': strong.where((r) => r.score.positive == null).length,
    },
    'retention_points': _quantiles([
      for (final r in strong) ?r.score.retention,
    ]),
    'hits_points': _quantiles([for (final r in strong) ?r.score.hits]),
    'hold_points': _quantiles([for (final r in strong) ?r.score.maxHold]),
  };

  // ---- 問1 ----
  final evalStrong = strong.where((r) => r.nextScore != null).toList();
  final allEval = rackDays.where((r) => r.nextScore != null).toList();
  final withinDiffs = <(String, String, double)>[];
  final binDeviation = <String, List<(String, String, double)>>{};
  String bin(double s) => s >= 80
      ? '80+'
      : s >= 60
      ? '60-80'
      : s >= 40
      ? '40-60'
      : '<40';
  for (final entry in byGroup.entries) {
    final evaluable = entry.value.where((r) => r.nextScore != null).toList();
    if (evaluable.isEmpty) continue;
    final groupMean = _mean(evaluable.map((r) => r.nextScore!))!;
    for (final r in evaluable) {
      final today = r.score.total;
      if (today == null) continue;
      binDeviation.putIfAbsent(bin(today), () => []).add((
        r.record.store,
        r.record.day,
        r.nextScore! - groupMean,
      ));
    }
    final s = evaluable.where((r) => r.strong).toList();
    final o = evaluable.where((r) => !r.strong).toList();
    if (s.isEmpty || o.isEmpty) continue;
    final first = entry.value.first.record;
    withinDiffs.add((
      first.store,
      first.day,
      _mean(s.map((r) => r.nextScore!))! - _mean(o.map((r) => r.nextScore!))!,
    ));
  }
  summary['Q1_next_day_of_80_plus'] = {
    'strong': strong.length,
    'evaluable': evalStrong.length,
    'evaluable_rate': _r(evalStrong.length / strong.length),
    'next_score': _quantiles(evalStrong.map((r) => r.nextScore!)),
    'next_share_80_plus': _share(evalStrong.map((r) => r.nextScore! >= 80)),
    'next_share_60_plus': _share(evalStrong.map((r) => r.nextScore! >= 60)),
    'next_share_under_40': _share(evalStrong.map((r) => r.nextScore! < 40)),
    'all_racks_next_share_80_plus': _share(
      allEval.map((r) => r.nextScore! >= 80),
    ),
    'all_racks_next_share_60_plus': _share(
      allEval.map((r) => r.nextScore! >= 60),
    ),
    'all_racks_next_mean': _r(_mean(allEval.map((r) => r.nextScore!))!),
    'next_end_state_when_next_record_exists': {
      for (final e in EndState.values)
        e.name: strong
            .where((r) => r.next != null && endState(r.next) == e)
            .length,
    },
    'within_machine_strong_minus_others': _byStoreDays(withinDiffs),
    'deviation_from_machine_next_day_mean_by_today_bin': {
      for (final b in ['80+', '60-80', '40-60', '<40'])
        b: {
          'racks': binDeviation[b]?.length ?? 0,
          'pooled_mean': binDeviation[b] == null
              ? null
              : _r(_mean(binDeviation[b]!.map((e) => e.$3))!),
          'days': _byStoreDays(binDeviation[b] ?? const [])['all'],
        },
    },
  };

  // ---- 問2 (b)(c) ----
  final rateDiffs = <(String, String, double)>[];
  final meanDiffs = <(String, String, double)>[];
  var pooledA = <double>[], pooledB = <double>[];
  final byStoreDay = <String, List<List<RackDay>>>{};
  for (final entry in byGroup.entries) {
    final first = entry.value.first.record;
    byStoreDay
        .putIfAbsent('${first.store}|${first.day}', () => [])
        .add(entry.value);
  }
  for (final entry in byStoreDay.entries) {
    final a = <double>[], b = <double>[];
    for (final group in entry.value) {
      final hasStrong = group.any((r) => r.strong);
      for (final r in group) {
        if (r.nextScore == null || r.strong) continue;
        (hasStrong ? a : b).add(r.nextScore!);
      }
    }
    pooledA.addAll(a);
    pooledB.addAll(b);
    if (a.isEmpty || b.isEmpty) continue;
    final parts = entry.key.split('|');
    double rate(List<double> xs) => xs.where((v) => v >= 80).length / xs.length;
    rateDiffs.add((parts[0], parts[1], rate(a) - rate(b)));
    meanDiffs.add((parts[0], parts[1], _mean(a)! - _mean(b)!));
  }
  final topCredits = <(String, double, double)>[];
  for (final group in byGroup.values) {
    final strongOnes = group.where((r) => r.strong).toList();
    if (strongOnes.length != 1) continue;
    final s = strongOnes.single;
    final evaluable = group.where((r) => r.nextScore != null).toList();
    if (s.nextScore == null || evaluable.length < 4) continue;
    final top = evaluable
        .map((r) => r.nextScore!)
        .reduce((x, y) => x > y ? x : y);
    final tied = evaluable.where((r) => r.nextScore == top).length;
    topCredits.add((
      s.record.store,
      s.nextScore == top ? 1 / tied : 0,
      1 / evaluable.length,
    ));
  }
  summary['Q2_other_racks'] = {
    'a_within_machine_strong_minus_others':
        'Q1_next_day_of_80_plus.within_machine_strong_minus_others を参照',
    'b_next_80_rate_other_racks_minus_machines_without_80': _byStoreDays(
      rateDiffs,
    ),
    'b_next_mean_other_racks_minus_machines_without_80': _byStoreDays(
      meanDiffs,
    ),
    'b_pooled': {
      'other_racks_in_machines_with_80': {
        'n': pooledA.length,
        'next_share_80_plus': _share(pooledA.map((v) => v >= 80)),
        'next_mean': _mean(pooledA) == null ? null : _r(_mean(pooledA)!),
      },
      'racks_in_machines_without_80': {
        'n': pooledB.length,
        'next_share_80_plus': _share(pooledB.map((v) => v >= 80)),
        'next_mean': _mean(pooledB) == null ? null : _r(_mean(pooledB)!),
      },
    },
    'c_single_80_rack_stays_top_next_day': {
      for (final store in [null, ...storeNames.keys])
        store ?? 'all': () {
          final mine = [
            for (final c in topCredits)
              if (store == null || c.$1 == store) c,
          ];
          return {
            'machine_days': mine.length,
            'stays_top_rate': mine.isEmpty
                ? null
                : _r(_mean(mine.map((c) => c.$2))!),
            'chance_expected': mine.isEmpty
                ? null
                : _r(_mean(mine.map((c) => c.$3))!),
          };
        }(),
    },
  };

  // ---- 問3・問4（現行の★、予測時点の見え方） ----
  final run = runBacktest(full, cutoffFor: predictionCutoff);
  for (final g in run.groups) {
    final order = {for (final m in currentOrder(g).take(g.count)) m.rack};
    final current = {
      for (final m in g.members)
        if (m.current) m.rack,
    };
    if (order.length != current.length || !order.containsAll(current)) {
      throw StateError('${g.store} ${g.day} ${g.machine}: 現行の並びが一致しない');
    }
  }
  final strongStarDiffWeak = <(String, String, double)>[];
  final strongStarDiffNonStar = <(String, String, double)>[];
  var stars = 0, strongStars = 0, weakStars = 0, noScoreStars = 0;
  var strongStarEval = 0, weakStarEval = 0;
  for (final g in run.groups) {
    final s = [
      for (final m in g.members)
        if (m.current && (m.todayScore ?? -1) >= strongScore) m,
    ];
    final w = [
      for (final m in g.members)
        if (m.current && m.todayScore != null && m.todayScore! < strongScore) m,
    ];
    final non = [
      for (final m in g.members)
        if (!m.current && m.nextScore != null) m.nextScore!,
    ];
    stars += g.members.where((m) => m.current).length;
    strongStars += s.length;
    weakStars += w.length;
    noScoreStars += g.members
        .where((m) => m.current && m.todayScore == null)
        .length;
    final sEval = [
      for (final m in s)
        if (m.nextScore != null) m.nextScore!,
    ];
    final wEval = [
      for (final m in w)
        if (m.nextScore != null) m.nextScore!,
    ];
    strongStarEval += sEval.length;
    weakStarEval += wEval.length;
    if (sEval.isNotEmpty && wEval.isNotEmpty) {
      strongStarDiffWeak.add((g.store, g.day, _mean(sEval)! - _mean(wEval)!));
    }
    if (sEval.isNotEmpty && non.isNotEmpty) {
      strongStarDiffNonStar.add((g.store, g.day, _mean(sEval)! - _mean(non)!));
    }
  }
  final strongStarScores = [
    for (final g in run.groups)
      for (final m in g.members)
        if (m.current &&
            (m.todayScore ?? -1) >= strongScore &&
            m.nextScore != null)
          m.nextScore!,
  ];
  final weakStarScores = [
    for (final g in run.groups)
      for (final m in g.members)
        if (m.current &&
            m.todayScore != null &&
            m.todayScore! < strongScore &&
            m.nextScore != null)
          m.nextScore!,
  ];
  summary['Q3_rerecommended_80_plus_stars'] = {
    'groups': run.groups.length,
    'stars': stars,
    'stars_80_plus': strongStars,
    'stars_under_80': weakStars,
    'stars_without_today_score': noScoreStars,
    'share_80_plus': _r(strongStars / stars),
    'evaluable_rate_80_plus': strongStars == 0
        ? null
        : _r(strongStarEval / strongStars),
    'evaluable_rate_under_80': weakStars == 0
        ? null
        : _r(weakStarEval / weakStars),
    'next_score_80_plus_stars': _quantiles(strongStarScores),
    'next_score_under_80_stars': _quantiles(weakStarScores),
    'next_share_80_plus_among_80_plus_stars': _share(
      strongStarScores.map((v) => v >= 80),
    ),
    'within_group_80_plus_star_minus_under_80_star': _byStoreDays(
      strongStarDiffWeak,
    ),
    'within_group_80_plus_star_minus_non_star': _byStoreDays(
      strongStarDiffNonStar,
    ),
  };

  // 問4
  final direct = <(String, String, double)>[];
  final directAffected = <(String, String, double)>[];
  final swapped = <(String, String, double)>[];
  var affected = 0, removed = 0, added = 0, lost = 0, emptied = 0;
  final perDay = <String, Map<String, int>>{};
  final methodSets = <String, Set<int>>{}, currentSets = <String, Set<int>>{};
  final addedByGroup = <String, List<BacktestMember>>{};
  for (final g in run.groups) {
    final current = [
      for (final m in g.members)
        if (m.current) m,
    ];
    final method = excludeStrong(g);
    final key = '${g.store}|${g.machine}|${g.day}';
    currentSets[key] = {for (final m in current) m.rack};
    methodSets[key] = {for (final m in method) m.rack};
    final out = current.where((m) => !method.contains(m)).toList();
    final inn = method.where((m) => !current.contains(m)).toList();
    addedByGroup[key] = inn;
    final changed = out.isNotEmpty || inn.isNotEmpty;
    if (changed) affected++;
    removed += out.length;
    added += inn.length;
    lost += current.length - method.length;
    if (method.isEmpty) emptied++;
    final day = perDay.putIfAbsent(g.day, () => {});
    if (changed) day['affected_groups'] = (day['affected_groups'] ?? 0) + 1;
    day['removed'] = (day['removed'] ?? 0) + out.length;
    day['added'] = (day['added'] ?? 0) + inn.length;
    final curEval = [
      for (final m in current)
        if (m.nextScore != null) m.nextScore!,
    ];
    final metEval = [
      for (final m in method)
        if (m.nextScore != null) m.nextScore!,
    ];
    if (curEval.isNotEmpty && metEval.isNotEmpty) {
      final d = _mean(metEval)! - _mean(curEval)!;
      direct.add((g.store, g.day, d));
      if (changed) directAffected.add((g.store, g.day, d));
    }
    final outEval = [
      for (final m in out)
        if (m.nextScore != null) m.nextScore!,
    ];
    final inEval = [
      for (final m in inn)
        if (m.nextScore != null) m.nextScore!,
    ];
    if (outEval.isNotEmpty && inEval.isNotEmpty) {
      swapped.add((g.store, g.day, _mean(outEval)! - _mean(inEval)!));
    }
  }
  Map<String, Object?> repeat(Map<String, Set<int>> sets) {
    var denominator = 0, repeated = 0, pairs = 0;
    for (final entry in sets.entries) {
      final parts = entry.key.split('|');
      final before = sets['${parts[0]}|${parts[1]}|${shiftDay(parts[2], -1)}'];
      if (before == null) continue;
      pairs++;
      denominator += entry.value.length;
      repeated += entry.value.intersection(before).length;
    }
    return {
      'pairs': pairs,
      'stars': denominator,
      'repeated': repeated,
      'rate': denominator == 0 ? null : _r(repeated / denominator),
    };
  }

  final removedScores = [
    for (final g in run.groups)
      for (final m in g.members)
        if (m.current &&
            (m.todayScore ?? -1) >= strongScore &&
            m.nextScore != null)
          m.nextScore!,
  ];
  final addedScores = [
    for (final list in addedByGroup.values)
      for (final m in list)
        if (m.nextScore != null) m.nextScore!,
  ];
  summary['Q4_exclude_80_plus_with_refill'] = {
    'groups': run.groups.length,
    'affected_groups': affected,
    'removed': removed,
    'added': added,
    'unrefilled': lost,
    'groups_left_without_candidates': emptied,
    'removed_next_score': _quantiles(removedScores),
    'added_next_score': _quantiles(addedScores),
    'removed_evaluable_rate': removed == 0
        ? null
        : _r(removedScores.length / removed),
    'added_evaluable_rate': added == 0 ? null : _r(addedScores.length / added),
    'method_minus_current_all_groups': _byStoreDays(direct),
    'method_minus_current_affected_groups': _byStoreDays(directAffected),
    'swapped_removed_minus_added': _byStoreDays(swapped),
    // 補足（規約外）：日を等しく重み付けすると、1グループしかない日の値が強く効く。
    // グループごとの値の分布と、その日の値を併記する。
    'supplementary_swapped_per_group': {
      'groups': swapped.length,
      'mean_of_groups': swapped.isEmpty
          ? null
          : _r(_mean(swapped.map((s) => s.$3))!),
      'median_of_groups': swapped.isEmpty
          ? null
          : _r(_quantile([for (final s in swapped) s.$3]..sort(), .5)),
      'removed_better_groups': swapped.where((s) => s.$3 > 0).length,
      'added_better_groups': swapped.where((s) => s.$3 < 0).length,
      'values': [
        for (final s in swapped)
          {'store': s.$1, 'day': s.$2, 'value': _r(s.$3)},
      ],
    },
    'repeat_rate_current': repeat(currentSets),
    'repeat_rate_method': repeat(methodSets),
    'by_day': perDay,
  };

  // ---- 事例（固定した選び方） ----
  final rackLookup = {for (final r in rackDays) r.record.key: r};
  final cases = <String, Object?>{};
  for (final store in storeNames.keys) {
    final candidates =
        [
          for (final g in run.groups.where((g) => g.store == store))
            for (final m in g.members)
              if (m.current &&
                  (m.todayScore ?? -1) >= strongScore &&
                  m.nextScore != null)
                (g, m),
        ]..sort((a, b) {
          final byDay = b.$1.day.compareTo(a.$1.day);
          if (byDay != 0) return byDay;
          final byScore = b.$2.todayScore!.compareTo(a.$2.todayScore!);
          return byScore != 0 ? byScore : a.$2.rack.compareTo(b.$2.rack);
        });
    cases[store] = [
      for (final (g, m) in candidates.take(2))
        () {
          final r = rackLookup['${g.store}|${g.day}|${g.machine}|${m.rack}']!;
          final available = availableRecords(
            full,
            g.day,
            cutoff: predictionCutoff(g.day),
          );
          final b = indexBreakdown(
            r.record,
            machineHistory(available, g.store, g.machine),
          );
          final latest = b.latestUsed;
          final group = byGroup['${g.store}|${g.machine}|${g.day}']!;
          final others = [
            for (final x in group)
              if (x.record.rack != m.rack && x.nextScore != null) x,
          ]..sort((a, b) => b.nextScore!.compareTo(a.nextScore!));
          return {
            'store': g.store,
            'machine': g.machine,
            'day': g.day,
            'rack': m.rack,
            'today_score': r.score.total,
            'today_parts': {
              'hits': r.score.hits,
              'hold': r.score.maxHold,
              'positive': r.score.positive,
              'retention': r.score.retention,
              'provisional': r.score.provisional,
            },
            'games_today': r.record.games,
            'machine_median_games': groupMedianGames(r),
            'graph_today': endState(r.record).name,
            'end_to_peak_today': endToPeak(r.record) == null
                ? null
                : _r(endToPeak(r.record)!),
            'index': m.index,
            'days_used': b.n,
            'today_in_index': b.todayUsed,
            'latest_gap': latest == null ? null : _r(latest.gap!),
            'older_gap_sum': latest == null ? null : _r(b.gapSum - latest.gap!),
            'eligible': g.members.length,
            'k': g.count,
            'next_score': m.nextScore,
            'next_graph': endState(r.next).name,
            'others_next_top3': [
              for (final x in others.take(3))
                {
                  'rack': x.record.rack,
                  'next_score': x.nextScore,
                  'today_score': x.score.total,
                },
            ],
            'any_other_80_next': others.any((x) => x.nextScore! >= 80),
            'replacement_if_excluded': [
              for (final a
                  in addedByGroup['${g.store}|${g.machine}|${g.day}'] ??
                      const <BacktestMember>[])
                {
                  'rack': a.rack,
                  'index': a.index,
                  'today_score': a.todayScore,
                  'next_score': a.nextScore,
                },
            ],
          };
        }(),
    ];
  }

  final dir = Directory(outDir)..createSync(recursive: true);
  const encoder = JsonEncoder.withIndent('  ');
  File('${dir.path}/summary.json').writeAsStringSync(encoder.convert(summary));
  File('${dir.path}/cases.json').writeAsStringSync(encoder.convert(cases));
  stdout.writeln(encoder.convert(summary));
}
