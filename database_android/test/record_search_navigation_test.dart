import 'package:database_android/machine_sections.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'android_variety_review_test.dart' show ReviewController;

List<SlotRecord> records({bool pscube = false}) => [
  for (final day in ['2026-09-28', '2026-09-27'])
    for (var rack = 120; rack <= 123; rack++)
      SlotRecord(
        store: pscube ? 'pscube:c1:20' : 'nagamachiminami',
        day: day,
        machine: '北斗',
        rack: rack,
        games: 400,
        bb: 0,
        rb: 0,
        extra: pscube ? {'source': 'pscube', 'my': 0, 'rate': '20'} : const {},
      ),
];

Future<void> prepare(WidgetTester tester, Widget page) async {
  await tester.binding.setSurfaceSize(const Size(393, 1800));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: page),
    ),
  );
  await tester.pumpAndSettle();
}

Iterable<int> shownRacks(WidgetTester tester) => tester
    .widget<MachineSection>(find.byType(MachineSection))
    .entries
    .map((e) => e.$1.rack);

void main() {
  testWidgets('Android：1機種でも検索でき、絞った台だけを表示し解除できる', (tester) async {
    final controller = ReviewController()..records = records();
    addTearDown(controller.dispose);
    await prepare(tester, ResultsPage(controller: controller));
    expect(find.byType(MachineSearchField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '１２３番台');
    await tester.pumpAndSettle();
    expect(shownRacks(tester), [123]);
    // 一部だけを表示中は機種全体の削除を出さない。
    expect(find.byIcon(Icons.delete_sweep_outlined), findsNothing);
    await tester.tap(find.byTooltip('絞り込みを消す'));
    await tester.pumpAndSettle();
    expect(shownRacks(tester), [120, 121, 122, 123]);
    expect(tester.takeException(), isNull);
  });

  for (final pscube in [false, true]) {
    testWidgets('閲覧版：検索→機種→グラフ→日付切替でも台番号を保持（P’s CUBE=$pscube）', (tester) async {
      await prepare(
        tester,
        ViewerHome(
          initialData: ViewerData(records: records(pscube: pscube)),
        ),
      );
      // 上のボタンが増えて検索欄が最初の画面の外になった（2026-11-11）。送ってから使う。
      await tester.scrollUntilVisible(
        find.byType(MachineSearchField),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.byType(MachineSearchField), findsOneWidget);
      await tester.enterText(find.byType(TextField), '#123');
      await tester.pumpAndSettle();
      // 実際の一覧タップから、検索語が次の画面へ渡ることを確認する。
      // （一覧の上に「全機種の台一覧」のボタンが入り、P’s CUBE版では画面の外になるので送ってから押す。2026-11-01）
      final hokuto = find.descendant(
        of: find.byType(MachineSummaryList),
        matching: find.text('北斗'),
      );
      await tester.ensureVisible(hokuto);
      await tester.pumpAndSettle();
      await tester.tap(hokuto);
      await tester.pumpAndSettle();
      expect(shownRacks(tester), [123]);
      await tester.tap(find.text('グラフ表示'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      expect(shownRacks(tester), [123]);
      expect(
        tester
            .widget<MachineSection>(find.byType(MachineSection))
            .entries
            .single
            .$1
            .day,
        '2026-09-27',
      );
      expect(find.byType(GraphGrid), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '999番台');
      await tester.pumpAndSettle();
      expect(find.textContaining('この日の検索条件に合う台がありません'), findsOneWidget);
      await tester.tap(find.byTooltip('絞り込みを消す'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<MachineSummaryList>(find.byType(MachineSummaryList))
            .summaries,
        hasLength(1),
      );
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('履歴：台番号検索を詳細と日付切替へ引き継ぐ', (tester) async {
    final controller = ReviewController()..records = records();
    addTearDown(controller.dispose);
    await prepare(tester, HistoryPage(controller: controller));
    await tester.enterText(find.byType(TextField), '123番台');
    await tester.pumpAndSettle();
    await tester.tap(find.text('北斗').first);
    await tester.pumpAndSettle();
    expect(shownRacks(tester), [123]);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(shownRacks(tester), [123]);
    expect(tester.takeException(), isNull);
  });
}
