import 'package:flutter/material.dart';

import 'calendar_day_page.dart';
import 'daily_net_page.dart' show DayNet;
import 'date_events.dart';
import 'event_name_dialog.dart';
import 'list_views.dart';
import 'models.dart' show SlotRecord, signedMedals, winRateLabel;
import 'shared_widgets.dart';
import 'theme.dart';

/// 「期間でまとめて入力」で一度に付けられる日数（PC `event_calendar.RANGE_MAX_DAYS` と同じ）。
const eventRangeMaxDays = 62;
const eventLateMark = '＊';
const eventLateNote = '＊＝前日までに入力した記録がありません（当日以降の入力・時刻不明）。予想の材料には使いません。';

/// 日曜から土曜の週ごと。月の外の日は null。
List<List<DateTime?>> monthWeeks(int year, int month) {
  final first = DateTime.utc(year, month);
  final start = first.subtract(Duration(days: first.weekday % 7));
  final weeks = <List<DateTime?>>[];
  for (var day = start; ; day = day.add(const Duration(days: 7))) {
    final week = [for (var i = 0; i < 7; i++) day.add(Duration(days: i))];
    if (week.first.month != month && week.first.isAfter(first)) break;
    weeks.add([for (final d in week) d.month == month ? d : null]);
  }
  return weeks;
}

/// [first]〜[last]（どちらが先でもよい）の毎日（yyyy-mm-dd）。
List<String> eventRangeDays(String first, String last) {
  final a = DateTime.parse(first), b = DateTime.parse(last);
  final start = a.isBefore(b) ? a : b, end = a.isBefore(b) ? b : a;
  return [
    for (var d = start; !d.isAfter(end); d = d.add(const Duration(days: 1)))
      _iso(d),
  ];
}

String _iso(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// カレンダーの1日に出すイベント名（前日までに入力していなければ＊）。
String eventCellLabel(DateEvent? event) => event == null || event.removed
    ? ''
    : '${event.name}${event.enteredInAdvance ? '' : eventLateMark}';

/// カレンダーの1日に出す差枚（その日の総差枚）。メルヘンはほぼ毎日、要確認（※）の推定差枚の台を
/// 含むので、マスには※を付けない（下の説明に書く、PC `event_calendar.net_text` と同じ）。
/// 差枚の分かる台が半分に満たない日は、代わりに勝率（[DayNet.showsWinRate]、2026-10-17）。
String? dayNetCellLabel(DayNet? net) => net == null
    ? null
    : net.showsWinRate
    ? winRateLabel(net.won, net.judged)
    : net.total == null
    ? null
    : signedMedals(net.total!);

/// イベントカレンダー（メルヘン2店舗・P’s CUBE。Android版・閲覧ページ共通、`EVENT_CALENDAR.md`）。
/// 先の日にもイベント名を入れられる。保存は [onSave]（名前 null は消す）。
/// [netFor] があれば、各日にその店の総差枚も出す（2026-10-08 利用者指定）。
class EventCalendarPage extends StatefulWidget {
  const EventCalendarPage({
    super.key,
    required this.stores,
    required this.initialStore,
    required this.eventFor,
    required this.namesFor,
    required this.onSave,
    this.actions = const [],
    this.note,
    this.today,
    this.netFor,
    this.netNote,
    this.recordsFor,
    this.onOpenRecord,
  });

  final Map<String, String> stores;
  final String initialStore;
  final DateEvent? Function(String store, String day) eventFor;
  final List<String> Function(String store) namesFor;
  final Future<void> Function(String store, List<String> days, String? name)
  onSave;
  final List<Widget> actions;

  /// 画面の下に出す補足（閲覧ページの書き出しの案内など）。
  final String? note;
  final DateTime? today;

  /// その店・その日の差枚（[dailyNet] の1日分）。記録の無い日は null。
  final DayNet? Function(String store, String day)? netFor;

  /// 差枚の説明（メルヘンは推定であることなど）。[netFor] があるときに出す。
  final String? netNote;

  /// その店・その日の台の記録。あれば日付を押すと、その日のTOP10・強かった機種5選
  /// （[CalendarDayPage]、2026-10-09）を開く。記録の無い日は今までどおりイベント名の入力。
  final List<SlotRecord> Function(String store, String day)? recordsFor;

  /// まとめの台を押したとき（台の詳細）。
  final void Function(SlotRecord record)? onOpenRecord;

  @override
  State<EventCalendarPage> createState() => _EventCalendarPageState();
}

class _EventCalendarPageState extends State<EventCalendarPage> {
  late String _store = widget.stores.containsKey(widget.initialStore)
      ? widget.initialStore
      : widget.stores.keys.first;
  late final DateTime _today = widget.today ?? DateTime.now();
  late DateTime _month = DateTime.utc(_today.year, _today.month);
  bool _picking = false;
  String? _picked;
  String? _error;

  void _move(int months) =>
      setState(() => _month = DateTime.utc(_month.year, _month.month + months));

  Future<void> _save(List<String> days, String? name, {String? store}) async {
    try {
      await widget.onSave(store ?? _store, days, name);
      if (mounted) setState(() => _error = null);
    } catch (error) {
      if (mounted) setState(() => _error = 'イベント名を保存できませんでした。\n$error');
    }
  }

  Future<void> _tap(String day) async {
    if (_picking) {
      if (_picked == null) {
        setState(() => _picked = day);
        return;
      }
      final days = eventRangeDays(_picked!, day);
      setState(() {
        _picking = false;
        _picked = null;
      });
      if (days.length > eventRangeMaxDays) {
        setState(() => _error = '一度に入れられるのは$eventRangeMaxDays日までです。');
        return;
      }
      final name = await showEventNameDialog(
        context,
        title:
            '${dayWithWeekday(days.first)}〜${dayWithWeekday(days.last)} のイベント（${days.length}日）',
        names: widget.namesFor(_store),
      );
      if (name == null || !mounted) return;
      await _save(days, name.isEmpty ? null : name);
      return;
    }
    final records = widget.recordsFor?.call(_store, day) ?? const [];
    if (records.isNotEmpty) {
      final store = _store;
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => CalendarDayPage(
            store: store,
            day: day,
            records: records,
            eventFor: () => widget.eventFor(store, day),
            onEditEvent: () => _editOne(store, day),
            onOpenRecord: widget.onOpenRecord,
          ),
        ),
      );
      if (mounted) setState(() {});
      return;
    }
    await _editOne(_store, day);
  }

  /// 1日のイベント名を入れる・変える・消す。
  Future<void> _editOne(String store, String day) async {
    final current = widget.eventFor(store, day);
    final name = await showEventNameDialog(
      context,
      title: '${dayWithWeekday(day)} のイベント',
      current: current == null || current.removed ? null : current.name,
      names: widget.namesFor(store),
    );
    if (name == null || !mounted) return;
    await _save([day], name.isEmpty ? null : name, store: store);
  }

  Widget _cell(DateTime? date) {
    if (date == null) return const SizedBox.shrink();
    final day = _iso(date);
    final label = eventCellLabel(widget.eventFor(_store, day));
    final net = widget.netFor?.call(_store, day);
    final netLabel = dayNetCellLabel(net);
    final today =
        date.year == _today.year &&
        date.month == _today.month &&
        date.day == _today.day;
    final picked = day == _picked;
    return Padding(
      padding: const EdgeInsets.all(1.5),
      child: Material(
        color: picked ? const Color(0xFFFFE8A3) : Colors.white,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
          key: ValueKey('event-day-$day'),
          borderRadius: BorderRadius.circular(6),
          onTap: () => _tap(day),
          child: Container(
            constraints: BoxConstraints(
              minHeight: widget.netFor == null ? 58 : 70,
            ),
            padding: const EdgeInsets.fromLTRB(4, 3, 4, 3),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(6),
              border: Border.all(
                color: today ? AppColors.appleBlue : AppColors.hairline,
                width: today ? 2 : 1,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${date.day}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: today ? FontWeight.w800 : FontWeight.w600,
                    color: date.weekday == DateTime.sunday
                        ? const Color(0xFFC62828)
                        : date.weekday == DateTime.saturday
                        ? AppColors.linkBlue
                        : AppColors.carbon,
                  ),
                ),
                if (label.isNotEmpty)
                  Text(
                    label,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 10, height: 1.2),
                  ),
                if (netLabel != null) ...[
                  const Spacer(),
                  // 狭い画面でも桁が切れないよう、入りきらないときだけ縮める。
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Text(
                      netLabel,
                      key: ValueKey('event-net-$day'),
                      maxLines: 1,
                      style: TextStyle(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        // 勝率は差枚ではないので色を付けない。
                        color: net!.showsWinRate || net.total == 0
                            ? AppColors.ash
                            : net.total! > 0
                            ? AppColors.linkBlue
                            : const Color(0xFFC62828),
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('イベントカレンダー'), actions: widget.actions),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          if (_error != null) Notice(text: _error!),
          storeDropdown(
            _store,
            (v) => setState(() {
              _store = v;
              _picked = null;
            }),
            short: true,
            stores: widget.stores,
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              IconButton(
                tooltip: '前の月',
                onPressed: () => _move(-1),
                icon: const Icon(Icons.chevron_left),
              ),
              Expanded(
                child: Text(
                  '${_month.year}年${_month.month}月',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              IconButton(
                tooltip: '次の月',
                onPressed: () => _move(1),
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('期間でまとめて入力'),
            subtitle: Text(
              _picking
                  ? (_picked == null
                        ? '最初の日を押してください。'
                        : '${dayWithWeekday(_picked!)} から。最後の日を押してください。')
                  : '最初の日と最後の日を押して、同じ名前を付けます（$eventRangeMaxDays日まで）。',
            ),
            value: _picking,
            onChanged: (v) => setState(() {
              _picking = v;
              _picked = null;
            }),
          ),
          Row(
            children: [
              for (final (i, name) in '日月火水木金土'.split('').indexed)
                Expanded(
                  child: Text(
                    name,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: i == 0
                          ? const Color(0xFFC62828)
                          : i == 6
                          ? AppColors.linkBlue
                          : AppColors.ash,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          for (final week in monthWeeks(_month.year, _month.month))
            IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final date in week) Expanded(child: _cell(date)),
                ],
              ),
            ),
          const SizedBox(height: 12),
          if (widget.netFor != null && widget.netNote != null)
            Notice(text: widget.netNote!),
          const Notice(text: eventLateNote),
          if (widget.note != null) Notice(text: widget.note!),
        ],
      ),
    ),
  );
}
