import 'dart:convert';
import 'dart:math';

import 'package:database_android/calendar_day_net.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

/// 段階B1（VIEWER_DAY_STORE.md、2026-11-18）：日別キャッシュから1日ずつ作ったカレンダーの差枚が、
/// 今のカレンダーの計算（全記録を [ViewerData.parse] で読んで [dailyNet]）と、全店・全日で1マスも違わないこと。
/// 合成データは、グラフの線を外して差枚を添えた記録・線のある記録・グラフの無い記録・数値異常・ゲーム数0・
/// 読めない記録・対象外の機種・同じ台の重複（機種名の表記ゆれを含む）を混ぜる。

String dayText(int i) {
  final d = DateTime.utc(2026, 1, 1).add(Duration(days: i));
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)}';
}

Map<String, List<Map<String, dynamic>>> synthetic(int days, {int seed = 7}) {
  final rnd = Random(seed);
  final byDay = <String, List<Map<String, dynamic>>>{};
  for (var i = 0; i < days; i++) {
    final day = dayText(i);
    final rows = byDay[day] = [];
    for (final store in ['nagamachiminami', 'saiwaichou']) {
      // 日によって台数を変え、まれに1台も無い日・全部が読めない日を作る。
      final racks = i % 37 == 5 ? 0 : 20 + rnd.nextInt(25);
      for (var rack = 1; rack <= racks; rack++) {
        final games = 500 + rnd.nextInt(7000);
        final base = <String, dynamic>{
          'store': store,
          'day': day,
          'machine': rack.isEven ? 'ハナハナ' : 'ジャグラー',
          'rack': rack,
          'games': games,
          'bb': rnd.nextInt(40) + 1,
          'rb': rnd.nextInt(30) + 1,
        };
        switch (rack % 8) {
          case 0: // 線を外し、差枚を添えた記録
            final maxHold = 300 + rnd.nextInt(2000);
            rows.add({
              ...base,
              'max_hold': maxHold,
              'graph_measurement': {
                'baseline_y': 200.5,
                'peak_y': 100.5,
                'end_y': 150.5,
                'curve_remote': true,
                'curve_index': rack,
                'net_estimate': {
                  'value': rnd.nextInt(6000) - 3000,
                  'needs_check': rnd.nextBool(),
                  'max_hold': maxHold,
                  'games': games,
                },
              },
            });
          case 1: // 線のある記録
            final heights = [
              for (var k = 0; k < 6; k++) 20.0 + rnd.nextInt(150),
            ];
            final ys = [for (final h in heights) 200.5 - h];
            rows.add({
              ...base,
              'max_hold': 300 + rnd.nextInt(2000),
              'graph_measurement': {
                'baseline_y': 200.5,
                'peak_y': ys.reduce(min),
                'trough_y': ys.reduce(max),
                'end_y': ys.last,
                'curve': [
                  for (final (k, y) in ys.indexed) [k * 10.0 + 0.5, y],
                ],
              },
            });
          case 2: // グラフの無い記録
            rows.add(base);
          case 3: // 数値異常（差枚に入れない）
            rows.add({...base, 'games': 88888888, 'bb': 888, 'rb': 888});
          case 4: // ゲーム数0
            rows.add({...base, 'games': 0, 'bb': 0, 'rb': 0});
          case 5: // 差枚が計算できなかった記録（値なし）
            rows.add({
              ...base,
              'graph_measurement': {
                'baseline_y': 200.5,
                'peak_y': 100.5,
                'end_y': 150.5,
                'curve_remote': true,
                'curve_index': rack,
                'net_estimate': {
                  'value': null,
                  'needs_check': false,
                  'max_hold': null,
                  'games': games,
                },
              },
            });
          case 6: // 同じ台が2回（ゲーム数の違い、機種名の表記ゆれ）
            rows.add({...base, 'machine': 'ハナ+ハナ'});
            rows.add({...base, 'machine': 'ハナ ハナ', 'games': games + 1});
          default:
            rows.add(base);
        }
      }
      if (i % 11 == 0) {
        // 読めない記録・対象外の記録（どちらの読み方でも除く）。
        rows.addAll([
          {...rowOf(store, day, 901), 'rack': 1.5},
          {...rowOf(store, day, 902), 'store': 'unknown'},
          {...rowOf(store, day, 903), 'machine': ''},
          {...rowOf(store, day, 904), 'kind_code': 20},
          {...rowOf(store, day, 905), 'day': '2026-13-40'},
          if (store == 'saiwaichou')
            {...rowOf(store, day, 906), 'machine': '聖闘士星矢海皇覚醒'},
        ]);
      }
    }
  }
  return byDay;
}

Map<String, dynamic> rowOf(String store, String day, int rack) => {
  'store': store,
  'day': day,
  'machine': 'ハナハナ',
  'rack': rack,
  'games': 3000,
  'bb': 10,
  'rb': 5,
};

/// JS から Dart へは文字（JSON）で渡るので、同じく文字を通す。
List<Object?> viaJson(List<Map<String, dynamic>> rows) =>
    jsonDecode(jsonEncode(rows)) as List;

void main() {
  for (final days in [108, 180, 365]) {
    test('日別キャッシュから1日ずつ作った差枚は、全記録から作った差枚と全マス一致（$days日）', () {
      final byDay = synthetic(days);
      final all = [for (final rows in byDay.values) ...rows];
      final data = ViewerData.parse(jsonEncode({'records': all}));
      final table = DayNetTable();
      for (final rows in byDay.values) {
        table.addDay(viaJson(rows));
      }
      final result = compareDayNets(table, data.records);
      expect(result['mismatched'], 0, reason: '${result['examples']}');
      expect(result['status'], 'match');
      // 空振りの照合にならないよう、差枚のあるマス・勝率のマス・欠けた日があることを確かめる。
      expect(table.cells.length, greaterThan(days));
      expect(result['cells'], table.cells.length);
      expect(table.cells.values.where((d) => d.total != null).length,
          greaterThan(days));
      expect(table.cells.values.where((d) => d.needsCheck > 0).length,
          greaterThan(0));
      expect(table.cells.values.where((d) => d.judged > 0).length,
          greaterThan(days));
    });
  }

  test('1マスでも違えば、一致しないマスとして数え、例を出す', () {
    final byDay = synthetic(40);
    final all = [for (final rows in byDay.values) ...rows];
    final data = ViewerData.parse(jsonEncode({'records': all}));

    // ① 1日の差枚の値が違う。
    // 入れ子の項目まで写す（元の合成データを書き換えない）。
    final changed = {
      for (final e in byDay.entries)
        e.key: (jsonDecode(jsonEncode(e.value)) as List)
            .cast<Map<String, dynamic>>(),
    };
    final target = changed[dayText(3)]!.firstWhere(
      (r) => (r['graph_measurement'] as Map?)?['net_estimate'] is Map,
    );
    ((target['graph_measurement'] as Map)['net_estimate']
            as Map<String, dynamic>)['value'] =
        99999;
    var table = DayNetTable();
    for (final rows in changed.values) {
      table.addDay(viaJson(rows));
    }
    var result = compareDayNets(table, data.records);
    expect(result['status'], 'mismatch');
    expect(result['mismatched'], 1);
    final example = (result['examples'] as List).single as Map;
    expect(example['day'], dayText(3));
    expect(example['old'], isNot(example['next']));

    // ② 日別キャッシュに1日足りない（その日の2店のマスが欠ける）。
    table = DayNetTable();
    for (final e in byDay.entries) {
      if (e.key != dayText(4)) table.addDay(viaJson(e.value));
    }
    result = compareDayNets(table, data.records);
    expect(result['status'], 'mismatch');
    expect(result['mismatched'], 2);
    expect(
      ((result['examples'] as List).first as Map)['next'],
      'マス無し',
    );

    // ③ 日別キャッシュに、本体に無い日がある。
    table = DayNetTable()..addDay(viaJson(synthetic(41)[dayText(40)]!));
    for (final rows in byDay.values) {
      table.addDay(viaJson(rows));
    }
    result = compareDayNets(table, data.records);
    expect(result['status'], 'mismatch');
    expect(result['mismatched'], 2);
  });

  test('読めない記録だけの日・記録の無い日は、マスを作らない', () {
    final table = DayNetTable()
      ..addDay(viaJson([
        {...rowOf('nagamachiminami', '2026-01-01', 1), 'rack': 0},
      ]))
      ..addDay(const []);
    expect(table.cells, isEmpty);
  });
}
