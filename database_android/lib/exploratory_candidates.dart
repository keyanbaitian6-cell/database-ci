import 'data_checks.dart';
import 'models.dart';
import 'scoring.dart';

/// 探索中の選び方（閲覧ページの「新規予測」）。現行の翌日候補
/// （[provisionalNextDayCandidates]）とは別物で、検証は済んでいない。
/// 案と決め方は `NEXT_DAY_CANDIDATES_VALIDATION_20260929.md` の「8. 探索」。
enum ExploratoryMethod {
  previousScore('前日の点数が高い台'),
  blend('指数と前日の点数の組み合わせ'),
  recentAverage('直近5日の平均点が高い台'),
  rebound('前日の点数が低い台（凹み台）');

  const ExploratoryMethod(this.label);
  final String label;
}

/// 新規予測の1台。[value] は選んだ根拠の値（方式ごとに意味が違う）。
typedef ExploratoryCandidate = ({
  SlotRecord record,
  double? value,
  double index,
  double? previousScore,
  double? recentAverage,
});

/// [dayRows]（1店舗・1日）の、[method] による新規予測。
///
/// 候補にできる台と台数は現行と同じ：同じ機種で指数（[nextDayIndex]）を
/// 計算できた台が4台以上あるとき、その上位4分の1の台数。点数は [all] から
/// 計算する（その日の点数は前の30日と比べる [scoreRecord]）。並びは、方式の
/// 値の強い順・機種名・台番号。
List<ExploratoryCandidate> exploratoryCandidates(
  List<SlotRecord> dayRows,
  List<SlotRecord> all,
  ExploratoryMethod method,
) {
  final scores = <String, double?>{};
  double? total(SlotRecord r) =>
      scores.putIfAbsent(r.key, () => scoreRecord(r, all).total);

  final byMachine = <String, List<SlotRecord>>{};
  for (final r in dayRows) {
    byMachine.putIfAbsent('${r.store}|${r.machine}', () => []).add(r);
  }
  final result = <ExploratoryCandidate>[];
  for (final rows in byMachine.values) {
    final first = rows.first;
    final history = machineHistory(all, first.store, first.machine);
    final eligible = <({SlotRecord record, double index})>[];
    for (final row in rows) {
      final index = nextDayIndex(row, history).index;
      if (index != null) eligible.add((record: row, index: index));
    }
    if (eligible.length < 4) continue;
    final count = (eligible.length * .25).ceil();

    double? recent(SlotRecord row) {
      final days = [
        for (final r in history)
          if (r.rack == row.rack && r.day.compareTo(row.day) <= 0) r,
      ]..sort((a, b) => b.day.compareTo(a.day));
      final values = [
        for (final r in days.take(5)) ?total(r),
      ];
      return values.length < 2
          ? null
          : values.reduce((a, b) => a + b) / values.length;
    }

    final indexes = [for (final e in eligible) e.index];
    final previous = [
      for (final e in eligible) ?total(e.record),
    ];
    final members = [
      for (final e in eligible)
        () {
          final prev = total(e.record);
          final avg = method == ExploratoryMethod.recentAverage
              ? recent(e.record)
              : null;
          final value = switch (method) {
            ExploratoryMethod.previousScore => prev,
            ExploratoryMethod.rebound => prev,
            ExploratoryMethod.recentAverage => avg,
            ExploratoryMethod.blend =>
              (percentile(e.index, indexes) +
                      (prev == null ? 0 : percentile(prev, previous))) /
                  2,
          };
          return (
            record: e.record,
            value: value,
            index: e.index,
            previousScore: prev,
            recentAverage: avg,
          );
        }(),
    ]..sort((a, b) => _compare(method, a, b));
    result.addAll(members.take(count));
  }
  result.sort((a, b) => _compare(method, a, b));
  return result;
}

/// 方式の値の強い順（凹み台は低い順）。値の無い台は最後。同点は機種名・台番号。
int _compare(
  ExploratoryMethod method,
  ExploratoryCandidate a,
  ExploratoryCandidate b,
) {
  final va = a.value, vb = b.value;
  if (va != null && vb != null && va != vb) {
    return method == ExploratoryMethod.rebound
        ? va.compareTo(vb)
        : vb.compareTo(va);
  }
  if (va != null && vb == null) return -1;
  if (va == null && vb != null) return 1;
  final byMachine = a.record.machine.compareTo(b.record.machine);
  return byMachine != 0 ? byMachine : a.record.rack.compareTo(b.record.rack);
}
