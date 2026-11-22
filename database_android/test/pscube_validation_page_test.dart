import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../lib/pscube_validation_page.dart';

void main() {
  testWidgets('今日に候補が無くても別日の保存済み候補を表示できる', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: PscubeValidationPage(
          load: () async => jsonEncode({
            'format': 'pscube-validation',
            'version': 1,
            'days': [
              {
                'target': '2026-11-09',
                'input_day': '2026-11-08',
                'saved_at': '2026-11-09T00:21:30+09:00',
                'preliminary': 1,
                'machines': [
                  {
                    // 半角カナの機種名（P-STATION）は全角で出す（2026-11-22、Geminiの点検 H-12④）。
                    'name': 'ﾏｲｼﾞｬｸﾞﾗｰV',
                    'candidates': {
                      'random_draw': [1001],
                      'date_two_exploratory': [1009],
                    },
                  },
                ],
              },
            ],
          }),
        ),
      ),
    );
    await tester.pumpAndSettle();
    if (find.text('この日の検証候補はまだ届いていません。').evaluate().isNotEmpty) {
      await tester.tap(find.byType(DropdownButton<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('対象日 2026-11-09').last);
      await tester.pumpAndSettle();
    }
    expect(find.text('保存時刻 00:21:30（日本時間）'), findsOneWidget);
    expect(find.text('マイジャグラーV'), findsOneWidget);
    expect(find.textContaining('ﾏｲｼﾞｬｸﾞﾗｰ'), findsNothing);
    expect(find.textContaining('確定前のサイトセブン記録が1台分'), findsOneWidget);
    expect(find.textContaining('日付と下2桁が一致（探索）\n1009'), findsOneWidget);
  });
}
