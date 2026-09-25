import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';

SlotRecord sample({
  String day = '2026-09-20',
  int rack = 1,
  int games = 3000,
  int bb = 60,
  int rb = 30,
  int? maxHold = 3000,
}) => SlotRecord(
  store: 'saiwaichou',
  machine: 'M',
  day: day,
  rack: rack,
  games: games,
  bb: bb,
  rb: rb,
  maxHold: maxHold,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 100,
  ),
);
List<SlotRecord> refs({int days = 3, int perDay = 10}) => [
  for (var d = 0; d < days; d++)
    for (var i = 0; i < perDay; i++)
      sample(day: '2026-09-${19 - d}', rack: i, bb: 30, rb: 15, maxHold: 1000),
];

void main() {
  test('回転数そのものでは加点しない', () {
    for (final g in [1, 499, 500, 1500, 3500, 7000]) {
      expect(spinScore(g), 0);
    }
    expect(spinScore(0), isNull);
  });
  test('当日500G以下の台は採点しない', () {
    for (final g in [1, 499, 500]) {
      final score = scoreRecord(sample(games: g), refs());
      expect(score.total, isNull);
      expect(score.reasons, ['500G以下のため採点なし']);
    }
    expect(scoreRecord(sample(games: 501), refs()).total, isNotNull);
  });
  test('手計算 .2の立方根の縮約係数・満点との比較で83.4点', () {
    // v9: 掛け算ではなく相乗平均。
    // weight = (3000/4500 * 30/50 * 3/6)^(1/3) = .2^(1/3) = .584804
    // 当たり = 60*(.5 + .584804*.5) = 47.5441
    // 持玉 = 20*(.5 + .584804*.5) = 15.8480（枚数による点 20*3000/19000 = 3.16 より大きい）
    // 合計 = 47.5441 + 15.8480 + 10 + 10 = 83.392 → 83.4
    final score = scoreRecord(sample(), refs());
    expect(score.hits, closeTo(47.5441064292772, 1e-9));
    expect(score.maxHold, closeTo(15.848035476425734, 1e-9));
    expect(score.total, 83.4);
    expect(score.coverage, 100);
    expect(score.referenceDays, 3);
    expect(score.provisional, false);
  });
  test('当日・未来・他店・他機種・過少稼働は比較しない', () {
    final row = sample();
    final extra = [
      sample(),
      sample(day: '2026-09-21'),
      sample(day: '2026-08-20'),
      sample(day: '2026-09-19', games: 499),
      sample(day: '2026-09-19', games: 7000),
      sample(day: '2026-09-19').copyWith(store: 'nagamachiminami'),
      sample(day: '2026-09-19').copyWith(machine: 'other'),
    ];
    expect(scoreRecord(row, [...refs(), ...extra]).total, 83.4);
    expect(scoreRecord(row, extra).total, 60);
    expect(scoreRecord(row, extra).coverage, 20);
  });
  test('持玉欠測は中立10点で補い他項目の配点を増やさない', () {
    // 47.5441 + 10 + 10 = 67.544 に、欠けた持玉20点の半分を足して 77.5。
    final score = scoreRecord(sample(maxHold: null), refs());
    expect(score.maxHold, isNull);
    expect(score.total, 77.5);
    expect(score.missingLow, 67.5);
    expect(score.missingHigh, 87.5);
    expect(score.coverage, 80);
    expect(score.provisional, true);
  });
  test('コンプリートまで出た台は持玉満点。枚数では点を下げない', () {
    // 上限（19,000枚）は機械が超えられない天井なので、比較相手が少なくても満点。
    expect(scoreRecord(sample(maxHold: 19000), refs()).maxHold, 20);
    expect(scoreRecord(sample(maxHold: 25000), refs()).maxHold, 20);
    // 枚数が少ない台は順位による点のまま（枚数による点では下げない）。
    // 比較相手と同じ1000枚なので順位は0.5＝中間の10点。
    // 枚数による点 20*1000/19000 = 1.05 で上書きしてしまわないことを確かめる。
    final low = scoreRecord(sample(maxHold: 1000), refs());
    expect(low.maxHold, closeTo(10, 1e-9));
    expect(low.maxHold, greaterThan(20 * 1000 / 19000));
  });
  test('同じ件数でも1日だけでは3日より中立へ寄せる', () {
    final one = scoreRecord(sample(), refs(days: 1, perDay: 30));
    final three = scoreRecord(sample(), refs());
    expect(one.hits, lessThan(three.hits!));
  });
  test('同率・同持玉なら回転数が増えただけで加点しない', () {
    final a = scoreRecord(sample(bb: 30, rb: 15, maxHold: 1000), refs());
    final b = scoreRecord(
      sample(games: 6000, bb: 60, rb: 30, maxHold: 1000),
      refs(),
    );
    expect(a.total, b.total);
  });
  test('303番台の確認済みグラフの得点を維持する', () {
    final decoded =
        jsonDecode(File('assets/database_seed.json').readAsStringSync()) as Map;
    final rows = (decoded['rows'] as List)
        .map((e) => SlotRecord.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
    final row = rows.singleWhere(
      (r) => r.day == '2026-09-15' && r.machine == 'L+防振り+FN' && r.rack == 303,
    );
    final score = scoreRecord(row, rows);
    expect(score.positive, 10);
    expect(score.retention, closeTo(8.62275449, .001));
    expect(score.total, isNotNull);
  });
}
