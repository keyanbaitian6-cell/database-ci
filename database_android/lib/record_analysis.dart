import 'candidate_log.dart';
import 'list_views.dart';
import 'models.dart';
import 'scoring.dart';
import 'data_checks.dart';

typedef CandidateCalculator = List<CandidateSnapshot> Function({
  required Iterable<SlotRecord> saved,
  required List<SlotRecord> all,
  required Map<String, CandidateSnapshot> latest,
  required DateTime now,
});

typedef DayView = ({
  Map<String, (SlotRecord, ScoreResult)> scored,
  ({List<ProvisionalCandidate> candidates, int machines, int judged})
  candidates,
});

/// computeへ渡す純粋な関数。ControllerやDB・画面を別Isolateへ送らない。
DayView calculateDay((List<SlotRecord>, String, String) input) {
  final (all, store, day) = input;
  final rows = [
    for (final r in all)
      if (r.store == store && r.day == day) r,
  ];
  return (
    scored: {for (final r in rows) r.key: (r, scoreRecord(r, all))},
    candidates: dayCandidates(rows, all),
  );
}

List<CandidateSnapshot> calculateCandidateChanges(
  (
    List<SlotRecord>,
    List<SlotRecord>,
    Map<String, CandidateSnapshot>,
    DateTime,
    CandidateCalculator,
  )
  input,
) => input.$5(saved: input.$1, all: input.$2, latest: input.$3, now: input.$4);
