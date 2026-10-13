import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:database_android/app_controller.dart';
import 'package:database_android/main.dart' show HistoryPage;
import 'package:database_android/theme.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/variety_idle.dart';

List<SlotRecord> sample(String store, {int games = 3000}) => [
  for (var day = 1; day <= 8; day++)
    for (var n = 1; n <= 4; n++)
      for (var i = 0; i < n; i++)
        SlotRecord(
          store: store,
          day: '2026-10-0$day',
          machine: '$n台機種',
          rack: 10 * n + i,
          games: games,
          bb: 10,
          rb: 5,
          graph: const GraphMeasurement(
            baselineY: 200,
            peakY: 100,
            troughY: 220,
            endY: 150,
          ),
        ),
];

void main() {
  testWidgets('Androidの過去の記録でも3台機種を個別表示し、幸町バラエティは1〜2台と説明する', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = AppController()
      ..records = sample('saiwaichou')
          .where((r) => r.day == '2026-10-08')
          .toList();
    addTearDown(controller.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: HistoryPage(controller: controller)),
      ),
    );
    await tester.pump();
    expect(find.text('3台機種'), findsOneWidget);
    expect(find.text('バラエティ（2機種）'), findsOneWidget);
    expect(find.text('幸町・1〜2台の機種の3台'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  test('幸町の一覧・候補は1〜2台、長町南は1〜3台。3台機種は個別に残る', () {
    for (final store in ['saiwaichou', 'nagamachiminami']) {
      final all = sample(store),
          today = all.where((r) => r.day == '2026-10-08').toList();
      final saiwaichou = store == 'saiwaichou';
      expect(
        varietyMachines(today),
        saiwaichou ? {'1台機種', '2台機種'} : {'1台機種', '2台機種', '3台機種'},
      );
      expect(
        isVarietyRecord(today.firstWhere((r) => r.machine == '3台機種'), all),
        !saiwaichou,
      );
      final entries = [
        for (final r in today)
          (
            r,
            const ScoreResult(
              total: 60,
              provisional: true,
              referenceCount: 0,
              reasons: [],
            ),
          ),
      ];
      final groups = groupForList(entries);
      expect(groups[varietyGroupName]!.length, saiwaichou ? 3 : 6);
      expect(groups.containsKey('3台機種'), saiwaichou);
      if (saiwaichou) expect(groups['3台機種']!.length, 3);
      expect(summarizeMachines(entries).last.varietyLimit, saiwaichou ? 2 : 3);
      final candidates = dayCandidates(
        today,
        all,
      ).candidates.where((c) => c.variety);
      if (saiwaichou)
        expect(candidates.every((c) => c.record.machine != '3台機種'), true);
      final snapshot = candidateSnapshot(
        store: store,
        day: '2026-10-08',
        machine: varietyGroupName,
        all: all,
        now: DateTime.utc(2026, 10, 8),
      );
      expect(snapshot.total, saiwaichou ? 3 : 6);
      expect(
        snapshot.method,
        saiwaichou ? '2026-10-13-saiwaichou-variety-2' : nextDayMethodVersion,
      );
    }
  });
  test('回っていない台でも幸町の3台機種は外し、長町南は残す', () {
    for (final store in ['saiwaichou', 'nagamachiminami']) {
      final idle = idleVarietyRacks(
        sample(store, games: 300),
        store,
        '2026-10-08',
      );
      expect(
        idle.map((x) => x.latest.rack).toList(),
        store == 'saiwaichou' ? [10, 20, 21] : [10, 20, 21, 30, 31, 32],
      );
    }
  });
  test('2台から3台になると、通常機種とバラエティの候補の記録を更新する', () {
    final all = sample('saiwaichou');
    final newRow = all
        .firstWhere((r) => r.day == '2026-10-08' && r.machine == '2台機種')
        .copyWith(rack: 29);
    final changed = changedCandidateSnapshots(
      saved: [newRow],
      all: [...all, newRow],
      latest: const {},
      now: DateTime.utc(2026, 10, 8),
    );
    expect(changed.any((s) => s.machine == '2台機種'), true);
    expect(changed.firstWhere((s) => s.machine == varietyGroupName).total, 1);
  });
}
