import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/daily_learning_page.dart';

Map<String, dynamic> fixture() => {
  'format': 'daily-learning',
  'version': 1,
  'updated_at': '2026-11-11T07:30:00+09:00',
  'status': '学習済み・比較中',
  'days': [
    {
      'target': '2026-11-11',
      'input_day': '2026-11-10',
      'saved_at': '2026-11-11T07:30:00+09:00',
      'groups': [
        {
          'store': 'nagamachiminami',
          'name': '試験機',
          'active': 'current',
          'status': '改善未確認',
          'selected': [
            ['nagamachiminami', '', '試験機', 101],
          ],
        },
      ],
    },
  ],
};

void main() {
  test('日次学習の形式と締切を検査する', () {
    expect(parseDailyLearning(jsonEncode(fixture()))['days'], hasLength(1));
    final raw = fixture();
    (raw['days'] as List).first['saved_at'] = '2026-11-11T08:00:00+09:00';
    expect(() => parseDailyLearning(jsonEncode(raw)), throwsFormatException);
    expect(() => parseDailyLearning('{}'), throwsFormatException);
  });
  testWidgets('店舗・対象日・従来方式・候補とエラーを表示する', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: DailyLearningPage(load: () async => jsonEncode(fixture())),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('日次学習・採用中の候補'), findsOneWidget);
    final dropdown = find.byType(DropdownButton<String>).last;
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('対象日 2026-11-11').last);
    await tester.pumpAndSettle();
    expect(find.text('採用中 従来方式'), findsOneWidget);
    expect(find.text('101番 試験機'), findsOneWidget);
    await tester.pumpWidget(
      MaterialApp(
        home: DailyLearningPage(
          key: const ValueKey('failure'),
          load: () async => throw StateError('失敗'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('日次学習を読み込めません'), findsOneWidget);
  });
}
