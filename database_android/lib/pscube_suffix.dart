import 'models.dart';
import 'scoring.dart';

const pscubeSuffixes = [0, 1, 2, 3, 5, 6, 7, 8];

/// メルヘンの末尾（台番号に4・9もあるので0〜9）。
const meruhenSuffixes = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

/// 末尾別データまとめを出すメルヘンの店（2026-10-12 利用者「幸町にもつくってもらうだけでいい」。
/// P’s CUBEの店はすべて）。閲覧ページ・Android版・共有ページ（share_viewer/data.mjs の SUFFIX_STORES）で同じ。
const meruhenSuffixStores = {'saiwaichou'};
bool hasSuffixPage(String store) =>
    isPscubeStore(store) || meruhenSuffixStores.contains(store);

/// その店で集計する末尾。
List<int> suffixesFor(String store) =>
    isPscubeStore(store) ? pscubeSuffixes : meruhenSuffixes;

/// ゾロ目（台番号の下2桁が00・11・22・33・55・66・77・88、2026-10-11 利用者指定）の集計の印。
/// 末尾とは別の項目として順位・表に並べる。ゾロ目の台は末尾の集計にも入る（例：1111番台は末尾1とゾロ目）。
const pscubeZorome = 100;
const pscubeZoromeEndings = [0, 11, 22, 33, 55, 66, 77, 88];
bool isPscubeZorome(int rack) =>
    rack >= 10 && pscubeZoromeEndings.contains(rack % 100);

/// メルヘンのゾロ目：台番号に4・9もあるので、下2桁が00・11・22・…・99（44・99も入る）。
const meruhenZoromeEndings = [0, 11, 22, 33, 44, 55, 66, 77, 88, 99];

/// その店のゾロ目か。
bool isZoromeAt(String store, int rack) => isPscubeStore(store)
    ? isPscubeZorome(rack)
    : rack >= 10 && meruhenZoromeEndings.contains(rack % 100);

/// 画面に出すゾロ目の下2桁（「00・11・…」）。
String zoromeEndingsText(String store) =>
    (isPscubeStore(store) ? pscubeZoromeEndings : meruhenZoromeEndings)
        .map((n) => n.toString().padLeft(2, '0'))
        .join('・');

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
  bool get isZorome => suffix == pscubeZorome;

  /// 画面の呼び方（「末尾1」「ゾロ目」）。
  String get label => isZorome ? 'ゾロ目' : '末尾$suffix';

  /// 日別の首位の内訳で使う短い呼び方（「1」「ゾロ目」）。
  String get shortLabel => isZorome ? 'ゾロ目' : '$suffix';
  int get records => entries.length;
  int get racks => entries.map((e) => e.$1.rack).toSet().length;
  int get days => entries.map((e) => e.$1.day).toSet().length;
  int get games => entries.fold(0, (n, e) => n + e.$1.games);
  int get bb => entries.fold(0, (n, e) => n + e.$1.bb);
  int get rb => entries.fold(0, (n, e) => n + e.$1.rb);
  int get atArt => entries.fold(0, (n, e) => n + e.$1.atArt);
  double? get averageGames => records == 0 ? null : games / records;

  /// 1記録あたりの差枚（メルヘン：推定差枚、ジャグラーオンラインの差枚があればそれ。差枚の分かった記録だけ）。
  double? get averageNet {
    final values = entries.map((e) => e.$1.netValue).whereType<int>().toList();
    return values.isEmpty
        ? null
        : values.reduce((a, b) => a + b) / values.length;
  }

  int get nets => entries.where((e) => e.$1.netValue != null).length;

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

  /// 合計は末尾の分だけ（ゾロ目の台は末尾にも入っているので、足すと二重になる）。
  int get records =>
      summaries.where((s) => !s.isZorome).fold(0, (n, s) => n + s.records);
  int get racks =>
      summaries.where((s) => !s.isZorome).fold(0, (n, s) => n + s.racks);
  int get days =>
      summaries.expand((s) => s.entries.map((e) => e.$1.day)).toSet().length;

  /// Rank at the precision shown on screen so equal displayed points tie.
  List<PscubeSuffixSummary> get ranked {
    final result = summaries.where((s) => s.averageScore != null).toList();
    result.sort((a, b) {
      final score = _shownScore(b).compareTo(_shownScore(a));
      return score != 0 ? score : a.suffix.compareTo(b.suffix);
    });
    return result;
  }

  double _shownScore(PscubeSuffixSummary s) =>
      double.parse(s.averageScore!.toStringAsFixed(1));
  int rankOf(PscubeSuffixSummary summary) =>
      1 + ranked.where((s) => _shownScore(s) > _shownScore(summary)).length;
  List<PscubeSuffixSummary> get leaders =>
      ranked.where((s) => rankOf(s) == 1).toList();

  /// Reuse the existing record scores; do not score each historical day again.
  List<PscubeSuffixReport> get daily {
    final dates =
        summaries.expand((s) => s.entries.map((e) => e.$1.day)).toSet().toList()
          ..sort((a, b) => b.compareTo(a));
    return [
      for (final day in dates)
        PscubeSuffixReport(
          summaries: [
            for (final s in summaries)
              PscubeSuffixSummary(
                s.suffix,
                s.entries.where((e) => e.$1.day == day).toList(),
              ),
          ],
          excludedInvalid: 0,
          excludedSuffix: 0,
          start: day,
          end: day,
        ),
    ];
  }
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
  final pscube = isPscubeStore(store);
  final suffixes = suffixesFor(store);
  final grouped = {
    for (final suffix in suffixes) suffix: <(SlotRecord, ScoreResult)>[],
  };
  final zorome = <(SlotRecord, ScoreResult)>[];
  var invalid = 0, otherSuffix = 0;
  for (final r in all) {
    if (r.isPscube != pscube ||
        r.store != store ||
        r.day.compareTo(day) > 0 ||
        (start != null && r.day.compareTo(start) < 0)) {
      continue;
    }
    // 機種タイプ（ノーマル／それ以外）はP’s CUBEだけ。
    if (pscube && type == PscubeSuffixType.normal && !r.pscubeNormal ||
        pscube && type == PscubeSuffixType.other && r.pscubeNormal) {
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
    final entry = (r, scoreRecord(r, all));
    entries.add(entry);
    if (isZoromeAt(store, r.rack)) zorome.add(entry);
  }
  for (final entries in [...grouped.values, zorome]) {
    entries.sort((a, b) {
      final byDay = b.$1.day.compareTo(a.$1.day);
      return byDay != 0 ? byDay : a.$1.rack.compareTo(b.$1.rack);
    });
  }
  return PscubeSuffixReport(
    summaries: [
      for (final suffix in suffixes)
        PscubeSuffixSummary(suffix, grouped[suffix]!),
      PscubeSuffixSummary(pscubeZorome, zorome),
    ],
    excludedInvalid: invalid,
    excludedSuffix: otherSuffix,
    start: start,
    end: day,
  );
}
