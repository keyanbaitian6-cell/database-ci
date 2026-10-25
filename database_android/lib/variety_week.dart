import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName, shortDayLabel;
import 'models.dart';
import 'rainbow_today.dart';
import 'scoring.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// 選んだ日を含む7日（選んだ日を右端に、カレンダーの日数、古い順。2026-10-13 利用者「当日を含む7日間」）。
List<String> varietyWeekDays(String day) => [
  for (var i = 6; i >= 0; i--)
    DateTime.parse('${day}T00:00:00Z')
        .subtract(Duration(days: i))
        .toIso8601String()
        .substring(0, 10),
];

class VarietyWeekRack {
  const VarietyWeekRack(this.current, this.records, this.high);
  final SlotRecord current;
  final List<SlotRecord> records;
  final List<({SlotRecord record, ScoreResult score})> high;
  int get rainbowDays => records.where((r) => r.rainbow).length;
  SlotRecord get openRecord => high.isNotEmpty
      ? high.first.record
      : records.isNotEmpty
      ? records.last
      : current;
}

/// 共有ページ varietyWeek と同じ並び・期間・台番号単位。未取得を🌈なしの7日と断定しない。
List<VarietyWeekRack> varietyWeekRacks(
  List<SlotRecord> all,
  String store,
  String day,
) {
  if (store != 'saiwaichou') return const [];
  final byDay = <String, List<SlotRecord>>{};
  for (final r in all) {
    if (r.store == store && !hasImplausibleNumbers(r)) {
      (byDay[r.day] ??= []).add(r);
    }
  }
  final recent = byDay.keys.toList()..sort((a, b) => b.compareTo(a));
  final days = recent.take(14).toList();
  if (days.isEmpty) return const [];
  final usual = days
      .map((d) => byDay[d]!.length)
      .reduce((a, b) => a > b ? a : b);
  final lineup =
      byDay[days.firstWhere((d) => byDay[d]!.length >= usual * 0.8)]!;
  final counts = <String, int>{};
  for (final r in lineup) {
    counts[r.machine] = (counts[r.machine] ?? 0) + 1;
  }
  final window = varietyWeekDays(day);
  final history = <int, List<SlotRecord>>{};
  for (final d in window) {
    for (final r in byDay[d] ?? <SlotRecord>[]) {
      (history[r.rack] ??= []).add(r);
    }
  }
  final result = <VarietyWeekRack>[];
  for (final r in lineup) {
    if (counts[r.machine] != 1) continue;
    final records = history[r.rack] ?? <SlotRecord>[];
    final high = <({SlotRecord record, ScoreResult score})>[];
    for (final record in records) {
      final score = scoreRecord(record, all);
      if (score.total != null && score.total! >= 70) {
        high.add((record: record, score: score));
      }
    }
    high.sort((a, b) {
      final points = b.score.total!.compareTo(a.score.total!);
      return points != 0 ? points : b.record.day.compareTo(a.record.day);
    });
    result.add(VarietyWeekRack(r, records, high));
  }
  return result..sort((a, b) => a.current.rack.compareTo(b.current.rack));
}

class VarietyWeekPage extends StatefulWidget {
  const VarietyWeekPage({
    super.key,
    required this.data,
    required this.store,
    required this.day,
    this.currentData,
    this.onDayChanged,
  });
  final ViewerData data;
  final String store, day;
  final ViewerData Function()? currentData;
  final ValueChanged<String>? onDayChanged;

  @override
  State<VarietyWeekPage> createState() => _VarietyWeekPageState();
}

class _VarietyWeekPageState extends State<VarietyWeekPage> {
  late String _day = widget.day;
  late ViewerData _data = widget.data;
  bool _today = false;

  @override
  void initState() {
    super.initState();
    // 開いたあとに読み込みが終わった内容（ほかの端末の🌈など）も週表に出す。
    viewerDataRevision.addListener(_dataChanged);
  }

  void _dataChanged() {
    final latest = widget.currentData?.call();
    if (latest != null && mounted) setState(() => _data = latest);
  }

  @override
  void dispose() {
    viewerDataRevision.removeListener(_dataChanged);
    super.dispose();
  }

  Future<void> _open(SlotRecord record) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ViewerRecordPage(data: _data, record: record),
      ),
    );
    if (mounted) setState(() => _data = widget.currentData?.call() ?? _data);
  }

  Widget _rack(VarietyWeekRack x, {required bool candidate}) {
    final best = x.high.isEmpty ? null : x.high.first;
    return Card(
      key: ValueKey(
        'week-${candidate ? 'candidate' : 'marked'}-${x.current.rack}',
      ),
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        title: Text(
          '${x.current.rack}番　${displayMachineName(x.current.machine)}',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                best == null ? '70点以上の記録なし' : '70点以上あり',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: best == null
                      ? FontWeight.normal
                      : FontWeight.w700,
                  color: best == null ? AppColors.ash : AppColors.linkBlue,
                ),
              ),
              if (best != null)
                Text(
                  '最高 ${best.score.total!.toStringAsFixed(1)}点'
                  '（${shortDayLabel(best.record.day)}・${best.score.provisional ? '暫定' : '参考'}）',
                  style: const TextStyle(fontSize: 13, color: AppColors.carbon),
                ),
              const SizedBox(height: 5),
              Text(
                x.records.length == 7
                    ? '7日分の記録あり'
                    : '記録${x.records.length}/7日・未取得${7 - x.records.length}日',
                style: const TextStyle(fontSize: 12, color: AppColors.ash),
              ),
              if (!candidate)
                Text(
                  '🌈の記録 ${x.rainbowDays}日',
                  style: const TextStyle(fontSize: 12, color: AppColors.ash),
                ),
              if (x.records.any((r) => r.machine != x.current.machine))
                const Text(
                  '入れ替え前の機種を含む履歴',
                  style: TextStyle(fontSize: 12, color: AppColors.ash),
                ),
            ],
          ),
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => _open(x.openRecord),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final days = varietyWeekDays(_day);
    final rows = _today
        ? const <VarietyWeekRack>[]
        : varietyWeekRacks(_data.records, widget.store, _day);
    final candidates = rows
        .where((x) => x.records.isNotEmpty && x.rainbowDays == 0)
        .toList();
    final marked = rows.where((x) => x.rainbowDays > 0).toList();
    final unknown = rows.where((x) => x.records.isEmpty).length;
    return Scaffold(
      appBar: AppBar(
        title: Text(_today ? 'バラエティ🌈 本日' : 'バラエティの候補'),
        bottom: _today
            ? null
            : ViewerDateBar(
                days: viewerDays(_data.records, widget.store),
                day: _day,
                eventFor: (d) => _data.dateEventFor(widget.store, d)?.name,
                event: _data.dateEventFor(widget.store, _day)?.name,
                onChanged: (d) {
                  if (d != null) {
                    setState(() => _day = d);
                    widget.onDayChanged?.call(d);
                  }
                },
              ),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                ChoiceChip(
                  label: const Text('7日間の候補'),
                  labelStyle: TextStyle(
                    color: !_today ? Colors.white : AppColors.carbon,
                  ),
                  selected: !_today,
                  onSelected: (_) => setState(() => _today = false),
                ),
                const SizedBox(width: 8),
                ChoiceChip(
                  label: const Text('本日'),
                  labelStyle: TextStyle(
                    color: _today ? Colors.white : AppColors.carbon,
                  ),
                  selected: _today,
                  onSelected: (_) => setState(() => _today = true),
                ),
              ],
            ),
          ),
          Expanded(
            child: _today
                ? RainbowTodayList(
                    data: _data,
                    store: widget.store,
                    currentData: widget.currentData,
                    onDataChanged: (data) => setState(() => _data = data),
                  )
                : _weekBody(days, candidates, marked, unknown),
          ),
        ],
      ),
    );
  }

  Widget _weekBody(
    List<String> days,
    List<VarietyWeekRack> candidates,
    List<VarietyWeekRack> marked,
    int unknown,
  ) => SafeArea(
    child: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text(
          '7日間🌈なしの候補',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 4),
        Text(
          '${days.first}〜${days.last}',
          style: const TextStyle(fontSize: 15, color: AppColors.ash),
        ),
        const SizedBox(height: 8),
        const Text(
          '幸町・1台機種。選んだ日を含む7日間に🌈の記録がない台です。'
          '70点以上の日がある台も候補に残し、点数を添えます。',
          style: TextStyle(fontSize: 13, color: AppColors.ash),
        ),
        const SizedBox(height: 16),
        Text(
          '候補 ${candidates.length}台',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        if (candidates.isEmpty)
          const Text('候補はありません', style: TextStyle(color: AppColors.ash)),
        for (final x in candidates) _rack(x, candidate: true),
        if (candidates.any((x) => x.records.length < 7))
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: Text(
              '未取得の日の🌈はわかりません。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
        ExpansionTile(
          key: ValueKey('week-marked-$_day'),
          tilePadding: EdgeInsets.zero,
          title: Text(
            '🌈が付いた台（${marked.length}台）',
            style: const TextStyle(fontSize: 15),
          ),
          children: [for (final x in marked) _rack(x, candidate: false)],
        ),
        if (unknown > 0)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(
              '記録がない台：$unknown台（候補に含めていません）',
              style: const TextStyle(fontSize: 12, color: AppColors.ash),
            ),
          ),
      ],
    ),
  );
}
