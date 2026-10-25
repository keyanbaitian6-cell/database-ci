// P’s CUBEの当日分をGoogleのスクリプトへ送る（2026-10-26、database/PSCUBE_SYNC.md「当日分の自動送信」）。
import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_day_upload.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

void main() {
  late Directory dir;
  late PscubeStore store;
  const url = 'https://script.google.com/macros/s/AKfy-test/exec';
  const setting = PscubeDayUploadSetting(url: url, key: 'あいことば2026');

  Map<String, dynamic> machine(String name) => {
    'store': 'c740601',
    'rate': '20',
    'machine': name,
    'expected_count': 2,
    'url': '${PscubeStore.root}cgi-bin/nc-v05-011.php?cd_ps=2&bai=20',
  };
  Map<String, dynamic> record(String name, int rack, String day) => {
    'store': 'c740601',
    'rate': '20',
    'machine': name,
    'rack': rack,
    'day': day,
    'bb': 3,
    'rb': 2,
    'at_art': 0,
    'games': 2000,
    'my': 500,
    'observed_at': '${day}T22:00:00+09:00',
  };
  String key(Map<String, dynamic> row, {bool record = false}) => jsonEncode([
    row['store'],
    row['rate'],
    row['machine'],
    if (record) ...[row['rack'], row['day']],
  ]);

  Future<void> put(
    List<Map<String, dynamic>> machines,
    List<Map<String, dynamic>> records, {
    List<Map<String, dynamic>> captured = const [],
  }) async {
    for (final m in machines) {
      await store.db.insert('machines', {
        'key': key(m),
        'payload': jsonEncode(m),
      });
    }
    for (final r in records) {
      await store.db.insert('records', {
        'key': key(r, record: true),
        'payload': jsonEncode(r),
      });
    }
    for (final r in captured) {
      await store.db.insert('rack_captures', {'key': key(r, record: true)});
    }
  }

  setUp(() async {
    sqfliteFfiInit();
    dir = await Directory.systemTemp.createTemp('pscube_day_upload');
    store = await PscubeStore.open(
      path: '${dir.path}/pscube.sqlite3',
      factory: databaseFactoryFfi,
    );
  });
  tearDown(() async {
    await store.close();
    await dir.delete(recursive: true);
  });

  test('当日分はその日の記録・印と、その記録の機種だけ', () async {
    final a = machine('試験A'), b = machine('試験B'), c = machine('試験C');
    final today = [
      record('試験A', 1, '2026-10-26'),
      record('試験B', 2, '2026-10-26'),
    ];
    await put(
      [a, b, c],
      [
        ...today,
        record('試験A', 1, '2026-10-25'),
        record('試験C', 3, '2026-10-25'),
      ],
      captured: [today.first, record('試験A', 1, '2026-10-25')],
    );
    final backup = (await store.dayBackup(
      '2026-10-26',
      now: DateTime(2026, 10, 26, 23, 50),
    ))!;
    expect(backup['format'], 'pscube-viewer');
    expect(
      [backup['version'], backup['kind'], backup['source']],
      [1, 'backup', 'android'],
    );
    expect(
      [
        for (final r in backup['records'] as List)
          '${r['machine']}/${r['day']}',
      ],
      ['試験A/2026-10-26', '試験B/2026-10-26'],
    );
    expect(
      [for (final m in backup['machines'] as List) m['machine']],
      ['試験A', '試験B'],
    );
    expect(backup['rack_captures'], [key(today.first, record: true)]);
    expect(await store.dayBackup('2026-10-24'), isNull);
  });

  test('合言葉と当日分を送り、結果を端末に残す。合言葉は他のバックアップに出さない', () async {
    await put([machine('試験A')], [record('試験A', 1, '2026-10-26')]);
    late Uri sentTo;
    late Map<String, dynamic> sent;
    final result = await uploadPscubeDay(
      store,
      '2026-10-26',
      setting,
      now: DateTime(2026, 10, 26, 23, 50),
      poster: (uri, body) async {
        sentTo = uri;
        sent = jsonDecode(body);
        return jsonEncode({
          'ok': true,
          'name': 'pscube-day-android-2026-10-26.json',
          'records': 1,
        });
      },
    );
    expect(result.ok, isTrue);
    expect(result.message, '10/26の分（1台）をDriveへ送りました。');
    expect(sentTo.toString(), url);
    expect(
      [sent['file'], sent['key'], sent['day']],
      ['pscube-day', 'あいことば2026', '2026-10-26'],
    );
    expect((sent['backup']['records'] as List).single['rack'], 1);
    final last = (await store.lastDayUpload())!;
    expect([last['day'], last['ok']], ['2026-10-26', true]);

    await store.setDayUploadSetting(setting.toJson());
    expect(
      PscubeDayUploadSetting.fromJson(await store.dayUploadSetting())!.key,
      'あいことば2026',
    );
    final exported = await (await store.exportViewer(
      path: '${dir.path}/backup.json',
    )).readAsString();
    expect(exported.contains('あいことば2026'), isFalse);
    expect(exported.contains('day_upload'), isFalse);
  });

  test('スクリプトの断り・通信の失敗・記録なしは失敗として残し、記録は変えない', () async {
    await put([machine('試験A')], [record('試験A', 1, '2026-10-26')]);
    var r = await uploadPscubeDay(
      store,
      '2026-10-26',
      setting,
      poster: (_, _) async => jsonEncode({'error': '合言葉が違います。'}),
    );
    expect([r.ok, r.message], [false, '10/26の分を送れませんでした：合言葉が違います。']);
    r = await uploadPscubeDay(
      store,
      '2026-10-26',
      setting,
      poster: (_, _) async => throw const SocketException('接続できません'),
    );
    expect(r.ok, isFalse);
    expect(r.message, contains('接続できません'));
    r = await uploadPscubeDay(
      store,
      '2026-10-25',
      setting,
      poster: (_, _) async => fail('記録が無い日は送らない'),
    );
    expect(r.message, '10/25の分を送れません：その日の記録がありません。');
    expect((await store.lastDayUpload())!['ok'], isFalse);
    expect((await store.db.query('records')).length, 1);
  });

  test('設定の確認：スクリプトのURLと8文字以上の合言葉だけ', () {
    expect(PscubeDayUploadSetting.problem(url, 'あいことば2026'), isNull);
    for (final bad in [
      'http://script.google.com/macros/s/x/exec',
      'https://example.com/macros/s/x/exec',
      'https://script.google.com/macros/s/x/dev',
      '',
    ]) {
      expect(
        PscubeDayUploadSetting.problem(bad, 'あいことば2026'),
        isNotNull,
        reason: bad,
      );
    }
    expect(PscubeDayUploadSetting.problem(url, '短い'), contains('8文字'));
    expect(
      PscubeDayUploadSetting.fromJson({'url': url, 'key': 'k'})!.enabled,
      isTrue,
    );
    expect(PscubeDayUploadSetting.fromJson({'url': 1}), isNull);
  });

  test('PC版が読む名前の当日分は、他の日の記録を持たない（スクリプトも同じ検査をする）', () async {
    await put(
      [machine('試験A')],
      [record('試験A', 1, '2026-10-26'), record('試験A', 1, '2026-10-02')],
    );
    final backup = (await store.dayBackup('2026-10-26'))!;
    expect(
      (backup['records'] as List).every((r) => r['day'] == '2026-10-26'),
      isTrue,
    );
  });
}
