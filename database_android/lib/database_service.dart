import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'candidate_log.dart';
import 'models.dart';

/// 端末のDBが、このアプリより新しい版で作られている（古いAPKを上書きで
/// 入れた等）。古い版がそのまま書き込むと、新しい版だけが知っている項目
/// （初回取り込み時刻・翌日候補の記録など）を落としてしまうので起動を止める。
class DatabaseTooNewException implements Exception {
  const DatabaseTooNewException(this.found, this.supported);
  final int found;
  final int supported;
  String get message =>
      'このデータは新しい版のアプリで作られています（データ版$found、このアプリは$supportedまで）。\n'
      '記録を守るため、この古い版では開きません。最新のアプリを入れ直してください。';
  @override
  String toString() => message;
}

/// sqflite の onDowngrade。何もしないと版番号を黙って下げて開いてしまう。
Future<void> refuseDowngrade(Object db, int oldVersion, int newVersion) =>
    Future.error(DatabaseTooNewException(oldVersion, newVersion));

class DatabaseService {
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    final path = p.join(await getDatabasesPath(), 'database.sqlite3');
    _database = await openDatabase(
      path,
      version: 3,
      onCreate: (db, _) async {
        await db.execute('''
          CREATE TABLE records (
            record_key TEXT PRIMARY KEY,
            store TEXT NOT NULL,
            day TEXT NOT NULL,
            machine TEXT NOT NULL,
            rack INTEGER NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
          )
        ''');
        await db.execute('''
          CREATE TABLE app_state (
            state_key TEXT PRIMARY KEY,
            value TEXT NOT NULL
          )
        ''');
        await _createCandidateSnapshots(db);
      },
      onUpgrade: (db, oldVersion, _) async {
        if (oldVersion < 2) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS app_state (
              state_key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
          ''');
          // 既存端末の記録は初期データではないため、空になっても再投入しない。
          await db.insert('app_state', {
            'state_key': 'initial_seeded',
            'value': '1',
          }, conflictAlgorithm: ConflictAlgorithm.ignore);
        }
        if (oldVersion < 3) await _createCandidateSnapshots(db);
      },
      onDowngrade: refuseDowngrade,
    );
    await _seedIfNeeded(_database!);
    return _database!;
  }

  /// 翌日候補（仮）の記録（candidate_log.dart）。同じ機種・日付・時刻は1件だけ。
  static Future<void> _createCandidateSnapshots(Database db) => db.execute('''
    CREATE TABLE IF NOT EXISTS candidate_snapshots (
      store TEXT NOT NULL,
      day TEXT NOT NULL,
      machine TEXT NOT NULL,
      taken_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      PRIMARY KEY (store, day, machine, taken_at)
    )
  ''');

  Future<List<CandidateSnapshot>> loadCandidateSnapshots() async {
    final db = await database;
    final rows = await db.query('candidate_snapshots', columns: ['payload']);
    return [
      for (final row in rows)
        ?CandidateSnapshot.tryFromJson(jsonDecode(row['payload'] as String)),
    ];
  }

  /// 追記だけ。すでにある（同じ機種・日付・時刻の）記録は書き換えない。
  Future<void> saveCandidateSnapshots(
    Iterable<CandidateSnapshot> snapshots,
  ) async {
    final db = await database;
    final batch = db.batch();
    for (final s in snapshots) {
      batch.insert('candidate_snapshots', {
        'store': s.store,
        'day': s.day,
        'machine': s.machine,
        'taken_at': s.takenAt,
        'payload': jsonEncode(s.toJson()),
      }, conflictAlgorithm: ConflictAlgorithm.ignore);
    }
    await batch.commit(noResult: true);
  }

  Future<void> _seedIfNeeded(Database db) async {
    final state = await db.query(
      'app_state',
      columns: ['value'],
      where: 'state_key = ?',
      whereArgs: ['initial_seeded'],
      limit: 1,
    );
    if (state.isNotEmpty) return;
    final raw = await rootBundle.loadString('assets/database_seed.json');
    final decoded = jsonDecode(raw) as Map<String, dynamic>;
    final batch = db.batch();
    for (final item in decoded['rows'] as List<dynamic>) {
      final record = SlotRecord.fromJson(
        Map<String, dynamic>.from(item as Map),
      );
      batch.insert(
        'records',
        _values(record),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
    await db.insert('app_state', {'state_key': 'initial_seeded', 'value': '1'});
  }

  Map<String, Object?> _values(SlotRecord record) => {
    'record_key': record.key,
    'store': record.store,
    'day': record.day,
    'machine': record.machine,
    'rack': record.rack,
    'payload': record.encode(),
    'updated_at': DateTime.now().toIso8601String(),
  };

  Future<List<SlotRecord>> loadAll() async {
    final db = await database;
    final rows = await db.query(
      'records',
      orderBy: 'day DESC, store, machine, rack',
    );
    return rows
        .map(
          (row) => SlotRecord.fromJson(
            Map<String, dynamic>.from(
              jsonDecode(row['payload'] as String) as Map,
            ),
          ),
        )
        .toList();
  }

  /// 指定した台の、DBにある今の内容（無い台は含まない）。
  Future<Map<String, SlotRecord>> loadByKeys(Iterable<String> keys) async {
    final unique = keys.toSet().toList();
    if (unique.isEmpty) return {};
    final db = await database;
    final found = <String, SlotRecord>{};
    // SQLite の引数の上限にかからないよう、少しずつ読む。
    for (var i = 0; i < unique.length; i += 200) {
      final chunk = unique.sublist(i, (i + 200).clamp(0, unique.length));
      final rows = await db.query(
        'records',
        columns: ['payload'],
        where: 'record_key IN (${List.filled(chunk.length, '?').join(',')})',
        whereArgs: chunk,
      );
      for (final row in rows) {
        final record = SlotRecord.fromJson(
          Map<String, dynamic>.from(
            jsonDecode(row['payload'] as String) as Map,
          ),
        );
        found[record.key] = record;
      }
    }
    return found;
  }

  Future<void> saveAll(Iterable<SlotRecord> records) async {
    final db = await database;
    final batch = db.batch();
    for (final record in records) {
      batch.insert(
        'records',
        _values(record),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
  }

  Future<void> replaceAll(Iterable<SlotRecord> records) async {
    final db = await database;
    await db.transaction((transaction) async {
      await transaction.delete('records');
      final batch = transaction.batch();
      for (final record in records) {
        batch.insert('records', _values(record));
      }
      await batch.commit(noResult: true);
    });
  }

  /// まとめて削除。途中で失敗したら1台も消さない（トランザクション）。
  Future<void> deleteRecords(Iterable<SlotRecord> records) async {
    final db = await database;
    await db.transaction((transaction) async {
      final batch = transaction.batch();
      for (final record in records) {
        batch.delete(
          'records',
          where: 'record_key = ?',
          whereArgs: [record.key],
        );
      }
      await batch.commit(noResult: true);
    });
  }

  Future<void> deleteRecord(SlotRecord record) async {
    final db = await database;
    await db.delete(
      'records',
      where: 'record_key = ?',
      whereArgs: [record.key],
    );
  }

  /// Deletions and exact restoration either both commit or both roll back.
  Future<void> restoreRecords(
    List<(SlotRecord saved, SlotRecord? previous)> entries,
  ) async {
    final db = await database;
    await db.transaction((transaction) async {
      final batch = transaction.batch();
      for (final (saved, previous) in entries) {
        if (previous == null) {
          batch.delete(
            'records',
            where: 'record_key = ?',
            whereArgs: [saved.key],
          );
        } else {
          batch.insert(
            'records',
            _values(previous),
            conflictAlgorithm: ConflictAlgorithm.replace,
          );
        }
      }
      await batch.commit(noResult: true);
    });
  }
}
