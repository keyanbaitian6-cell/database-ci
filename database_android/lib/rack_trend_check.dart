import 'data_checks.dart' show rackTrend;
import 'day_score_check.dart' show scoreText;
import 'models.dart';
import 'scoring.dart';
import 'viewer_data.dart';

/// 段階B3（VIEWER_DAY_STORE.md、2026-11-25 利用者「切り替えとB3進めて」）：台の詳細に出す「この台の推移」
/// （[rackTrend]：同じ店・同じ台番号・同じ機種の、その日までの直近7記録と各日の点数）を、日別キャッシュから
/// 1日ずつ作り、今の計算（全記録から [rackTrend]）と、記録と点数の全項目まで比べる。画面は変えない（照合だけ）。
///
/// 推移は期間を区切らない（同じ機種の記録を過去へいくらでもたどる）ので、日別キャッシュは全日を古い日から読む。
/// 持つのは、対象の台の機種（店・機種）の「その日と前30暦日」の記録（採点の窓。[comparisonPool]・
/// [newMachinePeers] は同じ店・同じ機種の30日前〜その日しか見ない）と、対象の台ごとの直近7記録と点数だけで、
/// 全日の記録は同時に持たない。
class RackTrendCheck {
  RackTrendCheck(this.records, Iterable<SlotRecord> targets)
    : targets = targets.toList() {
    for (final t in this.targets) {
      _machines.add('${t.store}|${t.machine}');
      (_byRack['${t.store}|${t.rack}|${t.machine}'] ??= []).add(t);
    }
  }

  /// 今の計算に使う全記録（表示中の `ViewerData.records`）。
  final List<SlotRecord> records;

  /// 推移を比べる台（表示中の記録）。
  final List<SlotRecord> targets;

  final Set<String> _machines = {};
  final Map<String, List<SlotRecord>> _byRack = {};
  final Map<String, List<(SlotRecord, ScoreResult)>> _trends = {};
  List<SlotRecord> _window = const [];
  int compared = 0, mismatched = 0;
  final List<Map<String, String>> examples = [];

  static String _key(SlotRecord t) =>
      '${t.store}|${t.day}|${t.rack}|${t.machine}';

  /// 日別キャッシュの1日分の記録（古い日から順に渡す）。
  void addDay(Iterable<Object?> rows) {
    final today = [
      for (final r in ViewerData.recordsOfRows(rows))
        if (_machines.contains('${r.store}|${r.machine}')) r,
    ];
    if (today.isEmpty) return;
    final day = today.first.day;
    final first = DateTime.parse(day)
        .subtract(const Duration(days: 30))
        .toIso8601String()
        .substring(0, 10);
    // 採点の索引（scoring.dart の _byMachine）は一覧そのものに紐づくので、日ごとに新しい一覧を作る。
    _window = [
      for (final r in _window)
        if (r.day.compareTo(first) >= 0) r,
      ...today,
    ];
    for (final r in today) {
      for (final t
          in _byRack['${r.store}|${r.rack}|${r.machine}'] ??
              const <SlotRecord>[]) {
        if (r.day.compareTo(t.day) > 0) continue;
        final trend = _trends[_key(t)] ??= [];
        trend.add((r, scoreRecord(r, _window)));
        if (trend.length > 7) trend.removeAt(0);
      }
    }
  }

  static String _entry((SlotRecord, ScoreResult) e) =>
      '${e.$1.day} ${e.$1.games}G ${e.$1.bb}/${e.$1.rb}［${scoreText(e.$2)}］';

  /// 照合の結果：`status`（`match`・`mismatch`）、`racks`（比べた台）、`entries`（比べた推移の行の数）、
  /// `mismatched`（一致しない台の数）、`examples`（最大3件）。
  Map<String, Object?> finish() {
    var entries = 0;
    for (final t in targets) {
      compared++;
      final old = rackTrend(t, records);
      final next = (_trends[_key(t)] ?? const []).reversed.toList();
      entries += old.length;
      String? diff;
      if (old.length != next.length) {
        diff = '件数';
      } else {
        for (var i = 0; i < old.length; i++) {
          if (old[i].$1.key != next[i].$1.key ||
              old[i].$1.games != next[i].$1.games ||
              old[i].$1.bb != next[i].$1.bb ||
              old[i].$1.rb != next[i].$1.rb ||
              old[i].$1.maxHold != next[i].$1.maxHold ||
              old[i].$1.netValue != next[i].$1.netValue ||
              scoreText(old[i].$2) != scoreText(next[i].$2)) {
            diff = '$i';
            break;
          }
        }
      }
      if (diff == null) continue;
      mismatched++;
      if (examples.length < 3) {
        final at = int.tryParse(diff);
        examples.add({
          'store': t.store,
          'day': t.day,
          'machine': t.machine,
          'rack': '${t.rack}',
          'old': at == null ? '${old.length}件' : _entry(old[at]),
          'next': at == null ? '${next.length}件' : _entry(next[at]),
        });
      }
    }
    return {
      'status': mismatched == 0 ? 'match' : 'mismatch',
      'racks': compared,
      'entries': entries,
      'mismatched': mismatched,
      'examples': examples,
    };
  }
}

/// 1回の照合で推移を比べる台：[store] のいちばん新しい日の台を台番号の順に並べ、前回の最後の台番号 [after] より
/// 大きい台から [count] 台（端まで行ったら小さい側へ戻る）。戻り値の `next`（最後に選んだ台番号）を次の [after]
/// として覚えると、更新のたびにその日の全台を一巡する。
({List<SlotRecord> targets, int? next}) pickTrendRacks(
  Iterable<SlotRecord> records,
  String store, {
  int? after,
  int count = 30,
}) {
  String? latest;
  for (final r in records) {
    if (r.store == store && (latest == null || r.day.compareTo(latest) > 0)) {
      latest = r.day;
    }
  }
  if (latest == null) return (targets: const [], next: null);
  final day = [
    for (final r in records)
      if (r.store == store && r.day == latest) r,
  ]..sort((a, b) => a.rack.compareTo(b.rack));
  if (day.length <= count) return (targets: day, next: null);
  var start = after == null ? 0 : day.indexWhere((r) => r.rack > after);
  if (start < 0) start = 0;
  final picked = [
    for (var i = 0; i < count; i++) day[(start + i) % day.length],
  ];
  return (targets: picked, next: picked.last.rack);
}
