import 'dart:convert';

import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(String day, int rack, int bb, {String machine = 'テスト'}) =>
    SlotRecord(
      store: 'saiwaichou',
      day: day,
      machine: machine,
      rack: rack,
      games: 3000,
      bb: bb,
      rb: 5,
    );

/// 6台・4日分。台番号が大きいほど当たりが多い。
List<SlotRecord> history() => [
  for (final day in ['2026-09-20', '2026-09-21', '2026-09-22', '2026-09-23'])
    for (var rack = 1; rack <= 6; rack++) rec(day, rack, 5 + rack * 2),
];

void main() {
  final now = DateTime(2026, 9, 23, 23, 30);

  test('記録する候補は結果画面の翌日候補と同じ台', () {
    final all = history();
    final snapshot = candidateSnapshot(
      store: 'saiwaichou',
      day: '2026-09-23',
      machine: 'テスト',
      all: all,
      now: now,
    );
    final shown = provisionalNextDayCandidates(
      all.where((r) => r.day == '2026-09-23').toList(),
      all,
    );
    expect(snapshot.total, 6);
    expect(snapshot.eligible, shown.eligible);
    expect(snapshot.candidates.map((c) => c.rack), [
      for (final c in shown.candidates) c.record.rack,
    ]);
    expect(snapshot.candidates, isNotEmpty);
  });

  test('中身が変わったときだけ記録し直す', () {
    final all = history();
    final saved = all.where((r) => r.day == '2026-09-23').toList();
    final first = changedCandidateSnapshots(
      saved: saved,
      all: all,
      latest: const {},
      now: now,
    );
    expect(first.map((s) => s.groupKey), ['saiwaichou|2026-09-23|テスト']);

    final latest = latestCandidateSnapshots(first);
    expect(
      changedCandidateSnapshots(
        saved: saved,
        all: all,
        latest: latest,
        now: now.add(const Duration(minutes: 5)),
      ),
      isEmpty,
    );

    // 1番台の当たりが増えると各台の指数が動くので、もう1件残る。
    final changedAll = [
      for (final r in all)
        r.day == '2026-09-23' && r.rack == 1 ? r.copyWith(bb: 60) : r,
    ];
    final second = changedCandidateSnapshots(
      saved: [
        changedAll.firstWhere((r) => r.day == '2026-09-23' && r.rack == 1),
      ],
      all: changedAll,
      latest: latest,
      now: now.add(const Duration(minutes: 10)),
    );
    expect(second, hasLength(1));
    expect(second.single.signature, isNot(first.single.signature));
  });

  test('保存した日より後の日の候補も計算し直すが、前の日と他機種は触らない', () {
    final all = [
      ...history(),
      for (var rack = 1; rack <= 6; rack++) rec('2026-09-24', rack, 9),
      for (var rack = 1; rack <= 6; rack++)
        rec('2026-09-23', rack, 9, machine: '別機種'),
    ];
    final changed = changedCandidateSnapshots(
      saved: [all.firstWhere((r) => r.day == '2026-09-23')],
      all: all,
      latest: const {},
      now: now,
    );
    expect(changed.map((s) => s.day).toSet(), {'2026-09-23', '2026-09-24'});
    expect(changed.every((s) => s.machine == 'テスト'), isTrue);
  });

  test('機種・日付の台を全部消すと「候補なし」を残す', () {
    final all = history();
    final saved = all.where((r) => r.day == '2026-09-23').toList();
    final latest = latestCandidateSnapshots(
      changedCandidateSnapshots(
        saved: saved,
        all: all,
        latest: const {},
        now: now,
      ),
    );
    final remaining = all.where((r) => r.day != '2026-09-23').toList();
    final afterDelete = changedCandidateSnapshots(
      saved: saved,
      all: remaining,
      latest: latest,
      now: now.add(const Duration(minutes: 1)),
    );
    expect(afterDelete.single.day, '2026-09-23');
    expect(afterDelete.single.total, 0);
    expect(afterDelete.single.candidates, isEmpty);
  });

  test('候補の記録はJSONで往復でき、壊れた記録は読まない', () {
    final snapshot = candidateSnapshot(
      store: 'saiwaichou',
      day: '2026-09-23',
      machine: 'テスト',
      all: history(),
      now: now,
    );
    final back = CandidateSnapshot.tryFromJson(
      jsonDecode(jsonEncode(snapshot.toJson())),
    )!;
    expect(back.signature, snapshot.signature);
    expect(back.takenAt, snapshot.takenAt);
    expect(
      CandidateSnapshot.tryFromJson({...snapshot.toJson(), 'store': 'other'}),
      isNull,
    );
    expect(
      CandidateSnapshot.tryFromJson({
        ...snapshot.toJson(),
        'day': '2026-02-30',
      }),
      isNull,
    );
    expect(CandidateSnapshot.tryFromJson('broken'), isNull);
  });

  test('記録時刻は時差付きで、同じ瞬間として読み戻せる', () {
    final stamp = timestampWithOffset(now);
    expect(stamp, matches(RegExp(r'[+-]\d\d:\d\d$')));
    expect(DateTime.parse(stamp).isAtSameMomentAs(now), isTrue);
    expect(
      // 23:00+09:00 は 14:00Z なので、14:30Z より早い。
      earliestTimestamp('2026-09-23T23:00:00+09:00', '2026-09-23T14:30:00Z'),
      '2026-09-23T23:00:00+09:00',
    );
    expect(
      earliestTimestamp(null, '2026-09-23T23:00:00+09:00'),
      '2026-09-23T23:00:00+09:00',
    );
    expect(earliestTimestamp(null, null), isNull);
  });

  test('バックアップに候補の記録が入り、読み戻せる', () {
    final service = BackupService();
    final snapshot = candidateSnapshot(
      store: 'saiwaichou',
      day: '2026-09-23',
      machine: 'テスト',
      all: history(),
      now: now,
    );
    final text = jsonEncode(
      service.backupPayload(history(), candidates: [snapshot]),
    );
    final read = service.candidatesFromJson(text);
    expect(read.single.signature, snapshot.signature);
    // 候補の記録がない（PC版などの）バックアップも、これまでどおり読める。
    final plain = jsonEncode(service.backupPayload(history()));
    expect(jsonDecode(plain), isNot(contains('candidate_snapshots')));
    expect(service.candidatesFromJson(plain), isEmpty);
    expect(service.planFromJson(plain, const []).added, hasLength(24));
  });

  test('初回取り込み時刻はバックアップの取り込みでも早い方を残す', () {
    final service = BackupService();
    final local = rec(
      '2026-09-23',
      1,
      9,
    ).copyWith(firstCapturedAt: '2026-09-23T23:00:00+09:00');
    final incoming = local.copyWith(
      firstCapturedAt: '2026-09-24T08:00:00+09:00',
      graph: const GraphMeasurement(
        baselineY: 200,
        peakY: 100,
        troughY: 250,
        endY: 180,
      ),
    );
    final plan = service.plan([incoming.toJson()], [local]);
    expect(plan.graphOnly.single.firstCapturedAt, '2026-09-23T23:00:00+09:00');
    expect(
      SlotRecord.fromJson(incoming.toJson()).firstCapturedAt,
      '2026-09-24T08:00:00+09:00',
    );
  });
}
