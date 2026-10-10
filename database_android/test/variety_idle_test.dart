import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/variety_idle.dart';
import 'package:database_android/viewer_bridge.dart';

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
    saveViewerSetting(idleDaysKey, '$idleDefaultDays');
    saveViewerSetting(idleGamesKey, '$idleDefaultGames');
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
      find.textContaining('9日間 1,000G未満（10/2（金）〜）・最多410G'),
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

  test('期間はカレンダーの日数：記録の無い日（サイトが落ちていた日）は飛ばして期間に含める', () {
    // 4〜7日は店舗の記録が無い。記録のある6日（1〜3日・8〜10日）はどれも1000G未満。
    final all = [
      for (final n in [1, 2, 3, 8, 9, 10]) ...[
        for (var rack = 1; rack <= 4; rack++) rec(n, '主力', rack, 300),
        rec(n, 'X', 50, 200),
      ],
    ];
    final idle = idleVarietyRacks(all, 'nagamachiminami', day(10)).single;
    expect((idle.spanDays, idle.days.length, idle.from), (10, 6, day(1)));
    expect(
      idleVarietyRacks(all, 'nagamachiminami', day(10), minDays: 14),
      isEmpty,
    );
    expect(calendarDays('2026-09-28', '2026-10-04'), 7, reason: '月をまたいでも数える');
  });

  test('期間・ゲーム数を変えて選び直せる', () {
    final all = sample();
    List<(int, int)> pick({int minDays = 7, int gamesLimit = 1000}) => [
      for (final r in idleVarietyRacks(
        all,
        'nagamachiminami',
        day(10),
        minDays: minDays,
        gamesLimit: gamesLimit,
      ))
        (r.latest.rack, r.spanDays),
    ];
    expect(pick(gamesLimit: 500), [(10, 9)], reason: 'B20は999Gなので500G未満ではない');
    expect(pick(minDays: 3), [(10, 9), (20, 7), (21, 6), (30, 5), (40, 3)]);
    expect(pick(minDays: 3, gamesLimit: 3000), [
      (10, 10),
      (20, 10),
      (21, 10),
      (30, 5),
      (40, 3),
    ], reason: '3000G未満なら1日目の2500G・1500Gの日も含む。同じ期間は台番号の順');
  });

  testWidgets('期間・ゲーム数のプルダウンで選び直し、選んだ値を覚える', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    saveViewerSetting(idleDaysKey, '$idleDefaultDays');
    saveViewerSetting(idleGamesKey, '$idleDefaultGames');
    Widget page() => MaterialApp(
      theme: buildAppTheme(),
      home: VarietyIdlePage(
        records: sample(),
        store: 'nagamachiminami',
        day: day(10),
        onOpen: (_) {},
      ),
    );
    await tester.pumpWidget(page());
    expect(find.text('7日以上'), findsOneWidget);
    expect(find.text('1,000G未満'), findsOneWidget);
    expect(find.text('2台'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('variety-idle-期間')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('3日以上').last);
    await tester.pumpAndSettle();
    expect(find.text('5台'), findsOneWidget);
    expect(loadViewerSetting(idleDaysKey), '3');
    await tester.tap(find.byKey(const ValueKey('variety-idle-ゲーム数')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('500G未満').last);
    await tester.pumpAndSettle();
    expect(
      find.text('4台'),
      findsOneWidget,
      reason: 'A（9日間）・B21（200G、6日間）・C（5日間）・D（3日間）。B20は999Gなので出ない',
    );
    expect(find.textContaining('9日間 500G未満'), findsOneWidget);
    expect(loadViewerSetting(idleGamesKey), '500');
    // 開き直しても覚えた値のまま。壊れた値は既定値に戻す。
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(page());
    expect(find.text('3日以上'), findsOneWidget);
    expect(find.text('500G未満'), findsOneWidget);
    saveViewerSetting(idleDaysKey, '99');
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(page());
    expect(find.text('7日以上'), findsOneWidget);
  });
}
