import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 閲覧ページに半角カナの機種名をそのまま出さない（再発防止、2026-11-17 利用者「店の入れ方の振り返り文字化けしすぎ。
/// こういう文字化け多いよ。前も機能追加したら同じ文字化けしてな」）。
///
/// 長町南の一覧などは機種名が半角カナ（例 ﾏｲｼﾞｬｸﾞﾗｰV）。閲覧ページの字体に無い半角カナは□になるので、画面に出すときは
/// `displayMachineName`（全角にそろえる）を通す決まり。新しい画面で通し忘れて□になったのが2回あった
/// （11/12ごろ 日次学習の画面、11/17 店の入れ方のふり返り）。画面ごとの試験だけでは次の新しい画面で漏れるので、
/// 日の画面と、そこのボタンから開くすべての画面をたどり、出ている文字に半角カナが無いことを確かめる。
/// 新しい画面をボタンで足せば、この試験が自動で見る。
final _halfWidthKana = RegExp(r'[ｦ-ﾟ]');

const _machines = ['ﾏｲｼﾞｬｸﾞﾗｰV', 'ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3', 'L MHRｻﾝﾌﾞﾚｲｸXA'];

/// メルヘン（長町南）と P’s CUBE（P-STATION）の両方の閲覧ページを見る。
List<SlotRecord> _records(String store) => [
  for (final day in ['2026-11-12', '2026-11-13', '2026-11-14'])
    for (var i = 0; i < 18; i++)
      SlotRecord(
        store: store,
        day: day,
        machine: _machines[i % _machines.length],
        rack: 1101 + i,
        games: 2000 + i * 150,
        bb: 4 + i % 5,
        rb: 3 + i % 4,
        maxHold: store.startsWith('pscube:') ? null : 900 + i * 40,
        extra: store.startsWith('pscube:')
            ? {
                'source': 'pscube',
                'rate': '20',
                'my': 1500 + i * 30,
                'net_medals': i % 3 == 0 ? 800 + i * 10 : -300 - i * 10,
                'machine_type': i % 3 == 2 ? 'other' : 'normal',
              }
            : {'jo_net': i % 3 == 0 ? 800 + i * 10 : -300 - i * 10},
      ),
];

/// 今の画面に出ている文字（Text・RichText）のうち、半角カナを含むもの。
List<String> _shown(WidgetTester tester) {
  final texts = <String>{};
  for (final e in find.byType(RichText).evaluate()) {
    texts.add((e.widget as RichText).text.toPlainText());
  }
  for (final e in find.byType(EditableText).evaluate()) {
    texts.add((e.widget as EditableText).controller.text);
  }
  return [
    for (final t in texts)
      if (_halfWidthKana.hasMatch(t)) t,
  ];
}

/// ボタンの文字（アイコンつきのボタンは中の部品が非公開なので、描かれた文字から読む）。
String _label(WidgetTester tester, Finder button) => [
  for (final e
      in find
          .descendant(of: button, matching: find.byType(RichText))
          .evaluate())
    (e.widget as RichText).text.toPlainText(),
].where((t) => t.trim().isNotEmpty).join(' ');

void main() {
  for (final store in ['nagamachiminami', 'pscube:c740601:20']) {
    testWidgets('日の画面と、ボタンから開くすべての画面に半角カナの機種名が出ない（$store）', (tester) async {
      await tester.binding.setSurfaceSize(const Size(430, 9000));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: ViewerHome(initialData: ViewerData(records: _records(store))),
        ),
      );
      await tester.pumpAndSettle();
      final problems = <String>[];
      void check(String where) {
        for (final t in _shown(tester)) {
          problems.add('$where：$t');
        }
      }

      check('日の画面');
      final buttons = find.byWidgetPredicate(
        (w) => w is ButtonStyleButton && w.onPressed != null,
      );
      final count = buttons.evaluate().length;
      expect(count, greaterThan(5), reason: '日の画面のボタンをたどれている');
      final visited = <String>[];
      // ずっと動く表示（読み込み中の丸など）がある画面もあるので、落ち着くまで待たずに一定時間だけ進める。
      Future<void> advance() async {
        for (var k = 0; k < 40; k++) {
          await tester.pump(const Duration(milliseconds: 50));
        }
      }

      for (var i = 0; i < count; i++) {
        final all = buttons.evaluate().toList();
        if (i >= all.length) break;
        final button = all[i].widget;
        final target = find.byWidget(button);
        final label = _label(tester, target);
        await tester.ensureVisible(target);
        await tester.pump(const Duration(milliseconds: 300));
        await tester.tap(target, warnIfMissed: false);
        await advance();
        tester.takeException();
        visited.add(label);
        check(label.isEmpty ? 'ボタン${i + 1}' : label);
        final navigator = tester.state<NavigatorState>(
          find.byType(Navigator).first,
        );
        while (navigator.canPop()) {
          navigator.pop();
          await advance();
        }
        tester.takeException();
      }
      expect(visited.where((v) => v.contains('店の入れ方のふり返り')), isNotEmpty);
      expect(visited.where((v) => v.contains('狙い台一覧')), isNotEmpty);
      expect(problems, isEmpty, reason: '半角カナのまま出ている所（displayMachineName を通す）');
    });
  }
}
