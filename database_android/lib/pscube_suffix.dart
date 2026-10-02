import 'models.dart';
import 'scoring.dart';

const pscubeSuffixes = [0, 1, 2, 3, 5, 6, 7, 8];

enum PscubeSuffixPeriod {
  day('選択日', 1),
  week('過去7日', 7),
  month('過去30日', 30),
  saved('選択日までの保存分', null);

  const PscubeSuffixPeriod(this.label, this.days);
  final String label;
  final int? days;
}

enum PscubeSuffixType {
  all('全機種'),
  normal('ノーマルタイプ'),
  other('それ以外');

  const PscubeSuffixType(this.label);
  final String label;
}

/// One record is a rack on one day. Repeated days are not additional racks.
class PscubeSuffixSummary {
  PscubeSuffixSummary(this.suffix, List<(SlotRecord, ScoreResult)> entries)
    : entries = List.unmodifiable(entries);
  final int suffix;
  final List<(SlotRecord, ScoreResult)> entries;
  int get records => entries.length;
  int get racks => entries.map((e) => e.$1.rack).toSet().length;
  int get days => entries.map((e) => e.$1.day).toSet().length;
  int get games => entries.fold(0, (n, e) => n + e.$1.games);
  int get bb => entries.fold(0, (n, e) => n + e.$1.bb);
  int get rb => entries.fold(0, (n, e) => n + e.$1.rb);
  int get atArt => entries.fold(0, (n, e) => n + e.$1.atArt);
  double? get averageGames => records == 0 ? null : games / records;
  double? get averageMy {
    final values = entries.map((e) => e.$1.my).whereType<int>().toList();
    return values.isEmpty
        ? null
        : values.reduce((a, b) => a + b) / values.length;
  }

  int get scored => entries.where((e) => e.$2.total != null).length;
  int get provisional =>
      entries.where((e) => e.$2.total != null && e.$2.provisional).length;
  double? get averageScore {
    final values = entries.map((e) => e.$2.total).whereType<double>().toList();
    return values.isEmpty
        ? null
        : values.reduce((a, b) => a + b) / values.length;
  }

  int get graphs => entries.where((e) => e.$1.graph != null).length;
  int get positiveGraphs => entries.where((e) {
    final g = e.$1.graph;
    return g != null && g.baselineY - g.endY > 1;
  }).length;
  double? get positivePercent =>
      graphs == 0 ? null : positiveGraphs * 100 / graphs;
}

class PscubeSuffixReport {
  const PscubeSuffixReport({
    required this.summaries,
    required this.excludedInvalid,
    required this.excludedSuffix,
    required this.start,
    required this.end,
  });
  final List<PscubeSuffixSummary> summaries;
  final int excludedInvalid, excludedSuffix;
  final String? start;
  final String end;
  int get records => summaries.fold(0, (n, s) => n + s.records);
  int get racks => summaries.fold(0, (n, s) => n + s.racks);
  int get days =>
      summaries.expand((s) => s.entries.map((e) => e.$1.day)).toSet().length;
}

PscubeSuffixReport summarizePscubeSuffixes(
  List<SlotRecord> all, {
  required String store,
  required String day,
  PscubeSuffixPeriod period = PscubeSuffixPeriod.day,
  PscubeSuffixType type = PscubeSuffixType.all,
}) {
  final start = period.days == null
      ? null
      : DateTime.parse('${day}T00:00:00Z')
            .subtract(Duration(days: period.days! - 1))
            .toIso8601String()
            .substring(0, 10);
  final grouped = {
    for (final suffix in pscubeSuffixes) suffix: <(SlotRecord, ScoreResult)>[],
  };
  var invalid = 0, otherSuffix = 0;
  for (final r in all) {
    if (!r.isPscube ||
        r.store != store ||
        r.day.compareTo(day) > 0 ||
        (start != null && r.day.compareTo(start) < 0)) {
      continue;
    }
    if (type == PscubeSuffixType.normal && !r.pscubeNormal ||
        type == PscubeSuffixType.other && r.pscubeNormal) {
      continue;
    }
    if (hasImplausibleNumbers(r) ||
        r.games < 0 ||
        r.bb < 0 ||
        r.rb < 0 ||
        r.atArt < 0 ||
        (r.my ?? 0) < 0) {
      invalid++;
      continue;
    }
    final entries = grouped[r.rack % 10];
    if (entries == null) {
      otherSuffix++;
      continue;
    }
    entries.add((r, scoreRecord(r, all)));
  }
  for (final entries in grouped.values) {
    entries.sort((a, b) {
      final byDay = b.$1.day.compareTo(a.$1.day);
      return byDay != 0 ? byDay : a.$1.rack.compareTo(b.$1.rack);
    });
  }
  return PscubeSuffixReport(
    summaries: [
      for (final suffix in pscubeSuffixes)
        PscubeSuffixSummary(suffix, grouped[suffix]!),
    ],
    excludedInvalid: invalid,
    excludedSuffix: otherSuffix,
    start: start,
    end: day,
  );
}
