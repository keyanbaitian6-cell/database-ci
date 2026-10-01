import 'dart:io';

import 'package:database_android/main.dart' show isPscubeBackupFile;
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('P’s CUBEのバックアップは先頭で見分け、メルヘンの読み込みに通さない', () async {
    final dir = await Directory.systemTemp.createTemp('route');
    addTearDown(() => dir.delete(recursive: true));
    final pscube = File('${dir.path}/p.json')
      ..writeAsStringSync(
        '{"format":"pscube-viewer","version":1,"kind":"backup"}',
      );
    final spaced = File('${dir.path}/s.json')
      ..writeAsStringSync('{ "format" : "pscube-viewer", "version": 1 }');
    final meruhen = File('${dir.path}/m.json')
      ..writeAsStringSync('{"format": "database-backup", "version": 1}');
    expect(await isPscubeBackupFile(pscube), isTrue);
    expect(await isPscubeBackupFile(spaced), isTrue);
    expect(await isPscubeBackupFile(meruhen), isFalse);
  });
}
