import 'package:database_android/list_views.dart';
import 'package:database_android/setting_estimate.dart';
import 'package:flutter_test/flutter_test.dart';

/// 画面に出す機種名（2026-11-22、Geminiの点検 M-7②）。P-STATIONの機種名の3つに半角の中点「･」があり、半角カナと
/// 同じく閲覧ページの字体に無い。表示だけ全角にし、照合に使う foldHalfWidthKana は変えない。
void main() {
  test('半角の中点・句読点・かぎ括弧も全角で出す', () {
    expect(displayMachineName('Lｺﾞｰ･ｼﾞｬｸﾞﾗｰ'), 'Lゴー・ジャグラー');
    expect(displayMachineName('｢ﾃｽﾄ｣､ﾃｽﾄ｡'), '「テスト」、テスト。');
    expect(displayMachineName('マイジャグラーV'), 'マイジャグラーV', reason: '全角のままの名前は変えない');
  });

  test('照合に使う変換（設定の推定・翌日候補の機種の照合）は変えない', () {
    expect(foldHalfWidthKana('Lｺﾞｰ･ｼﾞｬｸﾞﾗｰ'), 'Lゴー･ジャグラー');
  });
}
