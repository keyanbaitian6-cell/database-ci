import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import 'backup_service.dart';
import 'candidate_log.dart';
import 'date_events.dart';
import 'event_history_model.dart';
import 'models.dart';
import 'record_deletions.dart';

/// DBの版。4でグラフの画像・曲線を別の列（graph_blob）へ分け、ゴミ箱を足した。
/// 5で、バックアップから一時的に取り込んだ古い記録の印（temporary_records）を足した。
const databaseVersion = 5;

/// 端末に残す日数（最新の取り込み日から数えて）。採点は前の30日分と比べる
/// ので、直近30日分はPC版と同じ点数になる。これより古い記録は、全期間の
/// バックアップを書き出した後で端末から片付ける（PC版とバックアップには残る）。
const retentionDays = 60;

/// 保存期間を数える基準の日。最新の取り込み日と今日の早い方。
///
/// 最新の取り込み日だけで数えると、未来の日付（打ち間違いなど）の台が1件
/// あるだけで基準が先へずれ、残すべき台までまとめて片付けてしまう。
String retentionAnchor(String latestDay, String today) =>
    latestDay.compareTo(today) <= 0 ? latestDay : today;

/// [latestDay]（と今日 [today]）から数えて、端末に残す最初の日。これより
/// 前は片付けの対象。
String retentionCutoff(String latestDay, [String? today]) => _daysBefore(
  today == null ? latestDay : retentionAnchor(latestDay, today),
  retentionDays - 1,
);

String _daysBefore(String day, int days) =>
    DateTime.parse(day)
        .subtract(Duration(days: days))
        .toIso8601String()
        .substring(0, 10);

/// 一度にこれより多くの台（かつ全体の半分より多く）を片付けることになったら、
/// 片付けずに利用者に確かめる。ふだんは1日分（数百台）ずつしか消えないので、
/// これを超えるのは何かがおかしいとき。
const largeCleanupMinimum = 500;

/// 翌日候補の記録を端末に残す日数（利用者の指定、2026-09-27）。検証はPC版と
/// バックアップに残る記録で行う。これより古い記録は、全期間のバックアップに
/// 入れた後で端末から片付ける。
const candidateRetentionDays = 180;

/// ゴミ箱に残す日数。これより古いものは起動時に消す。
const trashDays = 7;

/// 起動時の片付けの結果。
typedef CleanupResult = ({
  int deleted,
  int kept,
  String? cutoff,

  /// 多すぎるので片付けずに止めた台の数（止めていなければ0）。
  int paused,

  /// 片付けた翌日候補の記録の数。
  int snapshots,
});

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
    this.deletions = const [],
    this.restoreDeleted = true,
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
  final List<RecordDeletion> deletions;
  final bool restoreDeleted;
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
    await _createTemporaryRecords(db);
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
    if (oldVersion < 5) await _createTemporaryRecords(db);
  }

  /// バックアップから一時的に取り込んだ、保存期間より古い台。次の起動時に消す。
  static Future<void> _createTemporaryRecords(Database db) => db.execute(
    'CREATE TABLE IF NOT EXISTS temporary_records (record_key TEXT PRIMARY KEY)',
  );

  /// 一時的に取り込んだ台として印を付ける（次の起動時に片付ける）。
  Future<void> markTemporary(Iterable<String> keys) async =>
      _markTemporary(await database, keys);

  static Future<void> _markTemporary(
    DatabaseExecutor db,
    Iterable<String> keys,
  ) async {
    final batch = db.batch();
    for (final key in keys) {
      batch.insert('temporary_records', {
        'record_key': key,
      }, conflictAlgorithm: ConflictAlgorithm.ignore);
    }
    await batch.commit(noResult: true);
  }

  /// 最新の取り込み日（記録が無ければ null）。
  Future<String?> latestDay() async => _latestDay(await database);

  static Future<String?> _latestDay(DatabaseExecutor db) async =>
      (await db.rawQuery('SELECT MAX(day) AS d FROM records')).first['d']
          as String?;

  /// 保存期間より古い台を片付ける。消すのは、[lastFullBackup]（全期間の
  /// バックアップを保存できたと利用者が確かめた書き出しの時刻）より前に保存
  /// したもの（＝バックアップに入っているもの）と、一時的に取り込んだもの。
  /// それ以外は残す。画像・曲線ごと消し、ゴミ箱には入れない（バックアップに
  /// あるため）。
  ///
  /// 基準の日は、最新の取り込み日と [today] の早い方（[retentionAnchor]）。
  /// バックアップ済みの台が多すぎる（[largeCleanupMinimum] 台を超え、かつ全体
  /// の半分より多い）ときは、[allowLarge] でなければ片付けずに数だけ返す。
  /// 翌日候補の記録も、[candidateRetentionDays] 日より古く、バックアップに
  /// 入れた後のものを片付ける。[temporary] が false なら、一時的に取り込んだ
  /// 台とその印には触らない（起動時以外に呼ぶとき）。
  Future<CleanupResult> cleanupOldRecords(
    DateTime? lastFullBackup, {
    required String today,
    bool allowLarge = false,
    bool temporary = true,
  }) async {
    final db = await database;
    final latest = await latestDay();
    final marked = {
      if (temporary)
        for (final row in await db.query('temporary_records'))
          row['record_key'] as String,
    };
    if (latest == null) {
      if (marked.isNotEmpty) await db.delete('temporary_records');
      return (deleted: 0, kept: 0, cutoff: null, paused: 0, snapshots: 0);
    }
    bool backedUp(Object? stamp) {
      final saved = DateTime.tryParse(stamp as String? ?? '');
      return lastFullBackup != null &&
          saved != null &&
          saved.isBefore(lastFullBackup);
    }

    final anchor = retentionAnchor(latest, today);
    final cutoff = retentionCutoff(latest, today);
    final rows = await db.rawQuery(
      'SELECT record_key, updated_at FROM records WHERE day < ?',
      [cutoff],
    );
    final total =
        (await db.rawQuery('SELECT COUNT(*) AS n FROM records')).first['n']
            as int;
    final temporaryKeys = <String>[];
    final backedUpKeys = <String>[];
    for (final row in rows) {
      final key = row['record_key'] as String;
      if (marked.contains(key)) {
        temporaryKeys.add(key);
      } else if (backedUp(row['updated_at'])) {
        backedUpKeys.add(key);
      }
    }
    final limit = max(largeCleanupMinimum, (total - temporaryKeys.length) ~/ 2);
    final paused = !allowLarge && backedUpKeys.length > limit;
    final doomed = [...temporaryKeys, if (!paused) ...backedUpKeys];
    final snapshotCutoff = _daysBefore(anchor, candidateRetentionDays);
    final oldSnapshots = lastFullBackup == null
        ? const <Map<String, Object?>>[]
        : [
            for (final row in await db.query(
              'candidate_snapshots',
              columns: ['store', 'day', 'machine', 'taken_at'],
              where: 'day < ?',
              whereArgs: [snapshotCutoff],
            ))
              if (backedUp(row['taken_at'])) row,
          ];
    await db.transaction((txn) async {
      final batch = txn.batch();
      for (final key in doomed) {
        batch.delete('records', where: 'record_key = ?', whereArgs: [key]);
      }
      if (temporary) batch.delete('temporary_records');
      for (final s in oldSnapshots) {
        batch.delete(
          'candidate_snapshots',
          where: 'store = ? AND day = ? AND machine = ? AND taken_at = ?',
          whereArgs: [s['store'], s['day'], s['machine'], s['taken_at']],
        );
      }
      await batch.commit(noResult: true);
    });
    return (
      deleted: doomed.length,
      kept: rows.length - doomed.length,
      cutoff: cutoff,
      paused: paused ? backedUpKeys.length : 0,
      snapshots: oldSnapshots.length,
    );
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

  /// 最後の [loadAll] で読めなかった台（DBには残したまま、一覧には入れない）。
  List<String> unreadableKeys = const [];

  /// 画面用の一覧。グラフの画像・曲線は読まない（別の列にある印だけ）。
  ///
  /// 読めない台（壊れた・形の違う記録）が1件あっても起動できるよう、その台
  /// だけ飛ばして [unreadableKeys] に残す。DBからは消さない（書き出しには
  /// そのまま入る）。
  Future<List<SlotRecord>> loadAll() async {
    final db = await database;
    final out = <SlotRecord>[];
    final unreadable = <String>[];
    var last = 0;
    while (true) {
      final rows = await db.rawQuery(
        'SELECT rowid AS id, record_key, payload FROM records '
        'WHERE rowid > ? ORDER BY rowid LIMIT ?',
        [last, _chunkRows],
      );
      if (rows.isEmpty) break;
      for (final row in rows) {
        last = row['id'] as int;
        final record = _parseRecord(row['payload']);
        if (record == null) {
          unreadable.add(row['record_key'] as String);
        } else {
          out.add(record);
        }
      }
    }
    unreadableKeys = unreadable;
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

  /// 本体のJSONを台にする（[full] なら別の列の画像・曲線も戻す）。壊れて
  /// いる・形が違うときは null。
  static SlotRecord? _parseRecord(
    Object? payload, {
    Object? blob,
    bool full = false,
  }) {
    try {
      return SlotRecord.fromJson(
        full
            ? joinStorageJson(payload as String, blob as String?)
            : Map<String, dynamic>.from(jsonDecode(payload as String) as Map),
      );
    } on Object {
      return null;
    }
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
        // 読めない台は無いものとして扱う（一覧にも出ていない）。
        // 画像・曲線の列だけが壊れていれば、それを除いて読む。
        final record =
            _parseRecord(row['payload'], blob: row['graph_blob'], full: true) ??
            _parseRecord(row['payload'], full: true);
        if (record != null) found[record.key] = record;
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
    await db.transaction((txn) => _applyIn(txn, changes));
  }

  /// 何回かに分けた書き込みを、1つのトランザクションにまとめる（バックアップの
  /// 取り込み用）。[action] の途中で失敗したら、それまでの分も含めて何も
  /// 書かない。[action] の中では、渡された [DatabaseWriter] だけを使うこと
  /// （このサービスの他のメソッドを呼ぶと、トランザクションの終わりを待って
  /// 止まる）。
  Future<T> writeTransaction<T>(
    Future<T> Function(DatabaseWriter writer) action,
  ) async {
    final db = await database;
    return db.transaction((txn) => action(DatabaseWriter._(txn)));
  }

  static Future<void> _applyIn(Transaction txn, ChangeSet changes) async {
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
    final deletionRows = await txn.query(
      'app_state',
      where: 'state_key = ?',
      whereArgs: ['record_deletions'],
    );
    final marks = mergeRecordDeletions([
      ...readRecordDeletions(
        deletionRows.isEmpty
            ? null
            : jsonDecode(deletionRows.single['value'] as String),
      ),
      ...changes.deletions,
    ]);
    final removed = await _loadFull(txn, changes.deleteKeys);
    for (final row in removed.values) {
      final mark = deletionForRecord(row);
      marks[mark.key] = mark;
    }
    final batch = txn.batch();
    for (final key in changes.deleteKeys) {
      batch.delete('records', where: 'record_key = ?', whereArgs: [key]);
    }
    // Incoming tombstones remove only rows older than the explicit operation.
    final affected = await _loadFull(txn, changes.deletions.map((m) => m.key));
    for (final row in affected.values) {
      if (!recordSurvivesDeletion(row.toJson(), marks)) {
        batch.delete('records', where: 'record_key = ?', whereArgs: [row.key]);
      }
    }
    for (var record in changes.upserts) {
      if (!recordSurvivesDeletion(record.toJson(), marks)) {
        if (!changes.restoreDeleted) continue;
        record = restoreDeletedRecord(record, marks[record.key]!);
      }
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
    if (marks.isNotEmpty) {
      batch.insert('app_state', {
        'state_key': 'record_deletions',
        'value': jsonEncode([for (final m in marks.values) m.toJson()]),
      }, conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  /// 画像込みのJSON文字列（ゴミ箱に入れる形）。読めない台は、本体の文字列を
  /// そのまま入れる（壊れていても消えずに残る）。
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
        String text;
        try {
          text = jsonEncode(
            joinStorageJson(
              row['payload'] as String,
              row['graph_blob'] as String?,
            ),
          );
        } on Object {
          text = row['payload'] as String;
        }
        found[row['record_key'] as String] = text;
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

  /// 画面の比較に必要なのはグループごとの最新だけ。履歴全文はDBと出力に残す。
  Future<List<CandidateSnapshot>> loadLatestCandidateSnapshots() async {
    final db = await database;
    final rows = await db.rawQuery('''
      SELECT s.payload FROM candidate_snapshots s
      WHERE NOT EXISTS (SELECT 1 FROM candidate_snapshots newer
        WHERE newer.store = s.store AND newer.day = s.day AND newer.machine = s.machine
          AND (julianday(newer.taken_at) > julianday(s.taken_at)
            OR (julianday(newer.taken_at) = julianday(s.taken_at) AND newer.rowid > s.rowid)))
    ''');
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
    // 読めない行は戻せないので飛ばす（ゴミ箱には残り、7日で消える）。
    return [
      for (final row in rows)
        if (_parseRecord(row['payload']) case final record?)
          TrashEntry(id: row['id'] as int, record: record),
    ];
  }

  /// [before] より前にゴミ箱へ入れたものを消し、消した数を返す。
  Future<int> purgeTrash(DateTime before) async {
    final db = await database;
    return db.delete(
      'trash',
      where: 'deleted_at < ?',
      whereArgs: [before.toUtc().toIso8601String()],
    );
  }

  /// バックアップを1台ずつ書き出す（全件を1つの文字列にしない）。
  /// 1行に1台を書くので、読み込みも1行ずつできる（[readBackupFile]）。
  ///
  /// 翌日候補の記録も、画面用の一覧ではなくDBから直接書く（起動時に読み
  /// 込めなかったときでも、書き出しから抜け落ちないように）。読めない台は
  /// 消さずに、本体・画像の元の文字列を救出用として書く。読めないデータを
  /// 含むファイルは通常の復元用とは区別する。[onProgress] には書いた
  /// 台数を渡す。
  Future<({int records, int candidates, int events, int unreadable})>
  exportBackup(
    File file, {
    String? store,
    String? day,
    List<DateEvent> events = const [],
    String source = 'android',
    void Function(int written)? onProgress,
  }) async => _writeBackup(
    await database,
    file,
    store: store,
    day: day,
    events: [for (final event in events) event.toJson()],
    source: source,
    onProgress: onProgress,
  );

  static Future<({int records, int candidates, int events, int unreadable})>
  _writeBackup(
    DatabaseExecutor db,
    File file, {
    String? store,
    String? day,
    List<Object?> events = const [],
    required String source,
    void Function(int written)? onProgress,
  }) async {
    final where = [
      'rowid > ?',
      if (store != null) 'store = ?',
      if (day != null) 'day = ?',
    ].join(' AND ');
    final sink = file.openWrite();
    var count = 0;
    var unreadable = 0;
    var candidates = 0;
    var eventCount = 0;
    try {
      // 画面で読み飛ばしたイベントも失わないよう、DBの原文から読む。
      // DB自体の読み取りエラーは握りつぶさず、書き出し失敗として知らせる。
      final eventRows = await db.query(
        'app_state',
        columns: ['value'],
        where: 'state_key = ?',
        whereArgs: ['date_events'],
      );
      Object? unreadableEvents;
      var eventData = events;
      if (eventRows.isNotEmpty) {
        final original = eventRows.single['value'];
        try {
          final decoded = jsonDecode(original as String);
          if (decoded is! List ||
              decoded.any((item) => DateEvent.tryFromJson(item) == null)) {
            throw const FormatException('イベント情報の形式が不正です。');
          }
          eventData = decoded
              .where(
                (item) =>
                    (store == null || item['store'] == store) &&
                    (day == null || item['day'] == day),
              )
              .toList();
        } on Object {
          unreadable++;
          unreadableEvents = original;
          eventData = const [];
        }
      }
      eventCount = eventData.length;
      final deletionRows = await db.query(
        'app_state',
        columns: ['value'],
        where: 'state_key = ?',
        whereArgs: ['record_deletions'],
      );
      final deletions =
          readRecordDeletions(
                deletionRows.isEmpty
                    ? null
                    : jsonDecode(deletionRows.single['value'] as String),
              )
              .where(
                (m) =>
                    (store == null || m.store == store) &&
                    (day == null || m.day == day),
              )
              .toList();
      final historyRows = await db.query(
        'app_state',
        columns: ['value'],
        where: 'state_key = ?',
        whereArgs: ['event_history_edits'],
      );
      final history = historyRows.isEmpty
          ? null
          : historyForBackup(historyRows.single['value'] as String?);
      final header = jsonEncode({
        'event_history_edits': ?history,
        'format': backupFormat,
        'version': backupVersion,
        'exported_at': DateTime.now().toUtc().toIso8601String(),
        'source': source,
        if (deletions.isNotEmpty)
          'record_deletions': [for (final m in deletions) m.toJson()],
        if (eventData.isNotEmpty) 'date_events': eventData,
        if (unreadableEvents != null)
          'unreadable_date_events': unreadableEvents,
      });
      sink.write('${header.substring(0, header.length - 1)}, "records": [');
      var last = 0;
      while (true) {
        final rows = await db.rawQuery(
          'SELECT rowid AS id, record_key, payload, graph_blob FROM records '
          'WHERE $where ORDER BY rowid LIMIT ?',
          [last, ?store, ?day, _chunkRows],
        );
        if (rows.isEmpty) break;
        for (final row in rows) {
          last = row['id'] as int;
          String line;
          try {
            if (_parseRecord(row['payload']) == null) {
              throw const FormatException('記録の形式が不正です。');
            }
            line = jsonEncode(
              joinStorageJson(
                row['payload'] as String,
                row['graph_blob'] as String?,
              ),
            );
          } on Object {
            unreadable++;
            line = jsonEncode({
              'unreadable_record': row['payload'],
              'record_key': row['record_key'],
              'graph_blob': row['graph_blob'],
            });
          }
          sink.write(count == 0 ? '\n' : ',\n');
          sink.write(line);
          count++;
        }
        onProgress?.call(count);
      }
      sink.write('\n]');
      var lastSnapshot = 0;
      var snapshotRows = 0;
      while (true) {
        final snapshots = await db.rawQuery(
          'SELECT rowid AS id, payload FROM candidate_snapshots WHERE rowid > ?'
          '${store == null ? '' : ' AND store = ?'}'
          '${day == null ? '' : ' AND day = ?'} ORDER BY rowid LIMIT ?',
          [lastSnapshot, ?store, ?day, _chunkRows],
        );
        if (snapshots.isEmpty) break;
        for (final row in snapshots) {
          lastSnapshot = row['id'] as int;
          Object? decoded;
          try {
            decoded = jsonDecode(row['payload'] as String);
            if (CandidateSnapshot.tryFromJson(decoded) == null) {
              throw const FormatException('翌日候補の記録の形式が不正です。');
            }
            candidates++;
          } on Object {
            unreadable++;
            decoded = {'unreadable_candidate_snapshot': row['payload']};
          }
          sink.write(
            snapshotRows == 0 ? ', "candidate_snapshots": [\n' : ',\n',
          );
          sink.write(jsonEncode(decoded));
          snapshotRows++;
        }
      }
      if (snapshotRows > 0) sink.write('\n]');
      if (unreadable > 0) sink.write(', "recovery_required": $unreadable');
      sink.write('}\n');
      await sink.flush();
    } finally {
      await sink.close();
    }
    return (
      records: count,
      candidates: candidates,
      events: eventCount,
      unreadable: unreadable,
    );
  }

  /// 非常用の書き出し。アプリが起動できないとき（DBが新しい版で作られた、
  /// 読み込み中に失敗した等）でも、DBを読むだけで開いて、記録・翌日候補の
  /// 記録・イベント名を1つのバックアップにする。DBには何も書かない。
  Future<({int records, int candidates, int events, int unreadable})> exportRaw(
    File file,
  ) async {
    final factory = factoryOverride ?? databaseFactory;
    final path =
        pathOverride ?? p.join(await getDatabasesPath(), 'database.sqlite3');
    final db = await factory.openDatabase(
      path,
      options: OpenDatabaseOptions(readOnly: true, singleInstance: false),
    );
    try {
      return await _writeBackup(db, file, source: 'android');
    } finally {
      await db.close();
    }
  }
}

/// [DatabaseService.writeTransaction] の中で使う書き込み口。
class DatabaseWriter {
  DatabaseWriter._(this._txn);
  final Transaction _txn;

  Future<void> apply(ChangeSet changes) =>
      DatabaseService._applyIn(_txn, changes);

  Future<int> addSnapshots(List<CandidateSnapshot> snapshots) async {
    if (snapshots.isEmpty) return 0;
    final before =
        (await _txn.rawQuery('SELECT total_changes() AS n')).single['n'] as int;
    await apply(ChangeSet(snapshots: snapshots));
    final after =
        (await _txn.rawQuery('SELECT total_changes() AS n')).single['n'] as int;
    return after - before;
  }

  Future<Map<String, SlotRecord>> loadByKeys(Iterable<String> keys) async =>
      keys.isEmpty ? {} : DatabaseService._loadFull(_txn, keys);

  Future<String?> latestDay() => DatabaseService._latestDay(_txn);

  Future<void> markTemporary(Iterable<String> keys) =>
      DatabaseService._markTemporary(_txn, keys);
}
