// メルヘン：機種の表の代わりにサイトが「該当する台情報が見つかりませんでした」を出す機種は、
// その日は飛ばして次の機種へ進む（2026-10-11 利用者「その仕様に両方作り替えて」）。
// PC版 tests/test_meruhen_no_racks.py と同じ規則。画面のJSは tool/test_meruhen_no_racks_browser.mjs
// （PC）と tool/test_meruhen_no_racks_android.mjs（Android）。
import 'package:database_android/import_day.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('the key ignores spacing and width, and keeps store and day apart', () {
    final key = noRacksKey('nagamachiminami', '2026-10-10', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8');
    expect(noRacksKey('nagamachiminami', '2026-10-10', 'Sﾊｲﾊﾟｰﾗｯｼｭ SLC8'), key);
    expect(
      noRacksKey('nagamachiminami', '2026-10-09', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8'),
      isNot(key),
      reason: '別の日は飛ばさない',
    );
    expect(
      noRacksKey('saiwaichou', '2026-10-10', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8'),
      isNot(key),
    );
  });

  test('the notice and the list page are the same as on PC', () {
    expect(
      noRacksNotice('2026-10-10', 'SﾊｲﾊﾟｰﾗｯｼｭSLC8'),
      '10/10のSﾊｲﾊﾟｰﾗｯｼｭSLC8は、サイトに台情報がありません（該当する台情報が見つかりませんでした）。'
      'この日は飛ばして、次の機種へ進みます。',
    );
    expect(
      meruhenMachineListUrl('nagamachiminami', '2026-10-10'),
      'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info_kt/?kind_code=21'
      '#database_next_machine=1&database_day=2026-10-10',
    );
  });
}
