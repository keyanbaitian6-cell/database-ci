import 'package:database_android/data_checks.dart';
import 'package:database_android/exploratory_candidates.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter_test/flutter_test.dart';

/// 長町南・機種A・8台・5日。当たりの軽さは台ごとに日で入れ替わる。
SlotRecord rec(String day, int rack, {int? bb, int games = 4000}) {
  final d = int.parse(day.substring(8));
  final value = bb ?? 10 + ((rack * 7 + d * 3) % 17);
  return SlotRecord(
    store: 'nagamachiminami',
    day: day,
    machine: 'A',
    rack: rack,
    games: games,
    bb: value,
    rb: 8,
    maxHold: value * 120,
    capturedAt: '${day}T23:00:00',
  );
}

const days = [
  '2026-09-20',
  '2026-09-21',
  '2026-09-22',
  '2026-09-23',
  '2026-09-24',
];

List<SlotRecord> data() => [
  for (final day in days)
    for (var rack = 1; rack <= 8; rack++) rec(day, rack),
];

List<SlotRecord> onDay(List<SlotRecord> all, String day) => [
  for (final r in all)
    if (r.day == day) r,
];

void main() {
  test('候補にできる台と台数は現行と同じ（上位4分の1）', () {
    final all = data();
    final rows = onDay(all, '2026-09-23');
    final current = provisionalNextDayCandidates(rows, all);
    for (final method in ExploratoryMethod.values) {
      final picks = exploratoryCandidates(rows, all, method);
      expect(picks, hasLength(current.candidates.length), reason: method.name);
      for (final p in picks) {
        expect(nextDayIndex(p.record, all).index, p.index);
      }
    }
  });

  test('前日の点数が高い台は、検証の計算と同じ台を選ぶ。凹み台は低い順', () {
    final all = data();
    final run = runBacktest(all, exploratory: ExploratoryMethod.values);
    final group = run.groups.singleWhere((g) => g.day == '2026-09-23');
    final rows = onDay(all, '2026-09-23');
    final previous = exploratoryCandidates(
      rows,
      all,
      ExploratoryMethod.previousScore,
    );
    expect(
      previous.map((c) => c.record.rack).toSet(),
      {for (final m in group.members) if (m.previousScore) m.rack},
    );
    final rebound = exploratoryCandidates(rows, all, ExploratoryMethod.rebound);
    final scored = [
      for (final m in group.members)
        if (m.todayScore != null) m,
    ]..sort((a, b) {
        final c = a.todayScore!.compareTo(b.todayScore!);
        return c != 0 ? c : a.rack.compareTo(b.rack);
      });
    expect(
      rebound.map((c) => c.record.rack).toList(),
      scored.take(group.count).map((m) => m.rack).toList(),
    );
    // 検証の計算にも、同じ台が各方式の候補として付く。
    for (final method in ExploratoryMethod.values) {
      final picks = exploratoryCandidates(rows, all, method);
      expect(
        {for (final m in group.members) if (m.exploratory.contains(method)) m.rack},
        picks.map((c) => c.record.rack).toSet(),
        reason: method.name,
      );
    }
  });

  test('直近5日の平均点：2日分以上の点があるときだけ。無い台は最後', () {
    final all = data();
    final rows = onDay(all, '2026-09-24');
    final picks = exploratoryCandidates(
      rows,
      all,
      ExploratoryMethod.recentAverage,
    );
    for (final p in picks) {
      final history = [
        for (final r in all)
          if (r.rack == p.record.rack && r.day.compareTo('2026-09-24') <= 0) r,
      ]..sort((a, b) => b.day.compareTo(a.day));
      final totals = [
        for (final r in history.take(5)) ?scoreRecord(r, all).total,
      ];
      expect(
        p.value,
        totals.length < 2 ? isNull : closeTo(totals.reduce((a, b) => a + b) / totals.length, 1e-9),
      );
    }
    // 1日分しか点が無い台（前の日は500G以下）は、値が無く最後に回る。
    final few = [
      for (final r in all)
        if (r.rack == 1 && r.day != '2026-09-24')
          rec(r.day, 1, games: 400)
        else
          r,
    ];
    final withFew = exploratoryCandidates(
      onDay(few, '2026-09-24'),
      few,
      ExploratoryMethod.recentAverage,
    );
    expect(withFew.where((c) => c.record.rack == 1 && c.value != null), isEmpty);
  });

  test('組み合わせは0〜1。指数も前日の点数も最高の台がいちばん上', () {
    final all = data();
    final rows = onDay(all, '2026-09-23');
    final picks = exploratoryCandidates(rows, all, ExploratoryMethod.blend);
    for (final p in picks) {
      expect(p.value, inInclusiveRange(0, 1));
    }
    final values = [for (final p in picks) p.value!];
    expect(values, [...values]..sort((a, b) => b.compareTo(a)));
  });

  test('未来の記録を足しても、その日の新規予測は変わらない', () {
    final all = data();
    final more = [
      ...all,
      for (var rack = 1; rack <= 8; rack++) rec('2026-09-25', rack, bb: rack * 9),
      rec('2026-09-26', 2, bb: 70),
    ];
    for (final method in ExploratoryMethod.values) {
      List<(int, double?)> picks(List<SlotRecord> source) => [
        for (final p in exploratoryCandidates(onDay(source, '2026-09-24'), source, method))
          (p.record.rack, p.value),
      ];
      expect(picks(more), picks(all), reason: method.name);
    }
  });
}
