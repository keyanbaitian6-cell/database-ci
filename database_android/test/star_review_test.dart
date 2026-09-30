import 'dart:math';

import 'package:database_android/data_checks.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/star_review.dart';
import 'package:flutter_test/flutter_test.dart';

// 通常★（参考候補）の現行の性質を、合成データで再現して記録する（2026-09-30の
// 独立した再検討）。本番の選び方は変えていない。ここに書いた性質を変えるときは、
// 先に規約（NEXT_DAY_STAR_INDEPENDENT_REVIEW_20260930.md）で検証の条件を決める。

SlotRecord rec(String day, int rack, int games, int hits, {int? hold}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: day,
      machine: 'テスト機種',
      rack: rack,
      games: games,
      bb: hits,
      rb: 0,
      maxHold: hold,
    );

String day(int d) => '2026-09-${d.toString().padLeft(2, '0')}';

Set<int> stars(List<SlotRecord> all, String d) => {
  for (final c in provisionalNextDayCandidates([
    for (final r in all)
      if (r.day == d) r,
  ], all).candidates)
    c.record.rack,
};

void main() {
  // 8台。1番台だけ毎日よく当たる。5日目に1番台は打たれない（0G）。
  List<SlotRecord> steady({required int lastDayGames}) => [
    for (var d = 1; d <= 5; d++)
      for (var rack = 1; rack <= 8; rack++)
        if (d == 5 && rack == 1)
          rec(day(d), rack, lastDayGames, 0)
        else
          rec(day(d), rack, 4000, rack == 1 ? 40 : 10 + rack),
  ];

  test('指数の中身の再計算は、アプリの指数と同じ値になる', () {
    final rng = Random(1);
    final all = [
      for (var d = 1; d <= 12; d++)
        for (var rack = 1; rack <= 9; rack++)
          rec(day(d), rack, 800 + rng.nextInt(6000), rng.nextInt(40)),
    ];
    for (final r in all) {
      final app = nextDayIndex(r, all);
      final b = indexBreakdown(r, all);
      expect(b.rounded, app.index, reason: '${r.day} ${r.rack}');
      if (app.index != null) expect(b.n, app.days);
    }
  });

  test('当日0Gの台は、当日の記録が指数に入らず前日と同じ指数のまま★になる', () {
    final all = steady(lastDayGames: 0);
    final day4 = all.firstWhere((r) => r.day == day(4) && r.rack == 1);
    final day5 = all.firstWhere((r) => r.day == day(5) && r.rack == 1);
    expect(nextDayIndex(day5, all).index, nextDayIndex(day4, all).index);
    expect(indexBreakdown(day5, all).todayUsed, isFalse);
    expect(stars(all, day(4)), contains(1));
    expect(stars(all, day(5)), contains(1));
    // 500G未満（例：499G）も同じ。
    final low = steady(lastDayGames: 499);
    expect(stars(low, day(5)), contains(1));
  });

  test('当日の点数（最大持玉・グラフ）を変えても指数は変わらない', () {
    final base = steady(lastDayGames: 4000);
    final changed = [
      for (final r in base)
        if (r.day == day(5) && r.rack == 1)
          r.copyWith(
            maxHold: 0,
            graph: const GraphMeasurement(
              baselineY: 100,
              peakY: 100,
              troughY: 300,
              endY: 300,
            ),
          )
        else
          r.copyWith(maxHold: 3000),
    ];
    final a = base.firstWhere((r) => r.day == day(5) && r.rack == 1);
    final b = changed.firstWhere((r) => r.day == day(5) && r.rack == 1);
    expect(nextDayIndex(b, changed).index, nextDayIndex(a, base).index);
    expect(scoreRecord(b, changed).total, isNot(scoreRecord(a, base).total));
  });

  test('1日の結果で指数が動く大きさは、最大で50÷(使った日数+5)', () {
    // 11日。1番台は10日目まで毎日一番よく当たり、11日目に一番悪い。
    // （1日20,000G・当たり500回を超えると数値異常で除かれるので、現実的な値）
    final all = [
      for (var d = 1; d <= 11; d++)
        for (var rack = 1; rack <= 8; rack++)
          rec(day(d), rack, 9000, rack == 1 ? (d == 11 ? 1 : 60) : 20 + rack),
    ];
    final before = indexBreakdown(
      all.firstWhere((r) => r.day == day(10) && r.rack == 1),
      all,
    );
    final after = indexBreakdown(
      all.firstWhere((r) => r.day == day(11) && r.rack == 1),
      all,
    );
    expect(before.n, 10);
    // 最も古い日が抜け、最新日（最下位）が入る。寄与の幅は約-37.5〜+37.5。
    final moved = before.unrounded! - after.unrounded!;
    expect(moved, lessThanOrEqualTo(100 / (10 + 5)));
    expect(moved, greaterThan(0));
    // 見積もり（寄与-50、最も古い日が抜ける）は、実際の値以下になる。
    expect(nextIndexWith(before, -50), lessThanOrEqualTo(after.unrounded!));
    // 10日分の上位が1日の最下位で消えず、指数は50より大きいまま。
    expect(after.unrounded!, greaterThan(50));
  });

  test('丸め後の同点は台番号の小さい順：丸め前は高い台が★から外れる', () {
    // 9台・3日。7・8番台が上位、2番台と5番台は当たり確率がちょうど同じで、
    // 5番台の方が少し多く回った（寄与の重みが少し大きい）。
    final hits = {7: 60, 8: 55, 2: 40, 1: 30, 3: 28, 4: 26, 6: 24, 9: 22};
    final all = [
      for (var d = 1; d <= 3; d++)
        for (var rack = 1; rack <= 9; rack++)
          if (rack == 5)
            rec(day(d), 5, 4920, 41) // 41/4920 = 40/4800 = 1/120
          else
            rec(day(d), rack, 4800, hits[rack]!),
    ];
    final two = indexBreakdown(
      all.firstWhere((r) => r.day == day(3) && r.rack == 2),
      all,
    );
    final five = indexBreakdown(
      all.firstWhere((r) => r.day == day(3) && r.rack == 5),
      all,
    );
    expect(five.unrounded!, greaterThan(two.unrounded!));
    expect(five.rounded, two.rounded);
    // 判定9台 → 上位3台。3位の同点は台番号の小さい2番台になる。
    expect(stars(all, day(3)), {7, 8, 2});
  });

  test('全台に差が無くても上位4分の1は必ず選ばれ、毎日同じ小さい台番号になる', () {
    final all = [
      for (var d = 1; d <= 6; d++)
        for (var rack = 11; rack <= 18; rack++) rec(day(d), rack, 3000, 15),
    ];
    for (var d = 3; d <= 6; d++) {
      expect(stars(all, day(d)), {11, 12}, reason: day(d));
    }
    expect(nextDayIndex(all.last, all).index, 50.0);
  });

  test('当たりが偶然だけでも、履歴が重なるので連日の★の重なりは大きい', () {
    // 台ごとの差が無い（毎日の当たりは無作為）8台・20日。
    final rng = Random(20260930);
    final all = [
      for (var d = 1; d <= 20; d++)
        for (var rack = 1; rack <= 8; rack++)
          rec(day(d), rack, 3000 + rng.nextInt(2000), 5 + rng.nextInt(30)),
    ];
    final groups = buildStarGroups(all);
    final r = repeatRate(groups);
    // 毎日独立に選ぶなら重なりは約25%（8台から2台）。
    expect(r.stars, greaterThan(20));
    expect(r.rate!, greaterThan(0.5));
  });

  test('台番号の入れ替えは、日ごとの数値の組をそのまま残し、台番号だけを入れ替える', () {
    final all = steady(lastDayGames: 4000);
    final permuted = permuteRackLabels(all, Random(3));
    for (var d = 1; d <= 5; d++) {
      List<(int, int)> values(List<SlotRecord> rows) => [
        for (final r in rows)
          if (r.day == day(d)) (r.games, r.bb),
      ]..sort((a, b) => a.$1 != b.$1 ? a.$1 - b.$1 : a.$2 - b.$2);
      Set<int> racks(List<SlotRecord> rows) => {
        for (final r in rows)
          if (r.day == day(d)) r.rack,
      };
      expect(values(permuted), values(all));
      expect(racks(permuted), racks(all));
    }
  });

  test('分析のグループはアプリの★と同じで、前日も★かを数える', () {
    final all = steady(lastDayGames: 4000);
    final groups = buildStarGroups(all);
    for (final g in groups) {
      expect({
        for (final m in g.members)
          if (m.star) m.record.rack,
      }, stars(all, g.day));
    }
    final last = groups.firstWhere((g) => g.day == day(5));
    expect(
      last.members.firstWhere((m) => m.record.rack == 1).starYesterday,
      isTrue,
    );
    expect(repeatRate(groups).rate, 1.0);
    expect(shiftDay(day(5), -1), day(4));
  });
}
