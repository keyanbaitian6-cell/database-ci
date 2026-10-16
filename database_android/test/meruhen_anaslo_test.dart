import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/data_checks.dart';
import 'package:database_android/meruhen_net.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';

/// 幸町のアナスロ補完（2026-10-16 利用者決定「通常の記録として採点・翌日候補にも使う」）。
/// P’s CUBEの補完は今までどおり外す（anaslo_import_test.dart）。PC版 core.py と同じ扱い。
SlotRecord rec(
  String day,
  int rack, {
  bool anaslo = false,
  String store = 'saiwaichou',
  int bb = 10,
}) => SlotRecord(
  store: store,
  day: day,
  machine: 'M',
  rack: rack,
  games: 3000,
  bb: bb,
  rb: 5,
  extra: anaslo ? const {'source_site': 'anaslo'} : const {},
);

void main() {
  final history = [
    for (var d = 1; d <= 9; d++)
      for (var rack = 1; rack <= 4; rack++)
        rec('2026-09-0$d', rack, anaslo: true, bb: 6 + rack * 2),
  ];
  final today = rec('2026-09-10', 1);

  test('meruhen supplements count as comparison data', () {
    expect(isExcludedSupplement(history.first), isFalse);
    expect(comparisonPool(today, [...history, today]).length, history.length);
  });

  test('next-day evidence and variety use meruhen supplements', () {
    final all = [...history, today];
    expect(nextDayEvidence(today, all).usedDays, greaterThanOrEqualTo(3));
    final supplement = history.last;
    expect(varietyHitPercent(supplement, all).percent, isNotNull);
  });

  test('graph from the anaslo source scores its shape but gives no net', () {
    // PC版 anaslo_converter.graph_measurement_from_source の出力（片側1000→180px）。
    final record = SlotRecord.fromJson({
      'store': 'saiwaichou',
      'kind_code': 21,
      'day': '2026-09-10',
      'machine': 'M',
      'rack': 1,
      'games': 3500,
      'bb': 10,
      'rb': 5,
      'max_hold': null,
      'source_site': 'anaslo',
      'graph_measurement': {
        'baseline_x': 0.5,
        'baseline_y': 200.5,
        'peak_x': 20.5,
        'peak_y': 20.5,
        'trough_x': 0.5,
        'trough_y': 200.5,
        'end_x': 30.5,
        'end_y': 110.5,
        'curve': [
          [0.5, 200.5],
          [10.5, 146.5],
          [20.5, 20.5],
          [30.5, 110.5],
        ],
        'method': 'anaslo-source-graph',
      },
    });
    final score = scoreRecord(record, [...history, record]);
    expect(score.positive, 10);
    expect(score.retention, 5);
    expect(varietyState(record), VarietyState.plus);
    final g = record.graph!;
    expect(
      meruhenNetEstimate(
        baselineY: g.baselineY,
        peakY: g.peakY,
        troughY: g.troughY,
        endY: g.endY,
        curve: g.curve,
        maxHold: record.maxHold,
        games: record.games,
      ),
      isNull,
    );
  });

  test('a P’s CUBE supplement is still excluded', () {
    final pscube = rec(
      '2026-09-01',
      1,
      anaslo: true,
      store: 'pscube:c740601:20',
    );
    expect(isExcludedSupplement(pscube), isTrue);
    const store = 'pscube:c740601:20';
    final pscubeHistory = [
      for (final r in history)
        rec(r.day, r.rack, anaslo: true, store: store, bb: r.bb),
    ];
    final pscubeToday = rec('2026-09-10', 1, store: store);
    expect(comparisonPool(pscubeToday, [...pscubeHistory, pscubeToday]), isEmpty);
    expect(
      nextDayEvidence(pscubeToday, [...pscubeHistory, pscubeToday]).usedDays,
      lessThanOrEqualTo(1),
    );
  });
}
