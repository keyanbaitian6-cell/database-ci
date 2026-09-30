import 'package:database_android/exploratory_page.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String store, String day, int rack) => SlotRecord(
  store: store,
  day: day,
  machine: 'テスト',
  rack: rack,
  games: 4000,
  bb: 20 + rack,
  rb: 10,
  maxHold: 1500,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
);

final records = [
  for (final store in ['nagamachiminami', 'saiwaichou'])
    for (var day = 20; day <= 28; day++)
      for (var rack = 1; rack <= 8; rack++) rec(store, '2026-09-$day', rack),
];

DropdownButtonFormField<String> storeSelector(WidgetTester tester) => tester
    .widgetList<DropdownButtonFormField<String>>(
      find.byType(DropdownButtonFormField<String>),
    )
    .singleWhere((w) => w.decoration.labelText == '店舗');

Future<void> openForecast(WidgetTester tester) async {
  await tester.binding.setSurfaceSize(const Size(393, 1200));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(),
      home: ViewerHome(initialData: ViewerData(records: records)),
    ),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text('新規予測（試験中の別の選び方）'));
  await tester.pumpAndSettle();
  expect(find.byType(ExploratoryForecastPage), findsOneWidget);
}

void main() {
  testWidgets('新規予測で別店舗の日付を選んで戻ったら同じ店舗と日付を表示する', (tester) async {
    await openForecast(tester);
    storeSelector(tester).onChanged!('saiwaichou');
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-27',
    );
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(storeSelector(tester).initialValue, 'saiwaichou');
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-27',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('新規予測の候補詳細で変えた日付を戻った新規予測画面にも反映する', (tester) async {
    await openForecast(tester);
    final card = tester.widget<ExploratoryCandidatesCard>(
      find.byType(ExploratoryCandidatesCard),
    );
    expect(card.candidates, isNotEmpty);
    card.onPick(card.candidates.first.record);
    await tester.pumpAndSettle();
    expect(find.byType(ViewerRecordPage), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-27',
    );
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-27',
    );
    expect(tester.takeException(), isNull);
  });
}
