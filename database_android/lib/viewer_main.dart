import 'package:flutter/material.dart';

import 'answer_check.dart';
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
/// 採点・翌日候補・表とグラフ（画像は使わず、保存したグラフの線から描く）で見せる。
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

/// [store] の [day] より前の30日間に、記録がある日の数（採点の比較に使える日数）。
int historyDays(List<SlotRecord> all, String store, String day) {
  final first = DateTime.parse(day)
      .subtract(const Duration(days: 30))
      .toIso8601String()
      .substring(0, 10);
  return {
    for (final r in all)
      if (r.store == store &&
          r.day.compareTo(first) >= 0 &&
          r.day.compareTo(day) < 0)
        r.day,
  }.length;
}

class ViewerHome extends StatefulWidget {
  const ViewerHome({super.key});
  @override
  State<ViewerHome> createState() => _ViewerHomeState();
}

class _ViewerHomeState extends State<ViewerHome> {
  ViewerData? _data;
  var _loading = true;

  /// Driveの自動読み込みに使う、Googleのスクリプトのアドレス（未設定なら null）。
  String? _remote;
  var _syncing = false;
  String? _error;
  String? _store;
  String? _day;
  final _query = TextEditingController();

  // 表示中の日の採点（読み込んだ内容・店舗・日付が変わったときだけ計算し直す）。
  // 読み込んだ内容は、読み込むたびに1つ進む番号で見分ける。
  Object? _scoredFor;
  var _dataVersion = 0;
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
    _remote = loadRemoteUrl();
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
    // 前の内容をすぐ出してから、Driveの最新を読みに行く。
    if (_remote != null && Uri.base.queryParameters['load'] == null) {
      await _refreshFromDrive();
    }
  }

  /// Googleのスクリプト経由で、Driveの最新（database-viewer.json）を読む。
  /// 読めなければ、前に読み込んだ内容のまま理由を出す。
  Future<void> _refreshFromDrive() async {
    final url = _remote;
    if (url == null || _syncing) return;
    setState(() {
      _syncing = true;
      _error = null;
    });
    try {
      final text = await backupFromRemote(url);
      if (text != null) {
        // 前に読み込んだ内容と合わせる（新しい方を使い、Driveに無い古い日は残す）。
        String? stored;
        try {
          stored = await loadViewerData();
        } on Object {
          stored = null;
        }
        final merged = ViewerData.merge(stored, text);
        final data = ViewerData.parse(merged.text);
        if (merged.text != stored) await saveViewerData(merged.text);
        _show(data);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                merged.note ?? 'Googleドライブの最新（${data.records.length}台）を読み込みました。',
              ),
            ),
          );
        }
      }
    } catch (error) {
      _error = 'Googleドライブから読めませんでした（前に読み込んだ内容を表示しています）。\n$error';
    }
    if (mounted) setState(() => _syncing = false);
  }

  Future<void> _editRemote() async {
    final field = TextEditingController(text: _remote ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Googleドライブの自動読み込み'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Googleのスクリプト（Apps Script）の「ウェブアプリのURL」（…/exec）を貼ると、'
              '開くたびにGoogleドライブの最新を読みます。URLはこの端末にだけ覚えます。'
              '人には教えないでください。',
              style: TextStyle(fontSize: 13, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: field,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: 'ウェブアプリのURL',
                hintText: 'https://script.google.com/macros/s/…/exec',
              ),
            ),
          ],
        ),
        actions: [
          if (_remote != null)
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(''),
              child: const Text('自動読み込みをやめる'),
            ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('閉じる'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(field.text.trim()),
            child: const Text('保存して読み込む'),
          ),
        ],
      ),
    );
    field.dispose();
    if (result == null || !mounted) return;
    final url = result.isEmpty ? null : result;
    saveRemoteUrl(url);
    setState(() => _remote = url);
    if (url != null) await _refreshFromDrive();
  }

  void _show(ViewerData data) {
    _data = data;
    _dataVersion++;
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
      'pc-viewer' => 'PC版（閲覧用・直近60日）',
      _ => '',
    };
    if (data.file == 'Googleドライブ（自動）') {
      final older = data.keptOlder > 0
          ? '（うち${data.keptOlder}台は前に読み込んだ古い日の記録）'
          : '';
      return 'Googleドライブから自動で読み込み：$from$when${data.records.length}台$older'
          '（グラフは保存した線から描画。線の無い台は概略図）';
    }
    return '読み込んだバックアップ：$from$when${data.records.length}台'
        '（グラフは保存した線から描画。線の無い台は概略図）';
  }

  @override
  Widget build(BuildContext context) {
    final data = _data;
    return Scaffold(
      appBar: AppBar(
        title: const Text('database 閲覧'),
        actions: [
          if (_remote != null)
            IconButton(
              tooltip: 'Googleドライブの最新を読み込む',
              onPressed: _syncing ? null : _refreshFromDrive,
              icon: const Icon(Icons.refresh),
            ),
          IconButton(
            tooltip: 'Googleドライブの自動読み込み',
            onPressed: _editRemote,
            icon: Icon(
              _remote == null ? Icons.link : Icons.cloud_done_outlined,
            ),
          ),
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
      const SizedBox(height: 12),
      Center(
        child: TextButton.icon(
          onPressed: _editRemote,
          icon: const Icon(Icons.link),
          label: const Text('Googleドライブの自動読み込みを設定する'),
        ),
      ),
      const SizedBox(height: 12),
      const Notice(
        text:
            'Googleドライブが出ないとき：Googleドライブのアプリを入れてログインし、'
            '「ファイル」アプリの「ブラウズ」→右上の「…」→「編集」でGoogleドライブを'
            'オンにします。それでも開けないときは、Googleドライブのアプリでファイルの'
            '「…」→「アプリで開く」→「"ファイル"に保存」でiCloud Driveに保存し、'
            'そこから選んでください。',
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
    final key = (_dataVersion, store, day);
    if (_scoredFor != key) {
      _digest = [for (final r in dayRows) (r, scoreRecord(r, all))];
      _candidates = dayCandidates(dayRows, all);
      _scoredFor = key;
    }
    final summaries = summarizeMachines(_digest);
    final history = day == null ? 0 : historyDays(all, store, day);
    final shown = [
      for (final s in summaries)
        if (machineMatches(s.machine, _query.text)) s,
    ];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
      children: [
        if (_error != null) Notice(text: _error!),
        Notice(text: _sourceText(data)),
        if (day != null && history < 3)
          Notice(
            text:
                'このバックアップには、この日より前の記録が$history日分しかありません。'
                '採点は前の30日分と比べるため、点数が中立（50〜60点前後）に寄っています。'
                '全期間のバックアップ（PC版の「database共有」にある database-backup-auto.json か、'
                'Android版で「すべての日付」を選んで書き出したもの）を読み込んでください。',
          ),
        if (_loading || _syncing) const LinearProgressIndicator(),
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
                    DropdownMenuItem(
                      value: v,
                      child: Builder(builder: (context) {
                        final event = data.dateEventFor(store, v);
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(dayWithWeekday(v)),
                            if (event != null)
                              Text(event.name, style: const TextStyle(fontSize: 11, color: AppColors.appleBlue)),
                          ],
                        );
                      }),
                    ),
                ],
                onChanged: (v) => setState(() => _day = v),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => AnswerCheckPage(
                records: all,
                store: store,
                onOpen: _openRecord,
              ),
            ),
          ),
          icon: const Icon(Icons.fact_check_outlined),
          label: const Text('答え合わせ（前の日の候補の結果）'),
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
