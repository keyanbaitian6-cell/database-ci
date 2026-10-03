import 'package:flutter/material.dart';

import 'list_views.dart' show shortDayLabel;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';

/// 1日分の差枚（元グラフを取得できた台だけ）。差枚の無い台は0にせず数えない。
class PscubeDayNet {
  const PscubeDayNet({
    required this.day,
    required this.total,
    required this.captured,
    required this.racks,
  });
  final String day;

  /// 差枚を取得できた台の合計。1台も無い日は null（0ではない）。
  final int? total;

  /// 差枚を取得できた台数／その日の記録の台数（数値異常の台は除く）。
  final int captured, racks;

  /// 取得できた台の平均（四捨五入）。1台も無い日は null。
  int? get average => captured == 0 ? null : (total! / captured).round();
}

/// [store]（P’s CUBEの店舗・貸玉）の日ごとの差枚。新しい日が先。
/// 別店舗・別貸玉は混ぜない。サイトの数値が異常な台は合計・平均・台数に入れない。
List<PscubeDayNet> pscubeDailyNet(Iterable<SlotRecord> records, String store) {
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
            if (r.netMedals != null) r.netMedals!,
        ];
        return PscubeDayNet(
          day: day,
          total: nets.isEmpty ? null : nets.reduce((a, b) => a + b),
          captured: nets.length,
          racks: byDay[day]!.length,
        );
      }(),
  ];
}

/// 月（`2026-10`）ごとの日別の差枚。日付をタップすると、その日を選んでホームへ戻る。
class PscubeDailyNetPage extends StatefulWidget {
  const PscubeDailyNetPage({
    super.key,
    required this.records,
    required this.store,
    required this.day,
    this.onDayChanged,
  });
  final List<SlotRecord> records;
  final String store, day;
  final ValueChanged<String>? onDayChanged;
  @override
  State<PscubeDailyNetPage> createState() => _PscubeDailyNetPageState();
}

class _PscubeDailyNetPageState extends State<PscubeDailyNetPage> {
  late final List<PscubeDayNet> _all = pscubeDailyNet(
    widget.records,
    widget.store,
  );
  late String _month = widget.day.substring(0, 7);
  int _sortColumn = 0;
  bool _ascending = true;

  List<String> get _months =>
      {for (final d in _all) d.day.substring(0, 7)}.toList()
        ..sort((a, b) => b.compareTo(a));

  static String _monthLabel(String month) =>
      '${month.substring(0, 4)}年${int.parse(month.substring(5))}月';

  List<PscubeDayNet> _rows() {
    final rows = [
      for (final d in _all)
        if (d.day.startsWith(_month)) d,
    ];
    int compare(PscubeDayNet a, PscubeDayNet b) {
      // 差枚の無い日は、並べ替えの向きにかかわらず最後に置く。
      int? value(PscubeDayNet d) => switch (_sortColumn) {
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
      appBar: AppBar(title: const Text('日別の差枚')),
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
                                child: Text(shortDayLabel(d.day)),
                              ),
                            ),
                            DataCell(Text(medals(d.total))),
                            DataCell(Text(medals(d.average))),
                            DataCell(Text('${d.captured}/${d.racks}')),
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
            const Notice(
              text:
                  '総差枚・平均差枚は、台別ページで差枚の元データを取得できた台だけの合計・平均です'
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
