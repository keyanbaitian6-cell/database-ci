import 'daily_net_page.dart' show DayNet, dailyNet;
import 'models.dart';
import 'viewer_data.dart';

/// 段階B1（VIEWER_DAY_STORE.md、2026-11-18）：カレンダーの店・日ごとの差枚を、日別キャッシュから
/// 1日ずつ作る表。1日分の記録を [addDay] に渡すたびに、その日の [DayNet] だけを控え、記録は持たない
/// （全日の記録を同時には持たない）。計算は今のカレンダーと同じ [dailyNet] で、記録の読み方は
/// [ViewerData.parse] と同じ [ViewerData.recordsOfRows]。
class DayNetTable {
  /// `店|日付` → その日の差枚。
  final Map<String, DayNet> cells = {};

  void addDay(Iterable<Object?> rows) {
    final records = ViewerData.recordsOfRows(rows);
    for (final store in {for (final r in records) r.store}) {
      for (final d in dailyNet(records, store)) {
        cells['$store|${d.day}'] = d;
      }
    }
  }
}

bool _same(DayNet a, DayNet b) =>
    a.total == b.total &&
    a.captured == b.captured &&
    a.racks == b.racks &&
    a.needsCheck == b.needsCheck &&
    a.judged == b.judged &&
    a.won == b.won;

String _text(DayNet? d) => d == null
    ? 'マス無し'
    : '差枚${d.total ?? 'なし'}・分かる${d.captured}/${d.racks}台・要確認${d.needsCheck}・勝ち${d.won}/${d.judged}';

/// 日別キャッシュから作った [table] と、今のカレンダーの計算（全記録 [records] から [dailyNet]）を、
/// 全店・全日で比べる。診断（`web/storage_report.mjs` の `recordCalendar`）に控える形で返す：
/// `status`（`match`・`mismatch`）、`cells`（比べたマスの数）、`mismatched`（一致しないマスの数）、
/// `examples`（最大3件。`store`・`day`・`old`（今の計算）・`next`（日別））。
Map<String, Object?> compareDayNets(
  DayNetTable table,
  Iterable<SlotRecord> records,
) {
  final current = <String, DayNet>{};
  for (final store in {for (final r in records) r.store}) {
    for (final d in dailyNet(records, store)) {
      current['$store|${d.day}'] = d;
    }
  }
  final keys = {...current.keys, ...table.cells.keys}.toList()..sort();
  final examples = <Map<String, String>>[];
  var mismatched = 0;
  for (final key in keys) {
    final a = current[key], b = table.cells[key];
    if (a != null && b != null && _same(a, b)) continue;
    mismatched++;
    if (examples.length < 3) {
      final at = key.indexOf('|');
      examples.add({
        'store': key.substring(0, at),
        'day': key.substring(at + 1),
        'old': _text(a),
        'next': _text(b),
      });
    }
  }
  return {
    'status': mismatched == 0 ? 'match' : 'mismatch',
    'cells': keys.length,
    'mismatched': mismatched,
    'examples': examples,
  };
}
