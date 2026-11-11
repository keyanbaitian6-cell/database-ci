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
  test('最初に開く対象日は23:30から翌日（日本時間）', () {
    expect(dailyDefaultTarget(DateTime.parse('2026-11-11T14:29:59Z')), '2026-11-11');
    expect(dailyDefaultTarget(DateTime.parse('2026-11-11T14:30:00Z')), '2026-11-12');
    expect(dailyDefaultTarget(DateTime.parse('2026-11-11T22:59:00Z')), '2026-11-12');
    expect(dailyDefaultTarget(DateTime.parse('2026-12-31T14:45:00Z')), '2027-01-01');
  });
  test('日次学習の形式と締切を検査する', () {
    expect(parseDailyLearning(jsonEncode(fixture()))['days'], hasLength(1));
    final raw = fixture();
    (raw['days'] as List).first['saved_at'] = '2026-11-11T08:00:00+09:00';
    expect(() => parseDailyLearning(jsonEncode(raw)), throwsFormatException);
    expect(() => parseDailyLearning('{}'), throwsFormatException);
  });
  test('保存時刻は対象日の前日23:30〜当日08:00だけ受け付ける', () {
    // 2026-11-11 利用者「23時半～8時でいいよ」。PC・Googleスクリプト・共有ページと同じ判定。
    for (final (stamp, ok) in [
      ('2026-11-10T23:30:00+09:00', true),
      ('2026-11-10T23:29:59+09:00', false),
      ('2026-11-11T00:00:00+09:00', true),
      ('2026-11-11T07:59:59+09:00', true),
      ('2026-11-11T23:30:00+09:00', false),
      ('2026-11-09T23:45:00+09:00', false),
      ('2026-11-10T14:30:00Z', true),
    ]) {
      final raw = fixture();
      final day = (raw['days'] as List).first as Map;
      day['saved_at'] = stamp;
      for (final g in day['groups'] as List) {
        (g as Map).remove('saved_at');
      }
      if (ok) {
        expect(parseDailyLearning(jsonEncode(raw))['days'], hasLength(1), reason: stamp);
      } else {
        expect(() => parseDailyLearning(jsonEncode(raw)), throwsFormatException, reason: stamp);
      }
    }
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
  testWidgets('半角カナの機種名を全角にそろえて表示する', (tester) async {
    // 2026-11-12 iPhoneの閲覧ページで半角カナ（例「ｻﾝﾌﾞﾚｲｸ」）が□になった。ほかの画面と同じ displayMachineName を通す。
    final raw = fixture();
    final g = ((raw['days'] as List).first['groups'] as List).first as Map;
    g['name'] = 'L MHRｻﾝﾌﾞﾚｲｸXA';
    g['selected'] = [
      ['nagamachiminami', '', 'L MHRｻﾝﾌﾞﾚｲｸXA', 1157],
    ];
    await tester.pumpWidget(
      MaterialApp(home: DailyLearningPage(load: () async => jsonEncode(raw))),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButton<String>).last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('対象日 2026-11-11').last);
    await tester.pumpAndSettle();
    expect(find.text('L MHRサンブレイクXA'), findsOneWidget);
    expect(find.text('1157番 L MHRサンブレイクXA'), findsOneWidget);
    expect(find.textContaining('ｻﾝ'), findsNothing);
  });
}
