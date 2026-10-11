import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart' show displayMachineName, shortDayLabel;
import 'models.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_bridge.dart';
import 'viewer_pages.dart';

/// バラエティの中で、しばらく回っていない台（利用者指定 2026-10-10「バラエティの中で一週間以上
/// 1000G以上回ってない台をピックアップするページ」。期間・ゲーム数はプルダウンで選び、期間は
/// カレンダーの日数で数える「カレンダーの日数でいいよ」）。

/// 期間（カレンダーの日数）の選択肢と既定値。
const idleDayChoices = [3, 5, 7, 10, 14];
const idleDefaultDays = 7;

/// 「回っていない」とする回転数（この回転数より少ない日）の選択肢と既定値。
const idleGamesChoices = [500, 1000, 1500, 2000, 3000];
const idleDefaultGames = 1000;

/// 端末に覚える選択の名前（閲覧ページの他の保存名と重ならない）。
const idleDaysKey = 'database-viewer-idle-days';
const idleGamesKey = 'database-viewer-idle-games';

/// 選んだ日から前へ、記録のある日がどれも決めた回転数未満だった台。
class IdleRack {
  const IdleRack(this.days);

  /// 続いた日の記録（新しい順）。先頭が選んだ日。
  final List<SlotRecord> days;

  SlotRecord get latest => days.first;
  String get from => days.last.day;
  int get maxGames => days.map((r) => r.games).reduce((a, b) => a > b ? a : b);

  /// 続いた期間（カレンダーの日数、最初の日と選んだ日を含む）。
  int get spanDays => calendarDays(from, latest.day);
}

/// [from] から [to] までのカレンダーの日数（両端を含む）。
int calendarDays(String from, String to) =>
    DateTime.parse('${to}T00:00:00Z')
        .difference(DateTime.parse('${from}T00:00:00Z'))
        .inDays +
    1;

/// [store] の [day] にバラエティ（その日1〜3台の機種）の台のうち、[day] から前へ、記録のある日が
/// どれも [gamesLimit] G未満のまま [minDays] 日（カレンダーの日数）以上続いている台。期間の長い順。
///
/// 同じ店舗・機種・台番号の記録だけを数える（入れ替えた台の前の機種は混ぜない）。店舗に記録が
/// ある日にその台の記録が無ければ（入れ替え前・取り込み漏れ）、そこで数えるのをやめる。店舗に
/// 記録が無い日（サイトが落ちていた日など）は飛ばし、期間には含める。
List<IdleRack> idleVarietyRacks(
  List<SlotRecord> all,
  String store,
  String day, {
  int minDays = idleDefaultDays,
  int gamesLimit = idleDefaultGames,
}) {
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
      if (row == null || row.games >= gamesLimit) break;
      run.add(row);
    }
    if (run.isNotEmpty && IdleRack(run).spanDays >= minDays) {
      result.add(IdleRack(run));
    }
  }
  result.sort(
    (a, b) => b.spanDays != a.spanDays
        ? b.spanDays.compareTo(a.spanDays)
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
  late int _minDays = _remembered(idleDaysKey, idleDayChoices, idleDefaultDays);
  late int _games = _remembered(
    idleGamesKey,
    idleGamesChoices,
    idleDefaultGames,
  );

  /// 覚えた選択。選択肢に無い値（古い・壊れた値）は既定値に戻す。
  static int _remembered(String key, List<int> choices, int fallback) {
    final value = int.tryParse(loadViewerSetting(key) ?? '');
    return choices.contains(value) ? value! : fallback;
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
  }

  // カレンダーの日付ページと同じ書き方（3桁ごとのカンマ）。
  static String _count(int g) => g > 0 ? signedMedals(g).substring(1) : '$g';

  Widget _choice({
    required String label,
    required int value,
    required List<int> choices,
    required String Function(int) text,
    required ValueChanged<int> onChanged,
  }) => DropdownButtonFormField<int>(
    key: ValueKey('variety-idle-$label'),
    initialValue: value,
    isExpanded: true,
    decoration: InputDecoration(labelText: label, isDense: true),
    items: [
      for (final c in choices) DropdownMenuItem(value: c, child: Text(text(c))),
    ],
    onChanged: (v) {
      if (v != null) onChanged(v);
    },
  );

  @override
  Widget build(BuildContext context) {
    final racks = idleVarietyRacks(
      widget.records,
      widget.store,
      _day,
      minDays: _minDays,
      gamesLimit: _games,
    );
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
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: _choice(
                    label: '期間',
                    value: _minDays,
                    choices: idleDayChoices,
                    text: (d) => '$d日以上',
                    onChanged: (d) {
                      saveViewerSetting(idleDaysKey, '$d');
                      setState(() => _minDays = d);
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _choice(
                    label: 'ゲーム数',
                    value: _games,
                    choices: idleGamesChoices,
                    text: (g) => '${_count(g)}G未満',
                    onChanged: (g) {
                      saveViewerSetting(idleGamesKey, '$g');
                      setState(() => _games = g);
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              'バラエティ（その日1〜3台の機種）の台で、選んだ日から前へ'
              '$_minDays日（カレンダーの日数）以上、毎日${_count(_games)}G未満の台です。'
              '記録の無い日（サイトが落ちていた日など）は飛ばして数えます。'
              '期間の長い順。台を押すとその台の記録を開きます。',
              style: const TextStyle(fontSize: 12, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            if (racks.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: '当てはまる台はありません',
                body: '入れ替えたばかりの台や、記録が足りない日は数えられません。期間・ゲーム数・日付を変えてみてください。',
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
                          '${idle.latest.rack}番${idle.latest.rainbow ? rainbowMark : ''}　'
                          '${displayMachineName(idle.latest.machine)}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          '${idle.spanDays}日間 ${_count(_games)}G未満'
                          '（${shortDayLabel(idle.from)}〜'
                          '${idle.days.length < idle.spanDays ? '、記録のある日${idle.days.length}日' : ''}）'
                          '・最多${_count(idle.maxGames)}G\n'
                          '${[for (final r in idle.days.take(7)) _count(r.games)].join('・')}G'
                          '${idle.days.length > 7 ? '…' : ''}',
                        ),
                        isThreeLine: true,
                        trailing: Text(
                          '${_count(idle.latest.games)}G',
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
