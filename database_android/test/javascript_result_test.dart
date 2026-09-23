import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/web_import_page.dart';

/// 例外の文言が [text] を含むか。
Matcher throwsMessage(String text) => throwsA(
  isA<FormatException>().having((e) => e.message, 'message', contains(text)),
);

void main() {
  group('WebViewのJavaScriptの結果を読む', () {
    test('Map・JSON文字列・二重にJSON化された文字列はどれも読める', () {
      final expected = {'store': 'saiwaichou', 'day': '2026-09-15'};
      expect(decodeJavaScriptResult(expected), expected);
      expect(decodeJavaScriptResult(jsonEncode(expected)), expected);
      // Android WebView は結果の文字列をさらにJSON化して返すことがある
      expect(
        decodeJavaScriptResult(jsonEncode(jsonEncode(expected))),
        expected,
      );
    });

    test('null・空文字・"null" は「結果が空」として、型エラーにせず日本語で失敗させる', () {
      for (final value in [
        null,
        '',
        '   ',
        'null',
        'undefined',
        jsonEncode(''),
      ]) {
        expect(
          () => decodeJavaScriptResult(value),
          throwsMessage('結果が空でした'),
          reason: '入力: ${jsonEncode(value)}',
        );
      }
    });

    test('JSONでない文字列や、Mapでない値は「形式が不正」として失敗させる', () {
      for (final value in [
        '<html>',
        '{壊れた',
        '[1,2]',
        '42',
        jsonEncode([1, 2]),
      ]) {
        expect(
          () => decodeJavaScriptResult(value),
          throwsMessage('形式が不正です'),
          reason: '入力: $value',
        );
      }
    });

    test('スクリプトが {error: ...} を返したら、その文言をそのまま伝える', () {
      final value = jsonEncode({'error': 'グラフを検出できません。個別台のグラフ画面を表示してください。'});
      expect(() => decodeJavaScriptResult(value), throwsMessage('グラフを検出できません'));
      // 空の error は失敗扱いにしない（中身のある結果として読む）
      expect(
        decodeJavaScriptResult(jsonEncode({'error': '', 'rows': []}))['rows'],
        isEmpty,
      );
    });

    test('何を読もうとして失敗したかを文言に含められる', () {
      expect(
        () => decodeJavaScriptResult(null, what: '機種一覧'),
        throwsMessage('機種一覧を読み取れませんでした'),
      );
    });
  });
}
