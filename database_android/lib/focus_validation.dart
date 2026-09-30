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

List<BacktestMember> focusPrimaryPicks(
  BacktestGroup group,
  Map<int, double> recentIndices,
) {
  final sorted = [...group.members]
    ..sort((a, b) {
      final byIndex = recentIndices[b.rack]!.compareTo(recentIndices[a.rack]!);
      if (byIndex != 0) return byIndex;
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
  );
  final BacktestGroup baseline;
  final Set<int> primary, focus, longTrend;
  final Map<int, double> recentIndices;
}

/// Keep the baseline population even when all the primary/focus picks are
/// excluded. Cutoffs are before D+1 midnight JST; missing labels stay null.
List<FocusValidationGroup> buildFocusValidation(List<SlotRecord> full) {
  if (scoringVersion != referenceScoringVersion ||
      nextDayMethodVersion != '2026-09-30') {
    throw StateError('固定期間の採点・候補方式の版が違います');
  }
  final baseline = runBacktest(full, cutoffFor: predictionCutoff);
  final available = <String, List<SlotRecord>>{};
  final result = <FocusValidationGroup>[];
  for (final g in baseline.groups) {
    if (g.day.compareTo(focusValidationFrom) < 0 ||
        g.day.compareTo(focusValidationThrough) > 0) {
      continue;
    }
    final source = available.putIfAbsent(
      g.day,
      () => availableRecords(full, g.day, cutoff: predictionCutoff(g.day)),
    );
    final history = machineHistory(source, g.store, g.machine);
    final rows = {
      for (final r in history)
        if (r.day == g.day) r.rack: r,
    };
    final recent = <int, double>{};
    final focus = <int>{}, longTrend = <int>{};
    for (final m in g.members) {
      final row = rows[m.rack]!;
      recent[m.rack] = recentReferenceIndex(row, history).index!;
      if (!m.current) continue;
      (qualifiesForNextDayFocus(nextDayEvidence(row, history), m.todayScore)
              ? focus
              : longTrend)
          .add(m.rack);
    }
    result.add(
      FocusValidationGroup(
        g,
        {for (final m in focusPrimaryPicks(g, recent)) m.rack},
        focus,
        longTrend,
        recent,
      ),
    );
  }
  return result;
}
