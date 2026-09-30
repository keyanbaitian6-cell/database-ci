import 'package:database_android/focus_validation.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

BacktestMember m(int rack, double? score) => BacktestMember(
  rack: rack,
  machine: 'A',
  index: 55,
  days: 5,
  confidence: '少',
  todayScore: score,
  nextScore: null,
);

void main() {
  test('固定した主方式は88以上を飛ばし直近重視の順で補充、未採点は保持', () {
    final group = BacktestGroup('saiwaichou', 'A', '2026-09-30', [
      m(1, 88),
      m(2, 90),
      m(3, null),
      m(4, 87.9),
    ], 2);
    expect(
      focusPrimaryPicks(group, {1: 60, 2: 59, 3: 58, 4: 57}).map((m) => m.rack),
      [3, 4],
    );
  });
  test('全台88以上なら候補なし、枠をゼロ点で補わない', () {
    final group = BacktestGroup('saiwaichou', 'A', '2026-09-30', [
      m(1, 88),
      m(2, 90),
    ], 1);
    expect(focusPrimaryPicks(group, {1: 60, 2: 59}), isEmpty);
    expect(group.count, 1);
  });
  test('未来検証の期間と最終評価日を固定する', () {
    expect(
      (focusValidationFrom, focusValidationThrough, focusValidationFinalOn),
      ('2026-09-30', '2026-10-29', '2026-10-31'),
    );
  });
  test('検証グループは固定期間だけ、締切後に取り込んだ予測日は使わない', () {
    final full = [
      for (final day in [
        '2026-09-27',
        '2026-09-28',
        '2026-09-29',
        '2026-09-30',
        '2026-10-01',
      ])
        for (var rack = 1; rack <= 4; rack++)
          SlotRecord(
            store: 'saiwaichou',
            day: day,
            machine: 'A',
            rack: rack,
            games: 4000,
            bb: 40 - rack * 3,
            rb: 0,
            maxHold: 1000,
            capturedAt: '${day}T23:00:00+09:00',
          ),
    ];
    expect(buildFocusValidation(full).map((g) => g.baseline.day).toSet(), {
      '2026-09-30',
    });
    final late = [
      for (final r in full)
        r.day == '2026-09-30'
            ? r.copyWith(capturedAt: '2026-10-01T00:01:00+09:00')
            : r,
    ];
    expect(buildFocusValidation(late), isEmpty);
  });
}
