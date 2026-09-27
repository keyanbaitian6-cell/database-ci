// 2026-09-28：時間を超えた書き込みの追跡（⑥）と、起動の途中で済んだ変更の
// 説明（⑦）のテスト。
import 'dart:async';
import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
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

  @override
  Future<List<SlotRecord>> loadAll() =>
      failLoad ? Future.error(StateError('読めません')) : super.loadAll();

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
}
