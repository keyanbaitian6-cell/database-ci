import 'dart:async';

import 'package:database_android/pscube_connection.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter_test/flutter_test.dart';

const rack = '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=1526#20261001';

void main() {
  test('初回通信はCookie設定完了まで待ち、失敗した場合は開かない', () async {
    final calls = <String>[];
    final cookies = Completer<void>();
    final task = preparePscubeBrowser(
      configureJavaScript: () async => calls.add('js'),
      configureNavigation: () async => calls.add('navigation'),
      configureCookies: () {
        calls.add('cookies');
        return cookies.future;
      },
      load: () async => calls.add('load'),
      active: () => true,
    );
    await Future<void>.delayed(Duration.zero);
    expect(calls, ['js', 'navigation', 'cookies']);
    cookies.complete();
    await task;
    expect(calls.last, 'load');
    calls.clear();
    await expectLater(
      preparePscubeBrowser(
        configureJavaScript: () async {},
        configureNavigation: () async {},
        configureCookies: () async => throw StateError('cookie setup failed'),
        load: () async => calls.add('load'),
        active: () => true,
      ),
      throwsStateError,
    );
    expect(calls, isEmpty);
  });
  test('Cookie設定中に画面を閉じたら通信しない', () async {
    var active = true;
    var loads = 0;
    await preparePscubeBrowser(
      configureJavaScript: () async {},
      configureNavigation: () async {},
      configureCookies: () async => active = false,
      load: () async => loads++,
      active: () => active,
    );
    expect(loads, 0);
  });
  test('DNS失敗後のpageFinishedは失敗を消さず、再読み込み完了まで取得しない', () {
    final c = PscubeConnection()..start(rack);
    expect(
      c.networkError(
        url: rack.split('#').first,
        mainFrame: true,
        code: -2,
        description: 'net::ERR_NAME_NOT_RESOLVED',
      ),
      isTrue,
    );
    expect(c.failure!.message, contains('DNS'));
    c.finish(rack);
    expect(c.canCapture, isFalse);
    c.start(rack);
    expect(c.canCapture, isFalse);
    c.finish(rack);
    expect(c.canCapture, isTrue);
    expect(c.history, hasLength(1));
  });
  test('同じ取得先の403は失敗、広告・認証・別台の403は無視', () {
    final c = PscubeConnection()..start(rack);
    for (final url in [
      'https://ads.example/ad.php',
      'https://hcaptcha.com/check',
      '${PscubeStore.root}cgi-bin/ad.php',
      '${PscubeStore.root}cgi-bin/nc-v06-001.php?cd_dai=1527',
      PscubeStore.index,
    ]) {
      expect(c.httpError(url: url, status: 403), isFalse, reason: url);
    }
    expect(
      c.httpError(url: '${rack.split('#').first}&action=graph', status: 403),
      isTrue,
    );
    c.finish(rack);
    expect(c.canCapture, isFalse);
    expect(c.failure!.message, contains('403'));
  });
  test('古いURL・主ページ以外のエラーは新ページを変えない', () {
    final c = PscubeConnection()..start(rack);
    final other = rack.replaceFirst('1526', '1527');
    c.start(other);
    expect(
      c.networkError(url: rack, mainFrame: true, code: -2, description: 'DNS'),
      isFalse,
    );
    expect(c.finish(rack), isFalse);
    expect(c.loading, isTrue);
    expect(
      c.networkError(
        url: other,
        mainFrame: false,
        code: -2,
        description: 'DNS',
      ),
      isFalse,
    );
    expect(
      c.networkError(url: null, mainFrame: true, code: -2, description: 'DNS'),
      isFalse,
    );
    c.finish(other);
    expect(c.canCapture, isTrue);
  });
  test('診断履歴は最大8件、クエリ・認証値を出さない', () {
    final c = PscubeConnection();
    for (var i = 0; i < 10; i++) {
      c.start(rack);
      c.httpError(url: '${rack.split('#').first}&token=secret', status: 500);
    }
    expect(c.history, hasLength(8));
    expect(c.history.last.report, contains('HTTP 500'));
    expect(c.history.last.report, isNot(contains('secret')));
    expect(c.history.last.report, isNot(contains('cd_dai')));
  });
  test('再読み込み対象はHTTPS・指定店の既知ページだけ', () {
    expect(PscubeConnection.allowedPage(Uri.parse(rack)), isTrue);
    expect(PscubeConnection.allowedPage(Uri.parse(PscubeStore.root)), isTrue);
    for (final url in [
      'about:blank',
      'http://www.pscube.jp/',
      'https://www.pscube.jp:444${PscubeConnection.shopPath}',
      'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c000000/',
      'https://user:password@www.pscube.jp${PscubeConnection.shopPath}',
      'https://www.pscube.jp${PscubeConnection.shopPath}cgi-bin/unknown.php',
    ]) {
      expect(
        PscubeConnection.allowedPage(Uri.parse(url)),
        isFalse,
        reason: url,
      );
    }
  });
}
