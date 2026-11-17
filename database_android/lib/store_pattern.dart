import 'dart:math' as math;

import 'models.dart';
import 'pscube_suffix.dart' show suffixesFor;
import 'scoring.dart' show minScoredGames;

/// 店の入れ方のふり返り（2026-11-17 利用者「２だけ作る。iPhoneブラウザ版の2種類のみで」。
/// 提案は共有記録 2026-11-17「勝ちにこだわる目線で、あったらいい機能を5つ」の2）。
///
/// その日の、プラスで終わった台（[SlotRecord.won]、勝率と同じ数え方）が、
/// 機種（全台系）・末尾・台番の並びに、ランダムに配ったときと比べてどれだけ偏っていたかを出す。
/// 角台は、島の配置のデータが無く台番だけでは分からないので出さない。
///
/// 探索の結果であり、翌日候補・採点には使わない。保存済みのデータだけを読む（サイトへはアクセスしない）。
/// 研究（日次学習の outcomes・decisions、前向きの研究の規則の成績）は計算しない。
///
/// 偶然の程度：機種・末尾は超幾何分布の上側確率（その日の店全体のプラス台の数を固定して、
/// その機種の台数をランダムに選んだとき、これ以上プラスが多くなる確率）に、比べた数を掛けて割り引く
/// （ボンフェローニ。何通りも比べた中の一番は偶然でも出やすいため）。
/// 並びは、プラスの印を台に配り直す並べ替えを [runTrials] 回行い、いちばん長い並びがこれ以上になる割合。

/// 比べる組（機種・末尾）に要る台数。2台以下では偏りを言えない。
const patternMinGroup = 3;

/// その日を判定するのに要る台数。
const patternMinRacks = 10;

/// 並びの並べ替えの回数。
const runTrials = 1000;

enum PatternChance {
  rare('偶然では出にくい'),
  sometimes('偶然でもときどき出る'),
  common('偶然でもよく出る');

  const PatternChance(this.label);
  final String label;
}

/// 割り引いたあとの確率から、偶然の程度の呼び方。
PatternChance chanceOf(double adjusted) => adjusted < .05
    ? PatternChance.rare
    : adjusted < .2
    ? PatternChance.sometimes
    : PatternChance.common;

/// 判定に使える台か：500G以下（採点の下限と同じ）と、プラスかどうか分からない台は除く。
bool patternUsable(SlotRecord r) => r.games > minScoredGames && r.won != null;

/// 機種または末尾の1組。
class PatternGroup {
  const PatternGroup({
    required this.label,
    required this.plus,
    required this.total,
    required this.p,
    required this.compared,
  });
  final String label;
  final int plus, total;

  /// 割り引く前の確率（これ以上プラスが多くなる確率）。
  final double p;

  /// 比べた組の数（割り引きに使う）。
  final int compared;
  double get adjusted => math.min(1.0, p * compared);
  PatternChance get chance => chanceOf(adjusted);
  double get rate => total == 0 ? 0 : plus / total;
}

/// 台番の並び（台番が1つずつ続き、どれもプラスだった台）。
class PatternRun {
  const PatternRun({required this.racks, required this.p});
  final List<int> racks;

  /// 並べ替えで、いちばん長い並びがこれ以上になった割合。
  final double p;
  int get length => racks.length;
  PatternChance get chance => chanceOf(p);
  String get label =>
      length == 1 ? '${racks.first}番' : '${racks.first}〜${racks.last}番';
}

class StorePatternDay {
  const StorePatternDay({
    required this.store,
    required this.day,
    required this.plus,
    required this.total,
    required this.excluded,
    required this.machines,
    required this.suffixes,
    required this.run,
  });
  final String store, day;

  /// 判定に使った台（プラスの台・全体）と、除いた台。
  final int plus, total, excluded;

  /// 機種ごと（[patternMinGroup]台以上）。割り引いたあとの確率の小さい順。
  final List<PatternGroup> machines;

  /// 末尾ごと（[patternMinGroup]台以上）。末尾の順。
  final List<PatternGroup> suffixes;

  /// いちばん長い並び。プラスの台が無い・判定できない日は null。
  final PatternRun? run;

  /// 判定できる日か（台が少ない・全部プラス・全部マイナスの日は偏りを言えない）。
  bool get usable => total >= patternMinRacks && plus > 0 && plus < total;
  double get rate => total == 0 ? 0 : plus / total;

  /// 偶然では出にくい偏り（履歴の一覧に出す）。
  List<String> get highlights => !usable
      ? const []
      : [
          for (final g in machines)
            if (g.chance == PatternChance.rare && g.rate > rate)
              '全台系：${g.label}（${g.plus}/${g.total}）',
          for (final g in suffixes)
            if (g.chance == PatternChance.rare && g.rate > rate)
              '${g.label}（${g.plus}/${g.total}）',
          if (run != null && run!.chance == PatternChance.rare)
            '並び：${run!.label}（${run!.length}台）',
        ];
}

/// その店・その日の入れ方のふり返り。[records] はほかの店・日を含んでよい。
StorePatternDay storePatternDay(
  String store,
  String day,
  Iterable<SlotRecord> records, {
  int trials = runTrials,
}) {
  final rows = [
    for (final r in records)
      if (r.store == store && r.day == day) r,
  ];
  // 同じ台が2回あれば後の記録を使う（台は1日1台）。
  final byRack = <int, SlotRecord>{};
  for (final r in rows) {
    byRack[r.rack] = r;
  }
  final usable = [
    for (final r in byRack.values)
      if (patternUsable(r)) r,
  ]..sort((a, b) => a.rack.compareTo(b.rack));
  final total = usable.length;
  final plus = usable.where((r) => r.won!).length;
  final table = _LogFactorials(total);

  List<PatternGroup> groups(Map<String, List<SlotRecord>> grouped) {
    final kept = grouped.entries
        .where((e) => e.value.length >= patternMinGroup)
        .toList();
    return [
      for (final e in kept)
        PatternGroup(
          label: e.key,
          plus: e.value.where((r) => r.won!).length,
          total: e.value.length,
          p: table.upperTail(
            total,
            plus,
            e.value.length,
            e.value.where((r) => r.won!).length,
          ),
          compared: kept.length,
        ),
    ];
  }

  final byMachine = <String, List<SlotRecord>>{};
  for (final r in usable) {
    byMachine.putIfAbsent(r.machine, () => []).add(r);
  }
  final machines = groups(byMachine)
    ..sort((a, b) {
      final c = a.adjusted.compareTo(b.adjusted);
      return c != 0 ? c : b.rate.compareTo(a.rate);
    });
  final bySuffix = <String, List<SlotRecord>>{};
  final order = suffixesFor(store);
  for (final s in order) {
    final list = [
      for (final r in usable)
        if (r.rack % 10 == s) r,
    ];
    if (list.isNotEmpty) bySuffix['末尾$s'] = list;
  }
  final suffixes = groups(bySuffix);

  final labels = [for (final r in usable) r.won!];
  final racks = [for (final r in usable) r.rack];
  PatternRun? run;
  if (plus > 0) {
    final best = _longestRun(racks, labels);
    var count = 0;
    if (plus < total) {
      final random = math.Random(_seed('$store|$day'));
      final shuffled = [...labels];
      for (var t = 0; t < trials; t++) {
        for (var i = shuffled.length - 1; i > 0; i--) {
          final j = random.nextInt(i + 1);
          final tmp = shuffled[i];
          shuffled[i] = shuffled[j];
          shuffled[j] = tmp;
        }
        if (_longestRunLength(racks, shuffled) >= best.length) count++;
      }
    }
    run = PatternRun(
      racks: best,
      p: plus < total ? (count + 1) / (trials + 1) : 1,
    );
  }
  return StorePatternDay(
    store: store,
    day: day,
    plus: plus,
    total: total,
    excluded: byRack.length - total,
    machines: machines,
    suffixes: suffixes,
    run: run,
  );
}

/// いちばん長い並び（台番が1つずつ続き、どれもプラス）。同じ長さなら台番の若い方。
List<int> _longestRun(List<int> racks, List<bool> plus) {
  var best = <int>[];
  var current = <int>[];
  for (var i = 0; i < racks.length; i++) {
    if (!plus[i]) {
      current = [];
      continue;
    }
    if (current.isNotEmpty && racks[i] != current.last + 1) current = [];
    current = [...current, racks[i]];
    if (current.length > best.length) best = current;
  }
  return best;
}

int _longestRunLength(List<int> racks, List<bool> plus) {
  var best = 0, current = 0;
  for (var i = 0; i < racks.length; i++) {
    if (!plus[i]) {
      current = 0;
      continue;
    }
    current = current > 0 && racks[i] == racks[i - 1] + 1 ? current + 1 : 1;
    if (current > best) best = current;
  }
  return best;
}

/// 端末（Dart VM・ブラウザ）によらず同じ値になる種（FNV-1a）。同じ日なら毎回同じ結果にするため。
int _seed(String text) {
  var hash = 0x811c9dc5;
  for (final unit in text.codeUnits) {
    hash ^= unit;
    hash = (hash * 0x01000193) & 0xffffffff;
  }
  return hash & 0x7fffffff;
}

class _LogFactorials {
  _LogFactorials(int n) : _values = List<double>.filled(n + 1, 0) {
    for (var i = 2; i <= n; i++) {
      _values[i] = _values[i - 1] + math.log(i);
    }
  }
  final List<double> _values;
  double _choose(int n, int k) => _values[n] - _values[k] - _values[n - k];

  /// 全体 [population] 台のうちプラス [successes] 台から [draws] 台を選んで、
  /// プラスが [observed] 台以上になる確率。
  double upperTail(int population, int successes, int draws, int observed) {
    final high = math.min(draws, successes);
    final low = math.max(observed, draws - (population - successes));
    if (low > high) return 0;
    final all = _choose(population, draws);
    var sum = 0.0;
    for (var x = low; x <= high; x++) {
      sum += math.exp(
        _choose(successes, x) +
            _choose(population - successes, draws - x) -
            all,
      );
    }
    return math.min(1.0, sum);
  }
}
