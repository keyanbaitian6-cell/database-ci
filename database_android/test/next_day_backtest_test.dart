import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:flutter_test/flutter_test.dart';

/// 長町南・機種A・8台。台番号が小さいほど当たりが軽い（9/20〜9/23）。
SlotRecord rec(
  String day,
  int rack, {
  int? bb,
  int games = 4000,
  String machine = 'A',
  String? capturedAt,
}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: bb ?? 34 - rack * 3,
  rb: 10,
  maxHold: (bb ?? 34 - rack * 3) * 100,
  capturedAt: capturedAt ?? '${day}T23:00:00',
);

const history = ['2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23'];

List<SlotRecord> base() => [
  for (final day in history)
    for (var rack = 1; rack <= 8; rack++) rec(day, rack),
  rec('2026-09-24', 1, bb: 40),
  rec('2026-09-24', 2, bb: 2),
  for (var rack = 3; rack <= 8; rack++) rec('2026-09-24', rack),
];

BacktestGroup group(BacktestRun run, String day) =>
    run.groups.singleWhere((g) => g.day == day && g.machine == 'A');

void main() {
  test('時刻：時差の無い時刻は日本時間。締切は翌日0:00（日本時間）の直前まで', () {
    final cutoff = predictionCutoff('2026-09-25');
    bool before(String s) => readJst(s)!.isBefore(cutoff);
    expect(before('2026-09-25T23:59:59'), isTrue);
    expect(before('2026-09-26T00:00:00'), isFalse);
    expect(before('2026-09-25T23:59:59+09:00'), isTrue);
    expect(before('2026-09-26T00:00:00+09:00'), isFalse);
    expect(before('2026-09-25T14:59:59Z'), isTrue);
    expect(before('2026-09-25T15:00:00Z'), isFalse); // = 9/26 0:00 日本時間
    expect(readJst(null), isNull);
    expect(readJst('bad'), isNull);
    expect(predictionCutoff('2026-09-30', hour: 9),
        DateTime.utc(2026, 10, 1, 0)); // 月末をまたぐ（10/1 9:00 日本時間）
  });

  test('候補はアプリの関数そのもの。最初の7台もアプリの並びと同じ', () {
    final all = base();
    final run = runBacktest(all, cutoffFor: (d) => predictionCutoff(d));
    final g = group(run, '2026-09-23');
    expect(g.count, 2);
    expect({for (final m in g.members) if (m.current) m.rack}, {1, 2});
    final rows = [for (final r in all) if (r.day == '2026-09-23') r];
    final app = dayCandidates(rows, all).candidates.take(7);
    final top = run.topSeven.singleWhere((t) => t.day == '2026-09-23');
    expect(top.current.map((m) => m.rack), app.map((c) => c.record.rack));
  });

  test('未来の記録を足しても、過去の予測（候補・指数・予測日の点）は変わらない', () {
    final before = runBacktest(base(), cutoffFor: (d) => predictionCutoff(d));
    final more = [
      ...base(),
      for (var rack = 1; rack <= 8; rack++)
        rec('2026-09-25', rack, bb: rack * 5, games: 9000),
      rec('2026-09-26', 3, bb: 60),
    ];
    final after = runBacktest(more, cutoffFor: (d) => predictionCutoff(d));
    for (final day in ['2026-09-22', '2026-09-23']) {
      final a = group(before, day), b = group(after, day);
      expect(
        [for (final m in b.members) (m.rack, m.index, m.days, m.todayScore, m.current, m.previousScore, m.nextScore)],
        [for (final m in a.members) (m.rack, m.index, m.days, m.todayScore, m.current, m.previousScore, m.nextScore)],
      );
    }
  });

  test('締切より後に取り込んだ記録は使わない。上書き前の値があればそれを使う', () {
    final late = [
      for (final r in base())
        r.day == '2026-09-23' && r.rack == 1
            ? r.copyWith(capturedAt: '2026-09-24T01:00:00', games: 8000)
            : r,
    ];
    final strict = runBacktest(late, cutoffFor: (d) => predictionCutoff(d));
    expect(group(strict, '2026-09-23').members.map((m) => m.rack), isNot(contains(1)));
    final loose = runBacktest(late);
    expect(group(loose, '2026-09-23').members.map((m) => m.rack), contains(1));

    // 取り込み直す前（締切前）の値が書き込み記録にあれば、その値で計算する。
    final earlier = rec('2026-09-23', 1, capturedAt: '2026-09-23T23:00:00');
    final withEarlier = runBacktest(
      late,
      cutoffFor: (d) => predictionCutoff(d),
      earlier: {earlier.key: [earlier]},
    );
    final exact = runBacktest(base(), cutoffFor: (d) => predictionCutoff(d));
    final m1 = group(withEarlier, '2026-09-23').members.singleWhere((m) => m.rack == 1);
    final e1 = group(exact, '2026-09-23').members.singleWhere((m) => m.rack == 1);
    expect((m1.index, m1.todayScore), (e1.index, e1.todayScore));
  });

  test('翌日に機種が入れ替わった台・記録の無い台・500G以下の台は0点にせず除外', () {
    final all = [
      for (final r in base())
        if (!(r.day == '2026-09-24' && r.rack <= 3)) r,
      rec('2026-09-24', 1, bb: 40, machine: 'B'), // 1番台は別の機種に
      rec('2026-09-24', 2, games: 400), // 2番台は500G以下
      // 3番台は翌日の記録なし
    ];
    final run = runBacktest(all, cutoffFor: (d) => predictionCutoff(d));
    final g = group(run, '2026-09-23');
    final next = {for (final m in g.members) m.rack: m.nextScore};
    expect(next[1], isNull);
    expect(next[2], isNull);
    expect(next[3], isNull);
    expect(next[4], isNotNull);
    expect(run.unlabeledNextDay['no_record'], greaterThanOrEqualTo(2));
    expect(run.unlabeledNextDay['not_scored'], greaterThanOrEqualTo(1));
    final result = evaluateMethod([g], (m) => m.current);
    // 候補（1・2番台）はどちらも翌日の点が無いので、差を出さない（0点にしない）。
    expect(result['evaluable'], 0);
    expect(result['groups'], 0);
  });

  test('前日の点数が高い台：点の無い台は最後、同点は台番号の小さい順', () {
    final all = [
      for (final r in base())
        if (!(r.day == '2026-09-23' && r.rack == 1)) r,
      rec('2026-09-23', 1, games: 400), // 予測日の点が無い（500G以下）
    ];
    final run = runBacktest(all, cutoffFor: (d) => predictionCutoff(d));
    final g = group(run, '2026-09-23');
    final one = g.members.singleWhere((m) => m.rack == 1);
    expect(one.todayScore, isNull);
    expect(one.previousScore, isFalse);
    final picked = [for (final m in g.members) if (m.previousScore) m];
    expect(picked, hasLength(g.count));
    final scored = [for (final m in g.members) if (m.todayScore != null) m]
      ..sort((a, b) {
        final c = b.todayScore!.compareTo(a.todayScore!);
        return c != 0 ? c : a.rack.compareTo(b.rack);
      });
    expect(picked.map((m) => m.rack), scored.take(g.count).map((m) => m.rack));
  });

  test('集計：差は候補にできる台の平均との差。区間は日を単位にする', () {
    BacktestMember m(int rack, double? next, {bool current = false}) =>
        BacktestMember(
          rack: rack,
          machine: 'A',
          index: 50,
          days: 3,
          confidence: '少',
          todayScore: 50,
          nextScore: next,
        )..current = current;
    final groups = [
      BacktestGroup('nagamachiminami', 'A', '2026-09-23', [
        m(1, 70, current: true),
        m(2, 50),
        m(3, 30),
        m(4, null, current: true),
      ], 2),
      BacktestGroup('nagamachiminami', 'A', '2026-09-24', [
        m(1, 40, current: true),
        m(2, 60),
      ], 1),
    ];
    final result = evaluateMethod(groups, (x) => x.current);
    expect(result['selected'], 3);
    expect(result['evaluable'], 2);
    final gap = result['gap_vs_pool'] as Map;
    // 9/23：70 − 50 ＝ +20、9/24：40 − 50 ＝ −10 → 日の平均 +5
    expect(gap['by_day'], {'2026-09-23': 20.0, '2026-09-24': -10.0});
    expect(gap['mean_of_days'], 5.0);
    expect(gap['positive_days'], 1);
    final ci = dayBootstrap([2, 2, 2])!;
    expect((ci.$1, ci.$2), (2.0, 2.0));
    expect(dayBootstrap([1]), isNull);
  });

  test('ブロック検定・O/E比・記録上のプラス率とManski境界が整合する', () {
    BacktestMember mk(
      int rack, {
      required double? nextScore,
      required int nextGames,
      required int nextHits,
      required bool? nextPlus,
      bool current = false,
    }) => BacktestMember(
      rack: rack,
      machine: 'A',
      index: 50,
      days: 5,
      confidence: '少',
      todayScore: 50,
      nextScore: nextScore,
      nextGames: nextGames,
      nextHits: nextHits,
      nextPlus: nextPlus,
    )..current = current;

    // 4週分（28日）の合成グループ：候補は毎回当たりが多く点数・プラス率も高い。
    final groups = <BacktestGroup>[];
    for (var i = 0; i < 28; i++) {
      final day = shiftDay('2026-09-01', i);
      groups.add(
        BacktestGroup('nagamachiminami', 'A', day, [
          mk(1, nextScore: 72, nextGames: 4000, nextHits: 30, nextPlus: true, current: true),
          mk(2, nextScore: null, nextGames: 300, nextHits: 2, nextPlus: null, current: true),
          mk(3, nextScore: 48, nextGames: 4000, nextHits: 16, nextPlus: false),
          mk(4, nextScore: 45, nextGames: 4000, nextHits: 16, nextPlus: false),
          mk(5, nextScore: 46, nextGames: 4000, nextHits: 16, nextPlus: null),
          mk(6, nextScore: 47, nextGames: 4000, nextHits: 16, nextPlus: false),
        ], 2),
      );
    }
    final robust = evaluateRobustMetrics(groups, (m) => m.current);
    final scoreGap = robust['score_gap'] as Map<String, Object?>;
    expect(scoreGap['block7_count'], 4);
    expect(scoreGap['block7_p'], closeTo(1 / 16, 1e-4));
    expect(scoreGap['block14_count'], 2);
    expect(scoreGap['block14_p'], closeTo(1 / 4, 1e-4));

    final oe = robust['oe_ratio'] as Map<String, Object?>;
    expect(oe['ratio'] as double, greaterThan(1.2));

    final plus = robust['plus_rate'] as Map<String, Object?>;
    final worst = plus['manski_worst'] as double;
    final best = plus['manski_best'] as double;
    final both0 = plus['both_zero'] as double;
    final both1 = plus['both_one'] as double;
    expect(worst, lessThanOrEqualTo(both0));
    expect(worst, lessThanOrEqualTo(both1));
    expect(both0, lessThanOrEqualTo(best));
    expect(both1, lessThanOrEqualTo(best));

    final flat = blockBootstrap({'2026-09-01': 3.0, '2026-09-08': 3.0})!;
    expect(flat, (3.0, 3.0));
    expect(blockBootstrap({'2026-09-01': 3.0}), isNull);
    final flip = blockSignFlipP({'2026-09-01': 2.0, '2026-09-08': 4.0})!;
    expect((flip.blocks, flip.p), (2, 0.25));
  });
}
