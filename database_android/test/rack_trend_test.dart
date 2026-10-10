import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_pages.dart';

// 「この台の推移」（利用者指定 2026-10-11）：列は 日付・採点・総回転数・差枚・確率、日付を押すと
// その日の記録へ移る。採点の表示に「暫定」は使わない。

SlotRecord rec(String day, {int rack = 7, int games = 3000, int? net}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: day,
      machine: 'ハナハナ',
      rack: rack,
      games: games,
      bb: 10,
      rb: 5,
      maxHold: 1500,
      graph: const GraphMeasurement(
        baselineY: 200,
        peakY: 100,
        troughY: 250,
        endY: 180,
      ),
      extra: net == null ? const {} : {'jo_net': net},
    );

/// 3日分（9/26〜28）。どの日も記録が少ないので、採点は少数データ扱い（以前は「暫定」と出た）。
List<SlotRecord> sample() => [
  for (final (day, games, net) in [
    ('2026-09-26', 1234, -560),
    ('2026-09-27', 4321, 1890),
    ('2026-09-28', 8765, null),
  ]) ...[
    rec(day, games: games, net: net),
    for (var rack = 1; rack <= 4; rack++) rec(day, rack: rack),
  ],
];

Widget app(Widget page) => MaterialApp(theme: buildAppTheme(), home: page);

void main() {
  for (final width in [320.0, 393.0]) {
    testWidgets('列は日付・採点・総回転数・差枚・確率で、日付を押すとその日へ（${width.toInt()}px）', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(Size(width, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final all = sample();
      final opened = <String>[];
      await tester.pumpWidget(
        app(
          Scaffold(
            body: SingleChildScrollView(
              child: RackTrend(
                record: all.firstWhere(
                  (r) => r.day == '2026-09-28' && r.rack == 7,
                ),
                all: all,
                onOpenDay: opened.add,
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      for (final label in ['日付', '採点', '総回転数', '差枚', '確率']) {
        expect(find.text(label), findsOneWidget);
      }
      expect(find.text('9/27（日）'), findsOneWidget);
      expect(find.text('4,321G'), findsOneWidget);
      expect(find.text('+1,890'), findsOneWidget);
      expect(find.text('-560'), findsOneWidget);
      expect(find.text('1/288.1'), findsOneWidget);
      expect(find.textContaining('暫定'), findsNothing);
      // 表示中の日（9/28）は押せない。前の日は押すとその日へ。
      expect(find.byKey(const ValueKey('rack-trend-2026-09-28')), findsNothing);
      await tester.tap(find.text('9/26（土）'));
      expect(opened, ['2026-09-26']);
      expect(tester.takeException(), isNull, reason: '狭い画面でもはみ出さない');
    });
  }

  testWidgets('閲覧ページの台の画面：推移の日付を押すと、その日の記録に切り替わる', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final all = sample();
    final changed = <String>[];
    await tester.pumpWidget(
      app(
        ViewerRecordPage(
          data: ViewerData(records: all),
          record: all.firstWhere((r) => r.day == '2026-09-28' && r.rack == 7),
          onDayChanged: changed.add,
        ),
      ),
    );
    await tester.pumpAndSettle();
    final date = find.byKey(const ValueKey('rack-trend-2026-09-27'));
    // 表は画面の下（グラフの後ろ）にあり、見えるまで描かれない。見つかるまで下へ送る。
    for (var i = 0; i < 20 && date.evaluate().isEmpty; i++) {
      await tester.drag(find.byType(ListView).first, const Offset(0, -300));
      await tester.pumpAndSettle();
    }
    // 右下の「一番上へ」ボタンに重ならない高さまで、もう少し送る。
    await tester.drag(find.byType(ListView).first, const Offset(0, -200));
    await tester.pumpAndSettle();
    await tester.tap(date);
    await tester.pumpAndSettle();
    final page = tester.widget<SavedGraphPage>(find.byType(SavedGraphPage));
    expect(
      (page.record.day, page.record.rack, page.record.games),
      ('2026-09-27', 7, 4321),
    );
    expect(changed, ['2026-09-27']);
    expect(find.textContaining('暫定'), findsNothing);
  });
}
