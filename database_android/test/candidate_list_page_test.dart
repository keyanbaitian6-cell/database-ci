import 'dart:convert';
import 'dart:io';

import 'package:database_android/candidate_list_page.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 狙い台一覧（台番号順、2026-11-17）。選び方は変えず、今までの候補を集めて並べ替えるだけ。
void main() {
  final doc = jsonDecode(
    File('../database/tests/fixtures/normal_next_day_rows.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  final rows = [
    for (final r in doc['rows'] as List)
      SlotRecord.fromJson(Map<String, dynamic>.from(r as Map)),
  ];
  // ジャグラー（試験用の記録）と、ほかの機種を同じ日にそろえる（normal_next_day_model_test と同じ）。
  List<SlotRecord> withOther(String store) => [
    for (final r in rows) SlotRecord.fromJson({...r.toJson(), 'store': store}),
    for (final r in rows)
      if (r.rack < 704)
        SlotRecord.fromJson({
          ...r.toJson(),
          'store': store,
          'machine': 'L ゴッドイーター',
          'rack': r.rack + 100,
        }),
  ];
  const day = '2026-10-20';

  test('今までの候補をすべて集め、台番号の順に並べる（選び方は変えない）', () {
    final all = withOther('saiwaichou');
    final dayRows = [
      for (final r in all)
        if (r.day == day) r,
    ];
    final list = candidateListRows('saiwaichou', day, all);
    final regular = dayCandidates(dayRows, all, excludeNormal: true).candidates;
    final normal = normalDayCandidates(dayRows, all).candidates;
    expect(list.length, regular.length + normal.length);
    expect(list, isNotEmpty);
    final racks = [for (final r in list) r.candidate.record.rack];
    expect([...racks]..sort(), racks);
    // 幸町のジャグラーは「おすすめ」、ほかは★か☆。
    expect(
      list
          .where((r) => r.kind == CandidateKind.normal)
          .every((r) => r.candidate.record.machine == 'SマイジャグラーVKD'),
      isTrue,
    );
    expect(list.where((r) => r.kind == CandidateKind.normal).length, normal.length);
    // 元の候補と同じ台・同じ指数のまま。
    for (final r in list) {
      final same = [...regular, ...normal].where(
        (c) => c.record.rack == r.candidate.record.rack,
      );
      expect(same.any((c) => c.index == r.candidate.index), isTrue);
    }
  });

  test('幸町以外はジャグラー・ハナハナを分けず、そのまま★・☆に入る', () {
    final all = withOther('nagamachiminami');
    final list = candidateListRows('nagamachiminami', day, all);
    expect(list.any((r) => r.kind == CandidateKind.normal), isFalse);
    expect(
      list.any((r) => r.candidate.record.machine == 'SマイジャグラーVKD'),
      isTrue,
    );
  });

  test('P’s CUBEの店でも、同じ選び方の候補が台番号順に出る', () {
    const store = 'pscube:c740601:20';
    final all = withOther(store);
    final list = candidateListRows(store, day, all);
    final dayRows = [
      for (final r in all)
        if (r.day == day) r,
    ];
    expect(
      list.length,
      dayCandidates(dayRows, all, excludeNormal: true).candidates.length,
    );
    expect(list, isNotEmpty);
    expect(list.any((r) => r.kind == CandidateKind.normal), isFalse);
    final racks = [for (final r in list) r.candidate.record.rack];
    expect([...racks]..sort(), racks);
  });

  test('別の日・別の店の台は混ざらない', () {
    final all = withOther('saiwaichou');
    expect(candidateListRows('saiwaichou', '2000-01-01', all), isEmpty);
    expect(candidateListRows('unknown-store', day, all), isEmpty);
  });

  testWidgets('一覧の画面：台番号・機種・理由の一行・絞り込み・タップ', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 2400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final all = withOther('saiwaichou');
    final picked = <int>[];
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: CandidateListPage(
          store: 'saiwaichou',
          day: day,
          records: all,
          onPick: (r) => picked.add(r.rack),
        ),
      ),
    );
    final list = candidateListRows('saiwaichou', day, all);
    expect(find.text('狙い台一覧（台番号順）'), findsOneWidget);
    expect(find.text(nextDayValidationNote), findsOneWidget);
    for (final r in list) {
      expect(find.byKey(ValueKey('candidate-row-${r.candidate.record.rack}')), findsOneWidget);
    }
    expect(find.textContaining('平均より'), findsWidgets);
    // 並びは台番号の昇順（画面の上から下）。
    final tops = [
      for (final r in list)
        tester.getTopLeft(find.byKey(ValueKey('candidate-row-${r.candidate.record.rack}'))).dy,
    ];
    expect([...tops]..sort(), tops);
    // 種類が2つ以上あるときだけ絞り込みが出て、押すとその種類だけになる。
    final kinds = {for (final r in list) r.kind};
    if (kinds.length > 1) {
      final only = kinds.first;
      await tester.tap(find.byKey(ValueKey('candidate-filter-${only.name}')));
      await tester.pump();
      final expected = list.where((r) => r.kind == only).length;
      expect(find.byWidgetPredicate((w) => w is InkWell && w.key.toString().contains('candidate-row-')), findsNWidgets(expected));
      await tester.tap(find.byKey(const ValueKey('candidate-filter-all')));
      await tester.pump();
    }
    await tester.tap(find.byKey(ValueKey('candidate-row-${list.first.candidate.record.rack}')));
    expect(picked, [list.first.candidate.record.rack]);
  });

  testWidgets('候補がない日は、不調ではないと説明する', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: CandidateListPage(
          store: 'saiwaichou',
          day: '2000-01-01',
          records: withOther('saiwaichou'),
          onPick: (_) {},
        ),
      ),
    );
    expect(find.textContaining('不調を意味しません'), findsOneWidget);
  });
}
