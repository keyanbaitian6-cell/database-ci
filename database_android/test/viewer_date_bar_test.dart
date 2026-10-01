import 'package:database_android/theme.dart';
import 'package:database_android/viewer_pages.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('日付の欄の見出し「表示する日付」が上の帯で切れない', (tester) async {
    tester.view.physicalSize = const Size(1080, 2340);
    tester.view.devicePixelRatio = 2.625;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      // 結果の画面と同じ：アプリの見た目（枠つきの入力欄）で、本文のいちばん上に置く。
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          appBar: AppBar(title: const Text('database')),
          body: Column(
            children: [
              ViewerDateBar(
                days: const ['2026-09-30', '2026-09-29'],
                day: '2026-09-30',
                onChanged: (_) {},
              ),
              const Expanded(child: SizedBox()),
            ],
          ),
        ),
      ),
    );
    final bar = tester.getRect(find.byType(ViewerDateBar));
    final label = tester.getRect(find.text('表示する日付'));
    expect(
      label.top,
      greaterThanOrEqualTo(bar.top),
      reason: '見出しの上端が帯の上にはみ出している',
    );
    final note = tester.getRect(find.text('記録がある日へ切り替え'));
    expect(note.bottom, lessThanOrEqualTo(bar.bottom), reason: '下の一行も帯の中に収まる');
  });
}
