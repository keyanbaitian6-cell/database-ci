import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/import_spool.dart';
import 'package:database_android/models.dart';
import 'package:database_android/page_readiness.dart';
import 'package:database_android/record_analysis.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

SlotRecord row(int rack, {bool graph = true, int games = 3000}) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-25',
  machine: 'テスト',
  rack: rack,
  games: games,
  bb: 10,
  rb: 5,
  maxHold: 1200,
  graph: graph
      ? GraphMeasurement(
          baselineY: 200,
          peakY: 100,
          troughY: 250,
          endY: 180,
          previewPng: Uint8List.fromList(List.filled(8192, rack % 256)),
          previewWidth: 100,
          previewHeight: 300,
          curve: const [
            [0, 200],
            [100, 180],
          ],
        )
      : null,
);

CandidateSnapshot snapshot(String time) => CandidateSnapshot(
  store: 'nagamachiminami',
  day: '2026-09-25',
  machine: 'テスト',
  takenAt: time,
  total: 4,
  eligible: 4,
  candidates: const [],
);

void main() {
  test('画像付き大量取り込みを取り消すと、追加台が消え元の画像が戻る', () async {
    final source = realDatabase(await newDatabasePath());
    final target = realDatabase(await newDatabasePath());
    addTearDown(source.close);
    addTearDown(target.close);
    final original = row(1);
    await target.applyChanges(ChangeSet(upserts: [original]));
    final records = [
      original.copyWith(confirmedSetting: '6'),
      for (var i = 2; i <= 350; i++) row(i),
    ];
    await source.applyChanges(ChangeSet(upserts: records));
    final file = File('${(await source.database).path}.json');
    await source.exportBackup(file);
    final app = AppController(database: target);
    await app.initialize();
    final result = await app.importBackup(file);
    expect(result.added, 349);
    expect(result.settingOnly, 1);
    expect(app.records, hasLength(350));
    expect(app.records.every((r) => r.graph?.previewPng == null), isTrue);
    expect(await target.loadPreview(original.key), original.graph!.previewPng);
    await app.undoLastSave();
    expect((await fullRows(target)).single.encode(), original.encode());
    expect(app.records, hasLength(1));
  });

  test('競合一覧は画像を持たず、選択した分だけ完全な記録を読み戻す', () async {
    final source = realDatabase(await newDatabasePath());
    final target = realDatabase(await newDatabasePath());
    addTearDown(source.close);
    addTearDown(target.close);
    await source.applyChanges(
      ChangeSet(upserts: [for (var i = 1; i <= 120; i++) row(i)]),
    );
    await target.applyChanges(
      ChangeSet(upserts: [for (var i = 1; i <= 120; i++) row(i, games: 4000)]),
    );
    final file = File('${(await source.database).path}.json');
    await source.exportBackup(file);
    final app = AppController(database: target);
    await app.initialize();
    final result = await app.importBackup(file);
    expect(result.conflicts, hasLength(120));
    expect(
      result.conflicts.every((c) => c.incoming.graph!.previewPng == null),
      isTrue,
    );
    final chosen = await result.readConflicts([result.conflicts.last.incoming]);
    expect(chosen.single.graph!.previewPng, row(120).graph!.previewPng);
    await app.applyBackupOverrides(chosen);
    expect(
      (await target.loadByKeys([chosen.single.key]))[chosen.single.key]!.games,
      3000,
    );
    await app.undoLastSave();
    expect(
      (await target.loadByKeys([chosen.single.key]))[chosen.single.key]!.games,
      4000,
    );
    await result.conflictSpool!.delete();
  });

  test('候補履歴は分割読込しDBに全件、画面用には各組の最新だけ残す', () async {
    final db = realDatabase(await newDatabasePath());
    addTearDown(db.close);
    final items = [
      for (var i = 0; i < 650; i++)
        snapshot(
          DateTime.utc(2026, 9, 25).add(Duration(seconds: i)).toIso8601String(),
        ),
      snapshot('2026-09-25T10:00:00+09:00'),
      snapshot('2026-09-25T02:00:00Z'),
    ];
    await db.applyChanges(ChangeSet(snapshots: items));
    expect(
      (await db.loadLatestCandidateSnapshots()).single.takenAt,
      '2026-09-25T02:00:00Z',
    );
    final file = File('${(await db.database).path}.json');
    await db.exportBackup(file);
    final chunks = await BackupService()
        .readBackupFile(file, chunkSize: 50)
        .toList();
    expect(chunks.every((c) => c.candidates.length <= 50), isTrue);
    expect(
      chunks.fold<int>(0, (n, c) => n + c.candidates.length),
      items.length,
    );
    final target = realDatabase(await newDatabasePath());
    addTearDown(target.close);
    final app = AppController(database: target);
    await app.initialize();
    expect((await app.importBackup(file)).candidates, items.length);
    expect(app.candidateSnapshots, hasLength(1));
    expect(app.candidateSnapshots.single.takenAt, '2026-09-25T02:00:00Z');
    expect(await target.loadCandidateSnapshots(), hasLength(items.length));
    expect((await app.importBackup(file)).candidates, 0);
  });

  test('別Isolateの採点は同じ入力の従来計算と一致する', () async {
    final all = [
      for (var d = 1; d <= 25; d++)
        for (var i = 1; i <= 20; i++)
          row(
            i,
            graph: false,
          ).copyWith(day: '2026-09-${d.toString().padLeft(2, '0')}'),
    ];
    final actual = await compute(calculateDay, (
      all,
      'nagamachiminami',
      '2026-09-25',
    ));
    expect(actual.scored, hasLength(20));
    for (final entry in actual.scored.values) {
      final expected = scoreRecord(entry.$1, all);
      expect(entry.$2.total, expected.total);
      expect(entry.$2.referenceCount, expected.referenceCount);
      expect(entry.$2.reasons, expected.reasons);
    }
    final expected = calculateDay((all, 'nagamachiminami', '2026-09-25'));
    expect(
      actual.candidates.candidates.map((c) => (c.record.key, c.index)),
      expected.candidates.candidates.map((c) => (c.record.key, c.index)),
    );
  });

  test('遅い通信中の部分一覧を確定せず、全体が安定してから返す', () async {
    var elapsed = Duration.zero;
    final result = await waitForStablePage(
      elapsed: () => elapsed,
      delay: (d) async {
        elapsed += d;
      },
      isCurrent: () => true,
      read: () async => {
        'ready': elapsed.inSeconds >= 5,
        'hasContent': true,
        'content': elapsed.inSeconds < 5 ? [1] : [1, 2, 3],
      },
    );
    expect(result['content'], [1, 2, 3]);
    expect(elapsed, greaterThanOrEqualTo(const Duration(milliseconds: 6500)));
  });

  test('空一覧・通信中は時間切れでも完了と扱わない', () async {
    for (final ready in [true, false]) {
      var elapsed = Duration.zero;
      await expectLater(
        waitForStablePage(
          timeout: const Duration(seconds: 2),
          elapsed: () => elapsed,
          delay: (d) async {
            elapsed += d;
          },
          isCurrent: () => true,
          read: () async => {
            'ready': ready,
            'hasContent': !ready,
            'content': [],
          },
        ),
        throwsFormatException,
      );
    }
  });

  test('内容が途中で変われば安定待ちをやり直し、画面遷移は中止する', () async {
    var elapsed = Duration.zero;
    await waitForStablePage(
      elapsed: () => elapsed,
      delay: (d) async {
        elapsed += d;
      },
      isCurrent: () => true,
      read: () async => {
        'ready': true,
        'hasContent': true,
        'content': elapsed.inMilliseconds < 1000 ? [1] : [1, 2],
      },
    );
    expect(elapsed, const Duration(milliseconds: 2500));
    var current = true;
    await expectLater(
      waitForStablePage(
        isCurrent: () => current,
        read: () async {
          current = false;
          return {
            'ready': true,
            'hasContent': true,
            'content': [1],
          };
        },
      ),
      throwsFormatException,
    );
  });

  test('一時控えの順次読込は指定件数以内、ランダム読込も同じ', () async {
    final spool = await ImportSpool.create(await newDatabasePath());
    for (var i = 0; i < 205; i++) {
      await spool.add({'id': i}, key: '$i');
    }
    final chunks = await spool.chunks(size: 50).toList();
    expect(chunks.map((c) => c.length), [50, 50, 50, 50, 5]);
    expect(await spool.read('204'), {'id': 204});
    await spool.delete();
    expect(await spool.file.exists(), isFalse);
  });
}
