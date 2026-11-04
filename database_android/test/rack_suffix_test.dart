import 'package:database_android/rack_suffix.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 差枚の一覧で選んだ台番の末尾（2026-11-05、閲覧ページだけ）。
void main() {
  test('台番の末尾', () {
    expect([7, 17, 120, 1203, 1207].map(rackSuffix), [7, 7, 0, 3, 7]);
  });

  testWidgets('末尾を選ぶ欄：選ぶ・「末尾7 ×」で消す・別の日の選択は出さない', (tester) async {
    final pick = ValueNotifier<RackSuffixPick?>(null);
    viewerSuffixPick = pick;
    addTearDown(() => viewerSuffixPick = null);
    Future<void> show(String day, {bool picker = true}) => tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ValueListenableBuilder(
            valueListenable: pick,
            builder: (_, _, _) =>
                SuffixPickBar(store: 'saiwaichou', day: day, picker: picker),
          ),
        ),
      ),
    );
    await show('2026-11-04');
    expect(find.text('末尾7 ×'), findsNothing);
    await tester.tap(find.byKey(const ValueKey('suffix-7')));
    await tester.pump();
    expect(pick.value?.digit, 7);
    expect(find.text('末尾7 ×'), findsOneWidget);
    // 機種の表（picker: false）でも「末尾7 ×」で消せる。
    await show('2026-11-04', picker: false);
    expect(find.byKey(const ValueKey('suffix-3')), findsNothing);
    await tester.tap(find.text('末尾7 ×'));
    await tester.pump();
    expect(pick.value, isNull);
    // 日付を変えたら消す。
    pick.value = const RackSuffixPick('saiwaichou', '2026-11-04', 7);
    clearSuffixPickUnless('saiwaichou', '2026-11-03');
    expect(pick.value, isNull);
    pick.value = const RackSuffixPick('saiwaichou', '2026-11-04', 7);
    clearSuffixPickUnless('saiwaichou', '2026-11-04');
    expect(pick.value?.digit, 7, reason: '同じ店・同じ日なら残す');
    clearSuffixPickUnless('nagamachiminami', '2026-11-04');
    expect(pick.value, isNull, reason: '店を変えたら消す');
  });

  testWidgets('Android版（viewerSuffixPick が null）では欄を出さない', (tester) async {
    viewerSuffixPick = null;
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SuffixPickBar(store: 'saiwaichou', day: '2026-11-04'),
        ),
      ),
    );
    expect(find.text('末尾'), findsNothing);
  });
}
