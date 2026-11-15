import 'package:database_android/answer_check.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/viewer_bridge.dart';
import 'package:flutter/material.dart';
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
      dayCandidates(
        rows,
        onlyBefore,
      ).candidates.map((c) => (c.record.rack, c.index)),
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

  // 2026-11-04：当時保存した候補で照らし、全台の目安を並べる（利用者が選んだ「翌日候補の答え合わせ」）。
  test('当時の候補があれば、計算し直した候補の代わりにそれで照らす', () {
    final recomputed = answerCheckFor(all, 'nagamachiminami', '2026-09-24')!;
    expect(recomputed.saved, isFalse);
    final saved = answerCheckFor(
      all,
      'nagamachiminami',
      '2026-09-24',
      saved: {
        'nagamachiminami|2026-09-23': [
          (rack: 2, index: 61.5, variety: false),
          (rack: 3, index: 58.0, variety: false),
          (rack: 99, index: 70.0, variety: false), // 前の日に記録の無い台は数えない
        ],
      },
    )!;
    expect(saved.saved, isTrue);
    expect(saved.candidates, 2);
    expect(saved.scored, 2);
    expect(saved.hits, isEmpty, reason: '当時の候補（2・3番台）は外れ。計算し直すと当たる1番台は入れない');
    expect(
      answerCheckFor(
        all,
        'nagamachiminami',
        '2026-09-24',
        saved: {
          'saiwaichou|2026-09-23': [(rack: 1, index: 60.0, variety: false)],
        },
      )!.saved,
      isFalse,
      reason: 'ほかの店・ほかの日の保存は使わない',
    );
  });

  test('くらべる目安は、前の日にも同じ機種で記録がある全台', () {
    final withNew = [...all, rec('2026-09-24', 9, bb: 40, machine: 'B')];
    final result = answerCheckFor(withNew, 'nagamachiminami', '2026-09-24')!;
    final scores = [
      for (final r in withNew)
        if (r.day == '2026-09-24' && r.machine == 'A')
          scoreRecord(r, withNew).total,
    ].whereType<double>().toList();
    expect(result.baseScored, scores.length, reason: '前の日に無い台（新台の9番台）は数えない');
    expect(
      result.baseHits,
      scores.where((t) => t >= answerCheckThreshold).length,
    );
    expect(result.baseHits, greaterThanOrEqualTo(result.hits.length));
  });

  // 2026-11-15 利用者「採点結果しか出てなくてタップしないとデータがわかりづらいので、機種一覧から開いたような
  // …データ一覧を見せて欲しい」。並べる台は「前日の候補の全台」（外れた台も）。
  test('日ごとの表には、前の日の候補のうちその日に記録がある全台を台番号順に入れる', () {
    final saved = answerCheckFor(
      all,
      'nagamachiminami',
      '2026-09-24',
      saved: {
        'nagamachiminami|2026-09-23': [
          (rack: 3, index: 58.0, variety: false),
          (rack: 1, index: 70.0, variety: false),
          (rack: 2, index: 61.5, variety: false),
        ],
      },
    )!;
    expect(saved.rows.map((e) => e.$1.rack), [1, 2, 3], reason: '外れた2・3番台も入れる');
    expect(saved.rows.every((e) => e.$1.day == '2026-09-24'), isTrue);
    for (final (record, score) in saved.rows) {
      expect(score.total, scoreRecord(record, all).total);
    }
    // 機種が入れ替わった台・その日に記録が無い台は、表に入れない（数字が無い）。
    final swapped = [
      ...history,
      rec('2026-09-24', 1, bb: 40, machine: 'B'),
      for (var rack = 3; rack <= 8; rack++) rec('2026-09-24', rack),
    ];
    final none = answerCheckFor(swapped, 'nagamachiminami', '2026-09-24')!;
    expect((none.candidates, none.rows.length), (2, 0));
  });

  testWidgets('日ごとのカードに機種一覧と同じ表を出し、60点以上に◎、行を押すと台を開く', (tester) async {
    tester.view.physicalSize = const Size(1200, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final opened = <SlotRecord>[];
    await tester.pumpWidget(
      MaterialApp(
        home: AnswerCheckPage(
          records: all,
          store: 'nagamachiminami',
          onOpen: (record, _) => opened.add(record),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final tables = tester
        .widgetList<MachineDataTable>(find.byType(MachineDataTable))
        .toList();
    final latest = tables.firstWhere(
      (t) => t.entries.first.$1.day == '2026-09-24',
    );
    expect(latest.entries.map((e) => e.$1.rack), [1, 2]);
    expect(latest.markedRacks, {1});
    expect(latest.showMachine, isTrue);
    expect(find.text('候補の台のこの日のデータ（台番号順・2台）'), findsWidgets);
    expect(find.textContaining('◎＝合計60点以上'), findsWidgets);
    final mark = find.text(' ◎').first;
    await tester.ensureVisible(mark);
    await tester.tap(mark);
    expect(opened.map((r) => (r.day, r.rack)), [('2026-09-24', 1)]);
    expect(tester.takeException(), isNull);
  });

  // 2026-11-15 利用者「並べ方もプルダウンで選べるように」。機種一覧と同じ選択肢・同じ並べ方で、全部の日の表に効く。
  testWidgets('並べ方のプルダウンで、日ごとの表を並べ替える', (tester) async {
    tester.view.physicalSize = const Size(1200, 5000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    addTearDown(() => saveViewerSetting(answerSortSetting, 'rack'));
    await tester.pumpWidget(
      MaterialApp(
        home: AnswerCheckPage(
          records: all,
          store: 'nagamachiminami',
          onOpen: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    List<int> latestRacks() => tester
        .widgetList<MachineDataTable>(find.byType(MachineDataTable))
        .firstWhere((t) => t.entries.first.$1.day == '2026-09-24')
        .entries
        .map((e) => e.$1.rack)
        .toList();
    expect(latestRacks(), [1, 2]);
    await tester.tap(find.byKey(const ValueKey('answer-check-sort')));
    await tester.pumpAndSettle();
    for (final label in ['台番号順', '回転数の多い順', '点数の低い順', '機種順']) {
      expect(find.text(label), findsWidgets, reason: label);
    }
    await tester.tap(find.text('点数の低い順').last);
    await tester.pumpAndSettle();
    expect(latestRacks(), [2, 1], reason: '2番台（外れ）が先');
    expect(find.text('候補の台のこの日のデータ（点数の低い順・2台）'), findsWidgets);
    expect(loadViewerSetting(answerSortSetting), 'score-asc');
    expect(tester.takeException(), isNull);
  });
}
