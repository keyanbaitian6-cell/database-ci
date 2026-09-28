// 2026-09-28：時間を超えた書き込みの追跡（⑥）と、起動の途中で済んだ変更の
// 説明（⑦）のテスト。
import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/import_service.dart';
import 'package:database_android/models.dart';
import 'package:database_android/write_queue.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'support/real_database.dart';

class TempBackupService extends BackupService {
  @override
  Future<File> newBackupFile({String source = 'android'}) async {
    final dir = await Directory.systemTemp.createTemp('backup_out');
    return File(p.join(dir.path, backupFileName(DateTime.now())));
  }
}

/// 起動の各段階を、わざと失敗・停止させられるDB。
class FaultyDatabase extends DatabaseService {
  FaultyDatabase(String path)
    : super(
        factoryOverride: databaseFactoryFfi,
        pathOverride: path,
        seed: false,
      );

  bool failLoad = false;
  bool failCleanup = false;
  Completer<void>? holdWrites;

  /// 機種名をそろえた（DBに確定した）直後の読み直しだけを失敗させる。
  bool failLoadAfterNormalize = false;
  var _normalized = false;

  @override
  Future<int> normalizeMachineNames() async {
    final merged = await super.normalizeMachineNames();
    _normalized = true;
    return merged;
  }

  @override
  Future<List<SlotRecord>> loadAll() {
    if (failLoad || (failLoadAfterNormalize && _normalized)) {
      return Future.error(StateError('読めません'));
    }
    return super.loadAll();
  }

  @override
  Future<CleanupResult> cleanupOldRecords(
    DateTime? lastFullBackup, {
    required String today,
    bool allowLarge = false,
    bool temporary = true,
  }) => failCleanup
      ? Future.error(StateError('片付けに失敗'))
      : super.cleanupOldRecords(
          lastFullBackup,
          today: today,
          allowLarge: allowLarge,
          temporary: temporary,
        );

  @override
  Future<void> applyChanges(ChangeSet changes) async {
    final hold = holdWrites;
    if (hold != null) await hold.future;
    return super.applyChanges(changes);
  }
}

EditableRow row(int rack) => EditableRow(
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
  maxHold: null,
  previousStart: null,
);

void main() {
  group('⑥ 時間を超えた書き込みを最後まで追う', () {
    test('続いている間は次の書き込みを断り、終わったら結果を知らせる', () async {
      final queue = WriteQueue(timeout: const Duration(milliseconds: 50));
      final late = <Object?>[];
      queue.onLateFinish = late.add;
      final hang = Completer<int>();
      final slow = queue.run(() => hang.future);
      await expectLater(slow, throwsA(isA<TimeoutException>()));
      expect(queue.overdue, isTrue);

      // 同じ操作をもう一度押しても、待たせずに断る（2回行われない）。
      var ran = false;
      await expectLater(
        queue.run(() async => ran = true),
        throwsA(
          isA<StateError>().having((e) => e.message, 'message', contains('まだ続いています')),
        ),
      );

      hang.complete(1);
      await Future<void>.delayed(Duration.zero);
      expect(late, [null]); // 成功として知らせる
      expect(queue.overdue, isFalse);
      expect(ran, isFalse);
      expect(await queue.run(() async => 2), 2); // 次の書き込みはできる
    });

    test('後から失敗したときも知らせる。時間内に終わった処理は知らせない', () async {
      final queue = WriteQueue(timeout: const Duration(milliseconds: 50));
      final late = <Object?>[];
      queue.onLateFinish = late.add;
      expect(await queue.run(() async => 1), 1);
      await expectLater(
        queue.run<void>(() => Future.error(StateError('すぐ失敗'))),
        throwsStateError,
      );
      expect(late, isEmpty);

      final hang = Completer<void>();
      final slow = queue.run(() => hang.future);
      await expectLater(slow, throwsA(isA<TimeoutException>()));
      hang.completeError(StateError('後から失敗'));
      await Future<void>.delayed(Duration.zero);
      expect(late.single, isA<StateError>());
      expect(queue.overdue, isFalse);
    });

    test('アプリの画面にも、後から終わったことを出す', () async {
      final db = FaultyDatabase(await newDatabasePath());
      final app = AppController(
        database: db,
        queue: WriteQueue(timeout: const Duration(milliseconds: 50)),
        backupService: TempBackupService(),
      );
      await app.initialize();
      final notices = <String>[];
      app.onNotice = notices.add;

      db.holdWrites = Completer<void>();
      await expectLater(
        app.saveTable('nagamachiminami', app.today(), 'テスト', [row(1)]),
        throwsA(isA<TimeoutException>()),
      );
      expect(app.records, isEmpty);

      db.holdWrites!.complete();
      db.holdWrites = null;
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(app.records.map((r) => r.rack), [1]); // 保存は最後まで済んだ
      expect(app.message, contains('いま終わりました'));
      expect(notices.single, app.message);
      await db.close();
    });
  });

  group('⑦ 起動の途中で済んだ変更を、正しく説明する', () {
    test('必須の読み込みで失敗したら、それまでに済んだ変更を書く', () async {
      final db = FaultyDatabase(await newDatabasePath())..failLoad = true;
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await expectLater(app.initialize(), throwsStateError);
      // 初めての起動なので、イベント名の初期値は保存が済んでいる。
      expect(app.startupChanges, ['イベント名の初期値を保存しました。']);
      expect((await db.loadState())['date_events'], isNotNull);
      final text = startupFailureText(app.startupChanges, StateError('読めません'));
      expect(text, contains('イベント名の初期値を保存しました'));
      expect(text, isNot(contains('起動できませんでした。記録は変更していません')));
      expect(text, contains('ほかの記録は変更していません'));
      await db.close();
    });

    test('何も変えていなければ、これまでどおり「変更していません」', () async {
      final path = await newDatabasePath();
      final first = realDatabase(path);
      await AppController(
        database: first,
        backupService: TempBackupService(),
      ).initialize(); // イベント名の初期値を保存しておく
      await first.close();

      final db = FaultyDatabase(path)..failLoad = true;
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await expectLater(app.initialize(), throwsStateError);
      expect(app.startupChanges, isEmpty);
      expect(
        startupFailureText(app.startupChanges, StateError('x')),
        startsWith('起動できませんでした。記録は変更していません。'),
      );
      await db.close();
    });

    test('後回しにできる片付けの失敗では起動を止めず、注意を出す', () async {
      final db = FaultyDatabase(await newDatabasePath())..failCleanup = true;
      await db.applyChanges(
        ChangeSet(
          upserts: [
            SlotRecord(
              store: 'nagamachiminami',
              day: '2026-09-25',
              machine: 'テスト',
              rack: 1,
              games: 3000,
              bb: 10,
              rb: 5,
            ),
          ],
        ),
      );
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await app.initialize();
      expect(app.records.map((r) => r.rack), [1]);
      expect(
        app.startupWarnings.single,
        contains('古い記録の片付けができませんでした。記録はそのままです'),
      );
      await db.close();
    });
  });

  group('起動時の機種名の統一と、変更の説明', () {
    final png = Uint8List.fromList(List.generate(40, (i) => 255 - i));
    SlotRecord slot(int rack, String machine, {bool image = false, String? setting}) =>
        SlotRecord(
          store: 'nagamachiminami',
          day: '2026-09-25',
          machine: machine,
          rack: rack,
          games: 3000 + rack,
          bb: 10,
          rb: 5,
          maxHold: 1200,
          confirmedSetting: setting,
          graph: image
              ? GraphMeasurement(
                  baselineY: 200,
                  peakY: 80,
                  troughY: 210,
                  endY: 120,
                  previewPng: png,
                  previewWidth: 120,
                  previewHeight: 300,
                  curve: const [
                    [1, 200],
                    [2, 120],
                  ],
                )
              : null,
        );

    /// 表記ゆれ（`テ+スト`）の台が2台あるDB。1番台は、そろえた名前の台
    /// （設定の記録あり）と画像付きの表記ゆれの台の2つに分かれている。
    /// イベント名・設定情報・翌日候補の記録も入れておく。
    Future<({String path, String? events})> seeded() async {
      final path = await newDatabasePath();
      final db = realDatabase(path);
      await AppController(
        database: db,
        backupService: TempBackupService(),
      ).initialize(); // イベント名の初期値を保存しておく
      final plain = [slot(1, 'テ スト', setting: '6')];
      await db.applyChanges(
        ChangeSet(
          upserts: [
            ...plain,
            slot(1, 'テ+スト', image: true),
            slot(2, 'テ+スト', image: true),
          ],
          snapshots: [
            candidateSnapshot(
              store: 'nagamachiminami',
              day: '2026-09-25',
              machine: 'テ スト',
              all: plain,
              now: DateTime(2026, 9, 25, 23),
            ),
          ],
          state: {'test_setting': 'keep'},
        ),
      );
      final events = (await db.loadState())['date_events'];
      await db.close();
      return (path: path, events: events);
    }

    Future<void> expectKept(DatabaseService db, String? events) async {
      final state = await db.loadState();
      expect(state['date_events'], events);
      expect(state['test_setting'], 'keep');
      expect(await db.loadCandidateSnapshots(), hasLength(1));
    }

    test('機種名をそろえた後の読み直しだけ失敗したら、そろえたことを説明する', () async {
      final seed = await seeded();
      final db = FaultyDatabase(seed.path)..failLoadAfterNormalize = true;
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await expectLater(app.initialize(), throwsStateError);
      expect(app.startupChanges, [
        '機種名の表記ゆれがある2台を、そろえた名前の台へまとめました'
            '（グラフの画像・設定の記録は残しています）。',
      ]);
      final text = startupFailureText(app.startupChanges, StateError('読めません'));
      expect(text, startsWith('起動できませんでした。起動の途中で、次のことだけは済んでいます'));
      expect(text, contains('・機種名の表記ゆれがある2台を'));
      expect(text, isNot(startsWith('起動できませんでした。記録は変更していません')));
      await db.close();

      // DBの実際：そろえた名前の台だけになり、画像・設定の記録・イベント・
      // 設定情報・翌日候補の記録は残っている（説明と一致する）。
      final check = realDatabase(seed.path);
      final rows = {for (final r in await fullRows(check)) r.rack: r};
      expect(rows.values.map((r) => r.machine).toSet(), {'テ スト'});
      expect(rows.keys.toSet(), {1, 2});
      expect(rows[1]!.confirmedSetting, '6');
      expect(rows[1]!.graph!.previewPng, png);
      expect(rows[2]!.graph!.previewPng, png);
      await expectKept(check, seed.events);
      await check.close();
    });

    test('そろえる処理が失敗して元に戻ったら、済んだことにしない', () async {
      final seed = await seeded();
      final db = realDatabase(seed.path);
      // そろえた名前の2番台を書くときだけ失敗させる（まとめた書き込みごと戻る）。
      await (await db.database).execute(
        'CREATE TRIGGER fail BEFORE INSERT ON records '
        "WHEN NEW.machine = 'テ スト' AND NEW.rack = 2 "
        "BEGIN SELECT RAISE(ABORT, 'disk failure'); END",
      );
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await expectLater(app.initialize(), throwsA(anything));
      expect(app.startupChanges, isEmpty);
      expect(
        startupFailureText(app.startupChanges, StateError('x')),
        startsWith('起動できませんでした。記録は変更していません。'),
      );
      // DBの実際：表記ゆれの台は元のまま（画像も残っている）。
      final rows = await fullRows(db);
      expect(
        rows.map((r) => (r.machine, r.rack)).toSet(),
        {('テ スト', 1), ('テ+スト', 1), ('テ+スト', 2)},
      );
      expect(
        rows.where((r) => r.machine == 'テ+スト').every((r) => r.graph!.previewPng != null),
        isTrue,
      );
      await expectKept(db, seed.events);
      await db.close();
    });

    test('起動し直すと前の説明は残らず、引っ張って更新の統一は起動の説明に入れない', () async {
      final seed = await seeded();
      final db = realDatabase(seed.path);
      final app = AppController(
        database: db,
        backupService: TempBackupService(),
      );
      await app.initialize();
      expect(app.startupChanges, hasLength(1));
      await app.initialize(); // もうそろえる台は無い
      expect(app.startupChanges, isEmpty);

      await db.applyChanges(ChangeSet(upserts: [slot(3, 'テ+スト')]));
      await app.reload();
      expect(app.startupChanges, isEmpty);
      expect(app.records.map((r) => (r.machine, r.rack)).toSet(), {
        ('テ スト', 1),
        ('テ スト', 2),
        ('テ スト', 3),
      });
      await expectKept(db, seed.events);
      await db.close();
    });
  });
}
