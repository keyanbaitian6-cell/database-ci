import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';

SlotRecord rec(
  int rack, {
  String store = 'nagamachiminami',
  String day = '2026-09-22',
  String machine = 'テスト',
}) => SlotRecord(
  store: store,
  day: day,
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
);

ScoreResult score(double? total) => ScoreResult(
  total: total,
  provisional: false,
  referenceCount: 20,
  reasons: const [],
);

void main() {
  test('機種名の検索：ひらがな・半角カナ・全角英字・空白と+の違いを気にしない', () {
    expect(machineMatches('SマイジャグラーV KD', 'じゃぐらー'), isTrue);
    expect(machineMatches('ｱｲﾑｼﾞｬｸﾞﾗｰEX', 'ジャグラー'), isTrue);
    expect(machineMatches('ｱｲﾑｼﾞｬｸﾞﾗｰEX', 'ｼﾞｬｸﾞﾗｰ'), isTrue);
    expect(machineMatches('L+防振り+FN', 'l防振り'), isTrue);
    expect(machineMatches('Ｌ戦国乙女５', 'l戦国乙女5'), isTrue);
    expect(machineMatches('Lスマスロ北斗の拳', 'ジャグラー'), isFalse);
    expect(machineMatches('何でも', '  '), isTrue);
  });

  test('機種一覧：機種名順に台数・平均・最高・グラフ未取得をまとめる', () {
    final list = summarizeMachines([
      (rec(3, machine: 'B'), score(50)),
      (rec(1, machine: 'A'), score(80)),
      (rec(2, machine: 'A'), score(60)),
      (rec(4, machine: 'A'), score(null)),
    ]);
    expect([for (final s in list) s.machine], ['A', 'B']);
    final a = list.first;
    expect(a.racks, 3);
    expect(a.scored, 2);
    expect(a.average, 70);
    expect(a.best, 80);
    expect(a.bestRack, 1);
    expect(a.noGraph, 3);
  });

  test('機種一覧：採点できた台が無ければ平均・最高は空', () {
    final only = summarizeMachines([(rec(1), score(null))]).single;
    expect(only.average, isNull);
    expect(only.best, isNull);
    expect(only.bestRack, isNull);
  });

  test('過去の記録：日付の新しい順、同じ日は店舗・機種名順、台は番号順', () {
    final days = groupHistoryByDay([
      rec(2, day: '2026-09-21'),
      rec(9, store: 'saiwaichou'),
      rec(5, machine: 'B'),
      rec(3),
      rec(1),
    ]);
    expect([for (final d in days) d.$1], ['2026-09-22', '2026-09-21']);
    final latest = days.first.$2;
    expect(
      [for (final g in latest) '${g.store}/${g.machine}'],
      ['nagamachiminami/B', 'nagamachiminami/テスト', 'saiwaichou/テスト'],
    );
    expect([for (final r in latest[1].rows) r.rack], [1, 3]);
  });

  test('日付に曜日を付ける。読めない日付はそのまま', () {
    expect(dayWithWeekday('2026-09-23'), '2026-09-23（水）');
    expect(dayWithWeekday('2026-09-27'), '2026-09-27（日）');
    expect(dayWithWeekday('2026-02-30'), '2026-02-30');
  });

  test('確率は 1/xx.x、当たりが無ければ —（1/0.0 とは書かない）', () {
    expect(hitRate(2254, 10), '1/225.4');
    expect(hitRate(591, 0), '—');
    expect(hitRate(0, 0), '—');
  });

  test('平均の行：数は台の平均、確率は合計どうしで割る', () {
    SlotRecord r(int games, int bb, int rb, int? hold) => SlotRecord(
      store: 'nagamachiminami',
      day: '2026-09-22',
      machine: 'テスト',
      rack: games,
      games: games,
      bb: bb,
      rb: rb,
      maxHold: hold,
    );
    final avg = rackAverages([
      (r(3000, 12, 8, 1000), score(60)),
      (r(1000, 2, 0, null), score(null)),
    ]);
    expect(avg.games, 2000);
    expect(avg.bb, 7);
    expect(avg.rb, 4);
    expect(avg.combined, '1/181.8'); // 4000 / 22
    expect(avg.bbRate, '1/285.7'); // 4000 / 14
    expect(avg.rbRate, '1/500.0'); // 4000 / 8
    expect(avg.maxHold, 1000);
    expect(avg.score, 60);
  });

  test('翌日の表示：月末をまたいでも正しい日と曜日', () {
    expect(nextDayLabel('2026-09-23'), '9/24（木）');
    expect(nextDayLabel('2026-09-30'), '10/1（木）');
    expect(nextDayLabel('bad'), '');
  });

  test('その日の翌日候補：機種ごとの候補を集め、平均よりの大きい順', () {
    // 2機種×5台×4日。台番号が小さいほど当たりが軽い。
    final all = <SlotRecord>[
      for (final machine in ['A', 'B'])
        for (final day in [
          '2026-09-20',
          '2026-09-21',
          '2026-09-22',
          '2026-09-23',
        ])
          for (var rack = 1; rack <= 5; rack++)
            SlotRecord(
              store: 'nagamachiminami',
              day: day,
              machine: machine,
              rack: machine == 'A' ? rack : rack + 10,
              games: 3000,
              bb: 30 - rack * (machine == 'A' ? 3 : 2),
              rb: 10,
            ),
    ];
    final dayRows = [
      for (final r in all)
        if (r.day == '2026-09-23') r,
    ];
    final result = dayCandidates(dayRows, all);
    expect(result.machines, 2);
    expect(result.judged, 2);
    // 各機種 5台中 判定5台 → 上位 ceil(5/4)=2台ずつ。
    expect(result.candidates.length, 4);
    expect({for (final c in result.candidates) c.record.rack}, {1, 2, 11, 12});
    for (var i = 1; i < result.candidates.length; i++) {
      expect(
        result.candidates[i - 1].index >= result.candidates[i].index,
        isTrue,
      );
    }
  });
}
