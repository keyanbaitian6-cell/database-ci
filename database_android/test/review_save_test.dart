import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/candidate_log.dart';
import 'package:database_android/database_service.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/import_service.dart';

class MemoryDatabase extends DatabaseService {
  List<SlotRecord> rows = [];
  List<CandidateSnapshot> snapshots = [];
  bool failWrite = false;
  @override
  Future<List<CandidateSnapshot>> loadCandidateSnapshots() async =>
      List.of(snapshots);
  @override
  Future<void> saveCandidateSnapshots(
    Iterable<CandidateSnapshot> incoming,
  ) async => snapshots.addAll(incoming);
  @override
  Future<List<SlotRecord>> loadAll() async => List.of(rows);
  @override
  Future<void> saveAll(Iterable<SlotRecord> records) async {
    if (failWrite) throw StateError('disk failure');
    final updated = {for (final r in rows) r.key: r};
    for (final r in records) {
      updated[r.key] = r;
    }
    rows = updated.values.toList();
  }

  @override
  Future<void> deleteRecords(Iterable<SlotRecord> records) async {
    if (failWrite) throw StateError('disk failure');
    final keys = records.map((r) => r.key).toSet();
    rows.removeWhere((r) => keys.contains(r.key));
  }

  @override
  Future<void> restoreRecords(List<(SlotRecord, SlotRecord?)> entries) async {
    if (failWrite) throw StateError('disk failure');
    final updated = {for (final r in rows) r.key: r};
    for (final (saved, previous) in entries) {
      if (previous == null) {
        updated.remove(saved.key);
      } else {
        updated[saved.key] = previous;
      }
    }
    rows = updated.values.toList();
  }
}

const old = SlotRecord(
  store: 'saiwaichou',
  day: '2026-09-22',
  machine: 'テスト',
  rack: 703,
  games: 3000,
  bb: 20,
  rb: 5,
  maxHold: 2000,
  previousStart: 50,
  confirmedSetting: '4以上',
  graph: GraphMeasurement(baselineY: 200, peakY: 100, troughY: 250, endY: 180),
);

void main() {
  late MemoryDatabase db;
  late AppController app;
  setUp(() {
    db = MemoryDatabase()..rows = [old];
    app = AppController(database: db)..records = [old];
  });
  Future<void> save({int games = 3000}) =>
      app.saveTable(old.store, old.day, old.machine, [
        EditableRow(
          rack: 703,
          games: games,
          bb: 20,
          rb: 5,
          maxHold: null,
          previousStart: null,
        ),
      ]);
  test('最大持玉のない表を再取得しても既存値・設定・グラフを失わない', () async {
    await save();
    expect(db.rows.single.maxHold, 2000);
    expect(db.rows.single.previousStart, 50);
    expect(db.rows.single.confirmedSetting, '4以上');
    expect(db.rows.single.graph, old.graph);
  });
  test('表の数値が変わったら古いグラフと混ぜず未取得扱いにする', () async {
    await save(games: 4000);
    expect(db.rows.single.graph, isNull);
    expect(db.rows.single.games, 4000);
  });
  test('保存失敗で、それ以前に成功した削除の取り消し控えを失わない', () async {
    await app.deleteGroup(day: old.day, store: old.store, machine: old.machine);
    db.failWrite = true;
    await expectLater(save(), throwsStateError);
    db.failWrite = false;
    await app.undoLastSave();
    expect(db.rows.map((r) => r.encode()).toList(), [old.encode()]);
  });
  test('取り消しが失敗しても控えを維持し再試行できる', () async {
    await app.deleteGroup(day: old.day, store: old.store, machine: old.machine);
    db.failWrite = true;
    await expectLater(app.undoLastSave(), throwsStateError);
    expect(db.rows, isEmpty);
    db.failWrite = false;
    await app.undoLastSave();
    expect(db.rows.single.encode(), old.encode());
    expect(await app.undoLastSave(), contains('ありません'));
  });

  test('新しく保存した台だけ初回取り込み時刻を持ち、取り込み直しても動かない', () async {
    Future<void> saveNew() => app.saveTable(old.store, old.day, old.machine, [
      EditableRow(
        rack: 704,
        games: 3000,
        bb: 20,
        rb: 5,
        maxHold: 2000,
        previousStart: null,
      ),
    ]);
    await saveNew();
    final first = app.records.firstWhere((r) => r.rack == 704).firstCapturedAt;
    expect(first, isNotNull);
    expect(first, matches(RegExp(r'[+-]\d\d:\d\d$')));
    await saveNew();
    expect(app.records.firstWhere((r) => r.rack == 704).firstCapturedAt, first);
    // 以前から保存済みで時刻のない台は、取り込み直しても「不明」のまま。
    await save();
    expect(
      app.records.firstWhere((r) => r.rack == 703).firstCapturedAt,
      isNull,
    );
  });

  test('取り込みのたびに翌日候補を記録し、同じ中身なら増やさない', () async {
    await save();
    expect(db.snapshots, hasLength(1));
    expect(
      db.snapshots.single.groupKey,
      '${old.store}|${old.day}|${old.machine}',
    );
    expect(db.snapshots.single.total, 1);
    await save();
    expect(db.snapshots, hasLength(1));
    await save(games: 3500);
    expect(db.snapshots, hasLength(1)); // 1台だけでは候補も指数も出ない
    expect(app.candidateSnapshots, hasLength(1));
  });
}
