import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/pscube_suffix.dart';
import 'package:database_android/pscube_suffix_page.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';

import 'pscube_viewer_test.dart' show fixture;

const store = 'pscube:c740601:20';
SlotRecord row(
  int rack,
  String day, {
  int games = 1000,
  int my = 1000,
  String scope = store,
  bool normal = true,
  GraphMeasurement? graph,
}) => SlotRecord(
  store: scope,
  day: day,
  rack: rack,
  machine: normal ? 'ノーマル' : 'AT機',
  games: games,
  bb: 4,
  rb: 1,
  graph: graph,
  extra: {
    'source': 'pscube',
    'my': my,
    'rate': scope.split(':').last,
    'machine_type': normal ? 'normal' : 'other',
    'at_art': normal ? 0 : 3,
  },
);
void main() {
  test('event names: old suffix marks read as 末尾イベ, free names, per day and rate, pull-down order', () {
    final raw = fixture();
    raw['suffix_events'] = [
      {
        'store': 'c740601',
        'rate': '20',
        'day': '2026-10-01',
        'enabled': true,
        'updated_at': '2026-10-02T00:00:00Z',
      },
      {
        'store': 'c740601',
        'rate': '20',
        'day': '2026-09-30',
        'enabled': false,
        'updated_at': '2026-10-02T00:00:00Z',
      },
      {
        'store': 'c740601',
        'rate': '5',
        'day': '2026-09-30',
        'enabled': true,
        'updated_at': '2026-10-02T00:00:00Z',
      },
    ];
    raw['date_events'] = [
      // 同じ日の古い印より新しいイベント名が勝つ。
      {
        'store': 'c740601',
        'rate': '20',
        'day': '2026-09-30',
        'name': ' 周年 ',
        'updated_at': '2026-10-03T00:00:00Z',
      },
      {
        'store': 'c740601',
        'rate': '20',
        'day': '2026-09-29',
        'name': null,
        'updated_at': '2026-10-04T00:00:00Z',
      },
    ];
    final data = ViewerData.parse(jsonEncode(raw));
    expect(data.dateEventFor(store, '2026-10-01')?.name, '末尾イベ');
    expect(data.dateEventFor(store, '2026-09-30')?.name, '周年');
    expect(data.dateEventFor(store, '2026-09-29'), isNull);
    expect(data.dateEventFor('pscube:c740601:5', '2026-09-30')?.name, '末尾イベ');
    expect(data.eventNames[store], ['周年', '末尾イベ'], reason: '新しく使った順');
    expect(data.records.length, 56);
    for (final bad in [
      {'day': '2026-02-30'},
      {'name': 'x' * 61},
      {'name': 'a\nb'},
      {'updated_at': 'bad'},
    ]) {
      final broken = fixture();
      broken['date_events'] = [
        {
          'store': 'c740601',
          'rate': '20',
          'day': '2026-10-01',
          'name': '周年',
          'updated_at': '2026-10-02T00:00:00Z',
          ...bad,
        },
      ];
      expect(
        () => ViewerData.parse(jsonEncode(broken)),
        throwsFormatException,
        reason: '$bad',
      );
    }
  });
  testWidgets(
    'free event names update the date bar and history; pull-down reuse, removal and save failure',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final raw = fixture();
      ViewerData? updated;
      var fail = false;
      var clock = 0;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: PscubeSuffixPage(
            data: ViewerData.parse(jsonEncode(raw)),
            store: store,
            day: '2026-10-01',
            onDataChanged: (data) => updated = data,
            saveDateEvent: (scope, day, name) async {
              expect(scope, store);
              if (fail) throw StateError('保存失敗');
              final events = [
                for (final e in (raw['date_events'] as List? ?? const []))
                  if ((e as Map)['day'] != day) e,
                {
                  'store': 'c740601',
                  'rate': '20',
                  'day': day,
                  'name': name,
                  'updated_at': '2026-10-02T00:00:0${clock++}Z',
                },
              ];
              raw['date_events'] = events;
              return jsonEncode(raw);
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('イベント：なし'), findsOneWidget);
      await tester.tap(find.text('イベント：なし'));
      await tester.pumpAndSettle();
      expect(find.text('今までのイベントから選ぶ'), findsNothing, reason: 'まだ名前が無い');
      await tester.enterText(find.byType(TextField), '末尾イベ');
      await tester.pump(); // 入力で保存ボタンが押せるようになる
      await tester.tap(find.widgetWithText(FilledButton, '保存'));
      await tester.pumpAndSettle();
      expect(find.text('イベント：末尾イベ'), findsOneWidget);
      expect(
        tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).event,
        '末尾イベ',
      );
      expect(updated?.dateEventFor(store, '2026-10-01')?.name, '末尾イベ');
      await tester.scrollUntilVisible(
        find.widgetWithText(ListTile, '2026-10-01（木）'),
        400,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.widgetWithText(Chip, '末尾イベ'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, '2026-10-01（木）'));
      await tester.pumpAndSettle();
      // 一度付けた名前はプルダウンに出る。「イベントなしにする」で外す。
      await tester.tap(find.text('イベント：末尾イベ'));
      await tester.pumpAndSettle();
      expect(find.text('今までのイベントから選ぶ'), findsOneWidget);
      await tester.tap(find.text('イベントなしにする'));
      await tester.pumpAndSettle();
      expect(find.text('イベント：なし'), findsOneWidget);
      expect(
        tester.widget<ViewerDateBar>(find.byType(ViewerDateBar)).event,
        isNull,
      );
      fail = true;
      await tester.tap(find.text('イベント：なし'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '周年');
      await tester.pump(); // 入力で保存ボタンが押せるようになる
      await tester.tap(find.widgetWithText(FilledButton, '保存'));
      await tester.pumpAndSettle();
      expect(find.text('イベント：なし'), findsOneWidget);
      expect(find.textContaining('イベント名を保存できませんでした'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  test('ranking respects displayed ties, null scores, and changes by day', () {
    PscubeSuffixSummary summary(int digit, String day, double? total) =>
        PscubeSuffixSummary(digit, [
          (
            row(10 + digit, day),
            ScoreResult(
              total: total,
              provisional: true,
              referenceCount: 1,
              reasons: [],
            ),
          ),
        ]);
    final report = PscubeSuffixReport(
      summaries: [
        PscubeSuffixSummary(0, []),
        summary(1, '2026-10-02', 72.01),
        summary(2, '2026-10-02', 72.04),
        summary(3, '2026-10-02', 69),
        summary(5, '2026-10-02', null),
        summary(6, '2026-10-01', 92),
        summary(7, '2026-10-01', 30),
      ],
      excludedInvalid: 0,
      excludedSuffix: 0,
      start: '2026-10-01',
      end: '2026-10-02',
    );
    final boundary = PscubeSuffixReport(
      summaries: [
        summary(1, '2026-10-02', 1.15),
        summary(2, '2026-10-02', 1.14),
      ],
      excludedInvalid: 0,
      excludedSuffix: 0,
      start: '2026-10-02',
      end: '2026-10-02',
    );
    expect(1.15.toStringAsFixed(1), '1.1');
    expect(boundary.leaders.length, 2);
    final days = report.daily;
    expect(days.map((d) => d.end), ['2026-10-02', '2026-10-01']);
    expect(days.first.leaders.map((s) => s.suffix), [1, 2]);
    expect(days.first.ranked.map((s) => days.first.rankOf(s)), [1, 1, 3]);
    expect(days.last.leaders.single.suffix, 6);
    expect(
      days.first.ranked.any((s) => s.suffix == 0 || s.suffix == 5),
      isFalse,
    );
    final unscored = summarizePscubeSuffixes(
      [row(11, '2026-10-02', games: 500)],
      store: store,
      day: '2026-10-02',
    );
    expect(unscored.leaders, isEmpty);
    expect(unscored.daily.single.records, 1);
  });
  testWidgets(
    'historical day tap updates the headline; no-score days have no winner',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final raw = fixture();
      for (final r in raw['records'] as List) {
        if (r['day'] == '2026-10-01') r['games'] = 500;
      }
      final data = ViewerData.parse(jsonEncode(raw));
      String? changed;
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: PscubeSuffixPage(
            data: data,
            store: store,
            day: '2026-10-01',
            onDayChanged: (day) => changed = day,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('採点なし（500G以下など）'), findsOneWidget);
      expect(find.textContaining('平均点の首位：'), findsNothing);
      final history = find.widgetWithText(ListTile, '2026-09-30（水）');
      // Select the historical row by its unique date label.
      await tester.ensureVisible(history);
      await tester.tap(history);
      await tester.pumpAndSettle();
      expect(changed, '2026-09-30');
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('suffix-day-ranking')),
          matching: find.textContaining('平均点の首位：'),
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  test(
    'eight explicit suffixes, empty groups and physical racks across days',
    () {
      final report = summarizePscubeSuffixes(
        [
          row(10, '2026-10-01'),
          row(10, '2026-10-02', games: 500, my: 500),
          row(20, '2026-10-02', games: 0, my: 0),
          row(14, '2026-10-02'),
          row(19, '2026-10-02'),
        ],
        store: store,
        day: '2026-10-02',
        period: PscubeSuffixPeriod.week,
      );
      expect(report.summaries.map((s) => s.suffix), [
        0,
        1,
        2,
        3,
        5,
        6,
        7,
        8,
        pscubeZorome,
      ]);
      expect(report.summaries.last.label, 'ゾロ目');
      expect(report.summaries.last.records, 0, reason: '10・20番台はゾロ目ではない');
      final zero = report.summaries.first;
      expect(zero.records, 3);
      expect(zero.racks, 2);
      expect(zero.days, 2);
      expect(zero.averageGames, 500);
      expect(zero.averageMy, 500);
      expect(zero.scored, 1);
      expect(zero.averageScore, 50);
      expect(report.excludedSuffix, 2);
      expect(report.summaries[1].averageMy, isNull);
      expect(report.summaries[1].averageScore, isNull);
      expect(zero.positivePercent, isNull);
    },
  );
  test('zorome: last two digits 00/11/22/33/55/66/77/88, also counted in its suffix, not double-counted in totals', () {
    // 2026-10-11 利用者「ゾロ目っていう項目も追加してほしい。00 11 22 33 55 66 77 88」。
    for (final rack in [100, 111, 1122, 33, 1155, 266, 1077, 1188]) {
      expect(isPscubeZorome(rack), isTrue, reason: '$rack');
    }
    for (final rack in [0, 5, 10, 101, 1112, 1144, 1199, 1121, 1000 + 12]) {
      expect(isPscubeZorome(rack), isFalse, reason: '$rack');
    }
    final report = summarizePscubeSuffixes(
      [
        row(1111, '2026-10-01', games: 3000, my: 3000),
        row(1100, '2026-10-01', games: 3000, my: 3000),
        row(1101, '2026-10-01'),
        row(1144, '2026-10-01'),
      ],
      store: store,
      day: '2026-10-01',
    );
    final zorome = report.summaries.singleWhere((s) => s.isZorome);
    expect(zorome.entries.map((e) => e.$1.rack), [1100, 1111]);
    expect(zorome.label, 'ゾロ目');
    expect(zorome.shortLabel, 'ゾロ目');
    expect(zorome.averageMy, 3000);
    // ゾロ目の台は末尾の集計にも入る（1111番台は末尾1、1100番台は末尾0）。
    expect(report.summaries[1].entries.map((e) => e.$1.rack), [1101, 1111]);
    expect(report.summaries[0].entries.map((e) => e.$1.rack), [1100]);
    // 合計は二重に数えない。44は指定外の末尾。
    expect(report.records, 3);
    expect(report.racks, 3);
    expect(report.excludedSuffix, 1);
    expect(report.ranked.map((s) => s.label), contains('ゾロ目'));
    expect(report.daily.single.summaries.last.isZorome, isTrue);
    expect(report.daily.single.records, 3);
  });
  test('calendar windows exclude future days, other stores/rates and invalid numbers', () {
    final all = [
      row(11, '2026-09-24'),
      row(11, '2026-09-25'),
      row(11, '2026-10-01'),
      row(11, '2026-10-02'),
      row(21, '2026-10-01', scope: 'pscube:c740601:5'),
      row(31, '2026-10-01', scope: 'pscube:c999999:20'),
      row(41, '2026-10-01', games: 88888888),
    ];
    final week = summarizePscubeSuffixes(
      all,
      store: store,
      day: '2026-10-01',
      period: PscubeSuffixPeriod.week,
    );
    expect(week.start, '2026-09-25');
    expect(week.records, 2);
    expect(week.excludedInvalid, 1);
    expect(week.racks, 1);
    expect(week.days, 2);
    final saved = summarizePscubeSuffixes(
      all,
      store: store,
      day: '2026-10-01',
      period: PscubeSuffixPeriod.saved,
    );
    expect(saved.records, 3);
    final day = summarizePscubeSuffixes(all, store: store, day: '2026-10-01');
    expect(day.records, 1);
    final month = summarizePscubeSuffixes(
      [row(10, '2026-09-01'), row(10, '2026-09-02')],
      store: store,
      day: '2026-10-01',
      period: PscubeSuffixPeriod.month,
    );
    expect(month.start, '2026-09-02');
    expect(month.records, 1);
  });
  test('type filter, MY averages and positive graph denominators', () {
    GraphMeasurement graph(double end) =>
        GraphMeasurement(baselineY: 100, peakY: 80, troughY: 110, endY: end);
    final all = [
      row(10, '2026-10-01', graph: graph(95)),
      row(20, '2026-10-01', graph: graph(105)),
      row(30, '2026-10-01', graph: graph(99)),
      row(40, '2026-10-01'),
      row(50, '2026-10-01', normal: false, my: 8000),
    ];
    final normal = summarizePscubeSuffixes(
      all,
      store: store,
      day: '2026-10-01',
      type: PscubeSuffixType.normal,
    ).summaries.first;
    expect(normal.records, 4);
    expect(normal.graphs, 3);
    expect(normal.positiveGraphs, 1);
    expect(normal.positivePercent, closeTo(100 / 3, 1e-9));
    expect(normal.averageMy, 1000);
    final other = summarizePscubeSuffixes(
      all,
      store: store,
      day: '2026-10-01',
      type: PscubeSuffixType.other,
    ).summaries.first;
    expect(other.records, 1);
    expect(other.atArt, 3);
    expect(other.averageMy, 8000);
    expect(other.entries.single.$1.maxHold, isNull);
  });
  testWidgets(
    'shared controls, eight rows, details and graph tabs on iPhone width',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final data = ViewerData.parse(jsonEncode(fixture()));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: ViewerHome(initialData: data),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('末尾別データまとめ'), findsOneWidget);
      await tester.tap(find.text('末尾別データまとめ'));
      await tester.pumpAndSettle();
      expect(find.byType(PscubeSuffixPage), findsOneWidget);
      expect(find.byType(ViewerDateBar), findsOneWidget);
      final ranking = find.byKey(const ValueKey('suffix-day-ranking'));
      expect(ranking, findsOneWidget);
      final expected = summarizePscubeSuffixes(
        data.records,
        store: store,
        day: '2026-10-01',
      );
      expect(
        find.descendant(
          of: ranking,
          matching: find.textContaining(
            '平均点の首位：末尾${expected.leaders.first.suffix}',
          ),
        ),
        findsOneWidget,
      );
      // The winner and its evidence are visible before any horizontal scroll.
      expect(
        tester
            .getRect(
              find.descendant(
                of: ranking,
                matching: find.textContaining('平均点の首位：'),
              ),
            )
            .bottom,
        lessThan(852),
      );
      expect(find.byType(DataTable), findsNothing);
      await tester.scrollUntilVisible(
        find.text('数値一覧・末尾別の内訳'),
        500,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text('数値一覧・末尾別の内訳'));
      await tester.pumpAndSettle();
      expect(find.byType(DataTable), findsOneWidget);
      for (final digit in pscubeSuffixes) {
        expect(
          find.descendant(
            of: find.byType(DataTable),
            matching: find.text('末尾$digit'),
          ),
          findsOneWidget,
        );
      }
      expect(
        find.descendant(of: find.byType(DataTable), matching: find.text('ゾロ目')),
        findsOneWidget,
      );
      expect(find.text('末尾4'), findsNothing);
      expect(find.text('末尾9'), findsNothing);
      await tester.ensureVisible(
        find.descendant(of: find.byType(DataTable), matching: find.text('末尾1')),
      );
      await tester.tap(
        find.descendant(of: find.byType(DataTable), matching: find.text('末尾1')),
      );
      await tester.pumpAndSettle();
      expect(find.text('末尾1の内訳'), findsOneWidget);
      expect(find.byType(MachineDataTable), findsOneWidget);
      expect(
        tester
            .widget<MachineDataTable>(find.byType(MachineDataTable))
            .showMachine,
        isTrue,
      );
      await tester.tap(find.text('グラフ表示'));
      await tester.pumpAndSettle();
      expect(find.byType(GraphGrid), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('period and date changes preserve distinct rack counts', (
    tester,
  ) async {
    final data = ViewerData.parse(jsonEncode(fixture()));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: PscubeSuffixPage(data: data, store: store, day: '2026-10-01'),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.textContaining('7件（台×日）'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('7件（台×日）'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byType(DropdownButtonFormField<PscubeSuffixPeriod>),
      -400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.byType(DropdownButtonFormField<PscubeSuffixPeriod>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('過去7日').last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.textContaining('7台・49件（台×日）'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('7台・49件（台×日）'), findsOneWidget);
    expect(find.byKey(const ValueKey('suffix-period-ranking')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('suffix-day-ranking')),
      -500,
      scrollable: find.byType(Scrollable).first,
    );
    // Period selection must not relabel the selected day as a period winner.
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('suffix-day-ranking')),
        matching: find.textContaining('の末尾順位'),
      ),
      findsOneWidget,
    );
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.textContaining('7台・42件（台×日）'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('7台・42件（台×日）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  // 幸町（メルヘン）の末尾別データまとめ（2026-10-12 利用者「幸町にもつくってもらうだけでいい」）。
  SlotRecord meruhen(
    int rack,
    String day, {
    String scope = 'saiwaichou',
    int? net,
  }) => SlotRecord(
    store: scope,
    day: day,
    rack: rack,
    machine: 'L北斗',
    games: 3000,
    bb: 10,
    rb: 5,
    extra: {if (net != null) 'jo_net': net},
  );

  test('幸町：末尾0〜9とゾロ目、平均差枚、長町南・P’s CUBEは混ぜない', () {
    expect(hasSuffixPage('saiwaichou'), isTrue);
    expect(hasSuffixPage('nagamachiminami'), isFalse);
    expect(hasSuffixPage(store), isTrue);
    expect(suffixesFor('saiwaichou'), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    final report = summarizePscubeSuffixes(
      [
        meruhen(1004, '2026-10-10', net: 500),
        meruhen(1014, '2026-10-10', net: -100),
        meruhen(1029, '2026-10-10'),
        meruhen(1011, '2026-10-10', net: 200),
        meruhen(1004, '2026-10-10', scope: 'nagamachiminami', net: 9999),
        row(1004, '2026-10-10'),
      ],
      store: 'saiwaichou',
      day: '2026-10-10',
    );
    final byLabel = {for (final s in report.summaries) s.label: s};
    expect(byLabel.keys, [
      for (final d in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) '末尾$d',
      'ゾロ目',
    ]);
    expect(byLabel['末尾4']!.records, 2);
    expect(byLabel['末尾4']!.averageNet, 200);
    expect(byLabel['末尾9']!.records, 1);
    expect(byLabel['末尾9']!.averageNet, isNull, reason: '差枚の分からない台は平均に入れない');
    expect(byLabel['ゾロ目']!.records, 1, reason: '1011番台（下2桁11）');
    expect(isZoromeAt('saiwaichou', 1044), isTrue, reason: 'メルヘンは44・99もゾロ目');
    expect(isZoromeAt(store, 1044), isFalse, reason: 'P’s CUBEは利用者の指定どおり');
    expect(report.records, 4);
  });

  testWidgets('幸町の末尾別データまとめ：平均差枚を出し、機種タイプ・イベントの編集は出さない', (tester) async {
    final data = ViewerData(
      records: [
        for (var rack = 1000; rack < 1020; rack++)
          meruhen(rack, '2026-10-10', net: rack.isEven ? 300 : -300),
      ],
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: PscubeSuffixPage(
          data: data,
          store: 'saiwaichou',
          day: '2026-10-10',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.byType(DropdownButtonFormField<PscubeSuffixType>),
      findsNothing,
    );
    expect(find.textContaining('自由記入'), findsNothing);
    expect(find.textContaining('平均差枚'), findsWidgets);
    expect(find.textContaining('平均MY'), findsNothing);
    await tester.scrollUntilVisible(
      find.textContaining('末尾0・1・2・3・4・5・6・7・8・9を集計'),
      500,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.textContaining('20台・20件（台×日）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
