import 'package:database_android/data_checks.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/record_analysis.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

class ReviewController extends AppController {
  final _views = <(int, String, String), Future<DayView>>{};

  // 計算内容は本番のまま、画面テストではIsolateの待ち時間を除く。
  @override
  Future<DayView> dayView(String store, String day) => _views.putIfAbsent((
    revision,
    store,
    day,
  ), () => SynchronousFuture(calculateDay((records, store, day))));

  // 画面の選択だけを試すため端末の設定ファイルには書かない。
  @override
  Future<void> rememberSelection(
    String? store,
    String? day,
    String? machine,
  ) async {}

  void replaceRecords(List<SlotRecord> rows) {
    records = rows;
    notifyListeners();
  }
}

SlotRecord rec(
  String machine,
  int rack, {
  int games = 3000,
  String store = 'nagamachiminami',
}) => SlotRecord(
  store: store,
  day: '2026-09-28',
  machine: machine,
  rack: rack,
  games: games,
  bb: 10,
  rb: 5,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
);

Future<void> prepare(WidgetTester tester, ReviewController controller) async {
  await tester.binding.setSurfaceSize(const Size(393, 3000));
  addTearDown(() => tester.binding.setSurfaceSize(null));
  addTearDown(controller.dispose);
  await tester.runAsync(() async {
    for (final store in controller.records.map((r) => r.store).toSet()) {
      await controller.dayView(store, '2026-09-28');
    }
  });
}

Widget app(Widget child) => MaterialApp(
  theme: buildAppTheme(),
  home: Scaffold(body: child),
);

void main() {
  testWidgets('結果：スマホ幅で日付・長いイベント名がはみ出さず一覧にも表示される', (tester) async {
    final controller = ReviewController()..records = [rec('北斗', 1)];
    const event = DateEvent(
      store: 'nagamachiminami',
      day: '2026-09-28',
      name: '自由記載の長いイベント名・超探す楽しみと華の日',
    );
    controller.dateEvents[event.key] = event;
    await prepare(tester, controller);
    await tester.pumpWidget(app(ResultsPage(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.text(event.name), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('2026-09-28（月）').first);
    await tester.pumpAndSettle();
    expect(find.text(event.name), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('結果：バラエティに集約後も検索でき、店舗変更後に検索語を解除できる', (tester) async {
    final controller = ReviewController()
      ..records = [
        for (var rack = 1; rack <= 8; rack++) rec('機種$rack', rack, games: 400),
        rec('別の機種', 100, games: 400, store: 'saiwaichou'),
      ];
    await prepare(tester, controller);
    await tester.pumpWidget(app(ResultsPage(controller: controller)));
    await tester.pumpAndSettle();
    expect(find.byType(MachineSearchField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '機種8');
    await tester.pumpAndSettle();
    await tester.tap(find.text('長町南').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('幸町').last);
    await tester.pumpAndSettle();
    expect(find.byType(MachineSearchField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '');
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<MachineSection>(find.byType(MachineSection))
          .entries
          .single
          .$1
          .machine,
      '別の機種',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('結果：機種名で絞ったバラエティの★は表示中の台数だけ', (tester) async {
    final controller = ReviewController()
      ..records = [
        for (var rack = 1; rack <= 7; rack++)
          for (var offset = 0; offset < 4; offset++)
            rec('通常$rack', 100 + rack * 4 + offset, games: 400),
        rec('北斗', 30),
        rec('北斗', 31),
        rec('ハナハナ', 20),
      ];
    await prepare(tester, controller);
    await tester.pumpWidget(app(ResultsPage(controller: controller)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '北斗');
    await tester.pumpAndSettle();
    final section = tester.widget<MachineSection>(find.byType(MachineSection));
    expect(section.entries.map((e) => e.$1.rack), [30, 31]);
    expect(section.candidateRacks, {30, 31});
    expect(tester.takeException(), isNull);
  });

  testWidgets('履歴：絞り込み後のバラエティの★は表示中の台数だけ', (tester) async {
    final controller = ReviewController()
      ..records = [rec('北斗', 30), rec('北斗', 31), rec('ハナハナ', 20)];
    await prepare(tester, controller);
    await tester.pumpWidget(
      app(
        HistoryGroupPage(
          controller: controller,
          day: '2026-09-28',
          store: 'nagamachiminami',
          machine: varietyGroupName,
          only: const {'北斗'},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<MachineSection>(find.byType(MachineSection)).candidateRacks,
      {30, 31},
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('履歴：表示中の機種が3台に減っても当日の全候補と★が一致する', (tester) async {
    final controller = ReviewController()
      ..records = [for (var rack = 1; rack <= 4; rack++) rec('北斗', rack)];
    await prepare(tester, controller);
    await tester.pumpWidget(
      app(
        HistoryGroupPage(
          controller: controller,
          day: '2026-09-28',
          store: 'nagamachiminami',
          machine: '北斗',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      controller.replaceRecords([
        for (var rack = 1; rack <= 3; rack++) rec('北斗', rack),
      ]);
      await controller.dayView('nagamachiminami', '2026-09-28');
    });
    await tester.pumpAndSettle();
    expect(
      tester.widget<MachineSection>(find.byType(MachineSection)).candidateRacks,
      {1, 2, 3},
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('結果：全機種の台一覧はバラエティ以外の台を1つの表に出し、機種で絞れる', (tester) async {
    // 2026-11-01 利用者「バラエティ以外の他の機種を一覧でだしつつ、機種だけみたいときは（プルダウン）で
    // 切り替えられるように」「媒体は全て」。
    final controller = ReviewController()
      ..records = [
        for (var rack = 1; rack <= 4; rack++)
          rec('北斗', rack, games: 1000 * rack),
        for (var rack = 11; rack <= 14; rack++) rec('ジャグラー', rack),
        rec('ハナハナ', 20),
      ];
    await prepare(tester, controller);
    await tester.pumpWidget(app(ResultsPage(controller: controller)));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('open-all-machines')));
    await tester.pumpAndSettle();
    expect(find.text('全機種の台一覧'), findsOneWidget);
    List<int> racks() => [
      for (final e
          in tester
              .widget<MachineDataTable>(find.byType(MachineDataTable))
              .entries)
        e.$1.rack,
    ];
    expect(racks(), [1, 2, 3, 4, 11, 12, 13, 14], reason: 'バラエティ（ハナハナ）は入れない');
    await tester.tap(find.byKey(const ValueKey('machine-only')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('北斗').last);
    await tester.pumpAndSettle();
    expect(racks(), [1, 2, 3, 4]);
    await tester.tap(find.byKey(const ValueKey('machine-sort')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('回転数の多い順').last);
    await tester.pumpAndSettle();
    expect(racks(), [4, 3, 2, 1]);
    await tester.tap(find.byKey(const ValueKey('machine-sort')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('台番号順').last);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
