import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

/// PCが書き出す「直近7日分」のバックアップ（database-backup-recent.json、2026-10-18）を、
/// 全期間のバックアップと同じように読み込めること。今ある記録は消さずに足し合わせる。
void main() {
  test('直近7日分のバックアップを読み込める（見出しの since は無視してよい）', () {
    final text = File(
      '../database/tests/fixtures/recent_backup.json',
    ).readAsStringSync();
    final service = BackupService();
    const older = SlotRecord(
      store: 'saiwaichou',
      day: '2026-10-02',
      machine: 'SマイジャグラーVKD',
      rack: 700,
      games: 4000,
      bb: 15,
      rb: 12,
    );
    final plan = service.planFromJson(text, [older]);
    expect(plan.added.length, 14);
    expect(plan.added.every((r) => r.day.compareTo('2026-10-04') >= 0), isTrue);
    expect(plan.conflicts, isEmpty);
  });

  // 2026-11-08 保存とバックアップのレビュー4：PCで最後の台まで消すと、記録0件・削除印付きの
  // 直近版を書く（見本はPCの試験 test_backup_review_20261108.py が同じ形かを確かめている）。
  test('PCが全件削除のあとに書く空の直近版から、端末の台も消える', () async {
    final db = realDatabase(await newDatabasePath());
    addTearDown(db.close);
    const kept = SlotRecord(
      store: 'saiwaichou',
      day: '2026-10-22',
      machine: '試験',
      rack: 538,
      games: 3000,
      bb: 10,
      rb: 5,
      capturedAt: '2026-10-22T23:00:00+09:00',
    );
    await db.applyChanges(
      ChangeSet(
        upserts: [
          const SlotRecord(
            store: 'saiwaichou',
            day: '2026-10-22',
            machine: '試験',
            rack: 537,
            games: 3000,
            bb: 10,
            rb: 5,
            capturedAt: '2026-10-22T23:00:00+09:00',
          ),
          kept,
        ],
      ),
    );
    final controller = AppController(
      database: db,
      backupService: BackupService(),
    )..today = () => '2026-11-08';
    await controller.initialize();
    final sample = File(
      '../database/tests/fixtures/recent_backup_after_delete_all.json',
    );
    final chunks = await BackupService().readBackupFile(sample).toList();
    expect(chunks.expand((c) => c.records), isEmpty);
    expect(chunks.expand((c) => c.deletions).single.rack, 537);
    await controller.importBackup(sample);
    expect((await db.loadAll()).map((r) => r.rack), [538]);
  });
}
