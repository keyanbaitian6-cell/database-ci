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
  Map<String, dynamic> estimate(int value, {bool sure = true}) => {
    'value': value,
    'sure': sure,
    'method': 'site777-axis-pixels-v1',
  };

  test('サイトセブンの推定差枚を「推定差枚」で出し、確かでない台は※。MYは差枚にしない', () {
    final data = fixture();
    data['records'][0]['net_estimate'] = estimate(-700);
    data['records'][1]['net_estimate'] = estimate(50, sure: false);
    final rows = ViewerData.parse(jsonEncode(data)).records;
    expect(rows[0].netText, '-700');
    expect(rows[0].netLabel, '推定差枚');
    expect(rows[1].netText, '+50※');
    expect(rows[0].netMedals, isNull);
    final held = fixture();
    expect(ViewerData.parse(jsonEncode(held)).records[1].netText, isNull);
  });

  test('方式・出典の合わない推定差枚や50枚単位でない値は拒否する', () {
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
      await store.importBackup(jsonEncode(fixture()));
      final later = fixture();
      later['records'][0]['net_estimate'] = estimate(-700);
      later['records'][1]['net_estimate'] = estimate(300);
      (later['records'][1]['source_graph'] as Map)['image_sha256'] =
          List.filled(64, 'f').join();
      await store.importBackup(jsonEncode(later));
      final file = await store.exportViewer(path: '${directory.path}/b.json');
      final rows = {
        for (final r in jsonDecode(await file.readAsString())['records'])
          r['rack']: r,
      };
      final first = later['records'][0]['rack'];
      final second = later['records'][1]['rack'];
      expect(rows[first]['net_estimate'], estimate(-700));
      expect(rows[first]['games'], fixture()['records'][0]['games']);
      expect(rows[second].containsKey('net_estimate'), isFalse);
    } finally {
      await store.close();
      await directory.delete(recursive: true);
    }
  });
}
