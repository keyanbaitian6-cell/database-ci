// アナスロで補った台の推定差枚（PC `anaslo_net.py`、2026-11-06 利用者「入れる画面を相談」→ Android・
// iPhone・PCの閲覧と共有カレンダー、確かでない台は※、合計・順位にも入れる）。
import 'dart:convert';
import 'dart:io';

import 'package:database_android/daily_net_page.dart';
import 'package:database_android/pscube_store.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Map<String, dynamic> row(int rack, {Object? estimate, int? net, String sha = 'a'}) => {
  'store': 'c740601',
  'rate': '20',
  'machine': 'マイジャグラーV',
  'rack': rack,
  'day': '2026-11-04',
  'games': 3000,
  'bb': 8,
  'rb': 4,
  'at_art': 0,
  'my': null,
  'detail_url': null,
  'observed_at': null,
  'graph': null,
  'net_medals': net,
  'source_site': 'anaslo',
  'source_url': 'https://ana-slo.com/2026-11-04-p-stationii-data/',
  'source_sha256': List.filled(64, sha).join(),
  'source_machine': 'マイジャグラーV',
  if (estimate != null) 'net_estimate': estimate,
};

Map<String, dynamic> doc(List<Map<String, dynamic>> records) => {
  'format': 'pscube-viewer',
  'version': 1,
  'machines': [
    {
      'store': 'c740601',
      'rate': '20',
      'machine': 'マイジャグラーV',
      'expected_count': null,
      'machine_type': null,
      'url': null,
      'source_site': 'anaslo',
    },
  ],
  'records': records,
};

const sure = {'value': 420, 'sure': true, 'method': 'anaslo-graph-v1'};
const check = {'value': -650, 'sure': false, 'method': 'anaslo-graph-v1'};

void main() {
  test('the estimate is the rack’s net, unsure ones carry ※ and the label says 推定差枚', () {
    final records = ViewerData.parse(jsonEncode(doc([row(101, estimate: sure), row(102, estimate: check), row(103)]))).records;
    final byRack = {for (final r in records) r.rack: r};
    expect(byRack[101]!.netValue, 420);
    expect(byRack[101]!.netText, '+420');
    expect(byRack[101]!.netLabel, '推定差枚');
    expect(byRack[102]!.netValue, -650);
    expect(byRack[102]!.netText, '-650※');
    expect(byRack[103]!.netValue, isNull);
    expect(byRack[103]!.netLabel, '差枚');
    // 合計・台数に入る（利用者「全部入れる」）。※の台数も数える。
    final day = dailyNet(records, records.first.store).single;
    expect(day.total, 420 - 650);
    expect(day.captured, 2);
    expect(day.needsCheck, 1);
  });

  test('a broken estimate or one on a real capture is rejected', () {
    for (final bad in [
      {'value': 1.5, 'sure': true, 'method': 'anaslo-graph-v1'},
      {'value': 1, 'sure': 'yes', 'method': 'anaslo-graph-v1'},
      {'value': 1, 'sure': true, 'method': 'other'},
      {'value': 1, 'sure': true, 'method': 'anaslo-graph-v1', 'x': 1},
    ]) {
      expect(() => ViewerData.parse(jsonEncode(doc([row(101, estimate: bad)]))), throwsFormatException, reason: '$bad');
    }
  });

  test('the store moves a later estimate onto the same anaslo page only', () async {
    sqfliteFfiInit();
    final dir = await Directory.systemTemp.createTemp('anaslo_net');
    final store = await PscubeStore.open(path: '${dir.path}/test.sqlite3', factory: databaseFactoryFfi);
    try {
      expect((await store.importBackup(jsonEncode(doc([row(101)])))).added, 1);
      await store.importBackup(jsonEncode(doc([row(101, estimate: sure, sha: 'b')])));
      var rows = await store.db.query('records');
      expect(jsonDecode(rows.single['payload'] as String)['net_estimate'], isNull, reason: '別のページの推定は移さない');
      await store.importBackup(jsonEncode(doc([row(101, estimate: sure)])));
      rows = await store.db.query('records');
      final payload = jsonDecode(rows.single['payload'] as String);
      expect(payload['net_estimate'], sure);
      expect(payload['games'], 3000);
    } finally {
      await store.close();
      await dir.delete(recursive: true);
    }
  });
}
