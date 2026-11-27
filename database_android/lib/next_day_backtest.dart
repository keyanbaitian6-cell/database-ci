import 'dart:math';

import 'data_checks.dart';
import 'exploratory_candidates.dart';
import 'list_views.dart';
import 'models.dart';
import 'scoring.dart';

/// 翌日候補（仮）の検証（読み取り専用。画面からは使わない）。
///
/// 候補の計算はアプリ本体の [provisionalNextDayCandidates]・[dayCandidates]、
/// 点数は [scoreRecord] をそのまま呼ぶので、検証の候補とアプリの候補は
/// 必ず同じになる。手順と結果は `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md`。

const _jst = Duration(hours: 9);

/// 時差の書かれた時刻の末尾（`+09:00`・`Z` など）。
final _zone = RegExp(r'(Z|[+-]\d{2}:?\d{2})$');

/// 時刻をUTCで読む。時差の無い時刻（Android版の古い記録）は日本時間とみなす。
DateTime? readJst(String? text) {
  if (text == null || text.isEmpty) return null;
  final parsed = DateTime.tryParse(text);
  if (parsed == null) return null;
  if (_zone.hasMatch(text)) return parsed.toUtc();
  return DateTime.utc(
    parsed.year,
    parsed.month,
    parsed.day,
    parsed.hour,
    parsed.minute,
    parsed.second,
    parsed.millisecond,
    parsed.microsecond,
  ).subtract(_jst);
}

String shiftDay(String day, int days) {
  final d = DateTime.parse(day);
  return DateTime.utc(
    d.year,
    d.month,
    d.day + days,
  ).toIso8601String().substring(0, 10);
}

/// 予測日 [day] の締切：翌日の [hour] 時（日本時間）をUTCで。
DateTime predictionCutoff(String day, {int hour = 0}) {
  final d = DateTime.parse(day);
  return DateTime.utc(d.year, d.month, d.day + 1, hour).subtract(_jst);
}

/// アプリの一覧と同じく、機種名をそろえて同じ台を1件にまとめる
/// （`AppController._normalizeRecords` と同じ規則）。
List<SlotRecord> normalizeForBacktest(Iterable<SlotRecord> source) {
  final merged = <String, SlotRecord>{};
  for (final original in source) {
    final record = original.copyWith(
      machine: normalizeMachineName(original.machine),
    );
    final current = merged[record.key];
    merged[record.key] = current == null
        ? record
        : mergeSameRack(current, record);
  }
  return merged.values.toList();
}

/// 予測日 [day] の締切 [cutoff] までに入手できた記録（日付が [day] 以前）。
///
/// 今の記録の `captured_at` が締切より前なら、その値は締切の時点で分かって
/// いた値と同じ。締切より後なら、[earlier]（取り込み直しで上書きされる前の
/// 値。PC版の書き込み記録など）のうち締切より前で最後のものを使い、それも
/// 無ければ使わない。[cutoff] が null なら時刻を見ない（後知恵を含み得る）。
List<SlotRecord> availableRecords(
  List<SlotRecord> all,
  String day, {
  DateTime? cutoff,
  Map<String, List<SlotRecord>> earlier = const {},
}) {
  final result = <SlotRecord>[];
  for (final r in all) {
    if (r.day.compareTo(day) > 0) continue;
    if (cutoff == null) {
      result.add(r);
      continue;
    }
    final at = readJst(r.capturedAt);
    if (at != null && at.isBefore(cutoff)) {
      result.add(r);
      continue;
    }
    SlotRecord? best;
    DateTime? bestAt;
    for (final e in earlier[r.key] ?? const <SlotRecord>[]) {
      final t = readJst(e.capturedAt);
      if (t == null || !t.isBefore(cutoff)) continue;
      if (bestAt == null || t.isAfter(bestAt)) {
        best = e;
        bestAt = t;
      }
    }
    if (best != null) result.add(best);
  }
  return result;
}

/// 候補にできる台（指数を計算できた台）1台ぶん。
class BacktestMember {
  BacktestMember({
    required this.rack,
    required this.machine,
    required this.index,
    required this.days,
    required this.confidence,
    required this.todayScore,
    required this.nextScore,
    this.rawIndex,
    this.latestUsed = '',
    this.nextGames,
    this.nextHits,
    this.nextPlus,
  });
  final int rack;

  /// 台の機種名（バラエティのグループには別々の機種の台が入る）。
  final String machine;
  final double index;
  final double? rawIndex;
  final String latestUsed;
  final int days;
  final String confidence;

  /// 予測日の合計点（締切の時点の記録で計算）。無ければ null。
  final double? todayScore;

  /// 翌日の合計点（正解）。翌日に同じ店舗・機種・台番号の記録が無い、
  /// または採点しない台は null（0点にはしない）。
  final double? nextScore;

  /// 翌日の正常稼働（500G未満含む）のゲーム数と総当たり回数（O/E比用）。異常値・未稼働は null。
  final int? nextGames;
  final int? nextHits;

  /// 翌日の記録上のプラス判定（取得差枚→グラフ終点±1px超→大当たり0回省略＝false、不明は null）。
  final bool? nextPlus;
  bool current = false;
  bool previousScore = false;

  /// 探索中の選び方（[exploratoryCandidates]）で選ばれた方式。
  final Set<ExploratoryMethod> exploratory = {};
}

bool? _plusOutcome(SlotRecord record) {
  if (record.games <= 0 ||
      hasImplausibleNumbers(record) ||
      isExcludedSupplement(record)) {
    return null;
  }
  final net = record.isPscube ? record.netMedals : record.joNet;
  if (net != null) return net > 0;
  final g = record.graph;
  if (g != null) {
    final end = g.baselineY - g.endY;
    if (!end.isFinite || end.abs() <= 1) return null;
    return end > 1;
  }
  if (record.graphNotNeeded) return false;
  return null;
}

/// 店舗・機種・予測日ごとの候補。[variety] なら、その日その店で1〜3台の
/// 機種をまとめたバラエティ（[machine] は [varietyGroupName]）。
class BacktestGroup {
  BacktestGroup(
    this.store,
    this.machine,
    this.day,
    this.members,
    this.count, {
    this.variety = false,
  });
  final String store, machine, day;
  final bool variety;
  final List<BacktestMember> members;

  /// 選ぶ台数（アプリの候補数と同じ）。
  final int count;
  Iterable<BacktestMember> get labeled =>
      members.where((m) => m.nextScore != null);
}

/// 店舗・予測日ごとの、最初に表示する7台。
class BacktestTopSeven {
  BacktestTopSeven(this.store, this.day, this.current, this.previousScore);
  final String store, day;
  final List<BacktestMember> current, previousScore;

  /// 探索中の選び方ごとの、最初に表示する7台。
  final Map<ExploratoryMethod, List<BacktestMember>> exploratory = {};
}

class BacktestRun {
  BacktestRun(
    this.groups,
    this.topSeven,
    this.unlabeledNextDay, {
    this.varietyGroups = const [],
  });

  /// 4台以上の機種ごとのグループ（2026-09-29の検証の対象）。
  final List<BacktestGroup> groups;

  /// バラエティのグループ（`runBacktest(variety: true)` のときだけ）。
  final List<BacktestGroup> varietyGroups;
  final List<BacktestTopSeven> topSeven;

  /// 候補にできた台のうち、翌日の正解が無かった数の内訳。
  final Map<String, int> unlabeledNextDay;
}

int _byMachineThenRack(
  ({String machine, BacktestMember member}) a,
  ({String machine, BacktestMember member}) b,
) {
  final byMachine = a.machine.compareTo(b.machine);
  return byMachine != 0 ? byMachine : a.member.rack.compareTo(b.member.rack);
}

/// 全予測日の候補を作る。[cutoffFor] が null なら時刻を見ない。
///
/// [variety] が false なら、2026-09-29の検証と同じく4台以上の機種だけを見る
/// （最初に表示する7台も、バラエティの台を除いたアプリの並び）。true なら
/// バラエティ（1〜3台の機種）のグループも作り（[BacktestRun.varietyGroups]）、
/// 最初に表示する7台は今のアプリの並びそのものにする。
BacktestRun runBacktest(
  List<SlotRecord> full, {
  DateTime? Function(String day)? cutoffFor,
  Map<String, List<SlotRecord>> earlier = const {},
  List<ExploratoryMethod> exploratory = const [],
  bool variety = false,
}) {
  final byKey = {for (final r in full) r.key: r};
  final nextScores = <String, double?>{};
  double? nextScore(String store, String day, String machine, int rack) {
    final key = '$store|${shiftDay(day, 1)}|$machine|$rack';
    return nextScores.putIfAbsent(key, () {
      final row = byKey[key];
      return row == null ? null : scoreRecord(row, full).total;
    });
  }

  final unlabeled = <String, int>{'no_record': 0, 'not_scored': 0};
  final allDays = {for (final r in full) r.day};
  final groups = <BacktestGroup>[];
  final varietyGroups = <BacktestGroup>[];
  final tops = <BacktestTopSeven>[];
  for (final day in allDays.toList()..sort()) {
    if (!allDays.contains(shiftDay(day, 1))) continue;
    final available = availableRecords(
      full,
      day,
      cutoff: cutoffFor?.call(day),
      earlier: earlier,
    );
    final byStore = <String, List<SlotRecord>>{};
    for (final r in available) {
      if (r.day == day) byStore.putIfAbsent(r.store, () => []).add(r);
    }
    for (final store in byStore.keys.toList()..sort()) {
      final dayRows = byStore[store]!;
      final varietyNames = varietyMachines(dayRows);
      final byMachine = <String, List<SlotRecord>>{};
      for (final r in dayRows) {
        byMachine.putIfAbsent(r.machine, () => []).add(r);
      }

      /// [rows] のグループ（候補が無ければ null）。候補はアプリの [app]、
      /// 過去傾向は [tendencyOf]（アプリと同じ関数）。バラエティは、候補にしない
      /// 台（あまり回らなかった台など）も比べる相手に入れる（選び方そのものの
      /// 良し悪しを、バラエティの全台と比べて見るため）。
      BacktestGroup? group(
        String name,
        List<SlotRecord> rows,
        ({int total, int eligible, List<ProvisionalCandidate> candidates}) app,
        ({
          int days,
          double? index,
          String confidence,
          double? rawIndex,
          String latestUsed,
        }) Function(SlotRecord)
        tendencyOf, {
        bool isVariety = false,
      }) {
        if (app.candidates.isEmpty) return null;
        final members = <BacktestMember>[];
        for (final row in rows) {
          final tendency = tendencyOf(row);
          if (tendency.index == null) continue;
          final nextKey = '$store|${shiftDay(day, 1)}|${row.machine}|${row.rack}';
          final nextRow = byKey[nextKey];
          final next = nextScore(store, day, row.machine, row.rack);
          if (next == null) {
            final exists = nextRow != null;
            unlabeled[exists ? 'not_scored' : 'no_record'] =
                unlabeled[exists ? 'not_scored' : 'no_record']! + 1;
          }
          final validNext =
              nextRow != null &&
              nextRow.games > 0 &&
              nextRow.bb >= 0 &&
              nextRow.rb >= 0 &&
              !hasImplausibleNumbers(nextRow) &&
              !isExcludedSupplement(nextRow);
          members.add(
            BacktestMember(
              rack: row.rack,
              machine: row.machine,
              index: tendency.index!,
              days: tendency.days,
              confidence: tendency.confidence,
              todayScore: scoreRecord(row, available).total,
              nextScore: next,
              rawIndex: tendency.rawIndex,
              latestUsed: tendency.latestUsed,
              nextGames: validNext ? nextRow.games : null,
              nextHits: validNext ? nextRow.bb + nextRow.rb : null,
              nextPlus: nextRow == null ? null : _plusOutcome(nextRow),
            ),
          );
        }
        // アプリの候補と同じ台であることを必ず確かめる（台番号はその日その店で
        // 1台ずつ）。
        final chosen = {for (final c in app.candidates) c.record.rack};
        if (!isVariety && members.length != app.eligible) {
          throw StateError('$store $day $name: 判定できた台数が違う');
        }
        if (!chosen.every((rack) => members.any((m) => m.rack == rack))) {
          throw StateError('$store $day $name: 候補が比べる相手に入っていない');
        }
        for (final m in members) {
          m.current = chosen.contains(m.rack);
        }
        final byPrevious = [...members]
          ..sort((a, b) {
            final sa = a.todayScore, sb = b.todayScore;
            if (sa != null && sb != null && sa != sb) return sb.compareTo(sa);
            if (sa != null && sb == null) return -1;
            if (sa == null && sb != null) return 1;
            return a.rack.compareTo(b.rack);
          });
        for (final m in byPrevious.take(chosen.length)) {
          m.previousScore = true;
        }
        return BacktestGroup(
          store,
          name,
          day,
          members,
          chosen.length,
          variety: isVariety,
        );
      }

      final storeGroups = <BacktestGroup>[];
      for (final machine in byMachine.keys.toList()..sort()) {
        // 1〜3台の機種は、機種ごとには候補が出ない（判定できる台が4台未満）。
        if (varietyNames.contains(machine)) continue;
        final rows = byMachine[machine]!;
        final history = machineHistory(available, store, machine);
        final built = group(
          machine,
          rows,
          provisionalNextDayCandidates(rows, history),
          (row) {
            final e = nextDayEvidence(row, history);
            return (
              days: e.usedDays,
              index: e.index,
              confidence: e.usedDays < 7 ? '少' : '中',
              rawIndex: e.rawIndex,
              latestUsed: e.latestUsed,
            );
          },
        );
        if (built == null) continue;
        groups.add(built);
        storeGroups.add(built);
      }
      if (variety && varietyNames.isNotEmpty) {
        final rows = [
          for (final r in dayRows)
            if (varietyNames.contains(r.machine)) r,
        ];
        final built = group(
          varietyGroupName,
          rows,
          varietyNextDayCandidates(rows, available),
          (row) {
            final hit = varietyHitPercent(row, available);
            final idx = hit.percent ?? 50.0;
            return (
              days: hit.refs,
              index: idx,
              confidence: hit.percent == null ? '比較なし' : (hit.refs < 7 ? '少' : '中'),
              rawIndex: idx,
              latestUsed: '',
            );
          },
          isVariety: true,
        );
        if (built != null) {
          varietyGroups.add(built);
          storeGroups.add(built);
        }
      }
      if (storeGroups.isEmpty) continue;
      // 最初に表示する台：アプリの並び（dayCandidates）の、4台以上の機種の
      // 上位7台（＝2026-09-29の検証のときの並び）。[variety] が true なら、
      // カードで最初から全部出すバラエティの候補も加える。
      final app = dayCandidates(dayRows, available).candidates;
      final shown = [
        ...app.where((c) => !c.variety).take(7),
        if (variety) ...app.where((c) => c.variety),
      ];
      final lookup = {
        for (final g in storeGroups)
          for (final m in g.members) '${m.machine}|${m.rack}': m,
      };
      final currentTop = [
        for (final c in shown) lookup['${c.record.machine}|${c.record.rack}']!,
      ];
      final previousPool = [
        for (final g in storeGroups)
          for (final m in g.members)
            if (m.previousScore) (machine: m.machine, member: m),
      ]..sort((a, b) {
          final sa = a.member.todayScore, sb = b.member.todayScore;
          if (sa != null && sb != null && sa != sb) return sb.compareTo(sa);
          if (sa != null && sb == null) return -1;
          if (sa == null && sb != null) return 1;
          return _byMachineThenRack(a, b);
        });
      final top = BacktestTopSeven(store, day, currentTop, [
        for (final p in previousPool.take(7)) p.member,
      ]);
      for (final method in exploratory) {
        final picks = exploratoryCandidates(dayRows, available, method);
        final members = [
          for (final c in picks) lookup['${c.record.machine}|${c.record.rack}']!,
        ];
        for (final m in members) {
          m.exploratory.add(method);
        }
        top.exploratory[method] = members.take(7).toList();
      }
      tops.add(top);
    }
  }
  return BacktestRun(groups, tops, unlabeled, varietyGroups: varietyGroups);
}

double? _mean(Iterable<double> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.reduce((a, b) => a + b) / list.length;
}

/// 日単位のブートストラップ95%区間（日を単位に復元抽出）。
(double, double)? dayBootstrap(
  List<double> dayValues, {
  int rounds = 10000,
  int seed = 20260929,
}) {
  if (dayValues.length < 2) return null;
  final rng = Random(seed);
  final means = <double>[];
  for (var i = 0; i < rounds; i++) {
    var sum = 0.0;
    for (var j = 0; j < dayValues.length; j++) {
      sum += dayValues[rng.nextInt(dayValues.length)];
    }
    means.add(sum / dayValues.length);
  }
  means.sort();
  return (means[(rounds * 0.025).floor()], means[(rounds * 0.975).floor() - 1]);
}

double _round(double v, [int digits = 2]) =>
    double.parse(v.toStringAsFixed(digits));

/// 日ごとの平均から、日の平均・区間・正の日数をまとめる。
Map<String, Object?> _daySummary(Map<String, List<double>> byDay) {
  final dayValues = [
    for (final day in byDay.keys.toList()..sort()) _mean(byDay[day]!)!,
  ];
  final ci = dayBootstrap(dayValues);
  return {
    'days': dayValues.length,
    'mean_of_days': dayValues.isEmpty ? null : _round(_mean(dayValues)!),
    'ci95': ci == null ? null : [_round(ci.$1), _round(ci.$2)],
    'positive_days': dayValues.where((v) => v > 0).length,
    'by_day': {
      for (final day in byDay.keys.toList()..sort())
        day: _round(_mean(byDay[day]!)!),
    },
  };
}

/// 選び方 [picked] の成績（候補にできる台の平均との差）。
Map<String, Object?> evaluateMethod(
  Iterable<BacktestGroup> groups,
  bool Function(BacktestMember) picked,
) {
  final chosen = <double>[], pool = <double>[], pct = <double>[];
  var selected = 0, evaluable = 0, groupsUsed = 0;
  final gapByDay = <String, List<double>>{};
  for (final g in groups) {
    final labeled = g.labeled.toList();
    final picks = g.members.where(picked).toList();
    selected += picks.length;
    final scored = [
      for (final m in picks)
        if (m.nextScore != null) m.nextScore!,
    ];
    evaluable += scored.length;
    if (labeled.isEmpty || scored.isEmpty) continue;
    groupsUsed++;
    final poolScores = [for (final m in labeled) m.nextScore!];
    chosen.addAll(scored);
    pool.addAll(poolScores);
    for (final s in scored) {
      pct.add(percentile(s, poolScores));
    }
    gapByDay
        .putIfAbsent(g.day, () => [])
        .add(_mean(scored)! - _mean(poolScores)!);
  }
  return {
    'groups': groupsUsed,
    'selected': selected,
    'evaluable': evaluable,
    'evaluable_rate': selected == 0 ? null : _round(evaluable / selected, 3),
    'chosen_mean': chosen.isEmpty ? null : _round(_mean(chosen)!),
    'pool_mean': pool.isEmpty ? null : _round(_mean(pool)!),
    'chosen_p60': chosen.isEmpty
        ? null
        : _round(chosen.where((v) => v >= 60).length / chosen.length, 3),
    'pool_p60': pool.isEmpty
        ? null
        : _round(pool.where((v) => v >= 60).length / pool.length, 3),
    'mean_percentile': pct.isEmpty ? null : _round(_mean(pct)!, 3),
    'gap_vs_pool': _daySummary(gapByDay),
  };
}

/// 現行と前日の点数が高い台の、同じグループでの直接比較（前日点 − 現行）。
Map<String, Object?> comparePreviousToCurrent(Iterable<BacktestGroup> groups) =>
    compareMethods(groups, (m) => m.previousScore, (m) => m.current);

/// 2つの選び方の、同じグループでの直接比較（[a] − [b]）。
Map<String, Object?> compareMethods(
  Iterable<BacktestGroup> groups,
  bool Function(BacktestMember) a,
  bool Function(BacktestMember) b,
) {
  final byDay = <String, List<double>>{};
  for (final g in groups) {
    final first = [
      for (final m in g.members)
        if (a(m) && m.nextScore != null) m.nextScore!,
    ];
    final second = [
      for (final m in g.members)
        if (b(m) && m.nextScore != null) m.nextScore!,
    ];
    if (first.isEmpty || second.isEmpty) continue;
    byDay.putIfAbsent(g.day, () => []).add(_mean(first)! - _mean(second)!);
  }
  return _daySummary(byDay);
}

/// 最初に表示する7台の成績（候補にできる台全体・候補全体との差）。
Map<String, Object?> evaluateTopSeven(
  List<BacktestTopSeven> tops,
  List<BacktestGroup> groups, {
  required bool current,
}) => evaluateTopSevenBy(
  tops,
  groups,
  (t) => current ? t.current : t.previousScore,
  (m) => current ? m.current : m.previousScore,
);

/// 最初に表示する7台（[shown]）の成績。[isCandidate] はその方式の候補全体。
Map<String, Object?> evaluateTopSevenBy(
  List<BacktestTopSeven> tops,
  List<BacktestGroup> groups,
  List<BacktestMember> Function(BacktestTopSeven) shownOf,
  bool Function(BacktestMember) isCandidate,
) {
  final vsPool = <String, List<double>>{}, vsCandidates = <String, List<double>>{};
  final shown = <double>[];
  var selected = 0;
  for (final t in tops) {
    final members = shownOf(t);
    selected += members.length;
    final scored = [
      for (final m in members)
        if (m.nextScore != null) m.nextScore!,
    ];
    final storeGroups = groups.where((g) => g.store == t.store && g.day == t.day);
    final pool = [
      for (final g in storeGroups)
        for (final m in g.labeled) m.nextScore!,
    ];
    final candidates = [
      for (final g in storeGroups)
        for (final m in g.labeled)
          if (isCandidate(m)) m.nextScore!,
    ];
    if (scored.isEmpty || pool.isEmpty) continue;
    shown.addAll(scored);
    vsPool.putIfAbsent(t.day, () => []).add(_mean(scored)! - _mean(pool)!);
    if (candidates.isNotEmpty) {
      vsCandidates
          .putIfAbsent(t.day, () => [])
          .add(_mean(scored)! - _mean(candidates)!);
    }
  }
  return {
    'store_days': vsPool.values.fold<int>(0, (n, v) => n + v.length),
    'selected': selected,
    'evaluable': shown.length,
    'shown_mean': shown.isEmpty ? null : _round(_mean(shown)!),
    'shown_p60': shown.isEmpty
        ? null
        : _round(shown.where((v) => v >= 60).length / shown.length, 3),
    'gap_vs_pool': _daySummary(vsPool),
    'gap_vs_all_candidates': _daySummary(vsCandidates),
  };
}

double? _spearman(List<(double, double)> pairs) {
  if (pairs.length < 4) return null;
  List<double> ranks(List<double> v) {
    final order = List<int>.generate(v.length, (i) => i)
      ..sort((a, b) => v[a].compareTo(v[b]));
    final r = List<double>.filled(v.length, 0);
    var i = 0;
    while (i < order.length) {
      var j = i;
      while (j + 1 < order.length && v[order[j + 1]] == v[order[i]]) {
        j++;
      }
      for (var k = i; k <= j; k++) {
        r[order[k]] = (i + j) / 2;
      }
      i = j + 1;
    }
    return r;
  }

  final a = ranks([for (final p in pairs) p.$1]);
  final b = ranks([for (final p in pairs) p.$2]);
  final ma = _mean(a)!, mb = _mean(b)!;
  var num = 0.0, da = 0.0, db = 0.0;
  for (var i = 0; i < a.length; i++) {
    num += (a[i] - ma) * (b[i] - mb);
    da += (a[i] - ma) * (a[i] - ma);
    db += (b[i] - mb) * (b[i] - mb);
  }
  return da == 0 || db == 0 ? null : num / sqrt(da * db);
}

/// 指数と翌日の点の順位相関：機種の中と、店舗・日の全台（機種をまたぐ）。
Map<String, Object?> indexCorrelation(List<BacktestGroup> groups) {
  final within = <String, List<double>>{};
  final across = <String, List<double>>{};
  final byStoreDay = <String, List<(double, double)>>{};
  for (final g in groups) {
    final pairs = [
      for (final m in g.labeled) (m.index, m.nextScore!),
    ];
    final rho = _spearman(pairs);
    if (rho != null) within.putIfAbsent(g.day, () => []).add(rho);
    byStoreDay.putIfAbsent('${g.store}|${g.day}', () => []).addAll(pairs);
  }
  for (final entry in byStoreDay.entries) {
    final rho = _spearman(entry.value);
    if (rho != null) {
      across.putIfAbsent(entry.key.split('|').last, () => []).add(rho);
    }
  }
  return {'within_machine': _daySummary(within), 'across_machines': _daySummary(across)};
}

/// 保存済みの予想（締切より前で最後の記録）を、再計算した候補と比べる。
Map<String, Object?> evaluateSavedSnapshots(
  List<BacktestGroup> groups,
  List<({String store, String day, String machine, String takenAt, List<int> racks})>
  snapshots, {
  int cutoffHour = 0,
}) {
  final latest = <String, ({String takenAt, List<int> racks})>{};
  for (final s in snapshots) {
    final at = readJst(s.takenAt);
    if (at == null || !at.isBefore(predictionCutoff(s.day, hour: cutoffHour))) {
      continue;
    }
    final key = '${s.store}|${s.day}|${s.machine}';
    final current = latest[key];
    if (current == null || readJst(current.takenAt)!.isBefore(at)) {
      latest[key] = (takenAt: s.takenAt, racks: s.racks);
    }
  }
  var matched = 0, same = 0, withCandidates = 0;
  final gapByDay = <String, List<double>>{};
  final chosen = <double>[];
  for (final g in groups) {
    final saved = latest['${g.store}|${g.day}|${g.machine}'];
    if (saved == null) continue;
    matched++;
    final recomputed = {
      for (final m in g.members)
        if (m.current) m.rack,
    };
    if (recomputed.length == saved.racks.length &&
        recomputed.containsAll(saved.racks)) {
      same++;
    }
    if (saved.racks.isEmpty) continue;
    withCandidates++;
    final pool = [for (final m in g.labeled) m.nextScore!];
    final picks = [
      for (final m in g.labeled)
        if (saved.racks.contains(m.rack)) m.nextScore!,
    ];
    if (pool.isEmpty || picks.isEmpty) continue;
    chosen.addAll(picks);
    gapByDay.putIfAbsent(g.day, () => []).add(_mean(picks)! - _mean(pool)!);
  }
  return {
    'saved_groups_before_cutoff': latest.length,
    'matched_to_evaluated_groups': matched,
    'same_as_recomputed': same,
    'with_candidates': withCandidates,
    'chosen_evaluable': chosen.length,
    'chosen_mean': chosen.isEmpty ? null : _round(_mean(chosen)!),
    'gap_vs_pool': _daySummary(gapByDay),
  };
}

List<List<double>> _calendarBlocks(
  Map<String, double> byDay, {
  int blockDays = 7,
  String? anchor,
}) {
  if (byDay.isEmpty) return const [];
  final days = byDay.keys.toList()..sort();
  final base = DateTime.parse(anchor ?? days.first);
  final grouped = <int, List<double>>{};
  for (final day in days) {
    final idx = DateTime.parse(day).difference(base).inDays ~/ blockDays;
    grouped.putIfAbsent(idx, () => []).add(byDay[day]!);
  }
  return [for (final k in grouped.keys.toList()..sort()) grouped[k]!];
}

/// 暦日ブロック単位のブートストラップ95%区間（日列の自己相関を保つためブロックごと復元抽出）。
(double, double)? blockBootstrap(
  Map<String, double> byDay, {
  int blockDays = 7,
  int rounds = 5000,
  int seed = 20260929,
  String? anchor,
}) {
  final blocks = _calendarBlocks(byDay, blockDays: blockDays, anchor: anchor);
  if (blocks.length < 2) return null;
  final stats = [
    for (final b in blocks) (b.reduce((a, c) => a + c), b.length),
  ];
  final rng = Random(seed);
  final means = <double>[];
  for (var i = 0; i < rounds; i++) {
    var s = 0.0;
    var n = 0;
    for (var j = 0; j < stats.length; j++) {
      final pick = stats[rng.nextInt(stats.length)];
      s += pick.$1;
      n += pick.$2;
    }
    means.add(s / n);
  }
  means.sort();
  return (means[(rounds * 0.025).floor()], means[(rounds * 0.975).floor() - 1]);
}

/// 暦日ブロック単位の符号反転検定（片側 p 値）。ブロック数14以下は全通り正確計算。
({double mean, double p, int blocks})? blockSignFlipP(
  Map<String, double> byDay, {
  int blockDays = 7,
  int trials = 10000,
  int seed = 20260929,
  String? anchor,
}) {
  final blocks = _calendarBlocks(byDay, blockDays: blockDays, anchor: anchor);
  if (blocks.isEmpty) return null;
  final sums = [for (final b in blocks) b.reduce((a, c) => a + c)];
  final totalDays = blocks.fold<int>(0, (n, b) => n + b.length);
  final observed = sums.reduce((a, c) => a + c) / totalDays;
  final k = sums.length;
  if (k <= 14) {
    final total = 1 << k;
    var hits = 0;
    for (var mask = 0; mask < total; mask++) {
      var signed = 0.0;
      for (var i = 0; i < k; i++) {
        signed += ((mask >> i) & 1) == 1 ? sums[i] : -sums[i];
      }
      if (signed / totalDays >= observed - 1e-12) hits++;
    }
    return (mean: observed, p: hits / total, blocks: k);
  }
  final rng = Random(seed);
  var hits = 0;
  for (var t = 0; t < trials; t++) {
    var signed = 0.0;
    for (var i = 0; i < k; i++) {
      signed += rng.nextBool() ? sums[i] : -sums[i];
    }
    if (signed / totalDays >= observed - 1e-12) hits++;
  }
  return (mean: observed, p: (hits + 1) / (trials + 1), blocks: k);
}

/// 自己相関・稼働バイアス・非無作為欠測を考慮した堅牢評価。
/// 1) 合計点差の7日／14日ブロック区間・ブロック符号反転検定
/// 2) 500G未満含む全稼働台の当たり回数比（O/E）
/// 3) 記録上のプラス率と Manski 最悪／最良境界・共通置換の感度分析
Map<String, Object?> evaluateRobustMetrics(
  Iterable<BacktestGroup> groups,
  bool Function(BacktestMember) picked,
) {
  final scoreByDay = <String, List<double>>{};
  final plusByDay = <String, List<double>>{};
  final worstByDay = <String, List<double>>{};
  final bestByDay = <String, List<double>>{};
  final both0ByDay = <String, List<double>>{};
  final both1ByDay = <String, List<double>>{};
  final oeByDay = <String, (double obs, double exp)>{};
  var oeObs = 0.0, oeExp = 0.0;
  var candTotal = 0, candPlusJudged = 0, candPlusHits = 0;
  var poolTotal = 0, poolPlusJudged = 0, poolPlusHits = 0;

  for (final g in groups) {
    final picks = g.members.where(picked).toList();
    if (picks.isEmpty || g.members.isEmpty) continue;
    final poolScores = [for (final m in g.labeled) m.nextScore!];
    final pickScores = [
      for (final m in picks)
        if (m.nextScore != null) m.nextScore!,
    ];
    if (poolScores.isNotEmpty && pickScores.isNotEmpty) {
      scoreByDay
          .putIfAbsent(g.day, () => [])
          .add(_mean(pickScores)! - _mean(poolScores)!);
    }

    final validPool = [
      for (final m in g.members)
        if (m.nextGames != null && m.nextGames! > 0 && m.nextHits != null) m,
    ];
    final validPicks = [
      for (final m in picks)
        if (m.nextGames != null && m.nextGames! > 0 && m.nextHits != null) m,
    ];
    if (validPool.isNotEmpty && validPicks.isNotEmpty) {
      final gPool = validPool.fold<int>(0, (s, m) => s + m.nextGames!);
      final hPool = validPool.fold<int>(0, (s, m) => s + m.nextHits!);
      if (gPool > 0) {
        final rate = hPool / gPool;
        final gCand = validPicks.fold<int>(0, (s, m) => s + m.nextGames!);
        final hCand = validPicks.fold<int>(0, (s, m) => s + m.nextHits!);
        final exp = gCand * rate;
        oeObs += hCand;
        oeExp += exp;
        final prev = oeByDay[g.day] ?? (0.0, 0.0);
        oeByDay[g.day] = (prev.$1 + hCand, prev.$2 + exp);
      }
    }

    candTotal += picks.length;
    poolTotal += g.members.length;
    final cj = [
      for (final m in picks)
        if (m.nextPlus != null) m.nextPlus! ? 1.0 : 0.0,
    ];
    final pj = [
      for (final m in g.members)
        if (m.nextPlus != null) m.nextPlus! ? 1.0 : 0.0,
    ];
    candPlusJudged += cj.length;
    candPlusHits += cj.where((v) => v > 0).length;
    poolPlusJudged += pj.length;
    poolPlusHits += pj.where((v) => v > 0).length;
    if (cj.isNotEmpty && pj.isNotEmpty) {
      plusByDay.putIfAbsent(g.day, () => []).add(_mean(cj)! - _mean(pj)!);
    }
    final wc = [
      for (final m in picks) m.nextPlus == null ? 0.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    final wp = [
      for (final m in g.members)
        m.nextPlus == null
            ? (picked(m) ? 0.0 : 1.0)
            : (m.nextPlus! ? 1.0 : 0.0),
    ];
    worstByDay.putIfAbsent(g.day, () => []).add(_mean(wc)! - _mean(wp)!);
    final bc = [
      for (final m in picks) m.nextPlus == null ? 1.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    final bp = [
      for (final m in g.members)
        m.nextPlus == null
            ? (picked(m) ? 1.0 : 0.0)
            : (m.nextPlus! ? 1.0 : 0.0),
    ];
    bestByDay.putIfAbsent(g.day, () => []).add(_mean(bc)! - _mean(bp)!);
    final z0c = [
      for (final m in picks) m.nextPlus == null ? 0.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    final z0p = [
      for (final m in g.members)
        m.nextPlus == null ? 0.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    both0ByDay.putIfAbsent(g.day, () => []).add(_mean(z0c)! - _mean(z0p)!);
    final z1c = [
      for (final m in picks) m.nextPlus == null ? 1.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    final z1p = [
      for (final m in g.members)
        m.nextPlus == null ? 1.0 : (m.nextPlus! ? 1.0 : 0.0),
    ];
    both1ByDay.putIfAbsent(g.day, () => []).add(_mean(z1c)! - _mean(z1p)!);
  }

  Map<String, double> dayMeans(Map<String, List<double>> src) => {
    for (final day in src.keys.toList()..sort()) day: _mean(src[day]!)!,
  };

  Map<String, Object?> blockSummary(Map<String, double> dm, {int digits = 2}) {
    final flip7 = blockSignFlipP(dm, blockDays: 7);
    final ci7 = blockBootstrap(dm, blockDays: 7);
    final flip14 = blockSignFlipP(dm, blockDays: 14);
    final ci14 = blockBootstrap(dm, blockDays: 14);
    return {
      'days': dm.length,
      'mean_of_days': dm.isEmpty ? null : _round(_mean(dm.values)!, digits),
      'block7_p': flip7 == null ? null : _round(flip7.p, 4),
      'block7_count': flip7?.blocks ?? 0,
      'block7_ci95': ci7 == null
          ? null
          : [_round(ci7.$1, digits), _round(ci7.$2, digits)],
      'block14_p': flip14 == null ? null : _round(flip14.p, 4),
      'block14_count': flip14?.blocks ?? 0,
      'block14_ci95': ci14 == null
          ? null
          : [_round(ci14.$1, digits), _round(ci14.$2, digits)],
    };
  }

  final oeExcess = {
    for (final e in oeByDay.entries)
      if (e.value.$2 > 0) e.key: e.value.$1 / e.value.$2 - 1.0,
  };
  final oeCi7 = blockBootstrap(oeExcess, blockDays: 7);
  final plusDays = dayMeans(plusByDay);
  final worstDays = dayMeans(worstByDay);
  final bestDays = dayMeans(bestByDay);
  final both0Days = dayMeans(both0ByDay);
  final both1Days = dayMeans(both1ByDay);

  return {
    'score_gap': blockSummary(dayMeans(scoreByDay)),
    'oe_ratio': {
      'observed': oeObs.round(),
      'expected': _round(oeExp, 2),
      'ratio': oeExp > 0 ? _round(oeObs / oeExp, 4) : null,
      'block7_ratio_ci95': oeCi7 == null
          ? null
          : [_round(1.0 + oeCi7.$1, 4), _round(1.0 + oeCi7.$2, 4)],
    },
    'plus_rate': {
      ...blockSummary(plusDays, digits: 4),
      'cand_total': candTotal,
      'cand_judged': candPlusJudged,
      'cand_plus': candPlusHits,
      'cand_rate': candPlusJudged == 0
          ? null
          : _round(candPlusHits / candPlusJudged, 4),
      'cand_missing_rate': candTotal == 0
          ? null
          : _round((candTotal - candPlusJudged) / candTotal, 4),
      'pool_total': poolTotal,
      'pool_judged': poolPlusJudged,
      'pool_plus': poolPlusHits,
      'pool_rate': poolPlusJudged == 0
          ? null
          : _round(poolPlusHits / poolPlusJudged, 4),
      'pool_missing_rate': poolTotal == 0
          ? null
          : _round((poolTotal - poolPlusJudged) / poolTotal, 4),
      'manski_worst': worstDays.isEmpty
          ? null
          : _round(_mean(worstDays.values)!, 4),
      'manski_best': bestDays.isEmpty
          ? null
          : _round(_mean(bestDays.values)!, 4),
      'both_zero': both0Days.isEmpty
          ? null
          : _round(_mean(both0Days.values)!, 4),
      'both_one': both1Days.isEmpty
          ? null
          : _round(_mean(both1Days.values)!, 4),
    },
  };
}
