import 'package:database_android/list_views.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('選択日の表示：9/27（日）の形。読めない日付は空', () {
    expect(shortDayLabel('2026-09-27'), '9/27（日）');
    expect(shortDayLabel('2026-10-01'), '10/1（木）');
    expect(shortDayLabel('bad'), '');
  });

  testWidgets('翌日候補のカード：選択日と対象日、検証の結果、データ量の意味を出す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    const record = SlotRecord(
      store: 'nagamachiminami',
      day: '2026-09-27',
      machine: 'テスト',
      rack: 5,
      games: 4000,
      bb: 20,
      rb: 10,
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-09-27',
              candidates: const [
                (record: record, index: 58.0, days: 7, confidence: '中'),
              ],
              machines: 3,
              judged: 1,
              onPick: (_) {},
            ),
          ),
        ),
      ),
    );
    expect(find.text('9/28（月） の候補（仮）'), findsOneWidget);
    expect(
      find.textContaining('9/27（日）（選択日）までの記録から、9/28（月）向けに選んだ台です'),
      findsOneWidget,
    );
    expect(find.text(nextDayValidationNote), findsOneWidget);
    expect(find.textContaining('当たりやすさを示すものではありません'), findsOneWidget);
    expect(find.textContaining('過去7日分・データ量 中'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
