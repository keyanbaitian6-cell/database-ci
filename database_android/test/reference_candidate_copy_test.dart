import 'package:database_android/answer_check.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String day, int rack, {String machine = '通常機種'}) => SlotRecord(
  store: 'nagamachiminami',
  day: day,
  machine: machine,
  rack: rack,
  games: 4000,
  bb: 20 + rack % 7,
  rb: 10,
  maxHold: 1500,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 250,
    endY: 180,
  ),
);

Widget app(Widget child) => MaterialApp(
  theme: buildAppTheme(),
  home: Scaffold(
    body: ListView(padding: const EdgeInsets.all(16), children: [child]),
  ),
);

Future<void> phone(WidgetTester tester) async {
  await tester.binding.setSurfaceSize(const Size(393, 852));
  addTearDown(() => tester.binding.setSurfaceSize(null));
}

void main() {
  testWidgets('通常機種：表とグラフで★を参考候補と説明し、対象台は変えない', (tester) async {
    await phone(tester);
    final rows = [
      for (var rack = 101; rack <= 104; rack++) rec('2026-09-27', rack),
    ];
    final entries = [for (final r in rows) (r, scoreRecord(r, rows))];
    await tester.pumpWidget(
      app(
        MachineSection(
          machine: '通常機種',
          entries: entries,
          candidateRacks: const {101},
          onTap: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('★注目1台'), findsOneWidget);
    expect(find.textContaining(referenceCandidateLegend), findsNWidgets(2));
    expect(find.textContaining(regularReferenceCandidateNote), findsOneWidget);
    expect(
      tester
          .widget<MachineDataTable>(find.byType(MachineDataTable))
          .candidateRacks,
      {101},
    );
    expect(find.text(' ★'), findsOneWidget);
    expect(find.textContaining('★翌日向け'), findsNothing);
    expect(tester.takeException(), isNull);

    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    expect(find.textContaining('★注目1台'), findsOneWidget);
    expect(find.textContaining(referenceCandidateLegend), findsOneWidget);
    expect(tester.widget<GraphGrid>(find.byType(GraphGrid)).candidateRacks, {
      101,
    });
    expect(find.text('101 ★'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('バラエティ：★は参考候補にそろえ、通常機種の10記録日の説明を出さない', (tester) async {
    await phone(tester);
    final rows = [
      rec('2026-09-27', 101, machine: '少数機種A'),
      rec('2026-09-27', 102, machine: '少数機種B'),
    ];
    await tester.pumpWidget(
      app(
        MachineSection(
          machine: varietyGroupName,
          entries: [for (final r in rows) (r, scoreRecord(r, rows))],
          candidateRacks: const {102},
          onTap: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('★参考候補1台'), findsOneWidget);
    expect(find.textContaining(referenceCandidateLegend), findsNWidgets(2));
    expect(find.textContaining('直近10記録日'), findsNothing);
    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    expect(find.text('102 ★'), findsOneWidget);
    expect(find.textContaining('直近10記録日'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('バラエティだけのカードも参考候補にそろえ、選び方は別として説明する', (tester) async {
    await phone(tester);
    final record = rec('2026-09-27', 101, machine: '少数機種');
    await tester.pumpWidget(
      app(
        NextDayCandidatesCard(
          day: record.day,
          candidates: [
            (
              record: record,
              index: 50,
              days: 0,
              confidence: '比較なし',
              variety: true,
            ),
          ],
          machines: 1,
          judged: 1,
          onPick: (_) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('9/28（月） の参考候補・長期傾向'), findsOneWidget);
    expect(find.text('バラエティ（1〜3台の機種）の参考候補1台'), findsOneWidget);
    expect(find.textContaining('長町南の狙い方：'), findsOneWidget);
    expect(find.textContaining('直近10記録日'), findsNothing);
    expect(find.text('101番台'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('候補なし：記録の判定条件を伝え、不調と断定しない', (tester) async {
    await phone(tester);
    await tester.pumpWidget(
      app(
        NextDayCandidatesCard(
          day: '2026-09-27',
          candidates: const [],
          machines: 1,
          judged: 0,
          onPick: (_) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('9/28（月） の参考候補・長期傾向'), findsOneWidget);
    expect(find.textContaining('3日分たまり、1機種で4台以上判定できる'), findsOneWidget);
    expect(find.textContaining('候補がないことは、不調を意味しません。'), findsOneWidget);
    expect(find.textContaining('直近10記録日'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('台の詳細：通常機種の履歴とバラエティの説明を混同しない', (tester) async {
    await phone(tester);
    final regular = [
      for (var day = 25; day <= 27; day++)
        for (var rack = 101; rack <= 104; rack++) rec('2026-09-$day', rack),
    ];
    await tester.pumpWidget(app(RackTrend(record: regular.last, all: regular)));
    await tester.pumpAndSettle();
    expect(find.textContaining('★注目・☆長期傾向の根拠'), findsOneWidget);
    expect(find.textContaining(regularReferenceCandidateNote), findsOneWidget);
    expect(tester.takeException(), isNull);

    final variety = [
      for (var day = 25; day <= 27; day++)
        rec('2026-09-$day', 201, machine: '少数機種'),
    ];
    await tester.pumpWidget(app(RackTrend(record: variety.last, all: variety)));
    await tester.pumpAndSettle();
    expect(find.textContaining('翌日向けの参考候補は、長町南で'), findsOneWidget);
    expect(find.textContaining('直近10記録日'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('答え合わせ：通常の参考候補の結果だと表示する', (tester) async {
    await phone(tester);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: AnswerCheckPage(
          records: const [],
          store: 'nagamachiminami',
          onOpen: (_, _) {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('前の日の「参考候補（翌日向け）」'), findsOneWidget);
    expect(find.textContaining('翌日候補（仮）'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
