import 'dart:convert';
import 'dart:io';

import 'package:database_android/candidate_log.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/focus_final_evaluation.dart';
import 'package:database_android/focus_validation.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';

/// 未来の固定期間の集計（分析専用。DB・画面の★・保存済みの候補は変えない）。
/// 条件は NEXT_DAY_FOCUS_PLAN_20260930.md の「5. 最終評価の集計」。
///
/// dart run tool/focus_final_evaluation.dart --json BACKUP --out RESULT_OUTSIDE_REPO
///     [--mode progress|interim|final] [--source-sha256 SHA]
///     [--last-label-day-missing-ok] [--from YYYY-MM-DD --through YYYY-MM-DD]
///
/// progress：翌日の点数を使わない進捗・データ品質・選び方の性質だけ（既定）。
/// interim：両方式の途中の成績も出す。採否の判定は出さない（判断に使わない）。
/// final：2026-10-31（日本時間）以降だけ。採用条件を判定する。1回だけ実行する。
/// --from/--through：固定期間以外（例：方式を選んだ9/22〜9/29）を回顧的な参考として
/// 集計する。採否の判定には使わない（final では指定できない）。
void main(List<String> args) {
  String? option(String key) {
    final i = args.indexOf(key);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final jsonPath = option('--json'), output = option('--out');
  final mode = option('--mode') ?? 'progress';
  final from = option('--from') ?? focusValidationFrom;
  final through = option('--through') ?? focusValidationThrough;
  final reference =
      from != focusValidationFrom || through != focusValidationThrough;
  if (jsonPath == null ||
      output == null ||
      !const ['progress', 'interim', 'final'].contains(mode)) {
    stderr.writeln(
      '--json <バックアップ> --out <リポジトリ外の結果.json> '
      '[--mode progress|interim|final] が必要です。',
    );
    exitCode = 64;
    return;
  }
  final repo = File.fromUri(Platform.script).parent.parent.parent.absolute.path
      .toLowerCase();
  final target = File(output).absolute.path.toLowerCase();
  if (target == repo || target.startsWith('$repo${Platform.pathSeparator}')) {
    throw ArgumentError('結果は実データと同様、リポジトリの外へ保存してください。');
  }
  final doc = jsonDecode(File(jsonPath).readAsStringSync());
  if (doc is! Map ||
      doc['format'] != 'database-backup' ||
      doc['records'] is! List) {
    throw const FormatException('databaseのバックアップではありません。');
  }
  if ((doc['recovery_required'] ?? 0) != 0) {
    throw const FormatException('救出用ファイルを通常の集計には使えません。');
  }
  final rawRecords = doc['records'] as List;
  final full = normalizeForBacktest([
    for (final item in rawRecords) _readRecord(item),
  ]);
  if (mode == 'final' && reference) {
    stderr.writeln('最終評価は固定期間（--from/--through なし）でだけ実行します。');
    exitCode = 64;
    return;
  }
  if (mode == 'final') {
    final blocker = focusFinalBlocker(
      DateTime.now(),
      full,
      lastLabelDayMissingOk: args.contains('--last-label-day-missing-ok'),
    );
    if (blocker != null) {
      stderr.writeln('最終評価は実行できません：$blocker');
      exitCode = 65;
      return;
    }
  }
  final snapshots = [
    for (final raw in (doc['candidate_snapshots'] as List? ?? const []))
      ?CandidateSnapshot.tryFromJson(raw),
  ];
  final groups = buildFocusValidation(full, from: from, through: through);
  final days = {for (final r in full) r.day}.toList()..sort();
  final result = <String, Object?>{
    'protocol': 'NEXT_DAY_FOCUS_PLAN_20260930.md section 5',
    'mode': mode,
    'period': [from, through],
    if (reference) 'reference_period_not_for_adoption': 'Retrospective reference: these days were seen when the method was chosen. Never counts toward the fixed-period judgment.',
    'run_at': DateTime.now().toUtc().toIso8601String(),
    'scoring_version': scoringVersion,
    'method_version': nextDayMethodVersion,
    'input_exported_at': doc['exported_at'],
    'input_sha256_externally_verified': option('--source-sha256'),
    'raw_records': rawRecords.length,
    'normalized_records': full.length,
    'merged_duplicates': rawRecords.length - full.length,
    'record_day_range': days.isEmpty ? null : [days.first, days.last],
    'record_days': days.length,
    'candidate_snapshots': snapshots.length,
    'fixed': {
      'period': [focusValidationFrom, focusValidationThrough],
      'final_on_or_after': focusValidationFinalOn,
      'cutoff':
          'Before next-day 0$focusCutoffHour:00 JST (business day); captured_at required; no earlier-value repair',
      'sensitivity_cutoff':
          'Before next-day 00:00 JST, reported only, never used for adoption',
      'bootstrap_rounds': focusFinalBootstrapRounds,
      'bootstrap_seed': focusFinalBootstrapSeed,
      'minimum_days': focusFinalMinimumDays,
      'block_days_main': focusFinalMainBlockDays,
      'block_days_sensitivity': focusFinalSensitivityBlockDays,
      'minimum_blocks': focusFinalMinimumBlocks,
      'coverage_tolerance': focusFinalCoverageTolerance,
    },
    'record_quality': focusRecordQuality(full),
    'progress': focusProgress(groups, full, from: from, through: through),
    'snapshots': focusSnapshotProgress(snapshots, from: from, through: through),
    'selection_profile': {
      'all': focusSelectionProfile(groups),
      'by_store': {
        for (final store in storeNames.keys)
          store: focusSelectionProfile(
            groups.where((g) => g.baseline.store == store).toList(),
          ),
      },
    },
  };
  if (mode != 'progress') {
    result['outcomes'] = focusOutcomeSummary(groups);
    final midnight = buildFocusValidation(
      full,
      cutoffHour: 0,
      from: from,
      through: through,
    );
    result['sensitivity_cutoff_0000'] = {
      'progress': focusProgress(midnight, full, from: from, through: through),
      'outcomes': focusOutcomeSummary(midnight),
    };
  }
  if (mode == 'interim') {
    result['interim_not_for_decision'] = 'Interim numbers only. No adoption judgment; the fixed period and conditions do not change.';
  }
  if (mode == 'final') {
    result['adoption_judgment'] = focusAdoptionJudgment(groups);
  }
  File(output)
      .writeAsStringSync(const JsonEncoder.withIndent('  ').convert(result));
  stdout.writeln(
    jsonEncode({
      'output': output,
      'mode': mode,
      'normalized_records': full.length,
      'prediction_days_with_labeled_groups':
          (result['progress'] as Map)['prediction_days_with_labeled_groups'],
      if (mode == 'final')
        'adopt': (result['adoption_judgment'] as Map)['adopt'],
    }),
  );
}

SlotRecord _readRecord(Object? item) {
  if (item is! Map || item.containsKey('unreadable_record')) {
    throw const FormatException('台の記録に読めない項目があります。');
  }
  final raw = Map<String, dynamic>.from(item);
  final graph = raw['graph_measurement'];
  if (graph is Map) {
    raw['graph_measurement'] = Map<String, dynamic>.from(graph)
      ..remove('preview_image')
      ..remove('preview_stored')
      ..remove('curve_stored');
  }
  return SlotRecord.fromJson(raw);
}
