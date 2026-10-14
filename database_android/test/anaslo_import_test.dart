import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_store.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/data_checks.dart';

Map<String, dynamic> fixture() => {
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
  'records': [
    {
      'store': 'c740601',
      'rate': '20',
      'machine': 'マイジャグラーV',
      'rack': 101,
      'day': '2026-09-15',
      'games': 3000,
      'bb': 8,
      'rb': 4,
      'at_art': 0,
      'my': null,
      'detail_url': null,
      'observed_at': null,
      'graph': null,
      'net_medals': null,
      'source_site': 'anaslo',
      'source_url': 'https://ana-slo.com/2026-09-15-p-stationii-data/',
      'source_sha256': List.filled(64, 'a').join(),
      'source_machine': 'マイジャグラーV',
    },
  ],
};

void main() {
  test('native store imports external history, preserves existing rack/day and roundtrips', () async {
    sqfliteFfiInit();
    final dir = await Directory.systemTemp.createTemp('anaslo_import');
    final store = await PscubeStore.open(
      path: '${dir.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      final first = await store.importBackup(jsonEncode(fixture()));
      expect(first.added, 1);
      expect((await store.importBackup(jsonEncode(fixture()))).keptLocal, 1);
      final different = fixture();
      (different['records'] as List).single['machine'] = '別表記';
      (different['machines'] as List).single['machine'] = '別表記';
      expect((await store.importBackup(jsonEncode(different))).added, 0);
      final file = await store.exportViewer(path: '${dir.path}/backup.json');
      final d = jsonDecode(await file.readAsString());
      expect((d['records'] as List).length, 1);
      expect((d['records'] as List).single['my'], isNull);
      expect((await store.importBackup(jsonEncode(d))).added, 0);
      expect((await store.nextTarget('2026-09-15')).remaining, 0);
    } finally {
      await store.close();
      await dir.delete(recursive: true);
    }
  });
  test('unknown MY stays null and external history has no score', () {
    final data = ViewerData.parse(jsonEncode(fixture()));
    final r = data.records.single;
    expect(r.my, isNull);
    expect(r.detailUrl, isNull);
    expect(r.extra['source_site'], 'anaslo');
    expect(scoreRecord(r, data.records).total, isNull);
    expect(nextDayEvidence(r, data.records).usedDays, 0);
  });
  test('invalid external provenance or fake MY is rejected', () {
    for (final patch in [
      {'my': 0},
      {'source_url': 'https://example.com/'},
      {'source_sha256': 'x'},
    ]) {
      final d = fixture();
      (d['records'] as List).single.addAll(patch);
      expect(() => ViewerData.parse(jsonEncode(d)), throwsFormatException);
    }
  });
}
