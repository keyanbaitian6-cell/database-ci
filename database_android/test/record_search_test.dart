import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord row(int rack, {String machine = '北斗'}) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-28',
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
);

const score = ScoreResult(provisional: true, referenceCount: 0, reasons: []);

void main() {
  test('台番号は完全一致し、全角・番台・#にも対応する', () {
    for (final query in ['123', '１２３', '123番台', '１２３番台', '#123', '＃１２３']) {
      final search = RecordQuery(query);
      expect(search.matches(row(123)), isTrue, reason: query);
      expect(search.matches(row(12)), isFalse, reason: query);
      expect(search.matches(row(1230)), isFalse, reason: query);
    }
  });

  test('数字の機種名検索を残し、番台指定なら台番号だけを探す', () {
    final juggler = row(20, machine: 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3');
    expect(RecordQuery('3').matches(juggler), isTrue);
    expect(RecordQuery('３番台').matches(juggler), isFalse);
    expect(RecordQuery('#3').matches(juggler), isFalse);
    expect(RecordQuery('じゃぐらー').matches(juggler), isTrue);
    expect(RecordQuery('  ').matches(juggler), isTrue);
    expect(RecordQuery('北斗123').matches(row(123)), isFalse);
  });

  test('通常機種とバラエティを台番号で絞り、元の記録と区分を変えない', () {
    final entries = [
      for (var rack = 120; rack <= 123; rack++) (row(rack), score),
      (row(200, machine: 'ハナハナ'), score),
    ];
    final groups = groupForList(entries);
    final summaries = summarizeMachines(entries);
    final normal = summaries.first;
    final variety = summaries.last;
    expect(normal.variety, isFalse);
    expect(
      filterForList(
        normal,
        groups[normal.machine]!,
        '１２３番台',
      )!.map((e) => e.$1.rack),
      [123],
    );
    expect(
      filterForList(
        variety,
        groups[variety.machine]!,
        '#200',
      )!.map((e) => e.$1.rack),
      [200],
    );
    expect(filterForList(normal, groups[normal.machine]!, '999番台'), isNull);
    expect(filterForList(normal, groups[normal.machine]!, ''), hasLength(4));
    expect(groups[normal.machine], hasLength(4));
    expect(entries, hasLength(5));
  });
}
