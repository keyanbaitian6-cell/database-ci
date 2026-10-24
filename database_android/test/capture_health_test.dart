import 'dart:convert';
import 'dart:io';

import 'package:database_android/capture_health.dart';
import 'package:database_android/pscube_store.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/pscube_viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

Map<String, dynamic> fixture() {
  final data = jsonDecode(
    File('../database/tests/fixtures/pscube_net_capture.json')
        .readAsStringSync(),
  ) as Map<String, dynamic>;
  data['records'][0]['net_capture']['checked_at'] = DateTime.now()
      .toUtc()
      .toIso8601String();
  return data;
}

void main() {
  test('診断は保持し、認証値を持ち出さず、別の台数値との組み合わせを拒否する', () {
    final data = fixture(),
        row = data['records'][0] as Map,
        cap = row['net_capture'] as Map;
    cap['token'] = 'credential-sentinel';
    cap['probe']['graph']['apikey'] = 'credential-sentinel';
    final result = validateNetCapture(cap, record: row)!;
    expect(jsonEncode(result), isNot(contains('credential-sentinel')));
    expect(
      () => validateNetCapture(cap, record: {...row, 'games': 301}),
      throwsFormatException,
    );
    expect(pscubeViewerRecords(data).single.extra['net_capture'], isNotNull);
  });
  test('期限後も台の数値は保持し、0枚と理由不明を区別する', () {
    final row = Map<String, dynamic>.from(fixture()['records'][0] as Map);
    final now = DateTime.parse(row['net_capture']['checked_at'] as String)
        .add(const Duration(days: 8));
    trimNetProbes([row], now: now);
    expect(row['net_capture']['probe'], isNull);
    expect(row['games'], 300);
    expect(row['net_medals'], isNull);
    expect(netCaptureLabel({...row, 'net_medals': 0}), '取得済み（0枚）');
    expect(updateStatusLines(null), contains('Google側の処理：未確認'));
  });
  test('SQLiteへの復元・書き出しと同じ数値の再復元で元数値を保持する', () async {
    sqfliteFfiInit();
    final dir = await Directory.systemTemp.createTemp('capture-health-');
    final store = await PscubeStore.open(
      path: '${dir.path}/test.sqlite3',
      factory: databaseFactoryFfi,
    );
    try {
      final data = fixture();
      await store.importBackup(jsonEncode(data));
      data['records'][0]['net_capture'].remove('probe');
      await store.importBackup(jsonEncode(data));
      final file = await store.exportViewer(path: '${dir.path}/backup.json');
      final out = jsonDecode(await file.readAsString()) as Map;
      expect(out['records'][0]['net_capture']['probe'], isNotNull);
      expect(out['records'][0]['games'], 300);
      expect(await store.healthRecords('2026-10-01'), hasLength(1));
      expect(await store.healthRecords('2026-09-30'), isEmpty);
      final written = await store.syncStatus();
      expect(written!['writes'].any((w) => w['source'] == 'android'), isTrue);
      await expectLater(
        store.exportViewer(path: '${dir.path}/missing/backup.json'),
        throwsA(isA<FileSystemException>()),
      );
      expect(await store.syncStatus(), written);
    } finally {
      await store.close();
      await dir.delete(recursive: true);
    }
  });
  test('更新工程を保持して古いファイルで巻き戻さず、最新日だけの台数を数える', () {
    final rows = [Map<String, dynamic>.from(fixture()['records'][0] as Map)];
    final status = makeSyncWrite('pc', '2026-10-24T10:00:00Z', [
      ...rows,
      {...rows[0], 'day': '2026-09-30'},
    ])!;
    expect(status['writes'][0]['stores'][0]['count'], 1);
    final newer = {
      ...status,
      'processed_at': '2026-10-24T11:00:00Z',
      'supplement_supported': true,
    };
    final older = makeSyncWrite('pc', '2026-10-23T10:00:00Z', rows)!;
    expect(
      mergeSyncStatuses(newer, older)!['writes'][0]['at'],
      '2026-10-24T10:00:00Z',
    );
    final old = jsonEncode({
      'header': {'exported_at': '2026-10-24T12:00:00Z', 'sync_status': newer},
      'records': [],
    });
    final fresh = jsonEncode({
      'header': {'exported_at': '2026-10-23T12:00:00Z', 'sync_status': older},
      'records': [],
    });
    final merged = jsonDecode(ViewerData.merge(old, fresh).text) as Map;
    expect(merged['sync_status']['processed_at'], '2026-10-24T11:00:00Z');
  });
}
