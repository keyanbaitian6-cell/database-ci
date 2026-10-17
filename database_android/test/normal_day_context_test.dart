import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/normal_day_context.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 翌日の曜日傾向の補足（幸町のジャグラー・ハナハナ、表示専用）。PC tests/test_normal_day_context.py と同じ例。
void main() {
  test('翌日が土日か平日か。幸町のジャグラー・ハナハナだけ、確定日以降だけ', () {
    final friday = normalDayContext('saiwaichou', '2026-10-23', [
      'SマイジャグラーVKD',
    ])!;
    expect(friday.targetDay, '2026-10-24');
    expect(friday.weekend, isTrue);
    expect(friday.title, '10/24（土）の曜日傾向：土日');
    final sunday = normalDayContext('saiwaichou', '2026-10-25', [
      'SキングハナハナSP−30',
    ])!;
    expect(sunday.targetDay, '2026-10-26');
    expect(sunday.weekend, isFalse);
    expect(sunday.body, contains('該当しません'));
    expect(
      normalDayContext('nagamachiminami', '2026-10-23', ['SマイジャグラーVKD']),
      isNull,
    );
    expect(normalDayContext('saiwaichou', '2026-10-23', ['L ゴッドイーター']), isNull);
    expect(
      normalDayContext('saiwaichou', '2026-10-16', ['SマイジャグラーVKD']),
      isNull,
    );
    for (final bad in ['2026-02-30', '2026/10/23', '']) {
      expect(normalDayContext('saiwaichou', bad, ['SマイジャグラーVKD']), isNull);
    }
    expect(normalDayContextEvidence, contains('候補の点数・順位には反映していません'));
    expect(normalDayContextEvidence, contains('混雑で長く打たれる台が増えるためか'));
  });

  Widget card(String store, String machine) {
    final record = SlotRecord(
      store: store,
      day: '2026-10-23',
      machine: machine,
      rack: 700,
      games: 4000,
      bb: 15,
      rb: 12,
    );
    return MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        body: SingleChildScrollView(
          child: NextDayCandidatesCard(
            day: '2026-10-23',
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

  testWidgets('翌日候補のカードに、幸町のノーマルだけ曜日傾向と根拠を出す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(card('saiwaichou', 'SマイジャグラーVKD'));
    expect(find.text('10/24（土）の曜日傾向：土日'), findsOneWidget);
    await tester.tap(find.text('曜日傾向の根拠と限界'));
    await tester.pumpAndSettle();
    expect(find.text(normalDayContextEvidence), findsOneWidget);
    await tester.pumpWidget(card('nagamachiminami', 'SマイジャグラーVKD'));
    expect(find.textContaining('曜日傾向'), findsNothing);
    await tester.pumpWidget(card('saiwaichou', 'L ゴッドイーター'));
    expect(find.textContaining('曜日傾向'), findsNothing);
  });
}
