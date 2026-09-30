import 'dart:convert';
import 'dart:io';

import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/reference_candidate_comparison.dart';
import 'package:database_android/scoring.dart';

/// Analysis only; never changes DB, app selections, or saved predictions.
/// dart tool/compare_reference_candidates.dart --json BACKUP --out RESULT_OUTSIDE_REPO
/// Optional --source-sha256 is the externally verified SHA-256 of the input.
void main(List<String> args) {
  String? option(String key) {
    final i = args.indexOf(key);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final jsonPath = option('--json'), output = option('--out');
  if (jsonPath == null || output == null) {
    stderr.writeln('--json <バックアップ> --out <リポジトリ外の結果.json> が必要です。');
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
    throw const FormatException('救出用ファイルを通常の比較データには使えません。');
  }
  final full = normalizeForBacktest([
    for (final item in doc['records'] as List) _readRecord(item),
  ]);
  final groups = buildReferenceComparison(full);
  final result = {
    'protocol': 'NEXT_DAY_REFERENCE_REVIEW_20260930.md',
    'scoring_version': scoringVersion,
    'input_exported_at': doc['exported_at'],
    'input_sha256_externally_verified': option('--source-sha256'),
    'raw_records': (doc['records'] as List).length,
    'normalized_records': full.length,
    'record_days': {for (final r in full) r.day}.length,
    'cutoff': 'Before next-day 00:00 JST, captured_at required, no earlier-value repair',
    'half_life_calendar_days': referenceHalfLifeDays,
    'bootstrap_rounds': 10000,
    'bootstrap_seed': referenceBootstrapSeed,
    'interpretation': {
      'retrospective_exploration_on_previously_seen_data': true,
      'additional_methods_compared': 3,
      'gate_results_conditional_on_selection_and_evaluable_outcome': true,
      'primary_unit': 'Equal-weight group means within each prediction day, then equal-weight prediction days; pooled rack means are descriptive only',
      'gate_rounding': 'currentGate uses current rounded index >50; recentGate uses raw recent index >50',
      'recent_shrinkage': 'Calendar decay also strengthens shrinkage towards 50; not merely a ranking effect',
      'bootstrap_limitation': 'IID day resampling does not account for dependence from overlapping histories/events; CI may be too narrow and is descriptive, not evidence for adoption',
      'production_candidate_selection_changed': false,
      'future_confirmation': 'Fixed 2026-09-30 through 2026-10-29; final once on or after 2026-10-31, >=20 evaluable days, both stores positive, check 5-day and 10-day moving-block intervals and coverage; no automatic adoption or monitoring',
    },
    'comparison': summarizeReferenceComparison(groups),
  };
  File(output)
      .writeAsStringSync(const JsonEncoder.withIndent('  ').convert(result));
  final all = (result['comparison'] as Map)['all'] as Map;
  stdout.writeln(
    jsonEncode({
      'output': output,
      'raw_records': result['raw_records'],
      'normalized_records': full.length,
      'population': all['fixed_population'],
      'methods': {
        for (final entry in (all['methods'] as Map).entries)
          entry.key: {
            'selected': entry.value['selected'],
            'evaluable': entry.value['evaluable'],
            'no_selection_groups': entry.value['no_selection_groups'],
            'selected_but_unscored_groups':
                entry.value['selected_but_unscored_groups'],
            'gap_vs_fixed_pool': entry.value['gap_vs_fixed_pool'],
            'minus_current':
                entry.value['minus_current_on_common_evaluable_groups'],
            'repeat_rate': entry.value['consecutive_repeat']['repeat_rate'],
          },
      },
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
