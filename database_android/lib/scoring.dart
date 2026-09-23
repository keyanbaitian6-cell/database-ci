import 'dart:math';

import 'models.dart';

// Policy, not a fitted setting/win probability model. See SCORING_POLICY.md.
const scoringVersion = '2026-09-21-v9';
const minimumReferenceRows = 20;
const shrinkGames = 1500.0;
const shrinkDays = 3.0;

/// 出玉のコンプリート上限。利用者の記録（最大持玉19,008枚で打ち止め）から採用した値で、
/// 規則の条文を確認したものではない。機種ごとの上限の違いも見ていない。
const completeHold = 19000.0;
const maxGamesScore = 0.0;
const maxHoldScore = 20.0;
const maxHitsScore = 60.0;
const maxPositiveScore = 10.0;
const maxRetentionScore = 10.0;

double? spinScore(int games) => games <= 0 ? null : 0.0;

double percentile(double value, List<double> values) =>
    (values.where((v) => v < value).length +
        0.5 * values.where((v) => v == value).length) /
    values.length;

/// 店舗・機種ごとに仕分けた記録。比較相手は必ず同じ店舗・同じ機種なので、
/// 1台ごとに全件を見に行かずに済む（記録が増えても遅くなりにくい）。
///
/// 仕分けた結果は、渡された一覧そのものに紐づけて覚えておく。一覧は保存の
/// たびに作り直されるので、新しい一覧なら仕分けも作り直される。件数が変わった
/// ときも作り直す（一覧をその場で書き換えた場合への備え）。
final Expando<({int length, Map<String, List<SlotRecord>> byMachine})>
_poolIndex = Expando('comparisonPoolIndex');

Map<String, List<SlotRecord>> _byMachine(List<SlotRecord> all) {
  final cached = _poolIndex[all];
  if (cached != null && cached.length == all.length) return cached.byMachine;
  final byMachine = <String, List<SlotRecord>>{};
  for (final r in all) {
    byMachine.putIfAbsent('${r.store}|${r.machine}', () => []).add(r);
  }
  _poolIndex[all] = (length: all.length, byMachine: byMachine);
  return byMachine;
}

List<SlotRecord> comparisonPool(SlotRecord row, List<SlotRecord> all) {
  // 日付は必ず 'YYYY-MM-DD' なので、文字列の大小がそのまま日付の前後になる。
  // 比較のたびに日付を解析すると、台数の二乗だけ解析が走って重くなる
  // （PC版 core.py の comparison_pool も同じ文字列比較）。
  final first = DateTime.parse(row.day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final target = max(500, row.games);
  final lowest = max(500, target / 2);
  final highest = target * 2;
  final sameMachine = _byMachine(all)['${row.store}|${row.machine}'];
  if (sameMachine == null) return const [];
  return sameMachine
      .where(
        (r) =>
            r.day.compareTo(first) >= 0 &&
            r.day.compareTo(row.day) < 0 &&
            r.games >= lowest &&
            r.games <= highest,
      )
      .toList();
}

double? adjustedRank(
  double? value,
  List<SlotRecord> refs,
  double Function(SlotRecord) field,
  double maximum,
  int games,
) {
  if (value == null || refs.isEmpty) return null;
  final n = refs.length;
  final days = refs.map((r) => r.day).toSet().length;
  // v9: 3つの薄さの目安を掛け算ではなく相乗平均にする。掛け算では効きすぎて、
  // 実際の比較件数（中央値4台・1日）だと全項目1位でも80点に届かなかった。
  final weight = pow(
    games /
        (games + shrinkGames) *
        n /
        (n + minimumReferenceRows) *
        days /
        (days + shrinkDays),
    1 / 3,
  );
  return maximum *
      (0.5 + weight * (percentile(value, refs.map(field).toList()) - 0.5));
}

/// 枚数そのものによる持玉点。コンプリート上限で満点。
///
/// 順位と違って比較相手がいらない。上限は機械が超えられない固定の天井なので、
/// そこに到達したことは他の台の出来に関係なく最良の結果を意味する。
/// 順位による点を引き上げるためだけに使い、下げることはない。
double? absoluteHoldScore(int? maxHold) =>
    maxHold == null ? null : maxHoldScore * min(1.0, maxHold / completeHold);

ScoreResult scoreRecord(SlotRecord row, List<SlotRecord> all) {
  if (row.games <= 0 || row.bb < 0 || row.rb < 0 || (row.maxHold ?? 0) < 0) {
    return ScoreResult(
      provisional: true,
      referenceCount: 0,
      reasons: [row.games <= 0 ? '未稼働・回転数なし' : '負の数値を確認してください'],
    );
  }
  final refs = comparisonPool(row, all);
  final hitRefs = refs.where((r) => r.bb >= 0 && r.rb >= 0).toList();
  final holdRefs = refs
      .where((r) => r.maxHold != null && r.maxHold! >= 0)
      .toList();
  double rateOf(SlotRecord r) => (r.bb + r.rb) / r.games;
  final hit = adjustedRank(
    rateOf(row),
    hitRefs,
    rateOf,
    maxHitsScore,
    row.games,
  );
  final rankedHold = adjustedRank(
    row.maxHold?.toDouble(),
    holdRefs,
    (r) => r.maxHold!.toDouble(),
    maxHoldScore,
    row.games,
  );
  // 枚数そのものによる点が上回るときだけ、そちらを採る（下げることはない）。
  // 比較相手がいない場合は従来どおり欠測扱いのまま（中立10点で補完）。
  final hold = rankedHold == null
      ? null
      : max(rankedHold, absoluteHoldScore(row.maxHold)!);
  final days = hitRefs.map((r) => r.day).toSet().length;
  final holdDays = holdRefs.map((r) => r.day).toSet().length;
  final reasons = <String>[];
  if (hit == null) reasons.add('当たり頻度の比較データ不足：中立30点で補完');
  if (hold == null) reasons.add('最大持玉の比較データ不足：中立10点で補完');
  double? positive, retention;
  final graph = row.graph;
  if (graph == null) {
    reasons.add('グラフ未取得：中立10点で補完');
  } else if (![
    graph.baselineY,
    graph.peakY,
    graph.endY,
  ].every((v) => v.isFinite)) {
    reasons.add('グラフ解析保留：中立10点で補完');
  } else {
    final peak = max(0.0, graph.baselineY - graph.peakY);
    final end = graph.baselineY - graph.endY;
    if (end != 0 && end.abs() <= 1) {
      reasons.add('グラフ終点がゼロ線付近：中立点で補完');
    } else {
      positive = end > 0 ? maxPositiveScore : 0;
      retention = peak == 0 ? 0 : maxRetentionScore * (end / peak).clamp(0, 1);
    }
  }
  final parts = [(hit, 60), (hold, 20), (positive, 10), (retention, 10)];
  final missing = parts
      .where((p) => p.$1 == null)
      .fold<int>(0, (v, p) => v + p.$2);
  final observed = parts.fold<double>(0, (v, p) => v + (p.$1 ?? 0));
  double rounded(double v) => (v * 10).round() / 10;
  final provisional =
      missing > 0 ||
      row.games < shrinkGames ||
      min(hitRefs.length, holdRefs.length) < minimumReferenceRows ||
      min(days, holdDays) < shrinkDays;
  if (provisional) reasons.add('少数データ・欠測を含む暫定評価');
  if (positive == 0) reasons.add('グラフ終点がゼロ線以下');
  reasons.add(
    '比較${hitRefs.length}件/$days日・持玉比較${holdRefs.length}件・観測${row.games}G',
  );
  if (missing > 0) {
    reasons.add(
      '評価可能配点${100 - missing}/100・欠測項目による幅${rounded(observed).toStringAsFixed(1)}〜${rounded(observed + missing).toStringAsFixed(1)}（信頼区間ではありません）',
    );
  }
  return ScoreResult(
    games: 0,
    maxHold: hold,
    hits: hit,
    positive: positive,
    retention: retention,
    total: rounded(observed + missing / 2),
    provisional: provisional,
    referenceCount: hitRefs.length,
    referenceDays: days,
    holdReferenceCount: holdRefs.length,
    coverage: 100 - missing,
    missingLow: rounded(observed),
    missingHigh: rounded(observed + missing),
    reasons: reasons,
  );
}
