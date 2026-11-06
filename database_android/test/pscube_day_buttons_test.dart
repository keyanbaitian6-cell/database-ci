// ignore_for_file: depend_on_referenced_packages
import 'dart:io';

import 'package:database_android/pscube_import_page.dart';
import 'package:database_android/pscube_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

import 'pscube_browser_test.dart' show BrowserPlatform;

void main() {
  testWidgets('日付指定取り込みと、上から・下からのボタンで自動取り込みを始める', (tester) async {
    final oldPlatform = WebViewPlatform.instance;
    final dir = (await tester.runAsync(
      () => Directory.systemTemp.createTemp('pscube-days-test-'),
    ))!;
    sqfliteFfiInit();
    databaseFactory = databaseFactoryFfiNoIsolate;
    final oldFactory = databaseFactory;
    await tester.runAsync(() => databaseFactory.setDatabasesPath(dir.path));
    WebViewPlatform.instance = BrowserPlatform();
    await tester.binding.setSurfaceSize(const Size(390, 900));
    final db = (await tester.runAsync(PscubeStore.open))!;
    try {
      await tester.pumpWidget(const MaterialApp(home: PscubeImportPage()));
      await tester.pumpAndSettle();
      final top = find.widgetWithText(FilledButton, '上から取り込む');
      final bottom = find.widgetWithText(FilledButton, '下から取り込む');
      // SQLiteとアセットの初期化完了を待つ。100ms固定ではWindowsの実I/O完了を保証しない。
      for (
        var i = 0;
        i < 60 && tester.widget<FilledButton>(top).onPressed == null;
        i++
      ) {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 50)),
        );
        await tester.pumpAndSettle();
      }
      expect(top, findsOneWidget);
      expect(bottom, findsOneWidget);
      expect(
        tester.widget<FilledButton>(top).onPressed,
        isNotNull,
        reason: tester
            .widgetList<Text>(find.byType(Text))
            .map((t) => t.data)
            .join('\n'),
      );
      expect(find.text('日付指定取り込み（取り込む日）'), findsOneWidget);
      expect(find.text('指定なし（サイトの表示どおり）'), findsOneWidget);
      // 日付を選ぶ（直近7日の営業日）。
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      expect(find.textContaining('今の営業日'), findsOneWidget);
      await tester.tap(find.textContaining('今の営業日').last);
      await tester.pumpAndSettle();
      // 下から取り込む：自動取り込みがONになり、ONの間は日付も向きも変えられない。
      await tester.tap(bottom);
      await tester.pumpAndSettle();
      expect(find.text('自動取り込み：ON'), findsOneWidget);
      expect(tester.widget<FilledButton>(top).onPressed, isNull);
      expect(tester.widget<FilledButton>(bottom).onPressed, isNull);
      expect(
        tester
            .widget<DropdownButtonFormField<String>>(
              find.byType(DropdownButtonFormField<String>),
            )
            .onChanged,
        isNull,
      );
      // OFFに戻すと、また選べる。
      await tester.tap(find.text('自動取り込み：ON'));
      await tester.pumpAndSettle();
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      expect(tester.widget<FilledButton>(top).onPressed, isNotNull);
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
  });
}
