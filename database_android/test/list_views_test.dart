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
    expect(machineMatches('L革命機ｳﾞｧﾙｳﾞﾚｲｳﾞ2jF', 'ヴァルヴレイヴ'), isTrue);
    expect(machineMatches('Lスマスロ北斗の拳', 'ジャグラー'), isFalse);
    expect(machineMatches('何でも', '  '), isTrue);
  });

  test('機種一覧：台数順に並べ、台数・平均・最高・グラフ未取得をまとめる', () {
    final list = summarizeMachines([
      (rec(9, machine: 'B'), score(50)),
      (rec(1, machine: 'A'), score(80)),
      (rec(2, machine: 'A'), score(60)),
      (rec(4, machine: 'A'), score(null)),
      (rec(5, machine: 'A'), score(70)),
    ]);
    expect([for (final s in list) s.machine], ['A', 'バラエティ']);
    final a = list.first;
    expect((a.racks, a.machines, a.variety), (4, 1, false));
    expect(a.scored, 3);
    expect(a.average, 70);
    expect(a.best, 80);
    expect(a.bestRack, 1);
    expect(a.noGraph, 4);
  });

  test('設置機種一覧：台数の多い順、同数なら機種名順。1〜3台の機種はバラエティで最後', () {
    final list = summarizeMachines([
      for (var rack = 1; rack <= 4; rack++) (rec(rack, machine: 'C'), score(50)),
      for (var rack = 11; rack <= 14; rack++)
        (rec(rack, machine: 'A'), score(50)),
      for (var rack = 21; rack <= 25; rack++)
        (rec(rack, machine: 'B'), score(50)),
      (rec(31, machine: 'D'), score(90)),
      (rec(32, machine: 'E'), score(40)),
      (rec(33, machine: 'E'), score(null)),
    ]);

    expect([for (final s in list) '${s.machine}:${s.racks}'], [
      'B:5',
      'A:4',
      'C:4',
      'バラエティ:3',
    ]);
    final variety = list.last;
    expect((variety.variety, variety.machines), (true, 2));
    expect((variety.best, variety.bestRack, variety.average), (90, 31, 65));
  });

  test('バラエティ：台番号順にまとめ、検索は「バラエティ」でも機種名でも当たる', () {
    final entries = [
      for (var rack = 1; rack <= 4; rack++)
        (rec(rack, machine: 'ハナハナ'), score(50)),
      (rec(20, machine: 'キングハナハナ'), score(60)),
      (rec(12, machine: '北斗'), score(70)),
      (rec(13, machine: '北斗'), score(40)),
    ];
    final groups = groupForList(entries);
    expect(groups.keys.toSet(), {'ハナハナ', 'バラエティ'});
    expect(groups['バラエティ']!.map((e) => e.$1.rack), [12, 13, 20]);
    final variety = summarizeMachines(entries).last;
    expect(filterForList(variety, groups['バラエティ']!, ''), hasLength(3));
    expect(filterForList(variety, groups['バラエティ']!, 'ばらえてぃ'), hasLength(3));
    // 機種名で当たったときは、その機種の台だけ。
    expect(
      filterForList(variety, groups['バラエティ']!, '北斗')!.map((e) => e.$1.rack),
      [12, 13],
    );
    expect(
      filterForList(variety, groups['バラエティ']!, 'はなはな')!.map((e) => e.$1.rack),
      [20],
    );
    expect(filterForList(variety, groups['バラエティ']!, 'ジャグラー'), isNull);
    // 4台以上の機種は今まで通り、機種名だけで判定する。
    final hana = summarizeMachines(entries).first;
    expect(filterForList(hana, groups['ハナハナ']!, 'はなはな'), hasLength(4));
    expect(filterForList(hana, groups['ハナハナ']!, '北斗'), isNull);
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
      for (final rack in [9, 8, 7, 6]) rec(rack, store: 'saiwaichou'),
      for (final rack in [15, 14, 13, 12]) rec(rack, machine: 'B'),
      for (final rack in [4, 3, 1, 2]) rec(rack),
    ]);
    expect([for (final d in days) d.$1], ['2026-09-22', '2026-09-21']);
    final latest = days.first.$2;
    expect(
      [for (final g in latest) '${g.store}/${g.machine}'],
      ['nagamachiminami/B', 'nagamachiminami/テスト', 'saiwaichou/テスト'],
    );
    expect([for (final r in latest[1].rows) r.rack], [1, 2, 3, 4]);
    // 9/21は1台だけの機種なので、バラエティの1行になる。
    expect(
      [for (final g in days.last.$2) (g.machine, g.variety, g.machines)],
      [('バラエティ', true, 1)],
    );
  });

  test('過去の記録：1〜3台の機種は店ごとにバラエティ1行にまとめ、その店の最後に置く', () {
    final days = groupHistoryByDay([
      for (var rack = 1; rack <= 4; rack++) rec(rack, machine: 'Z'),
      rec(30, machine: '北斗'),
      rec(31, machine: '北斗'),
      rec(20, machine: 'ハナハナ'),
      rec(40, machine: '北斗', store: 'saiwaichou'),
    ]);
    final groups = days.single.$2;
    expect(
      [for (final g in groups) '${g.store}/${g.machine}/${g.machines}'],
      [
        'nagamachiminami/Z/1',
        'nagamachiminami/バラエティ/2',
        'saiwaichou/バラエティ/1',
      ],
    );
    expect([for (final r in groups[1].rows) r.rack], [20, 30, 31]);
    // 機種名で絞り込んだときは、その機種の台だけにできる。
    final only = groups[1].withRows([
      for (final r in groups[1].rows)
        if (r.machine == '北斗') r,
    ]);
    expect((only.variety, only.machines, only.rows.length), (true, 1, 2));
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

  test('表示用の機種名：半角カナを全角にそろえ、それ以外は変えない', () {
    expect(displayMachineName('ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3'), 'ゴーゴージャグラー3');
    expect(displayMachineName('ﾌｧﾝｷｰｼﾞｬｸﾞﾗｰ2KT'), 'ファンキージャグラー2KT');
    expect(displayMachineName('L革命機ｳﾞｧﾙｳﾞﾚｲｳﾞ2jF'), 'L革命機ヴァルヴレイヴ2jF');
    expect(displayMachineName('L革命機ヴァルヴレイヴ2jF'), 'L革命機ヴァルヴレイヴ2jF');
    expect(displayMachineName('SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅV PA-30'), 'SBニューキングハナハナV PA-30');
    expect(displayMachineName('L 防振り FN'), 'L 防振り FN');
    expect(displayMachineName('Sハナハナホウオウ～天翔～EX-30'), 'Sハナハナホウオウ～天翔～EX-30');
  });

  test('機種の並び：半角カナの機種も全角にそろえた名前の順に並ぶ', () {
    final list = summarizeMachines([
      for (final (i, machine) in [
        'L戦国乙女5L8',
        'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3',
        'キングハナハナ',
      ].indexed)
        for (var rack = 1; rack <= 4; rack++)
          (rec(i * 10 + rack, machine: machine), score(50)),
    ]);
    expect(list.map((s) => displayMachineName(s.machine)).toList(), [
      'L戦国乙女5L8',
      'キングハナハナ',
      'ゴーゴージャグラー3',
    ]);
  });
}
