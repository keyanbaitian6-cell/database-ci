import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'backup_service.dart';
import 'candidate_log.dart';
import 'models.dart';

/// DBの版。4でグラフの画像・曲線を別の列（graph_blob）へ分け、ゴミ箱を足した。
const databaseVersion = 4;

/// ゴミ箱に残す日数。これより古いものは起動時に消す。
const trashDays = 7;

/// 一度に読む行数。全件を一度に読むと、sqflite の Android 側が全行を
/// Java のメモリに溜めてから渡すので、記録が増えると起動時に落ちる。
const _chunkRows = 300;

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

/// ゴミ箱に入れた理由。削除か、上書きで消えた前の内容か。
enum TrashKind { delete, overwrite }

/// 1回の書き込み。台の保存・削除、ゴミ箱、翌日候補の記録、アプリの状態を
/// 1つのトランザクションでまとめて書く（途中で落ちても片方だけ残らない）。
class ChangeSet {
  const ChangeSet({
    this.upserts = const [],
    this.deleteKeys = const [],
    this.trashKeys = const [],
    this.trashLabel = '',
    this.trashKind = TrashKind.delete,
    this.removeTrashIds = const [],
    this.snapshots = const [],
    this.state = const {},
  });

  /// 保存する台。グラフの画像・曲線を読み込んでいない（軽い）台は、DBに
  /// ある画像・曲線をそのまま残す。
  final List<SlotRecord> upserts;
  final List<String> deleteKeys;

  /// 書き換える前に、今のDBの内容（画像込み）をゴミ箱へ写す台。
  final List<String> trashKeys;
  final String trashLabel;
  final TrashKind trashKind;

  /// 戻し終えたゴミ箱の行。
  final List<int> removeTrashIds;
  final List<CandidateSnapshot> snapshots;
  final Map<String, String> state;
}

/// ゴミ箱の1回分（1回の削除・上書き）。
class TrashBatch {
  const TrashBatch({
    required this.batchId,
    required this.kind,
    required this.label,
    required this.deletedAt,
    required this.count,
  });
  final String batchId;
  final TrashKind kind;
  final String label;
  final DateTime deletedAt;
  final int count;
}

class TrashEntry {
  const TrashEntry({required this.id, required this.record});
  final int id;
  final SlotRecord record;
}

/// 保存用に、記録のJSONを「軽い本体」と「画像・曲線」に分ける。
/// 画像・曲線があれば、本体のグラフに「別の列にある」印を付ける。
(Map<String, dynamic> light, Map<String, dynamic>? heavy) splitStorageJson(
  Map<String, dynamic> json,
) {
  final graph = json['graph_measurement'];
  if (graph is! Map) return (json, null);
  final lightGraph = Map<String, dynamic>.from(graph);
  final heavy = <String, dynamic>{};
  for (final key in const ['preview_image', 'curve']) {
    final value = lightGraph.remove(key);
    if (value != null) heavy[key] = value;
  }
  if (heavy.containsKey('preview_image')) lightGraph['preview_stored'] = true;
  if (heavy.containsKey('curve')) lightGraph['curve_stored'] = true;
  return (
    {...json, 'graph_measurement': lightGraph},
    heavy.isEmpty ? null : heavy,
  );
}

/// 保存用の2つを1つに戻す（バックアップ・ゴミ箱・画像込みの読み込み用）。
Map<String, dynamic> joinStorageJson(String payload, String? blob) {
  final json = Map<String, dynamic>.from(jsonDecode(payload) as Map);
  final graph = json['graph_measurement'];
  if (graph is Map) {
    final full = Map<String, dynamic>.from(graph);
    if (blob != null) {
      full.addAll(Map<String, dynamic>.from(jsonDecode(blob) as Map));
    }
    full.remove('preview_stored');
    full.remove('curve_stored');
    json['graph_measurement'] = full;
  }
  return json;
}

class DatabaseService {
  DatabaseService({this.factoryOverride, this.pathOverride, this.seed = true});

  /// テストでPC上のSQLiteを使うとき用。普段は null（端末のSQLite）。
  final DatabaseFactory? factoryOverride;
  final String? pathOverride;

  /// 初回起動時に同梱の初期データを入れるか（テストでは入れない）。
  final bool seed;
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    final factory = factoryOverride ?? databaseFactory;
    final path =
        pathOverride ?? p.join(await getDatabasesPath(), 'database.sqlite3');
    _database = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(
        version: databaseVersion,
        onCreate: _create,
        onUpgrade: _upgrade,
        onDowngrade: refuseDowngrade,
      ),
    );
    await _seedIfNeeded(_database!);
    return _database!;
  }

  Future<void> close() async {
    await _database?.close();
    _database = null;
  }

  static Future<void> _create(Database db, int version) async {
    await db.execute('''
      CREATE TABLE records (
        record_key TEXT PRIMARY KEY,
        store TEXT NOT NULL,
        day TEXT NOT NULL,
        machine TEXT NOT NULL,
        rack INTEGER NOT NULL,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        graph_blob TEXT
      )
    ''');
    await db.execute('''
      CREATE TABLE app_state (
        state_key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      )
    ''');
    await _createCandidateSnapshots(db);
    await _createTrash(db);
  }

  static Future<void> _upgrade(Database db, int oldVersion, int _) async {
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
    if (oldVersion < 4) {
      await db.execute('ALTER TABLE records ADD COLUMN graph_blob TEXT');
      await _createTrash(db);
      await _moveGraphsOut(db);
    }
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

  static Future<void> _createTrash(Database db) => db.execute('''
    CREATE TABLE IF NOT EXISTS trash (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      batch_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      label TEXT NOT NULL,
      deleted_at TEXT NOT NULL,
      record_key TEXT NOT NULL,
      payload TEXT NOT NULL
    )
  ''');

  /// 版3までの記録（画像・曲線が本体の中）を、少しずつ別の列へ移す。
  static Future<void> _moveGraphsOut(Database db) async {
    var last = 0;
    while (true) {
      final rows = await db.rawQuery(
        'SELECT rowid AS id, payload FROM records WHERE rowid > ? ORDER BY rowid LIMIT ?',
        [last, _chunkRows],
      );
      if (rows.isEmpty) break;
      final batch = db.batch();
      for (final row in rows) {
        last = row['id'] as int;
        final json = Map<String, dynamic>.from(
          jsonDecode(row['payload'] as String) as Map,
        );
        final (light, heavy) = splitStorageJson(json);
        if (heavy == null) continue;
        batch.rawUpdate(
          'UPDATE records SET payload = ?, graph_blob = ? WHERE rowid = ?',
          [jsonEncode(light), jsonEncode(heavy), last],
        );
      }
      await batch.commit(noResult: true);
    }
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
    if (seed) {
      final raw = await rootBundle.loadString('assets/database_seed.json');
      final decoded = jsonDecode(raw) as Map<String, dynamic>;
      final now = DateTime.now().toUtc().toIso8601String();
      final batch = db.batch();
      for (final item in decoded['rows'] as List<dynamic>) {
        final record = SlotRecord.fromJson(
          Map<String, dynamic>.from(item as Map),
        );
        _upsert(batch, record, now);
      }
      await batch.commit(noResult: true);
    }
    await db.insert('app_state', {'state_key': 'initial_seeded', 'value': '1'});
  }

  /// 1台を保存する。古いSQLiteでも動くよう、UPSERT構文は使わない。
  /// グラフの画像・曲線を読み込んでいない（軽い）台は、graph_blob に
  /// 触らない。画面用の軽い台を書き戻しても、画像が消えることはない。
  static void _upsert(Batch batch, SlotRecord record, String now) {
    final (light, heavy) = splitStorageJson(record.toJson());
    final payload = jsonEncode(light);
    final keepBlob = record.graph?.detached ?? false;
    final blob = heavy == null ? null : jsonEncode(heavy);
    batch.rawInsert(
      'INSERT OR IGNORE INTO records '
      '(record_key, store, day, machine, rack, payload, updated_at, graph_blob) '
      'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
      [
        record.key,
        record.store,
        record.day,
        record.machine,
        record.rack,
        payload,
        now,
        keepBlob ? null : blob,
      ],
    );
    if (keepBlob) {
      batch.rawUpdate(
        'UPDATE records SET store = ?, day = ?, machine = ?, rack = ?, '
        'payload = ?, updated_at = ? WHERE record_key = ?',
        [
          record.store,
          record.day,
          record.machine,
          record.rack,
          payload,
          now,
          record.key,
        ],
      );
    } else {
      batch.rawUpdate(
        'UPDATE records SET store = ?, day = ?, machine = ?, rack = ?, '
        'payload = ?, updated_at = ?, graph_blob = ? WHERE record_key = ?',
        [
          record.store,
          record.day,
          record.machine,
          record.rack,
          payload,
          now,
          blob,
          record.key,
        ],
      );
    }
  }

  /// 画面用の一覧。グラフの画像・曲線は読まない（別の列にある印だけ）。
  Future<List<SlotRecord>> loadAll() async {
    final db = await database;
    final out = <SlotRecord>[];
    var last = 0;
    while (true) {
      final rows = await db.rawQuery(
        'SELECT rowid AS id, payload FROM records WHERE rowid > ? ORDER BY rowid LIMIT ?',
        [last, _chunkRows],
      );
      if (rows.isEmpty) break;
      for (final row in rows) {
        last = row['id'] as int;
        out.add(
          SlotRecord.fromJson(
            Map<String, dynamic>.from(
              jsonDecode(row['payload'] as String) as Map,
            ),
          ),
        );
      }
    }
    out.sort((a, b) {
      final day = b.day.compareTo(a.day);
      if (day != 0) return day;
      final store = a.store.compareTo(b.store);
      if (store != 0) return store;
      final machine = a.machine.compareTo(b.machine);
      return machine != 0 ? machine : a.rack.compareTo(b.rack);
    });
    return out;
  }

  static Future<Map<String, SlotRecord>> _loadFull(
    DatabaseExecutor db,
    Iterable<String> keys,
  ) async {
    final unique = keys.toSet().toList();
    final found = <String, SlotRecord>{};
    // SQLite の引数の上限にかからないよう、少しずつ読む。
    for (var i = 0; i < unique.length; i += 200) {
      final chunk = unique.sublist(i, min(i + 200, unique.length));
      final rows = await db.query(
        'records',
        columns: ['payload', 'graph_blob'],
        where: 'record_key IN (${List.filled(chunk.length, '?').join(',')})',
        whereArgs: chunk,
      );
      for (final row in rows) {
        final record = SlotRecord.fromJson(
          joinStorageJson(
            row['payload'] as String,
            row['graph_blob'] as String?,
          ),
        );
        found[record.key] = record;
      }
    }
    return found;
  }

  /// 指定した台の、DBにある今の内容（画像・曲線込み、無い台は含まない）。
  Future<Map<String, SlotRecord>> loadByKeys(Iterable<String> keys) async {
    if (keys.isEmpty) return {};
    return _loadFull(await database, keys);
  }

  /// 保存時のグラフ画像（無ければ null）。
  Future<Uint8List?> loadPreview(String key) async {
    final db = await database;
    final rows = await db.query(
      'records',
      columns: ['graph_blob'],
      where: 'record_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    final blob = rows.firstOrNull?['graph_blob'] as String?;
    if (blob == null) return null;
    final image = (jsonDecode(blob) as Map)['preview_image'];
    if (image is! String || image.isEmpty) return null;
    try {
      return base64Decode(image);
    } on FormatException {
      return null;
    }
  }

  /// まとめて書く（[ChangeSet]）。どれか1つでも失敗したら、何も書かない。
  Future<void> applyChanges(ChangeSet changes) async {
    final db = await database;
    await db.transaction((txn) async {
      final now = DateTime.now().toUtc().toIso8601String();
      if (changes.trashKeys.isNotEmpty) {
        final batchId =
            '$now-${Random.secure().nextInt(1 << 32).toRadixString(16)}';
        final current = await _loadFullRaw(txn, changes.trashKeys);
        final trash = txn.batch();
        for (final entry in current.entries) {
          trash.insert('trash', {
            'batch_id': batchId,
            'kind': changes.trashKind.name,
            'label': changes.trashLabel,
            'deleted_at': now,
            'record_key': entry.key,
            'payload': entry.value,
          });
        }
        await trash.commit(noResult: true);
      }
      final batch = txn.batch();
      for (final key in changes.deleteKeys) {
        batch.delete('records', where: 'record_key = ?', whereArgs: [key]);
      }
      for (final record in changes.upserts) {
        _upsert(batch, record, now);
      }
      for (final id in changes.removeTrashIds) {
        batch.delete('trash', where: 'id = ?', whereArgs: [id]);
      }
      for (final s in changes.snapshots) {
        batch.insert('candidate_snapshots', {
          'store': s.store,
          'day': s.day,
          'machine': s.machine,
          'taken_at': s.takenAt,
          'payload': jsonEncode(s.toJson()),
        }, conflictAlgorithm: ConflictAlgorithm.ignore);
      }
      for (final entry in changes.state.entries) {
        batch.insert('app_state', {
          'state_key': entry.key,
          'value': entry.value,
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
      await batch.commit(noResult: true);
    });
  }

  /// 画像込みのJSON文字列（ゴミ箱に入れる形）。
  static Future<Map<String, String>> _loadFullRaw(
    DatabaseExecutor db,
    List<String> keys,
  ) async {
    final unique = keys.toSet().toList();
    final found = <String, String>{};
    for (var i = 0; i < unique.length; i += 200) {
      final chunk = unique.sublist(i, min(i + 200, unique.length));
      final rows = await db.query(
        'records',
        columns: ['record_key', 'payload', 'graph_blob'],
        where: 'record_key IN (${List.filled(chunk.length, '?').join(',')})',
        whereArgs: chunk,
      );
      for (final row in rows) {
        found[row['record_key'] as String] = jsonEncode(
          joinStorageJson(
            row['payload'] as String,
            row['graph_blob'] as String?,
          ),
        );
      }
    }
    return found;
  }

  Future<void> saveAll(Iterable<SlotRecord> records) =>
      applyChanges(ChangeSet(upserts: records.toList()));

  /// 機種名の表記ゆれ（`+` 区切り）で保存された台を、揃えた名前の台へ
  /// まとめる。画像・曲線込みでまとめるので、どちらのグラフも消えない。
  /// 揃えた台の数を返す（無ければ0で、何も書かない）。
  Future<int> normalizeMachineNames() async {
    final db = await database;
    final keys = await db.query('records', columns: ['record_key', 'machine']);
    final odd = [
      for (final row in keys)
        if (row['machine'] != normalizeMachineName(row['machine'] as String))
          row['record_key'] as String,
    ];
    if (odd.isEmpty) return 0;
    await db.transaction((txn) async {
      final now = DateTime.now().toUtc().toIso8601String();
      final raw = await _loadFull(txn, odd);
      for (final record in raw.values) {
        final normalized = record.copyWith(
          machine: normalizeMachineName(record.machine),
        );
        final twin = (await _loadFull(txn, [normalized.key]))[normalized.key];
        final merged = twin == null
            ? normalized
            : mergeSameRack(twin, normalized);
        final batch = txn.batch();
        batch.delete(
          'records',
          where: 'record_key = ?',
          whereArgs: [record.key],
        );
        _upsert(batch, merged, now);
        await batch.commit(noResult: true);
      }
    });
    return odd.length;
  }

  Future<List<CandidateSnapshot>> loadCandidateSnapshots() async {
    final db = await database;
    final rows = await db.query('candidate_snapshots', columns: ['payload']);
    return [
      for (final row in rows)
        ?CandidateSnapshot.tryFromJson(jsonDecode(row['payload'] as String)),
    ];
  }

  Future<Map<String, String>> loadState() async {
    final db = await database;
    final rows = await db.query('app_state');
    return {
      for (final row in rows)
        row['state_key'] as String: row['value'] as String,
    };
  }

  /// ゴミ箱の一覧（新しい順）。
  Future<List<TrashBatch>> loadTrash() async {
    final db = await database;
    final rows = await db.rawQuery(
      'SELECT batch_id, kind, label, deleted_at, COUNT(*) AS n FROM trash '
      'GROUP BY batch_id ORDER BY deleted_at DESC',
    );
    return [
      for (final row in rows)
        TrashBatch(
          batchId: row['batch_id'] as String,
          kind: row['kind'] == TrashKind.overwrite.name
              ? TrashKind.overwrite
              : TrashKind.delete,
          label: row['label'] as String,
          deletedAt: DateTime.parse(row['deleted_at'] as String),
          count: row['n'] as int,
        ),
    ];
  }

  Future<List<TrashEntry>> loadTrashBatch(String batchId) async {
    final db = await database;
    final rows = await db.query(
      'trash',
      columns: ['id', 'payload'],
      where: 'batch_id = ?',
      whereArgs: [batchId],
    );
    return [
      for (final row in rows)
        TrashEntry(
          id: row['id'] as int,
          record: SlotRecord.fromJson(
            Map<String, dynamic>.from(
              jsonDecode(row['payload'] as String) as Map,
            ),
          ),
        ),
    ];
  }

  /// [before] より前にゴミ箱へ入れたものを消す。
  Future<void> purgeTrash(DateTime before) async {
    final db = await database;
    await db.delete(
      'trash',
      where: 'deleted_at < ?',
      whereArgs: [before.toUtc().toIso8601String()],
    );
  }

  /// バックアップを1台ずつ書き出す（全件を1つの文字列にしない）。
  /// 1行に1台を書くので、読み込みも1行ずつできる（[readBackupFile]）。
  /// 書き出した台数を返す。
  Future<int> exportBackup(
    File file, {
    String? store,
    String? day,
    List<CandidateSnapshot> candidates = const [],
    String source = 'android',
  }) async {
    final db = await database;
    final where = [
      'rowid > ?',
      if (store != null) 'store = ?',
      if (day != null) 'day = ?',
    ].join(' AND ');
    final sink = file.openWrite();
    var count = 0;
    try {
      final header = jsonEncode({
        'format': backupFormat,
        'version': backupVersion,
        'exported_at': DateTime.now().toIso8601String(),
        'source': source,
      });
      sink.write('${header.substring(0, header.length - 1)}, "records": [');
      var last = 0;
      while (true) {
        final rows = await db.rawQuery(
          'SELECT rowid AS id, payload, graph_blob FROM records WHERE $where '
          'ORDER BY rowid LIMIT ?',
          [last, ?store, ?day, _chunkRows],
        );
        if (rows.isEmpty) break;
        for (final row in rows) {
          last = row['id'] as int;
          sink.write(count == 0 ? '\n' : ',\n');
          sink.write(
            jsonEncode(
              joinStorageJson(
                row['payload'] as String,
                row['graph_blob'] as String?,
              ),
            ),
          );
          count++;
        }
      }
      sink.write('\n]');
      if (candidates.isNotEmpty) {
        sink.write(', "candidate_snapshots": [');
        for (var i = 0; i < candidates.length; i++) {
          sink.write(i == 0 ? '\n' : ',\n');
          sink.write(jsonEncode(candidates[i].toJson()));
        }
        sink.write('\n]');
      }
      sink.write('}\n');
      await sink.flush();
    } finally {
      await sink.close();
    }
    return count;
  }
}
