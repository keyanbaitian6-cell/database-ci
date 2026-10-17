import 'dart:convert';
import 'dart:io';

import 'package:database_android/data_checks.dart';
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
}
