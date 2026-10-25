import 'dart:async';

import 'package:flutter/material.dart';

import 'list_views.dart' show displayMachineName;
import 'models.dart';
import 'rainbow_marks.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart' show viewerDataRevision, viewerRainbowEditor;

String rainbowTodayDay(DateTime now) => now
    .toUtc()
    .add(const Duration(hours: 9))
    .toIso8601String()
    .substring(0, 10);

class RainbowTodayRack {
  const RainbowTodayRack(this.marker, this.imported);

  /// 既存の印編集APIへ渡すだけの値。数値の記録として保存・採点しない。
  final SlotRecord marker;
  final bool imported;
}

({String? lineupDay, List<RainbowTodayRack> rows}) rainbowTodayRows(
  ViewerData data,
  String store,
  String day,
) {
  if (store != 'saiwaichou') return (lineupDay: null, rows: []);
  final byDay = <String, List<SlotRecord>>{};
  for (final r in data.records) {
    if (r.store == store &&
        r.day.compareTo(day) <= 0 &&
        !hasImplausibleNumbers(r)) {
      (byDay[r.day] ??= []).add(r);
    }
  }
  final days = byDay.keys.toList()..sort((a, b) => b.compareTo(a));
  if (days.isEmpty) return (lineupDay: null, rows: []);
  final recent = days.take(14);
  final usual = recent
      .map((d) => byDay[d]!.length)
      .reduce((a, b) => a > b ? a : b);
  final source = recent.firstWhere((d) => byDay[d]!.length >= usual * 0.8);
  final lineup = byDay[source]!;
  final counts = <String, int>{};
  for (final r in lineup) {
    counts[r.machine] = (counts[r.machine] ?? 0) + 1;
  }
  final actual = {for (final r in byDay[day] ?? <SlotRecord>[]) r.rack: r};
  final rows = <RainbowTodayRack>[];
  for (final r in lineup) {
    if (counts[r.machine] != 1) continue;
    final record = actual[r.rack];
    // 未取得の台は日付と印だけを編集。過去日の印を本日へコピーしない。
    final marker = record ?? r.copyWith(day: day, extra: const {});
    rows.add(
      RainbowTodayRack(
        applyRainbowMarks([marker], data.rainbowMarks).single,
        record != null,
      ),
    );
  }
  rows.sort((a, b) => a.marker.rack.compareTo(b.marker.rack));
  return (lineupDay: source, rows: rows);
}

class RainbowTodayList extends StatefulWidget {
  const RainbowTodayList({
    super.key,
    required this.data,
    required this.store,
    this.currentData,
    this.onDataChanged,
  });
  final ViewerData data;
  final String store;
  final ViewerData Function()? currentData;
  final ValueChanged<ViewerData>? onDataChanged;

  @override
  State<RainbowTodayList> createState() => _RainbowTodayListState();
}

class _RainbowTodayListState extends State<RainbowTodayList> {
  late ViewerData _data = widget.data;
  late String _day = rainbowTodayDay(DateTime.now());
  Timer? _timer;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) {
      final day = rainbowTodayDay(DateTime.now());
      if (day != _day && mounted) setState(() => _day = day);
    });
    // 開いたあとに届いたほかの端末の🌈も出す（build は currentData から最新を読む）。
    viewerDataRevision.addListener(_dataChanged);
  }

  void _dataChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    viewerDataRevision.removeListener(_dataChanged);
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _toggle(SlotRecord marker) async {
    final day = rainbowTodayDay(DateTime.now());
    if (marker.day != day) {
      setState(() => _day = day);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('日付が変わりました。本日の一覧を確認してから押してください。')),
      );
      return;
    }
    final edit = viewerRainbowEditor;
    if (edit == null || _saving) return;
    setState(() => _saving = true);
    try {
      final next = await edit(marker, !marker.rainbow);
      if (next != null && mounted) {
        setState(() => _data = next);
        widget.onDataChanged?.call(next);
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('🌈を保存できませんでした。もう一度押してください。')),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.currentData?.call() ?? _data;
    final report = rainbowTodayRows(data, widget.store, _day);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('本日 $_day', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        const Text('確定を見た台に、その場で🌈を付けられます。データ取り込み後も印は引き継がれます。'),
        if (report.lineupDay != null)
          Text('機種一覧：${report.lineupDay}の取り込み済みデータを参照（幸町・1台機種）'),
        const SizedBox(height: 12),
        Text('本日の🌈 ${report.rows.where((x) => x.marker.rainbow).length}台'),
        if (report.rows.isEmpty) const Text('参照できる機種一覧がありません。先にデータを読み込んでください。'),
        for (final x in report.rows)
          Card(
            child: ListTile(
              title: Text(
                '${x.marker.rack}番　${displayMachineName(x.marker.machine)}',
              ),
              subtitle: Text(x.imported ? '本日分 取り込み済み' : '本日分 未取得'),
              trailing: OutlinedButton(
                key: ValueKey('today-rainbow-${x.marker.rack}'),
                onPressed: _saving || viewerRainbowEditor == null
                    ? null
                    : () => _toggle(x.marker),
                child: Text(x.marker.rainbow ? '🌈 外す' : '🌈 付ける'),
              ),
            ),
          ),
      ],
    );
  }
}
