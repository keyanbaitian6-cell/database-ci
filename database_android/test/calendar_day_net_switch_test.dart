import 'dart:convert';

import 'package:database_android/calendar_day_net.dart';
import 'package:database_android/daily_net_page.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

import 'calendar_day_net_test.dart' show synthetic, viaJson;

/// 段階B1の切り替え（VIEWER_DAY_STORE.md、2026-11-25）：日別キャッシュから作り、今の計算と一致した差枚表を
/// 端末に控え、カレンダーはその表から出す。控えて読み直した表が、今の計算（全記録から [dailyNet]）と全店・全日・
/// 全項目で同じこと、本体の目印が違う・壊れた控えは使わない（今の計算に戻る）ことを確かめる。

const exported = '2026-11-25T00:00:00+09:00';

ViewerData parse(
  Map<String, List<Map<String, dynamic>>> byDay, {
  String? at = exported,
}) => ViewerData.parse(
  jsonEncode({
    'header': {'exported_at': ?at},
    'records': [for (final rows in byDay.values) ...rows],
  }),
);

void expectSame(List<DayNet> a, List<DayNet> b) {
  expect(a.length, b.length);
  for (var i = 0; i < a.length; i++) {
    final x = a[i], y = b[i];
    expect(
      [y.day, y.total, y.captured, y.racks, y.needsCheck, y.judged, y.won],
      [x.day, x.total, x.captured, x.racks, x.needsCheck, x.judged, x.won],
      reason: x.day,
    );
  }
}

void main() {
  for (final days in [108, 180, 365]) {
    test('控えて読み直した差枚表は、今の計算と全店・全日・全項目で同じ（$days日）', () {
      final byDay = synthetic(days);
      final data = parse(byDay);
      final table = DayNetTable();
      for (final day in byDay.keys.toList()..sort()) {
        table.addDay(viaJson(byDay[day]!));
      }
      expect(compareDayNets(table, data.records)['status'], 'match');
      final stamp = dayNetStamp(data, 'body-1')!;
      final text = encodeDayNetTable(table, stamp);
      final stored = StoredDayNets.decode(text, stamp)!;
      expect(stored.cellCount, table.cells.length);
      final lookup = dailyNetLookup(data.records);
      for (final store in ['nagamachiminami', 'saiwaichou']) {
        final current = dailyNet(data.records, store);
        expect(current, isNotEmpty);
        // 日別差枚の月表に渡す一覧（新しい日が先）も、イベントカレンダーの1日ずつの引き方も同じ。
        expectSame(current, stored.days(store));
        for (final d in current) {
          expectSame([lookup(store, d.day)!], [stored.lookup(store, d.day)!]);
        }
        expect(stored.lookup(store, '2000-01-01'), isNull);
      }
      // 要確認の台がある日を含む（空振りでない）。差枚の無い日（合計 null）は、合成データでは365日にだけ出る。
      final all = [
        for (final s in ['nagamachiminami', 'saiwaichou']) ...stored.days(s),
      ];
      expect(all.any((d) => d.needsCheck > 0), isTrue);
      if (days == 365) expect(all.any((d) => d.total == null), isTrue);
      // 控えは小さい（localStorage に置く）。365日・2店でも100KB未満。
      expect(text.length, lessThan(100000));
    });
  }

  test('本体の目印が違う・無い・壊れた控えは使わない（今の計算に戻る）', () {
    final byDay = synthetic(40);
    final data = parse(byDay);
    final table = DayNetTable();
    for (final day in byDay.keys.toList()..sort()) {
      table.addDay(viaJson(byDay[day]!));
    }
    final stamp = dayNetStamp(data, 'body-1')!;
    expect(stamp, 'body-1|$exported|${data.records.length}');
    final text = encodeDayNetTable(table, stamp);
    expect(StoredDayNets.decode(text, stamp), isNotNull);
    // Googleの更新で本体が新しくなった（書き出しの時刻が替わった）・記録の件数が違う。
    expect(
      StoredDayNets.decode(
        text,
        'body-1|2026-11-26T00:00:00+09:00|${data.records.length}',
      ),
      isNull,
    );
    expect(
      StoredDayNets.decode(text, 'body-1|$exported|${data.records.length + 1}'),
      isNull,
    );
    // 2026-11-26 点検④：書き出しの時刻と件数が同じでも、端末に保存し直した別の本体（目印が違う）には使わない。
    // 目印の無い本体（目印を書く前の古い本体）・以前の形（時刻|件数）の控えも使わない。
    expect(StoredDayNets.decode(text, dayNetStamp(data, 'body-2')), isNull);
    expect(dayNetStamp(data, null), isNull);
    expect(dayNetStamp(data, ''), isNull);
    expect(
      StoredDayNets.decode(
        encodeDayNetTable(table, '$exported|${data.records.length}'),
        stamp,
      ),
      isNull,
    );
    // 書き出しの時刻の無い本体は目印を作らない（表を使わない）。
    expect(dayNetStamp(parse(byDay, at: null), 'body-1'), isNull);
    expect(StoredDayNets.decode(text, null), isNull);
    // 消した控え（照合が一致しなかった）・壊れた控え・形の違う控え。
    expect(StoredDayNets.decode('', stamp), isNull);
    expect(StoredDayNets.decode(null, stamp), isNull);
    expect(StoredDayNets.decode('{"version":1', stamp), isNull);
    expect(
      StoredDayNets.decode(
        jsonEncode({'version': 2, 'stamp': stamp, 'cells': {}}),
        stamp,
      ),
      isNull,
    );
    expect(
      StoredDayNets.decode(
        jsonEncode({
          'version': 1,
          'stamp': stamp,
          'cells': {
            'saiwaichou|2026-01-02': [1, 2],
          },
        }),
        stamp,
      ),
      isNull,
    );
  });
}
