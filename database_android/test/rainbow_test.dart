// 確定が出た台の印🌈（2026-10-11。RAINBOW.md）。PCで付け、閲覧ページで台番号の横・台の推移の日付の横に出す。
// 台の画面には「最終🌈」（この台番号に最後に🌈が付いた日と何日前か）。Android版では付けない。
import 'dart:convert';

import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(
  String day, {
  int rack = 660,
  bool rainbow = false,
  String machine = 'ハナハナ',
}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
  maxHold: 1500,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
  extra: rainbow ? const {'rainbow': true} : const {},
);

List<SlotRecord> sample() => [
  rec('2026-09-26', rainbow: true),
  rec('2026-10-05', rainbow: true, machine: '別の機種'),
  rec('2026-10-08'),
  rec('2026-10-10'),
  for (final day in ['2026-10-08', '2026-10-10'])
    for (var rack = 1; rack <= 4; rack++) rec(day, rack: rack),
];

Widget app(Widget page) => MaterialApp(theme: buildAppTheme(), home: page);

void main() {
  test('the mark rides in extra: read, written back and kept on merge', () {
    final record = SlotRecord.fromJson({
      ...rec('2026-10-10').toJson(),
      'rainbow': true,
    });
    expect(record.rainbow, isTrue);
    expect(record.toJson()['rainbow'], isTrue, reason: 'Androidのバックアップでも落とさない');
    expect(mergeSameRack(record, rec('2026-10-10')).rainbow, isTrue);
    expect(rec('2026-10-10').rainbow, isFalse);
    final data = ViewerData.parse(
      jsonEncode({
        'format': 'database-viewer',
        'records': [record.toJson()],
      }),
    );
    expect(data.records.single.rainbow, isTrue, reason: '閲覧用ファイルから読む');
  });

  test('last rainbow day by rack number, and its text', () {
    final all = sample();
    expect(
      lastRainbowDay(all, 'nagamachiminami', 660, '2026-10-10'),
      '2026-10-05',
      reason: '機種が変わっても同じ台番号',
    );
    expect(
      lastRainbowDay(all, 'nagamachiminami', 660, '2026-10-01'),
      '2026-09-26',
    );
    expect(lastRainbowDay(all, 'nagamachiminami', 660, '2026-09-25'), isNull);
    expect(lastRainbowDay(all, 'saiwaichou', 660, '2026-10-10'), isNull);
    expect(lastRainbowText('2026-10-05', '2026-10-10'), '10/5（5日前）');
    expect(lastRainbowText('2026-10-10', '2026-10-10'), '当日');
    expect(lastRainbowText(null, '2026-10-10'), 'なし');
  });

  testWidgets('rack page: title mark, last rainbow line, trend dates', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final all = [...sample(), rec('2026-10-11', rainbow: true)];
    final today = all.firstWhere((r) => r.day == '2026-10-10' && r.rack == 660);
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          data: ViewerData(records: all),
          record: today,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('660番台'), findsOneWidget, reason: 'この日は付いていない');
    expect(find.text('最終🌈：10/5（5日前）'), findsOneWidget);
    final trend = find.textContaining('🌈');
    expect(trend, findsWidgets);
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          key: const ValueKey('rainbow-day'),
          data: ViewerData(records: all),
          record: all.last,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('660番台 🌈'), findsOneWidget);
    expect(find.text('最終🌈：当日'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('no rainbow in the store: the last rainbow line is not shown', (
    tester,
  ) async {
    final all = [rec('2026-10-08'), rec('2026-10-10')];
    await tester.pumpWidget(
      app(
        Scaffold(
          body: LastRainbow(record: all.last, all: all),
        ),
      ),
    );
    expect(find.byKey(const ValueKey('last-rainbow')), findsNothing);
  });
}
