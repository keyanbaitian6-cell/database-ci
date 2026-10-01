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
    expect(await exported(), before);
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
}
