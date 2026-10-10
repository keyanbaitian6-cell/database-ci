import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/variety_idle.dart';

/// 2026-10-01 から数えて [n] 日目（1始まり）。
String day(int n) => '2026-10-${n.toString().padLeft(2, '0')}';

SlotRecord rec(
  int n,
  String machine,
  int rack,
  int games, {
  String store = 'nagamachiminami',
}) => SlotRecord(
  store: store,
  day: day(n),
  machine: machine,
  rack: rack,
  games: games,
  bb: 1,
  rb: 1,
);

/// 1〜10日：主力（4台）、バラエティのA（1台）・B（2台）・C（1台、5日目に記録なし）・
/// D（3日前にEから入れ替え）。
List<SlotRecord> sample() => [
  for (var n = 1; n <= 10; n++) ...[
    for (var rack = 1; rack <= 4; rack++) rec(n, '主力', rack, 300),
    rec(n, 'A', 10, n == 1 ? 2500 : 400 + n),
    rec(n, 'B', 20, n <= 3 ? 1000 : 999),
    rec(n, 'B', 21, n == 4 ? 1500 : 200),
    if (n != 5) rec(n, 'C', 30, 100),
    n >= 8 ? rec(n, 'D', 40, 50) : rec(n, 'E', 40, 50),
    rec(n, 'A', 10, 100, store: 'saiwaichou'),
  ],
];

void main() {
  test('バラエティで、選んだ日から前へ毎日1000G未満が7日以上続く台だけ（多い順）', () {
    final racks = idleVarietyRacks(sample(), 'nagamachiminami', day(10));
    expect(
      [for (final r in racks) (r.latest.machine, r.latest.rack, r.days.length)],
      [('A', 10, 9), ('B', 20, 7)],
      reason:
          '主力（4台）は出さない。1000Gちょうどは回った日。'
          'B21は1500Gの日で切れて6日、Cは記録の無い日で切れ、Dは入れ替え前のEを混ぜない',
    );
    expect(racks.first.from, day(2));
    expect(racks.first.maxGames, 410);
    expect(racks.first.days.first.day, day(10));
  });

  test('日を戻すとその日から数え直す。記録日の無い日・記録が足りない日は出さない', () {
    final all = sample();
    expect(
      [
        for (final r in idleVarietyRacks(all, 'nagamachiminami', day(9)))
          (r.latest.rack, r.days.length),
      ],
      [(10, 8)],
    );
    // 7日目はまだ入れ替え前：Eの40番は1〜7日の7日続いて出る（Aは2〜7日の6日で出ない）。
    expect(
      [
        for (final r in idleVarietyRacks(all, 'nagamachiminami', day(7)))
          (r.latest.machine, r.latest.rack, r.days.length),
      ],
      [('E', 40, 7)],
    );
    expect(idleVarietyRacks(all, 'nagamachiminami', day(6)), isEmpty);
    expect(idleVarietyRacks(all, 'nagamachiminami', '2026-10-11'), isEmpty);
    expect(idleVarietyRacks(all, 'saiwaichou', day(10)).single.days.length, 10);
  });

  testWidgets('一覧を出し、台を押すとその台を開く。日付を変えると数え直す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    SlotRecord? opened;
    String? changed;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: VarietyIdlePage(
          records: sample(),
          store: 'nagamachiminami',
          day: day(10),
          onOpen: (r) => opened = r,
          onDayChanged: (d) => changed = d,
        ),
      ),
    );
    expect(find.text('2台'), findsOneWidget);
    expect(find.text('10番　A'), findsOneWidget);
    expect(
      find.textContaining('9日連続 1000G未満（10/2（金）〜）・最多410G'),
      findsOneWidget,
    );
    expect(find.text('20番　B'), findsOneWidget);
    await tester.tap(find.text('20番　B'));
    expect((opened!.rack, opened!.day), (20, day(10)));
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(changed, day(9));
    expect(find.text('1台'), findsOneWidget);
    expect(find.text('20番　B'), findsNothing);
    for (var i = 0; i < 2; i++) {
      await tester.tap(find.byTooltip('前の記録日'));
      await tester.pumpAndSettle();
    }
    expect(find.text('40番　E'), findsOneWidget);
    await tester.tap(find.byTooltip('前の記録日'));
    await tester.pumpAndSettle();
    expect(find.text('当てはまる台はありません'), findsOneWidget);
  });
}
