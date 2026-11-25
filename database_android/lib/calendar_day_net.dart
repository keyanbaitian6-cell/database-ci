import 'dart:convert';

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

/// 段階B1の切り替え（2026-11-25 利用者「切り替えとB3進めて」「それで進めて」）：日別キャッシュから作った差枚表は、
/// 今の計算と全マス一致したときだけ端末（localStorage）に控え、カレンダー（イベントカレンダーの各日の差枚・
/// 日別差枚の月表）はその表から出す。表が無い・本体と食い違う（[dayNetStamp] が違う）・読めないときは、今の計算
/// （全記録から [dailyNet]）に戻る。表示する値は変えない（一致したときだけ使うので同じ値）。
const dayNetTableKey = 'database-viewer-day-net';

/// 本体の版の目印。書き出しの時刻と記録の件数。書き出しの時刻が無い本体は null（表を使わない）。
/// 本体の記録が変わるのはGoogleの更新・ファイルの読み込みのときで、そのたびに書き出しの時刻が替わる。
String? dayNetStamp(ViewerData data) {
  final at = data.exportedAtText;
  if (at == null || at.isEmpty) return null;
  return '$at|${data.records.length}';
}

/// [table] を、本体の目印 [stamp] と一緒に控える形（小さなJSON）にする。1マスは
/// `[合計, 分かる台, 台数, 要確認, 勝ち負けの分かる台, 勝ち]`（合計の無い日は null）。
String encodeDayNetTable(DayNetTable table, String stamp) => jsonEncode({
  'version': 1,
  'stamp': stamp,
  'cells': {
    for (final e in table.cells.entries)
      e.key: [
        e.value.total,
        e.value.captured,
        e.value.racks,
        e.value.needsCheck,
        e.value.judged,
        e.value.won,
      ],
  },
});

/// 控えた差枚表。店ごとに、日の新しい順の一覧（[dailyNet] と同じ並び）を持つ。
class StoredDayNets {
  StoredDayNets._(this._byStore);
  final Map<String, List<DayNet>> _byStore;
  late final Map<String, DayNet> _byKey = {
    for (final e in _byStore.entries)
      for (final d in e.value) '${e.key}|${d.day}': d,
  };

  /// [store] の [day] の差枚（[dailyNetLookup] と同じ。マスが無ければ null）。
  DayNet? lookup(String store, String day) => _byKey['$store|$day'];

  /// [store] の日ごとの差枚（新しい日が先。[dailyNet] と同じ）。
  List<DayNet> days(String store) => _byStore[store] ?? const [];

  int get cellCount => _byKey.length;

  /// 控えた [text] を、本体の目印 [stamp] と同じときだけ読む。違う・壊れている・空なら null。
  static StoredDayNets? decode(String? text, String? stamp) {
    if (text == null || text.isEmpty || stamp == null) return null;
    try {
      final doc = jsonDecode(text) as Map<String, dynamic>;
      if (doc['version'] != 1 || doc['stamp'] != stamp) return null;
      final byStore = <String, List<DayNet>>{};
      for (final e in (doc['cells'] as Map<String, dynamic>).entries) {
        final at = e.key.indexOf('|');
        final v = e.value as List<dynamic>;
        if (at <= 0 || v.length != 6) return null;
        (byStore[e.key.substring(0, at)] ??= []).add(
          DayNet(
            day: e.key.substring(at + 1),
            total: v[0] as int?,
            captured: v[1] as int,
            racks: v[2] as int,
            needsCheck: v[3] as int,
            judged: v[4] as int,
            won: v[5] as int,
          ),
        );
      }
      for (final list in byStore.values) {
        list.sort((a, b) => b.day.compareTo(a.day));
      }
      return StoredDayNets._(byStore);
    } on Object {
      return null;
    }
  }
}
