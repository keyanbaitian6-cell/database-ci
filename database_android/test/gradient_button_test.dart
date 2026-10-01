import 'package:database_android/gradient_button.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

BoxDecoration _decoration(WidgetTester tester) =>
    tester.widget<AnimatedContainer>(find.byType(AnimatedContainer)).decoration!
        as BoxDecoration;

void main() {
  testWidgets('指定のグラデーション・角丸・白文字で表示し、押すと実行する', (tester) async {
    var pressed = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: GradientButton(
              label: 'メルヘンワールドを取り込む',
              onPressed: () => pressed++,
            ),
          ),
        ),
      ),
    );
    final decoration = _decoration(tester);
    final gradient = decoration.gradient! as LinearGradient;
    expect(gradient.colors, const [
      Color(0xFF16A085),
      Color(0xFFF4D03F),
      Color(0xFF16A085),
    ]);
    expect(gradient.stops, const [0.0, 0.51, 1.0]);
    expect(gradient.begin, const Alignment(-1, 0));
    expect(gradient.end, const Alignment(3, 0));
    expect(decoration.borderRadius, BorderRadius.circular(10));
    expect(
      tester.widget<Text>(find.text('メルヘンワールドを取り込む')).style!.color,
      Colors.white,
    );
    await tester.tap(find.text('メルヘンワールドを取り込む'));
    await tester.pumpAndSettle();
    expect(pressed, 1);
  });

  testWidgets('押している間は右端（CSSの right center）へ流れ、離すと戻る', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: GradientButton(label: 'ボタン', onPressed: () {}),
          ),
        ),
      ),
    );
    final gesture = await tester.startGesture(
      tester.getCenter(find.text('ボタン')),
    );
    await tester.pump(const Duration(milliseconds: 600));
    expect(
      (_decoration(tester).gradient! as LinearGradient).begin,
      const Alignment(-3, 0),
    );
    await gesture.up();
    await tester.pumpAndSettle();
    expect(
      (_decoration(tester).gradient! as LinearGradient).begin,
      const Alignment(-1, 0),
    );
  });

  testWidgets('押せないときは薄く表示し、反応しない', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: GradientButton(label: 'ボタン')),
      ),
    );
    expect(tester.widget<Opacity>(find.byType(Opacity)).opacity, 0.5);
  });
}
