import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/variety_week.dart';
import 'package:database_android/viewer_data.dart';

ViewerData fixture() => ViewerData.parse(
  File('test/fixtures/variety_week.json').readAsStringSync(),
);

void main() {
  test('選んだ日を含む7日：当日の🌈は入り、8日前の🌈は入らない、70点ちょうど、重複、欠損、1台機種（共有と同じ例）', () {
    final rows = varietyWeekRacks(
      fixture().records,
      'saiwaichou',
      '2026-10-13',
    );
    expect(varietyWeekDays('2026-10-13'), [
      '2026-10-07',
      '2026-10-08',
      '2026-10-09',
      '2026-10-10',
      '2026-10-11',
      '2026-10-12',
      '2026-10-13',
    ]);
    expect(rows.map((x) => x.current.rack), [
      1101,
      1102,
      1103,
      1104,
      1105,
      1106,
    ]);
    expect(rows.where((x) => x.high.isNotEmpty).map((x) => x.current.rack), [
      1101,
      1102,
    ]);
    expect(rows.first.high.map((h) => h.score.total), List.filled(7, 70));
    expect(
      rows
          .where((x) => x.records.isNotEmpty && x.rainbowDays == 0)
          .map((x) => x.current.rack),
      [1101, 1102, 1104, 1105, 1106],
      reason: '1101の🌈（10/6）は期間外、1103の🌈（選んだ日10/13）は期間内',
    );
    expect(rows.map((x) => (x.records.length, x.rainbowDays)), [
      (7, 0),
      (7, 0),
      (7, 1),
      (7, 0),
      (5, 0),
      (1, 0),
    ]);
    expect(
      varietyWeekRacks(fixture().records, 'nagamachiminami', '2026-10-13'),
      isEmpty,
    );
  });
  test('日付を戻す・月年境界・一部取得の日の並び・台番号単位', () {
    final all = fixture().records;
    final rows = varietyWeekRacks(all, 'saiwaichou', '2026-10-11');
    expect(
      rows.singleWhere((x) => x.current.rack == 1104).rainbowDays,
      1,
      reason: '10/11を含む7日なので10/5も期間に入る',
    );
    final before = varietyWeekRacks(all, 'saiwaichou', '2026-10-12');
    expect(
      before
          .where((x) => x.records.isNotEmpty && x.rainbowDays == 0)
          .map((x) => x.current.rack),
      [1102, 1103, 1104, 1105],
      reason: '10/12を選ぶと10/13の🌈は入らず、10/6の🌈が入る',
    );
    expect(
      before.singleWhere((x) => x.current.rack == 1106).records,
      isEmpty,
    );
    expect(varietyWeekDays('2027-01-03').first, '2026-12-28');
    expect(varietyWeekDays('2027-01-03').last, '2027-01-03');
    final changed = [
      ...all,
      all.first.copyWith(day: '2026-10-14', machine: '入れ替え後'),
    ];
    final current = varietyWeekRacks(changed, 'saiwaichou', '2026-10-13');
    expect(
      current.map((x) => x.current.rack),
      rows.map((x) => x.current.rack),
      reason: '1台だけ取得の日を並びにしない',
    );
    final replaced = all
        .map(
          (r) => r.day == '2026-10-13' && r.rack == 1101
              ? r.copyWith(machine: '入れ替え後')
              : r,
        )
        .toList();
    expect(
      varietyWeekRacks(replaced, 'saiwaichou', '2026-10-12').first.rainbowDays,
      1,
      reason: '既存の🌈表と同じ台番号で見る（10/13に入れ替え、10/6の🌈は前の機種）',
    );
  });
  testWidgets('320/393pxで候補が先頭、70点以上の台も残し、🌈ありは折りたたみ', (tester) async {
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPhysicalSize);
    for (final width in [320.0, 393.0]) {
      tester.view.physicalSize = Size(width, 852);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: VarietyWeekPage(
            data: fixture(),
            store: 'saiwaichou',
            day: '2026-10-13',
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('2026-10-07〜2026-10-13'), findsOneWidget);
      expect(find.text('候補 5台'), findsOneWidget);
      expect(find.byKey(const ValueKey('week-candidate-1102')), findsOneWidget);
      expect(find.byKey(const ValueKey('week-candidate-1101')), findsOneWidget);
      expect(find.byKey(const ValueKey('week-candidate-1103')), findsNothing);
      expect(find.text('70点以上あり'), findsWidgets);
      expect(find.text('70点以上になった台（2台）'), findsNothing);
      await tester.scrollUntilVisible(find.text('🌈が付いた台（1台）'), 300);
      await tester.ensureVisible(find.text('🌈が付いた台（1台）'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('week-marked-1103')), findsNothing);
      await tester.tap(find.text('🌈が付いた台（1台）'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('week-marked-1103')), findsOneWidget);
      expect(find.textContaining('記録がない台：'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).first, const Offset(0, 3000));
      await tester.pumpAndSettle();
      expect(find.text('2026-10-06〜2026-10-12'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('記録がない台：1台（候補に含めていません）'), 300);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    }
  });
}
