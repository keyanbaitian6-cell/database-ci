import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/models.dart';
import 'package:database_android/record_deletions.dart';

import 'support/real_database.dart';

SlotRecord record(int rack) => SlotRecord(
  store: 'saiwaichou',
  day: '2026-10-14',
  machine: '試験',
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
  capturedAt: '2026-10-14T23:00:00+09:00',
);

Future<File> file() async {
  final dir = await Directory.systemTemp.createTemp('deletion-test-');
  addTearDown(() => dir.delete(recursive: true));
  return File('${dir.path}/backup.json');
}

class TestBackup extends BackupService {
  @override
  Future<File> newBackupFile({String source = 'android'}) => file();
}

void main() {
  test('端末の削除をバックアップに保持し、古い入力を拒否、明示復元を許可', () async {
    final db = realDatabase(await newDatabasePath());
    addTearDown(db.close);
    await db.applyChanges(ChangeSet(upserts: [record(537)]));
    final old = await file();
    await db.exportBackup(old);
    await db.applyChanges(ChangeSet(deleteKeys: [record(537).key]));
    final deleted = await file();
    await db.exportBackup(deleted);
    final chunks = await BackupService().readBackupFile(deleted).toList();
    expect(chunks.expand((c) => c.deletions).single.rack, 537);
    final controller = AppController(database: db, backupService: TestBackup())
      ..today = () => '2026-10-15';
    await controller.initialize();
    final result = await controller.importBackup(old);
    expect(result.skipped, 1);
    expect(await db.loadAll(), isEmpty);
    expect(controller.records, isEmpty);
    await db.applyChanges(ChangeSet(upserts: [record(537)]));
    final restored = (await fullRows(db)).single;
    expect(restored.extra['record_updated_at'], isNotNull);
    expect(
      recordSurvivesDeletion(
        restored.toJson(),
        mergeRecordDeletions(chunks.expand((c) => c.deletions)),
      ),
      isTrue,
    );
  });

  test('PCの最後の1台の削除を取り込み、別の台と新しい復元を維持する', () async {
    final db = realDatabase(await newDatabasePath());
    addTearDown(db.close);
    await db.applyChanges(ChangeSet(upserts: [record(537), record(538)]));
    final controller = AppController(database: db, backupService: TestBackup())
      ..today = () => '2026-10-15';
    await controller.initialize();
    final mark = deletionForRecord(record(537));
    final input = await file();
    await input.writeAsString(
      jsonEncode({
        'format': 'database-backup',
        'version': 1,
        'source': 'pc',
        'record_deletions': [mark.toJson()],
        'records': [],
      }),
    );
    await controller.importBackup(input);
    expect((await db.loadAll()).map((r) => r.rack), [538]);
    expect(controller.records.map((r) => r.rack), [538]);
    final out = await file();
    await db.exportBackup(out);
    expect(
      (await BackupService().readBackupFile(out).toList())
          .expand((c) => c.deletions)
          .single
          .key,
      mark.key,
    );
    final restored = restoreDeletedRecord(record(537), mark);
    await input.writeAsString(
      jsonEncode({
        'format': 'database-backup',
        'version': 1,
        'records': [restored.toJson()],
      }),
    );
    await controller.importBackup(input);
    expect((await db.loadAll()).map((r) => r.rack).toSet(), {537, 538});
  });

  test('末尾にある不正な削除情報でも全体を取り消す', () async {
    final db = realDatabase(await newDatabasePath());
    addTearDown(db.close);
    final controller = AppController(database: db, backupService: TestBackup())
      ..today = () => '2026-10-15';
    await controller.initialize();
    final input = await file();
    await input.writeAsString(
      '{"format":"database-backup","version":1,"records":[\n${[for (var i = 1; i <= 301; i++) jsonEncode(record(i).toJson())].join(',\n')}\n],"record_deletions":[{"deleted_at":"bad"}]}',
    );
    await expectLater(controller.importBackup(input), throwsFormatException);
    expect(await db.loadAll(), isEmpty);
    expect((await db.loadState())['record_deletions'], isNull);
  });
}
