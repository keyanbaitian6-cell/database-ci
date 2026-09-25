import 'models.dart';
import 'scoring.dart';

/// Racks of one machine whose games/BIG/REG are all identical (games > 0).
///
/// Real racks essentially never agree on all three, so this is the
/// fingerprint of a capture saved under the wrong rack number (the PC app's
/// `suspicious_duplicates` does the same). Returns machine -> rack groups.
List<(String machine, List<int> racks)> suspiciousDuplicates(
  Iterable<SlotRecord> rows,
) {
  final groups = <String, List<int>>{};
  for (final r in rows) {
    if (r.games <= 0) continue;
    groups
        .putIfAbsent(
          '${r.machine}\u0000${r.games}\u0000${r.bb}\u0000${r.rb}',
          () => [],
        )
        .add(r.rack);
  }
  final result = <(String, List<int>)>[];
  for (final entry in groups.entries) {
    if (entry.value.length > 1) {
      result.add((entry.key.split('\u0000').first, entry.value..sort()));
    }
  }
  result.sort((a, b) => a.$1.compareTo(b.$1));
  return result;
}

/// Warning text for the racks that look duplicated (only those including
/// [rack] when given), or null when nothing looks off.
String? duplicateWarning(Iterable<SlotRecord> machineRows, {int? rack}) {
  final groups = suspiciousDuplicates(machineRows)
      .where((g) => rack == null || g.$2.contains(rack))
      .toList();
  if (groups.isEmpty) return null;
  final racks = groups.map((g) => '${g.$2.join('・')}番台').join('、');
  return '⚠ $racksの数値（回転・BIG・REG）が完全に同じです。台番号のずれがないか確認してください。';
}

/// Recent days of the SAME rack running the SAME machine, newest first,
/// each with its score (the PC app's `rack_trend`). A machine swap on that
/// rack ends the history, since scores only compare within one machine.
List<(SlotRecord, ScoreResult)> rackTrend(
  SlotRecord record,
  List<SlotRecord> all, {
  int limit = 7,
}) {
  final rows =
      all
          .where(
            (r) =>
                r.store == record.store &&
                r.rack == record.rack &&
                r.machine == record.machine &&
                r.day.compareTo(record.day) <= 0,
          )
          .toList()
        ..sort((a, b) => b.day.compareTo(a.day));
  return [for (final r in rows.take(limit)) (r, scoreRecord(r, all))];
}

/// How much data stands behind a rack's hit frequency (games played).
String reliabilityLabel(int games) =>
    games >= 3500 ? '多' : (games >= 1500 ? '中' : '少');

/// "取得 09/18 23:48" (+ a warning when read well before closing), or ''.
String capturedNote(SlotRecord record) {
  // 時差付き（PC版の `+09:00` 等）は世界標準時で読まれるので、端末の時刻に
  // 直してから表示する。直さないと23:30の取得が14:30の「途中経過」に見える。
  final stamp = DateTime.tryParse(record.capturedAt ?? '')?.toLocal();
  if (stamp == null) return '';
  String two(int v) => v.toString().padLeft(2, '0');
  final text =
      '取得 ${two(stamp.month)}/${two(stamp.day)} ${two(stamp.hour)}:${two(stamp.minute)}';
  return stamp.hour < 20 ? '$text（早めの取得：回転数は途中経過）' : text;
}

/// Historical hit-frequency tendency for the provisional candidate view.
///
/// This is not a validated forecast, setting probability, or part of the
/// daily score. It only reads records available on or before [record.day].
({int days, double? index, String confidence}) nextDayIndex(
  SlotRecord record,
  List<SlotRecord> all, {
  int maxDays = 10,
  int shrinkDays = 5,
}) {
  // 日付は YYYY-MM-DD なので文字列のまま比べる（台ごと・記録ごとに日付へ
  // 変換し直すと、結果タブで全機種の候補を出すときに重い）。
  final first = DateTime.parse(record.day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final rows = all
      .where(
        (r) =>
            r.store == record.store &&
            r.machine == record.machine &&
            r.day.compareTo(first) >= 0 &&
            r.day.compareTo(record.day) <= 0 &&
            r.games >= 500 &&
            r.bb >= 0 &&
            r.rb >= 0,
      )
      .toList();
  final days =
      rows
          .where((r) => r.rack == record.rack)
          .map((r) => r.day)
          .toSet()
          .toList()
        ..sort((a, b) => b.compareTo(a));
  final gaps = <double>[];
  for (final day in days.take(maxDays)) {
    final mine = rows.firstWhere((r) => r.day == day && r.rack == record.rack);
    final peers = rows
        .where(
          (r) =>
              r.day == day &&
              r.games >= mine.games / 2 &&
              r.games <= mine.games * 2,
        )
        .toList();
    if (peers.length < 3) continue;
    final ranks = peers.map((r) => (r.bb + r.rb) / r.games).toList();
    final rank = percentile((mine.bb + mine.rb) / mine.games, ranks);
    gaps.add((100 * rank - 50) * mine.games / (mine.games + shrinkGames));
  }
  final n = gaps.length;
  if (n < 3) return (days: n, index: null, confidence: 'データ不足');
  return (
    days: n,
    index: double.parse(
      (50 + gaps.reduce((a, b) => a + b) / (n + shrinkDays)).toStringAsFixed(1),
    ),
    confidence: n < 7 ? '少' : '中',
  );
}

typedef ProvisionalCandidate = ({
  SlotRecord record,
  double index,
  int days,
  String confidence,
});

/// Candidate list for the day after the selected date, clearly marked as a
/// trial display. Each rack's own hit-frequency history is the only input.
/// Four eligible racks are required before showing the best quarter, and the
/// result never feeds back into [scoreRecord].
({int total, int eligible, List<ProvisionalCandidate> candidates})
provisionalNextDayCandidates(List<SlotRecord> rows, List<SlotRecord> all) {
  final eligible = <ProvisionalCandidate>[];
  for (final record in rows) {
    final tendency = nextDayIndex(record, all);
    if (tendency.index != null) {
      eligible.add((
        record: record,
        index: tendency.index!,
        days: tendency.days,
        confidence: tendency.confidence,
      ));
    }
  }
  eligible.sort((a, b) {
    final byIndex = b.index.compareTo(a.index);
    return byIndex != 0 ? byIndex : a.record.rack.compareTo(b.record.rack);
  });
  if (eligible.length < 4) {
    return (
      total: rows.length,
      eligible: eligible.length,
      candidates: const [],
    );
  }
  final count = (eligible.length * .25).ceil();
  return (
    total: rows.length,
    eligible: eligible.length,
    candidates: eligible.take(count).toList(),
  );
}

/// The latest [count] days of graphs for this rack (same machine), oldest
/// first. Empty unless at least [count] days have a saved graph: the strip
/// only makes sense as a multi-day view.
List<SlotRecord> slumpDays(
  SlotRecord record,
  List<SlotRecord> all, {
  int count = 5,
}) {
  final rows =
      all
          .where(
            (r) =>
                r.store == record.store &&
                r.rack == record.rack &&
                r.machine == record.machine &&
                r.day.compareTo(record.day) <= 0 &&
                r.graph != null,
          )
          .toList()
        ..sort((a, b) => b.day.compareTo(a.day));
  return rows.length < count ? [] : rows.take(count).toList().reversed.toList();
}

/// まとめて削除の対象：[day] の記録。[store] を指定すればその店舗だけ、さらに
/// [machine] を指定すればその機種だけ。機種だけの指定は（別店舗の同名機種を
/// 巻き込むので）受け付けない。PC版 `Store.delete_group` と同じ範囲。
List<SlotRecord> recordsInGroup(
  Iterable<SlotRecord> records, {
  required String day,
  String? store,
  String? machine,
}) {
  if (machine != null && store == null) {
    throw ArgumentError('機種ごとに消すときは店舗も指定してください。');
  }
  return [
    for (final r in records)
      if (r.day == day &&
          (store == null || r.store == store) &&
          (machine == null || r.machine == machine))
        r,
  ];
}
