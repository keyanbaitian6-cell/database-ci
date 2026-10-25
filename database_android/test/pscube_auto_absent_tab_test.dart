// 取り込み日の日付タブが無い機種（新台・入れ替え）を、自動取り込みが飛ばして次の機種へ進む（2026-10-22）。
// 以前は「表示中の日（サイトが選んだ最新のタブ）が取り込み日と違う」ので読み取りの前に待ち続け、保存側の飛ばす処理まで届かなかった。
// 判定と読み取りの出力は、生成済みの assets/pscube_auto_probe.js・pscube_capture.js を模擬ページで動かした結果
// （test/fixtures/pscube_absent_tab_auto.json。tool/test_pscube_absent_tab_auto.mjs が今の生成JSと一致するか確かめる）。
// 取り込み画面の _autoTick → _capture と同じ順に、判定（PscubeAutoGuard.decide）→ 読み取り開始 → 保存（PscubeStore.importPage、
// 一時DB）→ 次のページ、を通す。PC（database/test_pscube_auto_absent_tab.py）も同じ出力で確かめる。実サイトには接続しない。
import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_auto.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

final scenes = {
  for (final s
      in (jsonDecode(
            File('test/fixtures/pscube_absent_tab_auto.json')
                .readAsStringSync(),
          ) as Map)['scenes']
          as List)
    (s as Map)['name'] as String: s.cast<String, dynamic>(),
};

void main() {
  late Directory dir;
  late PscubeStore store;
  late PscubeAutoGuard guard;
  late Set<String> done;
  late Map<String, int> failures;
  late Map<String, String> freshSince;
  var clock = Duration.zero;

  setUp(() async {
    sqfliteFfiInit();
    dir = await Directory.systemTemp.createTemp('pscube_absent_tab');
    store = await PscubeStore.open(
      path: '${dir.path}/pscube.sqlite3',
      factory: databaseFactoryFfi,
    );
    guard = PscubeAutoGuard();
    done = {};
    failures = {};
    freshSince = {};
  });
  tearDown(() async {
    await store.close();
    await dir.delete(recursive: true);
  });

  /// 取り込み画面の1回分：判定 → 決定 → （読み取るなら）保存 → 結果。保存の失敗は画面と同じく失敗回数に数える。
  Future<
    ({
      String message,
      ({
        int saved,
        int remaining,
        String kind,
        String? nextUrl,
        String? skipped,
      })?
      result,
    })
  >
  tick(String name, String targetDay) async {
    final scene = scenes[name]!;
    clock += const Duration(seconds: 20);
    final decision = guard.decide(
      scene['probe'],
      done,
      failures,
      clock,
      targetDay: targetDay,
    );
    expect(decision.stop, isFalse);
    final signature = decision.capture;
    if (signature == null) return (message: decision.message, result: null);
    try {
      final result = await store.importPage(
        jsonEncode(scene['capture']),
        scene['url'] as String,
        expectedDay: targetDay,
        direction: 'top',
        manual: false,
        freshSince: freshSince,
      );
      done.add(signature);
      failures.remove(signature);
      return (message: decision.message, result: result);
    } catch (_) {
      failures[signature] = (failures[signature] ?? 0) + 1;
      rethrow;
    }
  }

  Future<List<String>> records() async => [
    for (final row in await store.db.query('records', columns: ['payload']))
      if (jsonDecode(row['payload'] as String) case final Map r)
        '${r['machine']}|${r['rack']}|${r['day']}',
  ]..sort();
  Future<List<Object?>> absentDays() async {
    final rows = await store.db.query(
      'state',
      where: 'key=?',
      whereArgs: [pscubeAbsentDaysKey],
    );
    return rows.isEmpty ? [] : jsonDecode(rows.single['value'] as String);
  }

  final newKey = jsonEncode(['c740601', '20', 'L新台']);

  for (final name in ['only_newer_tab', 'gap_in_tabs']) {
    test('$name：自動取り込みが保存側の飛ばす処理へ届き、保存0件で次の機種を取り込む', () async {
      const day = '2026-10-18';
      final scene = scenes[name]!, next = scenes['next_machine']!;
      // 機種一覧 → 取り込み日のタブで、一覧の最初の機種（新台）を開く。
      final opened = await tick('index', day);
      expect(opened.message, 'ON・取り込み中（機種一覧）');
      final index = opened.result!;
      expect(
        index.nextUrl!.split('#').first,
        (scene['url'] as String).split('#').first,
      );
      expect(index.nextUrl, endsWith('#0;0;20261018;0;cd_dai;1;0;0'));
      // 新台の全台一覧：サイトは10/19を選ぶ。待たずに読み取り、保存側が確かめて飛ばす。
      final skip = await tick(name, day);
      expect(skip.message, contains('10/18の日付タブが無い機種か確かめています'));
      expect(skip.result!.saved, 0);
      expect(skip.result!.skipped, contains('L新台は10/18の日付タブがサイトにありません'));
      expect(skip.result!.nextUrl, next['url'], reason: '次の機種を10/18のタブで開く');
      expect(skip.result!.remaining, 1);
      expect(await records(), isEmpty, reason: '何も保存しない');
      expect(await absentDays(), [
        [newKey, day],
      ], reason: 'その機種のその日だけ印');
      // 同じページに戻っても、二度は読み取らない。
      expect((await tick(name, day)).result, isNull);
      // 次の機種：10/18のタブで保存し、台別ページへ進む。
      final following = await tick('next_machine', day);
      expect(following.message, 'ON・取り込み中（全台一覧）');
      final saved = following.result!;
      expect(saved.saved, 1);
      expect(
        saved.nextUrl,
        ((next['capture'] as Map)['records'] as List).first['detail_url'],
      );
      expect(await records(), ['ﾏｲｼﾞｬｸﾞﾗｰV|2001|2026-10-18']);
      expect(await absentDays(), [
        [newKey, day],
      ], reason: '別の機種の保存では印を外さない');
    });
  }

  test('タブがある・タブより新しい日・タブ無し・人間確認・台別の日付違いは待ち、飛ばさず保存もしない', () async {
    await store.importPage(
      jsonEncode(scenes['index']!['capture']),
      scenes['index']!['url'] as String,
    );
    final cases = {
      'target_tab_not_selected': '全台一覧の日付タブを10/18に合わせてください',
      'target_newer_than_tabs': '全台一覧の日付タブを10/19に合わせてください',
      'no_tabs': '全台一覧の表示待ち',
      'challenge': '人間確認・同意の画面',
      'rack_other_day': 'このページを10/18に合わせてください',
    };
    for (final MapEntry(key: name, value: message) in cases.entries) {
      final scene = scenes[name]!;
      final waited = await tick(name, scene['target_day'] as String);
      expect(waited.result, isNull, reason: name);
      expect(waited.message, contains(message), reason: name);
      // 手で「未取得を取り込む」を押しても、保存側が理由を出して止め、印も付けない。
      if (scene['capture'] != null) {
        await expectLater(
          store.importPage(
            jsonEncode(scene['capture']),
            scene['url'] as String,
            expectedDay: scene['target_day'] as String,
          ),
          throwsA(isA<FormatException>()),
          reason: name,
        );
      }
      expect(await records(), isEmpty, reason: name);
      expect(await absentDays(), isEmpty, reason: name);
    }
  });
}
