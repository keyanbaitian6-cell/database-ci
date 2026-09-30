import 'dart:typed_data';

import 'package:database_android/database_service.dart';
import 'package:database_android/import_service.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/web_import_page.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'support/real_database.dart';

/// 本物のSQLiteに、書き込み失敗と読み出しの遅れを差し込めるようにしたもの。
class TestDatabase extends DatabaseService {
  TestDatabase(String path)
    : super(
        factoryOverride: databaseFactoryFfi,
        pathOverride: path,
        seed: false,
      );

  bool failWrite = false;

  /// 読み出しにかかる時間。0以外にすると、読み始めた時点の内容を
  /// 遅れて返す（保存と読み直しの行き違いを再現する）。
  Duration loadDelay = Duration.zero;

  @override
  Future<void> applyChanges(ChangeSet changes) async {
    if (failWrite) throw StateError('disk failure');
    await super.applyChanges(changes);
  }

  @override
  Future<List<SlotRecord>> loadAll() async {
    final snapshot = await super.loadAll();
    if (loadDelay != Duration.zero) await Future<void>.delayed(loadDelay);
    return snapshot;
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

final png = Uint8List.fromList(List.generate(64, (i) => i));

void main() {
  late TestDatabase db;
  late AppController app;
  setUp(() async {
    db = TestDatabase(await newDatabasePath());
    await db.applyChanges(const ChangeSet(upserts: [old]));
    app = AppController(database: db);
    await app.initialize();
  });
  tearDown(() => db.close());

  Future<SlotRecord> row(int rack) async =>
      (await fullRows(db)).firstWhere((r) => r.rack == rack);

  Future<void> save({int games = 3000, int rack = 703}) =>
      app.saveTable(old.store, old.day, old.machine, [
        EditableRow(
          rack: rack,
          games: games,
          bb: 20,
          rb: 5,
          maxHold: null,
          previousStart: null,
        ),
      ]);

  Future<void> saveGraph({int rack = 703, int games = 3000}) => app.saveGraph(
    store: old.store,
    day: old.day,
    machine: old.machine,
    rack: rack,
    games: games,
    bb: 20,
    rb: 5,
    maxHold: 2000,
    points: const [
      Offset(10, 200),
      Offset(40, 90),
      Offset(70, 240),
      Offset(100, 150),
    ],
    previewPng: png,
    previewWidth: 120,
    previewHeight: 300,
    curve: const [
      [10, 200],
      [100, 150],
    ],
  );

  test('最大持玉のない表を再取得しても既存値・設定・グラフを失わない', () async {
    await save();
    final saved = await row(703);
    expect(saved.maxHold, 2000);
    expect(saved.previousStart, 50);
    expect(saved.confirmedSetting, '4以上');
    expect(saved.graph!.toJson(), old.graph!.toJson());
  });

  test('表の数値が変わったら古いグラフと混ぜず未取得扱いにし、前の内容をゴミ箱に残す', () async {
    await save(games: 4000);
    final saved = await row(703);
    expect(saved.graph, isNull);
    expect(saved.games, 4000);
    final trash = await db.loadTrash();
    expect(trash.single.kind, TrashKind.overwrite);
    final entry = (await db.loadTrashBatch(trash.single.batchId)).single;
    expect(entry.record.games, 3000);
    expect(entry.record.graph!.toJson(), old.graph!.toJson());
  });

  test('保存失敗で、それ以前に成功した削除の取り消し控えを失わない', () async {
    await app.deleteGroup(day: old.day, store: old.store, machine: old.machine);
    db.failWrite = true;
    await expectLater(save(), throwsStateError);
    db.failWrite = false;
    await app.undoLastSave();
    expect((await fullRows(db)).map((r) => r.encode()).toList(), [
      old.encode(),
    ]);
  });

  test('取り消しが失敗しても控えを維持し再試行できる', () async {
    await app.deleteGroup(day: old.day, store: old.store, machine: old.machine);
    db.failWrite = true;
    await expectLater(app.undoLastSave(), throwsStateError);
    expect(await db.loadAll(), isEmpty);
    db.failWrite = false;
    await app.undoLastSave();
    expect((await fullRows(db)).single.encode(), old.encode());
    expect(await app.undoLastSave(), contains('ありません'));
  });

  test('新しく保存した台だけ初回取り込み時刻を持ち、取り込み直しても動かない', () async {
    await save(rack: 704);
    final first = app.records.firstWhere((r) => r.rack == 704).firstCapturedAt;
    expect(first, isNotNull);
    expect(first, matches(RegExp(r'[+-]\d\d:\d\d$')));
    await save(rack: 704);
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
    var snapshots = await db.loadCandidateSnapshots();
    expect(snapshots, hasLength(1));
    // 1台だけの機種は、その日その店の「バラエティ」として記録する。3000G回って
    // プラスで終わった台なので、幸町の狙い方で候補になる。
    expect(snapshots.single.groupKey, '${old.store}|${old.day}|バラエティ');
    expect(snapshots.single.total, 1);
    expect(snapshots.single.method, '2026-09-30');
    expect([for (final c in snapshots.single.candidates) c.rack], [703]);
    await save();
    snapshots = await db.loadCandidateSnapshots();
    expect(snapshots, hasLength(1)); // 同じ中身なら増やさない
    // 回転数の違う表を取り込み直すとグラフが外れ、終わり方が分からなくなるので
    // 候補から外れる（その変化は記録する）。
    await save(games: 3500);
    snapshots = await db.loadCandidateSnapshots();
    expect(
      [for (final s in snapshots) s.candidates.length]..sort(),
      [0, 1],
    );
    // 画面側はグループごとの最新だけを持つ。
    expect(app.candidateSnapshots, hasLength(1));
    expect(app.candidateSnapshots.single.candidates, isEmpty);
  });

  test('保存に失敗したら、台も翌日候補の記録も書かない（片方だけ残らない）', () async {
    db.failWrite = true;
    await expectLater(save(rack: 706), throwsStateError);
    db.failWrite = false;
    expect((await db.loadAll()).map((r) => r.rack), [703]);
    expect(await db.loadCandidateSnapshots(), isEmpty);
    expect(app.records.map((r) => r.rack), [703]);
  });

  test('翌日候補の計算に失敗しても台は保存し、失敗した回数を残して知らせる', () async {
    app.computeCandidates = ({
      required saved,
      required all,
      required latest,
      required now,
    }) => throw StateError('bug');
    await save(rack: 707);
    expect((await db.loadAll()).map((r) => r.rack), containsAll([703, 707]));
    expect(app.candidateLogFailures, 1);
    expect(app.message, contains('翌日候補を記録できませんでした'));
    expect((await db.loadState())['candidate_log_failures'], '1');
  });

  test('画面の一覧が古くても、DBにあるグラフと設定情報を表の保存で消さない', () async {
    // 画面側だけグラフも設定情報も無い古い内容（読み直しの行き違いなど）。
    app.records = [old.copyWithoutGraphAndSetting()];
    await save();
    expect((await row(703)).graph, isNotNull);
    expect((await row(703)).confirmedSetting, '4以上');
    // 取り消しもDBの内容（グラフあり）へ戻す。
    await app.undoLastSave();
    expect((await row(703)).encode(), old.encode());
  });

  test('画面の台が古くても、設定情報の保存でグラフを巻き戻さない', () async {
    await app.setConfirmedSetting(old.copyWithoutGraphAndSetting(), '6');
    expect((await row(703)).confirmedSetting, '6');
    expect((await row(703)).graph, isNotNull);
  });

  test('保存の途中に読み直しても、保存した内容が画面から消えない', () async {
    db.loadDelay = const Duration(milliseconds: 20);
    final saving = save(rack: 705, games: 1000);
    final reloading = app.reload();
    await Future.wait([saving, reloading]);
    expect(app.records.map((r) => r.rack), containsAll([703, 705]));
  });

  test('読み直しでも機種名の表記ゆれをそろえ、DBも画像込みでまとめる', () async {
    await db.applyChanges(
      ChangeSet(
        upserts: [
          old.copyWith(
            machine: 'テ+スト',
            graph: GraphMeasurement(
              baselineY: 1,
              peakY: 2,
              troughY: 3,
              endY: 4,
              previewPng: png,
            ),
          ),
        ],
      ),
    );
    await app.reload();
    expect(app.records.map((r) => r.machine).toSet(), {'テスト', 'テ スト'});
    expect(await db.loadPreview('${old.store}|${old.day}|テ スト|703'), png);
    await db.applyChanges(
      ChangeSet(
        upserts: [
          old.copyWith(machine: 'A+B', games: 3100),
          old.copyWith(machine: 'A B'),
        ],
      ),
    );
    await app.reload();
    final ab = app.records.where((r) => r.machine.startsWith('A')).toList();
    expect(ab.single.machine, 'A B');
    expect(ab.single.games, 3100);
    expect((await db.loadAll()).where((r) => r.machine.contains('+')), isEmpty);
  });

  test('知らない項目は、表を取り込み直しても落とさない', () async {
    await db.applyChanges(
      ChangeSet(
        upserts: [
          SlotRecord.fromJson({...old.toJson(), 'future_field': 7}),
        ],
      ),
    );
    await app.reload();
    await save();
    expect((await row(703)).toJson()['future_field'], 7);
  });

  test('画面の一覧は画像を持たないが、DBの画像は表の保存で消えない', () async {
    await saveGraph();
    final inMemory = app.records.firstWhere((r) => r.rack == 703);
    expect(inMemory.graph!.previewPng, isNull);
    expect(inMemory.graph!.hasPreview, isTrue);
    await save(); // 同じ数値の表の取り込み直し
    expect(await db.loadPreview(old.key), png);
    expect((await row(703)).graph!.curve, isNotNull);
  });

  test('まとめて削除のあとに別の保存をしても、ゴミ箱から画像ごと戻せる', () async {
    await saveGraph();
    await app.deleteGroup(day: old.day, store: old.store);
    await save(rack: 708); // 取り消しの控えはこれで上書きされる
    final batch = (await app.trashBatches()).firstWhere(
      (b) => b.kind == TrashKind.delete,
    );
    expect(batch.count, 1);
    final text = await app.restoreTrash(batch);
    expect(text, contains('1台を戻しました'));
    expect(await db.loadPreview(old.key), png);
    expect(app.records.map((r) => r.rack), containsAll([703, 708]));
    expect(
      (await app.trashBatches()).where((b) => b.batchId == batch.batchId),
      isEmpty,
    );
  });

  test('上書きで外れたグラフは、今の内容をゴミ箱に残して戻せる', () async {
    await saveGraph();
    await save(games: 4000); // 数値が変わりグラフが外れる
    // グラフの取り込み直し（前のグラフ）と、表の取り込み直しの2回分がある。
    final batch = (await app.trashBatches()).firstWhere(
      (b) => b.label.contains('表の取り込み直し'),
    );
    await app.restoreTrash(batch);
    expect((await row(703)).games, 3000);
    expect(await db.loadPreview(old.key), png);
    final trash = await app.trashBatches();
    expect(trash.map((b) => b.label), contains(contains('戻す前の内容')));
  });

  test('ゴミ箱は7日より古いものを起動時に消す', () async {
    await app.deleteGroup(day: old.day, store: old.store);
    await db.purgeTrash(DateTime.now().add(const Duration(days: 1)));
    expect(await app.trashBatches(), isEmpty);
  });

  test('確認なしで保存すると外れるグラフの数を数える', () async {
    WebTableExtraction table(int games) => WebTableExtraction(
      sourceUrl: '',
      expectedCount: null,
      store: old.store,
      day: old.day,
      machine: old.machine,
      rows: [
        EditableRow(
          rack: 703,
          games: games,
          bb: 20,
          rb: 5,
          maxHold: null,
          previousStart: null,
        ),
      ],
    );
    expect(app.graphsDroppedBy(table(3000)), 0);
    expect(app.graphsDroppedBy(table(4000)), 1);
  });

  test('書き出したときの時刻を残す', () async {
    expect(app.lastBackupExport, isNull);
    final state = <String, String>{
      'last_backup_export': DateTime.utc(2026, 9, 26, 14).toIso8601String(),
    };
    await db.applyChanges(ChangeSet(state: state));
    await app.initialize();
    expect(app.lastBackupExport, DateTime.utc(2026, 9, 26, 14).toLocal());
  });
}

extension on SlotRecord {
  SlotRecord copyWithoutGraphAndSetting() => SlotRecord(
    store: store,
    day: day,
    machine: machine,
    rack: rack,
    games: games,
    bb: bb,
    rb: rb,
    maxHold: maxHold,
    previousStart: previousStart,
  );
}
