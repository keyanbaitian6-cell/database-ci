import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/graph_gate.dart';
import 'package:database_android/models.dart';

/// Real captures shared with the PC app's tests (database/observed_graphs.json).
List<({int rack, List<Offset> curve, double baseline})> observed() {
  final decoded = jsonDecode(
    File('../database/observed_graphs.json').readAsStringSync(),
  ) as Map<String, dynamic>;
  return (decoded['records'] as List).map((raw) {
    final record = raw as Map<String, dynamic>;
    final numbers = (record['xy'] as String)
        .split(',')
        .map(double.parse)
        .toList();
    return (
      rack: record['rack'] as int,
      curve: [
        for (var i = 0; i + 1 < numbers.length; i += 2)
          Offset(numbers[i], numbers[i + 1]),
      ],
      baseline: (record['baseline'] as num).toDouble(),
    );
  }).toList();
}

SlotRecord saved({GraphMeasurement? graph}) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-13',
  machine: 'テスト機',
  rack: 128,
  games: 3500,
  bb: 20,
  rb: 10,
  maxHold: 2000,
  graph: graph,
);

List<String> gate(
  ({int rack, List<Offset> curve, double baseline}) capture, {
  List<Offset>? curve,
  double? baseline,
  double width = 682,
  int games = 3500,
  SlotRecord? existing,
  bool noExisting = false,
}) => graphAutoSaveBlockers(
  curve: curve ?? capture.curve,
  baselineY: baseline ?? capture.baseline,
  width: width,
  games: games,
  bb: 20,
  rb: 10,
  maxHold: 2000,
  existing: noExisting ? null : (existing ?? saved()),
);

void main() {
  final captures = observed();

  test('実測14台はすべて自動保存の条件を通る', () {
    expect(captures.length, 14);
    for (final capture in captures) {
      expect(gate(capture), isEmpty, reason: '${capture.rack}番台');
    }
  });

  test('疑わしいグラフは確認画面に回す', () {
    final capture = captures.first;
    expect(gate(capture, curve: capture.curve.take(5).toList()), isNotEmpty);
    expect(gate(capture, baseline: 150), isNotEmpty); // 開始がゼロ線と不一致
    expect(gate(capture, width: 2000), isNotEmpty); // 右端まで届いていない
    expect(
      gate(
        capture,
        curve: [
          ...capture.curve.take(capture.curve.length - 1),
          Offset(682, capture.baseline),
        ],
      ),
      isNotEmpty,
    ); // 終点がゼロ線
    expect(gate(capture, games: 999), isNotEmpty); // 一覧と数値が違う
    expect(gate(capture, noExisting: true), isNotEmpty); // 一覧が未取り込み
    expect(
      gate(
        capture,
        existing: saved(
          graph: const GraphMeasurement(
            baselineY: 200,
            peakY: 100,
            troughY: 250,
            endY: 150,
          ),
        ),
      ),
      isNotEmpty,
    ); // 既にグラフあり
  });

  test('スクリーンショット由来（線データなし）は自動保存しない', () {
    expect(
      graphAutoSaveBlockers(
        curve: null,
        baselineY: null,
        width: 400,
        games: 3500,
        bb: 20,
        rb: 10,
        maxHold: 2000,
        existing: saved(),
      ),
      isNotEmpty,
    );
  });
}
