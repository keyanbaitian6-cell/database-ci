// 端末で撮ったジャグラーオンラインの画面（PNG）を、アプリと同じ読み取りで読んで表示する（確かめ用）。
// 使い方（database_android/ で）：dart --packages=.dart_tool/package_config.json tool/juggler_read.dart <画面.png> ...
import 'dart:io';

import 'package:database_android/juggler_online.dart';
import 'package:image/image.dart' as imglib;

void main(List<String> args) {
  for (final path in args) {
    final image = imglib.decodePng(File(path).readAsBytesSync())!;
    final screen = parseJoScreen(image, const [], DateTime(2026, 10, 9));
    stdout.writeln('${path.split('/').last} side=${screen.side} problem=${screen.problem}');
    for (final r in screen.racks) {
      stdout.writeln('  ${r.rack} ${r.values} ${r.unreadable.isEmpty ? '' : '読めない:${r.unreadable}'}');
    }
  }
}
