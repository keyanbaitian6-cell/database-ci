import 'dart:convert';

import 'package:database_android/day_score_check.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

import 'calendar_day_net_test.dart' show dayText, synthetic, viaJson;

/// 段階B2（VIEWER_DAY_STORE.md、2026-11-18）：日別キャッシュの「その日と前30暦日」だけで採点した台の点数が、
/// 全記録から採点した点数（日・機種一覧に出す表示用の採点）と、全項目で1台も違わないこと。
/// 合成データはB1と同じもの（線を外した記録・線のある記録・グラフ無し・数値異常・ゲーム数0・重複・読めない記録・
/// 対象外の機種）に、途中の日から入る新しい機種（新台の採点＝同じ日のほかの台と比べる）を足す。

Map<String, List<Map<String, dynamic>>> withNewMachine(int days) {
  final byDay = synthetic(days);
  for (var i = 0; i < days; i++) {
    if (i < 45) continue; // 45日目から入れ替え（新台）。最初の日は新台の採点、30日たつと普通の採点に戻る。
    for (var k = 0; k < 4; k++) {
      byDay[dayText(i)]!.add({
        'store': 'saiwaichou',
        'day': dayText(i),
        'machine': '新台テスト',
        'rack': 500 + k,
        'games': 1200 + 700 * k + (i * 37) % 900,
        'bb': 5 + k + i % 7,
        'rb': 3 + (i + k) % 5,
        'max_hold': 400 + 300 * k + (i * 53) % 1200,
      });
    }
  }
  return byDay;
}

void main() {
  for (final days in [108, 180]) {
    test('その日と前30日だけで採点した点数は、全記録からの点数と全台一致（$days日）', () {
      final byDay = withNewMachine(days);
      final data = ViewerData.parse(
        jsonEncode({
          'records': [for (final rows in byDay.values) ...rows],
        }),
      );
      final check = DayScoreCheck(data.records, byDay.keys, fullCurrent: true);
      for (final day in byDay.keys.toList()..sort()) {
        check.addDay(viaJson(byDay[day]!));
      }
      final result = check.finish();
      expect(result['mismatched'], 0, reason: '${result['examples']}');
      expect(result['status'], 'match');
      expect(result['racks'], data.records.length);
      // 本番と同じ形（今の計算の側も本体の31日分だけ）でも、全日で一致する。
      final windowed = DayScoreCheck(data.records, byDay.keys);
      for (final day in byDay.keys.toList()..sort()) {
        windowed.addDay(viaJson(byDay[day]!));
      }
      expect(windowed.finish()['mismatched'], 0);
      // 空振りにならないよう、採点のある台・新台の扱いの台・比較相手が30日を超える台があることを確かめる。
      final scored = [
        for (final r in data.records) data.displayScore(r),
      ];
      expect(scored.where((s) => s.total != null).length, greaterThan(days * 10));
      expect(
        scored.where((s) => s.reasons.any((t) => t.contains('新台'))).length,
        greaterThan(0),
        reason: '新台の採点の台がある',
      );
    });
  }

  test('窓に足りない日があると点数が変わり、一致しない台として数える', () {
    final byDay = withNewMachine(60);
    final data = ViewerData.parse(
      jsonEncode({
        'records': [for (final rows in byDay.values) ...rows],
      }),
    );
    // 20日目の記録を日別キャッシュから欠くと、その日の台は「台無し」、21〜50日目の台は比較相手が減って点数が変わる。
    final check = DayScoreCheck(data.records, byDay.keys);
    for (final day in byDay.keys.toList()..sort()) {
      if (day == dayText(20)) continue;
      check.addDay(viaJson(byDay[day]!));
    }
    final result = check.finish();
    expect(result['status'], 'mismatch');
    final missing = data.records.where((r) => r.day == dayText(20)).length;
    expect(result['mismatched'] as int, greaterThan(missing));
    expect((result['examples'] as List).length, 3);
  });

  test('1台の数値が違えば、その台と、それを比較相手にする後の日の台が一致しない', () {
    final byDay = withNewMachine(40);
    final data = ViewerData.parse(
      jsonEncode({
        'records': [for (final rows in byDay.values) ...rows],
      }),
    );
    final changed = {
      for (final e in byDay.entries)
        e.key: (jsonDecode(jsonEncode(e.value)) as List)
            .cast<Map<String, dynamic>>(),
    };
    final target = changed[dayText(10)]!.firstWhere(
      (r) => r['machine'] == 'ハナハナ' && r['games'] is int && (r['games'] as int) < 20000,
    );
    target['bb'] = (target['bb'] as int) + 30;
    final check = DayScoreCheck(data.records, byDay.keys);
    for (final day in changed.keys.toList()..sort()) {
      check.addDay(viaJson(changed[day]!));
    }
    final result = check.finish();
    expect(result['status'], 'mismatch');
    final first = (result['examples'] as List).first as Map;
    expect(first['day'], dayText(10));
    expect(first['old'], isNot(first['next']));
  });

  test('照合する日：最新の日と、順に回す3日。更新のたびに全日を一巡する', () {
    final days = [for (var i = 0; i < 9; i++) dayText(i)];
    String? after;
    final seen = <String>{};
    for (var n = 0; n < 3; n++) {
      final pick = pickScoreDays(days, after);
      expect(pick.targets.first, dayText(8), reason: 'いちばん新しい日は毎回');
      expect(pick.targets.length, 4);
      seen.addAll(pick.targets);
      after = pick.next;
    }
    expect(seen, days.toSet(), reason: '3回の更新で全9日を一巡');
    expect(pickScoreDays(days, dayText(0)).targets.skip(1).first, dayText(7), reason: 'いちばん古い日まで済んだら新しい側へ戻る');
    expect(pickScoreDays(days, null).targets.skip(1).first, dayText(7), reason: '覚えた日が無ければ新しい側から');
    expect(pickScoreDays(days, '2027-12-31').targets.skip(1).first, dayText(7), reason: 'どの日より新しい日を覚えていても新しい側から');
    final single = pickScoreDays([dayText(0)], dayText(0));
    expect(single.targets, [dayText(0)]);
    expect(single.next, isNull);
    expect(pickScoreDays(const [], null).targets, isEmpty);
  });

  test('照合する日：毎回1日ずつ新しい日が増えても、過去の日を一巡する（2026-11-22）', () {
    // 実際の運用に近い形：更新のたびに最新の日が1日増え、順に回すのは1日だけ。以前（並びの位置で覚えた）は、
    // 新しい日が先頭に入るたびに位置がずれ、同じ過去の日ばかり選んで一巡しなかった。
    final days = [for (var i = 0; i < 20; i++) dayText(i)];
    final original = days.toSet();
    String? after;
    final seen = <String>{};
    for (var n = 0; n < 40 && !seen.containsAll(original.difference({dayText(19)})); n++) {
      final pick = pickScoreDays(days, after, rotating: 1);
      seen.addAll(pick.targets.skip(1));
      after = pick.next;
      days.add(dayText(20 + n));
    }
    expect(seen.containsAll(original.difference({dayText(19)})), isTrue,
        reason: '最初にあった過去の日（最新の日を除く19日）を、日が増えても選び切る');
  });

  test('対象の日だけを採点し、窓は対象の日の30日前から読めば足りる', () {
    final byDay = withNewMachine(80);
    final data = ViewerData.parse(
      jsonEncode({
        'records': [for (final rows in byDay.values) ...rows],
      }),
    );
    final targets = [dayText(79), dayText(50), dayText(46)];
    final check = DayScoreCheck(data.records, targets);
    expect(check.from, dayText(16));
    for (final day in byDay.keys.toList()..sort()) {
      if (day.compareTo(check.from!) < 0) continue; // JSは from より前の日を渡さない
      check.addDay(viaJson(byDay[day]!));
    }
    final result = check.finish();
    expect(result['mismatched'], 0, reason: '${result['examples']}');
    expect(result['targets'], [dayText(46), dayText(50), dayText(79)]);
    expect(
      result['racks'],
      data.records.where((r) => targets.contains(r.day)).length,
    );
  });

  test('1店だけを照合すると、その店の台だけを窓に持ち、全記録からの点数と一致する', () {
    final byDay = withNewMachine(70);
    final data = ViewerData.parse(
      jsonEncode({
        'records': [for (final rows in byDay.values) ...rows],
      }),
    );
    for (final store in ['nagamachiminami', 'saiwaichou']) {
      final targets = [dayText(69), dayText(47)];
      final check = DayScoreCheck(data.records, targets, store: store);
      for (final day in byDay.keys.toList()..sort()) {
        check.addDay(viaJson(byDay[day]!));
      }
      final result = check.finish();
      expect(result['mismatched'], 0, reason: '${result['examples']}');
      expect(result['store'], store);
      expect(
        result['racks'],
        data.records
            .where((r) => r.store == store && targets.contains(r.day))
            .length,
      );
      // 全記録で採点した点数とも同じ（店を絞っても比較相手は変わらない：比較相手は同じ店だけ）。
      final full = DayScoreCheck(data.records, targets, store: store, fullCurrent: true);
      for (final day in byDay.keys.toList()..sort()) {
        full.addDay(viaJson(byDay[day]!));
      }
      expect(full.finish()['mismatched'], 0);
    }
  });
}
