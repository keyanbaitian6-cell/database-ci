import 'dart:math';

import 'models.dart';

// Policy, not a fitted setting/win probability model. See SCORING_POLICY.md.
const scoringVersion = '2026-09-29-v12';

/// 画面に出す点数で、新台（その店でその機種の記録が評価日の30日前〜前日に1件も無い）を同じ日の同じ機種の
/// ほかの台と比べたときの版（2026-11-03 利用者「新台については比較せず出しても良いのでは？」→「同じ日の他の台と
/// 比べる」）。翌日候補・固定済みの検証は [scoringVersion]（v12）のまま（[scoreRecord] の sameDayForNew を使わない）。
/// PC版 core.py の NEW_MACHINE_SCORING_VERSION と同じ。
const newMachineScoringVersion = '2026-11-03-v13';
const minimumReferenceRows = 20;
const shrinkGames = 1500.0;
const shrinkDays = 3.0;

/// 当日この回転数以下の台は採点しない（利用者の指定、2026-09-25）。
const minScoredGames = 500;

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
/// 仕分けた結果は、渡された一覧そのものに紐づけて覚えておく。アプリの一覧
/// （`AppController.records`）は変更できない一覧で、保存のたびに新しく
/// 作られるので、新しい一覧なら仕分けも作り直される。変更できる一覧（テスト
/// など）をその場で書き換えた場合への備えとして、件数が変わったときも作り直す。
final Expando<({int length, Map<String, List<SlotRecord>> byMachine})>
_poolIndex = Expando('comparisonPoolIndex');

/// [all] のうち、[store] の [machine] の記録（[all] の中の順）。
List<SlotRecord> machineHistory(
  List<SlotRecord> all,
  String store,
  String machine,
) => _byMachine(all)['$store|$machine'] ?? const [];

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

/// 採点・翌日候補の比較から外すアナスロ補完。P’s CUBEの店だけ（MY・信号の対応が未確認）。
/// メルヘン（幸町）の補完は通常の記録として使う（2026-10-16 利用者決定、PC版 core.py と同じ）。
bool isExcludedSupplement(SlotRecord r) =>
    r.extra['source_site'] == 'anaslo' && isPscubeStore(r.store);

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
            r.games <= highest &&
            !hasImplausibleNumbers(r) &&
            !isExcludedSupplement(r),
      )
      .toList();
}

/// 新台のときだけ、同じ日の同じ機種のほかの台（回転数の幅・数値異常の除外は [comparisonPool] と同じ）。
/// 新台＝同じ店・同じ機種の、評価日の30日前〜前日の回転数のある記録が1件も無い。過去の記録があるのに回転数の幅で
/// 比較相手が0件になった台は新台ではない（v12のまま中立で補う）。PC版 core.py の new_machine_peers と同じ。
List<SlotRecord> newMachinePeers(SlotRecord row, List<SlotRecord> all) {
  final first = DateTime.parse(row.day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final sameMachine = _byMachine(all)['${row.store}|${row.machine}'];
  if (sameMachine == null) return const [];
  if (sameMachine.any(
    (r) =>
        r.day.compareTo(first) >= 0 &&
        r.day.compareTo(row.day) < 0 &&
        r.games > 0,
  )) {
    return const [];
  }
  final target = max(500, row.games);
  final lowest = max(500, target / 2);
  final highest = target * 2;
  return sameMachine
      .where(
        (r) =>
            r.day == row.day &&
            r.rack != row.rack &&
            r.games >= lowest &&
            r.games <= highest &&
            !hasImplausibleNumbers(r) &&
            !isExcludedSupplement(r),
      )
      .toList();
}

/// [scoreRecord] で使う比較相手と、新台の扱いにしたときの台数（0＝今までどおり）。
(List<SlotRecord>, int) _scoringPool(
  SlotRecord row,
  List<SlotRecord> all,
  bool sameDayForNew,
) {
  final refs = comparisonPool(row, all);
  if (!sameDayForNew || refs.isNotEmpty) return (refs, 0);
  final peers = newMachinePeers(row, all);
  return peers.isEmpty ? (refs, 0) : (peers, peers.length);
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

/// [sameDayForNew]：画面に出す点数だけ true。新台は同じ日の同じ機種のほかの台と比べる（[newMachineScoringVersion]）。
ScoreResult scoreRecord(
  SlotRecord row,
  List<SlotRecord> all, {
  bool sameDayForNew = false,
}) {
  if (row.isPscube) return _scorePscube(row, all, sameDayForNew);
  if (row.games <= 0 || row.bb < 0 || row.rb < 0 || (row.maxHold ?? 0) < 0) {
    return ScoreResult(
      provisional: true,
      referenceCount: 0,
      reasons: [row.games <= 0 ? '未稼働・回転数なし' : '負の数値を確認してください'],
    );
  }
  if (hasImplausibleNumbers(row)) {
    return ScoreResult(
      games: 0,
      provisional: true,
      referenceCount: 0,
      reasons: ['サイトの数値が異常なため採点なし（88888888などの表示）'],
    );
  }
  if (row.games <= minScoredGames) {
    // 回転数の項目（常に0点）はPC版と同じく出す。合計は出さない。
    return ScoreResult(
      games: 0,
      provisional: true,
      referenceCount: 0,
      reasons: ['${minScoredGames}G以下のため採点なし'],
    );
  }
  final (refs, peers) = _scoringPool(row, all, sameDayForNew);
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
  final reasons = <String>[
    if (peers > 0) '新台（過去30日の記録なし）：同じ日の同じ機種$peers台と比べた点',
  ];
  if (hit == null) reasons.add('当たり頻度の比較データ不足：中立30点で補完');
  if (hold == null) reasons.add('最大持玉の比較データ不足：中立10点で補完');
  double? positive, retention;
  final graph = row.graph;
  if (row.graphNotNeeded) {
    // v12：大当たり0回の台はグラフを取らない。取った場合とほぼ同じ結果
    // （終点はゼロ以下、最高はゼロ付近）になるので、終点・維持とも0点。
    positive = 0;
    retention = 0;
    reasons.add('大当たり0回でグラフ省略：終点・維持は0点');
  } else if (graph == null) {
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
  if (provisional) reasons.add('少数データ・欠測を含む評価');
  if (positive == 0 && graph != null) reasons.add('グラフ終点がゼロ線以下');
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

/// The already published P's CUBE policy, presented by the shared viewer.
/// The normal profile uses BIG/REG; other machines use MY and the curve.
ScoreResult _scorePscube(
  SlotRecord row,
  List<SlotRecord> all,
  bool sameDayForNew,
) {
  if (row.extra['source_site'] == 'anaslo') {
    return ScoreResult(
      games: null,
      provisional: true,
      referenceCount: 0,
      reasons: const ['アナスロ補完履歴：MY・信号の対応未確認のため採点対象外'],
    );
  }
  if (row.games <= 0 ||
      hasImplausibleNumbers(row) ||
      row.games <= minScoredGames) {
    return ScoreResult(
      games: row.games <= 0 ? null : 0,
      provisional: true,
      referenceCount: 0,
      reasons: [
        row.games <= 0
            ? '未稼働・回転数なし'
            : hasImplausibleNumbers(row)
            ? 'サイトの数値が異常なため採点なし（88888888などの表示）'
            : '${minScoredGames}G以下のため採点なし',
      ],
    );
  }
  final outputOnly = row.pscubeOutputProfile;
  final hitMax = outputOnly ? 0 : 60;
  final holdMax = outputOnly ? 50 : 20;
  final endMax = outputOnly ? 25 : 10;
  final retentionMax = outputOnly ? 25 : 10;
  final (refs, peers) = _scoringPool(row, all, sameDayForNew);
  final hitRefs = refs.where((r) => r.bb >= 0 && r.rb >= 0).toList();
  final holdRefs = refs.where((r) => r.my != null && r.my! >= 0).toList();
  final days = hitRefs.map((r) => r.day).toSet().length;
  final holdDays = holdRefs.map((r) => r.day).toSet().length;
  double rateOf(SlotRecord r) => (r.bb + r.rb) / r.games;
  final hit = hitMax == 0
      ? null
      : adjustedRank(rateOf(row), hitRefs, rateOf, hitMax.toDouble(), row.games);
  final rowMy = row.my != null && row.my! >= 0 ? row.my!.toDouble() : null;
  final ranked = adjustedRank(
    rowMy,
    holdRefs,
    (r) => r.my!.toDouble(),
    holdMax.toDouble(),
    row.games,
  );
  final absolute = row.extra['rate'] == '20' && rowMy != null
      ? holdMax * min(1.0, rowMy / completeHold)
      : 0.0;
  final hold = ranked == null ? null : max(ranked, absolute).toDouble();
  final reasons = <String>[
    if (peers > 0) '新台（過去30日の記録なし）：同じ日の同じ機種$peers台と比べた点',
  ];
  if (hitMax > 0 && hit == null)
    reasons.add('当たり頻度の比較データ不足：中立${hitMax ~/ 2}点で補完');
  if (hold == null) reasons.add('MYの比較データ不足：中立${holdMax ~/ 2}点で補完');
  double? positive, retention;
  final graph = row.graph;
  if (row.graphNotNeeded) {
    positive = 0;
    retention = 0;
    reasons.add('当たり0回でグラフ省略：終点・維持は0点');
  } else if (graph == null) {
    reasons.add('グラフ未取得：中立${(endMax + retentionMax) ~/ 2}点で補完');
  } else {
    final peak = max(0.0, graph.baselineY - graph.peakY);
    final end = graph.baselineY - graph.endY;
    if (end != 0 && end.abs() <= 1) {
      reasons.add('グラフ終点がゼロ線付近：中立点で補完');
    } else {
      positive = end > 0 ? endMax.toDouble() : 0;
      retention = peak == 0 ? 0 : retentionMax * (end / peak).clamp(0, 1);
      if (positive == 0) reasons.add('グラフ終点がゼロ線以下');
    }
  }
  final parts = [
    if (hitMax > 0) (hit, hitMax),
    (hold, holdMax),
    (positive, endMax),
    (retention, retentionMax),
  ];
  final missing = parts
      .where((p) => p.$1 == null)
      .fold<int>(0, (sum, p) => sum + p.$2);
  final observed = parts.fold<double>(0, (sum, p) => sum + (p.$1 ?? 0));
  double rounded(double v) => (v * 10).round() / 10;
  final refCount = outputOnly
      ? holdRefs.length
      : min(hitRefs.length, holdRefs.length);
  final refDays = outputOnly ? holdDays : min(days, holdDays);
  final provisional =
      missing > 0 ||
      row.games < shrinkGames ||
      refCount < minimumReferenceRows ||
      refDays < shrinkDays;
  if (provisional) reasons.add('少数データ・欠測を含む評価');
  if (holdRefs.length == hitRefs.length && holdRefs.length == refs.length) {
    reasons.add('比較${refs.length}件/$days日・観測${row.games}G');
  } else if (outputOnly) {
    reasons.add('MY比較${holdRefs.length}件/$holdDays日・観測${row.games}G');
  } else {
    reasons.add(
      '比較${hitRefs.length}件/$days日・MY比較${holdRefs.length}件・観測${row.games}G',
    );
  }
  if (missing > 0)
    reasons.add(
      '評価可能配点${100 - missing}/100・欠測による幅'
      '${rounded(observed).toStringAsFixed(1)}〜${rounded(observed + missing).toStringAsFixed(1)}（信頼区間ではありません）',
    );
  return ScoreResult(
    games: 0,
    maxHold: hold,
    hits: hit,
    positive: positive,
    retention: retention,
    total: rounded(observed + missing / 2),
    provisional: provisional,
    referenceCount: outputOnly ? holdRefs.length : hitRefs.length,
    referenceDays: outputOnly ? holdDays : days,
    holdReferenceCount: holdRefs.length,
    coverage: 100 - missing,
    missingLow: rounded(observed),
    missingHigh: rounded(observed + missing),
    reasons: reasons,
  );
}
