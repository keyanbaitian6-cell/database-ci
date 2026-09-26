import 'package:flutter/material.dart';

import 'data_checks.dart';
import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'scoring.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'viewer_bridge.dart';
import 'viewer_data.dart';

/// iPhoneなどで見るための閲覧専用ページ（Web）。
///
/// `flutter build web -t lib/viewer_main.dart` で作る。取り込み・保存はしない。
/// DriveなどにあるバックアップJSONを端末の中だけで読み、Android版と同じ
/// 採点・翌日候補・表とグラフ（画像は使わず4点からの概略図）で見せる。
void main() => runApp(const ViewerApp());

class ViewerApp extends StatelessWidget {
  const ViewerApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'database 閲覧',
    debugShowCheckedModeBanner: false,
    theme: buildAppTheme(),
    home: const ViewerHome(),
  );
}

class ViewerHome extends StatefulWidget {
  const ViewerHome({super.key});
  @override
  State<ViewerHome> createState() => _ViewerHomeState();
}

class _ViewerHomeState extends State<ViewerHome> {
  ViewerData? _data;
  var _loading = true;
  String? _error;
  String? _store;
  String? _day;
  final _query = TextEditingController();

  // 表示中の日の採点（店舗・日付が変わったときだけ計算し直す）。
  Object? _scoredFor;
  List<(SlotRecord, ScoreResult)> _digest = const [];
  ({List<ProvisionalCandidate> candidates, int machines, int judged})?
  _candidates;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    try {
      // 手元での確認用：同じサイト内のファイルを ?load= で読む。
      final url = Uri.base.queryParameters['load'];
      final text = url != null
          ? await backupFromUrl(url)
          : await loadViewerData();
      if (text != null) _show(ViewerData.parse(text));
    } catch (error) {
      _error = '前に読み込んだ内容を開けませんでした。もう一度読み込んでください。\n$error';
    }
    if (mounted) setState(() => _loading = false);
  }

  void _show(ViewerData data) {
    _data = data;
    _scoredFor = null;
    final first = data.records.firstOrNull;
    if (!data.records.any((r) => r.store == _store)) _store = first?.store;
  }

  Future<void> _pick() async {
    setState(() {
      _error = null;
      _loading = true;
    });
    try {
      final text = await pickBackup();
      if (text != null) {
        final data = ViewerData.parse(text);
        await saveViewerData(text);
        _show(data);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('${data.records.length}台を読み込みました。')),
          );
        }
      }
    } catch (error) {
      _error = 'バックアップを読み込めませんでした。\n$error';
    }
    if (mounted) setState(() => _loading = false);
  }

  void _openRecord(SlotRecord record, ScoreResult? score) =>
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => SavedGraphPage(
            record: record,
            score: score,
            allRecords: _data!.records,
          ),
        ),
      );

  void _openMachine(String machine) {
    final entries = [
      for (final e in _digest)
        if (e.$1.machine == machine) e,
    ]..sort((a, b) => a.$1.rack.compareTo(b.$1.rack));
    final racks = {
      for (final c in _candidates?.candidates ?? const <ProvisionalCandidate>[])
        if (c.record.machine == machine) c.record.rack,
    };
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => Scaffold(
          appBar: AppBar(title: Text(displayMachineName(machine))),
          body: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              MachineSection(
                machine: machine,
                entries: entries,
                candidateRacks: racks,
                onTap: _openRecord,
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _sourceText(ViewerData data) {
    String two(int v) => v.toString().padLeft(2, '0');
    final at = data.exportedAt;
    final when = at == null
        ? ''
        : '${at.month}/${at.day} ${two(at.hour)}:${two(at.minute)}書き出し・';
    final from = switch (data.source) {
      'android' => 'Android版',
      'pc' || 'pc-deleted' => 'PC版',
      _ => '',
    };
    return '読み込んだバックアップ：$from$when${data.records.length}台'
        '（グラフは画像を使わず概略図で表示）';
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Scaffold(
      appBar: AppBar(
        title: const Text('database 閲覧'),
        actions: [
          IconButton(
            tooltip: 'バックアップを読み込む',
            onPressed: _pick,
            icon: const Icon(Icons.file_open_outlined),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading && data == null
            ? const Center(child: CircularProgressIndicator())
            : data == null || data.records.isEmpty
            ? _welcome()
            : _results(data),
      ),
    );
  }

  Widget _welcome() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      if (_error != null) Notice(text: _error!),
      const EmptyState(
        icon: Icons.cloud_download_outlined,
        title: 'バックアップを読み込んでください',
        body:
            '「バックアップを読み込む」を押し、「ファイル」からGoogleドライブの'
            'database-backup-….json を選びます。読み込んだ内容はこの端末の中だけで'
            '使い、どこにも送りません。次からは選び直さなくても開けます。',
      ),
      const SizedBox(height: 16),
      Center(
        child: FilledButton.icon(
          onPressed: _loading ? null : _pick,
          icon: const Icon(Icons.file_open_outlined),
          label: Text(_loading ? '読み込み中…' : 'バックアップを読み込む'),
        ),
      ),
    ],
  );

  Widget _results(ViewerData data) {
    final all = data.records;
    final store = _store ?? all.first.store;
    final storeRows = [
      for (final r in all)
        if (r.store == store) r,
    ];
    final days = storeRows.map((r) => r.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    if (!days.contains(_day)) _day = days.firstOrNull;
    final day = _day;
    final dayRows = [
      for (final r in storeRows)
        if (r.day == day) r,
    ];
    final key = (identityHashCode(all), store, day);
    if (_scoredFor != key) {
      _digest = [for (final r in dayRows) (r, scoreRecord(r, all))];
      _candidates = dayCandidates(dayRows, all);
      _scoredFor = key;
    }
    final summaries = summarizeMachines(_digest);
    final shown = [
      for (final s in summaries)
        if (machineMatches(s.machine, _query.text)) s,
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      children: [
        if (_error != null) Notice(text: _error!),
        Notice(text: _sourceText(data)),
        if (_loading) const LinearProgressIndicator(),
        Row(
          children: [
            Expanded(
              flex: 2,
              child: storeDropdown(
                store,
                (v) => setState(() {
                  _store = v;
                  _day = null;
                }),
                short: true,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 3,
              child: DropdownButtonFormField<String>(
                key: ValueKey('$store|$day'),
                initialValue: day,
                isExpanded: true,
                decoration: const InputDecoration(labelText: '日付'),
                items: [
                  for (final v in days)
                    DropdownMenuItem(value: v, child: Text(dayWithWeekday(v))),
                ],
                onChanged: (v) => setState(() => _day = v),
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        if (dayRows.isEmpty || day == null)
          const EmptyState(
            icon: Icons.inbox_outlined,
            title: 'この店舗の記録はありません',
            body: '別の店舗を選ぶか、新しいバックアップを読み込んでください。',
          )
        else ...[
          NextDayCandidatesCard(
            day: day,
            candidates: _candidates!.candidates,
            machines: _candidates!.machines,
            judged: _candidates!.judged,
            onPick: (record) => _openRecord(
              record,
              _digest.where((e) => e.$1.key == record.key).firstOrNull?.$2,
            ),
          ),
          const SizedBox(height: 14),
          DaySummaryCard(entries: _digest, onPick: _openRecord),
          const SizedBox(height: 18),
          Text(
            '設置機種一覧　${summaries.length}機種・${_digest.length}台',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          if (summaries.length > 6) ...[
            MachineSearchField(
              controller: _query,
              onChanged: () => setState(() {}),
            ),
            const SizedBox(height: 8),
          ],
          MachineSummaryList(summaries: shown, onPick: _openMachine),
        ],
      ],
    );
  }
}
