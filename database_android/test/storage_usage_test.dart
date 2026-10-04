import 'dart:io';

import 'package:database_android/storage_usage_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('フォルダの大きさを大きい順に数え、大きいフォルダは中身も数える', () async {
    final root = await Directory.systemTemp.createTemp('usage-');
    addTearDown(() => root.delete(recursive: true));
    final http = await Directory('${root.path}/WebView/Default/HTTP Cache')
        .create(recursive: true);
    await File('${http.path}/a').writeAsBytes(List.filled(3000, 0));
    await File('${root.path}/WebView/Default/b')
        .writeAsBytes(List.filled(500, 0));
    final picker = await Directory('${root.path}/file_picker/1')
        .create(recursive: true);
    await File('${picker.path}/backup.json').writeAsBytes(List.filled(1000, 0));
    await File('${root.path}/loose.txt').writeAsBytes(List.filled(10, 0));

    final usage = await folderUsage(root, detailOver: 100, depth: 3);
    expect(
      [for (final e in usage) (e.name, e.bytes)],
      [('WebView', 3500), ('file_picker', 1000), ('loose.txt', 10)],
    );
    final web = usage.first.children.single;
    expect((web.name, web.bytes), ('Default', 3500));
    expect(
      [for (final e in web.children) (e.name, e.bytes)],
      [('HTTP Cache', 3000), ('b', 500)],
    );
    expect(await folderUsage(Directory('${root.path}/missing')), isEmpty);
    expect(formatBytes(287 * 1000 * 1000), '287.0 MB');
    expect(storageLabel('file_picker'), contains('写し'));
  });

  testWidgets('内訳の画面は、キャッシュとデータを分けて出し、何も消さない', (tester) async {
    final root = Directory.systemTemp.createTempSync('usage-page-');
    addTearDown(() => root.deleteSync(recursive: true));
    final cache = Directory('${root.path}/cache')..createSync();
    Directory('${cache.path}/WebView').createSync();
    File('${cache.path}/WebView/x').writeAsBytesSync(List.filled(2000, 0));
    Directory('${root.path}/databases').createSync();
    File('${root.path}/databases/db').writeAsBytesSync(List.filled(4000, 0));
    await tester.runAsync(() async {
      await tester.pumpWidget(
        MaterialApp(
          home: StorageUsagePage(cacheDir: cache, dataDir: root),
        ),
      );
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pumpAndSettle();
    expect(find.textContaining('キャッシュ　合計 2 KB'), findsOneWidget);
    expect(
      find.textContaining('データ（キャッシュ以外）　合計 4 KB'),
      findsOneWidget,
      reason: 'キャッシュのフォルダはデータ側に二重に数えない',
    );
    expect(find.textContaining('WebView（取り込み画面のブラウザ'), findsOneWidget);
    expect(File('${cache.path}/WebView/x').existsSync(), isTrue);
  });
}
