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

class CountingBackupFile implements File {
  CountingBackupFile(this.file);

  final File file;
  var bytesRead = 0;

  @override
  Future<int> length() => file.length();

  @override
  Stream<List<int>> openRead([int? start, int? end]) async* {
    await for (final block in file.openRead(start, end)) {
      bytesRead += block.length;
      yield block;
    }
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
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

  group('復元前の形式・容量の判定', () {
    test('上限以下の改行なし旧形式は従来どおり読める', () async {
      final file = await tempFile();
      await file.writeAsString(jsonEncode(service.backupPayload([rec(1)])));
      final chunks = await service
          .readBackupFile(file, wholeFileLimit: await file.length())
          .toList();
      expect(chunks.single.records.single, rec(1).toJson());
    });

    test('上限を超える改行なし旧形式は先頭の限られたバイトだけで拒否する', () async {
      final file = await tempFile();
      await file.writeAsString(
        jsonEncode(
          service.backupPayload([
            rec(1).copyWith(extra: {'test_data': 'あ' * 4096}),
          ]),
        ),
      );
      final measured = CountingBackupFile(file);
      const limit = 256;
      expect(await file.length(), greaterThan(4096));
      await expectLater(
        service.readBackupFile(measured, wholeFileLimit: limit).toList(),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('メモリ不足'),
          ),
        ),
      );
      expect(measured.bytesRead, lessThanOrEqualTo(limit));
    });

    test('長いイベント見出しを含む64MiB超の1台1行形式は分割して読める', () async {
      final file = await tempFile();
      final originalEvents = [
        for (var i = 0; i < 1200; i++)
          DateEvent(
            store: rec(1).store,
            day: DateTime(2023, 1, i + 1).toIso8601String().substring(0, 10),
            name: '試験' * 20,
          ),
      ];
      final testData = 'x' * (256 * 1024);
      final header = jsonEncode({
        'format': backupFormat,
        'version': backupVersion,
        'source': 'pc',
        'date_events': [for (final event in originalEvents) event.toJson()],
      });
      final sink = file.openWrite();
      try {
        sink.write(
          '\ufeff\r\n${header.substring(0, header.length - 1)}, "records": [\r\n',
        );
        for (var rack = 1; rack <= 256; rack++) {
          sink.write(
            jsonEncode(
              rec(rack).copyWith(extra: {'test_data': testData}).toJson(),
            ),
          );
          sink.write(rack == 256 ? '\r\n]}' : ',\r\n');
          if (rack % 8 == 0) await sink.flush();
        }
      } finally {
        await sink.close();
      }
      expect(utf8.encode(header).length, greaterThan(128 * 1024));
      expect(await file.length(), greaterThan(wholeBackupLimitBytes));
      final racks = <int>[];
      final events = <DateEvent>[];
      await for (final chunk in service.readBackupFile(file, chunkSize: 8)) {
        expect(chunk.records.length, lessThanOrEqualTo(8));
        for (final row in chunk.records) {
          racks.add(row['rack'] as int);
          expect((row['test_data'] as String).length, testData.length);
        }
        events.addAll(chunk.events);
      }
      expect(racks, [for (var rack = 1; rack <= 256; rack++) rack]);
      expect(
        events.map((event) => event.toJson()),
        originalEvents.map((event) => event.toJson()),
      );
    });

    test('64MiB超の旧形式を復元画面の処理で拒否してDBを保持する', () async {
      final file = await tempFile();
      final dbPath = await newDatabasePath();
      addTearDown(() => File(dbPath).parent.delete(recursive: true));
      final db = realDatabase(dbPath);
      addTearDown(db.close);
      final app = AppController(database: db);
      app.today = () => '2026-09-27';
      await db.applyChanges(ChangeSet(upserts: [rec(999)]));
      await app.initialize();
      final before = await db.loadState();
      final original = (await fullRows(db)).single.encode();
      final payload = jsonEncode(
        service.backupPayload([
          rec(1).copyWith(extra: {'test_data': '@large-field@'}),
        ]),
      );
      final parts = payload.split('@large-field@');
      final sink = file.openWrite();
      try {
        sink.write(parts.first);
        final megabyte = 'x' * (1024 * 1024);
        for (var i = 0; i < 64; i++) {
          sink.write(megabyte);
          await sink.flush();
        }
        sink.write(parts.last);
      } finally {
        await sink.close();
      }
      expect(await file.length(), greaterThan(wholeBackupLimitBytes));
      await expectLater(
        app.importBackup(file),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('メモリ不足'),
          ),
        ),
      );
      expect((await fullRows(db)).map((r) => r.encode()), [original]);
      expect(await db.loadState(), before);
    });
  });

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
