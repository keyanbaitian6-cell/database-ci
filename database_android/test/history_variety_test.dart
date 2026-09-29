import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String machine, int rack) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-28',
  machine: machine,
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
);

void main() {
  testWidgets('過去の記録：1〜3台の機種はバラエティ1行。機種名で絞るとその機種の台だけ', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = AppController()
      ..records = [
        for (var rack = 1; rack <= 4; rack++) rec('Z', rack),
        rec('北斗', 30),
        rec('北斗', 31),
        rec('ハナハナ', 20),
      ];
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: HistoryPage(controller: controller)),
      ),
    );
    await tester.pump();
    expect(find.text('Z'), findsOneWidget);
    expect(find.text('バラエティ（2機種）'), findsOneWidget);
    expect(find.text('長町南・1〜3台の機種の3台'), findsOneWidget);
    // 日付の見出しは、まとめる前の機種数（Z・北斗・ハナハナ）と台数。
    expect(find.text('3機種・7台'), findsOneWidget);

    // 機種名で絞ると、バラエティはその機種の台だけの行になる。
    await tester.enterText(find.byType(TextField).first, '北斗');
    await tester.pump();
    expect(find.text('バラエティ（1機種）'), findsOneWidget);
    expect(find.text('長町南・1〜3台の機種の2台'), findsOneWidget);
    expect(find.text('Z'), findsNothing);

    // 「バラエティ」で探すと、全部の台。
    await tester.enterText(find.byType(TextField).first, 'ばらえてぃ');
    await tester.pump();
    expect(find.text('バラエティ（2機種）'), findsOneWidget);
    expect(find.text('Z'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
