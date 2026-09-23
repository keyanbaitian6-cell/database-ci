import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'models.dart';

class DatabaseService {
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    final path = p.join(await getDatabasesPath(), 'database.sqlite3');
    _database = await openDatabase(
      path,
      version: 2,
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
      },
    );
    await _seedIfNeeded(_database!);
    return _database!;
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
