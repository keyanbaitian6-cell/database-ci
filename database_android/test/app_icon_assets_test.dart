import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;

void expectSquare(String path, int size) {
  final decoded = img.decodePng(File(path).readAsBytesSync());
  expect(decoded, isNotNull, reason: path);
  expect(decoded!.width, size, reason: path);
  expect(decoded.height, size, reason: path);
  expect(decoded.getPixel(size ~/ 2, size ~/ 2).a, 255, reason: path);
}

void main() {
  test(
    'Android manifest keeps existing launcher reference and all densities',
    () {
      expect(
        File('android/app/src/main/AndroidManifest.xml').readAsStringSync(),
        contains('android:icon="@mipmap/ic_launcher"'),
      );
      for (final density in {
        'mdpi': 48,
        'hdpi': 72,
        'xhdpi': 96,
        'xxhdpi': 144,
        'xxxhdpi': 192,
      }.entries) {
        expectSquare(
          'android/app/src/main/res/mipmap-${density.key}/ic_launcher.png',
          density.value,
        );
      }
    },
  );
  test(
    'PWA manifest points to actual new-version PNGs with matching dimensions',
    () {
      final manifest =
          jsonDecode(File('web/manifest.json').readAsStringSync()) as Map;
      final icons = manifest['icons'] as List;
      expect(icons, hasLength(4));
      for (final item in icons) {
        final uri = Uri.parse(item['src'] as String);
        expect(uri.queryParameters['v'], 'panda-20260930');
        final size = int.parse((item['sizes'] as String).split('x').first);
        expectSquare('web/${uri.path}', size);
      }
      expect(icons.where((i) => i['purpose'] == 'maskable').length, 2);
    },
  );
  test(
    'iPhone touch icon and favicon are versioned and exist at expected sizes',
    () {
      final html = File('web/index.html').readAsStringSync();
      expect(
        html,
        contains('sizes="180x180" href="icons/Icon-180.png?v=panda-20260930"'),
      );
      expect(html, contains('href="favicon.png?v=panda-20260930"'));
      expect(html, contains('href="manifest.json?v=panda-20260930"'));
      expectSquare('web/icons/Icon-180.png', 180);
      expectSquare('web/favicon.png', 32);
    },
  );
}
