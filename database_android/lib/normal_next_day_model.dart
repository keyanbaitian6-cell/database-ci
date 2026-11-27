import 'dart:math' as math;

import 'models.dart';
import 'scoring.dart' show percentile;
import 'setting_estimate.dart'
    show foldHalfWidthKana, settingModelForMachine, settingTable;

/// 幸町のジャグラー・ハナハナの翌日候補の並べ方（2026-10-17、
/// NEXT_DAY_MODEL_PLAN_20261017.md）。14か月分から作ったリッジ回帰の式で、翌日の
/// 当たりの軽さ（同じ機種で回転数が近い台の中の順位）を予想し、その点の高い順に並べる。
/// 候補に入りうる台と台数は今の選び方と同じで、変えるのは並べる順だけ。
/// PC版 `database/normal_next_day_model.py` と同じ材料・同じ重み。
const normalModelMethodVersion = '2026-10-18-saiwaichou-normal-model-2';
const _shrinkGames = 2000;

/// 式を使うのは、選ぶ日がこの日以降の候補だけ（PC `AVAILABLE_FROM` と同じ）。
const normalModelAvailableFrom = '2026-10-17';

/// 台の長期の癖は直近60日（PC `LONG_DAYS` と同じ）。
const _longDays = 60;

/// 生の重み（標準化を戻した値）。翌日が 2026-10-16 までのデータ 53,454 件で作った。
const normalModelWeights = <String, double>{
  'v0': 0.023660703,
  's': 0.041100879,
  'r': -0.061499909,
  's_last3': 0.011417444,
  's_28': 0.024624829,
  's_long': 0.331663748,
  'r_28': 0.023369600,
  'high_d': -0.431953077,
  'high_12': -0.238242452,
  'since_4_9': -0.252953453,
  'since_10_23': -0.370217296,
  'log_games': -0.164622000,
  'long_play': 0.801754507,
};

/// 候補のカードに出す説明（PC `NOTE` と同じ文）。
const normalModelNote =
    '幸町のジャグラー・ハナハナは、2026年10月17日以降、過去の記録から作った予想の式（台の直近60日の当たりの軽さ、当日の当たりとREG、回転数、直近に明らかに高かったかなど）の点の高い順に選んでいます。表示の数字は過去の当たりの軽さで、並び順とは違うことがあります。過去に当てはめた確認では、選んだ台の翌日の当たりの軽さ（同じ機種の中の順位）は、今までの選び方より平均で約0.7高い程度でした（2026年9〜10月だけでは差が見えていません）。翌日の設定や勝ち負けを示すものではありません。';

/// 幸町のジャグラー・ハナハナで、選ぶ日が [normalModelAvailableFrom] 以降
/// （[day] を省くと日付は見ない）。PC `applies` と同じ。
bool normalModelApplies(String store, String machine, [String? day]) =>
    store == 'saiwaichou' &&
    (machine.contains('ジャグラー') || machine.contains('ハナハナ')) &&
    (day == null || day.compareTo(normalModelAvailableFrom) >= 0);

String? _spec(String machine) {
  final key = settingModelForMachine(machine);
  if (key != null) return key;
  // アイムジャグラーEX はネオアイムジャグラーEX と同じ公表確率（北電子の公式表）。
  final name = foldHalfWidthKana(
    machine.toUpperCase().replaceAll(RegExp(r'[\s\-−‐‑–—~〜～_・]+'), ''),
  );
  return name == 'アイムジャグラーEXTP' || name == 'SアイムジャグラーEXTP'
      ? 'neo_im_juggler'
      : null;
}

/// 3,000回転以上で、BIG・REGから見た設定4以上の確率（等事前）が90%以上。
bool normalClearlyHigh(SlotRecord r) {
  final key = _spec(r.machine);
  if (key == null ||
      r.games < 3000 ||
      r.games > 20000 ||
      r.bb < 0 ||
      r.rb < 0 ||
      r.bb + r.rb > r.games) {
    return false;
  }
  final table = settingTable(key)!;
  final logs = [
    for (final (bb, rb) in table)
      r.bb * math.log(1 / bb) +
          r.rb * math.log(1 / rb) +
          (r.games - r.bb - r.rb) * math.log(1 - 1 / bb - 1 / rb),
  ];
  final peak = logs.reduce(math.max);
  final weights = [for (final x in logs) math.exp(x - peak)];
  final total = weights.reduce((a, b) => a + b);
  return weights.skip(3).fold(0.0, (a, b) => a + b) / total >= .9;
}

double? _rank(
  SlotRecord row,
  List<SlotRecord> dayRows,
  num Function(SlotRecord) value,
) {
  if (row.games < 500 ||
      row.bb < 0 ||
      row.rb < 0 ||
      hasImplausibleNumbers(row)) {
    return null;
  }
  final peers = [
    for (final r in dayRows)
      if (r.games >= 500 &&
          r.bb >= 0 &&
          r.rb >= 0 &&
          !hasImplausibleNumbers(r) &&
          r.games >= row.games / 2 &&
          r.games <= row.games * 2)
        r,
  ];
  if (peers.length < 3) return null;
  return 100 *
      percentile(value(row) / row.games, [
        for (final r in peers) value(r) / r.games,
      ]);
}

double? _hit(SlotRecord row, List<SlotRecord> dayRows) =>
    _rank(row, dayRows, (r) => r.bb + r.rb);

double? _reg(SlotRecord row, List<SlotRecord> dayRows) =>
    _rank(row, dayRows, (r) => r.rb);

int _dayNumber(String day) =>
    DateTime.utc(
      int.parse(day.substring(0, 4)),
      int.parse(day.substring(5, 7)),
      int.parse(day.substring(8, 10)),
    ).millisecondsSinceEpoch ~/
    86400000;

typedef NormalHistoryValue = ({String day, double? s, double? r, bool high});

final _dayCache = <String, Map<int, ({double? s, double? r, bool high})>>{};

/// 1日・1機種の台ごとの（当たりの軽さの寄与、REGの寄与、明らかに高い）。その日の台の数字だけで
/// 決まるので、数字が同じなら覚えた値を使う（PC `_day_values` と同じ）。
Map<int, ({double? s, double? r, bool high})> _dayValues(
  List<SlotRecord> rows,
) {
  final sorted = [...rows]..sort((a, b) => a.rack.compareTo(b.rack));
  final key =
      '${rows.first.machine}|${rows.first.day}|'
      '${sorted.map((r) => '${r.rack}:${r.games}:${r.bb}:${r.rb}:${r.outputValue}').join(',')}';
  final cached = _dayCache[key];
  if (cached != null) return cached;
  final values = <int, ({double? s, double? r, bool high})>{};
  for (final r in rows) {
    final shrink = r.games / (r.games + _shrinkGames);
    final h = _hit(r, rows);
    final g = _reg(r, rows);
    values[r.rack] = (
      s: h == null ? null : (h - 50) * shrink,
      r: g == null ? null : (g - 50) * shrink,
      high: normalClearlyHigh(r),
    );
  }
  if (_dayCache.length > 20000) _dayCache.clear();
  _dayCache[key] = values;
  return values;
}

/// 同じ店・同じ機種の [day] までの記録について、台ごとに（日、当たりの軽さの寄与、
/// REGの寄与、明らかに高い）を新しい日から並べる。
Map<int, List<NormalHistoryValue>> normalHistoryValues(
  List<SlotRecord> machineRows,
  String day,
) {
  final byDay = <String, List<SlotRecord>>{};
  for (final r in machineRows) {
    if (r.day.compareTo(day) <= 0) byDay.putIfAbsent(r.day, () => []).add(r);
  }
  final perRack = <int, List<NormalHistoryValue>>{};
  byDay.forEach((d, rows) {
    _dayValues(rows).forEach((rack, v) {
      perRack.putIfAbsent(rack, () => []).add((
        day: d,
        s: v.s,
        r: v.r,
        high: v.high,
      ));
    });
  });
  for (final values in perRack.values) {
    values.sort((a, b) => b.day.compareTo(a.day));
  }
  return perRack;
}

/// [perRack] は [normalHistoryValues] の結果（[row] の日まで）。PC `features` と同じ材料。
Map<String, double> normalModelFeatures(
  Map<int, List<NormalHistoryValue>> perRack,
  SlotRecord row,
  double v0Raw,
) {
  final t = _dayNumber(row.day);
  final sAll = <double>[], recent3 = <double>[], s28 = <double>[];
  final r28 = <double>[];
  var high12 = false, seen7 = false;
  int? lastHigh;
  double? todayS, todayR;
  for (final v in perRack[row.rack] ?? const <NormalHistoryValue>[]) {
    final ago = t - _dayNumber(v.day);
    if (ago == 0) {
      todayS = v.s;
      todayR = v.r;
    }
    if (v.s != null) {
      if (ago < _longDays) sAll.add(v.s!);
      if (ago < 7 && recent3.length < 3) recent3.add(v.s!);
      if (ago < 28) s28.add(v.s!);
    }
    if (v.r != null && ago < 28) r28.add(v.r!);
    if (v.high && ago >= 1 && ago <= 2) high12 = true;
    if (v.high && lastHigh == null) lastHigh = ago;
    if (ago >= 1 && ago <= 7) seen7 = true;
  }
  double mean(List<double> v) =>
      v.isEmpty ? 0.0 : v.reduce((a, b) => a + b) / v.length;
  return {
    'v0': v0Raw - 50,
    's': todayS ?? 0.0,
    'r': todayR ?? 0.0,
    's_last3': mean(recent3),
    's_28': mean(s28),
    's_long': sAll.fold(0.0, (a, b) => a + b) / (sAll.length + 10),
    'r_28': mean(r28),
    'high_d': normalClearlyHigh(row) ? 1 : 0,
    'high_12': high12 ? 1 : 0,
    'since_4_9': lastHigh != null && lastHigh >= 4 && lastHigh <= 9 ? 1 : 0,
    'since_10_23': lastHigh != null && lastHigh >= 10 && lastHigh <= 23 ? 1 : 0,
    'new_rack': seen7 ? 0 : 1,
    'log_games': math.log(math.max(row.games, 1) / 4000),
    'long_play': row.games >= 7000 ? 1 : 0,
  };
}

double normalModelScore(Map<String, double> features) {
  var total = 0.0;
  normalModelWeights.forEach((k, w) => total += w * features[k]!);
  return total;
}
