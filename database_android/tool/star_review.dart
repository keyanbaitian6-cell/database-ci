import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:database_android/candidate_log.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/star_review.dart';

/// 通常★（参考候補）の独立した再検討（読み取り専用）。事前に固定した条件と
/// 結果は `NEXT_DAY_STAR_INDEPENDENT_REVIEW_20260930.md`。
///
/// 使い方（database_android で）：
///   dart run tool/star_review.dart --json <全期間のバックアップ.json>
///       --out <出力フォルダ（リポジトリの外）> [--permutations 200]
///
/// 実データ・台ごとの出力はリポジトリに入れない。
const seed = 20260930;

double _r(num v, [int digits = 4]) => double.parse(v.toStringAsFixed(digits));

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

double _quantile(List<double> sorted, double q) {
  if (sorted.isEmpty) return double.nan;
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

int _dayDiff(String a, String b) =>
    DateTime.parse(a).difference(DateTime.parse(b)).inDays;

Map<String, Object?> memberTrace(StarGroup g, StarMember m) {
  final b = m.breakdown;
  final latest = b.latestUsed;
  final worst = nextIndexWith(b, -50);
  final best = nextIndexWith(b, 50);
  final out = g.firstOut;
  return {
    'store': g.store,
    'machine': g.machine,
    'day': g.day,
    'rack': m.record.rack,
    'games_today': m.record.games,
    'eligible': g.members.length,
    'k': g.k,
    'position': m.position,
    'star': m.star,
    'star_yesterday': m.starYesterday,
    'star_if_unrounded': m.starUnrounded,
    'index': m.index,
    'index_unrounded': _r(m.unrounded),
    'days_used': b.n,
    'today_used': b.todayUsed,
    'latest_used_day': latest?.day,
    'days_since_latest': latest == null ? null : _dayDiff(g.day, latest.day),
    'latest_gap': latest == null ? null : _r(latest.gap!),
    'latest_effect': latest == null ? null : _r(latest.gap! / (b.n + 5)),
    'older_gap_sum': latest == null ? null : _r(b.gapSum - latest.gap!),
    'last_star_index': g.lastStar.index,
    'first_out_index': out?.index,
    'first_out_rack': out?.record.rack,
    'tie_at_boundary': g.tieAtBoundary,
    'next_index_if_worst': _r(worst),
    'next_index_if_best': _r(best),
    'history': [
      for (final d in b.days)
        {
          'day': d.day,
          'games': d.games,
          'peers': d.peers,
          'rank': d.rank == null ? null : _r(d.rank!),
          'gap': d.gap == null ? null : _r(d.gap!),
        },
    ],
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
  final permutations = int.parse(option('--permutations') ?? '200');
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
    // 未来検証に固定した予測日（2026-09-30〜）を使わない。
    stderr.writeln('2026-09-30以降の記録を含むデータは使わない（未来検証の期間）');
    exit(65);
  }
  final summary = <String, Object?>{
    'input': {'records': full.length, 'last_day': lastDay},
  };
  final stopwatch = Stopwatch()..start();

  // ---- A. アプリの見え方 ----
  final app = buildStarGroups(full);
  final stars = [
    for (final g in app)
      for (final m in g.members)
        if (m.star) (g: g, m: m),
  ];
  summary['groups_app_view'] = {
    'groups': app.length,
    'days': {for (final g in app) g.day}.length,
    'first_day': app
        .map((g) => g.day)
        .reduce((a, b) => a.compareTo(b) <= 0 ? a : b),
    'eligible_racks': app.fold<int>(0, (s, g) => s + g.members.length),
    'stars': stars.length,
  };

  // A2：連日同台率（実データと、台番号を入れ替えたデータ）。
  Map<String, Object?> repeat(List<StarGroup> groups) => {
    for (final store in [null, ...storeNames.keys])
      store ?? 'all': () {
        final r = repeatRate(groups, store: store);
        return {
          'pairs': r.pairs,
          'stars': r.stars,
          'repeated': r.repeated,
          'rate': r.rate == null ? null : _r(r.rate!),
        };
      }(),
  };
  final realRepeat = repeat(app);
  final rng = Random(seed);
  final nullRates = <String, List<double>>{
    for (final s in ['all', ...storeNames.keys]) s: [],
  };
  final nullSd = <double>[];
  for (var i = 0; i < permutations; i++) {
    final permuted = buildStarGroups(
      permuteRackLabels(full, rng),
      check: false,
    );
    for (final s in ['all', ...storeNames.keys]) {
      final r = repeatRate(permuted, store: s == 'all' ? null : s);
      if (r.rate != null) nullRates[s]!.add(r.rate!);
    }
    final sd = meanWithinGroupSd(permuted);
    if (sd != null) nullSd.add(sd);
  }
  summary['A2_repeat_rate'] = {
    'definition': "当日★のうち前日も★だった割合（前日にも同じ店舗・機種のグループがある組、当日★が分母）。アプリの見え方。",
    'real': realRepeat,
    'permutation_null': {
      for (final s in nullRates.keys)
        s: () {
          final sorted = nullRates[s]!..sort();
          return {
            'runs': sorted.length,
            'mean': _r(_mean(sorted)!),
            'p2_5': _r(_quantile(sorted, .025)),
            'p97_5': _r(_quantile(sorted, .975)),
          };
        }(),
    },
  };
  // 参考：前回の比較と同じ見え方・期間（予測時点、予測日9/21〜28）での照合。
  final predicted = buildStarGroups(full, cutoffFor: predictionCutoff);
  final comparable = [
    for (final g in predicted)
      if (g.day.compareTo('2026-09-21') >= 0 &&
          g.day.compareTo('2026-09-28') <= 0)
        g,
  ];
  for (final g in comparable) {
    if (g.day == '2026-09-21') {
      for (final m in g.members) {
        m.starYesterday = null;
      }
    }
  }
  summary['A2_crosscheck_previous_definition'] = repeat(comparable);

  // A3：丸めと同点。
  final tieGroups = app.where((g) => g.tieAtBoundary).toList();
  var tiedStars = 0, reversedByRounding = 0;
  for (final g in tieGroups) {
    final tied = [
      for (final m in g.members)
        if (m.index == g.lastStar.index) m,
    ];
    final inside = tied.where((m) => m.star).toList();
    final outside = tied.where((m) => !m.star).toList();
    tiedStars += inside.length;
    for (final a in inside) {
      if (outside.any((b) => b.unrounded > a.unrounded)) reversedByRounding++;
    }
  }
  final changedIfUnrounded = [
    for (final g in app)
      for (final m in g.members)
        if (m.star != m.starUnrounded) m,
  ];
  final positions = <double>[];
  for (final g in app) {
    final racks = [for (final m in g.members) m.record.rack]..sort();
    for (final m in g.members.where((m) => m.star)) {
      positions.add(racks.indexOf(m.record.rack) / (racks.length - 1));
    }
  }
  summary['A3_rounding_ties'] = {
    'groups': app.length,
    'tie_at_boundary_groups': tieGroups.length,
    'stars_decided_by_rack_order': tiedStars,
    'stars_whose_unrounded_index_is_lower_than_an_excluded_tied_rack':
        reversedByRounding,
    'stars_that_change_if_ranked_unrounded': changedIfUnrounded
        .where((m) => m.star)
        .length,
    'star_rack_position_in_group_mean_0_low_1_high': _r(_mean(positions)!),
    'star_rack_position_expected_if_unrelated': 0.5,
  };

  // A4：当日の情報の有無。
  final notToday = stars.where((s) => !s.m.breakdown.todayUsed).toList();
  String reason(StarMember m) {
    final r = m.record;
    if (hasImplausibleNumbers(r)) return 'implausible';
    if (r.games == 0) return 'games_0';
    if (r.games < 500) return 'games_1_499';
    if (r.bb < 0 || r.rb < 0) return 'negative';
    return 'fewer_than_3_peers';
  }

  final reasons = <String, int>{};
  for (final s in notToday) {
    reasons[reason(s.m)] = (reasons[reason(s.m)] ?? 0) + 1;
  }
  summary['A4_same_day_information'] = {
    'stars': stars.length,
    'stars_without_today': notToday.length,
    'share': _r(notToday.length / stars.length),
    'reasons': reasons,
    'days_since_latest_used_day': _quantiles([
      for (final s in stars)
        if (s.m.breakdown.latestUsed case final d?)
          _dayDiff(s.g.day, d.day).toDouble(),
    ]),
    'by_store': {
      for (final store in storeNames.keys)
        store: () {
          final mine = stars.where((s) => s.g.store == store).toList();
          final without = mine.where((s) => !s.m.breakdown.todayUsed).length;
          return {
            'stars': mine.length,
            'without_today': without,
            'share': mine.isEmpty ? null : _r(without / mine.length),
          };
        }(),
    },
  };

  // A5：1日の結果の効き方と、翌日が最下位でも★が残るか。
  var sticky = 0, judged = 0;
  final effects = <double>[];
  final thresholds = <double>[];
  for (final s in stars) {
    final b = s.m.breakdown;
    final latest = b.latestUsed;
    if (latest != null) effects.add((latest.gap! / (b.n + 5)).abs());
    final out = s.g.firstOut;
    if (out == null) continue;
    judged++;
    final worst = nextIndexWith(b, -50);
    if (worst > out.index ||
        (worst == out.index && s.m.record.rack < out.record.rack)) {
      sticky++;
    }
    // ★が境界まで下がる翌日の寄与（-50〜+50の範囲外なら1日では外れない）。
    var kept = b.gapSum, n = b.n;
    if (b.days.length >= 10 && b.days.last.used) {
      kept -= b.days.last.gap!;
      n -= 1;
    }
    thresholds.add((out.index - 50) * (n + 1 + 5) - kept);
  }
  summary['A5_one_day_effect'] = {
    'abs_latest_effect_on_index': _quantiles(effects),
    'stars_judged': judged,
    'stay_above_todays_boundary_even_if_worst_tomorrow': sticky,
    'share': judged == 0 ? null : _r(sticky / judged),
    'contribution_that_reaches_boundary': _quantiles(thresholds),
    'note': '寄与は-50（同じ日の比較相手で最下位・回転数が十分）〜+50。境界まで下がる寄与が-50未満なら、翌日1日の結果だけでは外れない（他の台を据え置いた目安）。',
  };

  // A6：根拠の強さ（グループ内の指数のばらつき）。
  final realSd = meanWithinGroupSd(app)!;
  final nullSdSorted = nullSd..sort();
  summary['A6_signal_strength'] = {
    'mean_within_group_sd_real': _r(realSd),
    'mean_within_group_sd_null_mean': _r(_mean(nullSdSorted)!),
    'null_p2_5': _r(_quantile(nullSdSorted, .025)),
    'null_p97_5': _r(_quantile(nullSdSorted, .975)),
    'ratio_real_to_null': _r(realSd / _mean(nullSdSorted)!),
    'star_index_minus_50': _quantiles([for (final s in stars) s.m.index - 50]),
  };

  // A7：当時画面に出ていた候補（保存済み）と、今計算し直した★の一致。
  final appByKey = {for (final g in app) g.key: g};
  final latestSnapshot = <String, CandidateSnapshot>{};
  for (final raw in (doc['candidate_snapshots'] as List? ?? const [])) {
    final s = CandidateSnapshot.tryFromJson(raw);
    if (s == null || s.machine == varietyGroupName) continue;
    final at = readJst(s.takenAt);
    if (at == null || !at.isBefore(predictionCutoff(s.day))) continue;
    final key = '${s.store}|${normalizeMachineName(s.machine)}|${s.day}';
    final current = latestSnapshot[key];
    if (current == null || readJst(current.takenAt)!.isBefore(at)) {
      latestSnapshot[key] = s;
    }
  }
  var compared = 0, exact = 0, missingNow = 0, emptySnapshot = 0;
  var emptyButStarsNow = 0;
  final jaccard = <double>[];
  final shownByKey = <String, Set<int>>{};
  for (final entry in latestSnapshot.entries) {
    final shown = {for (final c in entry.value.candidates) c.rack};
    shownByKey[entry.key] = shown;
    if (shown.isEmpty) {
      emptySnapshot++;
      // 当時は候補なし。今の計算で★が出るなら不一致として数える。
      if (appByKey[entry.key] != null) emptyButStarsNow++;
      continue;
    }
    final g = appByKey[entry.key];
    if (g == null) {
      missingNow++;
      continue;
    }
    compared++;
    final now = {
      for (final m in g.members)
        if (m.star) m.record.rack,
    };
    if (now.length == shown.length && now.containsAll(shown)) exact++;
    jaccard.add(now.intersection(shown).length / now.union(shown).length);
  }
  // 当時画面に出ていた候補どうしの連日同台率。
  var shownPairs = 0, shownStars = 0, shownRepeated = 0;
  for (final entry in shownByKey.entries) {
    final parts = entry.key.split('|');
    final before =
        shownByKey['${parts[0]}|${parts[1]}|${shiftDay(parts[2], -1)}'];
    if (before == null || entry.value.isEmpty) continue;
    shownPairs++;
    shownStars += entry.value.length;
    shownRepeated += entry.value.intersection(before).length;
  }
  summary['A7_shown_vs_recomputed'] = {
    'snapshot_groups_before_cutoff': latestSnapshot.length,
    'empty_snapshots': emptySnapshot,
    'empty_snapshots_but_stars_now': emptyButStarsNow,
    'groups_missing_now': missingNow,
    'compared': compared,
    'exact_match': exact,
    'exact_match_rate': compared == 0 ? null : _r(exact / compared),
    'mean_jaccard': jaccard.isEmpty ? null : _r(_mean(jaccard)!),
    'shown_repeat': {
      'pairs': shownPairs,
      'stars': shownStars,
      'repeated': shownRepeated,
      'rate': shownStars == 0 ? null : _r(shownRepeated / shownStars),
    },
    'shown_days': ({
      for (final k in latestSnapshot.keys) k.split('|')[2],
    }.toList()..sort()),
  };

  // ---- B・C：予測時点の見え方（翌日の点数と組み合わせる） ----
  final byKeyFull = {for (final r in full) r.key: r};
  final fullByMachineDay = <String, List<SlotRecord>>{};
  for (final r in full) {
    fullByMachineDay
        .putIfAbsent('${r.store}|${r.machine}|${r.day}', () => [])
        .add(r);
  }
  final nextScoreCache = <String, double?>{};
  double? nextScore(SlotRecord row) =>
      nextScoreCache.putIfAbsent(row.key, () => scoreRecord(row, full).total);
  final allDays = {for (final r in full) r.day};
  final b1 = <String, Map<String, List<double>>>{};
  final b3 = <String, Map<String, List<double>>>{};
  final c3 = <String, Map<String, List<double>>>{};
  final b2 = <String, Map<String, int>>{};
  final b2Day = <String, Map<String, Map<String, (int, int)>>>{};
  for (final day in allDays.toList()..sort()) {
    final next = shiftDay(day, 1);
    if (!allDays.contains(next)) continue;
    final available = availableRecords(
      full,
      day,
      cutoff: predictionCutoff(day),
    );
    final byStore = <String, List<SlotRecord>>{};
    for (final r in available) {
      if (r.day == day) byStore.putIfAbsent(r.store, () => []).add(r);
    }
    for (final store in byStore.keys) {
      final dayRows = byStore[store]!;
      final variety = varietyMachines(dayRows);
      final byMachine = <String, List<SlotRecord>>{};
      for (final r in dayRows) {
        if (!variety.contains(r.machine)) {
          byMachine.putIfAbsent(r.machine, () => []).add(r);
        }
      }
      final machineMeans = <(double, double)>[];
      for (final machine in byMachine.keys) {
        final rows = byMachine[machine]!;
        final history = machineHistory(available, store, machine);
        final pairs = <(double, double)>[];
        final indexPairs = <(double, double)>[];
        for (final r in rows) {
          final nextRow = byKeyFull['$store|$next|$machine|${r.rack}'];
          final today = scoreRecord(r, available).total;
          final tomorrow = nextRow == null ? null : nextScore(nextRow);
          if (today != null && tomorrow != null) {
            pairs.add((today, tomorrow));
            final counts = b2.putIfAbsent(store, () => {});
            final perDay = b2Day
                .putIfAbsent(store, () => {})
                .putIfAbsent(day, () => {});
            void add(String name, bool hit) {
              counts['${name}_n'] = (counts['${name}_n'] ?? 0) + 1;
              if (hit) counts['${name}_hit'] = (counts['${name}_hit'] ?? 0) + 1;
              final (n, h) = perDay[name] ?? (0, 0);
              perDay[name] = (n + 1, h + (hit ? 1 : 0));
            }

            add('all', tomorrow >= 60);
            if (today >= 60) add('today60', tomorrow >= 60);
            if (today < 40) add('today_under40', tomorrow >= 60);
          }
          final index = nextDayIndex(r, history).index;
          final rank = nextRow == null
              ? null
              : hitRankAmongPeers(
                  nextRow,
                  fullByMachineDay['$store|$machine|$next'] ?? const [],
                );
          if (index != null && rank != null) indexPairs.add((index, rank));
        }
        if (pairs.length >= 4) {
          final rho = spearman(pairs);
          if (rho != null) {
            b1.putIfAbsent(store, () => {}).putIfAbsent(day, () => []).add(rho);
          }
          machineMeans.add((
            _mean(pairs.map((p) => p.$1))!,
            _mean(pairs.map((p) => p.$2))!,
          ));
        }
        if (indexPairs.length >= 4) {
          final rho = spearman(indexPairs);
          if (rho != null) {
            c3.putIfAbsent(store, () => {}).putIfAbsent(day, () => []).add(rho);
          }
        }
      }
      if (machineMeans.length >= 4) {
        final rho = spearman(machineMeans);
        if (rho != null) {
          b3.putIfAbsent(store, () => {}).putIfAbsent(day, () => []).add(rho);
        }
      }
    }
  }
  Map<String, Object?> byStoreSummary(
    Map<String, Map<String, List<double>>> data,
  ) {
    final all = <String, List<double>>{};
    for (final perStore in data.values) {
      for (final e in perStore.entries) {
        all.putIfAbsent(e.key, () => []).addAll(e.value);
      }
    }
    return {
      'all': daySummary(all, seed: seed),
      for (final store in storeNames.keys)
        store: daySummary(data[store] ?? {}, seed: seed),
    };
  }

  summary['B1_score_persistence_within_machine'] = byStoreSummary(b1);
  summary['B2_next_day_60_rates'] = {
    for (final store in b2.keys)
      store: {
        for (final name in ['all', 'today60', 'today_under40'])
          name: {
            'pooled_n': b2[store]!['${name}_n'] ?? 0,
            'pooled_rate': (b2[store]!['${name}_n'] ?? 0) == 0
                ? null
                : _r(
                    (b2[store]!['${name}_hit'] ?? 0) / b2[store]!['${name}_n']!,
                  ),
            'mean_of_days': switch (_mean([
              for (final perDay in b2Day[store]!.values)
                if (perDay[name] case (final n, final h) when n > 0) h / n,
            ])) {
              final double v => _r(v),
              null => null,
            },
          },
      },
  };
  summary['B3_machine_level_persistence'] = byStoreSummary(b3);
  summary['C3_index_vs_next_hit_rank'] = byStoreSummary(c3);

  // C1・C2：前回の評価の検出力と、比べる相手に★自身が入ることの影響。
  final run = runBacktest(full, cutoffFor: predictionCutoff);
  final current = evaluateMethod(run.groups, (m) => m.current);
  final gap = current['gap_vs_pool'] as Map<String, Object?>;
  final dayValues = [
    for (final v in (gap['by_day'] as Map).values) (v as num).toDouble(),
  ];
  final mean = _mean(dayValues)!;
  final sd = sqrt(
    dayValues.fold(0.0, (s, v) => s + (v - mean) * (v - mean)) /
        (dayValues.length - 1),
  );
  final ci = gap['ci95'] as List;
  summary['C1_power'] = {
    'prediction_days': dayValues.length,
    'daily_gap_mean': _r(mean),
    'daily_gap_sd': _r(sd),
    'bootstrap_ci95': ci,
    'bootstrap_half_width': _r(((ci[1] as num) - (ci[0] as num)) / 2),
    'normal_half_width': _r(1.96 * sd / sqrt(dayValues.length)),
    'days_for_half_width_1_point': (pow(1.96 * sd, 2)).ceil(),
    'days_for_half_width_2_points': (pow(1.96 * sd / 2, 2)).ceil(),
  };
  final shares = [for (final g in run.groups) g.count / g.members.length];
  summary['C2_dilution'] = {
    'groups': run.groups.length,
    'mean_k_over_n': _r(_mean(shares)!),
    'gap_is_times_star_minus_nonstar': _r(1 - _mean(shares)!),
  };

  // ---- 事例（固定した選び方） ----
  // 連日★の最長（店舗ごとに1台）。
  final byRack = <String, List<(StarGroup, StarMember)>>{};
  for (final g in app) {
    for (final m in g.members) {
      byRack
          .putIfAbsent('${g.store}|${g.machine}|${m.record.rack}', () => [])
          .add((g, m));
    }
  }
  final examples = <String, Object?>{};
  for (final store in storeNames.keys) {
    ({String key, int length, String end})? best;
    for (final e in byRack.entries.where((e) => e.key.startsWith('$store|'))) {
      final list = e.value..sort((a, b) => a.$1.day.compareTo(b.$1.day));
      var run = 0;
      String? previous;
      for (final (g, m) in list) {
        run = m.star
            ? (previous != null && shiftDay(previous, 1) == g.day && run > 0
                  ? run + 1
                  : 1)
            : 0;
        previous = g.day;
        if (run > 0 &&
            (best == null ||
                run > best.length ||
                (run == best.length && g.day.compareTo(best.end) > 0))) {
          best = (key: e.key, length: run, end: g.day);
        }
      }
    }
    if (best == null) continue;
    final rows = byRack[best.key]!
        .where(
          (p) =>
              p.$1.day.compareTo(shiftDay(best!.end, -best.length)) >= 0 &&
              p.$1.day.compareTo(shiftDay(best.end, 1)) <= 0,
        )
        .toList();
    examples['longest_streak_$store'] = {
      'why': '店舗内で★の連続日数が最も長い台（同じ長さなら最近のもの）。',
      'length': best.length,
      'days': [for (final (g, m) in rows) memberTrace(g, m)],
    };
  }
  // 前日★→当日外れ（最近の日から、指数の下がりが大きい順に2件）。
  final dropouts = <(StarGroup, StarMember, double)>[];
  final appKey = {for (final g in app) g.key: g};
  for (final g in app) {
    final before = appKey['${g.store}|${g.machine}|${shiftDay(g.day, -1)}'];
    if (before == null) continue;
    for (final m in g.members.where(
      (m) => m.starYesterday == true && !m.star,
    )) {
      final old = before.members.firstWhere(
        (x) => x.record.rack == m.record.rack,
      );
      dropouts.add((g, m, old.index - m.index));
    }
  }
  dropouts.sort((a, b) {
    final byDay = b.$1.day.compareTo(a.$1.day);
    return byDay != 0 ? byDay : b.$3.compareTo(a.$3);
  });
  examples['dropouts'] = {
    'why': '前日★だった台が当日外れた例。最近の日から、指数の下がりが大きい順。',
    'count_total': dropouts.length,
    'cases': [
      for (final (g, m, _) in dropouts.take(2))
        {
          'today': memberTrace(g, m),
          'yesterday': memberTrace(
            appKey['${g.store}|${g.machine}|${shiftDay(g.day, -1)}']!,
            appKey['${g.store}|${g.machine}|${shiftDay(g.day, -1)}']!.members
                .firstWhere((x) => x.record.rack == m.record.rack),
          ),
        },
    ],
  };
  // 境界の同点（最近の日から2件）。
  final ties = [...tieGroups]..sort((a, b) => b.day.compareTo(a.day));
  examples['boundary_ties'] = {
    'why': 'k位と(k+1)位の丸めた指数が同じで、台番号の小さい順で★が決まった例（最近の日から）。',
    'cases': [
      for (final g in ties.take(2))
        {
          'group': g.key,
          'k': g.k,
          'tied': [
            for (final m in g.members)
              if (m.index == g.lastStar.index)
                {
                  'rack': m.record.rack,
                  'index': m.index,
                  'index_unrounded': _r(m.unrounded, 6),
                  'star': m.star,
                },
          ],
        },
    ],
  };
  // 当日の情報なしの★（最近の日から2件）。
  final noToday = [...notToday]
    ..sort((a, b) {
      final byDay = b.g.day.compareTo(a.g.day);
      return byDay != 0 ? byDay : a.m.record.rack.compareTo(b.m.record.rack);
    });
  examples['stars_without_today'] = {
    'why': '当日の記録が指数に入っていない（0G・500G未満など）のに★の例（最近の日から）。',
    'cases': [for (final s in noToday.take(2)) memberTrace(s.g, s.m)],
  };

  summary['elapsed_seconds'] = stopwatch.elapsed.inSeconds;
  final dir = Directory(outDir)..createSync(recursive: true);
  const encoder = JsonEncoder.withIndent('  ');
  File('${dir.path}/summary.json').writeAsStringSync(encoder.convert(summary));
  File('${dir.path}/examples.json')
      .writeAsStringSync(encoder.convert(examples));
  File('${dir.path}/trace.json').writeAsStringSync(
    encoder.convert([
      for (final g in app)
        for (final m in g.members) memberTrace(g, m),
    ]),
  );
  stdout.writeln(encoder.convert(summary));
}
