import 'dart:convert';
import 'dart:io';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';

/// Run after the PC read-only audit. This does not build/install an APK.
void main(List<String> args) {
  final path = args.isEmpty ? '../database/reports/scoring-v8-audit/parity.json' : args.first;
  final fixture = jsonDecode(File(path).readAsStringSync()) as Map;
  if (fixture['version'] != scoringVersion) throw StateError('Version mismatch');
  final rows = (fixture['rows'] as List).map((r) => SlotRecord.fromJson(Map<String,dynamic>.from(r as Map))).toList();
  final expected = fixture['expected'] as List;
  for (var i = 0; i < rows.length; i++) {
    final s = scoreRecord(rows[i], rows);
    final actual = <String, Object?>{
      'games': s.games, 'max_hold': s.maxHold, 'hits': s.hits,
      'positive': s.positive, 'retention': s.retention, 'total': s.total,
      'reference_count': s.referenceCount, 'reference_days': s.referenceDays,
      'hold_reference_count': s.holdReferenceCount, 'coverage': s.coverage,
      'missing_low': s.missingLow, 'missing_high': s.missingHigh, 'provisional': s.provisional,
    };
    for (final entry in actual.entries) {
      final wanted = (expected[i] as Map)[entry.key];
      final value = entry.value;
      final equal = wanted is num && value is num
          ? (wanted - value).abs() < 1e-8 : wanted == value;
      if (!equal) throw StateError('${rows[i].key}: ${entry.key}: Python=$wanted Dart=$value');
    }
  }
  stdout.writeln('Python/Dart parity OK: ${rows.length} rows, version $scoringVersion');
}
