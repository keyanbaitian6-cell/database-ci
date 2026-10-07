import 'data_checks.dart';
import 'models.dart';
import 'next_day_backtest.dart';
import 'reference_candidate_comparison.dart';
import 'scoring.dart';

/// Analysis-only selection fixed in NEXT_DAY_FOCUS_PLAN_20260930.md. Nothing
/// here feeds production stars, daily scores or stored candidate snapshots.
const focusValidationFrom = '2026-09-30';
const focusValidationThrough = '2026-10-29';
const focusValidationFinalOn = '2026-10-31';

/// The prediction day D ends at 02:00 JST on D+1, the business-day rule the
/// user fixed for imports (`businessDayCutoffHour`, `browser_import.py`).
/// Changed from 00:00 on 2026-10-07 at the user's direction; 00:00 stays as a
/// sensitivity check that is never used for adoption.
const focusCutoffHour = 2;

/// Ties on the unrounded recent index go to the rack with more games on the
/// prediction day (user decision 2026-10-07, fixed before any result of the
/// period was viewed), then the production order: days, latest day, rack.
List<BacktestMember> focusPrimaryPicks(
  BacktestGroup group,
  Map<int, double> recentIndices,
  Map<int, int> todayGames,
) {
  final sorted = [...group.members]
    ..sort((a, b) {
      final byIndex = recentIndices[b.rack]!.compareTo(recentIndices[a.rack]!);
      if (byIndex != 0) return byIndex;
      final byGames = todayGames[b.rack]!.compareTo(todayGames[a.rack]!);
      if (byGames != 0) return byGames;
      final byDays = b.days.compareTo(a.days);
      if (byDays != 0) return byDays;
      final byLatest = b.latestUsed.compareTo(a.latestUsed);
      return byLatest != 0 ? byLatest : a.rack.compareTo(b.rack);
    });
  return sorted
      .where((m) => m.todayScore == null || m.todayScore! < 88)
      .take(group.count)
      .toList();
}

class FocusValidationGroup {
  FocusValidationGroup(
    this.baseline,
    this.primary,
    this.focus,
    this.longTrend,
    this.recentIndices,
    this.todayGames,
  );
  final BacktestGroup baseline;
  final Set<int> primary, focus, longTrend;
  final Map<int, double> recentIndices;
  final Map<int, int> todayGames;
}

/// Keep the baseline population even when all the primary/focus picks are
/// excluded. Cutoffs are before D+1 [cutoffHour]:00 JST; missing labels stay
/// null. A [from]/[through] other than the fixed period is a retrospective
/// reference only (those days were seen when the method was chosen).
List<FocusValidationGroup> buildFocusValidation(
  List<SlotRecord> full, {
  int cutoffHour = focusCutoffHour,
  String from = focusValidationFrom,
  String through = focusValidationThrough,
}) {
  if (scoringVersion != referenceScoringVersion ||
      nextDayMethodVersion != '2026-10-07') {
    throw StateError('固定期間の採点・候補方式の版が違います');
  }
  DateTime cutoff(String day) => predictionCutoff(day, hour: cutoffHour);
  final baseline = runBacktest(full, cutoffFor: cutoff);
  final available = <String, List<SlotRecord>>{};
  final result = <FocusValidationGroup>[];
  for (final g in baseline.groups) {
    if (g.day.compareTo(from) < 0 || g.day.compareTo(through) > 0) {
      continue;
    }
    final source = available.putIfAbsent(
      g.day,
      () => availableRecords(full, g.day, cutoff: cutoff(g.day)),
    );
    final history = machineHistory(source, g.store, g.machine);
    final rows = {
      for (final r in history)
        if (r.day == g.day) r.rack: r,
    };
    final recent = <int, double>{};
    final games = <int, int>{};
    final focus = <int>{}, longTrend = <int>{};
    for (final m in g.members) {
      final row = rows[m.rack]!;
      recent[m.rack] = recentReferenceIndex(row, history).index!;
      games[m.rack] = row.games;
      if (!m.current) continue;
      (qualifiesForNextDayFocus(nextDayEvidence(row, history), m.todayScore)
              ? focus
              : longTrend)
          .add(m.rack);
    }
    result.add(
      FocusValidationGroup(
        g,
        {for (final m in focusPrimaryPicks(g, recent, games)) m.rack},
        focus,
        longTrend,
        recent,
        games,
      ),
    );
  }
  return result;
}
