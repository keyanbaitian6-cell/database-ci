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
  test('前日まで7日：70点ちょうど、🌈なし、重複、境界、欠損、1台機種（共有と同じ例）', () {
    final rows = varietyWeekRacks(
      fixture().records,
      'saiwaichou',
      '2026-10-13',
    );
    expect(varietyWeekDays('2026-10-13'), [
      '2026-10-06',
      '2026-10-07',
      '2026-10-08',
      '2026-10-09',
      '2026-10-10',
      '2026-10-11',
      '2026-10-12',
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
      [1102, 1103, 1104, 1105],
    );
    expect(rows.map((x) => (x.records.length, x.rainbowDays)), [
      (7, 1),
      (7, 0),
      (7, 0),
      (7, 0),
      (4, 0),
      (0, 0),
    ]);
    expect(
      varietyWeekRacks(fixture().records, 'nagamachiminami', '2026-10-13'),
      isEmpty,
    );
  });
  test('日付を戻す・月年境界・一部取得の日の並び・台番号単位', () {
    final all = fixture().records;
    final rows = varietyWeekRacks(all, 'saiwaichou', '2026-10-12');
    expect(
      rows.singleWhere((x) => x.current.rack == 1104).rainbowDays,
      1,
      reason: '10/5も期間に入る',
    );
    expect(varietyWeekDays('2027-01-03').first, '2026-12-27');
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
      varietyWeekRacks(replaced, 'saiwaichou', '2026-10-13').first.rainbowDays,
      1,
      reason: '既存の🌈表と同じ台番号で見る',
    );
  });
  testWidgets('320/393pxで2一覧・対象期間・不足記録を表示、固定帯の日付で再計算', (tester) async {
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
      expect(find.text('2026-10-06〜2026-10-12'), findsOneWidget);
      expect(find.text('70点以上になった台（2台）'), findsOneWidget);
      await tester.scrollUntilVisible(find.text('🌈がない台（4台）'), 300);
      await tester.scrollUntilVisible(
        find.text('期間内の記録なし：1台（🌈の有無はわかりません）'),
        300,
      );
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
      await tester.drag(find.byType(ListView).first, const Offset(0, 3000));
      await tester.pumpAndSettle();
      expect(find.text('2026-10-05〜2026-10-11'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    }
  });
}
