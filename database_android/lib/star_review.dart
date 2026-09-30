import 'dart:math';

import 'data_checks.dart';
import 'models.dart';
import 'next_day_backtest.dart';
import 'scoring.dart';

/// 分析専用（画面からは呼ばない）。通常★（参考候補）の独立した再検討。
/// 事前に固定した条件は `NEXT_DAY_STAR_INDEPENDENT_REVIEW_20260930.md` の「1.」。
/// ★と指数はアプリの [provisionalNextDayCandidates]・[nextDayIndex] と同じ値で
/// あることを、[indexBreakdown] と [starSelection] で毎回確かめてから使う。

/// 指数の1日ぶんの中身。
class IndexDay {
  IndexDay(this.day, this.games, this.peers, this.rank, this.gap);
  final String day;
  final int games;

  /// 比べた台の数（その台自身を含む）。3台未満の日は寄与なし。
  final int peers;

  /// 同じ日・同じ機種で回転数が近い台の中の当たり順位（0〜1）。
  final double? rank;

  /// 指数への寄与（`(100×順位−50)×G/(G+1500)`）。寄与なしの日は null。
  final double? gap;
  bool get used => gap != null;
}

/// [nextDayIndex] の中身（同じ式）。
class IndexBreakdown {
  IndexBreakdown(this.day, this.days, this.unrounded, this.rounded);

  /// 予測日。
  final String day;

  /// 見た記録日（新しい順、最大10日。比べる台が3台未満で寄与の無い日も含む）。
  final List<IndexDay> days;
  final double? unrounded;
  final double? rounded;
  int get n => days.where((d) => d.used).length;
  double get gapSum => days.fold(0.0, (s, d) => s + (d.gap ?? 0));
  IndexDay? get latestUsed => days.where((d) => d.used).firstOrNull;

  /// 予測日の記録が指数に入ったか（500G未満・未取得・数値異常・比べる台が
  /// 3台未満なら入らない）。
  bool get todayUsed => latestUsed?.day == day;
}

IndexBreakdown indexBreakdown(
  SlotRecord record,
  List<SlotRecord> all, {
  int maxDays = 10,
  int shrink = 5,
}) {
  final first = DateTime.parse(record.day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final byDay = <String, List<SlotRecord>>{};
  for (final r in machineHistory(all, record.store, record.machine)) {
    if (r.day.compareTo(first) >= 0 &&
        r.day.compareTo(record.day) <= 0 &&
        r.games >= 500 &&
        r.bb >= 0 &&
        r.rb >= 0 &&
        !hasImplausibleNumbers(r)) {
      byDay.putIfAbsent(r.day, () => []).add(r);
    }
  }
  final days = [
    for (final entry in byDay.entries)
      if (entry.value.any((r) => r.rack == record.rack)) entry.key,
  ]..sort((a, b) => b.compareTo(a));
  final result = <IndexDay>[];
  for (final day in days.take(maxDays)) {
    final dayRows = byDay[day]!;
    final mine = dayRows.firstWhere((r) => r.rack == record.rack);
    final peers = dayRows
        .where((r) => r.games >= mine.games / 2 && r.games <= mine.games * 2)
        .toList();
    if (peers.length < 3) {
      result.add(IndexDay(day, mine.games, peers.length, null, null));
      continue;
    }
    final rank = percentile(
      (mine.bb + mine.rb) / mine.games,
      peers.map((r) => (r.bb + r.rb) / r.games).toList(),
    );
    result.add(
      IndexDay(
        day,
        mine.games,
        peers.length,
        rank,
        (100 * rank - 50) * mine.games / (mine.games + shrinkGames),
      ),
    );
  }
  final gaps = [
    for (final d in result)
      if (d.gap != null) d.gap!,
  ];
  if (gaps.length < 3) return IndexBreakdown(record.day, result, null, null);
  final raw = 50 + gaps.reduce((a, b) => a + b) / (gaps.length + shrink);
  return IndexBreakdown(
    record.day,
    result,
    raw,
    double.parse(raw.toStringAsFixed(1)),
  );
}

/// 翌日の寄与を c とした翌日の指数（他の台は据え置き、10記録日を超えたら最も
/// 古い日が抜ける）。
double nextIndexWith(IndexBreakdown b, double c) {
  var kept = b.gapSum, n = b.n;
  if (b.days.length >= 10) {
    final dropped = b.days.last;
    if (dropped.used) {
      kept -= dropped.gap!;
      n -= 1;
    }
  }
  return 50 + (kept + c) / (n + 1 + 5);
}

/// アプリと同じ選び方：[index] の大きい順、同じなら台番号の小さい順に、
/// 判定できた台が4台以上なら上位 ceil(0.25×台数)。アプリは丸めた指数で並べる
/// （丸める前の指数を渡すと比較用の並びになる）。
List<T> starSelection<T>(
  List<T> eligible,
  double Function(T) index,
  int Function(T) rack,
) {
  final sorted = [...eligible]
    ..sort((a, b) {
      final byIndex = index(b).compareTo(index(a));
      return byIndex != 0 ? byIndex : rack(a).compareTo(rack(b));
    });
  if (sorted.length < 4) return const [];
  return sorted.take((sorted.length * .25).ceil()).toList();
}

class StarMember {
  StarMember(this.record, this.breakdown);
  final SlotRecord record;
  final IndexBreakdown breakdown;
  double get index => breakdown.rounded!;
  double get unrounded => breakdown.unrounded!;

  /// アプリの並び（丸めた指数の大きい順・台番号）での順位（1から）。
  int position = 0;
  bool star = false;
  bool starUnrounded = false;
  bool? starYesterday;
}

class StarGroup {
  StarGroup(this.store, this.machine, this.day, this.members, this.k);
  final String store, machine, day;

  /// アプリの並びの順。
  final List<StarMember> members;
  final int k;
  StarMember get lastStar => members[k - 1];
  StarMember? get firstOut => members.length > k ? members[k] : null;

  /// k位と(k+1)位の丸めた指数が同じで、台番号の小さい順で★が決まった。
  bool get tieAtBoundary =>
      firstOut != null && firstOut!.index == lastStar.index;
  String get key => '$store|$machine|$day';
}

/// 予測日ごとの通常機種（4台以上）のグループ。[cutoffFor] が null なら
/// アプリの見え方（日付D以前の全記録）、あれば予測時点の見え方。[check] なら
/// アプリの関数と台・指数が一致することを確かめる（一致しなければ例外）。
List<StarGroup> buildStarGroups(
  List<SlotRecord> full, {
  DateTime? Function(String day)? cutoffFor,
  bool check = true,
}) {
  final result = <StarGroup>[];
  final days = {for (final r in full) r.day}.toList()..sort();
  for (final day in days) {
    final source = cutoffFor == null
        ? full
        : availableRecords(full, day, cutoff: cutoffFor(day));
    final byStore = <String, List<SlotRecord>>{};
    for (final r in source) {
      if (r.day == day) byStore.putIfAbsent(r.store, () => []).add(r);
    }
    for (final store in byStore.keys.toList()..sort()) {
      final dayRows = byStore[store]!;
      final variety = varietyMachines(dayRows);
      final byMachine = <String, List<SlotRecord>>{};
      for (final r in dayRows) {
        if (!variety.contains(r.machine)) {
          byMachine.putIfAbsent(r.machine, () => []).add(r);
        }
      }
      for (final machine in byMachine.keys.toList()..sort()) {
        final rows = byMachine[machine]!;
        final history = machineHistory(source, store, machine);
        final members = <StarMember>[];
        for (final row in rows) {
          final b = indexBreakdown(row, history);
          if (check) {
            final app = nextDayIndex(row, history);
            if (app.index != b.rounded ||
                (app.index != null && app.days != b.n)) {
              throw StateError('$store $day $machine ${row.rack}: 指数が一致しない');
            }
          }
          if (b.rounded != null) members.add(StarMember(row, b));
        }
        final stars = starSelection(
          members,
          (m) => m.index,
          (m) => m.record.rack,
        );
        if (check) {
          final app = provisionalNextDayCandidates(rows, history);
          final appRacks = {for (final c in app.candidates) c.record.rack};
          final mine = {for (final m in stars) m.record.rack};
          if (app.eligible != members.length ||
              appRacks.length != mine.length ||
              !appRacks.containsAll(mine)) {
            throw StateError('$store $day $machine: ★が一致しない');
          }
        }
        if (stars.isEmpty) continue;
        members.sort((a, b) {
          final byIndex = b.index.compareTo(a.index);
          return byIndex != 0
              ? byIndex
              : a.record.rack.compareTo(b.record.rack);
        });
        for (final (i, m) in members.indexed) {
          m.position = i + 1;
          m.star = i < stars.length;
        }
        for (final m in starSelection(
          members,
          (m) => m.unrounded,
          (m) => m.record.rack,
        )) {
          m.starUnrounded = true;
        }
        result.add(StarGroup(store, machine, day, members, stars.length));
      }
    }
  }
  final byKey = {for (final g in result) g.key: g};
  for (final g in result) {
    final before = byKey['${g.store}|${g.machine}|${shiftDay(g.day, -1)}'];
    if (before == null) continue;
    final starred = {
      for (final m in before.members)
        if (m.star) m.record.rack,
    };
    for (final m in g.members) {
      m.starYesterday = starred.contains(m.record.rack);
    }
  }
  return result;
}

/// 当日★のうち前日も★だった割合（前日にも同じ店舗・機種のグループがある
/// 組だけ、当日★を分母）。[store] を指定するとその店舗だけ。
({int pairs, int stars, int repeated, double? rate}) repeatRate(
  List<StarGroup> groups, {
  String? store,
}) {
  var pairs = 0, stars = 0, repeated = 0;
  for (final g in groups) {
    if (store != null && g.store != store) continue;
    if (g.members.every((m) => m.starYesterday == null)) continue;
    pairs++;
    for (final m in g.members.where((m) => m.star)) {
      stars++;
      if (m.starYesterday == true) repeated++;
    }
  }
  return (
    pairs: pairs,
    stars: stars,
    repeated: repeated,
    rate: stars == 0 ? null : repeated / stars,
  );
}

/// 店舗・機種・日ごとに、その日の記録の台番号だけを無作為に入れ替えたデータ
/// （回転数・当たりなどの数値はそのまま）。台ごとの本当の持続性は消えるが、
/// 履歴の重なりによる持続は残る。
List<SlotRecord> permuteRackLabels(List<SlotRecord> full, Random rng) {
  final groups = <String, List<SlotRecord>>{};
  for (final r in full) {
    groups.putIfAbsent('${r.store}|${r.machine}|${r.day}', () => []).add(r);
  }
  final result = <SlotRecord>[];
  for (final rows in groups.values) {
    final racks = [for (final r in rows) r.rack]..shuffle(rng);
    for (final (i, r) in rows.indexed) {
      result.add(r.copyWith(rack: racks[i]));
    }
  }
  return result;
}

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

double? _sd(List<double> values) {
  if (values.length < 2) return null;
  final m = _mean(values)!;
  return sqrt(
    values.fold(0.0, (s, v) => s + (v - m) * (v - m)) / (values.length - 1),
  );
}

/// グループ内の指数の標準偏差の平均（判定台数4台以上のグループ）。
double? meanWithinGroupSd(List<StarGroup> groups) => _mean([
  for (final g in groups) ?_sd([for (final m in g.members) m.index]),
]);

/// 順位（同順位は平均順位）。
List<double> _ranks(List<double> values) {
  final order = List.generate(values.length, (i) => i)
    ..sort((a, b) => values[a].compareTo(values[b]));
  final ranks = List<double>.filled(values.length, 0);
  var i = 0;
  while (i < order.length) {
    var j = i;
    while (j + 1 < order.length && values[order[j + 1]] == values[order[i]]) {
      j++;
    }
    final average = (i + j) / 2 + 1;
    for (var t = i; t <= j; t++) {
      ranks[order[t]] = average;
    }
    i = j + 1;
  }
  return ranks;
}

/// スピアマンの順位相関。どちらかが全部同じ値なら null。
double? spearman(List<(double, double)> pairs) {
  if (pairs.length < 3) return null;
  final x = _ranks([for (final p in pairs) p.$1]);
  final y = _ranks([for (final p in pairs) p.$2]);
  final mx = _mean(x)!, my = _mean(y)!;
  var sxy = 0.0, sxx = 0.0, syy = 0.0;
  for (var i = 0; i < x.length; i++) {
    sxy += (x[i] - mx) * (y[i] - my);
    sxx += (x[i] - mx) * (x[i] - mx);
    syy += (y[i] - my) * (y[i] - my);
  }
  if (sxx == 0 || syy == 0) return null;
  return sxy / sqrt(sxx * syy);
}

/// 日ごとの値（その日のグループの平均）を平均し、日単位のブートストラップで
/// 95%区間を付ける。
Map<String, Object?> daySummary(
  Map<String, List<double>> byDay, {
  int rounds = 10000,
  int seed = 20260930,
}) {
  final days = byDay.keys.toList()..sort();
  final values = [for (final d in days) _mean(byDay[d]!)!];
  final ci = dayBootstrap(values, rounds: rounds, seed: seed);
  double r(double v) => double.parse(v.toStringAsFixed(4));
  return {
    'days': values.length,
    'groups': byDay.values.fold<int>(0, (s, v) => s + v.length),
    'mean_of_days': values.isEmpty ? null : r(_mean(values)!),
    'ci95': ci == null ? null : [r(ci.$1), r(ci.$2)],
    'positive_days': values.where((v) => v > 0).length,
    'by_day': {for (final (i, d) in days.indexed) d: r(values[i])},
  };
}

/// 翌日、同じ機種で回転数が近い台の中での当たり順位（0〜1）。比べる台が
/// 3台未満、500G未満、数値異常なら null。
double? hitRankAmongPeers(SlotRecord row, List<SlotRecord> sameMachineDay) {
  if (row.games < 500 ||
      row.bb < 0 ||
      row.rb < 0 ||
      hasImplausibleNumbers(row)) {
    return null;
  }
  final peers = [
    for (final r in sameMachineDay)
      if (r.games >= 500 &&
          r.bb >= 0 &&
          r.rb >= 0 &&
          !hasImplausibleNumbers(r) &&
          r.games >= row.games / 2 &&
          r.games <= row.games * 2)
        r,
  ];
  if (peers.length < 3) return null;
  return percentile(
    (row.bb + row.rb) / row.games,
    peers.map((r) => (r.bb + r.rb) / r.games).toList(),
  );
}
