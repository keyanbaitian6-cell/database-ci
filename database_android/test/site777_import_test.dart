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
}
