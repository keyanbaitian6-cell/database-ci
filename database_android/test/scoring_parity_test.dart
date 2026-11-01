import 'dart:convert';
import 'dart:io';

import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter_test/flutter_test.dart';

/// 2026-11-01：採点と翌日候補が、PC（database/core.py）と同じになること。
/// 合成データ（実データではない）と期待値は database/tests/test_scoring_parity.py が作り、
/// PCの試験も同じファイルで自分の計算を確かめる。片方だけ直すと、どちらかの試験が落ちる。
void main() {
  final fixture =
      jsonDecode(File('test/fixtures/scoring_parity.json').readAsStringSync())
          as Map<String, dynamic>;
  final rows = [
    for (final raw in fixture['rows'] as List)
      SlotRecord.fromJson(Map<String, dynamic>.from(raw as Map)),
  ];

  bool same(Object? wanted, Object? actual) =>
      wanted is num && actual is num
      ? (wanted - actual).abs() < 1e-8
      : wanted == actual;

  test('採点版がPCと同じ', () {
    expect(fixture['version'], scoringVersion);
  });

  test('各台の採点がPCと同じ', () {
    final expected = fixture['scores'] as List;
    expect(expected, hasLength(rows.length));
    final differ = <String>[];
    for (var i = 0; i < rows.length; i++) {
      final s = scoreRecord(rows[i], rows);
      final actual = <String, Object?>{
        'games': s.games,
        'max_hold': s.maxHold,
        'hits': s.hits,
        'positive': s.positive,
        'retention': s.retention,
        'total': s.total,
        'reference_count': s.referenceCount,
        'reference_days': s.referenceDays,
        'hold_reference_count': s.holdReferenceCount,
        'coverage': s.coverage,
        'missing_low': s.missingLow,
        'missing_high': s.missingHigh,
        'provisional': s.provisional,
      };
      final wanted = expected[i] as Map;
      for (final entry in actual.entries) {
        if (!same(wanted[entry.key], entry.value)) {
          differ.add(
            '${rows[i].store} ${rows[i].day} ${rows[i].rack} ${entry.key}: '
            'PC=${wanted[entry.key]} Android=${entry.value}',
          );
        }
      }
    }
    expect(differ, isEmpty, reason: differ.take(10).join('\n'));
  });

  test('翌日候補（並び・平均より・日数）がPCと同じ', () {
    final actual = <Map<String, Object?>>[];
    final keys = {for (final r in rows) '${r.store}\t${r.day}'}.toList()
      ..sort();
    for (final key in keys) {
      final [store, day] = key.split('\t');
      final dayRows = [
        for (final r in rows)
          if (r.store == store && r.day == day) r,
      ];
      for (final c in dayCandidates(dayRows, rows).candidates) {
        actual.add({
          'store': store,
          'day': day,
          'machine': c.record.machine,
          'rack': c.record.rack,
          'index': c.index,
          'days': c.days,
        });
      }
    }
    final expected = (fixture['candidates'] as List).cast<Map>();
    expect(actual, hasLength(expected.length));
    for (var i = 0; i < expected.length; i++) {
      for (final key in ['store', 'day', 'machine', 'rack', 'index', 'days']) {
        expect(
          same(expected[i][key], actual[i][key]),
          isTrue,
          reason: '$i $key: PC=${expected[i][key]} Android=${actual[i][key]}',
        );
      }
    }
  });
}
