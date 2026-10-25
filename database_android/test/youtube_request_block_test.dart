import 'dart:convert';
import 'dart:io';

import 'package:database_android/browser_session.dart';
import 'package:database_android/youtube_request_block.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

const _kotlin =
    'android/app/src/main/kotlin/com/keyan/database_android/YouTubeRequestBlocker.kt';

/// webview_flutter_android の端末側ソース（WebViewClient の実装）の場所。
File _pluginWebViewClient() {
  final config = File('.dart_tool/package_config.json');
  final packages = (jsonDecode(config.readAsStringSync())['packages'] as List)
      .cast<Map<String, dynamic>>();
  final plugin = packages.firstWhere(
    (p) => p['name'] == 'webview_flutter_android',
  );
  var root = config.absolute.uri.resolve(plugin['rootUri'] as String);
  if (!root.path.endsWith('/')) root = root.replace(path: '${root.path}/');
  return File.fromUri(
    root.resolve(
      'android/src/main/java/io/flutter/plugins/webviewflutter/WebViewClientProxyApi.java',
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('database/web_requests');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  group('取り込み画面で通信を起こさない YouTube の宛先（2026-10-25）', () {
    test('動画・サムネイル・再生の通信をホスト名で止める', () {
      for (final url in [
        'https://www.youtube.com/embed/abc',
        'https://youtube.com/iframe_api',
        'https://m.youtube.com/watch?v=abc',
        'https://www.youtube-nocookie.com/embed/abc',
        'https://youtu.be/abc',
        'https://i.ytimg.com/vi/abc/hqdefault.jpg',
        'https://s.ytimg.com/yts/jsbin/www-widgetapi.js',
        'https://rr1---sn-abc.googlevideo.com/videoplayback?id=1',
        'HTTPS://WWW.YOUTUBE.COM/embed/abc',
      ]) {
        expect(isYouTubeRequestUrl(url), isTrue, reason: url);
      }
    });

    test('取り込み先のページや、名前・パスに youtube を含むだけの別サイトは止めない', () {
      for (final url in [
        'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21',
        'https://meruhenworld.pt.teramoba2.com/saiwaichou/?ref=youtube.com',
        'https://www.p-world.co.jp/youtube.com/abc',
        'https://notyoutube.com/embed/abc',
        'https://youtube.com.example.net/embed/abc',
        'https://fonts.googleapis.com/css',
        'about:blank',
        '',
        null,
      ]) {
        expect(isYouTubeRequestUrl(url), isFalse, reason: url);
      }
    });

    test('PC（pscube_connection.py の _YOUTUBE_HOSTS）と同じホスト名を止める', () {
      final source = File('../database/pscube_connection.py')
          .readAsStringSync();
      final line = RegExp(
        r'^_YOUTUBE_HOSTS = \((.*)\)$',
        multiLine: true,
      ).firstMatch(source)!;
      final pc = RegExp(r"'([^']+)'")
          .allMatches(line.group(1)!)
          .map((m) => m.group(1))
          .toList();
      expect(youTubeRequestHosts, pc);
    });
  });

  group('端末側への依頼', () {
    test('WebView の番号と止めるホスト名を渡す', () async {
      messenger.setMockMethodCallHandler(channel, (call) async {
        expect(call.method, 'blockYouTube');
        expect(call.arguments, {'webView': 7, 'hosts': youTubeRequestHosts});
        return true;
      });
      expect(await blockYouTubeRequestsFor(7), isTrue);
    });

    test('止められなくても取り込みは止めない（false を返すだけ）', () async {
      messenger.setMockMethodCallHandler(channel, (_) async => false);
      expect(await blockYouTubeRequestsFor(7), isFalse);
      messenger.setMockMethodCallHandler(channel, (_) async => null);
      expect(await blockYouTubeRequestsFor(7), isFalse);
      messenger.setMockMethodCallHandler(channel, (_) async {
        throw PlatformException(code: 'failed');
      });
      expect(await blockYouTubeRequestsFor(7), isFalse);
      messenger.setMockMethodCallHandler(channel, null);
      expect(await blockYouTubeRequestsFor(7), isFalse);
    });

    test('メルヘン・P’s CUBE の取り込み画面は、ブラウザの準備のたびに止める', () {
      for (final page in [
        'lib/web_import_page.dart',
        'lib/pscube_import_page.dart',
      ]) {
        expect(
          File(page).readAsStringSync(),
          contains('blockRequests: () => blockYouTubeRequests(_web),'),
          reason: page,
        );
      }
    });

    test('WebViewClient を置き換えた後、最初の読み込みの前に止める', () async {
      final calls = <String>[];
      Future<void> step(String name) async => calls.add(name);
      await prepareBrowserSession(
        configureJavaScript: () => step('javascript'),
        configureNavigation: () => step('navigation'),
        blockRequests: () => step('block'),
        configureCookies: () => step('cookies'),
        load: () => step('load'),
        active: () => true,
      );
      expect(calls, ['javascript', 'navigation', 'block', 'cookies', 'load']);

      // 止める設定が無い画面（呼び出し元が渡さない）は従来どおり。
      calls.clear();
      await prepareBrowserSession(
        configureJavaScript: () => step('javascript'),
        configureNavigation: () => step('navigation'),
        configureCookies: () => step('cookies'),
        load: () => step('load'),
        active: () => true,
      );
      expect(calls, ['javascript', 'navigation', 'cookies', 'load']);
    });
  });

  group('端末側（YouTubeRequestBlocker.kt）', () {
    final kotlin = File(_kotlin).readAsStringSync();

    test('YouTube の要求は外へ出さず、端末の中で空の応答（204）を返す', () {
      expect(kotlin, contains('override fun shouldInterceptRequest('));
      expect(kotlin, contains('204, "No Content"'));
      expect(kotlin, contains('host == it || host.endsWith(".\$it")'));
      expect(
        File(
          'android/app/src/main/kotlin/com/keyan/database_android/MainActivity.kt',
        ).readAsStringSync(),
        contains('"database/web_requests"'),
      );
    });

    // 包んだ WebViewClient がコールバックを渡し損ねると、読み込みの開始・完了や
    // onNavigationRequest・エラー処理が Dart に届かなくなる。プラグインを上げて
    // 新しいコールバックが増えたら、ここで落ちる。
    test('プラグインの WebViewClient が受けるコールバックをすべて元へ渡す', () {
      final plugin = _pluginWebViewClient().readAsStringSync();
      final impl = plugin.substring(
        plugin.indexOf('class WebViewClientImpl extends WebViewClient'),
        plugin.indexOf('public WebViewClientProxyApi('),
      );
      final overridden = RegExp(r'@Override\s+public\s+[\w.]+\s+(\w+)\(')
          .allMatches(impl)
          .map((m) => m.group(1)!)
          .toSet();
      expect(
        overridden,
        containsAll(['onPageStarted', 'shouldOverrideUrlLoading']),
      );
      for (final name in overridden) {
        expect(
          RegExp('override fun $name\\(').hasMatch(kotlin),
          isTrue,
          reason: '$name を元の WebViewClient へ渡していない',
        );
        expect(kotlin, contains('inner.$name('), reason: name);
      }
      // 置き換え前のものを包むだけで、二重に包まない。
      expect(kotlin, contains('if (current is Client)'));
    });
  });
}
