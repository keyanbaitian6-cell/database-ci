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
  bool failSave = false;
  Map<String, dynamic> get data => _scenes[scene]!;

  void show(String name) {
    scene = name;
    url = data['url'] as String;
    delegate.started?.call(url!);
    delegate.finished?.call(url!);
  }

  @override
  Future<void> runJavaScript(String script) async {
    if (script.startsWith('location.assign(')) {
      final target = jsonDecode(
        script.substring('location.assign('.length, script.length - 1),
      ) as String;
      navigations.add(target);
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
}
