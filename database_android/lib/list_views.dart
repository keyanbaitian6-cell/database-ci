import 'data_checks.dart';
import 'models.dart';
import 'setting_estimate.dart' show foldHalfWidthKana;

/// 一覧で使う短い店舗名。正式名は長く、スマホの幅では「…」で切れるため。
const storeShortNames = <String, String>{
  'nagamachiminami': '長町南',
  'saiwaichou': '幸町',
};

String storeShortName(String store) => storeShortNames[store] ?? store;

/// 画面に出す機種名。長町南の一覧は半角カナ（例：`ｺﾞｰｺﾞｰｼﾞｬｸﾞﾗｰ3`）で読みにくい
/// ので、表示だけ全角カナにそろえる。保存している名前（照合・検索・削除の
/// 範囲に使う）は変えない。
String displayMachineName(String machine) => foldHalfWidthKana(machine);

/// 機種名の並び順。表示している名前（全角にそろえた名前）の順に並べる。
/// 保存している名前のままだと、半角カナの機種が漢字の機種より後ろに回る。
int compareMachineNames(String a, String b) {
  final byDisplay = displayMachineName(a).compareTo(displayMachineName(b));
  return byDisplay != 0 ? byDisplay : a.compareTo(b);
}

/// 機種名の検索用に文字をそろえる。
///
/// サイトの機種名は全角・半角カナ、全角英字が混ざる（例：`ｼﾞｬｸﾞﾗｰ`）。
/// スマホではひらがなで打つことも多いので、ひらがな→カタカナ、
/// 半角カナ→全角、全角英数→半角、大文字→小文字にそろえ、空白と`+`は無視する
/// （機種一覧の行クリックと同じく`+`と空白の違いを気にしない）。
String foldForSearch(String text) {
  final kana = foldHalfWidthKana(text);
  final buffer = StringBuffer();
  for (final code in kana.runes) {
    if (code >= 0x3041 && code <= 0x3096) {
      buffer.writeCharCode(code + 0x60); // ひらがな→カタカナ
    } else if (code >= 0xFF01 && code <= 0xFF5E) {
      buffer.writeCharCode(code - 0xFEE0); // 全角英数記号→半角
    } else {
      buffer.writeCharCode(code);
    }
  }
  return buffer.toString().toLowerCase().replaceAll(RegExp(r'[\s+　]+'), '');
}

/// [machine] が検索語 [query] を含むか。空の検索語はすべてに一致する。
bool machineMatches(String machine, String query) {
  final folded = foldForSearch(query);
  return folded.isEmpty || foldForSearch(machine).contains(folded);
}

/// 結果タブの機種一覧の1行ぶん。
class MachineSummary {
  const MachineSummary({
    required this.machine,
    required this.racks,
    required this.scored,
    required this.noGraph,
    required this.average,
    required this.best,
    required this.bestRack,
  });

  final String machine;

  /// 台数・合計点が出た台数・グラフ未取得の台数。
  final int racks, scored, noGraph;

  /// 合計点が出た台の平均と最高。出た台が無ければ null。
  final double? average, best;
  final int? bestRack;
}

/// その日の台を機種ごとにまとめる。台数の多い順、同数なら機種名順。
List<MachineSummary> summarizeMachines(
  Iterable<(SlotRecord, ScoreResult)> entries,
) {
  final byMachine = <String, List<(SlotRecord, ScoreResult)>>{};
  for (final entry in entries) {
    byMachine.putIfAbsent(entry.$1.machine, () => []).add(entry);
  }
  final summaries = [
    for (final name in byMachine.keys)
      () {
        final rows = byMachine[name]!;
        final scored = [
          for (final e in rows)
            if (e.$2.total != null) e,
        ];
        (SlotRecord, ScoreResult)? best;
        for (final e in scored) {
          if (best == null || e.$2.total! > best.$2.total!) best = e;
        }
        return MachineSummary(
          machine: name,
          racks: rows.length,
          scored: scored.length,
          noGraph: rows.where((e) => e.$1.graph == null).length,
          average: scored.isEmpty
              ? null
              : scored.map((e) => e.$2.total!).reduce((a, b) => a + b) /
                    scored.length,
          best: best?.$2.total,
          bestRack: best?.$1.rack,
        );
      }(),
  ];
  summaries.sort((a, b) {
    final byCount = b.racks.compareTo(a.racks);
    return byCount != 0 ? byCount : compareMachineNames(a.machine, b.machine);
  });
  return summaries;
}

/// 過去の記録の1行ぶん（ある日・ある店舗・ある機種の台）。
class HistoryGroup {
  const HistoryGroup(this.day, this.store, this.machine, this.rows);
  final String day, store, machine;

  /// 台番号順。
  final List<SlotRecord> rows;
}

/// 過去の記録を日付ごとにまとめる。日付は新しい順、同じ日の中は店舗・機種名順。
List<(String, List<HistoryGroup>)> groupHistoryByDay(
  Iterable<SlotRecord> records,
) {
  final groups = <String, Map<(String, String), List<SlotRecord>>>{};
  for (final record in records) {
    groups
        .putIfAbsent(record.day, () => {})
        .putIfAbsent((record.store, record.machine), () => [])
        .add(record);
  }
  final days = groups.keys.toList()..sort((a, b) => b.compareTo(a));
  return [
    for (final day in days)
      (
        day,
        [
          for (final entry
              in groups[day]!.entries.toList()..sort((a, b) {
                final byStore = a.key.$1.compareTo(b.key.$1);
                return byStore != 0
                    ? byStore
                    : compareMachineNames(a.key.$2, b.key.$2);
              }))
            HistoryGroup(
              day,
              entry.key.$1,
              entry.key.$2,
              entry.value..sort((a, b) => a.rack.compareTo(b.rack)),
            ),
        ],
      ),
  ];
}

/// `2026-09-23` → `2026-09-23（水）`。読めない日付はそのまま返す。
String dayWithWeekday(String day) {
  if (!isValidRecordDay(day)) return day;
  const names = ['月', '火', '水', '木', '金', '土', '日'];
  return '$day（${names[DateTime.parse(day).weekday - 1]}）';
}

/// `2026-09-23` を `9/23（水）` の形で。読めない日付は空文字。
String shortDayLabel(String day) {
  if (!isValidRecordDay(day)) return '';
  const names = ['月', '火', '水', '木', '金', '土', '日'];
  final d = DateTime.parse(day);
  return '${d.month}/${d.day}（${names[d.weekday - 1]}）';
}

/// `2026-09-23` の翌日を `9/24（木）` の形で。読めない日付は空文字。
String nextDayLabel(String day) {
  if (!isValidRecordDay(day)) return '';
  const names = ['月', '火', '水', '木', '金', '土', '日'];
  final next = DateTime.parse(day).add(const Duration(days: 1));
  return '${next.month}/${next.day}（${names[next.weekday - 1]}）';
}

/// 当たり確率を `1/151.8` の形で。当たりが無ければ `—`（サイトの `1/0.0` は
/// 「確率0」と読めてしまうため使わない）。
String hitRate(int games, int hits) =>
    games <= 0 || hits <= 0 ? '—' : '1/${(games / hits).toStringAsFixed(1)}';

/// 機種の表の一番下の「平均」行。
///
/// 回転・BIG・REG・最大持玉・点数は台ごとの値の平均。確率は台ごとの確率の
/// 平均ではなく、合計の回転数を合計の当たり回数で割った値（回転の少ない台の
/// 極端な確率に引っ張られないため）。
class RackAverages {
  const RackAverages({
    required this.games,
    required this.bb,
    required this.rb,
    required this.combined,
    required this.bbRate,
    required this.rbRate,
    required this.maxHold,
    required this.score,
  });
  final int games, bb, rb;
  final String combined, bbRate, rbRate;

  /// 値のある台だけの平均。1台も無ければ null。
  final int? maxHold;
  final double? score;
}

RackAverages rackAverages(List<(SlotRecord, ScoreResult)> all) {
  // サイトの数値が異常な台（88888888など）は平均に入れない。
  final entries = [
    for (final e in all)
      if (!hasImplausibleNumbers(e.$1)) e,
  ];
  final n = entries.isEmpty ? 1 : entries.length;
  var games = 0, bb = 0, rb = 0;
  for (final (r, _) in entries) {
    games += r.games;
    bb += r.bb;
    rb += r.rb;
  }
  final holds = [
    for (final (r, _) in entries)
      if (r.maxHold != null) r.maxHold!,
  ];
  final scores = [
    for (final (_, s) in entries)
      if (s.total != null) s.total!,
  ];
  return RackAverages(
    games: (games / n).round(),
    bb: (bb / n).round(),
    rb: (rb / n).round(),
    combined: hitRate(games, bb + rb),
    bbRate: hitRate(games, bb),
    rbRate: hitRate(games, rb),
    maxHold: holds.isEmpty
        ? null
        : (holds.reduce((a, b) => a + b) / holds.length).round(),
    score: scores.isEmpty
        ? null
        : scores.reduce((a, b) => a + b) / scores.length,
  );
}

/// その日の全機種の翌日候補（仮）。機種ごとに [provisionalNextDayCandidates]
/// で選んだ台（各機種の上位4分の1）を集め、「平均より」の大きい順に並べる。
/// 比べる相手は同じ機種の台なので、機種をまたいだ順位は目安にとどまる。
({List<ProvisionalCandidate> candidates, int machines, int judged})
dayCandidates(List<SlotRecord> dayRows, List<SlotRecord> all) {
  final byMachine = <String, List<SlotRecord>>{};
  for (final r in dayRows) {
    byMachine.putIfAbsent(r.machine, () => []).add(r);
  }
  // 過去の傾向は同じ店舗・同じ機種の記録しか見ないので、先に絞ってから渡す
  // （台ごとに全記録を見直すと、記録が増えるほど結果タブが重くなる）。
  final history = <(String, String), List<SlotRecord>>{};
  for (final r in all) {
    history.putIfAbsent((r.store, r.machine), () => []).add(r);
  }
  final candidates = <ProvisionalCandidate>[];
  var judged = 0;
  for (final rows in byMachine.values) {
    final first = rows.first;
    final result = provisionalNextDayCandidates(
      rows,
      history[(first.store, first.machine)] ?? rows,
    );
    if (result.candidates.isNotEmpty) judged++;
    candidates.addAll(result.candidates);
  }
  candidates.sort((a, b) {
    final byIndex = b.index.compareTo(a.index);
    if (byIndex != 0) return byIndex;
    final byMachine = a.record.machine.compareTo(b.record.machine);
    return byMachine != 0 ? byMachine : a.record.rack.compareTo(b.record.rack);
  });
  return (candidates: candidates, machines: byMachine.length, judged: judged);
}
