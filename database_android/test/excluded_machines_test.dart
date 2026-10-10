import 'dart:convert';

import 'package:database_android/app_controller.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/excluded_machines.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

// 対象外の機種（2026-10-11 利用者「1279番台の聖闘士星矢ってずっと稼働停止なので取り込まない、
// 表示しないようにしてほしい」）。PC版 tests/test_excluded_machines.py と同じ規則。

const seiya = 'L聖闘士星矢海皇覚醒ED';

SlotRecord rec(String machine, int rack, {String store = 'saiwaichou'}) =>
    SlotRecord(
      store: store,
      day: '2026-10-09',
      machine: machine,
      rack: rack,
      games: 300,
      bb: 1,
      rb: 0,
    );

void main() {
  test('幸町の聖闘士星矢 海皇覚醒だけを対象外にする（これまでの対象外もそのまま）', () {
    for (final name in [seiya, 'L 聖闘士星矢 海皇覚醒 ED', 'L聖闘士星矢　海皇覚醒ED']) {
      expect(isExcludedMachine('saiwaichou', name), isTrue, reason: name);
    }
    expect(isExcludedMachine('nagamachiminami', seiya), isFalse);
    expect(isExcludedMachine('saiwaichou', 'S聖闘士星矢 冥王復活'), isFalse);
    expect(isExcludedMachine('saiwaichou', 'Sブラックボード'), isTrue);
    expect(isExcludedMachine('nagamachiminami', 'S/沖ﾄﾞｷ!GOLD/LS'), isTrue);
    expect(excludedMachineNotes['saiwaichou'], contains('聖闘士星矢'));
    // 表示しないのは聖闘士星矢だけ。沖ドキなど、対象外にする前に取り込んだ記録は今までどおり出す。
    expect(isHiddenMachine('saiwaichou', 'L 聖闘士星矢 海皇覚醒 ED'), isTrue);
    expect(isHiddenMachine('saiwaichou', 'L／オキドキデュオ2／FR'), isFalse);
    expect(isHiddenMachine('nagamachiminami', 'S/沖ﾄﾞｷ!GOLD/LS'), isFalse);
  });

  test('閲覧ページ：古い閲覧用ファイルに残っていても出さない', () {
    final data = ViewerData.parse(
      jsonEncode({
        'header': {'format': 'database-backup', 'version': 1},
        'records': [
          for (final r in [
            rec(seiya, 1279),
            rec('Lモンキーターン5CE', 722),
            rec('L／オキドキデュオ2／FR', 900),
          ])
            r.toJson(),
        ],
      }),
    );
    expect([for (final r in data.records) r.rack]..sort(), [722, 900]);
  });

  test('Android：以前に保存した記録は消さずに、画面の一覧から外す', () async {
    final db = realDatabase(await newDatabasePath());
    await db.applyChanges(
      ChangeSet(
        upserts: [
          rec(seiya, 1279),
          rec('Lモンキーターン5CE', 722),
          rec('L／オキドキデュオ2／FR', 900),
        ],
      ),
    );
    final c = AppController(database: db);
    await c.initialize();
    expect([for (final r in c.records) r.rack]..sort(), [722, 900]);
    expect((await db.loadAll()).length, 3, reason: '記録は消さない');
  });
}
