import 'package:database_android/exploratory_candidates.dart';
import 'package:database_android/exploratory_page.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 長町南・機種A・8台・5日（9/20〜9/24）。
SlotRecord rec(String day, int rack) {
  final d = int.parse(day.substring(8));
  final bb = 10 + ((rack * 7 + d * 3) % 17);
  return SlotRecord(
    store: 'nagamachiminami',
    day: day,
    machine: 'A',
    rack: rack,
    games: 4000,
    bb: bb,
    rb: 8,
    maxHold: bb * 120,
  );
}

final records = [
  for (final day in [
    '2026-09-20',
    '2026-09-21',
    '2026-09-22',
    '2026-09-23',
    '2026-09-24',
  ])
    for (var rack = 1; rack <= 8; rack++) rec(day, rack),
];

void main() {
  testWidgets('新規予測：選択日と対象日、探索中の表示、成績の説明。台を押すと詳細へ', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final opened = <SlotRecord>[];
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: ExploratoryForecastPage(
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          day: '2026-09-24',
          onOpen: opened.add,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('新規予測（試験）'), findsOneWidget);
    expect(find.text('9/25（金） の新規予測'), findsOneWidget);
    expect(find.text('探索中'), findsOneWidget);
    expect(
      find.textContaining('9/24（木）（選択日）までの記録から、9/25（金）向けに選んだ台です'),
      findsOneWidget,
    );
    expect(find.text(exploratoryValidationNote), findsOneWidget);

    // 画面の候補は、新規予測の計算（組み合わせ）そのもの。
    final expected = exploratoryCandidates(
      [for (final r in records) if (r.day == '2026-09-24') r],
      records,
      ExploratoryMethod.blend,
    );
    expect(expected, isNotEmpty);
    final first = expected.first;
    expect(find.text('${first.record.rack}番台'), findsOneWidget);
    await tester.tap(find.text('${first.record.rack}番台'));
    expect(opened.single.key, first.record.key);

    // 日付を変えると、その日の新規予測に変わる。
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.text('9/24（木） の新規予測'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('候補を出せない日は、何が足りないかを出す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: ExploratoryForecastPage(
          data: ViewerData(records: records),
          store: 'nagamachiminami',
          day: '2026-09-20',
          onOpen: (_) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('まだ選べる機種がありません'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
