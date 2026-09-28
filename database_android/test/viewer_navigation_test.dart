import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/answer_check.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';

SlotRecord rec(
  String day, {
  String machine = 'テスト',
  int rack = 1,
  String store = 'nagamachiminami',
  int games = 3000,
}) => SlotRecord(
  store: store,
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: 15,
  rb: 5,
  maxHold: 1500,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
);

Widget app(Widget page) => MaterialApp(theme: buildAppTheme(), home: page);

Future<void> phone(WidgetTester tester) async {
  await tester.binding.setSurfaceSize(const Size(393, 852));
  addTearDown(() => tester.binding.setSurfaceSize(null));
}

void main() {
  testWidgets('記録がある日にだけ移動し、両端の矢印は無効', (tester) async {
    await phone(tester);
    var day = '2026-09-28';
    await tester.pumpWidget(
      app(
        StatefulBuilder(
          builder: (context, setState) => Scaffold(
            appBar: AppBar(
              bottom: ViewerDateBar(
                days: const ['2026-09-28', '2026-09-25'],
                day: day,
                onChanged: (v) => setState(() => day = v!),
              ),
            ),
          ),
        ),
      ),
    );
    expect(
      tester
          .widget<IconButton>(
            find.byWidgetPredicate(
              (w) => w is IconButton && w.tooltip == '次の記録日',
            ),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(day, '2026-09-25');
    expect(
      tester
          .widget<IconButton>(
            find.byWidgetPredicate(
              (w) => w is IconButton && w.tooltip == '前の記録日',
            ),
          )
          .onPressed,
      isNull,
    );
    await tester.tap(find.byTooltip('次の記録日'));
    await tester.pumpAndSettle();
    expect(day, '2026-09-28');
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('2026-09-25').last);
    await tester.pumpAndSettle();
    expect(day, '2026-09-25');
    expect(tester.takeException(), isNull);
  });

  testWidgets('機種のグラフ表示を保ち、記録なしの日を挟んでも日付を切り替えられる', (tester) async {
    await phone(tester);
    final records = [
      rec('2026-09-28'),
      rec('2026-09-27', machine: '別機種'),
      rec('2026-09-25'),
    ];
    const event = DateEvent(
      store: 'nagamachiminami',
      day: '2026-09-25',
      name: '華の日',
    );
    final data = ViewerData(records: records, dateEvents: {event.key: event});
    final changed = <String>[];
    await tester.pumpWidget(
      app(
        ViewerMachinePage(
          data: data,
          store: 'nagamachiminami',
          machine: 'テスト',
          day: '2026-09-28',
          onDayChanged: changed.add,
        ),
      ),
    );
    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    expect(find.byType(GraphGrid), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.text('この日の記録はありません'), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.byType(GraphGrid), findsOneWidget);
    expect(
      tester.widget<GraphGrid>(find.byType(GraphGrid)).entries.single.$1.day,
      '2026-09-25',
    );
    expect(find.text('華の日'), findsOneWidget);
    expect(changed, ['2026-09-27', '2026-09-25']);
    expect(tester.takeException(), isNull);
  });

  testWidgets('台の詳細は同じ店舗・機種・台番号だけを切り替え、点数も更新', (tester) async {
    await phone(tester);
    final latest = rec('2026-09-28');
    final data = ViewerData(
      records: [
        latest,
        rec('2026-09-27', machine: '別機種'),
        rec('2026-09-27', store: 'saiwaichou'),
        rec('2026-09-25', games: 400),
      ],
    );
    await tester.pumpWidget(app(ViewerRecordPage(data: data, record: latest)));
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.text('この日の記録はありません'), findsOneWidget);
    expect(find.byType(SavedGraphPage), findsNothing);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    final page = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
    expect(page.record.day, '2026-09-25');
    expect(page.record.games, 400);
    expect(page.score!.total, isNull);
    // データ欄を下へスクロールしても上部の日付操作は残る。
    await tester.drag(find.byType(ListView).first, const Offset(0, -450));
    await tester.pumpAndSettle();
    expect(find.byTooltip('次の記録日').hitTestable(), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('答え合わせは全日表示を残し、選んだ日のカードだけに絞れる', (tester) async {
    await phone(tester);
    final records = [
      for (var d = 23; d <= 28; d++)
        for (var rack = 1; rack <= 4; rack++) rec('2026-09-$d', rack: rack),
    ];
    await tester.pumpWidget(
      app(
        AnswerCheckPage(
          records: records,
          store: 'nagamachiminami',
          onOpen: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    final bar = tester.widget<ViewerDateBar>(find.byType(ViewerDateBar));
    expect(bar.allowAll, isTrue);
    expect(bar.day, isNull);
    bar.onChanged('2026-09-25');
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-25',
    );
    expect(find.textContaining('2026-09-28（月）'), findsNothing);
    await tester.tap(find.byTooltip('次の記録日'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).day,
      '2026-09-26',
    );
    expect(tester.takeException(), isNull);
  });
}
