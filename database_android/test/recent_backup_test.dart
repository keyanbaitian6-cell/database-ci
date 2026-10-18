import 'dart:io';

import 'package:database_android/backup_service.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
