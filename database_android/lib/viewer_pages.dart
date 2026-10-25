import 'package:flutter/material.dart';

import 'data_checks.dart';
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
    this.eventFor,
    this.allowAll = false,
  });
  final List<String> days;
  final String? day;
  final ValueChanged<String?> onChanged;
  final String? event;

  /// 日付一覧の各日に添えるイベント名（無ければ null）。
  final String? Function(String day)? eventFor;
  final bool allowAll;

  // 枠つきの入力欄は、見出し（「表示する日付」）を枠の上の線にまたがって描く。上に余白が
  // 無いと、見出しの上半分が上の帯に隠れて切れる（2026-10-01、利用者の指摘）。
  @override
  Size get preferredSize => const Size.fromHeight(92);

  @override
  Widget build(BuildContext context) {
    final index = day == null ? -1 : days.indexOf(day!);
    return SizedBox(
      height: preferredSize.height,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 12, 8, 0),
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
                    // 選んだ後の欄は日付だけ（イベント名は下の行に出す）。
                    selectedItemBuilder: (context) => [
                      if (allowAll) const Text('すべての日付'),
                      for (final d in days) Text(dayWithWeekday(d)),
                    ],
                    items: [
                      if (allowAll)
                        const DropdownMenuItem(
                          value: '',
                          child: Text('すべての日付'),
                        ),
                      for (final d in days)
                        DropdownMenuItem(
                          value: d,
                          child: _DayItem(day: d, event: eventFor?.call(d)),
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

/// 日付一覧の1行：日付と、その日のイベント名。
class _DayItem extends StatelessWidget {
  const _DayItem({required this.day, this.event});
  final String day;
  final String? event;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(dayWithWeekday(day)),
      if (event != null)
        Text(
          event!,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 11, color: AppColors.appleBlue),
        ),
    ],
  );
}

/// 1機種の台（[machine] が [varietyGroupName] なら、その日その店で1〜3台の
/// 機種をまとめたバラエティ）を、日付を切り替えながら見る画面。
class ViewerMachinePage extends StatefulWidget {
  const ViewerMachinePage({
    super.key,
    required this.data,
    required this.store,
    required this.machine,
    required this.day,
    this.query = '',
    this.onDayChanged,
  });
  final ViewerData data;
  final String store, machine, day;

  /// 一覧の機種名・台番号の絞り込みを、この画面でも引き継ぐ。
  final String query;
  final ValueChanged<String>? onDayChanged;
  @override
  State<ViewerMachinePage> createState() => _ViewerMachinePageState();
}

class _ViewerMachinePageState extends State<ViewerMachinePage> {
  late String _day = widget.day;
  late String _query = widget.query;
  bool _graph = false;
  bool _hasDayRecords = false;
  String? _calculatedDay;
  List<(SlotRecord, ScoreResult)> _entries = [];
  Set<int> _candidateRacks = {};
  Set<int> _longTrendRacks = {};

  /// 台の表・グラフのリスト（右下の「一番上へ」ボタンで戻す）。
  final _scroll = ScrollController();

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    final variety = widget.machine == varietyGroupName;
    if (_calculatedDay != _day) {
      final dayRows = [
        for (final r in data.records)
          if (r.store == widget.store && r.day == _day) r,
      ];
      final varietyNames = variety
          ? varietyMachines(dayRows)
          : const <String>{};
      final rows = [
        for (final r in dayRows)
          if (variety
              ? varietyNames.contains(r.machine)
              : r.machine == widget.machine)
            r,
      ]..sort((a, b) => a.rack.compareTo(b.rack));
      _hasDayRecords = rows.isNotEmpty;
      final grouped = [for (final r in rows) (r, scoreRecord(r, data.records))];
      final search = RecordQuery(_query);
      _entries = !search.matchesMachine(widget.machine)
          ? [
              for (final e in grouped)
                if (search.matches(e.$1)) e,
            ]
          : grouped;
      // 候補はホームと同じ店舗・日付の全台から選び、表示中の台にだけ★を付ける。
      // 日付を変えて機種が4台以上から3台以下になっても、機種内だけで
      // バラエティの候補を選び直さない。検索で隠れた候補を見出しの台数に含めない。
      final visibleKeys = {for (final e in _entries) e.$1.key};
      final candidates = dayCandidates(dayRows, data.records).candidates;
      _candidateRacks = {
        for (final c in candidates)
          if (visibleKeys.contains(c.record.key) &&
              candidateIsFocus(c, data.records))
            c.record.rack,
      };
      _longTrendRacks = {
        for (final c in candidates)
          if (visibleKeys.contains(c.record.key) &&
              !candidateIsFocus(c, data.records))
            c.record.rack,
      };
      _calculatedDay = _day;
    }
    return Scaffold(
      appBar: AppBar(
        title: Text(
          variety ? varietyGroupName : displayMachineName(widget.machine),
        ),
        bottom: ViewerDateBar(
          days: viewerDays(data.records, widget.store),
          day: _day,
          event: data.dateEventFor(widget.store, _day)?.name,
          eventFor: (day) => data.dateEventFor(widget.store, day)?.name,
          onChanged: _changeDay,
        ),
      ),
      // 日付を変えるとリストは一番上から作り直すので、ボタンも隠した状態に戻す。
      floatingActionButton: ScrollTopButton(
        key: ValueKey(_day),
        controller: _scroll,
      ),
      body: SafeArea(
        child: ListView(
          key: ValueKey(_day),
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 88),
          children: [
            Text(
              storeDisplayName(widget.store),
              style: const TextStyle(color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            if (_entries.isEmpty) ...[
              EmptyState(
                icon: Icons.inbox_outlined,
                title: _hasDayRecords ? '検索条件に合う台がありません' : 'この日の記録はありません',
                body: _hasDayRecords
                    ? 'この日の機種の記録はあります。台番号が変わっている場合は、全台を表示して確認してください。'
                    : variety
                    ? 'この日は${varietyRangeFor(widget.store)}の機種（バラエティ）の記録がありません。別の日付を選んでください。'
                    : 'この機種の記録がある別の日付を選んでください。入れ替え前や、まだ取り込んでいない日は表示されません。',
              ),
              if (_hasDayRecords)
                OutlinedButton(
                  onPressed: () => setState(() {
                    _query = '';
                    _calculatedDay = null;
                  }),
                  child: const Text('この機種の全台を表示'),
                ),
            ] else
              MachineSection(
                machine: widget.machine,
                entries: _entries,
                candidateRacks: _candidateRacks,
                longTrendRacks: _longTrendRacks,
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
/// 閲覧ページで🌈を付け外しする（RAINBOW.md「iPhoneから付ける」）。閲覧ページの画面（ViewerHome）が設定する。
/// 端末の内容に保存して共有ファイルへ送り、新しい内容を返す（できなければ null）。null の間（Android版・
/// P’s CUBE）は台の画面に🌈のボタンを出さない。
Future<ViewerData?> Function(SlotRecord record, bool on)? viewerRainbowEditor;

/// 閲覧ページの表示データが新しくなるたびに進む番号（ViewerHome._show が増やす）。開いたままの画面
/// （バラエティの候補・本日の🌈）はこれを聞いて描き直す。起動直後に開くと、あとから届いたほかの端末の
/// 🌈が出なかった（2026-10-25、CIの閲覧ページ試験でたまに失敗していた原因）。
final viewerDataRevision = ValueNotifier<int>(0);

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
  // 🌈を付け外ししたら、新しい内容で表示し直す。
  late ViewerData _data = widget.data;
  bool _savingRainbow = false;

  Future<void> _setRainbow(SlotRecord record, bool on) async {
    final editor = viewerRainbowEditor;
    if (editor == null || _savingRainbow) return;
    setState(() => _savingRainbow = true);
    try {
      final next = await editor(record, on);
      if (next != null && mounted) setState(() => _data = next);
    } finally {
      if (mounted) setState(() => _savingRainbow = false);
    }
  }

  void _changeDay(String? day) {
    if (day == null || day == _day) return;
    setState(() => _day = day);
    widget.onDayChanged?.call(day);
  }

  @override
  Widget build(BuildContext context) {
    final original = widget.record;
    final data = _data;
    final record = data.records
        .where(
          (r) =>
              r.store == original.store &&
              r.machine == original.machine &&
              r.rack == original.rack &&
              r.day == _day,
        )
        .firstOrNull;
    final bar = ViewerDateBar(
      days: viewerDays(data.records, original.store),
      day: _day,
      event: data.dateEventFor(original.store, _day)?.name,
      eventFor: (day) => data.dateEventFor(original.store, day)?.name,
      onChanged: _changeDay,
    );
    if (record == null) {
      final sameNumber = widget.data.records
          .where(
            (r) =>
                r.store == original.store &&
                r.day == _day &&
                r.rack == original.rack &&
                r.machine != original.machine,
          )
          .toList();
      final otherNumbers = widget.data.records.any(
        (r) =>
            r.store == original.store &&
            r.day == _day &&
            r.machine == original.machine &&
            r.rack != original.rack,
      );
      final recordedDays =
          widget.data.records
              .where(
                (r) =>
                    r.store == original.store &&
                    r.machine == original.machine &&
                    r.rack == original.rack,
              )
              .map((r) => r.day)
              .toList()
            ..sort((a, b) => b.compareTo(a));
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
                body: '同じ店舗・機種・台番号の記録がありません。入れ替えや番号の変更があっても、別の台の履歴は混ぜずに表示します。',
              ),
              if (sameNumber.isNotEmpty) ...[
                Text('この日の${original.rack}番台には、別の機種の記録があります。'),
                const SizedBox(height: 8),
                for (final other in sameNumber)
                  OutlinedButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => ViewerRecordPage(
                          data: widget.data,
                          record: other,
                          onDayChanged: widget.onDayChanged,
                        ),
                      ),
                    ),
                    child: Text(
                      'この日の「${displayMachineName(other.machine)}」を見る',
                    ),
                  ),
              ],
              if (otherNumbers) ...[
                Text(
                  'この日は「${displayMachineName(original.machine)}」に、別の台番号の記録があります。',
                ),
                const SizedBox(height: 8),
                OutlinedButton(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => ViewerMachinePage(
                        data: widget.data,
                        store: original.store,
                        machine: original.machine,
                        day: _day,
                        onDayChanged: widget.onDayChanged,
                      ),
                    ),
                  ),
                  child: const Text('この日の機種一覧を見る'),
                ),
              ],
              if (recordedDays.isNotEmpty)
                OutlinedButton(
                  onPressed: () => _changeDay(recordedDays.first),
                  child: const Text('この台の最新の記録へ戻る'),
                ),
            ],
          ),
        ),
      );
    }
    return SavedGraphPage(
      key: ValueKey(record.key),
      record: record,
      score: scoreRecord(record, data.records),
      allRecords: data.records,
      dateNavigation: bar,
      scrollTopButton: true,
      onOpenDay: _changeDay,
      onRainbow:
          viewerRainbowEditor == null ||
              !storeNames.containsKey(record.store) ||
              _savingRainbow
          ? null
          : (on) => _setRainbow(record, on),
    );
  }
}
