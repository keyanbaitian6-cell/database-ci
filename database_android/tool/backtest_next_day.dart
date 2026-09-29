import 'dart:convert';
import 'dart:io';

import 'package:database_android/candidate_log.dart';
import 'package:database_android/exploratory_candidates.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';

/// 翌日候補（仮）の検証（読み取り専用）。事前登録と結果は
/// `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md`。
///
/// 使い方（database_android で）：
///   dart run tool/backtest_next_day.dart --json <全期間のバックアップ.json>
///       [--earlier <上書き前の値.json>] [--out <結果.json>]
///       [--dump-candidates <候補.json>]
///
/// `--earlier` は PC版DBの書き込み記録から作る（`database/export_earlier_values.py`）。
/// `--dump-candidates` は、時刻を見ない全データでの候補をPC版と照合するための出力。
/// 実データ・台ごとの結果はリポジトリに入れない（集計だけを出す）。
const freshFrom = '2026-09-25';

/// 探索（「8. 探索」）：選ぶ期間は予測日 [freshFrom] より前、確かめる期間はそれ以降。
const exploratoryMethods = ExploratoryMethod.values;

void main(List<String> args) {
  String? option(String name) {
    final i = args.indexOf(name);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final jsonPath = option('--json');
  if (jsonPath == null) {
    stderr.writeln('--json <バックアップ> が必要です');
    exit(64);
  }
  final doc = jsonDecode(File(jsonPath).readAsStringSync()) as Map;
  final full = normalizeForBacktest([
    for (final raw in doc['records'] as List)
      if (raw is Map && !raw.containsKey('unreadable_record'))
        SlotRecord.fromJson(Map<String, dynamic>.from(raw)),
  ]);
  final snapshots = [
    for (final raw in (doc['candidate_snapshots'] as List? ?? const []))
      if (CandidateSnapshot.tryFromJson(raw) case final s?)
        (
          store: s.store,
          day: s.day,
          machine: s.machine,
          takenAt: s.takenAt,
          racks: [for (final c in s.candidates) c.rack],
        ),
  ];
  final earlier = <String, List<SlotRecord>>{};
  final earlierPath = option('--earlier');
  if (earlierPath != null) {
    for (final raw in jsonDecode(File(earlierPath).readAsStringSync()) as List) {
      final r = SlotRecord.fromJson(Map<String, dynamic>.from(raw as Map));
      final fixed = r.copyWith(machine: normalizeMachineName(r.machine));
      earlier.putIfAbsent(fixed.key, () => []).add(fixed);
    }
  }

  Map<String, Object?> summarize(BacktestRun run) {
    Map<String, Object?> part(bool Function(BacktestGroup) keep) {
      final groups = run.groups.where(keep).toList();
      final tops = run.topSeven
          .where((t) => groups.any((g) => g.store == t.store && g.day == t.day))
          .toList();
      return {
        'groups': groups.length,
        'prediction_days': {for (final g in groups) g.day}.length,
        'eligible_racks': groups.fold<int>(0, (n, g) => n + g.members.length),
        'labeled_racks': groups.fold<int>(0, (n, g) => n + g.labeled.length),
        'current': evaluateMethod(groups, (m) => m.current),
        'previous_score': evaluateMethod(groups, (m) => m.previousScore),
        'previous_minus_current': comparePreviousToCurrent(groups),
        'current_by_confidence': {
          for (final c in ['少', '中'])
            c: evaluateMethod(groups, (m) => m.current && m.confidence == c),
        },
        'top7_current': evaluateTopSeven(tops, groups, current: true),
        'top7_previous_score': evaluateTopSeven(tops, groups, current: false),
        'index_correlation': indexCorrelation(groups),
      };
    }

    return {
      'all': part((_) => true),
      'fresh_from_$freshFrom': part((g) => g.day.compareTo(freshFrom) >= 0),
      for (final store in storeNames.keys)
        store: part((g) => g.store == store),
      'unlabeled_next_day': run.unlabeledNextDay,
    };
  }

  // 探索：案ごとの成績を、選ぶ期間・確かめる期間に分けて出し、事前に決めた
  // 規則（選ぶ期間の差がいちばん大きい案。同点は番号の小さい案）で1つ選ぶ。
  Map<String, Object?> explore(BacktestRun run) {
    Map<String, Object?> period(bool Function(BacktestGroup) keep) {
      final groups = run.groups.where(keep).toList();
      final tops = run.topSeven
          .where((t) => groups.any((g) => g.store == t.store && g.day == t.day))
          .toList();
      return {
        'groups': groups.length,
        'prediction_days': {for (final g in groups) g.day}.length,
        'current': evaluateMethod(groups, (m) => m.current),
        'top7_current': evaluateTopSeven(tops, groups, current: true),
        for (final method in exploratoryMethods) ...{
          method.name: evaluateMethod(
            groups,
            (m) => m.exploratory.contains(method),
          ),
          '${method.name}_minus_current': compareMethods(
            groups,
            (m) => m.exploratory.contains(method),
            (m) => m.current,
          ),
          'top7_${method.name}': evaluateTopSevenBy(
            tops,
            groups,
            (t) => t.exploratory[method]!,
            (m) => m.exploratory.contains(method),
          ),
        },
      };
    }

    final select = period((g) => g.day.compareTo(freshFrom) < 0);
    ExploratoryMethod? chosen;
    double? best;
    for (final method in exploratoryMethods) {
      final gap =
          ((select[method.name] as Map)['gap_vs_pool'] as Map)['mean_of_days']
              as double?;
      if (gap != null && (best == null || gap > best)) {
        best = gap;
        chosen = method;
      }
    }
    return {
      'select_period': select,
      'confirm_period': period((g) => g.day.compareTo(freshFrom) >= 0),
      'all': period((_) => true),
      'chosen_by_select_period': chosen?.name,
    };
  }

  // バラエティ（1〜3台の機種、2026-09-29から候補に入れた）：4台以上の機種の
  // 集計（上の main など）とは分けて出す。main は2026-09-29の検証のときと
  // 同じ数字のまま。
  Map<String, Object?> summarizeVariety(BacktestRun run) {
    Map<String, Object?> part(bool Function(BacktestGroup) keep) {
      final variety = run.varietyGroups.where(keep).toList();
      final both = [...run.groups.where(keep), ...variety];
      final tops = run.topSeven
          .where((t) => both.any((g) => g.store == t.store && g.day == t.day))
          .toList();
      return {
        'groups': variety.length,
        'prediction_days': {for (final g in variety) g.day}.length,
        'eligible_racks': variety.fold<int>(0, (n, g) => n + g.members.length),
        'labeled_racks': variety.fold<int>(0, (n, g) => n + g.labeled.length),
        'current': evaluateMethod(variety, (m) => m.current),
        'previous_score': evaluateMethod(variety, (m) => m.previousScore),
        'previous_minus_current': comparePreviousToCurrent(variety),
        'index_correlation': indexCorrelation(variety),
        'with_regular_current': evaluateMethod(both, (m) => m.current),
        'top7_current_with_variety': evaluateTopSeven(
          tops,
          both,
          current: true,
        ),
      };
    }

    return {
      'all': part((_) => true),
      for (final store in storeNames.keys)
        store: part((g) => g.store == store),
      'saved_snapshots': evaluateSavedSnapshots(run.varietyGroups, snapshots),
    };
  }

  final main = runBacktest(full, cutoffFor: (day) => predictionCutoff(day));
  final result = <String, Object?>{
    'scoring_version': scoringVersion,
    'records': full.length,
    'days': {for (final r in full) r.day}.length,
    'main_cutoff_0000': summarize(main),
    'saved_snapshots_cutoff_0000': evaluateSavedSnapshots(main.groups, snapshots),
    'supplement_cutoff_0900': summarize(
      runBacktest(full, cutoffFor: (day) => predictionCutoff(day, hour: 9)),
    ),
    'supplement_ignore_time': summarize(runBacktest(full)),
    'exploratory_cutoff_0000': explore(
      runBacktest(
        full,
        cutoffFor: (day) => predictionCutoff(day),
        exploratory: exploratoryMethods,
      ),
    ),
    'exploratory_supplement_cutoff_0900': explore(
      runBacktest(
        full,
        cutoffFor: (day) => predictionCutoff(day, hour: 9),
        exploratory: exploratoryMethods,
      ),
    ),
    'variety_cutoff_0000': summarizeVariety(
      runBacktest(
        full,
        cutoffFor: (day) => predictionCutoff(day),
        variety: true,
      ),
    ),
    if (earlier.isNotEmpty)
      'supplement_earlier_values_0000': summarize(
        runBacktest(
          full,
          cutoffFor: (day) => predictionCutoff(day),
          earlier: earlier,
        ),
      ),
  };
  final text = const JsonEncoder.withIndent('  ').convert(result);
  final out = option('--out');
  if (out != null) File(out).writeAsStringSync(text);
  stdout.writeln(text);

  final dump = option('--dump-candidates');
  if (dump != null) {
    // 時刻を見ない全データで、各店舗・日付の候補（PC版との照合用）。
    final rows = <Map<String, Object?>>[];
    final days = {for (final r in full) r.day}.toList()..sort();
    for (final day in days) {
      for (final store in storeNames.keys) {
        final dayRows = [
          for (final r in full)
            if (r.day == day && r.store == store) r,
        ];
        if (dayRows.isEmpty) continue;
        for (final c in dayCandidates(dayRows, full).candidates) {
          rows.add({
            'store': store,
            'day': day,
            'machine': c.record.machine,
            'rack': c.record.rack,
            'index': c.index,
            'days': c.days,
          });
        }
      }
    }
    File(dump).writeAsStringSync(jsonEncode(rows));
  }
}
