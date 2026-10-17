import 'dart:convert';
import 'dart:io';

import 'package:database_android/data_checks.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/normal_next_day_model.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 幸町のジャグラー・ハナハナの翌日候補を予想の式で並べる（2026-10-17）。PC版
/// tests/test_normal_next_day_model.py と同じ試験用の記録・同じ期待値を読む。
void main() {
  final doc = jsonDecode(
    File('../database/tests/fixtures/normal_next_day_rows.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  final rows = [
    for (final r in doc['rows'] as List)
      SlotRecord.fromJson(Map<String, dynamic>.from(r as Map)),
  ];

  test('幸町のジャグラー・ハナハナだけ、10/17以降だけ。選び方の名前も変わる', () {
    expect(
      normalModelApplies('saiwaichou', 'SマイジャグラーVKD', '2026-10-17'),
      isTrue,
    );
    expect(
      normalModelApplies('saiwaichou', 'SマイジャグラーVKD', '2026-10-16'),
      isFalse,
    );
    expect(
      normalModelApplies('saiwaichou', 'SキングハナハナSP−30', '2026-11-01'),
      isTrue,
    );
    expect(
      normalModelApplies('nagamachiminami', 'SマイジャグラーVKD', '2026-11-01'),
      isFalse,
    );
    expect(
      normalModelApplies('saiwaichou', 'L ゴッドイーター', '2026-11-01'),
      isFalse,
    );
    expect(
      candidateMethodVersion('saiwaichou', 'SマイジャグラーVKD', '2026-10-17'),
      normalModelMethodVersion,
    );
    expect(
      candidateMethodVersion('saiwaichou', 'SマイジャグラーVKD', '2026-10-16'),
      nextDayMethodVersion,
    );
    expect(
      candidateMethodVersion('nagamachiminami', 'SマイジャグラーVKD', '2026-10-17'),
      nextDayMethodVersion,
    );
  });

  test('PC版と同じ候補・同じ点（共通の試験用の記録）', () {
    for (final e in doc['expected'] as List) {
      final day = e['day'] as String;
      final today = rows.where((r) => r.day == day).toList();
      final result = provisionalNextDayCandidates(today, rows);
      expect(
        [for (final c in result.candidates) c.record.rack],
        List<int>.from(e['candidates'] as List),
        reason: day,
      );
      final perRack = normalHistoryValues(rows, day);
      final scores = Map<String, dynamic>.from(e['scores'] as Map);
      for (final r in today) {
        final evidence = nextDayEvidence(r, rows);
        if (evidence.rawIndex == null) continue;
        final score = normalModelScore(
          normalModelFeatures(perRack, r, evidence.rawIndex!),
        );
        expect(
          score,
          closeTo((scores['${r.rack}'] as num).toDouble(), 1e-9),
          reason: '$day ${r.rack}',
        );
      }
    }
  });

  testWidgets('候補のカードに、予想の式で選んでいる説明を出す（幸町のノーマルだけ）', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    Widget card(String store) {
      final record = SlotRecord(
        store: store,
        day: '2026-10-20',
        machine: 'SマイジャグラーVKD',
        rack: 702,
        games: 6000,
        bb: 25,
        rb: 20,
      );
      return MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-09-20',
              store: store,
              allRecords: [record],
              candidates: [
                (
                  record: record,
                  index: 58.0,
                  days: 7,
                  confidence: '中',
                  variety: false,
                ),
              ],
              machines: 1,
              judged: 1,
              onPick: (_) {},
            ),
          ),
        ),
      );
    }

    await tester.pumpWidget(card('saiwaichou'));
    expect(find.text(normalModelNote), findsOneWidget);
    await tester.pumpWidget(card('nagamachiminami'));
    expect(find.text(normalModelNote), findsNothing);
  });

  group('ジャグラー・ハナハナのおすすめを別ページに分ける（2026-10-18 利用者指定）', () {
    // 同じ日に、ジャグラー（試験用の記録）と、ほかの機種4台をそろえる。
    List<SlotRecord> withOther(String store) => [
      for (final r in rows)
        SlotRecord.fromJson({...r.toJson(), 'store': store}),
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

    test('今までの候補から外し、おすすめにはそれだけを出す（幸町だけ）', () {
      final all = withOther('saiwaichou');
      final dayRows = [
        for (final r in all)
          if (r.day == day) r,
      ];
      final mixed = dayCandidates(dayRows, all).candidates;
      final regular = dayCandidates(dayRows, all, excludeNormal: true);
      final normal = normalDayCandidates(dayRows, all);
      expect(mixed.any((c) => c.record.machine == 'SマイジャグラーVKD'), isTrue);
      expect(
        regular.candidates.any((c) => c.record.machine.contains('ジャグラー')),
        isFalse,
      );
      expect(regular.candidates, isNotEmpty);
      expect(normal.candidates, isNotEmpty);
      expect(
        normal.candidates.every((c) => c.record.machine == 'SマイジャグラーVKD'),
        isTrue,
      );
      // おすすめの並びは、その機種の候補の順（式の点の高い順）のまま。
      final machineRows = [
        for (final r in dayRows)
          if (r.machine == 'SマイジャグラーVKD') r,
      ];
      expect(
        [for (final c in normal.candidates) c.record.rack],
        [
          for (final c in provisionalNextDayCandidates(machineRows, [
            for (final r in all)
              if (r.machine == 'SマイジャグラーVKD') r,
          ]).candidates)
            c.record.rack,
        ],
      );
      // 長町南は分けない。
      final other = withOther('nagamachiminami');
      final otherDay = [
        for (final r in other)
          if (r.day == day) r,
      ];
      expect(
        dayCandidates(
          otherDay,
          other,
          excludeNormal: true,
        ).candidates.any((c) => c.record.machine.contains('ジャグラー')),
        isTrue,
      );
      expect(normalDayCandidates(otherDay, other).candidates, isEmpty);
      expect(hasNormalRecommendations('saiwaichou'), isTrue);
      expect(hasNormalRecommendations('nagamachiminami'), isFalse);
    });

    testWidgets('おすすめのページ：見出し・説明・一覧', (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 2400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final all = withOther('saiwaichou');
      final picked = <int>[];
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: NormalRecommendationsPage(
            store: 'saiwaichou',
            day: day,
            records: all,
            onPick: (r) => picked.add(r.rack),
          ),
        ),
      );
      expect(find.textContaining('ジャグラー・ハナハナのおすすめ'), findsWidgets);
      expect(find.text(normalModelNote), findsOneWidget);
      expect(find.textContaining('おすすめ（'), findsOneWidget);
      expect(find.textContaining('★ 翌日向けに注目'), findsNothing);
      expect(find.text(nextDayValidationNote), findsNothing);
    });
  });
}
