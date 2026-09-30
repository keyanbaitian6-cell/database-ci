import 'dart:convert';
import 'dart:io';

import 'package:database_android/low_activity_candidate_comparison.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';

/// Read-only offline analysis. Aggregate output must remain outside the repo.
void main(List<String> args) {
  String? option(String key) {
    final i = args.indexOf(key);
    return i >= 0 && i + 1 < args.length ? args[i + 1] : null;
  }

  final input = option('--json'), output = option('--out');
  if (input == null || output == null) {
    throw ArgumentError('--json BACKUP --out RESULT_OUTSIDE_REPO required');
  }
  final repo = File.fromUri(Platform.script).parent.parent.parent
      .resolveSymbolicLinksSync()
      .toLowerCase();
  final parent = File(output).absolute.parent
      .resolveSymbolicLinksSync()
      .toLowerCase();
  if (parent == repo ||
      parent.startsWith('$repo${Platform.pathSeparator}') ||
      FileSystemEntity.isLinkSync(output)) {
    throw ArgumentError('Output must be outside the repo and not a symlink');
  }
  final doc = jsonDecode(File(input).readAsStringSync());
  if (doc is! Map ||
      doc['format'] != 'database-backup' ||
      doc['records'] is! List ||
      (doc['recovery_required'] ?? 0) != 0) {
    throw const FormatException('Normal database backup required');
  }
  final full = normalizeForBacktest([
    for (final item in doc['records'] as List) _record(item),
  ]);
  final comparison = summarizeLowActivityComparison(
    buildLowActivityComparison(full),
  );
  final result = {
    'protocol': 'CANDIDATE_LOW_ACTIVITY_REVIEW_20260930.md',
    'scoring_version': scoringVersion,
    'input_exported_at': doc['exported_at'],
    'input_sha256_externally_verified': option('--source-sha256'),
    'raw_records': (doc['records'] as List).length,
    'normalized_records': full.length,
    'bootstrap_rounds': 10000,
    'bootstrap_seed': 20260930,
    'interpretation': {
      'production_candidate_selection_changed': false,
      'retrospective_exploration_on_previously_seen_data': true,
      'additional_methods_compared': 3,
      'population': 'Only groups with production candidates; no-baseline-candidate groups are excluded by runBacktest',
      'missing': 'Missing/abnormal records are not zero games; unscored records are not zero scores',
      'features': 'Exact 3 calendar days with valid records; score requires >=2 scored days',
      'cutoff':
          'Before next-day 00:00 JST with captured_at; no earlier-value repair',
      'confidence': 'IID day bootstrap descriptive only; overlap/events dependence and multiple comparisons prevent adoption proof',
      'variety': 'Games across different machines also reflects popularity, not a causal setting signal',
    },
    'comparison': comparison,
  };
  File(output)
      .writeAsStringSync(const JsonEncoder.withIndent('  ').convert(result));
  stdout.writeln(
    jsonEncode({
      'output': output,
      'population': (comparison['all'] as Map)['fixed_population'],
    }),
  );
}

SlotRecord _record(Object? item) {
  if (item is! Map ||
      item['day'] is! String ||
      item.containsKey('unreadable_record')) {
    throw const FormatException('Invalid record');
  }
  final clean = Map<String, dynamic>.from(item);
  final graph = clean['graph_measurement'];
  if (graph is Map) {
    clean['graph_measurement'] = Map<String, dynamic>.from(graph)
      ..remove('preview_image')
      ..remove('preview_stored')
      ..remove('curve_stored');
  }
  return SlotRecord.fromJson(clean);
}
