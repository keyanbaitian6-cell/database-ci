import 'package:flutter/material.dart';

import 'machine_sections.dart';
import 'list_views.dart' show dayWithWeekday;
import 'models.dart';
import 'pscube_suffix.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_bridge.dart';
import 'viewer_pages.dart';

class PscubeSuffixPage extends StatefulWidget {
  const PscubeSuffixPage({
    super.key,
    required this.data,
    required this.store,
    required this.day,
    this.onDayChanged,
    this.onDataChanged,
    this.saveSuffixEvent,
  });
  final ViewerData data;
  final String store, day;
  final ValueChanged<String>? onDayChanged;
  final ValueChanged<ViewerData>? onDataChanged;
  final Future<String?> Function(String scope, String day, bool enabled)?
  saveSuffixEvent;
  @override
  State<PscubeSuffixPage> createState() => _PscubeSuffixPageState();
}

class _PscubeSuffixPageState extends State<PscubeSuffixPage> {
  late String _day = widget.day;
  late ViewerData _data = widget.data;
  bool _savingMark = false;
  var _period = PscubeSuffixPeriod.day;
  var _type = PscubeSuffixType.all;
  final _scroll = ScrollController();
  Object? _calculatedFor;
  PscubeSuffixReport? _report;
  PscubeSuffixReport? _selectedDay;
  List<PscubeSuffixReport> _history = [];
  bool _allHistory = false;
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
      _data.records,
      store: widget.store,
      day: _day,
      period: _period,
      type: _type,
    );
    final selectedDay = _period == PscubeSuffixPeriod.day
        ? report
        : summarizePscubeSuffixes(
            _data.records,
            store: widget.store,
            day: _day,
            type: _type,
          );
    final history = _period == PscubeSuffixPeriod.day
        ? summarizePscubeSuffixes(
            _data.records,
            store: widget.store,
            day: _day,
            period: PscubeSuffixPeriod.week,
            type: _type,
          )
        : report;
    setState(() {
      _selectedDay = selectedDay;
      _history = history.daily;
      _report = report;
      _calculatedFor = key;
    });
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    _day = day;
    _allHistory = false;
    widget.onDayChanged?.call(day);
    _calculate();
  }

  Future<void> _setMark(bool enabled) async {
    if (_savingMark) return;
    final day = _day;
    setState(() => _savingMark = true);
    try {
      final text = await (widget.saveSuffixEvent ?? setPscubeSuffixEvent)(
        widget.store,
        day,
        enabled,
      );
      if (text == null) throw StateError('印を保存できませんでした。');
      final data = ViewerData.parse(text);
      widget.onDataChanged?.call(data);
      if (mounted) {
        setState(() => _data = data);
        _calculate();
      }
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('末尾イベの印を保存できませんでした。\n$error')));
    } finally {
      if (mounted) setState(() => _savingMark = false);
    }
  }

  void _open(PscubeSuffixSummary summary) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => _PscubeSuffixDetails(
          data: _data,
          store: widget.store,
          summary: summary,
        ),
      ),
    );
  }

  String _average(double? value) => value?.toStringAsFixed(1) ?? '—';
  String _positive(PscubeSuffixSummary s) => s.positivePercent == null
      ? 'プラス終点 —（グラフなし）'
      : 'プラス終点 ${s.positivePercent!.toStringAsFixed(1)}%（${s.positiveGraphs}/${s.graphs}件）';

  Widget _rankRow(PscubeSuffixReport report, PscubeSuffixSummary s) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            SizedBox(
              width: 40,
              child: Text(
                '${report.rankOf(s)}位',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
            ),
            TextButton(
              onPressed: () => _open(s),
              child: Text(
                '末尾${s.suffix}',
                style: const TextStyle(
                  fontSize: 19,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            const Spacer(),
            ScorePill(
              text: '${_average(s.averageScore)}点',
              tier: scoreTier(s.averageScore),
            ),
          ],
        ),
        Text(
          '平均MY ${_average(s.averageMy)}・平均G ${_average(s.averageGames)}',
          style: const TextStyle(fontSize: 12),
        ),
        Text(
          '${_positive(s)}\n採点 ${s.scored}/${s.records}件（暫定${s.provisional}件）・${s.racks}台',
          style: const TextStyle(fontSize: 12, color: AppColors.ash),
        ),
      ],
    ),
  );

  Widget _ranking(PscubeSuffixReport report, String title, String key) {
    final top = report.ranked.where((s) => report.rankOf(s) <= 3).toList();
    return Card(
      key: ValueKey(key),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            if (top.isEmpty)
              Text(report.records == 0 ? '対象の記録がありません' : '採点なし（500G以下など）')
            else ...[
              Text(
                '平均点の首位：${report.leaders.map((s) => '末尾${s.suffix}').join('・')}'
                '${report.leaders.length > 1 ? '（同点）' : ''}',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              for (final s in top) ...[
                _rankRow(report, s),
                if (s != top.last) const Divider(),
              ],
            ],
            TextButton(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                useSafeArea: true,
                builder: (context) => DraggableScrollableSheet(
                  initialChildSize: 0.75,
                  maxChildSize: 0.95,
                  minChildSize: 0.4,
                  expand: false,
                  builder: (context, controller) => ListView(
                    controller: controller,
                    padding: const EdgeInsets.all(16),
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              title,
                              style: const TextStyle(
                                fontSize: 17,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                          IconButton(
                            tooltip: '閉じる',
                            onPressed: () => Navigator.pop(context),
                            icon: const Icon(Icons.close),
                          ),
                        ],
                      ),
                      const Text('平均点の高い順。同点は同順位。'),
                      for (final s in report.ranked) _rankRow(report, s),
                      for (final s in report.summaries.where(
                        (s) => s.averageScore == null,
                      ))
                        ListTile(
                          title: Text('末尾${s.suffix}'),
                          subtitle: Text(
                            s.records == 0 ? '記録なし' : '採点なし・${s.records}件',
                          ),
                          onTap: s.records == 0 ? null : () => _open(s),
                        ),
                    ],
                  ),
                ),
              ),
              child: const Text('8末尾すべての順位・内訳を見る'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _dayHistory() {
    final days = _allHistory ? _history : _history.take(7).toList();
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(12, 12, 12, 4),
            child: Text(
              '日別の首位',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(
              '${_period == PscubeSuffixPeriod.day ? '過去7日' : _period.label}・平均点の比較。日付をタップしてその日の順位へ。',
              style: const TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
          if (days.isEmpty)
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('対象の記録がありません'),
            ),
          for (final d in days)
            ListTile(
              selected: d.end == _day,
              selectedTileColor: AppColors.ice,
              onTap: () {
                _changeDay(d.end);
                _scroll.animateTo(
                  0,
                  duration: const Duration(milliseconds: 250),
                  curve: Curves.easeOut,
                );
              },
              title: Wrap(
                spacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    dayWithWeekday(d.end),
                    style: const TextStyle(fontSize: 14),
                  ),
                  if (_data.dateEventFor(widget.store, d.end) != null)
                    Semantics(
                      label: '末尾イベ',
                      child: const ExcludeSemantics(
                        child: Chip(
                          label: Text('末尾イベ'),
                          visualDensity: VisualDensity.compact,
                        ),
                      ),
                    ),
                ],
              ),
              subtitle: Text(
                d.leaders.isEmpty
                    ? '採点なし'
                    : '${d.leaders.map((s) => '末尾${s.suffix}').join('・')}'
                          '${d.leaders.length > 1 ? '（同点）' : ''}\n'
                          '平均 ${_average(d.leaders.first.averageScore)}点・採点 '
                          '${d.leaders.map((s) => '${s.suffix}：${s.scored}/${s.records}件').join('／')}',
                style: const TextStyle(fontSize: 12),
              ),
              trailing: const Icon(Icons.chevron_right),
            ),
          if (_history.length > 7)
            TextButton(
              onPressed: () => setState(() => _allHistory = !_allHistory),
              child: Text(
                _allHistory ? '直近7記録日に戻す' : '全${_history.length}記録日を表示',
              ),
            ),
        ],
      ),
    );
  }

  Widget _numbers(PscubeSuffixReport report) => Card(
    child: ExpansionTile(
      title: const Text('数値一覧・末尾別の内訳'),
      childrenPadding: const EdgeInsets.all(12),
      children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            showCheckboxColumn: false,
            columnSpacing: 18,
            horizontalMargin: 12,
            headingRowColor: const WidgetStatePropertyAll(AppColors.ice),
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
                        onPressed: s.records == 0 ? null : () => _open(s),
                        child: Text('末尾${s.suffix}'),
                      ),
                    ),
                    DataCell(Text('${s.racks}')),
                    DataCell(Text('${s.records}')),
                    DataCell(Text(_average(s.averageGames))),
                    DataCell(Text(_average(s.averageMy))),
                    DataCell(Text(_average(s.averageScore))),
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
        const SizedBox(height: 8),
        const Text(
          '表は横にスクロールできます。末尾をタップして台ごとの表・グラフへ。',
          style: TextStyle(fontSize: 12, color: AppColors.ash),
        ),
        for (final s in report.summaries.where((s) => s.records > 0))
          ListTile(
            onTap: () => _open(s),
            title: Text('末尾${s.suffix}の内訳'),
            subtitle: Text(
              '${s.racks}台・${s.days}日・${s.records}件／BB ${s.bb}・RB ${s.rb}・AT/ART ${s.atArt}',
            ),
            trailing: const Icon(Icons.chevron_right),
          ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) {
    final ready = _calculatedFor == (_day, _period, _type);
    final report = _report;
    return Scaffold(
      appBar: AppBar(
        title: const Text('末尾別データまとめ'),
        bottom: ViewerDateBar(
          days: viewerDays(_data.records, widget.store),
          day: _day,
          onChanged: _changeDay,
          event: _data.dateEventFor(widget.store, _day)?.name,
          eventFor: (day) => _data.dateEventFor(widget.store, day)?.name,
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
            Card(
              child: SwitchListTile(
                title: const Text('末尾イベの印'),
                subtitle: Text(_savingMark ? '保存中…' : '自分用の印。付ける・外すができます。'),
                value: _data.dateEventFor(widget.store, _day) != null,
                onChanged: _savingMark ? null : _setMark,
              ),
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
            else if (report != null && _selectedDay != null) ...[
              _ranking(
                _selectedDay!,
                '${dayWithWeekday(_day)}の末尾順位',
                'suffix-day-ranking',
              ),
              const SizedBox(height: 8),
              const Text(
                '平均点は既存の採点を集計した結果です。採点件数・暫定件数とあわせて比較してください。',
                style: TextStyle(fontSize: 12, color: AppColors.ash),
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<PscubeSuffixPeriod>(
                initialValue: _period,
                decoration: const InputDecoration(labelText: '比較期間'),
                items: [
                  for (final p in PscubeSuffixPeriod.values)
                    DropdownMenuItem(value: p, child: Text(p.label)),
                ],
                onChanged: (p) {
                  if (p != null && p != _period) {
                    _period = p;
                    _allHistory = false;
                    _calculate();
                  }
                },
              ),
              const SizedBox(height: 12),
              _dayHistory(),
              const SizedBox(height: 16),
              if (_period != PscubeSuffixPeriod.day) ...[
                _ranking(
                  report,
                  '${_period.label}の末尾順位',
                  'suffix-period-ranking',
                ),
                const SizedBox(height: 12),
              ],
              Notice(
                text:
                    '${report.start ?? '保存開始'}〜${report.end}：記録${report.days}日・'
                    '${report.racks}台・${report.records}件（台×日）。末尾0・1・2・3・5・6・7・8を集計。'
                    '${report.excludedInvalid > 0 ? '数値異常${report.excludedInvalid}件は対象外。' : ''}'
                    '${report.excludedSuffix > 0 ? '指定外の末尾${report.excludedSuffix}件は対象外。' : ''}',
              ),
              const SizedBox(height: 12),
              _numbers(report),
              const SizedBox(height: 12),
              const Notice(
                text:
                    '平均G・平均MYは1記録（台×日）あたり。平均点は採点できた記録のみ（暫定を含む）。'
                    '同点は表示と同じ小数1桁で判定。プラス終点は取得済みグラフのうち終点がゼロ線より上の割合（1ピクセル以内はゼロ扱い）。'
                    'MYは差枚ではありません。全機種では機種構成の影響を含むため、機種タイプと内訳も確認できます。',
              ),
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
