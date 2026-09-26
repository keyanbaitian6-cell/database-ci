import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'support/real_database.dart';

final png = Uint8List.fromList(List.generate(40, (i) => 255 - i));

SlotRecord rec(int rack, {bool image = false, String machine = 'テスト'}) =>
    SlotRecord(
      store: 'nagamachiminami',
      day: '2026-09-25',
      machine: machine,
      rack: rack,
      games: 3000 + rack,
      bb: 10,
      rb: 5,
      maxHold: 1200,
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
      firstCapturedAt: '2026-09-25T23:00:00.000+09:00',
    );

Future<File> tempFile(String name) async {
  final dir = await Directory.systemTemp.createTemp('backup_test');
  return File(p.join(dir.path, name));
}

void main() {
  test('版3のDB（画像が本体の中）を開くと、画像を別の列へ移して中身は変えない', () async {
    final path = await newDatabasePath();
    final full = rec(1, image: true).copyWith(extra: {'future_field': 1});
    final old = await databaseFactoryFfi.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: 3,
        onCreate: (db, _) async {
          await db.execute(
            'CREATE TABLE records (record_key TEXT PRIMARY KEY, store TEXT NOT NULL, '
            'day TEXT NOT NULL, machine TEXT NOT NULL, rack INTEGER NOT NULL, '
            'payload TEXT NOT NULL, updated_at TEXT NOT NULL)',
          );
          await db.execute(
            'CREATE TABLE app_state (state_key TEXT PRIMARY KEY, value TEXT NOT NULL)',
          );
          await db.execute(
            'CREATE TABLE candidate_snapshots (store TEXT NOT NULL, day TEXT NOT NULL, '
            'machine TEXT NOT NULL, taken_at TEXT NOT NULL, payload TEXT NOT NULL, '
            'PRIMARY KEY (store, day, machine, taken_at))',
          );
        },
      ),
    );
    await old.insert('records', {
      'record_key': full.key,
      'store': full.store,
      'day': full.day,
      'machine': full.machine,
      'rack': full.rack,
      'payload': full.encode(),
      'updated_at': 'x',
    });
    await old.insert('app_state', {
      'state_key': 'initial_seeded',
      'value': '1',
    });
    await old.close();

    final db = realDatabase(path);
    final light = (await db.loadAll()).single;
    expect(light.graph!.previewPng, isNull);
    expect(light.graph!.curve, isNull);
    expect(light.graph!.hasPreview, isTrue);
    expect(await db.loadPreview(full.key), png);
    expect((await fullRows(db)).single.encode(), full.encode());
    expect(await db.loadTrash(), isEmpty); // ゴミ箱の表もできている
    await db.close();
  });

  test('画像を読み込んでいない台を保存しても、画像と曲線は残る。グラフを外せば消える', () async {
    final db = realDatabase(await newDatabasePath());
    final full = rec(2, image: true);
    await db.applyChanges(ChangeSet(upserts: [full]));
    final light = (await db.loadAll()).single;
    await db.applyChanges(
      ChangeSet(upserts: [light.copyWith(confirmedSetting: '6')]),
    );
    final back = (await fullRows(db)).single;
    expect(back.confirmedSetting, '6');
    expect(back.graph!.previewPng, png);
    expect(back.graph!.curve, isNotNull);
    await db.applyChanges(
      ChangeSet(
        upserts: [
          SlotRecord.fromJson({...back.toJson()..remove('graph_measurement')}),
        ],
      ),
    );
    expect((await fullRows(db)).single.graph, isNull);
    expect(await db.loadPreview(full.key), isNull);
    await db.close();
  });

  test('バックアップは1行1台で書き出し、PC版と同じ1つのJSONとしても読める', () async {
    final db = realDatabase(await newDatabasePath());
    final records = [rec(1, image: true), rec(2), rec(3, image: true)];
    await db.applyChanges(ChangeSet(upserts: records));
    final snapshot = candidateSnapshot(
      store: 'nagamachiminami',
      day: '2026-09-25',
      machine: 'テスト',
      all: records,
      now: DateTime(2026, 9, 25, 23),
    );
    final file = await tempFile('b.json');
    final count = await db.exportBackup(file, candidates: [snapshot]);
    expect(count, 3);
    final whole = jsonDecode(await file.readAsString()) as Map;
    expect(whole['format'], backupFormat);
    expect(whole['records'], hasLength(3));
    expect((whole['candidate_snapshots'] as List), hasLength(1));
    // 画像は別の列から戻して、元の形（preview_image）で書く。
    final first = (whole['records'] as List).first as Map;
    expect((first['graph_measurement'] as Map)['preview_image'], isNotNull);
    expect(
      (first['graph_measurement'] as Map),
      isNot(contains('preview_stored')),
    );

    final chunks = await BackupService()
        .readBackupFile(file, chunkSize: 2)
        .toList();
    expect([for (final c in chunks) c.records.length], [2, 1]);
    expect(chunks.last.candidates.single.signature, snapshot.signature);
    await db.close();
  });

  test('書き出したバックアップを別の端末に取り込むと、画像ごと同じになる', () async {
    final from = realDatabase(await newDatabasePath());
    final records = [
      rec(1, image: true).copyWith(extra: {'future_field': 'x'}),
      rec(2),
    ];
    await from.applyChanges(ChangeSet(upserts: records));
    final file = await tempFile('b.json');
    await from.exportBackup(file);

    final to = realDatabase(await newDatabasePath());
    final app = AppController(database: to);
    await app.initialize();
    final result = await app.importBackup(file);
    expect(result.added, 2);
    expect(
      [for (final r in await fullRows(to)) r.encode()]..sort(),
      [for (final r in records) r.encode()]..sort(),
    );
    // 取り込みの取り消しで、足した台は消える。
    await app.undoLastSave();
    expect(await to.loadAll(), isEmpty);
    await from.close();
    await to.close();
  });

  test('PC版の書き出し（1行1台・空白入りの見出し）を1行ずつ読める', () async {
    final file = await tempFile('pc.json');
    await file.writeAsString(
      '{"format": "database-backup", "version": 1, "exported_at": "x", "source": "pc", "records": [\n'
      '${jsonEncode(rec(1).toJson())},\n'
      '${jsonEncode(rec(2).copyWith(machine: 'テ+スト').toJson())}\n'
      ']}',
    );
    final chunks = await BackupService().readBackupFile(file).toList();
    final plan = BackupService().plan(chunks.first.records, const []);
    expect(plan.added.map((r) => r.machine).toSet(), {'テスト', 'テ スト'});
  });

  test('以前の1行だけの形は丸ごと読み、上限を超える大きさなら止める', () async {
    final file = await tempFile('old.json');
    await file.writeAsString(
      jsonEncode(BackupService().backupPayload([rec(1), rec(2)])),
    );
    final chunks = await BackupService().readBackupFile(file).toList();
    expect(chunks.first.records, hasLength(2));
    await expectLater(
      BackupService().readBackupFile(file, wholeFileLimit: 10).toList(),
      throwsFormatException,
    );
  });

  test('形式の違うファイルは読まない', () async {
    final file = await tempFile('bad.json');
    await file.writeAsString('{"format": "other", "records": [\n{}\n]}');
    await expectLater(
      BackupService().readBackupFile(file).toList(),
      throwsFormatException,
    );
  });

  test('機種名の表記ゆれをDBの側で画像込みにまとめる', () async {
    final db = realDatabase(await newDatabasePath());
    await db.applyChanges(
      ChangeSet(
        upserts: [
          rec(5, image: true, machine: 'A+B'),
          rec(5, machine: 'A B').copyWith(confirmedSetting: '6'),
        ],
      ),
    );
    expect(await db.normalizeMachineNames(), 1);
    final rows = await fullRows(db);
    expect(rows.single.machine, 'A B');
    expect(rows.single.confirmedSetting, '6');
    expect(rows.single.graph!.previewPng, png);
    expect(await db.normalizeMachineNames(), 0);
    await db.close();
  });

  test('ゴミ箱には画像込みで入り、古いものは消せる', () async {
    final db = realDatabase(await newDatabasePath());
    final full = rec(9, image: true);
    await db.applyChanges(ChangeSet(upserts: [full]));
    await db.applyChanges(
      ChangeSet(
        deleteKeys: [full.key],
        trashKeys: [full.key],
        trashLabel: 'テスト削除',
      ),
    );
    final batch = (await db.loadTrash()).single;
    expect(batch.label, 'テスト削除');
    final entry = (await db.loadTrashBatch(batch.batchId)).single;
    expect(entry.record.encode(), full.encode());
    await db.purgeTrash(DateTime.now().add(const Duration(minutes: 1)));
    expect(await db.loadTrash(), isEmpty);
    await db.close();
  });

  SlotRecord onDay(String day, int rack) =>
      rec(rack)
          .copyWith(day: day, firstCapturedAt: '${day}T23:00:00.000+09:00');

  test('60日より古い台は、全期間バックアップの後に保存済みだったものだけ片付ける', () async {
    final db = realDatabase(await newDatabasePath());
    await db.applyChanges(
      ChangeSet(
        upserts: [
          onDay('2026-11-30', 1), // 最新の日
          onDay('2026-10-02', 2), // 残す最初の日（60日目）
          onDay('2026-10-01', 3), // 61日前：片付けの対象
        ],
      ),
    );
    // まだ書き出していなければ、何も消さない。
    var result = await db.cleanupOldRecords(null);
    expect((result.deleted, result.kept, result.cutoff), (0, 1, '2026-10-02'));
    // 書き出しの後に保存し直した台は、まだバックアップに入っていないので残す。
    result = await db.cleanupOldRecords(
      DateTime.now().subtract(const Duration(days: 1)),
    );
    expect(result.deleted, 0);
    // 書き出しより前に保存した台だけ消える。
    result = await db.cleanupOldRecords(
      DateTime.now().add(const Duration(minutes: 1)),
    );
    expect(result.deleted, 1);
    expect([for (final r in await db.loadAll()) r.rack]..sort(), [1, 2]);
    await db.close();
  });

  test('保存期間より古い台をバックアップから読み込むと、次の起動時に片付ける', () async {
    final from = realDatabase(await newDatabasePath());
    await from.applyChanges(
      ChangeSet(upserts: [onDay('2026-08-01', 7), onDay('2026-11-29', 8)]),
    );
    final file = await tempFile('b.json');
    await from.exportBackup(file);

    final path = await newDatabasePath();
    var db = realDatabase(path);
    await db.applyChanges(ChangeSet(upserts: [onDay('2026-11-30', 1)]));
    var app = AppController(database: db);
    await app.initialize();
    final result = await app.importBackup(file);
    expect(result.temporary, 1);
    expect(app.records.map((r) => r.rack), containsAll([1, 7, 8]));
    await db.close();

    db = realDatabase(path); // アプリを開き直す
    app = AppController(database: db);
    await app.initialize();
    expect([for (final r in app.records) r.rack]..sort(), [1, 8]);
    expect(app.retentionNotice, contains('1台を端末から片付けました'));
    await from.close();
    await db.close();
  });

  test('全期間バックアップを3日書き出していないと注意を出す', () {
    final now = DateTime(2026, 9, 30, 12);
    expect(backupReminderText(null, false, now), isNull); // 記録が無い
    expect(backupReminderText(null, true, now), contains('まだ全期間'));
    expect(backupReminderText(DateTime(2026, 9, 28, 23), true, now), isNull);
    expect(
      backupReminderText(DateTime(2026, 9, 27, 1), true, now),
      contains('3日'),
    );
  });
}
