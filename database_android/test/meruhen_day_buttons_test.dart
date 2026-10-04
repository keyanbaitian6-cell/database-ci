// ignore_for_file: depend_on_referenced_packages
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:webview_flutter_platform_interface/webview_flutter_platform_interface.dart';

import 'meruhen_browser_test.dart' show MeruhenPlatform, page;

void main() {
  testWidgets('メルヘンも日付指定と、上から・下からのボタンで自動取り込みを始める', (tester) async {
    final oldPlatform = WebViewPlatform.instance;
    WebViewPlatform.instance = MeruhenPlatform();
    await tester.binding.setSurfaceSize(const Size(390, 900));
    try {
      await tester.pumpWidget(page());
      await tester.pumpAndSettle();
      final top = find.widgetWithText(FilledButton, '上から取り込む');
      final bottom = find.widgetWithText(FilledButton, '下から取り込む');
      await tester.ensureVisible(top);
      expect(top, findsOneWidget);
      expect(bottom, findsOneWidget);
      expect(tester.widget<FilledButton>(top).onPressed, isNotNull);
      expect(find.text('日付指定取り込み（取り込む日）'), findsOneWidget);
      expect(find.text('指定なし（サイトの表示どおり）'), findsOneWidget);
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      expect(find.textContaining('今の営業日'), findsOneWidget);
      await tester.tap(find.textContaining('今の営業日').last);
      await tester.pumpAndSettle();
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
        reason: 'ONの間は日付を変えられない',
      );
      await tester.ensureVisible(find.text('自動取り込み：ON'));
      await tester.tap(find.text('自動取り込み：ON'));
      await tester.pumpAndSettle();
      expect(find.text('自動取り込み：OFF'), findsOneWidget);
      await tester.ensureVisible(top);
      expect(tester.widget<FilledButton>(top).onPressed, isNotNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    } finally {
      if (oldPlatform != null) WebViewPlatform.instance = oldPlatform;
      await tester.binding.setSurfaceSize(null);
    }
  });
}
