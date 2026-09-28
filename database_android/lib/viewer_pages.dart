import 'package:flutter/material.dart';

import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'scoring.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_data.dart';

/// 店舗の記録日（新しい順）。機種・台に記録がない日も選べる。
List<String> viewerDays(List<SlotRecord> records, String store) => {
  for (final r in records)
    if (r.store == store) r.day,
}.toList()..sort((a, b) => b.compareTo(a));

/// スクロール中も操作できる、閲覧画面共通の日付切り替え。
class ViewerDateBar extends StatelessWidget implements PreferredSizeWidget {
  const ViewerDateBar({
    super.key,
    required this.days,
    required this.day,
    required this.onChanged,
    this.event,
    this.allowAll = false,
  });
  final List<String> days;
  final String? day;
  final ValueChanged<String?> onChanged;
  final String? event;
  final bool allowAll;

  @override
  Size get preferredSize => const Size.fromHeight(80);

  @override
  Widget build(BuildContext context) {
    final index = day == null ? -1 : days.indexOf(day!);
    return SizedBox(
      height: preferredSize.height,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: Column(
          children: [
            Row(
              children: [
                IconButton(
                  tooltip: '前の記録日',
                  icon: const Icon(Icons.chevron_left),
                  onPressed: index >= 0 && index + 1 < days.length
                      ? () => onChanged(days[index + 1])
                      : null,
                ),
                Expanded(
                  child: DropdownButtonFormField<String>(
                    key: ValueKey((day, Object.hashAll(days), allowAll)),
                    initialValue: index >= 0 ? day : (allowAll ? '' : null),
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: '表示する日付',
                      isDense: true,
                    ),
                    items: [
                      if (allowAll)
                        const DropdownMenuItem(
                          value: '',
                          child: Text('すべての日付'),
                        ),
                      for (final d in days)
                        DropdownMenuItem(
                          value: d,
                          child: Text(dayWithWeekday(d)),
                        ),
                    ],
                    onChanged: days.isEmpty
                        ? null
                        : (d) => onChanged(d == '' ? null : d),
                  ),
                ),
                IconButton(
                  tooltip: '次の記録日',
                  icon: const Icon(Icons.chevron_right),
                  onPressed: index > 0
                      ? () => onChanged(days[index - 1])
                      : null,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              event ?? '記録がある日へ切り替え',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 11,
                color: event == null ? AppColors.ash : AppColors.appleBlue,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class ViewerMachinePage extends StatefulWidget {
  const ViewerMachinePage({
    super.key,
    required this.data,
    required this.store,
    required this.machine,
    required this.day,
    this.onDayChanged,
  });
  final ViewerData data;
  final String store, machine, day;
  final ValueChanged<String>? onDayChanged;
  @override
  State<ViewerMachinePage> createState() => _ViewerMachinePageState();
}

class _ViewerMachinePageState extends State<ViewerMachinePage> {
  late String _day = widget.day;
  bool _graph = false;
  String? _calculatedDay;
  List<(SlotRecord, ScoreResult)> _entries = [];
  Set<int> _candidateRacks = {};

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    if (_calculatedDay != _day) {
      final rows =
          data.records
              .where(
                (r) =>
                    r.store == widget.store &&
                    r.machine == widget.machine &&
                    r.day == _day,
              )
              .toList()
            ..sort((a, b) => a.rack.compareTo(b.rack));
      _entries = [for (final r in rows) (r, scoreRecord(r, data.records))];
      _candidateRacks = {
        for (final c in dayCandidates(rows, data.records).candidates)
          c.record.rack,
      };
      _calculatedDay = _day;
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(displayMachineName(widget.machine)),
        bottom: ViewerDateBar(
          days: viewerDays(data.records, widget.store),
          day: _day,
          event: data.dateEventFor(widget.store, _day)?.name,
          onChanged: _changeDay,
        ),
      ),
      body: SafeArea(
        child: ListView(
          key: ValueKey(_day),
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              storeNames[widget.store] ?? widget.store,
              style: const TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            if (_entries.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: 'この日の記録はありません',
                body: 'この機種の記録がある別の日付を選んでください。',
              )
            else
              MachineSection(
                machine: widget.machine,
                entries: _entries,
                candidateRacks: _candidateRacks,
                graph: _graph,
                onGraphChanged: (v) => setState(() => _graph = v),
                onTap: (record, score) => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => ViewerRecordPage(
                      data: data,
                      record: record,
                      onDayChanged: _changeDay,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// 同じ店舗・機種・台番号を保って日付を変える。別機種へ入れ替わった日は混ぜない。
class ViewerRecordPage extends StatefulWidget {
  const ViewerRecordPage({
    super.key,
    required this.data,
    required this.record,
    this.onDayChanged,
  });
  final ViewerData data;
  final SlotRecord record;
  final ValueChanged<String>? onDayChanged;
  @override
  State<ViewerRecordPage> createState() => _ViewerRecordPageState();
}

class _ViewerRecordPageState extends State<ViewerRecordPage> {
  late String _day = widget.record.day;

  @override
  Widget build(BuildContext context) {
    final original = widget.record;
    final record = widget.data.records
        .where(
          (r) =>
              r.store == original.store &&
              r.machine == original.machine &&
              r.rack == original.rack &&
              r.day == _day,
        )
        .firstOrNull;
    final bar = ViewerDateBar(
      days: viewerDays(widget.data.records, original.store),
      day: _day,
      event: widget.data.dateEventFor(original.store, _day)?.name,
      onChanged: (day) {
        if (day == null || day == _day) return;
        setState(() => _day = day);
        widget.onDayChanged?.call(day);
      },
    );
    if (record == null) {
      return Scaffold(
        appBar: AppBar(title: Text('${original.rack}番台'), bottom: bar),
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text(displayMachineName(original.machine)),
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: 'この日の記録はありません',
                body: '同じ店舗・機種・台番号の記録がありません。別の日付を選んでください。',
              ),
            ],
          ),
        ),
      );
    }
    return SavedGraphPage(
      key: ValueKey(record.key),
      record: record,
      score: scoreRecord(record, widget.data.records),
      allRecords: widget.data.records,
      dateNavigation: bar,
    );
  }
}
