import 'models.dart';
import 'setting_estimate.dart' show foldHalfWidthKana;

/// 一覧で使う短い店舗名。正式名は長く、スマホの幅では「…」で切れるため。
const storeShortNames = <String, String>{
  'nagamachiminami': '長町南',
  'saiwaichou': '幸町',
};

String storeShortName(String store) => storeShortNames[store] ?? store;

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

/// その日の台を機種ごとにまとめる。並びは機種名順（従来のプルダウンと同じ）。
List<MachineSummary> summarizeMachines(
  Iterable<(SlotRecord, ScoreResult)> entries,
) {
  final byMachine = <String, List<(SlotRecord, ScoreResult)>>{};
  for (final entry in entries) {
    byMachine.putIfAbsent(entry.$1.machine, () => []).add(entry);
  }
  final names = byMachine.keys.toList()..sort();
  return [
    for (final name in names)
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
                return byStore != 0 ? byStore : a.key.$2.compareTo(b.key.$2);
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
