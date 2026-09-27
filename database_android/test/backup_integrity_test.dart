import 'dart:convert';
import 'dart:io';

import 'package:database_android/app_controller.dart';
import 'package:database_android/backup_service.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/date_events.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/real_database.dart';

SlotRecord rec(int rack) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-26',
  machine: 'テスト',
  rack: rack,
  games: 3000,
  bb: 10,
  rb: 5,
  maxHold: 1200,
);

class TempBackup extends BackupService {
  @override
  Future<File> newBackupFile({String source = 'android'}) async => tempFile();
}

Future<File> tempFile() async {
  final dir = await Directory.systemTemp.createTemp('backup_integrity_');
  addTearDown(() => dir.delete(recursive: true));
  return File('${dir.path}/backup.json');
}

String lineFile(List<SlotRecord> records, {String ending = ']}'}) =>
    '{"format":"database-backup","version":1,"source":"android","records":[\n'
    '${records.map((r) => jsonEncode(r.toJson())).join(',\n')}\n$ending';

void main() {
  final service = BackupService();

  group('文書の完全性', () {
    for (final ending in ['', ']', ']}junk', ']}\n{}', ',]}']) {
      test('不完全または余分な末尾 ${jsonEncode(ending)} を拒否する', () async {
        final file = await tempFile();
        await file.writeAsString(lineFile([rec(1)], ending: ending));
        await expectLater(
          service.readBackupFile(file).toList(),
          throwsFormatException,
        );
      });
    }

    test('行間のカンマ不足を拒否する', () async {
      final file = await tempFile();
      await file.writeAsString(
        lineFile([rec(1), rec(2)]).replaceFirst('},\n', '}\n'),
      );
      await expectLater(
        service.readBackupFile(file).toList(),
        throwsFormatException,
      );
    });

    test('正常な空配列・CRLF・文字列内の括弧と改行は読める', () async {
      final file = await tempFile();
      await file.writeAsString(lineFile([]).replaceAll('\n', '\r\n'));
      expect(
        (await service.readBackupFile(file).toList()).single.records,
        isEmpty,
      );
      final record = rec(1).copyWith(machine: 'テスト ]} ",\n [');
      await file.writeAsString(lineFile([record]).replaceAll('\n', '\r\n'));
      final chunks = await service.readBackupFile(file).toList();
      expect(chunks.single.records.single['machine'], record.machine);
    });

    test('300台を超えて読み進めた後の欠損でもDB・イベントは変更しない', () async {
      final db = realDatabase(await newDatabasePath());
      addTearDown(db.close);
      final app = AppController(database: db);
      app.today = () => '2026-09-27';
      await app.initialize();
      await db.applyChanges(ChangeSet(upserts: [rec(999)]));
      final before = await db.loadState();
      final file = await tempFile();
      await file.writeAsString(
        lineFile([for (var i = 1; i <= 301; i++) rec(i)], ending: ''),
      );
      await expectLater(app.importBackup(file), throwsFormatException);
      expect((await db.loadAll()).map((r) => r.rack), [999]);
      expect(await db.loadState(), before);
    });
  });

  group('書式に依存しないヘッダー検証', () {
    for (final layout in ['compact', 'pretty', 'lines']) {
      for (final entry in <String, Object?>{
        'format': 'other',
        'version': 99,
        'source': 'pc-viewer',
      }.entries) {
        test('$layout の不正な ${entry.key} を拒否する', () async {
          final payload = service.backupPayload([rec(1)])
            ..[entry.key] = entry.value;
          final text = switch (layout) {
            'pretty' => const JsonEncoder.withIndent('  ').convert(payload),
            'lines' =>
              '${jsonEncode(Map.of(payload)..remove('records')).replaceFirst(RegExp(r'}$'), '')},"records":[\n${jsonEncode(rec(1).toJson())}\n]}',
            _ => jsonEncode(payload),
          };
          final file = await tempFile();
          await file.writeAsString(text);
          await expectLater(
            service.readBackupFile(file).toList(),
            throwsFormatException,
          );
          expect(() => service.planFromJson(text, []), throwsFormatException);
        });
      }
    }

    test('候補ログの閉じ括弧欠損を拒否する', () async {
      final file = await tempFile();
      final candidate = candidateSnapshot(
        store: rec(1).store,
        day: rec(1).day,
        machine: rec(1).machine,
        all: [rec(1)],
        now: DateTime(2026, 9, 26, 23),
      );
      await file.writeAsString(
        lineFile(
          [rec(1)],
          ending:
              '], "candidate_snapshots": [\n${jsonEncode(candidate.toJson())}\n]',
        ),
      );
      await expectLater(
        service.readBackupFile(file).toList(),
        throwsFormatException,
      );
    });

    test('整形されたPCバックアップのイベント・候補を保持する', () async {
      final candidate = candidateSnapshot(
        store: rec(1).store,
        day: rec(1).day,
        machine: rec(1).machine,
        all: [rec(1)],
        now: DateTime(2026, 9, 26, 23),
      );
      final payload = service.backupPayload(
        [rec(1)],
        source: 'pc',
        candidates: [candidate],
        events: [DateEvent(store: rec(1).store, day: rec(1).day, name: '華の日')],
      );
      final file = await tempFile();
      await file.writeAsString(
        const JsonEncoder.withIndent('  ').convert(payload),
      );
      final chunks = await service.readBackupFile(file).toList();
      expect(chunks.expand((c) => c.records), hasLength(1));
      expect(
        chunks.expand((c) => c.candidates).single.toJson(),
        candidate.toJson(),
      );
      expect(chunks.expand((c) => c.events).single.name, '華の日');
    });
  });

  group('救出用の元データを落とさない', () {
    for (final eventPayload in [
      '{broken events',
      '{"not":"a list"}',
      '[{"name":"invalid"}]',
    ]) {
      test('通常・非常用とも壊れたイベントを原文で残す $eventPayload', () async {
        final db = realDatabase(await newDatabasePath());
        addTearDown(db.close);
        await db.applyChanges(
          ChangeSet(upserts: [rec(1)], state: {'date_events': eventPayload}),
        );
        for (final emergency in [false, true]) {
          final file = await tempFile();
          final result = emergency
              ? await db.exportRaw(file)
              : await db.exportBackup(file);
          expect(result.unreadable, 1);
          expect(result.events, 0);
          final payload = jsonDecode(await file.readAsString());
          expect(payload['unreadable_date_events'], eventPayload);
          expect(payload['recovery_required'], 1);
          await expectLater(
            service.readBackupFile(file).toList(),
            throwsFormatException,
          );
        }
        expect((await db.loadState())['date_events'], eventPayload);
      });
    }

    test('壊れた台の本体・画像と、構文不正／形違いの候補ログをすべて残す', () async {
      final db = realDatabase(await newDatabasePath());
      addTearDown(db.close);
      await db.applyChanges(ChangeSet(upserts: [rec(1), rec(2)]));
      final raw = await db.database;
      await raw.update(
        'records',
        {'payload': '{broken', 'graph_blob': 'original-image-data'},
        where: 'record_key = ?',
        whereArgs: [rec(2).key],
      );
      for (final entry in ['{broken candidate', '{"invalid":true}'].indexed) {
        await raw.insert('candidate_snapshots', {
          'store': rec(1).store,
          'day': rec(1).day,
          'machine': rec(1).machine,
          'taken_at': '2026-09-26T23:00:0${entry.$1}',
          'payload': entry.$2,
        });
      }
      final file = await tempFile();
      final result = await db.exportBackup(file);
      expect((result.records, result.candidates, result.unreadable), (2, 0, 3));
      final payload = jsonDecode(await file.readAsString());
      final rescued = (payload['records'] as List).last;
      expect(rescued['unreadable_record'], '{broken');
      expect(rescued['graph_blob'], 'original-image-data');
      expect(
        (payload['candidate_snapshots'] as List).map(
          (c) => c['unreadable_candidate_snapshot'],
        ),
        ['{broken candidate', '{"invalid":true}'],
      );
      expect(payload['recovery_required'], 3);
      await expectLater(
        service.readBackupFile(file).toList(),
        throwsFormatException,
      );
      expect(await raw.query('candidate_snapshots'), hasLength(2));
    });

    test('救出用ファイルを保存してもバックアップ済みの印を進めない', () async {
      final db = realDatabase(await newDatabasePath());
      addTearDown(db.close);
      final app = AppController(database: db, backupService: TempBackup());
      await app.initialize();
      await db.applyChanges(const ChangeSet(state: {'date_events': '{broken'}));
      final stateBefore = await db.loadState();
      final exported = await app.exportBackup();
      expect(exported.unreadable, 1);
      await expectLater(app.confirmBackupSaved(exported), throwsStateError);
      expect(app.lastFullBackupExport, isNull);
      expect(await db.loadState(), stateBefore);
    });

    test('イベントのDB読取失敗は正常な出力として扱わない', () async {
      final db = realDatabase(await newDatabasePath());
      addTearDown(db.close);
      await (await db.database).execute('DROP TABLE app_state');
      await expectLater(
        db.exportBackup(await tempFile()),
        throwsA(isA<Exception>()),
      );
    });
  });
}
