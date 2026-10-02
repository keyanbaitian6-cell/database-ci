// The fake implements the same platform boundary as the production WebView.
// ignore_for_file: depend_on_referenced_packages
import 'dart:io';

import 'package:database_android/pscube_import_page.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

class BrowserPlatform extends WebViewPlatform {
  late BrowserController controller;
  int cookieClears = 0;
  @override
  PlatformWebViewController createPlatformWebViewController(
    PlatformWebViewControllerCreationParams params,
  ) => controller = BrowserController(params);
  @override
  PlatformNavigationDelegate createPlatformNavigationDelegate(
    PlatformNavigationDelegateCreationParams params,
  ) => BrowserDelegate(params);
  @override
  PlatformWebViewWidget createPlatformWebViewWidget(
    PlatformWebViewWidgetCreationParams params,
  ) => BrowserWidget(params);
  @override
  PlatformWebViewCookieManager createPlatformCookieManager(
    PlatformWebViewCookieManagerCreationParams params,
  ) => BrowserCookies(params, this);
}

class BrowserDelegate extends PlatformNavigationDelegate {
  BrowserDelegate(super.params) : super.implementation();
  PageEventCallback? started, finished;
  WebResourceErrorCallback? network;
  HttpResponseErrorCallback? http;
  @override
  Future<void> setOnPageStarted(PageEventCallback callback) async =>
      started = callback;
  @override
  Future<void> setOnPageFinished(PageEventCallback callback) async =>
      finished = callback;
  @override
  Future<void> setOnWebResourceError(WebResourceErrorCallback callback) async =>
      network = callback;
  @override
  Future<void> setOnHttpError(HttpResponseErrorCallback callback) async =>
      http = callback;
}

class BrowserController extends PlatformWebViewController {
  BrowserController(super.params) : super.implementation();
  late BrowserDelegate delegate;
  String? url;
  final loads = <String>[];
  int storageClears = 0, cacheClears = 0, jsCalls = 0, reloads = 0;
  @override
  Future<void> setJavaScriptMode(JavaScriptMode mode) async {}
  @override
  Future<void> setPlatformNavigationDelegate(
    PlatformNavigationDelegate value,
  ) async => delegate = value as BrowserDelegate;
  @override
  Future<void> loadRequest(LoadRequestParams params) async {
    url = params.uri.toString();
    loads.add(url!);
    delegate.started?.call(url!);
    delegate.finished?.call(url!);
  }

  @override
  Future<void> reload() async {
    reloads++;
    await loadRequest(LoadRequestParams(uri: Uri.parse(url!)));
  }

  @override
  Future<String?> currentUrl() async => url;
  @override
  Future<void> clearCache() async => cacheClears++;
  @override
  Future<void> clearLocalStorage() async => storageClears++;
  @override
  Future<void> runJavaScript(String script) async => jsCalls++;
  @override
  Future<Object> runJavaScriptReturningResult(String script) async => '-1';
}

class BrowserWidget extends PlatformWebViewWidget {
  BrowserWidget(super.params) : super.implementation();
  @override
  Widget build(BuildContext context) => const SizedBox.expand();
}

class BrowserCookies extends PlatformWebViewCookieManager {
  BrowserCookies(super.params, this.owner) : super.implementation();
  final BrowserPlatform owner;
  @override
  Future<bool> clearCookies() async {
    owner.cookieClears++;
    return true;
  }
}

void main() {
  testWidgets(
    'DNS failure offers native retry without deleting Cookies or SQLite; explicit reset stays separate',
    (tester) async {
      final oldPlatform = WebViewPlatform.instance;
      sqfliteFfiInit();
      databaseFactory = databaseFactoryFfiNoIsolate;
      final oldFactory = databaseFactory;
      final dir = (await tester.runAsync(
        () => Directory.systemTemp.createTemp('pscube-browser-test-'),
      ))!;
      sqfliteFfiInit();
      databaseFactory = databaseFactoryFfiNoIsolate;
      await tester.runAsync(() => databaseFactory.setDatabasesPath(dir.path));
      final platform = BrowserPlatform();
      WebViewPlatform.instance = platform;
      await tester.binding.setSurfaceSize(const Size(390, 850));
      final db = (await tester.runAsync(() async {
        final db = await PscubeStore.open();
        await db.db.insert('state', {'key': 'retained', 'value': 'keep'});
        return db;
      }))!;
      try {
        await tester.pumpWidget(const MaterialApp(home: PscubeImportPage()));
        await tester.pumpAndSettle();
        await tester.runAsync(
          () async => Future<void>.delayed(const Duration(milliseconds: 100)),
        );
        await tester.pumpAndSettle();
        final web = platform.controller;
        web.delegate.network!(
          WebResourceError(
            errorCode: -2,
            description: 'net::ERR_NAME_NOT_RESOLVED',
            isForMainFrame: true,
            url: PscubeStore.root,
          ),
        );
        web.delegate.finished!(PscubeStore.root);
        await tester.pumpAndSettle();
        expect(find.textContaining('DNSエラー'), findsOneWidget);
        expect(find.text('もう一度開く'), findsOneWidget);
        final capture = tester.widget<FilledButton>(
          find.widgetWithText(FilledButton, '未取得を取り込む'),
        );
        expect(capture.onPressed, isNull);
        await tester.tap(find.text('もう一度開く'));
        await tester.pumpAndSettle();
        expect(web.loads, [PscubeStore.root, PscubeStore.root]);
        expect(web.reloads, 1);
        expect(
          web.jsCalls,
          0,
          reason: 'native error page is not used for JS navigation',
        );
        expect(platform.cookieClears, 0);
        expect(web.storageClears, 0);
        expect(web.cacheClears, 0);
        expect(
          (await tester.runAsync(
            () => db.db.query('state', where: 'key=?', whereArgs: ['retained']),
          ))!.single['value'],
          'keep',
        );
        // The separate, confirmed reset leaves the old document before deletion.
        await tester.tap(find.byTooltip('サイトの記録を消してやり直す'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('消してやり直す'));
        await tester.pumpAndSettle();
        expect(web.loads.sublist(web.loads.length - 2), [
          'about:blank',
          PscubeStore.root,
        ]);
        expect(platform.cookieClears, 1);
        expect(web.storageClears, 1);
        expect(web.cacheClears, 1);
        expect(
          (await tester.runAsync(
            () => db.db.query('state', where: 'key=?', whereArgs: ['retained']),
          ))!.single['value'],
          'keep',
        );
        await tester.pumpWidget(const SizedBox());
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      } finally {
        if (oldPlatform != null) WebViewPlatform.instance = oldPlatform;
        databaseFactory = oldFactory;
        await tester.binding.setSurfaceSize(null);
        await tester.runAsync(() async {
          await db.close();
          await dir.delete(recursive: true);
        });
      }
    },
  );
}
