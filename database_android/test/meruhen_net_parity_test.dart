import 'dart:convert';
import 'dart:io';

import 'package:database_android/meruhen_net.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

/// 2026-10-25：閲覧ページはグラフの線を起動時に読まず、Googleが線から計算して添えた推定差枚
/// （tool/viewer_curves_split.js）を使う。閲覧ページが線から計算する値と1枚も違わないこと。
/// 合成データは tool/make_meruhen_net_parity.mjs（共有カレンダーの net.mjs で期待値を作る）。
void main() {
  final fixture =
      jsonDecode(
            File('test/fixtures/meruhen_net_parity.json').readAsStringSync(),
          )
          as Map<String, dynamic>;
  final records = (fixture['records'] as List).cast<Map<String, dynamic>>();
  final expected = (fixture['expected'] as List).cast<Map<String, dynamic>>();

  ({int? value, bool check}) want(Map<String, dynamic> raw, int i) =>
      meruhenNetHidden(raw['store'] as String, raw['day'] as String)
      ? (value: null, check: false)
      : (
          value: expected[i]['value'] as int?,
          check: expected[i]['needs_check'] as bool,
        );

  Map<String, dynamic> light(Map<String, dynamic> raw, int i) {
    final graph = Map<String, dynamic>.from(raw['graph_measurement'] as Map)
      ..remove('curve');
    return {
      ...raw,
      'graph_measurement': {
        ...graph,
        'curve_remote': true,
        'curve_index': i,
        'net_estimate': {
          ...expected[i],
          'max_hold': raw['max_hold'],
          'games': raw['games'] ?? 0,
        },
      },
    };
  }

  test('線から計算した値は、共有カレンダーの規則（合成600件）と同じ', () {
    for (var i = 0; i < records.length; i++) {
      final r = SlotRecord.fromJson(records[i]);
      expect(
        (value: r.estimatedNetMedals, check: r.netNeedsCheck),
        want(records[i], i),
        reason: '${records[i]['rack']}番',
      );
    }
  });

  test('線を外した記録は添えた値を使い、線を読んだあとも同じ値', () {
    for (var i = 0; i < records.length; i++) {
      final r = SlotRecord.fromJson(light(records[i], i));
      expect(r.graph!.curve, isNull);
      expect(
        (value: r.estimatedNetMedals, check: r.netNeedsCheck),
        want(records[i], i),
      );
      final curve = SavedCurve(
        (records[i]['graph_measurement'] as Map)['curve'] as List,
      );
      final loaded = r.copyWith(graph: r.graph!.withCurve(curve));
      expect(
        (value: loaded.estimatedNetMedals, check: loaded.netNeedsCheck),
        want(records[i], i),
      );
    }
  });

  test('最大持玉・回転数が計算時と違う記録は、ずれた値を出さない', () {
    final i = expected.indexWhere((e) => e['value'] != null);
    final raw = light(records[i], i);
    expect(
      SlotRecord.fromJson({
        ...raw,
        'games': (raw['games'] as int) + 1,
      }).estimatedNetMedals,
      isNull,
    );
    expect(
      SlotRecord.fromJson({...raw, 'max_hold': 1}).estimatedNetMedals,
      isNull,
    );
  });

  test('閲覧ページの読み込みで、線の参照・添えた値・番号を保持する', () {
    final doc = {
      'header': {
        'format': 'database-backup',
        'version': 1,
        'exported_at': '2026-10-25T12:00:00+09:00',
        'curve_parts': [
          {'day': '2026-10-02', 'hash': 'a' * 64, 'count': 1, 'bytes': 10},
          {'day': 'bad'},
        ],
      },
      'records': [
        {...light(records[1], 0), 'kind_code': 21, 'bb': 1, 'rb': 1},
      ],
    };
    final data = ViewerData.parse(jsonEncode(doc));
    expect(data.curveParts, hasLength(1));
    final graph = data.records.single.graph!;
    expect(graph.remoteCurve, isTrue);
    expect(graph.curveIndex, 0);
    expect(graph.netEstimate!.games, records[1]['games'] ?? 0);
    expect(graph.toJson()['net_estimate'], isNotNull);
  });
}
