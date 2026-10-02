// ignore_for_file: depend_on_referenced_packages
import 'dart:async';

import 'package:database_android/web_import_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

import 'pscube_browser_test.dart' as fixture;

const root = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info';

class MeruhenPlatform extends fixture.BrowserPlatform {
  Completer<void>? settings;
  bool failSettings = false;
  final steps = <String>[];

  @override
  PlatformWebViewController createPlatformWebViewController(
    PlatformWebViewControllerCreationParams params,
  ) => controller = MeruhenController(params, this);

  @override
  PlatformWebViewCookieManager createPlatformCookieManager(
    PlatformWebViewCookieManagerCreationParams params,
  ) {
    steps.add('cookies');
    return super.createPlatformCookieManager(params);
  }

  @override
  PlatformNavigationDelegate createPlatformNavigationDelegate(
    PlatformNavigationDelegateCreationParams params,
  ) => MeruhenDelegate(params);
}

class MeruhenDelegate extends fixture.BrowserDelegate {
  MeruhenDelegate(super.params);
  @override
  Future<void> setOnNavigationRequest(
    NavigationRequestCallback callback,
  ) async {}
}

class MeruhenController extends fixture.BrowserController {
  MeruhenController(super.params, this.platform);
  final MeruhenPlatform platform;

  @override
  Future<void> setJavaScriptMode(JavaScriptMode mode) async {
    platform.steps.add('js');
    if (platform.settings != null) await platform.settings!.future;
    if (platform.failSettings) throw StateError('settings failure');
  }

  @override
  Future<void> addJavaScriptChannel(JavaScriptChannelParams params) async {
    platform.steps.add('channel');
  }

  @override
  Future<void> setPlatformNavigationDelegate(
    PlatformNavigationDelegate value,
  ) async {
    platform.steps.add('navigation');
    await super.setPlatformNavigationDelegate(value);
  }

  @override
  Future<void> loadRequest(LoadRequestParams params) async {
    platform.steps.add('load');
    url = params.uri.toString();
    loads.add(url!);
    delegate.started?.call(url!);
  }
}

Widget page() => MaterialApp(
  home: WebImportPage(
    onSave: (_) async {},
    onGraph: (_, _) async => false,
    onNext: ({required store, required day, required machine, required rack}) =>
        const NextGraphTarget(),
    onUndo: () async => '',
    onProgress: ({required store, required day}) => '',
    onMachineStatus: ({required store, required day, required machines}) => [],
    skipTableReview: () => false,
  ),
);

void main() {
  testWidgets(
    'settings finish before first Meruhen load; DNS stops auto and retry preserves browser data',
    (tester) async {
      final platform = MeruhenPlatform()..settings = Completer<void>();
      WebViewPlatform.instance = platform;
      await tester.pumpWidget(page());
      await tester.pump();
      expect(platform.controller.loads, isEmpty);
      platform.settings!.complete();
      await tester.pumpAndSettle();
      expect(platform.steps, [
        'js',
        'channel',
        'navigation',
        'cookies',
        'load',
      ]);
      await tester.tap(find.text('自動取り込み：OFF'));
      await tester.pump();
      expect(find.text('自動取り込み：ON'), findsOneWidget);
      platform.controller.delegate.network!(
        WebResourceError(
          errorCode: -2,
          description: 'net::ERR_NAME_NOT_RESOLVED',
          isForMainFrame: true,
          url: root,
        ),
      );
      platform.controller.delegate.finished!(root);
      await tester.pumpAndSettle();
      expect(find.textContaining('DNSエラー'), findsOneWidget);
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      await tester.tap(find.byTooltip('再読み込み'));
      await tester.pumpAndSettle();
      expect(platform.controller.loads, [root, root]);
      expect(platform.controller.reloads, 1);
      expect(platform.cookieClears, 0);
      expect(platform.controller.storageClears, 0);
      expect(platform.controller.cacheClears, 0);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'failed setup makes no request; reload retries setup; disposal cancels waiting load',
    (tester) async {
      final platform = MeruhenPlatform()..failSettings = true;
      WebViewPlatform.instance = platform;
      await tester.pumpWidget(page());
      await tester.pumpAndSettle();
      expect(platform.controller.loads, isEmpty);
      expect(find.textContaining('Cookie・ブラウザ設定'), findsOneWidget);
      platform.failSettings = false;
      await tester.tap(find.byTooltip('再読み込み'));
      await tester.pumpAndSettle();
      expect(platform.controller.loads, [root]);
      await tester.pumpWidget(const SizedBox());
      final waiting = MeruhenPlatform()..settings = Completer<void>();
      WebViewPlatform.instance = waiting;
      await tester.pumpWidget(page());
      await tester.pump();
      await tester.pumpWidget(const SizedBox());
      waiting.settings!.complete();
      await tester.pumpAndSettle();
      expect(waiting.controller.loads, isEmpty);
      expect(tester.takeException(), isNull);
    },
  );
}
