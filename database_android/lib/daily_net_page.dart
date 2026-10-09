import 'package:flutter/material.dart';

import 'list_views.dart' show shortDayLabel;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';

/// 1日分の差枚（P’s CUBEは元グラフの確定差枚、メルヘンはグラフと最大持玉からの推定差枚。
/// 差枚の無い台は0にせず数えない）。
class DayNet {
  const DayNet({
    required this.day,
    required this.total,
    required this.captured,
    required this.racks,
    this.needsCheck = 0,
  });
  final String day;

  /// 合計に入っている推定差枚のうち、要確認（※）の台数（[SlotRecord.netNeedsCheck]）。
  final int needsCheck;

  /// 差枚がある台の合計。1台も無い日は null（0ではない）。
  final int? total;

  /// 差枚がある台数／その日の記録の台数（数値異常の台は除く）。
  final int captured, racks;

  /// 差枚がある台の平均（四捨五入）。1台も無い日は null。
  int? get average => captured == 0 ? null : (total! / captured).round();
}

/// [store] の日ごとの差枚。新しい日が先。
/// 別店舗・別貸玉は混ぜない。サイトの数値が異常な台は合計・平均・台数に入れない。
List<DayNet> dailyNet(Iterable<SlotRecord> records, String store) {
  final byDay = <String, List<SlotRecord>>{};
  for (final r in records) {
    if (r.store == store && !hasImplausibleNumbers(r)) {
      (byDay[r.day] ??= []).add(r);
    }
  }
  final days = byDay.keys.toList()..sort((a, b) => b.compareTo(a));
  return [
    for (final day in days)
      () {
        final nets = [
          for (final r in byDay[day]!)
            if (r.netValue != null) r.netValue!,
        ];
        return DayNet(
          day: day,
          total: nets.isEmpty ? null : nets.reduce((a, b) => a + b),
          captured: nets.length,
          racks: byDay[day]!.length,
          needsCheck: byDay[day]!
              .where((r) => r.netValue != null && r.netNeedsCheck)
              .length,
        );
      }(),
  ];
}

/// 店舗ごとの日別の差枚を、店舗ごとに1回だけ数えて引けるようにする（カレンダーのマスごとに数え直さない）。
DayNet? Function(String store, String day) dailyNetLookup(
  Iterable<SlotRecord> records,
) {
  final cache = <String, Map<String, DayNet>>{};
  return (store, day) => (cache[store] ??= {
    for (final d in dailyNet(records, store)) d.day: d,
  })[day];
}

/// 差枚の説明（カレンダーの下）。メルヘンは推定であることを必ず添える。
String dailyNetNote(String store) => isPscubeStore(store)
    ? '差枚＝その日の総差枚（元グラフの差枚がわかった台の合計）。'
    : '差枚＝その日の総差枚（推定。グラフと最大持玉から計算できた台の合計で、確定値ではありません。'
          '要確認の台も含みます。ジャグラーオンラインから取り込んだ台は、その差枚）。';

/// 月（`2026-10`）ごとの日別の差枚。日付をタップすると、その日を選んでホームへ戻る。
/// P’s CUBEとメルヘンで同じ画面。メルヘンは推定差枚であることを見出しと注記で示す。
class DailyNetPage extends StatefulWidget {
  const DailyNetPage({
    super.key,
    required this.records,
    required this.store,
    required this.day,
    this.onDayChanged,
    this.eventFor,
  });
  final List<SlotRecord> records;
  final String store, day;
  final ValueChanged<String>? onDayChanged;

  /// 月別一覧の日付に添えるイベント名。無い日は日付だけ表示する。
  final String? Function(String day)? eventFor;
  @override
  State<DailyNetPage> createState() => _DailyNetPageState();
}

class _DailyNetPageState extends State<DailyNetPage> {
  late final bool _estimated = !isPscubeStore(widget.store);
  late final List<DayNet> _all = dailyNet(widget.records, widget.store);
  late String _month = widget.day.substring(0, 7);
  int _sortColumn = 0;
  bool _ascending = true;

  List<String> get _months =>
      {for (final d in _all) d.day.substring(0, 7)}.toList()
        ..sort((a, b) => b.compareTo(a));

  static String _monthLabel(String month) =>
      '${month.substring(0, 4)}年${int.parse(month.substring(5))}月';

  List<DayNet> _rows() {
    final rows = [
      for (final d in _all)
        if (d.day.startsWith(_month)) d,
    ];
    int compare(DayNet a, DayNet b) {
      // 差枚の無い日は、並べ替えの向きにかかわらず最後に置く。
      int? value(DayNet d) => switch (_sortColumn) {
        1 => d.total,
        2 => d.average,
        _ => null,
      };
      if (_sortColumn == 0) {
        return _ascending ? a.day.compareTo(b.day) : b.day.compareTo(a.day);
      }
      final x = value(a), y = value(b);
      if (x == null || y == null) {
        return x == null ? (y == null ? 0 : 1) : -1;
      }
      final c = _ascending ? x.compareTo(y) : y.compareTo(x);
      return c != 0 ? c : a.day.compareTo(b.day);
    }

    return rows..sort(compare);
  }

  void _sort(int column, bool ascending) => setState(() {
    _sortColumn = column;
    _ascending = ascending;
  });

  void _open(String day) {
    widget.onDayChanged?.call(day);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final rows = _rows();
    final captured = rows.fold(0, (sum, d) => sum + d.captured);
    final total = rows.fold(0, (sum, d) => sum + (d.total ?? 0));
    const bold = TextStyle(fontWeight: FontWeight.w800);
    String medals(int? value) => value == null ? '—' : signedMedals(value);
    return Scaffold(
      appBar: AppBar(title: Text(_estimated ? '日別の差枚（推定）' : '日別の差枚')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          children: [
            Text(
              '${storeDisplayName(widget.store)}　${_monthLabel(_month)}のデータ',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            const Text(
              '日付を選択すると当日データを確認できます。',
              style: TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _month,
              decoration: const InputDecoration(labelText: '月'),
              items: [
                for (final m in _months)
                  DropdownMenuItem(value: m, child: Text(_monthLabel(m))),
              ],
              onChanged: (m) {
                if (m != null && m != _month) setState(() => _month = m);
              },
            ),
            const SizedBox(height: 12),
            if (rows.isEmpty)
              const Notice(text: 'この月の記録はありません。')
            else
              Card(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    key: const ValueKey('pscube-daily-net'),
                    showCheckboxColumn: false,
                    columnSpacing: 18,
                    horizontalMargin: 12,
                    // イベント名（日付の下の2行目）が入る表は、行を少し高くする。
                    // 標準の48では、2行がはみ出してイベント名が切れる。
                    dataRowMinHeight: widget.eventFor == null ? null : 56,
                    dataRowMaxHeight: widget.eventFor == null ? null : 56,
                    headingRowColor: const WidgetStatePropertyAll(
                      AppColors.ice,
                    ),
                    sortColumnIndex: _sortColumn,
                    sortAscending: _ascending,
                    columns: [
                      DataColumn(label: const Text('日付'), onSort: _sort),
                      DataColumn(
                        label: const Text('総差枚'),
                        numeric: true,
                        onSort: _sort,
                      ),
                      DataColumn(
                        label: const Text('平均差枚'),
                        numeric: true,
                        onSort: _sort,
                      ),
                      const DataColumn(label: Text('取得台数'), numeric: true),
                    ],
                    rows: [
                      for (final d in rows)
                        DataRow(
                          selected: d.day == widget.day,
                          cells: [
                            DataCell(
                              TextButton(
                                onPressed: () => _open(d.day),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(shortDayLabel(d.day)),
                                    if (widget.eventFor?.call(d.day)
                                        case final event?)
                                      Text(
                                        event,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: AppColors.ash,
                                        ),
                                      ),
                                  ],
                                ),
                              ),
                            ),
                            DataCell(Text(medals(d.total))),
                            DataCell(Text(medals(d.average))),
                            DataCell(
                              Text(
                                '${d.captured}/${d.racks}'
                                '${d.needsCheck > 0 ? '（※${d.needsCheck}）' : ''}',
                              ),
                            ),
                          ],
                        ),
                      DataRow(
                        cells: [
                          const DataCell(Text('期間累計', style: bold)),
                          DataCell(
                            Text(
                              captured == 0 ? '—' : signedMedals(total),
                              style: bold,
                            ),
                          ),
                          DataCell(
                            Text(
                              captured == 0
                                  ? '—'
                                  : signedMedals((total / captured).round()),
                              style: bold,
                            ),
                          ),
                          DataCell(Text('$captured台', style: bold)),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 8),
            const Text(
              '表は横にスクロールできます。見出しをタップすると並べ替えます。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            Notice(
              text: _estimated
                  ? '推定差枚です。サイトは差枚の数値を出していないため、保存したグラフの形と最大持玉から'
                        '縦軸の目盛りを割り出して計算しています（確定値ではありません。誤差はおよそ'
                        'グラフ1目盛り分：通常±6枚、大きく動いた台は±10〜30枚）。'
                        '総差枚・平均差枚は計算できた台だけの合計・平均です（取得台数＝計算できた台／その日の記録の台）。'
                        'グラフの無い台・最大持玉の無い台・目盛りを決められない台は含まないため、店舗全体の総差枚ではありません。'
                        '取得台数の（※N）は、グラフだけでは目盛りを決めきれず回転数から選び直した、要確認の台数です（合計には含みます）。'
                        '差枚の無い日は「—」（0ではありません）。最大持玉は差枚ではありません。'
                  : '総差枚・平均差枚は、台別ページで差枚の元データを取得できた台だけの合計・平均です'
                        '（取得台数＝取得できた台／その日の記録の台）。当たり0回の台・沖ドキ・未取得の台は含まないため、'
                        '店舗全体の総差枚ではありません。差枚の無い日は「—」（0ではありません）。'
                        'サイトの数値が異常な台は除いています。MYは差枚ではありません。',
            ),
          ],
        ),
      ),
    );
  }
}
