import 'dart:math' as math;

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

/// 翌日候補（仮）の計算方式の版。保存する候補の記録（[CandidateSnapshot]）に
/// 残し、式を変えたときに新旧の成績を混ぜないようにする。式を変えたら上げる。
/// 2026-09-27：サイトの異常値（点検中の88888888など）を除外。
/// 2026-09-29：1〜3台の機種を店ごとに「バラエティ」にまとめ、店ごとの狙い方で
/// 5台選ぶ（[varietyNextDayCandidates]）。4台以上の機種の選び方は変えていない。
/// PC版 `core.NEXT_DAY_METHOD_VERSION` と同じ値。
const nextDayMethodVersion = '2026-09-30';

/// バラエティ：その日その店で1〜3台の機種（利用者の指定、2026-09-29）。
/// 今の選び方は同じ機種の台どうしで比べ、1機種で4台以上判定できる必要が
/// あるので、これらの機種は一度も候補に入らなかった。
const varietyMaxRacks = 3;

/// バラエティで「よく回った」とみなす回転数。4時間ほど打たれた台の目安で、
/// 回されるのは打ち手が良い台だと見たからだ、というプロの見方による（経験則
/// で、根拠となる数値の出典は無い）。実データ（2026-09-22〜28）でも、前日
/// この回転数以上の台は、翌日に3000G以上回ってプラスで終わる割合が約2倍
/// （約20%、それ未満の台は約9〜10%）だった。
const varietyBusyGames = 3000;

/// バラエティから候補に出す台数（1店舗・1日。利用者の指定、2026-09-29）。
const varietyPicks = 5;

/// バラエティのまとまりの名前（画面の見出し・候補の記録の機種名）。
const varietyGroupName = 'バラエティ';

/// [dayRows]（1店舗・1日）のうち、バラエティにまとめる機種の名前。
Set<String> varietyMachines(Iterable<SlotRecord> dayRows) {
  final counts = <String, int>{};
  for (final r in dayRows) {
    counts[r.machine] = (counts[r.machine] ?? 0) + 1;
  }
  return {
    for (final entry in counts.entries)
      if (entry.value <= varietyMaxRacks) entry.key,
  };
}

/// [record] の機種が、その日その店でバラエティ（1〜3台）か。[all] にその日の
/// 同じ機種の台がそろっている前提（一覧は機種ごとに全台を保存する）。
bool isVarietyRecord(SlotRecord record, List<SlotRecord> all) =>
    machineHistory(
      all,
      record.store,
      record.machine,
    ).where((r) => r.day == record.day).length <=
    varietyMaxRacks;

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
  final evidence = nextDayEvidence(
    record,
    all,
    maxDays: maxDays,
    shrinkDays: shrinkDays,
  );
  return (
    days: evidence.usedDays,
    index: evidence.index,
    confidence: evidence.usedDays < 3
        ? 'データ不足'
        : evidence.usedDays < 7
        ? '少'
        : '中',
  );
}

/// One recording day's actual contribution; unusable peer groups still occupy
/// a place in the 10-recording-day window, just as in the original formula.
class NextDayContribution {
  const NextDayContribution(
    this.day,
    this.games,
    this.peers,
    this.rank,
    this.gap,
  );
  final String day;
  final int games, peers;
  final double? rank, gap;
  String get band => rank == null
      ? '比較不足'
      : rank! >= .75
      ? '上'
      : rank! <= .25
      ? '下'
      : '中';
}

class NextDayEvidence {
  const NextDayEvidence(this.record, this.contributions, this.rawIndex);
  final SlotRecord record;
  final List<NextDayContribution> contributions;
  final double? rawIndex;
  double? get index =>
      rawIndex == null ? null : double.parse(rawIndex!.toStringAsFixed(1));
  int get usedDays => contributions.where((d) => d.gap != null).length;
  String get latestUsed =>
      contributions.where((d) => d.gap != null).firstOrNull?.day ?? '';
  NextDayContribution? get today =>
      contributions.where((d) => d.day == record.day).firstOrNull;
  bool get todayUsed => today?.gap != null;
  // A fixed descriptive screen, not a calibrated probability or a hypothesis
  // test: serial dependence, ties and selection invalidate a simple p-value.
  double get stabilityZ {
    var sum = 0.0, variance = 0.0;
    for (final d in contributions.where((d) => d.rank != null)) {
      sum += d.rank! - .5;
      variance += (d.peers * d.peers - 1) / (12 * d.peers * d.peers);
    }
    return variance == 0 ? 0 : sum / math.sqrt(variance);
  }

  String get todayText {
    final d = today;
    if (todayUsed) {
      return '選択日 ${record.games}G・${record.pscubeOutputProfile ? 'MY' : '当たり'}順位 ${d!.band}・寄与${signedContribution(d.gap!)}';
    }
    final reason = record.games < 500
        ? '500G未満'
        : hasImplausibleNumbers(record) || record.bb < 0 || record.rb < 0
        ? '数値異常'
        : d != null
        ? '回転数が近い比較相手が3台未満'
        : '使用できる記録なし';
    return '選択日の結果は指数に入っていません（$reason）';
  }

  /// [todayText] の、専門用語のあとに意味を添えた版（iPhoneの閲覧ページ用。2026-10-05、利用者
  /// 「専門用語のあとにわかりやすい意味を書いてほしい」）。数字と判定は同じ。
  String get todayTextExplained {
    final d = today;
    final what = record.pscubeOutputProfile ? 'MY' : '当たりの回数';
    if (todayUsed) {
      return '選択日（この日）：${record.games}G。'
          '${record.pscubeOutputProfile ? 'MY' : '当たり'}順位 ${d!.band}'
          '（同じ日・同じ機種で回転数が近い台の中で、$whatが'
          '${d.band == '上'
              ? '多い方から4分の1以内'
              : d.band == '下'
              ? '少ない方から4分の1以内'
              : '真ん中あたり'}）。'
          '寄与${signedContribution(d.gap!)}'
          '（この日だけで見た当たりの軽さ。0が平均で、＋なら軽い。過去の日の寄与をならしたものが「平均より」の数字）';
    }
    return '選択日（この日）の結果は、当たりの軽さ（指数）の計算に入っていません'
        '（${todayText.substring(todayText.indexOf('（') + 1)}';
  }

  String get bandsText => ['上', '中', '下']
      .map(
        (b) =>
            '$b${contributions.where((d) => d.gap != null && d.band == b).length}日',
      )
      .join('・');
}

String signedContribution(double value) =>
    '${value >= 0 ? '+' : ''}${value.toStringAsFixed(1)}';

NextDayEvidence nextDayEvidence(
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
  // 同じ店舗・機種の記録だけを見る（店舗・機種ごとの仕分けは一覧ごとに1回）。
  // 日ごとにまとめておき、1日ぶんを探すたびに全部を見直さない。
  final byDay = <String, List<SlotRecord>>{};
  for (final r in machineHistory(all, record.store, record.machine)) {
    if (r.day.compareTo(first) >= 0 &&
        r.day.compareTo(record.day) <= 0 &&
        r.games >= 500 &&
        r.bb >= 0 &&
        r.rb >= 0 &&
        !hasImplausibleNumbers(r)) {
      byDay.putIfAbsent(r.day, () => []).add(r);
    }
  }
  final days = [
    for (final entry in byDay.entries)
      if (entry.value.any((r) => r.rack == record.rack)) entry.key,
  ]..sort((a, b) => b.compareTo(a));
  final gaps = <double>[];
  final contributions = <NextDayContribution>[];
  for (final day in days.take(maxDays)) {
    final dayRows = byDay[day]!;
    final mine = dayRows.firstWhere((r) => r.rack == record.rack);
    final peers = dayRows
        .where((r) => r.games >= mine.games / 2 && r.games <= mine.games * 2)
        .toList();
    if (peers.length < 3) {
      contributions.add(
        NextDayContribution(day, mine.games, peers.length, null, null),
      );
      continue;
    }
    double metric(SlotRecord r) => record.pscubeOutputProfile
        ? (r.my ?? 0).toDouble()
        : (r.bb + r.rb) / r.games;
    final ranks = peers.map(metric).toList();
    final rank = percentile(metric(mine), ranks);
    final gap = (100 * rank - 50) * mine.games / (mine.games + shrinkGames);
    gaps.add(gap);
    contributions.add(
      NextDayContribution(day, mine.games, peers.length, rank, gap),
    );
  }
  final n = gaps.length;
  return NextDayEvidence(
    record,
    List.unmodifiable(contributions),
    n < 3 ? null : 50 + gaps.reduce((a, b) => a + b) / (n + shrinkDays),
  );
}

/// Explicitly user's cutoff, inclusive. Missing scores are not converted to 0.
bool qualifiesForNextDayFocus(NextDayEvidence e, double? todayScore) =>
    e.rawIndex != null &&
    e.todayUsed &&
    e.stabilityZ >= 1.96 &&
    (todayScore == null || todayScore < 88);

bool candidateIsFocus(ProvisionalCandidate c, List<SlotRecord> all) =>
    c.variety ||
    qualifiesForNextDayFocus(
      nextDayEvidence(c.record, all),
      scoreRecord(c.record, all).total,
    );

String focusReason(
  NextDayEvidence e,
  double? todayScore, {
  bool explain = false,
}) {
  if (explain) return _focusReasonExplained(e, todayScore);
  if (todayScore != null && todayScore >= 88) {
    return '当日${todayScore.toStringAsFixed(1)}点：88点以上のため★注目から除外';
  }
  if (!e.todayUsed) return '当日情報が入っていないため★注目の条件未達';
  if (e.stabilityZ < 1.96) return '傾向の安定性基準未達のため★注目の条件未達';
  return '当日情報あり・安定性基準を満たす${todayScore == null ? '（当日点数なし）' : '・当日88点未満'}';
}

/// [focusReason] の、専門用語のあとに意味を添えた版（iPhoneの閲覧ページ用）。判定は同じ。
String _focusReasonExplained(NextDayEvidence e, double? todayScore) {
  if (todayScore != null && todayScore >= 88) {
    return '★注目にしない理由：当日の合計点（この日の結果の点数）が${todayScore.toStringAsFixed(1)}点で、'
        '88点以上のため（★注目は当日88点未満の台だけ。88点以上でも☆長期傾向には残します）';
  }
  if (!e.todayUsed) {
    return '★注目にしない理由：選択日（この日）の結果が、当たりの軽さの計算に入っていないため';
  }
  if (e.stabilityZ < 1.96) {
    return '★注目にしない理由：安定性（毎日のように当たりが多い側だったか）が基準の1.96に届かないため';
  }
  return '★注目の条件をすべて満たしています（選択日の結果が計算に入っている・安定性が1.96以上'
      '${todayScore == null ? '・当日の点数なし' : '・当日の合計点が88点未満'}）';
}

/// [explain]：専門用語のあとに意味を添える（iPhoneの閲覧ページ用）。数字と判定は同じ。
String regularCandidateDetail(
  SlotRecord record,
  List<SlotRecord> all,
  NextDayEvidence e, {
  bool explain = false,
}) {
  if (explain) return _regularCandidateDetailExplained(record, all, e);
  final history = machineHistory(all, record.store, record.machine);
  final selected = provisionalNextDayCandidates(
    history.where((r) => r.day == record.day).toList(),
    history,
  ).candidates.any((c) => c.record.rack == record.rack);
  final score = scoreRecord(record, all).total;
  final label = !selected
      ? 'この台は長期傾向の上位に選ばれていません'
      : qualifiesForNextDayFocus(e, score)
      ? '★ 翌日向けに注目'
      : '☆ 長期傾向の上位（★注目ではありません）';
  final influential = e.contributions.where((d) => d.gap != null).toList()
    ..sort((a, b) => b.gap!.compareTo(a.gap!));
  final target = DateTime.parse(record.day);
  final recent =
      [
            for (var i = 0; i < 3; i++)
              target
                  .subtract(Duration(days: i))
                  .toIso8601String()
                  .substring(0, 10),
          ]
          .map((day) {
            final row = history
                .where((r) => r.rack == record.rack && r.day == day)
                .firstOrNull;
            final total = row == null ? null : scoreRecord(row, all).total;
            return '$day ${row == null
                ? '未取得'
                : total == null
                ? '未採点'
                : '${total.toStringAsFixed(1)}点'}';
          })
          .join('／');
  return '$label\n${e.todayText}\n${e.bandsText}\n${focusReason(e, score)}\n'
      '記録日ごとの当たり順位（新しい順）：${e.contributions.map((d) => '${d.day} ${d.band}${d.gap == null ? '' : '（寄与${signedContribution(d.gap!)}）'}').join('／')}\n'
      '指数を押し上げる日：${influential.where((d) => d.gap! > 0).take(2).map((d) => '${d.day} ${signedContribution(d.gap!)}').join('／')}\n'
      '${e.contributions.length >= 10 ? '次の使用記録で10日枠から抜ける日：${e.contributions.last.day}' : '10記録日の枠はまだ満たしていません'}\n'
      '${nextDayBottomScenario(record, all)}\n'
      '傾向の安定性 z=${e.stabilityZ.toStringAsFixed(2)}（基準1.96）。独立・同順位なしを仮定した目安で、'
      '検定の有意性・高設定の確率・予測精度を示しません。\n'
      '直近3暦日の点数（参考。選択条件には使わない）：$recent';
}

String _regularCandidateDetailExplained(
  SlotRecord record,
  List<SlotRecord> all,
  NextDayEvidence e,
) {
  final history = machineHistory(all, record.store, record.machine);
  final selected = provisionalNextDayCandidates(
    history.where((r) => r.day == record.day).toList(),
    history,
  ).candidates.any((c) => c.record.rack == record.rack);
  final score = scoreRecord(record, all).total;
  final label = !selected
      ? 'この台は☆長期傾向の上位（同じ機種で、当たりの軽さが上から4分の1に入る台）に選ばれていません'
      : qualifiesForNextDayFocus(e, score)
      ? '★ 翌日向けに注目（☆長期傾向の上位のうち、下の条件をすべて満たす台）'
      : '☆ 長期傾向の上位（同じ機種で、当たりの軽さが上から4分の1に入る台）。★注目ではありません';
  final influential = e.contributions.where((d) => d.gap != null).toList()
    ..sort((a, b) => b.gap!.compareTo(a.gap!));
  final target = DateTime.parse(record.day);
  final recent =
      [
            for (var i = 0; i < 3; i++)
              target
                  .subtract(Duration(days: i))
                  .toIso8601String()
                  .substring(0, 10),
          ]
          .map((day) {
            final row = history
                .where((r) => r.rack == record.rack && r.day == day)
                .firstOrNull;
            final total = row == null ? null : scoreRecord(row, all).total;
            return '$day ${row == null
                ? '未取得'
                : total == null
                ? '未採点'
                : '${total.toStringAsFixed(1)}点'}';
          })
          .join('／');
  final pushing = influential
      .where((d) => d.gap! > 0)
      .take(2)
      .map((d) => '${d.day} ${signedContribution(d.gap!)}')
      .join('／');
  return '$label\n'
      '${e.todayTextExplained}\n'
      '記録日ごとの当たり順位の内訳：${e.bandsText}（上＝多い方から4分の1以内、下＝少ない方から4分の1以内）\n'
      '${focusReason(e, score, explain: true)}\n'
      '記録日ごとの当たり順位と寄与（新しい順。寄与＝その日だけで見た当たりの軽さ、0が平均）：'
      '${e.contributions.map((d) => '${d.day} ${d.band}${d.gap == null ? '' : '（寄与${signedContribution(d.gap!)}）'}').join('／')}\n'
      '指数（当たりの軽さ）を押し上げている日：${pushing.isEmpty ? 'なし' : pushing}\n'
      '${e.contributions.length >= 10 ? '次に記録が増えると計算から外れる日：${e.contributions.last.day}（当たりの軽さは、新しい10記録日だけで計算するため）' : '計算に使う10記録日にはまだ届いていません（記録が増えるほど値が落ち着きます）'}\n'
      '${nextDayBottomScenario(record, all, explain: true)}\n'
      '安定性 z=${e.stabilityZ.toStringAsFixed(2)}（毎日のように当たりが多い側だったかの目安。'
      '0なら多い日と少ない日が半々、大きいほど多い側の日が続いている。1.96以上を「安定している」とみなします）。'
      '統計の検定の結果や、高設定の確率・予測の当たりやすさを示すものではありません。\n'
      '直近3日の当日の合計点（その日の結果の点数。参考で、★や☆を選ぶ条件には使っていません）：$recent';
}

/// Identical nine-decimal comparison on PC and Dart; never rank the displayed
/// one-decimal value. Days/latest date are evidence-based deterministic ties.
int compareNextDayEvidence(NextDayEvidence a, NextDayEvidence b) {
  final byIndex = double.parse(b.rawIndex!.toStringAsFixed(9))
      .compareTo(double.parse(a.rawIndex!.toStringAsFixed(9)));
  if (byIndex != 0) return byIndex;
  final byDays = b.usedDays.compareTo(a.usedDays);
  if (byDays != 0) return byDays;
  final byLatest = b.latestUsed.compareTo(a.latestUsed);
  return byLatest != 0 ? byLatest : a.record.rack.compareTo(b.record.rack);
}

/// A sensitivity scenario, NOT a prediction: same games/peer count as the
/// latest usable day, strictly bottom rank, every OTHER rack held fixed.
/// Also rolls the 10-day window and 30-calendar-day expiry forward by one day.
String nextDayBottomScenario(
  SlotRecord record,
  List<SlotRecord> all, {
  bool explain = false,
}) {
  final history = machineHistory(all, record.store, record.machine);
  final rows = history.where((r) => r.day == record.day).toList();
  final eligible = [
    for (final r in rows) nextDayEvidence(r, history),
  ].where((e) => e.rawIndex != null).toList()..sort(compareNextDayEvidence);
  final e = eligible.where((e) => e.record.rack == record.rack).firstOrNull;
  if (e == null || eligible.length < 4) {
    return explain
        ? '翌日最下位の仮定（翌日この台が同じ機種で一番当たりが少なかったら）：判定材料が足りません'
        : '翌日最下位の目安：判定材料が足りません';
  }
  final latest = e.contributions.where((d) => d.gap != null).first;
  final next = DateTime.parse(record.day).add(const Duration(days: 1));
  final first = next
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  final kept = e.contributions
      .take(9)
      .where((d) => d.day.compareTo(first) >= 0)
      .toList();
  final gap =
      (100 * (.5 / latest.peers) - 50) *
      latest.games /
      (latest.games + shrinkGames);
  final n = kept.where((d) => d.gap != null).length + 1;
  if (n < 3) {
    return explain
        ? '翌日最下位の仮定（翌日この台が同じ機種で一番当たりが少なかったら）：計算に使える日数が足りなくなります'
        : '翌日最下位なら判定日数不足（他台を固定した仮定）';
  }
  final raw = 50 + (kept.fold(0.0, (s, d) => s + (d.gap ?? 0)) + gap) / (n + 5);
  final hypothetical = NextDayEvidence(record, [
    NextDayContribution(
      next.toIso8601String().substring(0, 10),
      latest.games,
      latest.peers,
      .5 / latest.peers,
      gap,
    ),
    ...kept,
  ], raw);
  final position = eligible
      .where(
        (other) =>
            other.record.rack != record.rack &&
            compareNextDayEvidence(other, hypothetical) < 0,
      )
      .length;
  final remains = position < (eligible.length * .25).ceil();
  if (explain) {
    return '翌日最下位の仮定（もし翌日この台が同じ機種で一番当たりが少なかったら）：'
        '指数（当たりの軽さ、50が平均）${e.index!.toStringAsFixed(1)}→${raw.toStringAsFixed(1)}、'
        '${remains ? '☆長期傾向の上位に残る' : '☆長期傾向の上位から外れる'}見込み'
        '（回転数と比べる台の数は直近の記録日と同じ、ほかの台は変わらないと仮定。★が続くかの予測ではありません）';
  }
  return '翌日最下位の仮定：指数${e.index!.toStringAsFixed(1)}→${raw.toStringAsFixed(1)}・'
      '${remains ? '長期傾向の上位に残る' : '長期傾向の上位から外れる'}目安'
      '（直近使用日と同じ回転数・比較台数、他台は固定。★継続の予測ではありません）';
}

/// バラエティの台の、その日の終わり方。
enum VarietyState {
  /// [varietyBusyGames]以上回ったのに、プラスで終わらなかった（凹み）。
  dented('回ったのに凹み'),

  /// [varietyBusyGames]以上回って、プラスで終わった。
  plus('回ってプラス'),

  /// [varietyBusyGames]未満（判断の材料が少ない）。
  quiet('3000G未満'),

  /// グラフがまだ無く、終わり方が分からない。
  unknown('グラフ未取得');

  const VarietyState(this.label);
  final String label;
}

/// [record] のその日の終わり方。プラスはグラフの終点がゼロ線より上（採点の
/// 終点と同じく1ピクセル以内はゼロ扱い）。大当たり0回でグラフを取らない台は
/// 凹み。
VarietyState varietyState(SlotRecord record) {
  if (record.games < varietyBusyGames) return VarietyState.quiet;
  if (record.graphNotNeeded) return VarietyState.dented;
  final graph = record.graph;
  if (graph == null || !graph.baselineY.isFinite || !graph.endY.isFinite) {
    return VarietyState.unknown;
  }
  return graph.baselineY - graph.endY > 1
      ? VarietyState.plus
      : VarietyState.dented;
}

/// 店ごとの狙い方（先に見る終わり方の順）。利用者の指定（2026-09-29）で、
/// 実データ7日分の傾向に合わせている：長町南は前日「回ったのに凹んだ台」が
/// 翌日よい割合が高く（回ってプラスの台は低い）、幸町は「回ってプラスの台」が
/// 翌日も続きやすかった。7日分なので外れる可能性も高い。
List<VarietyState> varietyOrder(String store) => store == 'nagamachiminami'
    ? const [VarietyState.dented, VarietyState.plus]
    : const [VarietyState.plus, VarietyState.dented];

/// 店ごとの狙い方の説明（画面に出す）。
String varietyRuleText(String store) {
  final order = varietyOrder(store);
  return '前日${varietyBusyGames}G以上回った台から、'
      '「${order.first.label}」の台を先に、次に「${order.last.label}」の台を、'
      'それぞれ当たりがその台の普段より軽い順に$varietyPicks台';
}

/// その日の当たり確率が、その台の普段（同じ機種の前の30日の記録。1台の機種
/// ならその台自身の過去）と比べて何番目か（0〜100、50が普段どおり）。比べる
/// 相手の条件は採点の [comparisonPool] と同じで、別の機種とは比べない。比べる
/// 記録が3件未満なら null。
({double? percent, int refs}) varietyHitPercent(
  SlotRecord record,
  List<SlotRecord> all,
) {
  double metric(SlotRecord r) => record.pscubeOutputProfile
      ? (r.my ?? 0).toDouble()
      : (r.bb + r.rb) / r.games;
  final rates = [
    for (final r in comparisonPool(record, all))
      if (r.bb >= 0 && r.rb >= 0) metric(r),
  ];
  if (rates.length < 3 || record.games <= 0) {
    return (percent: null, refs: rates.length);
  }
  final rank = percentile(metric(record), rates);
  return (
    percent: double.parse((100 * rank).toStringAsFixed(1)),
    refs: rates.length,
  );
}

/// 翌日候補（仮）の1台。[variety] はバラエティ（1〜3台の機種）から選んだ台で、
/// そのときの [index] は当たりの普段比（[varietyHitPercent]、比べられなければ
/// 50）、[days] は比べた記録の件数。
typedef ProvisionalCandidate = ({
  SlotRecord record,
  double index,
  int days,
  String confidence,
  bool variety,
});

/// Candidate list for the day after the selected date, clearly marked as a
/// trial display. Each rack's own hit-frequency history is the only input.
/// Four eligible racks are required before showing the best quarter, and the
/// result never feeds back into [scoreRecord].
({int total, int eligible, List<ProvisionalCandidate> candidates})
provisionalNextDayCandidates(List<SlotRecord> rows, List<SlotRecord> all) {
  final eligible = <ProvisionalCandidate>[];
  final evidence = <int, NextDayEvidence>{};
  for (final record in rows) {
    evidence[record.rack] = nextDayEvidence(record, all);
    final e = evidence[record.rack]!;
    final tendency = (
      days: e.usedDays,
      index: e.index,
      confidence: e.usedDays < 7 ? '少' : '中',
    );
    if (tendency.index != null) {
      eligible.add((
        record: record,
        index: tendency.index!,
        days: tendency.days,
        confidence: tendency.confidence,
        variety: false,
      ));
    }
  }
  eligible.sort((a, b) {
    return compareNextDayEvidence(
      evidence[a.record.rack]!,
      evidence[b.record.rack]!,
    );
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

/// バラエティ（1店舗・1日の、1〜3台の機種の台 [rows]）の翌日候補。プロの見方で
/// 選ぶ（利用者の指定、2026-09-29）：前日 [varietyBusyGames] 以上回った台
/// （打ち手が粘った台）だけを見て、店ごとの狙い方（[varietyOrder]）の順に、
/// 同じ終わり方の中では当たりがその台の普段より軽い順（[varietyHitPercent]。
/// 比べられない台は50として並べる）、次に回転数の多い順で [varietyPicks] 台。
/// [eligible] は判断できた（よく回って終わり方が分かる）台の数。
({int total, int eligible, List<ProvisionalCandidate> candidates})
varietyNextDayCandidates(List<SlotRecord> rows, List<SlotRecord> all) {
  if (rows.isEmpty) return (total: 0, eligible: 0, candidates: const []);
  final order = varietyOrder(rows.first.store);
  final ranked = <({int group, ProvisionalCandidate candidate})>[];
  for (final record in rows) {
    if (hasImplausibleNumbers(record)) continue;
    final group = order.indexOf(varietyState(record));
    if (group < 0) continue;
    final hit = varietyHitPercent(record, all);
    ranked.add((
      group: group,
      candidate: (
        record: record,
        index: hit.percent ?? 50.0,
        days: hit.refs,
        confidence: hit.percent == null
            ? '比較なし'
            : hit.refs < 7
            ? '少'
            : '中',
        variety: true,
      ),
    ));
  }
  ranked.sort((a, b) {
    if (a.group != b.group) return a.group.compareTo(b.group);
    final ca = a.candidate, cb = b.candidate;
    final byHit = cb.index.compareTo(ca.index);
    if (byHit != 0) return byHit;
    final byGames = cb.record.games.compareTo(ca.record.games);
    if (byGames != 0) return byGames;
    final byRack = ca.record.rack.compareTo(cb.record.rack);
    // 同じ台番号は同じ日の同じ店に1台だけなので、ここに来るのは記録の誤りだけ。
    return byRack != 0
        ? byRack
        : ca.record.machine.compareTo(cb.record.machine);
  });
  return (
    total: rows.length,
    eligible: ranked.length,
    candidates: [for (final r in ranked.take(varietyPicks)) r.candidate],
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
