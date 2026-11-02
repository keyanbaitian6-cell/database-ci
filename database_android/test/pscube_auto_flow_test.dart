// WebViewの境界だけを模擬し、画面の周期Timer→_autoTick→_capture→実Storeを通す。
// 判定・読み取りの応答は生成JSのブラウザ試験と共通。実サイトへは接続しない。
// ignore_for_file: depend_on_referenced_packages
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:database_android/pscube_import_page.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

import 'pscube_browser_test.dart' show BrowserPlatform, BrowserController;

final _scenes = {
  for (final scene
      in (jsonDecode(
            File('test/fixtures/pscube_absent_tab_auto.json')
                .readAsStringSync(),
          ) as Map)['scenes']
          as List)
    scene['name'] as String: Map<String, dynamic>.from(scene as Map),
};

class _Platform extends BrowserPlatform {
  late _Controller web;
  @override
  PlatformWebViewController createPlatformWebViewController(
    PlatformWebViewControllerCreationParams params,
  ) => controller = web = _Controller(params);
}

class _Controller extends BrowserController {
  _Controller(super.params);
  String scene = 'index';
  final captures = <String>[];
  final navigations = <String>[];
  int probes = 0;
  Completer<Object>? reading;
  Completer<String?>? locating;
  bool failSave = false;
  int failOpens = 0, failedOpens = 0, pageReloads = 0;

  /// 機種一覧を読むたびに返す機種（読み取りの機種の番号）。空なら読み取りのまま。
  final indexPicks = <List<int>>[];
  Map<String, dynamic> get data => _scenes[scene]!;

  void show(String name) {
    scene = name;
    url = data['url'] as String;
    delegate.started?.call(url!);
    delegate.finished?.call(url!);
  }

  void checkOpening() {
    if (failOpens > 0) {
      failOpens--;
      failedOpens++;
      throw StateError('回帰試験の移動失敗');
    }
  }

  @override
  Future<void> loadRequest(LoadRequestParams params) async {
    checkOpening();
    await super.loadRequest(params);
  }

  @override
  Future<String?> currentUrl() => locating?.future ?? super.currentUrl();

  @override
  Future<void> runJavaScript(String script) async {
    if (script == 'location.reload()') {
      checkOpening();
      pageReloads++;
      delegate.started?.call(url!);
      delegate.finished?.call(url!);
    } else if (script.startsWith('location.assign(')) {
      checkOpening();
      final target = jsonDecode(
        script.substring('location.assign('.length, script.length - 1),
      ) as String;
      navigations.add(target);
      if (target == PscubeStore.index) scene = 'index';
      url = target;
      delegate.started?.call(target);
      delegate.finished?.call(target);
    } else if (script.contains('window.__pscubeCaptureResult = null')) {
      captures.add(scene);
    } else {
      throw StateError('未対応のJS: $script');
    }
  }

  @override
  Future<Object> runJavaScriptReturningResult(String script) async {
    if (script == 'window.__pscubeCaptureResult') {
      if (reading != null) return reading!.future;
      if (failSave) return jsonEncode({'error': '回帰試験の読み取り失敗'});
      if (scene == 'index' && indexPicks.isNotEmpty) {
        final capture = Map<String, dynamic>.from(data['capture'] as Map);
        final machines = capture['machines'] as List;
        capture['machines'] = [
          for (final i in indexPicks.removeAt(0)) machines[i],
        ];
        return jsonEncode(capture);
      }
      return jsonEncode(data['capture']);
    }
    if (script.startsWith('window.__pscubeCaptureRun ===')) return true;
    if (script.contains('autoPageState(location.href, document)')) {
      probes++;
      return jsonEncode(data['probe']);
    }
    // 全台表示の待機も実処理を通し、WidgetTesterの仮想時間で進める。
    if (script.contains("document.querySelector('#ulKI')")) {
      return scene == 'index' ? '-1|0' : '${scene == 'next_machine' ? 1 : 2}|1';
    }
    throw StateError('未対応の問い合わせ: $script');
  }
}

void main() {
  late _Platform platform;
  late PscubeStore store;
  late Directory dir;
  late Duration elapsed;
  late WebViewPlatform? oldPlatform;
  late WidgetTester activeTester;

  Future<void> flushDatabase(WidgetTester tester) async {
    // SQLiteの非同期I/Oだけを実行し、待機Timerは仮想時間に置いたままにする。
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    await tester.pump();
  }

  setUp(() async {
    oldPlatform = WebViewPlatform.instance;
    sqfliteFfiInit();
    dir = await Directory.systemTemp.createTemp('pscube-auto-flow-');
    store = await PscubeStore.open(
      path: '${dir.path}/test.sqlite3',
      factory: databaseFactoryFfiNoIsolate,
    );
    await store.db.insert('state', {'key': 'retained', 'value': 'keep'});
    // 非同期アセット読込は時計を進める前に済ませる。
    await rootBundle.loadString('assets/pscube_capture.js');
    await rootBundle.loadString('assets/pscube_auto_probe.js');
    elapsed = Duration.zero;
    WebViewPlatform.instance = platform = _Platform();
  });

  tearDown(() async {
    if (oldPlatform != null) WebViewPlatform.instance = oldPlatform;
    // 画面のdisposeがStoreの直列キューを閉じる。後始末はDBハンドルを直接確認する。
    await store.db.close();
    await dir.delete(recursive: true);
  });

  Future<void> mount(WidgetTester tester) async {
    activeTester = tester;
    await tester.binding.setSurfaceSize(const Size(390, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox());
      await flushDatabase(tester);
    });
    await tester.pumpWidget(
      MaterialApp(
        home: PscubeImportPage(
          elapsed: () => elapsed,
          now: () => DateTime(2026, 10, 19, 12),
          openStore: () async => store,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await flushDatabase(tester);
    await tester.pumpAndSettle();
    platform.web.show('index');
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('10/18').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '上から取り込む'));
    await tester.pumpAndSettle();
    expect(
      find.text('自動取り込み：ON'),
      findsOneWidget,
      reason: tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data)
          .join('\n'),
    );
  }

  Future<void> tick(WidgetTester tester) async {
    elapsed += const Duration(seconds: 26); // 抽選値15〜25秒の上限を越す。
    // 周期Timer・一覧表示待ち・読取Promiseの監視をすべて仮想時間で実行。
    for (var i = 0; i < 55; i++) {
      await tester.pump(const Duration(milliseconds: 100));
      await flushDatabase(tester);
    }
  }

  Future<List<Map<String, Object?>>> rows() async =>
      (await activeTester.runAsync(() => store.db.query('records')))!;
  Future<List<dynamic>> absent() async {
    final state = (await activeTester.runAsync(
      () => store.db.query(
        'state',
        where: 'key=?',
        whereArgs: [pscubeAbsentDaysKey],
      ),
    ))!;
    return state.isEmpty
        ? []
        : jsonDecode(state.single['value'] as String) as List;
  }

  Future<void> finish(WidgetTester tester) async {
    expect(platform.cookieClears, 0);
    expect(platform.web.cacheClears, 0);
    expect(platform.web.storageClears, 0);
    expect(
      (await tester.runAsync(
        () => store.db.query('state', where: 'key=?', whereArgs: ['retained']),
      ))!.single['value'],
      'keep',
    );
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    await flushDatabase(tester);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  }

  for (final scene in ['only_newer_tab', 'gap_in_tabs']) {
    testWidgets('$scene：周期Timerからタブなしを飛ばし、次の機種をStoreへ保存する', (tester) async {
      await mount(tester);
      elapsed = const Duration(seconds: 14);
      await tester.pump(const Duration(seconds: 1));
      expect(platform.web.probes, 0, reason: '期限前には判定しない');
      await tick(tester);
      expect(platform.web.captures, ['index']);
      expect(
        platform.web.navigations.single,
        endsWith('#0;0;20261018;0;cd_dai;1;0;0'),
      );
      platform.web.show(scene);
      await tick(tester);
      expect(platform.web.captures, ['index', scene]);
      expect(await rows(), isEmpty);
      expect(await absent(), [
        [
          jsonEncode(['c740601', '20', 'L新台']),
          '2026-10-18',
        ],
      ]);
      expect(platform.web.navigations.last, _scenes['next_machine']!['url']);
      platform.web.show('next_machine');
      await tick(tester);
      expect(platform.web.captures, ['index', scene, 'next_machine']);
      final record =
          jsonDecode((await rows()).single['payload'] as String) as Map;
      expect(
        [
          record['machine'],
          record['rack'],
          record['day'],
          record['games'],
          record['bb'],
          record['rb'],
        ],
        ['ﾏｲｼﾞｬｸﾞﾗｰV', 2001, '2026-10-18', 1200, 3, 2],
      );
      expect(platform.web.navigations.last, record['detail_url']);
      expect(await absent(), hasLength(1), reason: '別機種を保存しても新台の印は保持');
      platform.web.show('next_machine');
      await tick(tester);
      expect(platform.web.captures, hasLength(3), reason: '同じページを重複保存しない');
      await finish(tester);
      await tester.runAsync(() async {
        final reopened = await PscubeStore.open(
          path: '${dir.path}/test.sqlite3',
          factory: databaseFactoryFfiNoIsolate,
        );
        try {
          expect(await reopened.db.query('records'), hasLength(1));
          expect(
            await reopened.db.query(
              'state',
              where: 'key=?',
              whereArgs: [pscubeAbsentDaysKey],
            ),
            hasLength(1),
          );
        } finally {
          await reopened.close();
        }
      });
    });
  }

  for (final scene in [
    'target_tab_not_selected',
    'target_newer_than_tabs',
    'no_tabs',
    'challenge',
    'rack_other_day',
  ]) {
    testWidgets('$scene：画面の自動判定で待ち、読み取り・印・保存を始めない', (tester) async {
      await mount(tester);
      // early-morningの場面だけ対象日10/19に選び直す。
      if (scene == 'target_newer_than_tabs') {
        await tester.tap(find.text('自動取り込み：ON'));
        await tester.pumpAndSettle();
        await tester.tap(find.byType(DropdownButtonFormField<String>));
        await tester.pumpAndSettle();
        await tester.tap(find.textContaining('今の営業日').last);
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, '上から取り込む'));
        await tester.pumpAndSettle();
      }
      platform.web.show(scene);
      await tick(tester);
      expect(platform.web.probes, greaterThan(0));
      expect(platform.web.captures, isEmpty);
      expect(platform.web.navigations, isEmpty);
      expect(await rows(), isEmpty);
      expect(await absent(), isEmpty);
      expect(find.text('自動取り込み：ON'), findsOneWidget);
      await finish(tester);
    });
  }

  for (final action in ['OFF', 'navigation']) {
    testWidgets('読み取り待ちの$actionで古い結果を保存しない', (tester) async {
      await mount(tester);
      await tick(tester); // 機種一覧を先に保存する。
      platform.web.show('next_machine');
      final pending = platform.web.reading = Completer<Object>();
      await tick(tester);
      expect(platform.web.captures, ['index', 'next_machine']);
      final probing = platform.web.probes;
      await tick(tester);
      expect(platform.web.probes, probing, reason: '読み取り中は次の判定を重ねない');
      expect(platform.web.captures, ['index', 'next_machine']);
      if (action == 'OFF') {
        await tester.tap(find.text('自動取り込み：ON'));
        await tester.pump();
      } else {
        platform.web.show('only_newer_tab');
      }
      pending.complete(jsonEncode(_scenes['next_machine']!['capture']));
      await tester.pumpAndSettle();
      expect(await rows(), isEmpty);
      expect(await absent(), isEmpty);
      expect(
        platform.web.navigations,
        hasLength(1),
        reason: '保存しなかった結果の次ページへ進まない',
      );
      await finish(tester);
    });
  }

  testWidgets('画面の読み取り失敗を3回数え、その後は待つ', (tester) async {
    await mount(tester);
    platform.web.failSave = true;
    for (var i = 1; i <= 3; i++) {
      await tick(tester);
      expect(platform.web.captures, hasLength(i));
    }
    await tick(tester);
    expect(platform.web.captures, hasLength(3));
    expect(find.textContaining('同じページで3回失敗したため待機中'), findsOneWidget);
    expect(await rows(), isEmpty);
    expect(await absent(), isEmpty);
    await finish(tester);
  });

  // 2026-10-27：前回より少ない機種一覧は、開き直して同じなら保存（撤去）。違い続けても開き直しは3回まで。
  group('減った機種一覧の再確認', () {
    Future<List<String>> seedActive(WidgetTester tester, int extra) async {
      final keys = [
        for (final m
            in (_scenes['index']!['capture'] as Map)['machines'] as List)
          jsonEncode([m['store'], m['rate'], m['machine']]),
        for (var i = 0; i < extra; i++) jsonEncode(['c740601', '20', '撤去機種$i']),
      ];
      await tester.runAsync(
        () => store.db.insert('state', {
          'key': 'active_machine_keys',
          'value': jsonEncode(keys),
        }),
      );
      return keys;
    }

    Future<List<String>> active(WidgetTester tester) async {
      final state = (await tester.runAsync(
        () => store.db.query(
          'state',
          where: 'key=?',
          whereArgs: ['active_machine_keys'],
        ),
      ))!;
      return (jsonDecode(state.single['value'] as String) as List)
          .cast<String>();
    }

    testWidgets('撤去で減った一覧は、開き直して同じなら保存する', (tester) async {
      final keys = await seedActive(tester, 1);
      await mount(tester);
      await tick(tester);
      expect(platform.web.captures, ['index']);
      expect(platform.web.pageReloads, 1, reason: '1回目は保存せず開き直す');
      expect(await active(tester), keys);
      await tick(tester);
      expect(platform.web.captures, ['index', 'index']);
      expect(await active(tester), keys.take(2).toList());
      await finish(tester);
    });

    testWidgets('開き直すたびに違う減った一覧なら、3回で止めて開き直さない', (tester) async {
      final keys = await seedActive(tester, 3);
      await mount(tester);
      platform.web.indexPicks.addAll([
        [0],
        [1],
        [0, 1],
      ]);
      for (var i = 1; i <= 3; i++) {
        await tick(tester);
        expect(platform.web.captures, hasLength(i));
      }
      expect(platform.web.pageReloads, 2, reason: '3回目は開き直さない');
      await tick(tester);
      expect(platform.web.captures, hasLength(3));
      expect(find.textContaining('同じページで3回失敗したため待機中'), findsOneWidget);
      expect(await active(tester), keys);
      await finish(tester);
    });

    testWidgets('いつもの機種数より大幅に少ない一覧は、同じでも受け付けず3回で止めて知らせる（2026-11-03）', (
      tester,
    ) async {
      // 11/1は19機種・11/2は38機種（いつもは59機種）で「すべて取り込みました」になった件。
      final keys = await seedActive(tester, 1);
      await tester.runAsync(() async {
        for (final key in keys) {
          final [store_, rate, name] = jsonDecode(key) as List;
          await store.db.insert('records', {
            'key': jsonEncode([store_, rate, name, 1, '2026-10-30']),
            'payload': jsonEncode({
              'store': store_,
              'rate': rate,
              'machine': name,
              'rack': 1,
              'day': '2026-10-30',
            }),
          });
        }
      });
      await mount(tester);
      for (var i = 1; i <= 3; i++) {
        await tick(tester);
        expect(platform.web.captures, hasLength(i));
      }
      expect(
        platform.web.pageReloads,
        2,
        reason: '同じ2機種の一覧が返り続けても受け付けず、3回目は開き直さない',
      );
      expect(
        find.textContaining('途中までしか読めていません（いつもの3機種に対して2機種）'),
        findsOneWidget,
      );
      expect(find.textContaining('すべて取り込みました'), findsNothing);
      expect(await active(tester), keys, reason: '途中の一覧で機種の並びを上書きしない');
      await finish(tester);
    });
  });

  // 0時の予約（2026-10-26）：画面を開いたまま0時をまたぐと、前日を指定して自動取り込みを始める。
  group('0時の予約', () {
    late DateTime clock;

    Future<void> open(WidgetTester tester, {required bool reserved}) async {
      activeTester = tester;
      if (reserved) {
        await tester.runAsync(() => store.setMidnightAutoEnabled(true));
      }
      await tester.binding.setSurfaceSize(const Size(390, 1000));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      addTearDown(() async {
        await tester.pumpWidget(const SizedBox());
        await flushDatabase(tester);
      });
      await tester.pumpWidget(
        MaterialApp(
          home: PscubeImportPage(
            elapsed: () => elapsed,
            now: () => clock,
            openStore: () async => store,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await flushDatabase(tester);
      await tester.pumpAndSettle();
      platform.web.show('index');
      await tester.pumpAndSettle();
    }

    Future<void> passMidnight(WidgetTester tester, DateTime to) async {
      clock = to;
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 100));
        await flushDatabase(tester);
      }
      await tester.pumpAndSettle();
    }

    testWidgets('予約ONなら0時に前日を指定して始め、前日のページへ進む（開いた直後はOFFのまま）', (tester) async {
      clock = DateTime(2026, 10, 18, 23, 59, 59);
      await open(tester, reserved: true);
      expect(
        find.text('自動取り込み：OFF'),
        findsOneWidget,
        reason: '自動取り込み自体は開いた直後はOFF',
      );
      expect(find.textContaining('0時の予約：10/19'), findsOneWidget);
      await passMidnight(tester, DateTime(2026, 10, 19, 0, 0, 1));
      expect(find.text('自動取り込み：ON'), findsOneWidget);
      await tick(tester);
      expect(platform.web.captures, ['index']);
      expect(
        platform.web.navigations.single,
        endsWith('#0;0;20261018;0;cd_dai;1;0;0'),
        reason: '3時までの営業日（前日10/18）を取り込む',
      );
      await finish(tester);
    });

    for (final previous in ['next_machine', 'rack_other_day']) {
      testWidgets('$previous：0時の予約は古いページから機種一覧へ戻って対象日を取り込む', (tester) async {
        clock = DateTime(2026, 10, 19, 23, 59, 59);
        await open(tester, reserved: true);
        platform.web.show(previous);
        await tester.pumpAndSettle();
        await passMidnight(tester, DateTime(2026, 10, 20, 0, 0, 1));
        expect(find.text('自動取り込み：ON'), findsOneWidget);
        await tick(tester);
        expect(platform.web.captures, ['index']);
        expect(platform.web.navigations, [
          PscubeStore.index,
          contains('#0;0;20261019;0;cd_dai;1;0;0'),
        ]);
        await finish(tester);
      });
    }

    testWidgets('0時の開始準備中に予約を取り消すと、遅い結果で開始・移動しない', (tester) async {
      clock = DateTime(2026, 10, 18, 23, 59, 59);
      await open(tester, reserved: true);
      platform.web.show('rack_other_day');
      final locating = Completer<String?>();
      platform.web.locating = locating;
      await passMidnight(tester, DateTime(2026, 10, 19, 0, 0, 1));
      await tester.tap(find.byKey(const ValueKey('pscube-midnight-auto')));
      await flushDatabase(tester);
      await tester.pumpAndSettle();
      locating.complete(platform.web.url);
      await tester.pumpAndSettle();
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      expect(platform.web.navigations, isEmpty);
      expect(platform.web.captures, isEmpty);
      expect(await tester.runAsync(store.midnightAutoEnabled), isFalse);
      await finish(tester);
    });

    testWidgets('予約開始のページ移動に失敗しても1分間隔の3回までで止める', (tester) async {
      clock = DateTime(2026, 10, 18, 23, 59, 59);
      await open(tester, reserved: true);
      platform.web.show('rack_other_day');
      platform.web.failOpens = 10;
      await passMidnight(tester, DateTime(2026, 10, 19, 0, 0, 1));
      expect(platform.web.failedOpens, 1);
      await passMidnight(tester, DateTime(2026, 10, 19, 0, 0, 40));
      expect(platform.web.failedOpens, 1, reason: '1分より短い間隔で開き直さない');
      for (var minute = 1; minute <= 4; minute++) {
        await passMidnight(tester, DateTime(2026, 10, 19, 0, minute, 2));
      }
      expect(platform.web.failedOpens, 3);
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      expect(find.textContaining('3回試しても始められませんでした'), findsOneWidget);
      expect(find.textContaining('0時の予約：10/20'), findsOneWidget);
      await finish(tester);
    });

    testWidgets('予約OFFなら0時になっても始めない。ボタンで予約すると端末に残る', (tester) async {
      clock = DateTime(2026, 10, 18, 23, 59, 59);
      await open(tester, reserved: false);
      await passMidnight(tester, DateTime(2026, 10, 19, 0, 0, 1));
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      expect(platform.web.probes, 0);
      await tester.tap(find.byKey(const ValueKey('pscube-midnight-auto')));
      await flushDatabase(tester);
      await tester.pumpAndSettle();
      expect(await tester.runAsync(store.midnightAutoEnabled), isTrue);
      expect(
        find.textContaining('0時の予約：10/20'),
        findsOneWidget,
        reason: '予約したのが0時過ぎなら次の0時',
      );
      await tester.tap(find.byKey(const ValueKey('pscube-midnight-auto')));
      await flushDatabase(tester);
      await tester.pumpAndSettle();
      expect(await tester.runAsync(store.midnightAutoEnabled), isFalse);
      await finish(tester);
    });

    testWidgets('端末が眠って3時を過ぎたら、その夜は始めずに次の0時を待つ', (tester) async {
      clock = DateTime(2026, 10, 18, 23, 59, 59);
      await open(tester, reserved: true);
      await passMidnight(tester, DateTime(2026, 10, 19, 3, 0, 1));
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      expect(find.textContaining('3時までに始められませんでした'), findsOneWidget);
      expect(find.textContaining('0時の予約：10/20'), findsOneWidget);
      await finish(tester);
    });
  });
}
