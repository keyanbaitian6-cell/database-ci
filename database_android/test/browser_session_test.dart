import 'dart:async';

import 'package:database_android/browser_session.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'same document reloads, preserving a newly selected history hash',
    () async {
      final calls = <String>[];
      await reopenBrowserPage(
        target: Uri.parse('https://example.test/rack#day1'),
        currentUrl: () async => 'https://example.test/rack#day2',
        reload: () async => calls.add('reload'),
        load: (uri) async => calls.add(uri.toString()),
        active: () => true,
      );
      expect(calls, ['reload']);
    },
  );

  test(
    'native error/unknown document navigates to the failed target',
    () async {
      for (final current in [
        'about:blank',
        null,
        'https://example.test/other',
      ]) {
        final calls = <String>[];
        await reopenBrowserPage(
          target: Uri.parse('https://example.test/rack#day1'),
          currentUrl: () async => current,
          reload: () async => calls.add('reload'),
          load: (uri) async => calls.add(uri.toString()),
          active: () => true,
        );
        expect(calls, ['https://example.test/rack#day1']);
      }
    },
  );

  test('disposal while querying the current URL cancels retry', () async {
    var active = true;
    final url = Completer<String?>();
    final calls = <String>[];
    final task = reopenBrowserPage(
      target: Uri.parse('https://example.test/rack'),
      currentUrl: () => url.future,
      reload: () async => calls.add('reload'),
      load: (uri) async => calls.add('load'),
      active: () => active,
    );
    active = false;
    url.complete('https://example.test/rack');
    await task;
    expect(calls, isEmpty);
  });
}
