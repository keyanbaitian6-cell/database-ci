import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/capture_health_ui.dart';

void main() {
  testWidgets('選んだ店舗・日だけの欠測理由を表示し、0枚や未確認の工程と区別する', (tester) async {
    final records = [
      {
        'store': 'pscube:c740601:20',
        'day': '2026-10-23',
        'rack': 1,
        'machine': '試験機種',
        'net_medals': 0,
      },
      {
        'store': 'pscube:c740601:20',
        'day': '2026-10-23',
        'rack': 2,
        'machine': '試験機種',
        'net_medals': null,
        'net_capture': {'reason': 'network'},
      },
      {
        'store': 'pscube:c740601:20',
        'day': '2026-10-22',
        'rack': 3,
        'machine': '別の日',
        'net_medals': null,
      },
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showCaptureHealth(
                context,
                records: records,
                store: 'pscube:c740601:20',
                day: '2026-10-23',
                pscube: true,
              ),
              child: const Text('開く'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('開く'));
    await tester.pumpAndSettle();
    final text = tester
        .widget<Text>(
          find.byWidgetPredicate(
            (w) => w is Text && (w.data?.contains('Google側の処理') ?? false),
          ),
        )
        .data!;
    expect(text, contains('2台中1台取得済み（0枚1台）・未取得1台'));
    expect(text, contains('2番 試験機種：差枚の通信失敗'));
    expect(text, isNot(contains('3番')));
    expect(text, contains('Google側の処理：未確認'));
    expect(text, contains('この端末の読み込み：未確認'));
  });
}
