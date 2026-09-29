import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/web_import_page.dart';

const host = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami';

void main() {
  group('機種一覧から次の機種を選ぶ判定（PC版と同じ規則）', () {
    test('YouTubeの埋め込み動画だけを表示しない対象にする', () {
      expect(isYouTubeUrl('https://www.youtube.com/embed/abc'), isTrue);
      expect(isYouTubeUrl('//www.youtube-nocookie.com/embed/abc'), isTrue);
      expect(isYouTubeUrl('https://youtu.be/abc'), isTrue);
      expect(isYouTubeUrl('https://m.youtube.com/watch?v=abc'), isTrue);
      expect(isYouTubeUrl('$host/rack_info_kt/?kind_code=21'), isFalse);
      // 名前に youtube を含むだけの別サイトは対象外
      expect(isYouTubeUrl('https://notyoutube.com/embed/abc'), isFalse);
      expect(isYouTubeUrl('https://example.com/?u=youtube.com'), isFalse);
      expect(isYouTubeUrl(null), isFalse);
    });

    test('深夜2時までは前日扱い（9/22の26時＝9/23 1:59 までは9/22）', () {
      expect(todayIso(DateTime(2026, 9, 22, 12)), '2026-09-22');
      expect(todayIso(DateTime(2026, 9, 23, 0, 30)), '2026-09-22');
      expect(todayIso(DateTime(2026, 9, 23, 1, 59, 59)), '2026-09-22');
      expect(todayIso(DateTime(2026, 9, 23, 2)), '2026-09-23');
      // 月・年の変わり目
      expect(todayIso(DateTime(2026, 10, 1, 1)), '2026-09-30');
      expect(todayIso(DateTime(2027, 1, 1, 1)), '2026-12-31');
    });

    test('一覧の見出し行は機種として扱わない', () {
      expect(isListHeaderName('機種名 台数 通常順 ピックアップ順'), isTrue);
      expect(isListHeaderName('機種名台数通常順ピックアップ順'), isTrue);
      expect(isListHeaderName('SBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅVPA-30'), isFalse);
      expect(isListHeaderName(null), isFalse);
    });

    test('長町南店のジャグラーは対象外（半角カナの表記も）。幸町は対象のまま', () {
      expect(isExcludedMachine('nagamachiminami', 'SﾏｲｼﾞｬｸﾞﾗｰV'), isTrue);
      expect(isExcludedMachine('nagamachiminami', 'ファンキージャグラー2'), isTrue);
      expect(isExcludedMachine('nagamachiminami', 'S+ｱｲﾑｼﾞｬｸﾞﾗｰEX'), isTrue);
      expect(
        isExcludedMachine('nagamachiminami', 'L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX'),
        isFalse,
      );
      expect(isExcludedMachine('saiwaichou', 'SマイジャグラーVKD'), isFalse);
      // 幸町はブラックボードを公開していない（長町南は対象のまま・別機種は巻き込まない）
      expect(isExcludedMachine('saiwaichou', 'Sブラックボード'), isTrue);
      expect(isExcludedMachine('saiwaichou', 'Sﾌﾞﾗｯｸﾎﾞｰﾄﾞ'), isTrue);
      expect(isExcludedMachine('nagamachiminami', 'Sブラックボード'), isFalse);
      expect(
        isExcludedMachine('nagamachiminami', 'LｽｰﾊﾟｰﾌﾞﾗｯｸｼﾞｬｯｸSLDC'),
        isFalse,
      );
      expect(isExcludedMachine('saiwaichou', 'LスーパーブラックジャックSLDC'), isFalse);
      expect(isExcludedMachine(null, 'SマイジャグラーVKD'), isFalse);
      expect(isExcludedMachine('nagamachiminami', null), isFalse);
    });

    test('沖ドキ・オキドキは両店とも対象外（全角・半角とも）。似た名前は巻き込まない', () {
      for (final store in ['nagamachiminami', 'saiwaichou']) {
        // 実サイトの表記（長町南は半角カナ）。
        expect(isExcludedMachine(store, 'S/沖ﾄﾞｷ!GOLD/LS'), isTrue);
        expect(isExcludedMachine(store, 'L/ｵｷﾄﾞｷﾃﾞｭｵ2/FR'), isTrue);
        expect(isExcludedMachine(store, 'L／オキドキデュオ2／FR'), isTrue);
        expect(isExcludedMachine(store, 'パチスロ沖ドキ！DUO'), isTrue);
        // 「コードギアス」「ドキドキ」は別機種。
        expect(isExcludedMachine(store, 'Sｺｰﾄﾞｷﾞｱｽ3C.C. FS'), isFalse);
        expect(isExcludedMachine(store, 'L コードギアス復活のルルーシュ ZS'), isFalse);
        expect(isExcludedMachine(store, 'ドキドキ'), isFalse);
      }
    });

    test('低貸し（kind_code=10・5）の機種へは移動しない', () {
      expect(
        isTargetKindUrl('$host/standlist_slot/?kind_code=21&machine_name=a'),
        isTrue,
      );
      expect(
        isTargetKindUrl('$host/standlist_slot/?kind_code=10&machine_name=a'),
        isFalse,
      );
      expect(
        isTargetKindUrl('$host/standlist_slot/?kind_code=5&machine_name=a'),
        isFalse,
      );
      expect(isTargetKindUrl('$host/rack_info_kt/?kind_code=10'), isFalse);
      // 旧形式のリンクは種別を持たないことがあるので、無いものは対象外にしない
      expect(isTargetKindUrl('$host/standlist_slot?machine_name=a'), isTrue);
    });

    test('一覧の台数が保存台数より多いときだけ、表の取り込み直しを案内する', () {
      // 増台・取りこぼし：取り込み直せば台が増えるので案内する
      expect(listedCountNeedsReimport(listed: 10, saved: 8), isTrue);
      // 同じ台数：案内しない
      expect(listedCountNeedsReimport(listed: 8, saved: 8), isFalse);
      // 一覧の台数が不明：案内しない
      expect(listedCountNeedsReimport(listed: null, saved: 8), isFalse);
    });

    test('減台後に前日分を取り込んだとき（保存10台・一覧8台）に、同じ機種へ戻し続けない', () {
      // 取り込み直しても台は上書きされるだけで消えないため、ここで案内すると
      // 何度押しても同じ機種に戻され、後ろの機種へ進めなくなっていた。
      expect(listedCountNeedsReimport(listed: 8, saved: 10), isFalse);
    });
  });
}
