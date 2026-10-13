import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName, shortDayLabel;
import 'models.dart';
import 'scoring.dart';
import 'theme.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// 選んだ日の前日までの7日（カレンダーの日数、古い順）。
List<String> varietyWeekDays(String day) => [
  for (var i = 7; i >= 1; i--)
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

  Future<void> _open(SlotRecord record) async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ViewerRecordPage(data: _data, record: record),
      ),
    );
    if (mounted) setState(() => _data = widget.currentData?.call() ?? _data);
  }

  Widget _group(
    String title,
    List<VarietyWeekRack> rows, {
    bool high = false,
  }) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        '$title（${rows.length}台）',
        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
      ),
      const SizedBox(height: 8),
      if (rows.isEmpty)
        const Text('該当する台はありません', style: TextStyle(color: AppColors.ash))
      else
        Card(
          child: Column(
            children: [
              for (final x in rows)
                ListTile(
                  key: ValueKey(
                    'week-${high ? 'high' : 'none'}-${x.current.rack}',
                  ),
                  title: Text(
                    '${x.current.rack}番　${displayMachineName(x.current.machine)}',
                  ),
                  subtitle: Text(
                    [
                      if (high) ...[
                        '最高：${shortDayLabel(x.high.first.record.day)} '
                            '${x.high.first.score.provisional ? '暫定' : '参考'} '
                            '${x.high.first.score.total!.toStringAsFixed(1)}点'
                            '${x.high.first.record.rainbow ? rainbowMark : ''}',
                        '70点以上 ${x.high.length}日',
                      ],
                      '記録${x.records.length}/7日・期間内の$rainbowMark ${x.rainbowDays}日',
                      if (x.records.length < 7) '未取得の日は判定できません',
                      if (x.records.any((r) => r.machine != x.current.machine))
                        '入れ替え前の機種を含む台番号の履歴',
                    ].join('\n'),
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _open(x.openRecord),
                ),
            ],
          ),
        ),
      const SizedBox(height: 20),
    ],
  );

  @override
  Widget build(BuildContext context) {
    final days = varietyWeekDays(_day);
    final rows = varietyWeekRacks(_data.records, widget.store, _day);
    final unknown = rows.where((x) => x.records.isEmpty).length;
    return Scaffold(
      appBar: AppBar(
        title: const Text('バラエティ🌈・過去7日'),
        bottom: ViewerDateBar(
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
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              '${days.first}〜${days.last}',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            const Text(
              '幸町の記録のそろった最新の日の1台機種。選んだ日の前日まで7日間を台番号で比較します。'
              '70点以上と🌈なしは別々に表示し、両方に当てはまる台は両方に出ます。'
              '🌈なしは取得済みの記録で判定します。採点は既存の実績点（暫定を含む）です。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
            const SizedBox(height: 16),
            _group(
              '70点以上になった台',
              rows.where((x) => x.high.isNotEmpty).toList(),
              high: true,
            ),
            _group(
              '🌈がない台',
              rows
                  .where((x) => x.records.isNotEmpty && x.rainbowDays == 0)
                  .toList(),
            ),
            if (unknown > 0)
              Text(
                '期間内の記録なし：$unknown台（🌈の有無はわかりません）',
                style: const TextStyle(color: AppColors.ash),
              ),
          ],
        ),
      ),
    );
  }
}
