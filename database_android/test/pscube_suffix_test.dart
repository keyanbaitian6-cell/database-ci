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
      expect(report.summaries.map((s) => s.suffix), [0, 1, 2, 3, 5, 6, 7, 8]);
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
      expect(find.byType(DataTable), findsOneWidget);
      for (final digit in pscubeSuffixes) {
        expect(find.text('末尾$digit'), findsOneWidget);
      }
      expect(find.text('末尾4'), findsNothing);
      expect(find.text('末尾9'), findsNothing);
      await tester.ensureVisible(find.text('末尾1'));
      await tester.tap(find.text('末尾1'));
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
    expect(find.textContaining('7件（台×日）'), findsOneWidget);
    await tester.tap(find.byType(DropdownButtonFormField<PscubeSuffixPeriod>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('過去7日').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('7台・49件（台×日）'), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.textContaining('7台・42件（台×日）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
