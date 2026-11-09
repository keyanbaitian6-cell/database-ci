import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_store.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Map<String, dynamic> fixture() =>
    jsonDecode(File('test/fixtures/site777_backup.json').readAsStringSync())
        as Map<String, dynamic>;

void main() {
  test('サイトセブンのMY・グラフ・未知ART・差枚・出典が閲覧用の変換で保持される', () {
    final data = ViewerData.parse(jsonEncode(fixture()));
    expect(data.records.length, 2);
    final row = data.records.first;
    expect(row.my, 900);
    expect(row.extra['at_art'], isNull);
    expect(row.netMedals, isNull);
    expect(row.extra['source_site'], 'site777');
    expect(row.graph, isNotNull);
    expect(row.extra['source_day_label'], '11/6');
    expect(
      (row.extra['source_graph'] as Map)['format'],
      'site777-yellow-pixels-v1',
    );
    final missing = fixture();
    missing['records'][1]['my'] = null;
    expect(ViewerData.parse(jsonEncode(missing)).records[1].my, isNull);
  });

  test('別日・別店舗・架空の差枚・型の違いを拒否する', () {
    for (final patch in <Map<String, dynamic>>[
      {'source_day_label': '11/5'},
      {'rate': '5'},
      {'net_medals': 0},
      {'my': '900'},
      {'source_captured_at': '2026-12-01T00:00:00+09:00'},
      {
        'source_url':
            'https://m.site777.jp/f/D3300.do?pmc=1234&urt=2000&mdc=123&dtdd=0',
      },
    ]) {
      final data = fixture();
      (data['records'] as List).first.addAll(patch);
      expect(() => ViewerData.parse(jsonEncode(data)), throwsFormatException);
    }
  });

  test('画像を解析できないときは理由付きの不明として読み込む', () {
    final data = fixture();
    final row = (data['records'] as List).first;
    row['graph'] = null;
    row['source_graph']['error'] = 'curve_unknown';
    expect(ViewerData.parse(jsonEncode(data)).records.first.graph, isNull);
    row['source_graph'].remove('error');
    expect(() => ViewerData.parse(jsonEncode(data)), throwsFormatException);
  });

  test('Androidの保存・別名の既存台の保持・再復元で出典が失われない', () async {
    sqfliteFfiInit();
    final directory = await Directory.systemTemp.createTemp('site777-import-');
    final store = await PscubeStore.open(
      path: '${directory.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      expect((await store.importBackup(jsonEncode(fixture()))).added, 2);
      final other = fixture();
      (other['machines'] as List).first['machine'] = '別表記';
      for (final row in other['records']) {
        row['machine'] = '別表記';
        row['games'] = 100;
      }
      expect((await store.importBackup(jsonEncode(other))).keptLocal, 2);
      final file = await store.exportViewer(
        path: '${directory.path}/backup.json',
      );
      final restored = jsonDecode(await file.readAsString());
      expect((restored['records'] as List).length, 2);
      expect(restored['records'].first['source_site'], 'site777');
      expect(restored['records'].first['games'], 3000);
      expect(restored['records'].first['at_art'], isNull);
      expect((await store.importBackup(jsonEncode(restored))).added, 0);
    } finally {
      await store.close();
      await directory.delete(recursive: true);
    }
  });

  // グラフ画像の目盛りから読んだ推定差枚（PC `site777_net.py`、2026-11-07）。
  Map<String, dynamic> estimate(int value, {bool sure = true, bool legacy = false}) => {
    'value': value,
    'sure': sure,
    'method': legacy ? 'site777-axis-pixels-v1' : 'site777-axis-pixels-v2',
  };

  test('サイトセブンの推定差枚を「推定差枚」で出し、確かでない台は※。MYは差枚にしない', () {
    final data = fixture();
    data['records'][0]['net_estimate'] = estimate(-573);
    data['records'][1]['net_estimate'] = estimate(50, sure: false, legacy: true);
    final rows = ViewerData.parse(jsonEncode(data)).records;
    expect(rows[0].netText, '-573');
    expect(rows[0].netLabel, '推定差枚');
    expect(rows[1].netText, '+50※');
    expect(rows[0].netMedals, isNull);
    final held = fixture();
    expect(ViewerData.parse(jsonEncode(held)).records[1].netText, isNull);
  });

  test('方式・出典の合わない推定差枚や旧方式の50枚単位でない値は拒否する', () {
    for (final bad in <Object?>[
      {'value': -700, 'sure': true, 'method': 'anaslo-graph-v1'},
      {'value': -703, 'sure': true, 'method': 'site777-axis-pixels-v1'},
      {'value': -700, 'sure': true},
    ]) {
      final data = fixture();
      data['records'][0]['net_estimate'] = bad;
      expect(() => ViewerData.parse(jsonEncode(data)), throwsFormatException);
    }
  });

  test('同じ表・同じ画像から後で付けた推定差枚だけを保存済みの台へ移す', () async {
    sqfliteFfiInit();
    final directory = await Directory.systemTemp.createTemp('site777-net-');
    final store = await PscubeStore.open(
      path: '${directory.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      final legacy = fixture();
      legacy['records'][0]['net_estimate'] = estimate(-550, legacy: true);
      await store.importBackup(jsonEncode(legacy));
      final later = fixture();
      later['records'][0]['net_estimate'] = estimate(-573);
      later['records'][1]['net_estimate'] = estimate(300);
      (later['records'][1]['source_graph'] as Map)['image_sha256'] =
          List.filled(64, 'f').join();
      await store.importBackup(jsonEncode(later));
      await store.importBackup(jsonEncode(legacy));
      final file = await store.exportViewer(path: '${directory.path}/b.json');
      final rows = {
        for (final r in jsonDecode(await file.readAsString())['records'])
          r['rack']: r,
      };
      final first = later['records'][0]['rack'];
      final second = later['records'][1]['rack'];
      expect(rows[first]['net_estimate'], estimate(-573));
      expect(rows[first]['games'], fixture()['records'][0]['games']);
      expect(rows[second].containsKey('net_estimate'), isFalse);
    } finally {
      await store.close();
      await directory.delete(recursive: true);
    }
  });

  test('サイトセブンはアナスロで補った台を置き換え、P’s CUBE本来の台は置き換えない', () async {
    // 2026-11-07 利用者「サイトセブンのを取り込んでっていってるの」（PC `import_backup` と同じ規則）。
    sqfliteFfiInit();
    final directory = await Directory.systemTemp.createTemp('site777-replace-');
    final store = await PscubeStore.open(
      path: '${directory.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      Map<String, dynamic> anaslo(int rack) => {
        'store': 'c740601', 'rate': '20', 'machine': 'アナスロの別表記', 'rack': rack,
        'day': '2026-11-06', 'games': 1000, 'bb': 1, 'rb': 1, 'at_art': 0, 'my': null,
        'detail_url': null, 'observed_at': null, 'graph': null, 'net_medals': null,
        'source_site': 'anaslo',
        'source_url': 'https://ana-slo.com/2026-11-06-p-stationii-data/',
        'source_sha256': List.filled(64, 'a').join(),
        'source_machine': 'アナスロの別表記',
      };
      await store.importBackup(jsonEncode({
        'format': 'pscube-viewer', 'version': 1,
        'machines': [
          {'store': 'c740601', 'rate': '20', 'machine': 'アナスロの別表記', 'expected_count': null,
           'machine_type': null, 'url': null, 'source_site': 'anaslo'},
        ],
        'records': [anaslo(101), anaslo(102)],
      }));
      final result = await store.importBackup(jsonEncode(fixture()));
      expect(result.added, 2);
      final file = await store.exportViewer(path: '${directory.path}/b.json');
      final rows = (jsonDecode(await file.readAsString())['records'] as List);
      expect(rows.length, 2, reason: 'アナスロの記録は消え、同じ台・日に2つ残らない');
      expect(rows.every((r) => r['source_site'] == 'site777'), isTrue);
      // アナスロをもう一度読み込んでも、サイトセブンの台は戻らない。
      await store.importBackup(jsonEncode({
        'format': 'pscube-viewer', 'version': 1,
        'machines': [
          {'store': 'c740601', 'rate': '20', 'machine': 'アナスロの別表記', 'expected_count': null,
           'machine_type': null, 'url': null, 'source_site': 'anaslo'},
        ],
        'records': [anaslo(101)],
      }));
      final again = await store.exportViewer(path: '${directory.path}/c.json');
      expect((jsonDecode(await again.readAsString())['records'] as List)
          .every((r) => r['source_site'] == 'site777'), isTrue);
    } finally {
      await store.close();
      await directory.delete(recursive: true);
    }
  });

  test('確定はその日の23:30以降。確定前の台だけ、あとで取った台で置き換える（PC と同じ）', () async {
    // 2026-11-10 利用者「23時半以降に取り込みだしたやつも飛ばしていいです。23時45分くらいに最終更新だから」
    // （2026-11-08 は翌0:30だった）。
    Map<String, dynamic> at(String captured) =>
        {'source_site': 'site777', 'day': '2026-11-06', 'source_captured_at': captured};
    expect(site777Final(at('2026-11-06T23:29:59+09:00')), isFalse);
    expect(site777Final(at('2026-11-06T23:30:00+09:00')), isTrue);
    expect(site777Final(at('2026-11-06T14:30:00Z')), isTrue, reason: '時差の書き方が違っても同じ瞬間');
    expect(site777Final({'source_site': 'site777', 'day': '2026-11-06'}), isTrue,
        reason: '時刻が読めない台は置き換えない');
    expect(site777Supersedes(at('2026-11-06T23:20:00+09:00'), at('2026-11-06T23:10:00+09:00')), isFalse,
        reason: '古い取り込みでは置き換えない');
    sqfliteFfiInit();
    final directory = await Directory.systemTemp.createTemp('site777-final-');
    final store = await PscubeStore.open(
      path: '${directory.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      Map<String, dynamic> capture(String captured, int games, String sha) {
        final data = fixture();
        for (final r in data['records'] as List) {
          r['source_captured_at'] = captured;
          r['source_sha256'] = List.filled(64, sha).join();
        }
        (data['records'] as List)[0]['games'] = games;
        return data;
      }
      Future<Map<String, dynamic>> first() async {
        final file = await store.exportViewer(path: '${directory.path}/x.json');
        final rows = jsonDecode(await file.readAsString())['records'] as List;
        expect(rows.length, 2, reason: '同じ台・日に2つ残らない');
        return rows.firstWhere((r) => r['rack'] == fixture()['records'][0]['rack']) as Map<String, dynamic>;
      }
      await store.importBackup(jsonEncode(capture('2026-11-06T23:20:00+09:00', 3000, 'a')));
      await store.importBackup(jsonEncode(capture('2026-11-07T10:00:00+09:00', 8000, 'b')));
      expect((await first())['games'], 8000, reason: '確定前の台は、あとで取った台で置き換える');
      await store.importBackup(jsonEncode(capture('2026-11-07T11:00:00+09:00', 9000, 'c')));
      expect((await first())['games'], 8000, reason: '確定した台は置き換えない');
      await store.importBackup(jsonEncode(capture('2026-11-06T23:20:00+09:00', 3000, 'a')));
      expect((await first())['games'], 8000, reason: '古いバックアップを読み直しても戻らない');
    } finally {
      await store.close();
      await directory.delete(recursive: true);
    }
  });
}
