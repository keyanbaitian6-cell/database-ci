// 2026-09-27 の見直し（妥協点の洗い出し）で直した所のテスト。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/graph_preview.dart';
import 'package:database_android/import_service.dart';
import 'package:database_android/models.dart';
import 'package:database_android/ui_prefs.dart';
import 'package:database_android/write_queue.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'support/real_database.dart';

SlotRecord rec(int rack, {String day = '2026-09-25', int games = 3000}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: day,
      machine: 'テスト',
      rack: rack,
      games: games,
      bb: 10,
      rb: 5,
      maxHold: 1200,
      firstCapturedAt: '${day}T23:00:00.000+09:00',
    );

Future<File> tempFile(String name) async {
  final dir = await Directory.systemTemp.createTemp('robustness_test');
  return File(p.join(dir.path, name));
}

EditableRow row(int rack, {int games = 3000}) => EditableRow(
  rack: rack,
  games: games,
  bb: 10,
  rb: 5,
  maxHold: null,
  previousStart: null,
);

/// 翌日候補の記録を読めないDB（起動時の失敗を知らせるかの確認用）。
class BrokenCandidates extends DatabaseService {
  BrokenCandidates(String path)
    : super(
        factoryOverride: databaseFactoryFfi,
        pathOverride: path,
        seed: false,
      );

  @override
  Future<List<CandidateSnapshot>> loadLatestCandidateSnapshots() =>
      Future.error(StateError('broken table'));
}

/// 書き出し先を、端末の一時フォルダではなくテスト用のフォルダにする。
class TempBackupService extends BackupService {
  @override
  Future<File> newBackupFile({String source = 'android'}) async {
    final dir = await Directory.systemTemp.createTemp('backup_out');
    return File(p.join(dir.path, backupFileName(DateTime.now())));
  }
}

Future<AppController> openApp(DatabaseService db, {String? today}) async {
  final app = AppController(database: db, backupService: TempBackupService());
  if (today != null) app.today = () => today;
  await app.initialize();
  return app;
}

void main() {
  group('1-1 バックアップは、保存できたと確かめてから印を付ける', () {
    test('書き出しただけでは印を付けず、確かめたら書き出しの時刻で付ける', () async {
      final db = realDatabase(await newDatabasePath());
      await db.applyChanges(ChangeSet(upserts: [rec(1)]));
      final app = await openApp(db);
      final exported = await app.exportBackup();
      expect(exported.full, isTrue);
      expect(app.lastFullBackupExport, isNull);
      expect(app.lastBackupExport, isNull);
      expect((await db.loadState())['last_full_backup_export'], isNull);

      await app.confirmBackupSaved(exported);
      expect(app.lastFullBackupExport, exported.exportedAt.toLocal());
      expect(
        (await db.loadState())['last_full_backup_export'],
        exported.exportedAt.toIso8601String(),
      );
      await db.close();
    });

    test('店舗や日付を絞った書き出しでは、全期間の印を付けない・古い印に戻さない', () async {
      final db = realDatabase(await newDatabasePath());
      await db.applyChanges(ChangeSet(upserts: [rec(1)]));
      final app = await openApp(db);
      final older = await app.exportBackup();
      final newer = await app.exportBackup();
      await app.confirmBackupSaved(newer);
      await app.confirmBackupSaved(older); // 後から古い方を確かめても戻さない
      expect(app.lastFullBackupExport, newer.exportedAt.toLocal());
      final partial = await app.exportBackup(day: '2026-09-25');
      expect(partial.full, isFalse);
      await app.confirmBackupSaved(partial);
      expect(app.lastFullBackupExport, newer.exportedAt.toLocal());
      expect(app.lastBackupExport, partial.exportedAt.toLocal());
      await db.close();
    });
  });

  group('1-2 保存期間の基準日と、未来の日付', () {
    test('未来の日付の台が1件あっても、基準は今日までにして残すべき台を消さない', () async {
      final db = realDatabase(await newDatabasePath());
      await db.applyChanges(
        ChangeSet(
          upserts: [
            rec(1, day: '2027-09-27'), // 打ち間違いの1年先
            rec(2, day: '2026-09-27'),
            rec(3, day: '2026-08-01'),
          ],
        ),
      );
      final result = await db.cleanupOldRecords(
        DateTime.now().add(const Duration(minutes: 1)),
        today: '2026-09-27',
      );
      expect(result.cutoff, '2026-07-30');
      expect(result.deleted, 0);
      expect((await db.loadAll()).length, 3);
      await db.close();
    });

    test('片付ける台が多すぎるときは止め、確かめたら片付ける（一時取り込みの印は残す）', () async {
      final db = realDatabase(await newDatabasePath());
      await db.applyChanges(
        ChangeSet(
          upserts: [
            for (var i = 0; i < 600; i++) rec(i, day: '2026-06-01'),
            rec(9000, day: '2026-09-27'),
          ],
        ),
      );
      await db.markTemporary(['nagamachiminami|2026-09-27|テスト|9000']);
      final state = {
        'last_full_backup_export': DateTime.now()
            .add(const Duration(minutes: 1))
            .toUtc()
            .toIso8601String(),
      };
      await db.applyChanges(ChangeSet(state: state));
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      )..today = () => '2026-09-27';
      await app.initialize();
      expect(app.pausedCleanup, 600);
      expect(app.records.length, 601);
      await app.confirmLargeCleanup();
      expect(app.pausedCleanup, 0);
      expect(app.records.map((r) => r.rack), [9000]);
      expect(app.retentionNotice, contains('600台'));
      await db.close();
    });

    test('明日より先の日付は保存しない。バックアップの中の未来の台も取り込まない', () async {
      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      await expectLater(
        app.saveTable('nagamachiminami', '2026-09-29', 'テスト', [row(1)]),
        throwsArgumentError,
      );
      await app.saveTable('nagamachiminami', '2026-09-28', 'テスト', [row(1)]);
      expect(app.records.single.day, '2026-09-28');

      final plan = BackupPlanner(const [], latestDay: '2026-09-28').plan([
        rec(2, day: '2026-09-28').toJson(),
        rec(3, day: '2027-01-01').toJson(),
      ]);
      expect(plan.added.map((r) => r.rack), [2]);
      expect(plan.skipped, 1);
      await db.close();
    });
  });

  group('1-3 バックアップの取り込みは、途中で失敗したら何も保存しない', () {
    Future<File> backupOf(List<SlotRecord> records) async {
      final from = realDatabase(await newDatabasePath());
      await from.applyChanges(ChangeSet(upserts: records));
      final file = await tempFile('b.json');
      await from.exportBackup(file);
      await from.close();
      return file;
    }

    test('壊れた行があれば、前の分も保存せず、取り消しの控えもそのまま', () async {
      final file = await backupOf([for (var i = 0; i < 400; i++) rec(i)]);
      final lines = await file.readAsLines();
      lines[350] = '{broken,'; // 2つ目の塊（301台目以降）の中
      await file.writeAsString(lines.join('\n'));

      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      await app.saveTable('nagamachiminami', '2026-09-26', 'テスト', [row(9)]);
      await expectLater(app.importBackup(file), throwsFormatException);
      expect(await db.loadAll(), hasLength(1));
      expect(app.records, hasLength(1));
      // 取り消しは、取り込みの前の保存に効く。
      await app.undoLastSave();
      expect(await db.loadAll(), isEmpty);
      await db.close();
    });

    test('保存の途中でDBが失敗しても、それまでの分を残さない', () async {
      final file = await backupOf([for (var i = 0; i < 400; i++) rec(i)]);
      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      // 350番台を書くときだけ失敗させる（1回目の確認は通り、2回目の保存で失敗）。
      await (await db.database).execute(
        'CREATE TRIGGER fail BEFORE INSERT ON records WHEN NEW.rack = 350 '
        "BEGIN SELECT RAISE(ABORT, 'disk failure'); END",
      );
      await expectLater(app.importBackup(file), throwsA(anything));
      expect(await db.loadAll(), isEmpty);
      expect(app.records, isEmpty);
      await db.close();
    });

    test('同じ台の違う記録が重複していたら、何も保存せずに止める', () async {
      final file = await tempFile('dup.json');
      await file.writeAsString(
        '{"format": "database-backup", "version": 1, "source": "pc", "records": [\n'
        '${jsonEncode(rec(1).toJson())},\n'
        '${jsonEncode(rec(2).toJson())},\n'
        '${jsonEncode(rec(1, games: 4000).toJson())}\n'
        ']}',
      );
      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      await expectLater(
        app.importBackup(file),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('保存せず中止しました'),
          ),
        ),
      );
      expect(await db.loadAll(), isEmpty);
      await db.close();
    });

    test('取り込めたら、進み具合を知らせ、取り消しで元に戻せる', () async {
      final file = await backupOf([for (var i = 0; i < 5; i++) rec(i)]);
      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      final progress = <String>[];
      final result = await app.importBackup(file, onProgress: progress.add);
      expect(result.added, 5);
      expect(progress.first, contains('確かめています'));
      expect(progress.last, contains('保存しています'));
      await app.undoLastSave();
      expect(await db.loadAll(), isEmpty);
      await db.close();
    });

    test('中身の目印は項目の順番に左右されず、違う中身は見分ける', () {
      final a = rec(1).toJson();
      final reordered = Map.fromEntries(a.entries.toList().reversed);
      expect(
        BackupService().plan([a, reordered], const []).added,
        hasLength(1),
      );
      expect(
        () => BackupService().plan([a, rec(1, games: 3001).toJson()], const []),
        throwsFormatException,
      );
    });
  });

  group('1-4 読めない記録があっても起動でき、記録は残す', () {
    test('壊れた行・形の違う行は飛ばして知らせ、書き出しにはそのまま入れる', () async {
      final db = realDatabase(await newDatabasePath());
      await db.applyChanges(ChangeSet(upserts: [rec(1)]));
      final raw = await db.database;
      final now = DateTime.now().toUtc().toIso8601String();
      await raw.rawInsert(
        'INSERT INTO records (record_key, store, day, machine, rack, payload, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        ['bad|1', 'nagamachiminami', '2026-09-25', 'テスト', 2, '{not json', now],
      );
      await raw.rawInsert(
        'INSERT INTO records (record_key, store, day, machine, rack, payload, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        [
          'bad|2',
          'nagamachiminami',
          '2026-09-25',
          'テスト',
          3,
          '{"rack": "x"}',
          now,
        ],
      );
      final app = await openApp(db);
      expect(app.records.map((r) => r.rack), [1]);
      expect(app.startupWarnings.single, contains('読めない記録が2件'));

      // JSONとして壊れた行も形の違う行も、元の内容を救出用として残す。
      final exported = await app.exportBackup();
      expect((exported.records, exported.unreadable), (3, 2));
      final whole = jsonDecode(await exported.file.readAsString()) as Map;
      final records = whole['records'] as List;
      expect(
        records.where((r) => (r as Map).containsKey('unreadable_record')),
        hasLength(2),
      );
      // 取り込み側（Android版）では対象外として飛ばす。
      final plan = BackupService().plan(records, const []);
      expect((plan.added.length, plan.skipped), (1, 2));
      await db.close();
    });

    test('新しい版で作られたDBでも、非常用の書き出しは読むだけで行える', () async {
      final path = await newDatabasePath();
      var db = realDatabase(path);
      await db.applyChanges(ChangeSet(upserts: [rec(1), rec(2)]));
      await db.close();
      final raw = await databaseFactoryFfi.openDatabase(path);
      await raw.setVersion(databaseVersion + 5);
      await raw.close();

      db = realDatabase(path);
      await expectLater(db.loadAll(), throwsA(isA<DatabaseTooNewException>()));
      final file = await tempFile('raw.json');
      final written = await db.exportRaw(file);
      expect(written.records, 2);
      final chunks = await BackupService().readBackupFile(file).toList();
      expect(chunks.expand((c) => c.records), hasLength(2));
      // 書き出しでDBの版を書き換えていない。
      final check = await databaseFactoryFfi.openDatabase(path);
      expect(await check.getVersion(), databaseVersion + 5);
      await check.close();
    });
  });

  group('1-5 失敗を黙って捨てない', () {
    test('翌日候補の記録を読めなければ知らせ、書き出しにはDBから入れる', () async {
      final path = await newDatabasePath();
      final setup = realDatabase(path);
      final records = [rec(1), rec(2)];
      await setup.applyChanges(
        ChangeSet(
          upserts: records,
          snapshots: [
            candidateSnapshot(
              store: 'nagamachiminami',
              day: '2026-09-25',
              machine: 'テスト',
              all: records,
              now: DateTime(2026, 9, 25, 23),
            ),
          ],
        ),
      );
      await setup.close();

      final db = BrokenCandidates(path);
      final app = await openApp(db);
      expect(app.startupWarnings.single, contains('翌日候補の記録を読み込めませんでした'));
      final exported = await app.exportBackup();
      expect(exported.candidates, 1);
      await db.close();
    });

    test('画像の読み込みに失敗しても覚えず、次は読み直す', () async {
      var calls = 0;
      final previews = GraphPreviews((key) async {
        calls++;
        if (calls == 1) throw StateError('busy');
        return Uint8List.fromList([1, 2, 3]);
      });
      final record = rec(1).copyWith(
        capturedAt: '2026-09-25T23:00:00',
        graph: const GraphMeasurement(
          baselineY: 1,
          peakY: 2,
          troughY: 3,
          endY: 4,
          storedPreview: true,
        ),
      );
      expect(await previews.load(record), isNull);
      expect(await previews.load(record), [1, 2, 3]);
      expect(await previews.load(record), [1, 2, 3]);
      expect(calls, 2);
      // 保存し直した台（取得時刻が変わった）は、忘れる指示がなくても読み直す。
      await previews.load(record.copyWith(capturedAt: '2026-09-26T23:00:00'));
      expect(calls, 3);
    });
  });

  test('1-6 店舗・機種名・台データが欠けた表は保存しない', () async {
    final db = realDatabase(await newDatabasePath());
    final app = await openApp(db, today: '2026-09-27');
    await expectLater(
      app.saveTable('nagamachiminami', '2026-09-25', '', [row(1)]),
      throwsArgumentError,
    );
    await expectLater(
      app.saveTable('unknown', '2026-09-25', 'テスト', [row(1)]),
      throwsArgumentError,
    );
    expect(await db.loadAll(), isEmpty);
    await db.close();
  });

  test('2-7 翌日候補の記録は180日より古く、バックアップに入れた後のものだけ片付ける', () async {
    final db = realDatabase(await newDatabasePath());
    CandidateSnapshot snap(String day, String takenAt) => CandidateSnapshot(
      store: 'nagamachiminami',
      day: day,
      machine: 'テスト',
      takenAt: takenAt,
      total: 1,
      eligible: 0,
      candidates: const [],
    );
    final backup = DateTime.utc(2026, 9, 27);
    await db.applyChanges(
      ChangeSet(
        upserts: [rec(1, day: '2026-09-27')],
        snapshots: [
          snap('2026-03-01', '2026-03-01T23:00:00.000+09:00'), // 片付ける
          snap('2026-04-01', '2026-09-28T01:00:00.000+09:00'), // 書き出しの後に記録
          snap('2026-06-01', '2026-06-01T23:00:00.000+09:00'), // 180日以内
        ],
      ),
    );
    final result = await db.cleanupOldRecords(backup, today: '2026-09-27');
    expect(result.snapshots, 1);
    expect([for (final s in await db.loadCandidateSnapshots()) s.day]..sort(), [
      '2026-04-01',
      '2026-06-01',
    ]);
    await db.close();
  });

  group('3-1 記録の版', () {
    test('保存のたびに版が進み、一覧は書き換えられない。1日ぶんの計算は使い回す', () async {
      final db = realDatabase(await newDatabasePath());
      final app = await openApp(db, today: '2026-09-27');
      final before = app.revision;
      await app.saveTable('nagamachiminami', '2026-09-25', 'テスト', [row(1)]);
      expect(app.revision, greaterThan(before));
      expect(() => app.records.add(rec(2)), throwsUnsupportedError);
      final view = app.dayView('nagamachiminami', '2026-09-25');
      await view;
      expect(
        identical(app.dayView('nagamachiminami', '2026-09-25'), view),
        isTrue,
      );
      await app.saveTable('nagamachiminami', '2026-09-25', 'テスト', [row(2)]);
      final next = app.dayView('nagamachiminami', '2026-09-25');
      await next;
      expect(identical(next, view), isFalse);
      expect((await next).scored, hasLength(2));
      await db.close();
    });
  });

  test('3-2 画面の設定は一時ファイルから名前を変えて保存し、最後の値が残る', () async {
    final dir = await Directory.systemTemp.createTemp('ui_prefs');
    final file = File(p.join(dir.path, 'ui_state.json'));
    final prefs = UiPrefs(file: () async => file);
    await Future.wait([
      prefs.remember('nagamachiminami', '2026-09-25', null),
      prefs.remember('saiwaichou', '2026-09-26', 'テスト'),
      prefs.setSkipTableReview(false),
    ]);
    final loaded = UiPrefs(file: () async => file);
    await loaded.load();
    expect(
      (loaded.store, loaded.day, loaded.machine, loaded.skipTableReview),
      ('saiwaichou', '2026-09-26', 'テスト', false),
    );
    expect(File('${file.path}.tmp').existsSync(), isFalse);
    // 壊れたファイルは既定値で読む。
    await file.writeAsString('{broken');
    final broken = UiPrefs(file: () async => file);
    await broken.load();
    expect(broken.skipTableReview, isTrue);
  });

  group('3-3 書き込みの順番待ち', () {
    test('順番待ちの中から入り直すと、止まらずに失敗する', () async {
      final queue = WriteQueue();
      final result = queue.run(() async {
        await queue.run(() async {});
      });
      await expectLater(result, throwsStateError);
      // 失敗の後も、次の書き込みはできる。
      expect(await queue.run(() async => 7), 7);
    });

    test('前の処理が終わらないとき、待っていた処理は時間切れにして行わない', () async {
      final queue = WriteQueue(timeout: const Duration(milliseconds: 50));
      final hang = Completer<void>();
      final first = queue.run(() => hang.future, unlimited: true);
      var ran = false;
      final second = queue.run(() async => ran = true);
      await expectLater(second, throwsA(isA<TimeoutException>()));
      hang.complete();
      await first;
      await queue.run(() async {}); // 順番は崩れていない
      expect(ran, isFalse);
    });

    test('順番待ちの外から保存の内部を呼ぶと失敗する', () async {
      final queue = WriteQueue();
      expect(() => queue.checkInside('保存'), throwsStateError);
      await queue.run(() async => queue.checkInside('保存'));
    });
  });

  test('3-8 は viewer_data_test、3-5 は capture_flow_test にある', () {});
}
