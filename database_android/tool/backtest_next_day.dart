import 'dart:convert';
import 'dart:io';

import 'package:database_android/candidate_log.dart';
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
