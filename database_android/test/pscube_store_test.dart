import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  late Directory dir;
  late PscubeStore store;
  const day = '2026-10-01';
  final machine = <String, dynamic>{
    'store': 'c740601',
    'rate': '20',
    'machine': '試験機種',
    'expected_count': 1,
    'url': '${PscubeStore.root}cgi-bin/nc-v05-011.php?cd_ps=2&bai=20',
  };
  Map<String, dynamic> record([String date = day]) => {
    'store': 'c740601',
    'rate': '20',
    'machine': '試験機種',
    'rack': 1526,
    'day': date,
    'bb': 13,
    'rb': 5,
    'at_art': 0,
    'games': 1854,
    'my': 1921,
    'observed_at': '2026-10-01T12:00:00+09:00',
    'detail_url':
        '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=1526#${date.replaceAll('-', '')}',
    'graph': {
      'kind': 'overview',
      'zero_y': 10,
      'points': [
        [0, 10],
        [1, 8],
      ],
    },
  };
  String page(
    String url,
    List<Map<String, dynamic>> machines, [
    List<Map<String, dynamic>> records = const [],
  ]) => jsonEncode({
    'format': 'pscube-viewer',
    'version': 1,
    'source_url': url,
    'machines': machines,
    'records': records,
  });
  Future<String> seedRack() async {
    await store.importPage(
      page(PscubeStore.index, [machine]),
      PscubeStore.index,
    );
    await store.importPage(
      page(machine['url'], [machine], [record()]),
      machine['url'],
    );
    final history = [
      for (var i = 0; i < 7; i++)
        record(
          DateTime.utc(
            2026,
            10,
            1,
          ).subtract(Duration(days: i)).toIso8601String().substring(0, 10),
        ),
    ];
    for (final row in history) {
      (row['graph'] as Map)['kind'] = 'daily';
    }
    final payload = page(record()['detail_url'], [
      {
        ...machine,
        'url': (machine['url'] as String).replaceAll('cd_ps=2&', ''),
      },
    ], history);
    await store.importPage(payload, record()['detail_url']);
    return payload;
  }

  Future<Map<String, dynamic>> exported() async => jsonDecode(
    await (await store.exportViewer(path: '${dir.path}/viewer.json'))
        .readAsString(),
  );

  setUp(() async {
    sqfliteFfiInit();
    dir = await Directory.systemTemp.createTemp('pscube_test');
    store = await PscubeStore.open(
      path: '${dir.path}/pscube.sqlite3',
      factory: databaseFactoryFfi,
    );
  });
  tearDown(() async {
    await store.close();
    await dir.delete(recursive: true);
  });

  test('現在の機種URLから設置台数を読み取り、記録や保存値を変えない', () async {
    final known = {...machine, 'expected_count': 31};
    final other = {
      ...machine,
      'machine': '別機種',
      'url': '${machine['url']}&nmk_kisyu=other',
    };
    await store.importPage(
      page(PscubeStore.index, [known, other]),
      PscubeStore.index,
    );
    final before = {
      for (final table in ['machines', 'records', 'state'])
        table: await store.db.query(table),
    };
    expect(await store.installationCount('${machine['url']}#scroll=6'), 31);
    expect(await store.installationCount(other['url'] as String), 1);
    expect(
      await store.installationCount(
        (machine['url'] as String).replaceFirst(
          'cd_ps=2&bai=20',
          'bai=20&cd_ps=2',
        ),
      ),
      31,
    );
    expect(
      await store.installationCount(
        (machine['url'] as String).replaceFirst('bai=20', 'bai=5'),
      ),
      isNull,
    );
    expect(await store.installationCount(PscubeStore.index), isNull);
    for (final table in before.keys) {
      expect(await store.db.query(table), before[table]);
    }
  });

  test('未登録URLの設置台数は推測せず、別店舗を拒否する', () async {
    expect(await store.installationCount(machine['url'] as String), isNull);
    expect(
      store.installationCount(
        (machine['url'] as String).replaceFirst('c740601', 'c999999'),
      ),
      throwsFormatException,
    );
  });

  test('一覧・台別7日・再読込・JSON書き出しと保存復元', () async {
    final payload = await seedRack();
    await store.importPage(payload, record()['detail_url']);
    expect((await store.nextTarget(day)).url, isNull);
    final data = await exported();
    expect(data['records'], hasLength(7));
    expect(data['records'][0]['my'], 1921);
    await store.close();
    store = await PscubeStore.open(
      path: '${dir.path}/pscube.sqlite3',
      factory: databaseFactoryFfi,
    );
    expect((await store.nextTarget(day)).url, isNull);
  });

  test('数値更新は取得済みを解除し、古い詳細と結び付けない', () async {
    await seedRack();
    final fresh = record()
      ..['games'] = 2000
      ..['observed_at'] = '2026-10-01T13:00:00+09:00';
    final result = await store.importPage(
      page(machine['url'], [machine], [fresh]),
      machine['url'],
    );
    expect(result.nextUrl, record()['detail_url']);
    expect(
      ((await exported())['records'] as List).singleWhere(
        (r) => r['day'] == day,
      )['graph']['kind'],
      'overview',
    );
  });

  test('古い一覧・同じ数値は取得済みと詳細を保持する', () async {
    await seedRack();
    for (final fresh in [
      record()..['observed_at'] = '2026-10-01T13:00:00+09:00',
      record()
        ..['games'] = 1000
        ..['observed_at'] = '2026-10-01T11:00:00+09:00',
    ]) {
      await store.importPage(
        page(machine['url'], [machine], [fresh]),
        machine['url'],
      );
      expect((await store.nextTarget(day)).url, isNull);
    }
    expect((await exported())['records'][0]['graph']['kind'], 'daily');
    expect((await exported())['records'][0]['games'], 1854);
  });

  test('途中一覧・URL不一致では一件も保存しない', () async {
    await store.importPage(
      page(PscubeStore.index, [
        {...machine, 'expected_count': 2},
      ]),
      PscubeStore.index,
    );
    await expectLater(
      store.importPage(
        page(machine['url'], [machine], [record()]),
        machine['url'],
      ),
      throwsFormatException,
    );
    await expectLater(
      store.importPage(
        page(machine['url'], [machine], [record()]),
        PscubeStore.index,
      ),
      throwsFormatException,
    );
    expect((await exported())['records'], isEmpty);
  });

  test('台番号違い・連続していない7日・壊れたグラフを拒否する', () async {
    final payload = await seedRack();
    final before = await exported();
    final wrong = jsonDecode(payload) as Map<String, dynamic>;
    wrong['source_url'] = (wrong['source_url'] as String).replaceAll(
      '1526',
      '1527',
    );
    await expectLater(
      store.importPage(jsonEncode(wrong), wrong['source_url']),
      throwsFormatException,
    );
    final broken = jsonDecode(payload) as Map<String, dynamic>;
    broken['records'][6] = record('2026-09-20');
    await expectLater(
      store.importPage(jsonEncode(broken), record()['detail_url']),
      throwsFormatException,
    );
    final badGraph = record()
      ..['graph'] = {
        'kind': 'daily',
        'zero_y': 10,
        'points': [
          [2, 10],
          [1, 8],
        ],
      };
    await expectLater(
      store.importPage(
        page(machine['url'], [machine], [badGraph]),
        machine['url'],
      ),
      throwsFormatException,
    );
    // 書き出しの時刻は毎回変わるので、中身（機種・台・印）だけを比べる。
    expect(await exported(), {...before, 'exported_at': anything});
  });

  test('並行取り込みと共有も保存順を守り、失敗後もキューが進む', () async {
    await seedRack();
    final newer = record()
      ..['games'] = 2000
      ..['observed_at'] = '2026-10-01T14:00:00+09:00';
    final older = record()..['observed_at'] = '2026-10-01T13:00:00+09:00';
    final imports = [
      store.importPage(
        page(machine['url'], [machine], [newer]),
        machine['url'],
      ),
      store.importPage(
        page(machine['url'], [machine], [older]),
        machine['url'],
      ),
    ];
    final file = store.exportViewer(path: '${dir.path}/viewer.json');
    await Future.wait(imports);
    expect(
      (jsonDecode(await (await file).readAsString())['records'] as List)
          .singleWhere((r) => r['day'] == day)['games'],
      2000,
    );
    await expectLater(
      store.importPage('{}', PscubeStore.index),
      throwsFormatException,
    );
    expect((await store.nextTarget(day)).url, record()['detail_url']);
  });

  test('当たりが1回もない台（0回転を含む）は数値を保存し、台別7日分は取りに行かない', () async {
    final m = {...machine, 'expected_count': 2};
    await store.importPage(page(PscubeStore.index, [m]), PscubeStore.index);
    final zero = record()
      ..['rack'] = 1527
      ..['detail_url'] =
          '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=1527#20261001'
      ..['bb'] = 0
      ..['rb'] = 0
      ..['at_art'] = 0
      ..['games'] = 0
      ..['my'] = 0;
    final result = await store.importPage(
      page(
        machine['url'],
        [
          {...machine, 'expected_count': null},
        ],
        [record(), zero],
      ),
      machine['url'],
    );
    expect(result.nextUrl, record()['detail_url']);
    expect(result.remaining, 1);
    expect((await exported())['records'], hasLength(2));
    expect(PscubeStore.noHits({'bb': 0, 'rb': 0, 'at_art': 1}), isFalse);
  });

  test('沖ドキ（半角も）は回る対象にせず、表も保存しない（メルヘンと同じ約束）', () async {
    final oki = {
      ...machine,
      'machine': '沖ﾄﾞｷ!GOLD-30',
      'url':
          '${PscubeStore.root}cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&nmk_kisyu=oki',
    };
    final result = await store.importPage(
      page(PscubeStore.index, [oki, machine]),
      PscubeStore.index,
    );
    expect(result.remaining, 1);
    expect((await store.nextTarget(day)).url, machine['url']);
    final okiRecord = record()..['machine'] = '沖ﾄﾞｷ!GOLD-30';
    await expectLater(
      store.importPage(
        page(
          oki['url'] as String,
          [
            {...oki, 'expected_count': null},
          ],
          [okiRecord],
        ),
        oki['url'] as String,
      ),
      throwsFormatException,
    );
    expect((await exported())['records'], isEmpty);
    expect(PscubeStore.isExcludedMachine('ｵｷﾄﾞｷ!'), isTrue);
    expect(PscubeStore.isExcludedMachine('ﾏｲｼﾞｬｸﾞﾗｰV'), isFalse);
  });

  group('バックアップ・同期（database/PSCUBE_SYNC.md）', () {
    Future<PscubeStore> other() => PscubeStore.open(
      path: '${dir.path}/other.sqlite3',
      factory: databaseFactoryFfi,
    );

    test('ファイル名はメルヘンと重ならず、書き出しには種別・出どころ・時刻・取り込み済みの印が付く', () async {
      expect(
        PscubeStore.backupFileName(DateTime(2026, 10, 1, 9, 5, 7)),
        'pscube-backup-android-20261001-090507.json',
      );
      await seedRack();
      final data = await exported();
      expect(data['format'], 'pscube-viewer');
      expect(data['kind'], 'backup');
      expect(data['source'], 'android');
      expect(
        data['exported_at'],
        matches(
          RegExp(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$'),
        ),
      );
      expect(data['rack_captures'], hasLength(1));
    });

    test('別の端末へ往復でき、印も引き継がれる。2回目は変化なし', () async {
      await seedRack();
      final text = jsonEncode(await exported());
      final second = await other();
      addTearDown(second.close);
      final first = await second.importBackup(text);
      expect((first.added, first.updated, first.unchanged), (7, 0, 0));
      expect((await second.nextTarget(day)).url, isNull);
      final again = await second.importBackup(text);
      expect((again.added, again.updated, again.unchanged), (0, 0, 7));
    });

    test('軽い閲覧用ファイル・他店・重複・孤立・不正な印・形式違いは何も保存しない', () async {
      await seedRack();
      final good = await exported();
      Map<String, dynamic> copy() =>
          jsonDecode(jsonEncode(good)) as Map<String, dynamic>;
      final light = copy()..['kind'] = 'viewer';
      final otherShop = copy();
      (otherShop['machines'] as List)[0]['store'] = 'c1';
      final lastBad = copy();
      ((lastBad['records'] as List).last as Map)['rack'] = 0;
      final duplicate = copy();
      (duplicate['records'] as List).add((duplicate['records'] as List).first);
      final orphan = copy()..['machines'] = [];
      final strayMark = copy()..['rack_captures'] = ['["x"]'];
      final second = await other();
      addTearDown(second.close);
      for (final bad in [
        light,
        otherShop,
        lastBad,
        duplicate,
        orphan,
        strayMark,
        {'format': 'database-backup', 'version': 1},
      ]) {
        await expectLater(
          second.importBackup(jsonEncode(bad)),
          throwsFormatException,
        );
      }
      await expectLater(
        second.importBackup('これはJSONではない'),
        throwsFormatException,
      );
      expect((await second.nextTarget(day)).remaining, 0);
      expect(
        (await second.importBackup(jsonEncode(good))).added,
        7,
        reason: '不正なファイルのあとでも、正しいファイルはそのまま入る',
      );
    });

    test('古い数値で新しい数値を上書きせず、自分の機種タイプを残し、数値が変わった台は取得済みを外す', () async {
      await seedRack();
      final newer = record()
        ..['games'] = 4000
        ..['observed_at'] = '2026-10-01T20:00:00+09:00';
      await store.importPage(
        page(
          machine['url'],
          [
            {...machine, 'machine_type': 'normal'},
          ],
          [newer],
        ),
        machine['url'],
      );
      final older = {
        'format': 'pscube-viewer',
        'version': 1,
        'kind': 'backup',
        'machines': [
          {...machine, 'machine_type': 'other'},
        ],
        'records': [
          record()
            ..['games'] = 3500
            ..['observed_at'] = '2026-10-01T15:00:00+09:00',
        ],
      };
      final kept = await store.importBackup(jsonEncode(older));
      expect(kept.keptLocal, 1);
      var data = await exported();
      expect(
        (data['records'] as List).singleWhere((r) => r['day'] == day)['games'],
        4000,
      );
      expect((data['machines'] as List).single['machine_type'], 'normal');
      final newest = {
        ...older,
        'records': [
          record()
            ..['games'] = 5000
            ..['observed_at'] = '2026-10-01T22:00:00+09:00',
        ],
        'rack_captures': <String>[],
      };
      final changed = await store.importBackup(jsonEncode(newest));
      expect(changed.updated, 1);
      expect((await store.nextTarget(day)).url, record()['detail_url']);
      data = await exported();
      expect(
        (data['records'] as List).singleWhere((r) => r['day'] == day)['games'],
        5000,
      );
    });

    test('印の無い古い書き出しは、台別7日分のグラフがある日を取り込み済みとみなす', () async {
      final daily = record()
        ..['graph'] = {
          'kind': 'daily',
          'zero_y': 10,
          'points': [
            [0, 10],
            [1, 6],
          ],
        };
      final second = await other();
      addTearDown(second.close);
      await second.importBackup(
        jsonEncode({
          'format': 'pscube-viewer',
          'version': 1,
          'machines': [machine],
          'records': [daily],
        }),
      );
      expect((await second.nextTarget(day)).url, isNull);
    });

    test('最後にバックアップした時刻は共有を終えたときだけ残る', () async {
      expect(await store.lastBackupAt(), isNull);
      await store.markBackedUp(DateTime.utc(2026, 10, 1, 3));
      expect(
        (await store.lastBackupAt())!.toUtc(),
        DateTime.utc(2026, 10, 1, 3),
      );
    });
  });
}
