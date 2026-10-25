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

  test('台別で取得した差枚をMYと別に保存し、一覧の再取り込みでも保持する', () async {
    final payload = jsonDecode(await seedRack()) as Map<String, dynamic>;
    final records = payload['records'] as List<dynamic>;
    (records[0] as Map<String, dynamic>)['net_medals'] = 14118;
    (records[1] as Map<String, dynamic>)['net_medals'] = -250;
    await store.importPage(jsonEncode(payload), record()['detail_url']);
    await store.importPage(
      page(machine['url'], [machine], [record()]),
      machine['url'],
    );
    final saved = (await exported())['records'] as List<dynamic>;
    final selected = saved.singleWhere((row) => row['day'] == day);
    expect(selected['net_medals'], 14118);
    expect(selected['my'], 1921);
    expect(
      saved.singleWhere((row) => row['day'] == '2026-09-30')['net_medals'],
      -250,
    );
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

  test('一覧のスクロール位置（#以降）が変わっても同じページとして保存し、台別の日付は区別する', () async {
    final list = Uri.parse(PscubeStore.index);
    expect(pscubeSamePage(list, list.replace(fragment: 'scroll=1200')), isTrue);
    expect(
      pscubeSamePage(
        list.replace(fragment: 'scroll=0'),
        list.replace(fragment: 'scroll=1200'),
      ),
      isTrue,
    );
    final rack = Uri.parse(record()['detail_url']);
    expect(pscubeSamePage(rack, rack), isTrue);
    expect(pscubeSamePage(rack, rack.replace(fragment: '20260930')), isFalse);
    expect(pscubeSamePage(rack, rack.removeFragment()), isFalse);
    expect(pscubeSamePage(list, Uri.parse(machine['url'] as String)), isFalse);
    // 機種名（日本語）が%の形でも元の文字の形でも同じページ。別の機種名は別のページ。
    final named = '${machine['url']}&nmk_kisyu=L東京喰種';
    expect(
      pscubeSamePage(
        Uri.parse(named),
        Uri.parse('${Uri.encodeFull(named)}#scroll=40'),
      ),
      isTrue,
    );
    expect(
      pscubeSamePage(
        Uri.parse(named),
        Uri.parse('${machine['url']}&nmk_kisyu=ﾏｲｼﾞｬｸﾞﾗｰV'),
      ),
      isFalse,
    );

    // 読み取り後にサイトがスクロール位置を書き換えても、一覧を保存する。
    await store.importPage(
      page('${PscubeStore.index}#scroll=1200', [machine]),
      PscubeStore.index,
    );
    expect(await store.installationCount(machine['url'] as String), 1);
    // 台別ページの日付が違う結果は保存しない。
    await store.importPage(
      page(machine['url'], [machine], [record()]),
      machine['url'],
    );
    final wrongDay = jsonDecode(await seedRack()) as Map<String, dynamic>;
    wrongDay['source_url'] = (wrongDay['source_url'] as String).replaceAll(
      '#20261001',
      '#20260930',
    );
    await expectLater(
      store.importPage(jsonEncode(wrongDay), record()['detail_url']),
      throwsFormatException,
    );
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
    // 出力ファイルとAndroidの書き出し時刻だけは毎回変わる。台・印・他工程は厳密に比べる。
    expect(await exported(), {
      ...before,
      'exported_at': anything,
      'sync_status': {
        ...before['sync_status'] as Map,
        'writes': [
          for (final w in before['sync_status']['writes'] as List)
            {...w as Map, 'at': anything},
        ],
      },
    });
  });

  test('新台の全空欄の過去日だけを省略し、旧機種の同番号の履歴を維持する', () async {
    final oldMachine = {
      ...machine,
      'machine': '旧機種',
      'url': '${machine['url']}&nmk_kisyu=old',
    };
    final oldRecord = {...record('2026-09-30'), 'machine': '旧機種'};
    await store.importPage(
      page(PscubeStore.index, [oldMachine, machine]),
      PscubeStore.index,
    );
    await store.importPage(
      page(oldMachine['url'] as String, [oldMachine], [oldRecord]),
      oldMachine['url'] as String,
    );
    await store.importPage(
      page(PscubeStore.index, [machine]),
      PscubeStore.index,
    );
    await store.importPage(
      page(machine['url'] as String, [machine], [record()]),
      machine['url'] as String,
    );
    final missing = [
      for (var i = 1; i < 7; i++)
        DateTime.utc(
          2026,
          10,
          1,
        ).subtract(Duration(days: i)).toIso8601String().substring(0, 10),
    ];
    final detail = record()..['net_medals'] = 125;
    (detail['graph'] as Map)['kind'] = 'daily';
    final payload = jsonDecode(
      page(record()['detail_url'] as String, [machine], [detail]),
    ) as Map<String, dynamic>;
    final before = await exported();
    for (final invalid in <dynamic>[
      null,
      missing.sublist(1),
      [...missing, missing.first],
      [day, ...missing.skip(1)],
      ['2020-01-01', ...missing.skip(1)],
      [
        [missing.first],
        ...missing.skip(1),
      ],
    ]) {
      await expectLater(
        store.importPage(
          jsonEncode({...payload, 'missing_history_days': invalid}),
          record()['detail_url'] as String,
        ),
        throwsFormatException,
      );
    }
    expect(await exported(), {
      ...before,
      'exported_at': anything,
      'sync_status': {
        ...before['sync_status'] as Map,
        'writes': [
          for (final w in before['sync_status']['writes'] as List)
            {...w as Map, 'at': anything},
        ],
      },
    });
    final result = await store.importPage(
      jsonEncode({...payload, 'missing_history_days': missing}),
      record()['detail_url'] as String,
    );
    expect(result.saved, 1);
    expect((await store.nextTarget(day)).url, isNull);
    final after = await exported();
    expect(after['records'], hasLength(2));
    final oldSaved = (after['records'] as List).singleWhere(
      (r) => r['machine'] == '旧機種',
    );
    expect(oldSaved['games'], oldRecord['games']);
    expect(oldSaved['day'], '2026-09-30');
    final newSaved = (after['records'] as List).singleWhere(
      (r) => r['machine'] == machine['machine'],
    );
    expect(newSaved['day'], day);
    expect(newSaved['net_medals'], 125);
    expect(newSaved['graph']['kind'], 'daily');
    final backup = await store.exportViewer(
      path: '${dir.path}/replacement.json',
    );
    final restored = await PscubeStore.open(
      path: '${dir.path}/replacement.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      await restored.importBackup(await backup.readAsString());
      await restored.importPage(
        page(PscubeStore.index, [machine]),
        PscubeStore.index,
      );
      final restoredExport = jsonDecode(
        await (await restored.exportViewer(path: '${dir.path}/restored.json'))
            .readAsString(),
      );
      expect(restoredExport['records'], hasLength(2));
      expect((await restored.nextTarget(day)).url, isNull);
    } finally {
      await restored.close();
    }
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

  test('手動のときは、飛ばした上の機種へ戻らず、保存したページの次へ進む（最後まで来たら最初へ回る）', () async {
    Map<String, dynamic> named(String name) => {
      ...machine,
      'machine': name,
      'expected_count': 2,
      'url': '${PscubeStore.root}cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&k=$name',
    };
    final a = named('甲機'), b = named('乙機'), c = named('丙機');
    await store.importPage(
      page(PscubeStore.index, [a, b, c]),
      PscubeStore.index,
    );
    Map<String, dynamic> rec(
      Map<String, dynamic> m,
      int rack, [
      String d = day,
    ]) => record(d)
      ..['machine'] = m['machine']
      ..['rack'] = rack
      ..['detail_url'] =
          '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=$rack&k=${m['machine']}#${d.replaceAll('-', '')}';
    Future<String?> saveTable(Map<String, dynamic> m, bool manual) async =>
        (await store.importPage(
          page(
            m['url'] as String,
            [
              {...m, 'expected_count': null},
            ],
            [rec(m, 100), rec(m, 101)],
          ),
          m['url'] as String,
          manual: manual,
        )).nextUrl;
    Future<String?> saveRack(Map<String, dynamic> m, int rack) async {
      final url = rec(m, rack)['detail_url'] as String;
      return (await store.importPage(
        page(
          url,
          [
            {...m, 'expected_count': null},
          ],
          [
            for (var ago = 0; ago < 7; ago++)
              rec(
                m,
                rack,
                DateTime.parse('${day}T00:00:00Z')
                    .subtract(Duration(days: ago))
                    .toIso8601String()
                    .substring(0, 10),
              ),
          ],
        ),
        url,
        manual: true,
      )).nextUrl;
    }

    String url(Map<String, dynamic> m, int rack) =>
        rec(m, rack)['detail_url'] as String;
    // 甲機（一覧の一番上）は飛ばして、乙機・丙機だけを取り込む。
    expect(await saveTable(b, false), a['url'], reason: '自動（手動でない）は一覧の最初の未取得');
    expect(await saveTable(b, true), url(b, 100), reason: '手動：保存した機種の台へ');
    expect(await saveRack(b, 100), url(b, 101), reason: '手動：同じ機種の次の台番');
    expect(await saveRack(b, 101), c['url'], reason: '乙機が済んだら次の機種（丙機）の表へ');
    expect(await saveTable(c, true), url(c, 100));
    expect(await saveRack(c, 100), url(c, 101));
    expect(await saveRack(c, 101), a['url'], reason: '最後の機種まで来たら、取りこぼした甲機へ回る');
  });

  test('昼に取った機種を、夜の取り込みで「済み」として飛ばさない（PC版と同じ）', () async {
    Map<String, dynamic> named(String name) => {
      ...machine,
      'machine': name,
      'expected_count': 1,
      'url': '${PscubeStore.root}cgi-bin/nc-v05-011.php?cd_ps=2&bai=20&k=$name',
    };
    final a = named('甲機'), b = named('乙機'), c = named('丙機');
    await store.importPage(
      page(PscubeStore.index, [a, b, c]),
      PscubeStore.index,
    );
    Map<String, dynamic> rec(
      Map<String, dynamic> m,
      int rack,
      String time, [
      String d = day,
      int games = 1854,
    ]) => record(d)
      ..['machine'] = m['machine']
      ..['rack'] = rack
      ..['games'] = games
      ..['observed_at'] = '2026-10-01T$time:00+09:00'
      ..['detail_url'] =
          '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=$rack&k=${m['machine']}#${d.replaceAll('-', '')}';
    final fresh = <String, String>{};
    Future<String?> table(
      Map<String, dynamic> m,
      int rack,
      String time, {
      int games = 1854,
      Map<String, String>? since,
    }) async => (await store.importPage(
      page(
        m['url'] as String,
        [
          {...m, 'expected_count': null},
        ],
        [rec(m, rack, time, day, games)],
      ),
      m['url'] as String,
      direction: 'bottom',
      freshSince: since,
    )).nextUrl;
    Future<String?> rack(
      Map<String, dynamic> m,
      int no,
      String time, {
      Map<String, String>? since,
    }) async {
      final url = rec(m, no, time)['detail_url'] as String;
      return (await store.importPage(
        page(
          url,
          [
            {...m, 'expected_count': null},
          ],
          [
            for (var i = 0; i < 7; i++)
              rec(
                m,
                no,
                time,
                DateTime.parse('${day}T00:00:00Z')
                    .subtract(Duration(days: i))
                    .toIso8601String()
                    .substring(0, 10),
              ),
          ],
        ),
        url,
        direction: 'bottom',
        freshSince: since,
      )).nextUrl;
    }

    String detail(Map<String, dynamic> m, int no) =>
        rec(m, no, '00:00')['detail_url'] as String;
    // 昼（11:12）に3機種とも取った。
    for (final (i, m) in [a, b, c].indexed) {
      await table(m, 100 + i, '11:12');
      await rack(m, 100 + i, '11:12');
    }
    expect(
      (await store.nextTarget(day, 'bottom')).url,
      isNull,
      reason: '基準が無ければ、これまでどおり済み',
    );
    // 夜（23:12）に下から：丙機の全台一覧で基準が分かり、数値が変わった台は台別ページも取り直す。
    expect(
      await table(c, 102, '23:12', games: 6000, since: fresh),
      detail(c, 102),
    );
    expect(fresh, {day: '2026-10-01T23:12:00+09:00'});
    expect(
      await rack(c, 102, '23:12', since: fresh),
      b['url'],
      reason: '昼の数値のままの乙機を飛ばさない',
    );
    expect(
      await table(b, 101, '23:12', since: fresh),
      a['url'],
      reason: '数値が変わっていなければ台別ページは取り直さない',
    );
    expect(await table(a, 100, '23:12', since: fresh), isNull);
    expect(
      (await store.nextTarget(day, 'bottom', null, fresh[day])).url,
      isNull,
      reason: '今回取った分は、その後サイトの時刻が進んでも取り直さない（終わらなくならない）',
    );
    expect(
      pscubeStaleCutoff('2026-10-01', '2026-10-03T09:00:00+09:00'),
      DateTime.parse('2026-10-01T23:00:00+09:00').millisecondsSinceEpoch,
      reason: '終わった日は、その日の23時より後に取った分が最終',
    );
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

    test('イベントカレンダー：先の日・期間に全貸玉で付け、同じ名前は時刻を変えず、何も無い日に消した印を作らない', () async {
      await seedRack();
      final at = DateTime.utc(2026, 10, 8, 12);
      await store.setDateEventDays(
        ['2026-10-20', '2026-10-21'],
        ' 華の日 ',
        now: at,
      );
      expect(
        await store.dateEventFor('2026-10-20'),
        '華の日',
        reason: '記録の無い先の日にも入る',
      );
      expect(await store.dateEventFor('2026-10-21'), '華の日');
      await store.setDateEventDays(
        ['2026-10-20', '2026-10-22'],
        '華の日',
        now: at.add(const Duration(hours: 1)),
      );
      await store.setDateEventDays(
        ['2026-10-25'],
        null,
        now: at.add(const Duration(hours: 1)),
      );
      final events = {
        for (final e in (await exported())['date_events'] as List)
          (e as Map)['day']: e,
      };
      expect(
        events['2026-10-20']!['updated_at'],
        '2026-10-08T12:00:00.000Z',
        reason: '同じ名前は時刻そのまま',
      );
      expect(events['2026-10-22']!['updated_at'], '2026-10-08T13:00:00.000Z');
      expect(
        events.containsKey('2026-10-25'),
        isFalse,
        reason: '何も無い日の「イベントなし」は印を作らない',
      );
      // カレンダーの元データ：閲覧ページと同じ形（記録とイベント）。
      final data = await store.calendarData();
      expect(data['format'], 'pscube-viewer');
      expect(data['records'], (await exported())['records']);
      expect((data['date_events'] as List).length, 3);
      expect(store.setDateEventDays(const [], '華の日'), throwsFormatException);
      expect(
        store.setDateEventDays(List.filled(63, '2026-10-20'), '華の日'),
        throwsFormatException,
      );
      final empty = await PscubeStore.open(
        path: '${dir.path}/empty-days.sqlite3',
        factory: databaseFactoryFfi,
      );
      addTearDown(empty.close);
      expect(
        empty.setDateEventDays(['2026-10-20'], '華の日'),
        throwsFormatException,
      );
    });

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

    test('イベント名：全貸玉に付け、書き出し・読み込みで新しい方が勝ち、古い末尾イベの印も読める', () async {
      await seedRack();
      final at = DateTime.utc(2026, 10, 6, 12);
      await store.setDateEvent(day, ' 周年 ', now: at);
      expect(await store.dateEventFor(day), '周年');
      await store.setDateEvent(
        '2026-09-30',
        '末尾イベ',
        now: at.add(const Duration(minutes: 1)),
      );
      expect(await store.dateEventNames(), ['末尾イベ', '周年'], reason: '新しく使った順');
      final data = await exported();
      final events = data['date_events'] as List;
      expect(events, hasLength(2), reason: '記録のある貸玉（20）ごとに1件');
      expect(events.first, {
        'store': 'c740601',
        'rate': '20',
        'day': day,
        'name': '周年',
        'updated_at': '2026-10-06T12:00:00.000Z',
      });
      expect(data['suffix_events'], isNull);
      // 別の端末へ：イベント名も引き継ぐ。2回目は変化なし。
      final second = await other();
      addTearDown(second.close);
      await second.importBackup(jsonEncode(data));
      expect(await second.dateEventFor(day), '周年');
      expect(await second.dateEventFor('2026-09-30'), '末尾イベ');
      // こちらで消した（新しい）ものは、古いバックアップを読んでも戻らない。
      await second.setDateEvent(
        day,
        null,
        now: at.add(const Duration(hours: 1)),
      );
      await second.importBackup(jsonEncode(data));
      expect(await second.dateEventFor(day), isNull);
      expect(await second.dateEventNames(), ['末尾イベ'], reason: '消した名前は候補から外れる');
      // 相手の新しい名前は取り込む。
      await store.setDateEvent(
        day,
        '周年2',
        now: at.add(const Duration(hours: 2)),
      );
      await second.importBackup(jsonEncode(await exported()));
      expect(await second.dateEventFor(day), '周年2');
      // 以前の閲覧ページの末尾イベの印（suffix_events）は「末尾イベ」として読む。
      final legacy = await exported()
        ..remove('date_events')
        ..['suffix_events'] = [
          {
            'store': 'c740601',
            'rate': '20',
            'day': '2026-09-29',
            'enabled': true,
            'updated_at': '2026-10-02T00:00:00Z',
          },
        ];
      await second.importBackup(jsonEncode(legacy));
      expect(await second.dateEventFor('2026-09-29'), '末尾イベ');
      // 長すぎる名前・改行は保存しない。記録が無ければ付けられない。
      expect(store.setDateEvent(day, 'x' * 61), throwsFormatException);
      expect(store.setDateEvent(day, 'a\nb'), throwsFormatException);
      final empty = await PscubeStore.open(
        path: '${dir.path}/empty.sqlite3',
        factory: databaseFactoryFfi,
      );
      addTearDown(empty.close);
      expect(empty.setDateEvent(day, '周年'), throwsFormatException);
      // 形の違うイベント名を含むバックアップは、何も保存しない。
      final broken = await exported()
        ..['date_events'] = [
          {
            'store': 'c740601',
            'rate': '20',
            'day': day,
            'name': 3,
            'updated_at': 'bad',
          },
        ];
      final before = await second.dateEvents();
      await expectLater(
        second.importBackup(jsonEncode(broken)),
        throwsFormatException,
      );
      expect(
        [for (final e in await second.dateEvents()) e.toJson()],
        [for (final e in before) e.toJson()],
      );
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

  test('上から・下からで、次に開く機種を一覧の端から選ぶ', () async {
    final second = {
      ...machine,
      'machine': '二つ目',
      'url': '${machine['url']}&nmk_kisyu=second',
    };
    final index = page(PscubeStore.index, [machine, second]);
    expect(
      (await store.importPage(index, PscubeStore.index)).nextUrl,
      machine['url'],
    );
    expect(
      (await store.importPage(
        index,
        PscubeStore.index,
        direction: 'bottom',
      )).nextUrl,
      second['url'],
    );
    expect((await store.nextTarget(day, 'top')).url, machine['url']);
    expect((await store.nextTarget(day, 'bottom')).url, second['url']);
    expect(
      () => store.importPage(index, PscubeStore.index, direction: 'sideways'),
      throwsFormatException,
    );
  });

  test('取り込み日を指定すると、違う日のページは保存せず、その日の未取得の先頭へ進む', () async {
    const yesterday = '2026-10-03', today = '2026-10-04';
    final second = {
      ...machine,
      'machine': '二つ目',
      'url': '${machine['url']}&nmk_kisyu=second',
    };
    await store.importPage(
      page(PscubeStore.index, [machine, second]),
      PscubeStore.index,
    );
    // 日付が変わったあと、サイトの表示は新しい日。取り込み日（昨日）を指定していると保存しない。
    expect(
      () => store.importPage(
        page(machine['url'], [machine], [record(today)]),
        machine['url'],
        expectedDay: yesterday,
      ),
      throwsA(
        isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('取り込み日は2026-10-03ですが、表示中は2026-10-04'),
        ),
      ),
    );
    expect(((await exported())['records'] as List), isEmpty);
    // 昨日の日付タブに合わせれば保存でき、次は昨日の台別ページ。
    final table = await store.importPage(
      page(machine['url'], [machine], [record(yesterday)]),
      machine['url'],
      expectedDay: yesterday,
    );
    expect(table.nextUrl, record(yesterday)['detail_url']);
    // 機種一覧を取り直しても、その日の基準の時刻が分かっていれば、最初の機種へ戻らず、昨日の未取得の先頭へ進む。
    final known = {yesterday: '2026-10-01T12:00:00+09:00'};
    final again = await store.importPage(
      page(PscubeStore.index, [machine, second]),
      PscubeStore.index,
      expectedDay: yesterday,
      freshSince: known,
    );
    expect(again.nextUrl, record(yesterday)['detail_url']);
    final bottom = await store.importPage(
      page(PscubeStore.index, [machine, second]),
      PscubeStore.index,
      expectedDay: yesterday,
      direction: 'bottom',
      freshSince: known,
    );
    expect(
      bottom.nextUrl,
      '${second['url']}#0;0;20261003;0;cd_dai;1;0;0',
      reason: '下からなら二つ目の機種から（全台一覧は取り込み日のタブで開く）',
    );
    // 基準の時刻がまだ無い（今回まだ1ページも保存していない）ときは、決めた向きの最初の機種で確かめる。
    final unknown = await store.importPage(
      page(PscubeStore.index, [machine, second]),
      PscubeStore.index,
      expectedDay: yesterday,
    );
    expect(unknown.nextUrl, '${machine['url']}#0;0;20261003;0;cd_dai;1;0;0');
    // 台別ページ：ハッシュの日が取り込み日と違えば保存しない。
    final history = [
      for (var i = 0; i < 7; i++)
        record(
          DateTime.utc(
            2026,
            10,
            3,
          ).subtract(Duration(days: i)).toIso8601String().substring(0, 10),
        ),
    ];
    final rackUrl = record(yesterday)['detail_url'] as String;
    final rack = page(rackUrl, [
      {
        ...machine,
        'url': (machine['url'] as String).replaceAll('cd_ps=2&', ''),
      },
    ], history);
    expect(
      () => store.importPage(rack, rackUrl, expectedDay: today),
      throwsFormatException,
    );
    await store.importPage(rack, rackUrl, expectedDay: yesterday);
  });

  // 2026-10-19 入れ替えの日に前日（10/18）を指定すると、新台は10/19のタブしか無く、サイトは10/19を選ぶ。
  // 以前は「対象のP’s CUBEページではありません」で止まり、新台が未取得の先頭に残り続けた（PC版と同じ試験）。
  test('取り込み日の日付タブが無い機種は、その日だけ飛ばして次へ進む', () async {
    const yesterday = '2026-10-18', today = '2026-10-19';
    final fresh = {
      ...machine,
      'machine': 'L魔法少女にあこがれて',
      'url': '${machine['url']}&nmk_kisyu=L魔法少女にあこがれて',
    };
    final second = {
      ...machine,
      'machine': '二つ目',
      'url': '${machine['url']}&nmk_kisyu=second',
    };
    await store.importPage(
      page(PscubeStore.index, [fresh, second]),
      PscubeStore.index,
    );
    // WebViewの住所は機種名の%が保存したリンクと違う形（二重）で、#以降はサイトが選んだ10/19。
    final shown =
        '${machine['url']}&nmk_kisyu=${Uri.encodeComponent(Uri.encodeComponent('L魔法少女にあこがれて'))}'
        '#3;0;20261019;0;cd_dai;1;0;664';
    String failed(List<String> tabs, [String? url]) => jsonEncode({
      'error': '1526番台の台別ページへのリンクがありません。',
      'source_url': url ?? shown,
      'available_days': tabs,
    });
    final result = await store.importPage(
      failed([today]),
      shown,
      expectedDay: yesterday,
    );
    expect(result.saved, 0);
    expect(
      result.skipped,
      contains('L魔法少女にあこがれては10/18の日付タブがサイトにありません（タブ：10/19'),
    );
    expect(result.nextUrl, '${second['url']}#0;0;20261018;0;cd_dai;1;0;0');
    expect((await exported())['records'], isEmpty, reason: '何も保存しない');
    expect((await store.nextTarget(yesterday)).remaining, 1);
    expect((await store.nextTarget(today)).remaining, 2, reason: 'ほかの日は今までどおり');
    // 飛ばさない：取り込み日のタブがある／タブより新しい日（早朝でタブがまだ出ていない）。
    for (final (tabs, target) in [
      ([yesterday, today], yesterday),
      (['2026-10-12', yesterday], today),
    ]) {
      expect(
        () => store.importPage(failed(tabs), shown, expectedDay: target),
        throwsA(
          isA<FormatException>().having(
            (e) => e.message,
            'message',
            contains('台別ページへのリンクがありません'),
          ),
        ),
      );
    }
    // 保存した機種一覧に無い機種は、飛ばさずに理由を出す。
    final unknown = '${machine['url']}&nmk_kisyu=X#3;0;20261019;0;cd_dai;1;0;0';
    expect(
      () => store.importPage(
        failed([today], unknown),
        unknown,
        expectedDay: yesterday,
      ),
      throwsA(
        isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('日付タブがこの機種にありません（タブ：10/19）'),
        ),
      ),
    );
  });

  // 増台（4台→6台）の翌日に前日を取り込む：過去の日の全台一覧にも今の6台が並び、増えた2台はその日の
  // 数値もリンクも無い（2026-10-19 利用者「前の日の台数が出てくることはない」）。0で埋めず残り4台を保存する。
  test('過去の日の全台一覧で、数値もリンクも無い台（増台）を除いて保存する', () async {
    const yesterday = '2026-10-18', today = '2026-10-19';
    final six = {...machine, 'expected_count': 6};
    await store.importPage(page(PscubeStore.index, [six]), PscubeStore.index);
    Map<String, dynamic> rack(int number, String date) => {
      ...record(date),
      'rack': number,
      'detail_url':
          '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=$number#${date.replaceAll('-', '')}',
    };
    String table(String date, List<int> numbers, List<int> missing) =>
        jsonEncode({
          ...jsonDecode(
            page(
              six['url'],
              [
                {...six, 'expected_count': null},
              ],
              [for (final n in numbers) rack(n, date)],
            ),
          ) as Map,
          'missing_racks': missing,
          'available_days': [yesterday, today],
        });
    final result = await store.importPage(
      table(yesterday, [1, 2, 3, 4], [5, 6]),
      six['url'],
      expectedDay: yesterday,
    );
    expect(result.saved, 4);
    expect(result.kind, '全台一覧（5・6番台はこの日の数値なし）');
    expect(result.nextUrl, rack(1, yesterday)['detail_url']);
    final next = await store.nextTarget(yesterday);
    expect((next.url, next.remaining), (rack(1, yesterday)['detail_url'], 4));
    // 今動いている日（タブの最新）では受け付けない。台数が合わなければ今までどおり止める。
    expect(
      () => store.importPage(
        table(today, [1, 2, 3, 4], [5, 6]),
        six['url'],
        expectedDay: today,
      ),
      throwsA(
        isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('5・6番台に数値と台別ページへのリンクがありません'),
        ),
      ),
    );
    expect(
      () => store.importPage(
        table(yesterday, [1, 2, 3, 4], [5]),
        six['url'],
        expectedDay: yesterday,
      ),
      throwsA(
        isA<FormatException>().having(
          (e) => e.message,
          'message',
          contains('表示 5 台、設置 6 台'),
        ),
      ),
    );
    // 6台そろった一覧を取り直したら、その日に無かった台の記録は消える（6台とも台別ページが未取得になる）。
    await store.importPage(
      table(yesterday, [1, 2, 3, 4, 5, 6], []),
      six['url'],
      expectedDay: yesterday,
    );
    expect((await store.nextTarget(yesterday)).remaining, 6);
    // 残り件数だけでは、古い印が残っていても通ってしまう。保存された印そのものを確かめる（2026-10-22）。
    final saved = await store.db.query(
      'state',
      where: 'key=?',
      whereArgs: [pscubeAbsentRacksKey],
    );
    expect(jsonDecode(saved.single['value'] as String), isEmpty);
  });

  // 全台一覧を保存できたら「タブなし」（absent_table_days）を外す（2026-10-22、PC版と同じ）。以前は外さず、一度「その日は
  // タブなし」と覚えた機種・日は、あとで正しい全台一覧を保存しても未取得から外れ続けた。
  group('全台一覧の保存で「タブなし」を外す', () {
    const tabs = ['2026-10-17', '2026-10-18', '2026-10-19'];
    final six = {
      ...machine,
      'machine': 'L東京喰種',
      'expected_count': 6,
      'url': '${machine['url']}&nmk_kisyu=six',
    };
    final other = {
      ...machine,
      'machine': 'ﾏｲｼﾞｬｸﾞﾗｰV',
      'url': '${machine['url']}&nmk_kisyu=other',
    };
    Map<String, dynamic> rack(Map m, int number, String date, int games) => {
      ...record(date),
      'machine': m['machine'],
      'rack': number,
      'games': games,
      'detail_url':
          '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=$number#${date.replaceAll('-', '')}',
    };
    String table(
      Map m,
      String date,
      List<int> numbers, [
      List<int> missing = const [],
      int games = 1854,
      List<String> days = tabs,
    ]) => jsonEncode({
      ...jsonDecode(
        page(
          m['url'],
          [
            {...m, 'expected_count': null},
          ],
          [for (final n in numbers) rack(m, n, date, games)],
        ),
      ) as Map,
      if (missing.isNotEmpty) 'missing_racks': missing,
      'available_days': days,
    });
    Future<void> seed([bool alone = false]) => store.importPage(
      page(PscubeStore.index, alone ? [six] : [six, other]),
      PscubeStore.index,
    );
    Future<void> skipTab(Map m, String date) async {
      final url = '${m['url']}#3;0;20261019;0;cd_dai;1;0;664';
      final result = await store.importPage(
        jsonEncode({
          'error': '1526番台の台別ページへのリンクがありません。',
          'source_url': url,
          'available_days': ['2026-10-19'],
        }),
        url,
        expectedDay: date,
      );
      expect(result.saved, 0);
    }

    /// 保存された印：日単位は [機種名, 日]、台単位は {機種名|日: 台番号}。
    Future<List<Object>> absent() async {
      Future<List> read(String key) async {
        final rows = await store.db.query(
          'state',
          where: 'key=?',
          whereArgs: [key],
        );
        return rows.isEmpty ? [] : jsonDecode(rows.single['value'] as String);
      }

      String name(Object key) => (jsonDecode(key as String) as List)[2];
      return [
        [
          for (final e in await read(pscubeAbsentDaysKey))
            '${name(e[0])}|${e[1]}',
        ]..sort(),
        {
          for (final e in await read(pscubeAbsentRacksKey))
            '${name(e[0])}|${e[1]}': (e[2] as List).cast<int>(),
        },
      ];
    }

    Future<List<String>> rows() async => [
      for (final row in await store.db.query('records', columns: ['payload']))
        if (jsonDecode(row['payload'] as String) case final Map r)
          '${r['machine']}|${r['rack']}|${r['day']}|${r['games']}',
    ]..sort();
    Future<void> reopen() async {
      await store.close();
      store = await PscubeStore.open(
        path: '${dir.path}/pscube.sqlite3',
        factory: databaseFactoryFfi,
      );
    }

    test('6台そろった一覧で、この機種・この日の日単位・台単位の印だけが外れ、台別ページが未取得に戻る', () async {
      await seed();
      for (final date in ['2026-10-17', '2026-10-18']) {
        await store.importPage(
          table(six, date, [1, 2, 3, 4], [5, 6]),
          six['url'],
          expectedDay: date,
        );
        await skipTab(six, date);
      }
      await skipTab(other, '2026-10-18');
      expect(await absent(), [
        ['L東京喰種|2026-10-17', 'L東京喰種|2026-10-18', 'ﾏｲｼﾞｬｸﾞﾗｰV|2026-10-18'],
        {
          'L東京喰種|2026-10-17': [5, 6],
          'L東京喰種|2026-10-18': [5, 6],
        },
      ]);
      final before18 = await store.nextTarget('2026-10-18');
      expect((before18.url, before18.remaining), (null, 0));
      final before17 = await store.nextTarget('2026-10-17');
      expect((before17.url, before17.remaining), (other['url'], 1));
      final result = await store.importPage(
        table(six, '2026-10-18', [1, 2, 3, 4, 5, 6], [], 2000),
        six['url'],
        expectedDay: '2026-10-18',
      );
      expect((result.saved, result.kind), (6, '全台一覧'));
      final expected = [
        ['L東京喰種|2026-10-17', 'ﾏｲｼﾞｬｸﾞﾗｰV|2026-10-18'],
        {
          'L東京喰種|2026-10-17': [5, 6],
        },
      ];
      expect(await absent(), expected);
      final after18 = await store.nextTarget('2026-10-18');
      expect(
        (after18.url, after18.remaining),
        (rack(six, 1, '2026-10-18', 2000)['detail_url'], 6),
      );
      final after17 = await store.nextTarget('2026-10-17');
      expect((after17.url, after17.remaining), (other['url'], 1));
      await reopen();
      expect(await absent(), expected, reason: '開き直しても同じ');
      expect((await store.nextTarget('2026-10-18')).remaining, 6);
    });

    test('実データ4台＋その日に無かった2台の過去の一覧で、日の印は外れ、2台は覚えたまま', () async {
      const date = '2026-10-18';
      await seed(true);
      await skipTab(six, date);
      expect((await absent())[0], ['L東京喰種|$date']);
      final result = await store.importPage(
        table(six, date, [1, 2, 3, 4], [5, 6]),
        six['url'],
        expectedDay: date,
      );
      expect(result.saved, 4);
      final expected = [
        <String>[],
        {
          'L東京喰種|$date': [5, 6],
        },
      ];
      expect(await absent(), expected);
      final next = await store.nextTarget(date);
      expect(
        (next.url, next.remaining),
        (rack(six, 1, date, 1854)['detail_url'], 4),
      );
      await reopen();
      expect(await absent(), expected);
    });

    test('4台＋2台 → 5台＋1台 → 6台で、印と次のページ・残り件数が変わる', () async {
      const date = '2026-10-18';
      await seed(true);
      final first = rack(six, 1, date, 1854)['detail_url'];
      for (final (numbers, missing, remaining) in [
        ([1, 2, 3, 4], [5, 6], 4),
        ([1, 2, 3, 4, 5], [6], 5),
        ([1, 2, 3, 4, 5, 6], <int>[], 6),
      ]) {
        final result = await store.importPage(
          table(six, date, numbers, missing),
          six['url'],
          expectedDay: date,
        );
        expect((result.nextUrl, result.remaining), (first, remaining));
        final expected = [
          <String>[],
          missing.isEmpty ? <String, List<int>>{} : {'L東京喰種|$date': missing},
        ];
        expect(await absent(), expected, reason: '$missing');
        final next = await store.nextTarget(date);
        expect((next.url, next.remaining), (first, remaining));
        await reopen();
        expect(await absent(), expected, reason: '開き直しても同じ');
      }
    });

    test('拒否した一覧・保存の途中で失敗した一覧は、記録も両方の印も変えない', () async {
      const date = '2026-10-18';
      await seed();
      await store.importPage(
        table(six, date, [1, 2, 3, 4], [5, 6]),
        six['url'],
        expectedDay: date,
      );
      await skipTab(six, date);
      final marks = await absent(), saved = await rows();
      expect(marks, [
        ['L東京喰種|$date'],
        {
          'L東京喰種|$date': [5, 6],
        },
      ]);
      final refused = {
        '台数が合わない': (table(six, date, [1, 2, 3, 4], [5]), '表示 5 台、設置 6 台'),
        '数値があるのにリンクが無い': (
          jsonEncode({
            'error': '5番台の台別ページへのリンクがありません。数値が表示されてから保存してください。',
            'source_url': six['url'],
            'available_days': tabs,
          }),
          '5番台の台別ページへのリンクがありません',
        ),
        '最新のタブの日に数値なしの台': (
          table(six, date, [1, 2, 3, 4], [5, 6], 1854, ['2026-10-17', date]),
          '5・6番台に数値と台別ページへのリンクがありません',
        ),
        '数値のある台が無い': (table(six, date, [], [1, 2, 3, 4, 5, 6]), '全台一覧が揃っていません'),
      };
      for (final MapEntry(key: label, value: (payload, message))
          in refused.entries) {
        await expectLater(
          store.importPage(payload, six['url'], expectedDay: date),
          throwsA(
            isA<FormatException>().having(
              (e) => e.message,
              'message',
              contains(message),
            ),
          ),
          reason: label,
        );
        expect([await absent(), await rows()], [marks, saved], reason: label);
      }
      // 保存の途中（日の印を書くところ）で失敗：同じトランザクションなので、記録も印も書き換えない。
      await store.db.execute(
        "CREATE TEMP TRIGGER fail_absent BEFORE INSERT ON state WHEN NEW.key = '$pscubeAbsentDaysKey' "
        "BEGIN SELECT RAISE(ABORT, 'disk I/O error'); END",
      );
      await expectLater(
        store.importPage(
          table(six, date, [1, 2, 3, 4, 5, 6], [], 2000),
          six['url'],
          expectedDay: date,
        ),
        throwsA(isA<DatabaseException>()),
      );
      await store.db.execute('DROP TRIGGER fail_absent');
      expect([await absent(), await rows()], [marks, saved]);
      await reopen();
      expect([await absent(), await rows()], [marks, saved]);
    });
  });

  test('取り込み日を指定すると、全台一覧はその日の日付タブで開く（サイトは#以降の日付でタブを選ぶ）', () {
    final table = machine['url'] as String;
    expect(
      pscubeTableUrlForDay(table, '2026-10-05'),
      '$table#0;0;20261005;0;cd_dai;1;0;0',
    );
    expect(
      pscubeTableUrlForDay(
        '$table#2;600;20261006;0;cd_dai;1;0;332',
        '2026-10-05',
      ),
      '$table#0;0;20261005;0;cd_dai;1;0;0',
      reason: 'サイトが書いた前の状態は置き換える',
    );
    expect(pscubeTableUrlForDay(table, null), table, reason: '指定なしは今までどおり');
    final rack = record('2026-10-05')['detail_url'] as String;
    expect(
      pscubeTableUrlForDay(rack, '2026-10-05'),
      rack,
      reason: '台別ページは変えない',
    );
    expect(
      pscubeTableUrlForDay(PscubeStore.index, '2026-10-05'),
      PscubeStore.index,
    );
  });

  test('台別ページの列はサイトの本日から並ぶ：選んだ日より新しい列は無く、7日の範囲は1列目の日付で確かめる', () async {
    // サイトの本日は10/02、取り込み日は10/01。読み取りは10/02（営業中）の列を除き、10/01〜09/26の6日分を返す。
    await seedRack();
    final rackUrl = record()['detail_url'] as String;
    final six = [
      for (var i = 0; i < 6; i++)
        record(
            DateTime.utc(
              2026,
              10,
              1,
            ).subtract(Duration(days: i)).toIso8601String().substring(0, 10),
          )
          ..['graph'] = {
            'kind': 'daily',
            'zero_y': 10,
            'points': [
              [0, 10],
              [1, 8],
            ],
          },
    ];
    String rackPage(List<Map<String, dynamic>> rows, [Object? latest]) =>
        jsonEncode({
          ...jsonDecode(
            page(rackUrl, [
              {
                ...machine,
                'url': (machine['url'] as String).replaceAll('cd_ps=2&', ''),
              },
            ], rows),
          ) as Map<String, dynamic>,
          if (latest != null) 'history_latest_day': latest,
        });
    await store.importPage(
      rackPage(six, '2026-10-02'),
      rackUrl,
      expectedDay: day,
    );
    final before = (await exported())['records'];
    // 1列目の日付が無い古い形なら、従来どおり選んだ日から7日分が必要。
    await expectLater(
      store.importPage(rackPage(six), rackUrl),
      throwsFormatException,
    );
    for (final latest in ['2026-09-30', '2026-10-08', '10/02', 20261002]) {
      await expectLater(
        store.importPage(rackPage(six, latest), rackUrl),
        throwsFormatException,
        reason: '1列目の日付が選んだ日より前・7日より先・形が違う：$latest',
      );
    }
    // 選んだ日より新しい日（営業中の本日）の記録が混ざっていたら保存しない。
    await expectLater(
      store.importPage(
        rackPage([record('2026-10-02'), ...six.take(5)], '2026-10-02'),
        rackUrl,
      ),
      throwsFormatException,
    );
    expect((await exported())['records'], before);
  });
}
