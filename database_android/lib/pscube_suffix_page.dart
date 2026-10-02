import 'package:flutter/material.dart';

import 'machine_sections.dart';
import 'list_views.dart' show dayWithWeekday;
import 'models.dart';
import 'pscube_suffix.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

class PscubeSuffixPage extends StatefulWidget {
  const PscubeSuffixPage({
    super.key,
    required this.data,
    required this.store,
    required this.day,
    this.onDayChanged,
  });
  final ViewerData data;
  final String store, day;
  final ValueChanged<String>? onDayChanged;
  @override
  State<PscubeSuffixPage> createState() => _PscubeSuffixPageState();
}

class _PscubeSuffixPageState extends State<PscubeSuffixPage> {
  late String _day = widget.day;
  var _period = PscubeSuffixPeriod.day;
  var _type = PscubeSuffixType.all;
  final _scroll = ScrollController();
  Object? _calculatedFor;
  PscubeSuffixReport? _report;
  @override
  void initState() {
    super.initState();
    _calculate();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _calculate() async {
    setState(() => _calculatedFor = null);
    final key = (_day, _period, _type);
    await Future<void>.delayed(Duration.zero);
    if (!mounted || key != (_day, _period, _type)) return;
    final report = summarizePscubeSuffixes(
      widget.data.records,
      store: widget.store,
      day: _day,
      period: _period,
      type: _type,
    );
    setState(() {
      _report = report;
      _calculatedFor = key;
    });
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    _day = day;
    widget.onDayChanged?.call(day);
    _calculate();
  }

  void _open(PscubeSuffixSummary summary) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _PscubeSuffixDetails(
          data: widget.data,
          store: widget.store,
          summary: summary,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ready = _calculatedFor == (_day, _period, _type);
    final report = _report;
    String average(double? value) => value?.toStringAsFixed(1) ?? '—';
    return Scaffold(
      appBar: AppBar(
        title: const Text('末尾別データまとめ'),
        bottom: ViewerDateBar(
          days: viewerDays(widget.data.records, widget.store),
          day: _day,
          onChanged: _changeDay,
        ),
      ),
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
          children: [
            Text(
              storeDisplayName(widget.store),
              style: const TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<PscubeSuffixPeriod>(
              initialValue: _period,
              decoration: const InputDecoration(labelText: '集計期間'),
              items: [
                for (final p in PscubeSuffixPeriod.values)
                  DropdownMenuItem(value: p, child: Text(p.label)),
              ],
              onChanged: (p) {
                if (p != null && p != _period) {
                  _period = p;
                  _calculate();
                }
              },
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<PscubeSuffixType>(
              initialValue: _type,
              decoration: const InputDecoration(labelText: '機種タイプ'),
              items: [
                for (final t in PscubeSuffixType.values)
                  DropdownMenuItem(value: t, child: Text(t.label)),
              ],
              onChanged: (t) {
                if (t != null && t != _type) {
                  _type = t;
                  _calculate();
                }
              },
            ),
            const SizedBox(height: 12),
            if (!ready)
              const Center(child: CircularProgressIndicator())
            else if (report != null) ...[
              Notice(
                text:
                    '${report.start ?? '保存開始'}〜${report.end}：記録${report.days}日・'
                    '${report.racks}台・${report.records}件（台×日）。末尾0・1・2・3・5・6・7・8を集計。'
                    '${report.excludedInvalid > 0 ? '数値異常${report.excludedInvalid}件は対象外。' : ''}'
                    '${report.excludedSuffix > 0 ? '指定外の末尾${report.excludedSuffix}件は対象外。' : ''}',
              ),
              const SizedBox(height: 12),
              const Text(
                '末尾別まとめ',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 6),
              Card(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    showCheckboxColumn: false,
                    columnSpacing: 18,
                    horizontalMargin: 12,
                    headingRowColor: const WidgetStatePropertyAll(
                      AppColors.ice,
                    ),
                    columns: [
                      for (final label in [
                        '末尾',
                        '台数',
                        '記録件数',
                        '平均G',
                        '平均MY',
                        '平均点',
                        '採点件数',
                        'プラス終点',
                      ])
                        DataColumn(label: Text(label), numeric: label != '末尾'),
                    ],
                    rows: [
                      for (final s in report.summaries)
                        DataRow(
                          cells: [
                            DataCell(
                              TextButton(
                                onPressed: s.records == 0
                                    ? null
                                    : () => _open(s),
                                child: Text('末尾${s.suffix}'),
                              ),
                            ),
                            DataCell(Text('${s.racks}')),
                            DataCell(Text('${s.records}')),
                            DataCell(Text(average(s.averageGames))),
                            DataCell(Text(average(s.averageMy))),
                            DataCell(Text(average(s.averageScore))),
                            DataCell(Text('${s.scored}')),
                            DataCell(
                              Text(
                                s.positivePercent == null
                                    ? '—'
                                    : '${s.positiveGraphs}/${s.graphs}（${s.positivePercent!.toStringAsFixed(1)}%）',
                              ),
                            ),
                          ],
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                '表は横にスクロールできます。末尾をタップすると台ごとの内訳を表示します。',
                style: TextStyle(fontSize: 12, color: AppColors.ash),
              ),
              const SizedBox(height: 12),
              const Notice(
                text:
                    '平均G・平均MYは1記録（台×日）あたり。平均点は採点できた記録のみ（暫定を含む）。'
                    'プラス終点は取得済みグラフのうち終点がゼロ線より上の割合（1ピクセル以内はゼロ扱い）。'
                    'MYは差枚ではありません。機種構成や稼働量の違いは、機種タイプと内訳で確認できます。',
              ),
              const SizedBox(height: 16),
              for (final s in report.summaries.where((s) => s.records > 0)) ...[
                Card(
                  child: ListTile(
                    onTap: () => _open(s),
                    title: Text('末尾${s.suffix}の内訳'),
                    subtitle: Text(
                      '${s.racks}台・${s.days}日・${s.records}件／BB ${s.bb}・RB ${s.rb}・AT/ART ${s.atArt}'
                      '\n採点${s.scored}件（暫定${s.provisional}件）・グラフ${s.graphs}件',
                    ),
                    trailing: const Icon(Icons.chevron_right),
                  ),
                ),
                const SizedBox(height: 8),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _PscubeSuffixDetails extends StatefulWidget {
  const _PscubeSuffixDetails({
    required this.data,
    required this.store,
    required this.summary,
  });
  final ViewerData data;
  final String store;
  final PscubeSuffixSummary summary;
  @override
  State<_PscubeSuffixDetails> createState() => _PscubeSuffixDetailsState();
}

class _PscubeSuffixDetailsState extends State<_PscubeSuffixDetails> {
  var _graph = false;
  final _scroll = ScrollController();
  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final summary = widget.summary;
    final days = summary.entries.map((e) => e.$1.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    return Scaffold(
      appBar: AppBar(title: Text('末尾${summary.suffix}の内訳')),
      floatingActionButton: ScrollTopButton(controller: _scroll),
      body: SafeArea(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
          children: [
            Text(
              '${storeDisplayName(widget.store)}・${summary.racks}台・${summary.days}日・${summary.records}件',
              style: const TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 16),
            for (final day in days) ...[
              MachineSection(
                machine: dayWithWeekday(day),
                showMachine: true,
                entries: summary.entries.where((e) => e.$1.day == day).toList(),
                graph: _graph,
                onGraphChanged: (v) => setState(() => _graph = v),
                onTap: (record, score) => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) =>
                        ViewerRecordPage(data: widget.data, record: record),
                  ),
                ),
              ),
              const SizedBox(height: 24),
            ],
          ],
        ),
      ),
    );
  }
}
