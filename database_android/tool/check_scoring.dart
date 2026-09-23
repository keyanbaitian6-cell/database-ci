import 'dart:convert';
import 'dart:io';

import '../lib/models.dart';
import '../lib/scoring.dart';

void main() {
  assert(spinScore(499) == 0);
  assert(spinScore(500) == 0);
  assert(spinScore(3500) == 0);

  final decoded = jsonDecode(
    File('assets/database_seed.json').readAsStringSync(),
  ) as Map<String, dynamic>;
  final rows = (decoded['rows'] as List)
      .map((e) => SlotRecord.fromJson(Map<String, dynamic>.from(e as Map)))
      .toList();
  if (rows.length != 110) {
    throw StateError('seed row count: ${rows.length}');
  }
  final row = rows.singleWhere(
    (r) => r.day == '2026-09-15' && r.machine == 'L+防振り+FN' && r.rack == 303,
  );
  final result = scoreRecord(row, rows);
  if (result.positive != 10 ||
      (result.retention! - 8.622754491017965).abs() > .001) {
    throw StateError(
      '303 score mismatch: ${result.positive}/${result.retention}',
    );
  }
  print('scoring checks passed: ${rows.length} seed rows');
}
