import 'dart:convert';

import 'package:database_android/models.dart';
import 'package:database_android/rack_trend_check.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

import 'calendar_day_net_test.dart' show dayText, viaJson;
import 'day_score_check_test.dart' show withNewMachine;

/// 段階B3（VIEWER_DAY_STORE.md、2026-11-25）：台の推移（同じ店・台番号・機種の、その日までの直近7記録と各日の
/// 点数）を日別キャッシュから1日ずつ作ったものが、今の計算（全記録から rackTrend）と、記録と点数の全項目まで
/// 同じこと。合成データはB2と同じもの（新台の入れ替えを含む）に、同じ台番号の機種の入れ替え（A→B→A）を足す。

Map<String, List<Map<String, dynamic>>> withSwap(int days) {
  final byDay = withNewMachine(days);
  // 幸町の3番台：20〜34日目だけ別の機種にし、そのあと元の機種に戻す（元の機種の推移は入れ替えの前の日へ続く）。
  for (var i = 20; i < 35 && i < days; i++) {
    for (final r in byDay[dayText(i)]!) {
      if (r['store'] == 'saiwaichou' && r['rack'] == 3) r['machine'] = '入替テスト';
    }
  }
  return byDay;
}

ViewerData parse(Map<String, List<Map<String, dynamic>>> byDay) =>
    ViewerData.parse(
      jsonEncode({
        'records': [for (final rows in byDay.values) ...rows],
      }),
    );

Map<String, Object?> run(
  Map<String, List<Map<String, dynamic>>> byDay,
  ViewerData data,
  List<SlotRecord> targets, {
  String? skip,
}) {
  final check = RackTrendCheck(data.records, targets);
  for (final day in byDay.keys.toList()..sort()) {
    if (day == skip) continue;
    check.addDay(viaJson(byDay[day]!));
  }
  return check.finish();
}

void main() {
  for (final days in [108, 180]) {
    test('日別キャッシュから作った台の推移は、全記録からの推移と全項目で一致（$days日）', () {
      final byDay = withSwap(days);
      final data = parse(byDay);
      // 9日ごとの日の全台と、最後の日の全台（推移が7件に満たない最初の頃の日・入れ替えをまたぐ日を含む）。
      final days9 = {
        for (var i = 0; i < days; i += 9) dayText(i),
        dayText(days - 1),
      };
      final targets = [
        for (final r in data.records)
          if (days9.contains(r.day)) r,
      ];
      final result = run(byDay, data, targets);
      expect(result['mismatched'], 0, reason: '${result['examples']}');
      expect(result['status'], 'match');
      expect(result['racks'], targets.length);
      // 空振りにならないよう、7件そろう台・7件に満たない台・入れ替えをまたいだ台・点数のある行があることを確かめる。
      expect(result['entries'] as int, greaterThan(targets.length * 5));
      final swapped = data.records.firstWhere(
        (r) => r.store == 'saiwaichou' && r.rack == 3 && r.day == dayText(36),
      );
      final trend = run(byDay, data, [swapped]);
      expect(trend['status'], 'match');
      expect(trend['entries'], 7, reason: '入れ替えの前（19日目以前）の同じ機種の記録までたどる');
    });
  }

  test('日別キャッシュに日が欠けると推移・点数が変わり、一致しない台として数える', () {
    final byDay = withSwap(60);
    final data = parse(byDay);
    final targets = [
      for (final r in data.records)
        if (r.day == dayText(25)) r,
    ];
    final result = run(byDay, data, targets, skip: dayText(22));
    expect(result['status'], 'mismatch');
    expect(result['mismatched'], greaterThan(0));
    final example = (result['examples'] as List).first as Map;
    expect(example['day'], dayText(25));
  });

  test('1台の数値が違うと、その台と、それを比較相手にする後の日の台の推移が一致しない', () {
    final byDay = withSwap(60);
    final data = parse(byDay);
    final targets = [
      for (final r in data.records)
        if (r.day == dayText(30)) r,
    ];
    // 日別キャッシュの側だけ、28日目の幸町2番台（ハナハナ）の回転数を変える。
    final changed = {
      for (final e in byDay.entries)
        e.key: [
          for (final r in e.value)
            e.key == dayText(28) && r['store'] == 'saiwaichou' && r['rack'] == 2
                ? {...r, 'games': (r['games'] as int) + 1}
                : r,
        ],
    };
    final result = run(changed, data, targets);
    expect(result['status'], 'mismatch');
    final racks = [
      for (final e in result['examples'] as List) (e as Map)['rack'],
    ];
    expect(racks, contains('2'));
  });

  test('照合する台：いちばん新しい日の台を台番号の順に、前回の続きから30台ずつ一巡する', () {
    final byDay = withSwap(20);
    final data = parse(byDay);
    final latest = [
      for (final r in data.records)
        if (r.store == 'saiwaichou' && r.day == dayText(19)) r,
    ]..sort((a, b) => a.rack.compareTo(b.rack));
    var pick = pickTrendRacks(data.records, 'saiwaichou', count: 5);
    expect(
      [for (final r in pick.targets) r.rack],
      [for (final r in latest.take(5)) r.rack],
    );
    expect(pick.targets.every((r) => r.day == dayText(19)), isTrue);
    final seen = <int>{...pick.targets.map((r) => r.rack)};
    for (var i = 0; i < 20 && seen.length < latest.length; i++) {
      pick = pickTrendRacks(
        data.records,
        'saiwaichou',
        after: pick.next,
        count: 5,
      );
      seen.addAll(pick.targets.map((r) => r.rack));
    }
    expect(seen, {for (final r in latest) r.rack}, reason: '全台を一巡する');
    // 台が少なければ全台（覚える台番号なし）。記録の無い店は空。
    final few = pickTrendRacks(data.records, 'saiwaichou', count: 999);
    expect(few.targets.length, latest.length);
    expect(few.next, isNull);
    expect(pickTrendRacks(data.records, 'nostore').targets, isEmpty);
  });
}
