import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/answer_check.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
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
  testWidgets('日付一覧の各日にイベント名を添え、選んだ欄は日付だけ', (tester) async {
    await phone(tester);
    const events = {'2026-09-25': '超探す楽しみ'};
    await tester.pumpWidget(
      app(
        Scaffold(
          appBar: AppBar(
            bottom: ViewerDateBar(
              days: const ['2026-09-28', '2026-09-25'],
              day: '2026-09-28',
              eventFor: (day) => events[day],
              onChanged: (_) {},
            ),
          ),
        ),
      ),
    );
    // 選んだ日（9/28）にはイベントが無いので、閉じているときは出ない。
    expect(find.text('超探す楽しみ'), findsNothing);
    await tester.tap(find.text('2026-09-28（月）'));
    await tester.pumpAndSettle();
    // 一覧を開くと、イベントがある日（9/25）の下に出る。
    expect(find.text('2026-09-25（金）'), findsOneWidget);
    expect(find.text('超探す楽しみ'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

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

  testWidgets('バラエティ：1〜3台の機種の台を機種名つきで並べ、機種名で絞り込める', (tester) async {
    await phone(tester);
    final records = [
      rec('2026-09-28', machine: 'ハナハナ', rack: 5),
      rec('2026-09-28', machine: '北斗', rack: 8),
      rec('2026-09-28', machine: '北斗', rack: 7),
      for (var rack = 20; rack < 24; rack++) rec('2026-09-28', rack: rack),
    ];
    final data = ViewerData(records: records);
    Future<void> open(String query) => tester.pumpWidget(
      app(
        ViewerMachinePage(
          key: ValueKey(query),
          data: data,
          store: 'nagamachiminami',
          machine: varietyGroupName,
          day: '2026-09-28',
          query: query,
        ),
      ),
    );
    await open('');
    await tester.pumpAndSettle();
    expect(find.text('バラエティ（2機種）'), findsOneWidget);
    expect(find.text('機種'), findsOneWidget);
    final table = tester.widget<MachineDataTable>(
      find.byType(MachineDataTable),
    );
    // 4台の機種（テスト）の台は入らない。台番号順。
    expect([for (final e in table.entries) e.$1.rack], [5, 7, 8]);
    expect(table.showMachine, isTrue);
    expect(find.text('ハナハナ'), findsOneWidget);
    expect(find.text('北斗'), findsNWidgets(2));
    // 一覧で機種名を入れて開いたときは、その機種の台だけ。
    await open('北斗');
    await tester.pumpAndSettle();
    expect(
      [
        for (final e
            in tester
                .widget<MachineDataTable>(find.byType(MachineDataTable))
                .entries)
          e.$1.rack,
      ],
      [7, 8],
    );
    expect(
      tester.widget<MachineSection>(find.byType(MachineSection)).candidateRacks,
      {7, 8},
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('バラエティ：台の並べ方（台番号順・回転数の多い順・少ない順・機種順）を切り替え、覚える', (tester) async {
    // 2026-11-01 利用者「回転数とかでもソートできるようにしておいてほしい」。
    await phone(tester);
    final records = [
      rec('2026-09-28', machine: 'ハナハナ', rack: 5, games: 1200),
      rec('2026-09-28', machine: '北斗', rack: 8, games: 6000),
      rec('2026-09-28', machine: '北斗', rack: 7, games: 1200),
      for (var rack = 20; rack < 24; rack++) rec('2026-09-28', rack: rack),
    ];
    Future<void> open() => tester.pumpWidget(
      app(
        ViewerMachinePage(
          key: UniqueKey(),
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          machine: varietyGroupName,
          day: '2026-09-28',
        ),
      ),
    );
    List<int> racks() => [
      for (final e
          in tester
              .widget<MachineDataTable>(find.byType(MachineDataTable))
              .entries)
        e.$1.rack,
    ];
    Future<void> choose(String label) async {
      await tester.tap(find.byKey(const ValueKey('variety-sort')));
      await tester.pumpAndSettle();
      await tester.tap(find.text(label).last);
      await tester.pumpAndSettle();
    }

    await open();
    await tester.pumpAndSettle();
    expect(find.text('台番号順'), findsOneWidget);
    expect(racks(), [5, 7, 8]);
    await choose('回転数の多い順');
    expect(racks(), [8, 5, 7], reason: '同じ回転数は台番号順');
    await choose('回転数の少ない順');
    expect(racks(), [5, 7, 8]);
    await choose('機種順');
    expect(racks(), [5, 7, 8], reason: 'ハナハナ→北斗');
    await choose('回転数の多い順');
    // 開き直しても覚えている。
    await open();
    await tester.pumpAndSettle();
    expect(find.text('回転数の多い順'), findsOneWidget);
    expect(racks(), [8, 5, 7]);
    expect(tester.takeException(), isNull);
  });

  test('バラエティの並べ方：回転数・機種で並べ、同じなら台番号順', () {
    final entries = [
      for (final r in [
        rec('2026-09-28', machine: 'B', rack: 3, games: 100),
        rec('2026-09-28', machine: 'A', rack: 9, games: 100),
        rec('2026-09-28', machine: 'A', rack: 1, games: 500),
      ])
        (r, scoreRecord(r, [r])),
    ];
    List<int> order(String sort) => [
      for (final e in sortVarietyEntries(entries, sort)) e.$1.rack,
    ];
    expect(order('rack'), [1, 3, 9]);
    expect(order('games-desc'), [1, 3, 9]);
    expect(order('games-asc'), [3, 9, 1]);
    expect(order('machine'), [1, 9, 3]);
  });

  testWidgets('機種ページで3台の日へ切り替えても全店バラエティと同じ★になる', (tester) async {
    await phone(tester);
    final records = [
      for (var rack = 1; rack <= 4; rack++)
        rec('2026-09-28', machine: '対象機種', rack: rack),
      for (var rack = 1; rack <= 3; rack++)
        rec('2026-09-27', machine: '対象機種', rack: rack),
      for (var rack = 10; rack < 15; rack++)
        rec('2026-09-27', machine: '別機種$rack', rack: rack, games: 6000),
    ];
    await tester.pumpWidget(
      app(
        ViewerMachinePage(
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          machine: '対象機種',
          day: '2026-09-28',
        ),
      ),
    );
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    // 同じ店舗の6000Gの5台が選ばれる。表示中の3台だけで選び直さない。
    expect(
      tester.widget<MachineSection>(find.byType(MachineSection)).candidateRacks,
      isEmpty,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('バラエティ1行にまとめても機種名で検索でき、少数機種の日でも解除できる', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 3000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final records = [
      for (var rack = 1; rack <= 8; rack++)
        rec('2026-09-28', machine: '機種$rack', rack: rack, games: 400),
      rec('2026-09-27', machine: '別の機種', games: 400),
    ];
    await tester.pumpWidget(
      app(ViewerHome(initialData: ViewerData(records: records))),
    );
    await tester.pumpAndSettle();
    expect(find.byType(MachineSearchField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '機種8');
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.byType(MachineSearchField), findsOneWidget);
    await tester.enterText(find.byType(TextField), '');
    await tester.pumpAndSettle();
    expect(find.text('バラエティ（1機種）'), findsOneWidget);
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

  for (final store in ['nagamachiminami', 'pscube:c740601:20']) {
    testWidgets('台を番号順に往復し、日付・店舗・機種を保つ（$store）', (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final selected = rec('2026-09-28', store: store, rack: 20);
      final changedDays = <String>[];
      await tester.pumpWidget(
        app(
          ViewerRecordPage(
            data: ViewerData(
              records: [
                rec('2026-09-28', store: store, rack: 30, games: 4300),
                selected,
                rec('2026-09-28', store: store, rack: 10, games: 4100),
                rec('2026-09-28', store: store, machine: '別機種', rack: 21),
                rec('2026-09-28', store: '別店舗', rack: 22),
                rec('2026-09-27', store: store, rack: 10, games: 400),
                rec('2026-09-27', store: store, rack: 30, games: 4400),
              ],
            ),
            record: selected,
            onDayChanged: changedDays.add,
          ),
        ),
      );
      await tester.tap(find.text('次の台'));
      await tester.pumpAndSettle();
      var page = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
      expect(page.record.rack, 30);
      expect(page.record.games, 4300);
      expect(page.record.day, '2026-09-28');
      expect(page.record.store, store);
      expect(page.record.machine, selected.machine);
      expect(
        tester
            .widget<TextButton>(find.byKey(const ValueKey('viewer-next-rack')))
            .onPressed,
        isNull,
      );
      await tester.tap(find.text('前の台'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('前の台'));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextButton>(
              find.byKey(const ValueKey('viewer-previous-rack')),
            )
            .onPressed,
        isNull,
      );
      expect(changedDays, isEmpty, reason: '台移動では親の日付を変更しない');
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      page = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
      expect(page.record.rack, 10);
      expect(page.record.day, '2026-09-27');
      expect(page.record.games, 400);
      expect(page.score!.total, isNull);
      await tester.tap(find.text('次の台'));
      await tester.pumpAndSettle();
      page = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
      expect(page.record.rack, 30);
      expect(page.record.day, '2026-09-27');
      expect(page.record.games, 4400);
      expect(changedDays, ['2026-09-27']);
      expect(
        Navigator.of(tester.element(find.byType(SavedGraphPage))).canPop(),
        isFalse,
        reason: '台移動で戻る履歴を積み増さない',
      );
      await tester.drag(find.byType(ListView).first, const Offset(0, -450));
      await tester.pumpAndSettle();
      expect(find.text('前の台').hitTestable(), findsOneWidget);
      expect(tester.takeException(), isNull, reason: '320pxでも操作欄がはみ出さない');
    });
  }

  testWidgets('欠測日でも同じ機種の前後の台へ移れ、0台なら両方無効', (tester) async {
    await phone(tester);
    final selected = rec('2026-09-28', rack: 20);
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          data: ViewerData(
            records: [
              selected,
              rec('2026-09-27', rack: 10),
              rec('2026-09-27', rack: 30),
              rec('2026-09-26', machine: '別機種', rack: 20),
            ],
          ),
          record: selected,
        ),
      ),
    );
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.text('この日の記録はありません'), findsOneWidget);
    await tester.tap(find.text('次の台'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.rack,
      30,
    );
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    for (final key in ['viewer-previous-rack', 'viewer-next-rack']) {
      expect(
        tester.widget<TextButton>(find.byKey(ValueKey(key))).onPressed,
        isNull,
      );
    }
    expect(tester.takeException(), isNull);
  });

  testWidgets('1台だけの機種では台移動を無効にし、日付移動は残す', (tester) async {
    await phone(tester);
    final selected = rec('2026-09-28');
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          data: ViewerData(records: [selected, rec('2026-09-27')]),
          record: selected,
        ),
      ),
    );
    for (final key in ['viewer-previous-rack', 'viewer-next-rack']) {
      expect(
        tester.widget<TextButton>(find.byKey(ValueKey(key))).onPressed,
        isNull,
      );
    }
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<SavedGraphPage>(find.byType(SavedGraphPage)).record.day,
      '2026-09-27',
    );
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
