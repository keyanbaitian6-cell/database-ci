import 'package:database_android/answer_check.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String day, int rack, {int bb = 10, String machine = 'A'}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: day,
      machine: machine,
      rack: rack,
      games: 4000,
      bb: bb,
      rb: 10,
      maxHold: bb * 100,
    );

void main() {
  // 1機種8台。9/20〜9/23は台番号が小さいほど当たりが軽い（9/23の翌日候補は
  // 上位4分の1の1・2番台）。9/24は1番台だけ大きく出て、2番台は出なかった。
  final history = [
    for (final day in ['2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23'])
      for (var rack = 1; rack <= 8; rack++) rec(day, rack, bb: 34 - rack * 3),
  ];
  final all = [
    ...history,
    rec('2026-09-24', 1, bb: 40),
    rec('2026-09-24', 2, bb: 2),
    for (var rack = 3; rack <= 8; rack++) rec('2026-09-24', rack),
  ];

  test('前の日の候補のうち、その日に60点以上の台だけを挙げる', () {
    final result = answerCheckFor(all, 'nagamachiminami', '2026-09-24')!;
    final before = dayCandidates([
      for (final r in all)
        if (r.day == '2026-09-23') r,
    ], all).candidates;
    expect(before.map((c) => c.record.rack), [1, 2]);
    expect(result.predictedOn, '2026-09-23');
    expect(result.candidates, 2);
    expect(result.scored, 2);
    expect(result.hits.map((h) => h.result.rack), [1]);
    final hit = result.hits.single;
    expect(hit.result.day, '2026-09-24');
    expect(hit.score.total, scoreRecord(hit.result, all).total);
    expect(hit.score.total, greaterThanOrEqualTo(answerCheckThreshold));
    // 2番台（候補だが外れ）は60点未満。
    final miss = all.firstWhere((r) => r.day == '2026-09-24' && r.rack == 2);
    expect(scoreRecord(miss, all).total, lessThan(answerCheckThreshold));
  });

  test('候補は前の日までの記録だけで決まる（その日の結果を見て変わらない）', () {
    final onlyBefore = [
      for (final r in all)
        if (r.day.compareTo('2026-09-23') <= 0) r,
    ];
    final rows = [
      for (final r in all)
        if (r.day == '2026-09-23') r,
    ];
    expect(
      dayCandidates(rows, all).candidates.map((c) => (c.record.rack, c.index)),
      dayCandidates(rows, onlyBefore)
          .candidates
          .map((c) => (c.record.rack, c.index)),
    );
  });

  test('機種が入れ替わった台・取り込んでいない台は数えない。前の日が無ければ対象外', () {
    final swapped = [
      ...history,
      rec('2026-09-24', 1, bb: 40, machine: 'B'), // 1番台は別の機種に
      for (var rack = 3; rack <= 8; rack++) rec('2026-09-24', rack), // 2番台は無し
    ];
    final result = answerCheckFor(swapped, 'nagamachiminami', '2026-09-24')!;
    expect((result.candidates, result.scored), (2, 0));
    expect(result.hits, isEmpty);
    expect(answerCheckFor(all, 'nagamachiminami', '2026-09-20'), isNull);
    expect(answerCheckFor(all, 'saiwaichou', '2026-09-24'), isNull);
  });

  test('答え合わせできる日：前の日にも記録がある日だけ、新しい順', () {
    final gap = [
      ...all,
      rec('2026-09-26', 1), // 9/25が無いので対象外
    ];
    expect(answerCheckDays(gap, 'nagamachiminami'), [
      '2026-09-24',
      '2026-09-23',
      '2026-09-22',
      '2026-09-21',
    ]);
    expect(answerCheckDays(gap, 'saiwaichou'), isEmpty);
  });
}
