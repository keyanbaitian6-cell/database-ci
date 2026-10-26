import 'dart:async';

import 'package:database_android/models.dart';
import 'package:database_android/remote_curve.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord record() => SlotRecord.fromJson({
  'store': 'saiwaichou',
  'day': '2026-10-24',
  'machine': '合成機種',
  'rack': 1,
  'games': 1000,
  'bb': 3,
  'rb': 2,
  'graph_measurement': {
    'baseline_y': 10,
    'peak_y': 0,
    'end_y': 5,
    'curve_remote': true,
    'curve_index': 0,
  },
});
void main() {
  tearDown(() {
    clearRemoteCurves();
    remoteCurveFetcher = null;
  });
  test('同じ日と通し番号でも記録に結び付いた版の線だけを使う', () async {
    final old = record(), current = record();
    Future<Map<int, List<List<double>>>> before(String _) async => {
      0: [
        [0, 10],
        [1, 20],
      ],
    };
    Future<Map<int, List<List<double>>>> after(String _) async => {
      0: [
        [0, 30],
        [1, 40],
      ],
    };
    bindRemoteCurves([old], before);
    remoteCurveFetcher = before;
    expect((await loadRemoteCurve(old)).graph!.curve!.last.last, 20);
    clearRemoteCurves();
    bindRemoteCurves([current], after);
    remoteCurveFetcher = after;
    expect((await loadRemoteCurve(current)).graph!.curve!.last.last, 40);
    expect((await loadRemoteCurve(old)).graph!.curve!.last.last, 20);
  });
  test('遅れた古い応答で新しい版のキャッシュを置き換えない', () async {
    final old = record(),
        current = record(),
        pending = Completer<Map<int, List<List<double>>>>();
    Future<Map<int, List<List<double>>>> before(String _) => pending.future;
    Future<Map<int, List<List<double>>>> after(String _) async => {
      0: [
        [0, 30],
        [1, 40],
      ],
    };
    bindRemoteCurves([old], before);
    remoteCurveFetcher = before;
    final waiting = loadRemoteCurve(old);
    clearRemoteCurves();
    bindRemoteCurves([current], after);
    remoteCurveFetcher = after;
    expect((await loadRemoteCurve(current)).graph!.curve!.last.last, 40);
    pending.complete({
      0: [
        [0, 10],
        [1, 20],
      ],
    });
    await waiting;
    expect((await loadRemoteCurve(current)).graph!.curve!.last.last, 40);
  });
}
