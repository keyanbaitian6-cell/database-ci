import 'data_checks.dart';
import 'models.dart';
import 'next_day_backtest.dart';
import 'scoring.dart';

/// 分析専用（画面からは呼ばない）。当日80点以上の台を翌日も推すのは適切か。
/// 事前に固定した条件は `NEXT_DAY_STRONG_RACK_REVIEW_20260930.md` の「1.」。

/// 「強い出方が観測された台」の目印（利用者の指定。結果を見て変えない）。
const strongScore = 80.0;

/// グラフの終わり方。大当たり0回でグラフを取らない台は凹み。
enum EndState { plus, dented, none }

EndState endState(SlotRecord? row) {
  if (row == null) return EndState.none;
  if (row.graphNotNeeded) return EndState.dented;
  final g = row.graph;
  if (g == null || !g.baselineY.isFinite || !g.endY.isFinite) {
    return EndState.none;
  }
  return g.baselineY - g.endY > 1 ? EndState.plus : EndState.dented;
}

/// 終点÷最高点（最高点がゼロ線より上の台だけ。グラフが無ければ null）。
double? endToPeak(SlotRecord row) {
  final g = row.graph;
  if (g == null ||
      !g.baselineY.isFinite ||
      !g.peakY.isFinite ||
      !g.endY.isFinite) {
    return null;
  }
  final peak = g.baselineY - g.peakY;
  if (peak <= 0) return null;
  return (g.baselineY - g.endY) / peak;
}

/// 1台・1予測日（主対象の機種、予測時点の見え方）。
class RackDay {
  RackDay({
    required this.record,
    required this.score,
    required this.next,
    required this.nextScore,
  });

  /// 予測日の記録（翌日0:00より前に取り込んだもの）。
  final SlotRecord record;

  /// 予測日の採点（予測時点で入手できた記録だけで計算）。
  final ScoreResult score;

  /// 翌日の同じ店舗・機種・台番号の記録（無ければ null）。
  final SlotRecord? next;

  /// 翌日の点数（正解）。記録が無い・採点しない台は null（0点にしない）。
  final double? nextScore;

  bool get strong => (score.total ?? double.negativeInfinity) >= strongScore;
  String get groupKey => '${record.store}|${record.machine}|${record.day}';
}

/// 予測日ごとに、主対象の機種（その日その店で4台以上）の全台。翌日の日付が
/// データに無い予測日は除く。
List<RackDay> buildRackDays(List<SlotRecord> full) {
  final byKey = {for (final r in full) r.key: r};
  final days = {for (final r in full) r.day};
  final nextCache = <String, double?>{};
  final result = <RackDay>[];
  for (final day in days.toList()..sort()) {
    final next = shiftDay(day, 1);
    if (!days.contains(next)) continue;
    final available = availableRecords(
      full,
      day,
      cutoff: predictionCutoff(day),
    );
    final byStore = <String, List<SlotRecord>>{};
    for (final r in available) {
      if (r.day == day) byStore.putIfAbsent(r.store, () => []).add(r);
    }
    for (final store in byStore.keys.toList()..sort()) {
      final dayRows = byStore[store]!;
      final variety = varietyMachines(dayRows);
      for (final r in dayRows) {
        if (variety.contains(r.machine)) continue;
        final nextRow = byKey['$store|$next|${r.machine}|${r.rack}'];
        result.add(
          RackDay(
            record: r,
            score: scoreRecord(r, available),
            next: nextRow,
            nextScore: nextRow == null
                ? null
                : nextCache.putIfAbsent(
                    nextRow.key,
                    () => scoreRecord(nextRow, full).total,
                  ),
          ),
        );
      }
    }
  }
  return result;
}

/// アプリの並び（丸めた指数の大きい順、同じなら台番号の小さい順）。
List<BacktestMember> currentOrder(BacktestGroup g) =>
    [...g.members]..sort((a, b) {
      final byIndex = b.index.compareTo(a.index);
      return byIndex != 0 ? byIndex : a.rack.compareTo(b.rack);
    });

/// 当日 [threshold] 点以上の台を飛ばしながら、現行の順位で同じ機種の判定可能台
/// から現行の候補数を上限に選ぶ。当日の点数が無い台は飛ばさない。埋まらなければ
/// 候補数が減る（候補なしもあり得る）。
List<BacktestMember> excludeStrong(
  BacktestGroup g, {
  double threshold = strongScore,
}) => excludeWhere(
  g,
  (m) => (m.todayScore ?? double.negativeInfinity) >= threshold,
);

/// [skip] に当たる台を飛ばしながら、現行の順位で同じ機種の判定可能台から現行の
/// 候補数を上限に選ぶ（埋まらなければ候補数が減る）。
List<BacktestMember> excludeWhere(
  BacktestGroup g,
  bool Function(BacktestMember) skip,
) {
  final picks = <BacktestMember>[];
  for (final m in currentOrder(g)) {
    if (picks.length >= g.count) break;
    if (skip(m)) continue;
    picks.add(m);
  }
  return picks;
}

/// 右肩上がり（2026-09-30に利用者が確認した条件）：グラフがあり、終点がゼロ線
/// より上で、終点÷最高点が0.9以上。
bool isUptrend(SlotRecord row) =>
    endState(row) == EndState.plus && (endToPeak(row) ?? 0) >= 0.9;

/// 高稼働（同）：当日3,000G以上、かつ同じ店舗・機種・日の回転数の中央値の
/// 1.5倍以上。
bool isBusy(SlotRecord row, double machineMedianGames) =>
    row.games >= 3000 &&
    machineMedianGames > 0 &&
    row.games / machineMedianGames >= 1.5;
