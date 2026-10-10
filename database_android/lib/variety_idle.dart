import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart' show displayMachineName, shortDayLabel;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_pages.dart';

/// バラエティの中で、1週間以上ずっと1000G以上回っていない台（利用者指定 2026-10-10
/// 「バラエティの中で一週間以上1000G以上回ってない台をピックアップするページ」）。

/// 「回っていない」とする回転数（この回転数より少ない日）。
const idleGamesLimit = 1000;

/// 何日（記録日）続いたら出すか。
const idleMinDays = 7;

/// 選んだ日から前へ、毎日 [idleGamesLimit] G未満が続いた台。
class IdleRack {
  const IdleRack(this.days);

  /// 続いた日の記録（新しい順）。先頭が選んだ日。
  final List<SlotRecord> days;

  SlotRecord get latest => days.first;
  String get from => days.last.day;
  int get maxGames => days.map((r) => r.games).reduce((a, b) => a > b ? a : b);
}

/// [store] の [day] にバラエティ（その日1〜3台の機種）の台のうち、[day] から前の記録日へ
/// 続けて [idleGamesLimit] G未満だった日が [idleMinDays] 日以上ある台。続いた日数の多い順。
///
/// 同じ店舗・機種・台番号の記録だけを数える（入れ替えた台の前の機種は混ぜない）。店舗に記録が
/// ある日にその台の記録が無ければ（入れ替え前・取り込み漏れ）、そこで数えるのをやめる。
List<IdleRack> idleVarietyRacks(
  List<SlotRecord> all,
  String store,
  String day,
) {
  final storeDays = {
    for (final r in all)
      if (r.store == store && r.day.compareTo(day) <= 0) r.day,
  }.toList()..sort((a, b) => b.compareTo(a));
  if (storeDays.isEmpty || storeDays.first != day) return const [];
  final byRack = <(String, int), Map<String, SlotRecord>>{};
  for (final r in all) {
    if (r.store != store || r.day.compareTo(day) > 0) continue;
    (byRack[(r.machine, r.rack)] ??= {})[r.day] = r;
  }
  final dayRows = [
    for (final r in all)
      if (r.store == store && r.day == day) r,
  ];
  final variety = varietyMachines(dayRows);
  final result = <IdleRack>[];
  for (final r in dayRows) {
    if (!variety.contains(r.machine)) continue;
    final history = byRack[(r.machine, r.rack)]!;
    final run = <SlotRecord>[];
    for (final d in storeDays) {
      final row = history[d];
      if (row == null || row.games >= idleGamesLimit) break;
      run.add(row);
    }
    if (run.length >= idleMinDays) result.add(IdleRack(run));
  }
  result.sort(
    (a, b) => b.days.length != a.days.length
        ? b.days.length.compareTo(a.days.length)
        : a.latest.rack.compareTo(b.latest.rack),
  );
  return result;
}

class VarietyIdlePage extends StatefulWidget {
  const VarietyIdlePage({
    super.key,
    required this.records,
    required this.store,
    required this.day,
    required this.onOpen,
    this.onDayChanged,
    this.eventFor,
  });
  final List<SlotRecord> records;
  final String store, day;
  final ValueChanged<SlotRecord> onOpen;
  final ValueChanged<String>? onDayChanged;
  final String? Function(String day)? eventFor;

  @override
  State<VarietyIdlePage> createState() => _VarietyIdlePageState();
}

class _VarietyIdlePageState extends State<VarietyIdlePage> {
  late String _day = widget.day;

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
  }

  // カレンダーの日付ページと同じ書き方（3桁ごとのカンマ）。
  static String _games(int g) => g > 0 ? signedMedals(g).substring(1) : '$g';

  @override
  Widget build(BuildContext context) {
    final racks = idleVarietyRacks(widget.records, widget.store, _day);
    return Scaffold(
      appBar: AppBar(
        title: const Text('バラエティの回っていない台'),
        bottom: ViewerDateBar(
          days: viewerDays(widget.records, widget.store),
          day: _day,
          event: widget.eventFor?.call(_day),
          eventFor: widget.eventFor,
          onChanged: _changeDay,
        ),
      ),
      body: SafeArea(
        child: ListView(
          key: ValueKey(_day),
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
          children: [
            Text(
              storeDisplayName(widget.store),
              style: const TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 8),
            const Text(
              'バラエティ（その日1〜3台の機種）の台で、選んだ日から前へ毎日'
              '${idleGamesLimit}G未満が$idleMinDays日（記録日）以上続いている台です。'
              '続いた日数の多い順。台を押すとその台の記録を開きます。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            if (racks.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: '当てはまる台はありません',
                body:
                    '記録日が$idleMinDays日分そろっていない日や、入れ替えたばかりの台は数えられません。'
                    '別の日付も選んでみてください。',
              )
            else ...[
              Text(
                '${racks.length}台',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 6),
              Card(
                child: Column(
                  children: [
                    for (final idle in racks)
                      ListTile(
                        key: ValueKey('variety-idle-${idle.latest.key}'),
                        title: Text(
                          '${idle.latest.rack}番　'
                          '${displayMachineName(idle.latest.machine)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          '${idle.days.length}日連続 ${idleGamesLimit}G未満'
                          '（${shortDayLabel(idle.from)}〜）・最多${_games(idle.maxGames)}G\n'
                          '${[for (final r in idle.days.take(idleMinDays)) _games(r.games)].join('・')}G'
                          '${idle.days.length > idleMinDays ? '…' : ''}',
                        ),
                        isThreeLine: true,
                        trailing: Text(
                          '${_games(idle.latest.games)}G',
                          style: const TextStyle(fontWeight: FontWeight.w800),
                        ),
                        onTap: () => widget.onOpen(idle.latest),
                      ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
