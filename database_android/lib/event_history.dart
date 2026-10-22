import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'event_history_model.dart';
import 'list_views.dart' show displayMachineName;
import 'viewer_bridge.dart';
import 'viewer_data.dart';
import 'viewer_pages.dart';

/// PC・Androidが保存した週表。Webでは共有先から取得して閲覧する。
class EventHistoryPage extends StatefulWidget {
  const EventHistoryPage({
    super.key,
    required this.data,
    this.edits,
    this.onSave,
    this.remoteUrl,
    this.recordCutoff,
    this.loadBase = loadHistoryBase,
    this.store = historyStore,
  });
  final ViewerData data;
  final Map<String, dynamic>? edits;
  final Future<Map<String, dynamic>> Function(Map<String, dynamic>)? onSave;
  final String? remoteUrl;
  final String? recordCutoff;
  final Future<Map<String, dynamic>> Function() loadBase;
  final String store;
  @override
  State<EventHistoryPage> createState() => _EventHistoryPageState();
}

class _EventHistoryPageState extends State<EventHistoryPage> {
  Map<String, dynamic>? _base;
  Map<String, dynamic> _edits = emptyHistoryEdits();
  late final _index = historyRecordIndex(
    widget.data.records,
    store: widget.store,
  );
  String _type = historyTypes.first;
  String? _week, _error;
  String _status = '';
  bool _busy = false;
  bool get _saiwaichou => widget.store == saiwaichouHistoryStore;
  String get _title => _saiwaichou ? '幸町のバラエティ履歴' : '長町南のイベント履歴';
  bool get _editable => !_saiwaichou && widget.onSave != null && !kIsWeb;
  @override
  void initState() {
    super.initState();
    if (_saiwaichou) _type = 'バラエティ';
    _load();
  }

  Future<void> _load() async {
    try {
      Map<String, dynamic> base, edits;
      var status = '';
      if (kIsWeb) {
        final url = widget.remoteUrl;
        if (url == null) {
          throw const FormatException('履歴を見るにはGoogleドライブの自動読み込みを設定してください。');
        }
        final key = 'event-history:$url';
        dynamic raw;
        try {
          raw = jsonDecode(await fetchSharedEvents(url, 'event-history'));
          if (raw is! Map || raw['base'] == null) {
            throw const FormatException('編集の反映にはApps Scriptの更新が必要です。');
          }
          final document = historyDocumentForStore(raw, widget.store);
          base = parseHistoryBase(document['base']);
          edits = document;
          cleanHistoryEdits(edits, base);
          saveViewerSetting(key, jsonEncode(raw));
        } on Object catch (error) {
          final cached = loadViewerSetting(key);
          if (cached == null) rethrow;
          raw = jsonDecode(cached);
          final document = historyDocumentForStore(raw, widget.store);
          base = parseHistoryBase(document['base']);
          edits = document;
          status = '最新の履歴を取得できません。保存済みの内容を表示しています。$error';
        }
      } else {
        base = _saiwaichou ? saiwaichouHistoryBase() : await widget.loadBase();
        edits = historyEditsForStore(
          widget.edits ?? emptyHistoryEdits(),
          widget.store,
        );
        status = _saiwaichou
            ? '優・良の入力・修正はPCで行います。'
            : _editable
            ? '編集は端末に保存します。バックアップをPCへ取り込むと共有へ反映します。'
            : '';
      }
      if (base['store'] != widget.store)
        throw const FormatException('履歴の店舗が一致しません。');
      final rejected =
          cleanHistoryEdits(edits, base).rejected +
          (edits['rejected'] is int ? edits['rejected'] as int : 0);
      if (rejected > 0) status += ' 基準に合わない履歴$rejected件を表示から除いています。';
      if (mounted) {
        setState(() {
          _base = base;
          _edits = edits;
          _status = status;
          _error = null;
        });
      }
    } on Object catch (e) {
      if (mounted) setState(() => _error = '履歴ファイルを読めません：$e');
    }
  }

  void _say(String s) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
    }
  }

  Future<void> _save(String group, Map<String, dynamic> entry) async {
    if (_busy || !_editable) return;
    var now = DateTime.now().toUtc();
    for (final old in parseHistoryEdits(_edits, _base!)[group]) {
      if (historyKey(group, old) == historyKey(group, entry)) {
        final previous = historyStamp(old['updated_at']);
        if (!now.isAfter(previous)) {
          now = previous.add(const Duration(milliseconds: 1));
        }
      }
    }
    entry = {
      ...entry,
      'updated_at': now.toIso8601String(),
      'device': 'android',
    };
    final incoming = emptyHistoryEdits();
    (incoming[group] as List).add(entry);
    setState(() => _busy = true);
    try {
      final merged = await widget.onSave!(incoming);
      if (mounted) {
        setState(() {
          _edits = merged;
          final rejected = cleanHistoryEdits(merged, _base!).rejected;
          _status =
              '端末に保存しました。バックアップをPCへ取り込むと共有へ反映します。${rejected > 0 ? ' 基準に合わない履歴$rejected件を表示から除いています。' : ''}';
        });
      }
    } on Object catch (e) {
      _say('保存できませんでした：$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _open(String day, String name) => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ViewerMachinePage(
        data: widget.data,
        store: widget.store,
        machine: name,
        day: day,
      ),
    ),
  );
  Future<void> _link(Map w, Map m) async {
    final names =
        _index.entries
            .where(
              (e) =>
                  e.key.compareTo(w['from'] as String) >= 0 &&
                  e.key.compareTo(w['to'] as String) <= 0,
            )
            .expand((e) => e.value)
            .toSet()
            .toList()
          ..sort();
    if (names.isEmpty) {
      _say('対象週の保存済み機種がありません。');
      return;
    }
    String? selected = m['record_name'] as String?;
    if (!names.contains(selected)) selected = null;
    final result = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: Text(displayMachineName(m['name'] as String)),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('同じ機種であることを確認して、保存済みの機種名を選んでください。'),
                DropdownButtonFormField<String>(
                  initialValue: selected,
                  isExpanded: true,
                  items: [
                    for (final n in names)
                      DropdownMenuItem(value: n, child: Text(n, maxLines: 2)),
                  ],
                  onChanged: (v) => update(() => selected = v),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            TextButton(
              onPressed: selected == null
                  ? null
                  : () => Navigator.pop(context, selected),
              child: const Text('対応付ける'),
            ),
          ],
        ),
      ),
    );
    if (result != null) {
      await _save('links', {
        'store': historyStore,
        'machine': m['name'],
        'record_name': result,
      });
    }
  }

  String _missingRecord(String day) =>
      widget.recordCutoff != null && day.compareTo(widget.recordCutoff!) < 0
      ? '端末に記録がありません（60日より前）'
      : 'この日の記録なし';

  Widget _table(Map<String, dynamic> w) {
    final first = historyDate(w['from']);
    final days = List.generate(
      7,
      (i) => historyDay(first.add(Duration(days: i))),
    );
    final machines = w['machines'] as List;
    final rowHeight =
        (_editable ? 132.0 : 112.0) * MediaQuery.textScalerOf(context).scale(1);
    const headingHeight = 50.0, columnWidth = 112.0;
    Widget nameCell(Map m) => SizedBox(
      height: rowHeight,
      child: Padding(
        padding: const EdgeInsets.all(6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              displayMachineName(m['name'] as String),
              style:
                  !_saiwaichou &&
                      w['type'] == 'バラエティ' &&
                      !(m['results'] as List).contains('😍')
                  ? const TextStyle(color: Color(0xffb91c1c))
                  : null,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            Text("${m['count']}台", style: const TextStyle(fontSize: 12)),
            if (_editable)
              TextButton(
                onPressed: _busy ? null : () => _link(w, m),
                child: const Text('保存名の対応', style: TextStyle(fontSize: 11)),
              ),
          ],
        ),
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (w['lineup_day'] != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text("分類日：${w['lineup_day']}（作成時の構成で固定）"),
          ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 148,
              child: Column(
                children: [
                  const SizedBox(
                    height: headingHeight,
                    child: Center(child: Text('機種名・台数')),
                  ),
                  for (final m in machines) nameCell(m as Map),
                ],
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Column(
                  children: [
                    SizedBox(
                      height: headingHeight,
                      child: Row(
                        children: [
                          for (var i = 0; i < 7; i++)
                            SizedBox(
                              width: columnWidth,
                              child: Center(
                                child: Text(
                                  "${days[i].substring(5)} ${'月火水木金土日'[i]}",
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                    for (final m in machines)
                      SizedBox(
                        height: rowHeight,
                        child: Row(
                          children: [
                            for (var i = 0; i < 7; i++)
                              Builder(
                                builder: (context) {
                                  final name = historySavedName(
                                    m as Map,
                                    _index[days[i]] ?? {},
                                  );
                                  return Container(
                                    width: columnWidth,
                                    padding: const EdgeInsets.all(4),
                                    decoration: BoxDecoration(
                                      border: Border.all(
                                        color: Theme.of(context).dividerColor
                                            .withValues(alpha: .3),
                                      ),
                                    ),
                                    child: Column(
                                      mainAxisAlignment:
                                          MainAxisAlignment.center,
                                      children: [
                                        if (_editable)
                                          DropdownButton<String>(
                                            key: ValueKey(
                                              'symbol:${w['from']}:${m['name']}:$i',
                                            ),
                                            value: m['results'][i] as String,
                                            items: [
                                              for (final s in [
                                                '',
                                                ..._base!['symbols'] as List,
                                              ])
                                                DropdownMenuItem(
                                                  value: s as String,
                                                  child: Text(
                                                    s.isEmpty ? '空欄' : s,
                                                    style: const TextStyle(
                                                      fontSize: 20,
                                                    ),
                                                  ),
                                                ),
                                            ],
                                            onChanged: _busy
                                                ? null
                                                : (v) {
                                                    if (v != null) {
                                                      _save('cells', {
                                                        'store': historyStore,
                                                        'type': w['type'],
                                                        'week': w['from'],
                                                        'machine': m['name'],
                                                        'day': days[i],
                                                        'value': v,
                                                      });
                                                    }
                                                  },
                                          )
                                        else
                                          Text(
                                            m['results'][i] as String,
                                            style: const TextStyle(
                                              fontSize: 24,
                                            ),
                                          ),
                                        TextButton(
                                          onPressed: name == null
                                              ? null
                                              : () => _open(days[i], name),
                                          child: Text(
                                            name == null
                                                ? _missingRecord(days[i])
                                                : '開く →',
                                            style: const TextStyle(
                                              fontSize: 10,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ),
                                  );
                                },
                              ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final base = _base;
    if (_error != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('イベント履歴')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_error!),
          ),
        ),
      );
    }
    if (base == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('イベント履歴')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }
    final weeks = historyWeeks(
      base,
      _edits,
    ).where((w) => w['type'] == _type).toList();
    if (!weeks.any((w) => w['from'] == _week)) {
      _week = weeks.isEmpty ? null : weeks.first['from'] as String;
    }
    final selected = weeks.where((w) => w['from'] == _week).firstOrNull;
    return Scaffold(
      appBar: AppBar(title: Text(_title)),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey(_type),
            isExpanded: true,
            initialValue: _type,
            decoration: const InputDecoration(labelText: 'イベント種別'),
            items: [
              for (final t in historyTypesForStore(widget.store))
                DropdownMenuItem(value: t, child: Text(t)),
            ],
            onChanged: _busy
                ? null
                : (v) {
                    if (v != null) setState(() => _type = v);
                  },
          ),
          const SizedBox(height: 12),
          if (weeks.isNotEmpty)
            DropdownButtonFormField<String>(
              key: ValueKey('$_type:$_week'),
              isExpanded: true,
              initialValue: _week,
              decoration: const InputDecoration(labelText: '対象週'),
              items: [
                for (final w in weeks)
                  DropdownMenuItem(
                    value: w['from'] as String,
                    child: Text("${w['from']}〜${w['to']}"),
                  ),
              ],
              onChanged: (v) => setState(() => _week = v),
            ),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(_status),
            ),
          if (_busy) const LinearProgressIndicator(),
          if (selected == null)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Text('この種別の週表はまだありません。'),
            )
          else
            _table(selected),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(
              _saiwaichou
                  ? '2,500枚以上＝優、0〜2,499枚＝良。マイナス・差枚不明は空欄です。入力・修正はPCのみ。'
                  : '記号の意味は未設定です。「開く」は、その機種・その日の保存データを表示します。',
            ),
          ),
        ],
      ),
    );
  }
}
