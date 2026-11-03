import 'list_views.dart' show displayMachineName;
import 'models.dart' show SlotRecord, signedMedals;

/// お店のひとこと（2026-11-04、利用者が選んだ「お店の昨日のひとこと」）。閲覧ページで、選んでいる日について出す。
///
/// 共有カレンダー（share_viewer/data.mjs `dayComment`）と同じ文。決め方は同じ試験データ
/// （test/fixtures/day_comment_cases.json）で照らし合わせる。その日の数字から言い切れることだけを短く書き、
/// 設定や勝ちを言い当てる言い方はしない。
/// 1. その日の総差枚（差枚の分かる台が半分以上のときだけ。推定なら「（推定）」）と、何台中何台がプラスか。
///    イベントがあれば先に。
/// 2. この30日（比べられる日＝勝ち負けの分かる台が20台以上の日が10日以上あるとき）の中で、プラスの台の割合が
///    高い方（4分の3以上の日より高い）・低い方（4分の3以上の日より低い）・真ん中くらいのどれか。
/// 3. 1台あたりの平均差枚がいちばんの機種（差枚の分かる台が3台以上の機種。どれもマイナスならそう書く）。
/// 4. 台番号が4台以上続けてプラスだった所（いちばん長い所）。無ければ、全体より2割以上プラスの割合が
///    高い末尾（8台以上）。
const commentRecentDays = 30;
const commentMinDays = 10;
const commentMinJudged = 20;
const commentMachineMin = 3;
const commentRunMin = 4;
const commentSuffixMin = 8;

/// 1台分の入力（[SlotRecord] の netValue・won と同じ意味）。
typedef CommentRack = ({
  int rack,
  String machine,
  int? net,
  bool? won,
  bool estimated,
});

const _weekdays = ['月', '火', '水', '木', '金', '土', '日'];

String dayComment({
  required String day,
  String? event,
  required List<CommentRack> racks,
  List<({int judged, int won})> recent = const [],
}) {
  final judged = [
    for (final r in racks)
      if (r.won != null) r,
  ];
  final won = judged.where((r) => r.won!).length;
  if (judged.isEmpty) return '';
  final nets = [
    for (final r in racks)
      if (r.net != null) r,
  ];
  final netsKnown = nets.length * 2 >= judged.length;
  final est = nets.any((r) => r.estimated) ? '（推定）' : '';
  final date = DateTime.parse(day);
  final label = '${date.month}/${date.day}（${_weekdays[date.weekday - 1]}）';
  final total = nets.fold(0, (sum, r) => sum + r.net!);
  final result =
      '${netsKnown ? '総差枚${signedMedals(total)}枚$estで、' : ''}${judged.length}台中$won台がプラスでした。';
  final lines = [
    event != null ? '$labelはイベント「$event」の日。$result' : '$labelは、$result',
  ];
  // 割合は整数の掛け算で比べる（共有カレンダーの JS と小数の丸めで食い違わないように）。
  final others = [
    for (final x in recent)
      if (x.judged >= commentMinJudged) x,
  ];
  if (judged.length >= commentMinJudged && others.length >= commentMinDays) {
    final lower = others
        .where((x) => x.won * judged.length < won * x.judged)
        .length;
    final higher = others
        .where((x) => x.won * judged.length > won * x.judged)
        .length;
    final place = lower * 4 >= others.length * 3
        ? '高い方'
        : higher * 4 >= others.length * 3
        ? '低い方'
        : '真ん中くらい';
    lines.add(
      'この$commentRecentDays日で記録のある${others.length}日の中では、プラスの台の割合が$placeでした。',
    );
  }
  if (netsKnown) {
    final byMachine = <String, List<int>>{};
    for (final r in nets) {
      byMachine.putIfAbsent(r.machine, () => []).add(r.net!);
    }
    final machines =
        [
          for (final e in byMachine.entries)
            if (e.value.length >= commentMachineMin)
              (
                machine: e.key,
                count: e.value.length,
                // JS の Math.round と同じ（0.5は大きい方へ）。
                average:
                    (e.value.fold(0, (s, n) => s + n) / e.value.length + 0.5)
                        .floor(),
              ),
        ]..sort((a, b) {
          final byAverage = b.average.compareTo(a.average);
          if (byAverage != 0) return byAverage;
          final byCount = b.count.compareTo(a.count);
          return byCount != 0 ? byCount : a.machine.compareTo(b.machine);
        });
    if (machines.isNotEmpty && machines.first.average > 0) {
      final best = machines.first;
      lines.add(
        '機種別では、${displayMachineName(best.machine)}（${best.count}台）が1台あたり'
        '${signedMedals(best.average)}枚$estでいちばんでした。',
      );
    } else if (machines.length >= 3) {
      lines.add('$commentMachineMin台以上ある機種は、どれも1台あたりではマイナスでした。');
    }
  }
  final plus = {
    for (final r in judged)
      if (r.won!) r.rack,
  };
  ({int start, int end})? run;
  for (final start in plus.toList()..sort()) {
    if (plus.contains(start - 1)) continue;
    var end = start;
    while (plus.contains(end + 1)) {
      end++;
    }
    if (end - start + 1 >= commentRunMin &&
        (run == null || end - start > run.end - run.start)) {
      run = (start: start, end: end);
    }
  }
  if (run != null) {
    lines.add('${run.start}〜${run.end}番は${run.end - run.start + 1}台続けてプラスでした。');
  } else {
    final bySuffix = <int, List<bool>>{};
    for (final r in judged) {
      bySuffix.putIfAbsent(r.rack % 10, () => []).add(r.won!);
    }
    final suffixes =
        [
          for (final e in bySuffix.entries)
            if (e.value.length >= commentSuffixMin)
              (
                suffix: e.key,
                judged: e.value.length,
                won: e.value.where((w) => w).length,
              ),
        ]..sort((a, b) {
          final byRate = (b.won * a.judged).compareTo(a.won * b.judged);
          if (byRate != 0) return byRate;
          final byJudged = b.judged.compareTo(a.judged);
          return byJudged != 0 ? byJudged : a.suffix.compareTo(b.suffix);
        });
    final best = suffixes.isEmpty ? null : suffixes.first;
    // 末尾の割合が全体より2割以上高い：(w/j − W/J) × 5 ≥ 1 を整数で。
    if (best != null &&
        (best.won * judged.length - won * best.judged) * 5 >=
            best.judged * judged.length) {
      lines.add('末尾${best.suffix}は${best.judged}台中${best.won}台がプラスでした。');
    }
  }
  return lines.join();
}

/// その店の [day] のひとこと（前の30日の勝ち負けと、その日のイベントを添える）。
String storeDayComment(
  List<SlotRecord> all,
  String store,
  String day, {
  String? event,
}) {
  final byDay = <String, List<SlotRecord>>{};
  for (final r in all) {
    if (r.store == store) byDay.putIfAbsent(r.day, () => []).add(r);
  }
  final base = DateTime.utc(
    int.parse(day.substring(0, 4)),
    int.parse(day.substring(5, 7)),
    int.parse(day.substring(8, 10)),
  );
  final recent = <({int judged, int won})>[];
  for (var back = 1; back <= commentRecentDays; back++) {
    final other = base
        .subtract(Duration(days: back))
        .toIso8601String()
        .substring(0, 10);
    final results = [
      for (final r in byDay[other] ?? const <SlotRecord>[]) ?r.won,
    ];
    if (results.isNotEmpty) {
      recent.add((judged: results.length, won: results.where((w) => w).length));
    }
  }
  return dayComment(
    day: day,
    event: event,
    racks: [
      for (final r in byDay[day] ?? const <SlotRecord>[])
        (
          rack: r.rack,
          machine: r.machine,
          net: r.netValue,
          won: r.won,
          estimated: r.netValue != null && r.netLabel == '推定差枚',
        ),
    ],
    recent: recent,
  );
}
