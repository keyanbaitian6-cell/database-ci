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
}
