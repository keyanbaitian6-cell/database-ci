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

String _count(int value) =>
    value > 0 ? signedMedals(value).substring(1) : '$value';

Color _netColor(int value) => value > 0
    ? AppColors.linkBlue
    : value < 0
    ? const Color(0xFFC62828)
    : AppColors.ash;

/// 「0回転」「500回転未満」として数える境目（その日のまとめの注記用）。
const lowGamesLimit = 500;

/// 「　40台が0回転。8台が500回転未満」（全角空白つき）。どちらも0台なら空（共有カレンダー share_viewer の lowGamesNote と同じ数え方）。
String lowGamesNote(List<SlotRecord> records) {
  final zero = records.where((r) => r.games == 0).length;
  final short =
      records.where((r) => r.games > 0 && r.games < lowGamesLimit).length;
  final parts = [
    if (zero > 0) '$zero台が0回転',
    if (short > 0) '$short台が$lowGamesLimit回転未満',
  ];
  return parts.isEmpty ? '' : '　${parts.join('。')}';
}

/// その日・その店のTOP10と強かった機種5選。イベント名の編集もここから。
class CalendarDayPage extends StatefulWidget {
  const CalendarDayPage({
    super.key,
    required this.store,
    required this.day,
    required this.records,
    this.birthdays = const [],
    required this.eventFor,
    required this.onEditEvent,
    this.onOpenRecord,
  });

  final String store, day;
  final List<SlotRecord> records;
  final List<String> birthdays;
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
    // P-STATION：サイトセブン・アナスロで補った台の推定差枚も合計に入る。出典ごとに正しく出し分ける。
    final estimatedRows = [
      for (final r in usable)
        if (r.pscubeNetEstimate != null) r,
    ];
    final estimated = estimatedRows.length;
    final hasSite777Estimate = estimatedRows.any(
      (r) => r.extra['source_site'] == 'site777',
    );
    final hasAnasloEstimate = estimatedRows.any(
      (r) => r.extra['source_site'] == 'anaslo',
    );
    final estimateSources = [
      if (hasSite777Estimate) 'サイトセブンのグラフ画像から計算',
      if (hasAnasloEstimate) 'アナスロの集計時点の値',
    ];
    final estimateSourceText = estimateSources.isEmpty
        ? 'グラフ等から計算'
        : estimateSources.join('・');
    final judged = [
      for (final r in usable)
        if (r.won != null) r.won!,
    ];
    final won = judged.where((w) => w).length;
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
            if (widget.birthdays.isNotEmpty) ...[
              const SizedBox(height: 4),
              const Text(
                'キャラ誕生日',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
              ),
              for (final name in widget.birthdays)
                Text(
                  '🎂 $name',
                  key: ValueKey('calendar-day-birthday-$name'),
                  style: const TextStyle(color: Color(0xFF9A4D00)),
                ),
            ],
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
                    TextSpan(
                      text:
                          '（$netLabelがわかった台 ${nets.length}/${usable.length}台'
                          '${estimated > 0 ? '・うち推定$estimated台（$estimateSourceText）' : ''}'
                          '${lowGamesNote(usable)}）',
                    ),
                  ],
                ),
              ),
            if (showWinRate(nets.length, judged.length))
              Text(
                'この日は$netLabelの分からない台が多いため勝率：'
                '${judged.length}台中$won台プラス（${winRateLabel(won, judged.length)}）',
                key: const ValueKey('calendar-day-win-rate'),
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
                          '${r.rack}番${r.rainbow ? rainbowMark : ''}　${displayMachineName(r.machine)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          '${_count(r.games)}G　BB${r.bb} RB${r.rb}',
                        ),
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
              )
            else if (estimated > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  '推定差枚は$estimateSourceTextで、確定値ではありません（※は要確認）。',
                  style: const TextStyle(fontSize: 12, color: AppColors.ash),
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
