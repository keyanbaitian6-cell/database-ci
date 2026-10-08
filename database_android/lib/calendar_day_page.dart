import 'package:flutter/material.dart';

import 'date_events.dart';
import 'event_calendar_page.dart' show eventCellLabel;
import 'list_views.dart' show dayWithWeekday, displayMachineName;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';

/// 「強かった機種」に入れる最小の台数（1台だけの機種は、たまたまに左右されるため入れない）。
const strongMachineMinRacks = 2;

/// 機種ごとの1台あたりの平均回転数。
class MachineGames {
  const MachineGames({
    required this.machine,
    required this.racks,
    required this.average,
  });
  final String machine;
  final int racks;
  final int average;
}

/// カレンダーの日付を押したときの、その日・その店のまとめ（2026-10-09 利用者指定）。
/// [top]：差枚の多い順の10台（メルヘンは推定差枚。差枚の無い台は入れない）。
/// [machines]：強かった機種5選＝1台あたりの平均回転数の多い順（[strongMachineMinRacks]台以上の機種）。
/// 数値異常の台（整備中の 88888888 など）はどちらにも入れない（`dailyNet` と同じ）。
({List<SlotRecord> top, List<MachineGames> machines}) calendarDaySummary(
  Iterable<SlotRecord> records,
) {
  final usable = [
    for (final r in records)
      if (!hasImplausibleNumbers(r)) r,
  ];
  final top =
      [
        for (final r in usable)
          if (r.netValue != null) r,
      ]..sort((a, b) {
        final net = b.netValue!.compareTo(a.netValue!);
        if (net != 0) return net;
        final games = b.games.compareTo(a.games);
        return games != 0 ? games : a.rack.compareTo(b.rack);
      });
  final byMachine = <String, List<SlotRecord>>{};
  for (final r in usable) {
    (byMachine[r.machine] ??= []).add(r);
  }
  final machines =
      [
        for (final e in byMachine.entries)
          if (e.value.length >= strongMachineMinRacks)
            MachineGames(
              machine: e.key,
              racks: e.value.length,
              average:
                  (e.value.fold(0, (sum, r) => sum + r.games) / e.value.length)
                      .round(),
            ),
      ]..sort((a, b) {
        final average = b.average.compareTo(a.average);
        if (average != 0) return average;
        final racks = b.racks.compareTo(a.racks);
        return racks != 0 ? racks : a.machine.compareTo(b.machine);
      });
  return (top: top.take(10).toList(), machines: machines.take(5).toList());
}

String _count(int value) => value > 0 ? signedMedals(value).substring(1) : '$value';

Color _netColor(int value) => value > 0
    ? AppColors.linkBlue
    : value < 0
    ? const Color(0xFFC62828)
    : AppColors.ash;

/// その日・その店のTOP10と強かった機種5選。イベント名の編集もここから。
class CalendarDayPage extends StatefulWidget {
  const CalendarDayPage({
    super.key,
    required this.store,
    required this.day,
    required this.records,
    required this.eventFor,
    required this.onEditEvent,
    this.onOpenRecord,
  });

  final String store, day;
  final List<SlotRecord> records;
  final DateEvent? Function() eventFor;
  final Future<void> Function() onEditEvent;

  /// 台を押したとき（台の詳細）。null なら押せない。
  final void Function(SlotRecord record)? onOpenRecord;

  @override
  State<CalendarDayPage> createState() => _CalendarDayPageState();
}

class _CalendarDayPageState extends State<CalendarDayPage> {
  late final _summary = calendarDaySummary(widget.records);

  @override
  Widget build(BuildContext context) {
    final pscube = isPscubeStore(widget.store);
    final netLabel = pscube ? '差枚' : '推定差枚';
    final usable = [
      for (final r in widget.records)
        if (!hasImplausibleNumbers(r)) r,
    ];
    final nets = [
      for (final r in usable)
        if (r.netValue != null) r.netValue!,
    ];
    final event = eventCellLabel(widget.eventFor());
    const heading = TextStyle(fontSize: 16, fontWeight: FontWeight.w800);
    return Scaffold(
      appBar: AppBar(title: Text(dayWithWeekday(widget.day))),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
          children: [
            Text(
              storeDisplayName(widget.store),
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Expanded(
                  child: Text(
                    'イベント：${event.isEmpty ? 'なし' : event}',
                    key: const ValueKey('calendar-day-event'),
                  ),
                ),
                TextButton.icon(
                  onPressed: () async {
                    await widget.onEditEvent();
                    if (mounted) setState(() {});
                  },
                  icon: const Icon(Icons.edit_outlined, size: 18),
                  label: const Text('イベントを編集'),
                ),
              ],
            ),
            if (nets.isNotEmpty)
              Text.rich(
                TextSpan(
                  children: [
                    TextSpan(text: '総$netLabel '),
                    TextSpan(
                      text: signedMedals(nets.reduce((a, b) => a + b)),
                      style: TextStyle(
                        fontWeight: FontWeight.w800,
                        color: _netColor(nets.reduce((a, b) => a + b)),
                      ),
                    ),
                    TextSpan(text: '（$netLabelがわかった台 ${nets.length}/${usable.length}台）'),
                  ],
                ),
              ),
            const SizedBox(height: 16),
            Text('TOP10（$netLabelの多い順）', style: heading),
            const SizedBox(height: 4),
            if (_summary.top.isEmpty)
              const Notice(text: 'この日は差枚がわかる台がありません。')
            else
              Card(
                child: Column(
                  children: [
                    for (final (i, r) in _summary.top.indexed)
                      ListTile(
                        key: ValueKey('calendar-top-${r.rack}'),
                        dense: true,
                        leading: Text(
                          '${i + 1}',
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        title: Text(
                          '${r.rack}番　${displayMachineName(r.machine)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text('${_count(r.games)}G　BB${r.bb} RB${r.rb}'),
                        trailing: Text(
                          r.netText!,
                          style: TextStyle(
                            fontWeight: FontWeight.w800,
                            color: _netColor(r.netValue!),
                          ),
                        ),
                        onTap: widget.onOpenRecord == null
                            ? null
                            : () => widget.onOpenRecord!(r),
                      ),
                  ],
                ),
              ),
            if (!pscube)
              const Padding(
                padding: EdgeInsets.only(top: 4),
                child: Text(
                  '推定差枚はグラフと最大持玉からの計算で、確定値ではありません（※は要確認）。',
                  style: TextStyle(fontSize: 12, color: AppColors.ash),
                ),
              ),
            const SizedBox(height: 20),
            const Text('強かった機種5選（1台あたりの平均回転数）', style: heading),
            const SizedBox(height: 4),
            if (_summary.machines.isEmpty)
              const Notice(text: '$strongMachineMinRacks台以上ある機種がありません。')
            else
              Card(
                child: Column(
                  children: [
                    for (final (i, m) in _summary.machines.indexed)
                      ListTile(
                        key: ValueKey('calendar-machine-$i'),
                        dense: true,
                        leading: Text(
                          '${i + 1}',
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        title: Text(
                          displayMachineName(m.machine),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Text(
                          '${_count(m.average)}G（${m.racks}台）',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                      ),
                  ],
                ),
              ),
            const Padding(
              padding: EdgeInsets.only(top: 4),
              child: Text(
                '$strongMachineMinRacks台以上ある機種から。数値異常の台は数えていません。',
                style: TextStyle(fontSize: 12, color: AppColors.ash),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
