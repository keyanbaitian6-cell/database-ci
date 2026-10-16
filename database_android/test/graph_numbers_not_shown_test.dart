import 'package:database_android/import_service.dart';
import 'package:flutter_test/flutter_test.dart';

// 2026-10-16 幸町：台ページの数字が4つとも空のまま読まれ、一覧に最大持玉が無いので
// 最大持玉が空のまま保存されていた（PCは「数値を確認できません」で止まっていた）。
CaptureAnalysis analysis({int? games, int? bb, int? rb, int? maxHold}) =>
    CaptureAnalysis(
      path: '',
      kind: CaptureKind.graph,
      fullText: '',
      store: 'saiwaichou',
      day: '2026-10-16',
      rack: 734,
      games: games,
      bb: bb,
      rb: rb,
      maxHold: maxHold,
    );

void main() {
  test('数字が4つとも空で、一覧でも最大持玉を補えないときは保存しない', () {
    final empty = analysis();
    // 一覧の記録（幸町は最大持玉なし）を引き継いだ後。
    final resolved = analysis(games: 1348, bb: 12, rb: 6);
    expect(
      graphNumbersNotShown(empty, resolved),
      '734番台：グラフ内の数値（総回転数・最大持玉など）がまだ表示されていません。'
      '数値が表示されてから取り込み直してください。',
    );
  });

  test('一覧に最大持玉があれば、これまでどおり一覧の値で保存する（長町）', () {
    expect(
      graphNumbersNotShown(
        analysis(),
        analysis(games: 1348, bb: 12, rb: 6, maxHold: 700),
      ),
      isNull,
    );
  });

  test('台ページの数字が読めていれば保存する', () {
    final read = analysis(games: 1348, bb: 12, rb: 6, maxHold: 859);
    expect(graphNumbersNotShown(read, read), isNull);
  });
}
