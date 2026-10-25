import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'event_history_model.dart';
import 'recommendations.dart';
import 'recommendations_view.dart';
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
    this.browserLayout = kIsWeb,
  });
  final ViewerData data;
  final Map<String, dynamic>? edits;
  final Future<Map<String, dynamic>> Function(Map<String, dynamic>)? onSave;
  final String? remoteUrl;
  final String? recordCutoff;
  final Future<Map<String, dynamic>> Function() loadBase;
  final String store;
  final bool browserLayout;
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
  bool _recommendationResultsEditing = false;
  bool _sharedEditing = false;
  String get _historyPendingKey =>
      'event-history-pending:${widget.remoteUrl ?? 'local'}';
  Map<String, dynamic> _pendingWebHistory() {
    final text = loadViewerSetting(_historyPendingKey);
    if (text == null) return emptyHistoryEdits();
    final raw = jsonDecode(text);
    validateHistoryEnvelope(raw);
    return Map<String, dynamic>.from(raw as Map);
  }

  bool get _saiwaichou => widget.store == saiwaichouHistoryStore;
  String get _title => _saiwaichou ? '幸町のバラエティ履歴' : '長町南のイベント履歴';
  bool get _editable => !_saiwaichou && (widget.onSave != null || kIsWeb);
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
        final key = 'event-history:$url';
        dynamic raw;
        try {
          if (url == null) {
            throw const FormatException('共有するにはGoogleドライブの自動読み込みを設定してください。');
          }
          raw = jsonDecode(await fetchSharedEvents(url, 'event-history'));
          if (raw is! Map || raw['base'] == null) {
            throw const FormatException('編集の反映にはApps Scriptの更新が必要です。');
          }
          final document = historyDocumentForStore(raw, widget.store);
          base = parseHistoryBase(document['base']);
          edits = document;
          _recommendationResultsEditing =
              raw['recommendation_results_editing'] == true;
          _sharedEditing = raw['shared_editing'] == true;
          cleanHistoryEdits(edits, base);
          saveViewerSetting(key, jsonEncode(raw));
        } on Object catch (error) {
          final cached = loadViewerSetting(key);
          if (cached == null) {
            if (_saiwaichou) rethrow;
            base = {
              'version': 2,
              'store': widget.store,
              'symbols': ['😀', '😍', '🥶', '😌', '😇'],
              'weeks': [],
              'user_blank_days': [],
            };
            edits = emptyHistoryEdits();
            status = '共有の履歴を取得できません。4大オススメの顔文字は端末に保存できます。$error';
            raw = null;
          } else {
            raw = jsonDecode(cached);
            final document = historyDocumentForStore(raw, widget.store);
            base = parseHistoryBase(document['base']);
            edits = document;
            status = '最新の履歴を取得できません。保存済みの内容を表示しています。$error';
          }
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
      if (kIsWeb && !_saiwaichou) {
        final pending = _pendingWebHistory();
        edits = {...edits, ...mergeHistoryEdits(edits, pending, base).edits};
        if ((pending['cells'] as List).isNotEmpty ||
            (pending['recommendation_results'] as List? ?? []).isNotEmpty) {
          status += ' 顔文字は共有への送信待ちです。「未送信の顔文字を再送」で再送できます。';
        }
      }
      if (base['store'] != widget.store) {
        throw const FormatException('履歴の店舗が一致しません。');
      }
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

  Future<void> _saveRecommendationResult(Map<String, dynamic> entry) async {
    if (kIsWeb) {
      await _saveWebHistory('recommendation_results', entry);
      return;
    }
    if (widget.onSave == null) throw const FormatException('この画面では保存できません。');
    final next = await widget.onSave!({
      ...emptyHistoryEdits(),
      'recommendation_results': [entry],
    });
    if (mounted) {
      setState(() {
        _edits = next;
        _status = '端末に保存しました。バックアップをPCへ取り込むと共有へ反映します。';
      });
    }
  }

  Future<void> _saveWebHistory(String group, Map<String, dynamic> entry) async {
    final incoming = {
      ...emptyHistoryEdits(),
      group: [
        {...entry, 'device': 'shared'},
      ],
    };
    final pending = mergeHistoryEdits(
      _pendingWebHistory(),
      incoming,
      _base!,
    ).edits;
    final text = jsonEncode(pending);
    saveViewerSetting(_historyPendingKey, text);
    if (loadViewerSetting(_historyPendingKey) != text) {
      throw const FormatException('端末に顔文字を保存できません。');
    }
    if (mounted) {
      setState(() {
        _edits = {
          ..._edits,
          ...mergeHistoryEdits(_edits, pending, _base!).edits,
        };
        _status = '顔文字を端末に保存しました。共有への送信待ちです。';
      });
    }
    if (group == 'recommendation_results'
        ? !_recommendationResultsEditing
        : !_sharedEditing) {
      throw const FormatException(
        '端末には保存済みです。共有するには閲覧・共有用Apps Scriptを更新して再読み込み後に再送してください。',
      );
    }
    await _flushWebHistory();
  }

  Future<void> _flushWebHistory() async {
    final url = widget.remoteUrl;
    if (url == null) {
      throw const FormatException('共有するにはGoogleドライブの自動読み込みを設定してください。');
    }
    final pending = _pendingWebHistory();
    final cells = _sharedEditing
        ? (pending['cells'] as List).take(100).toList()
        : <dynamic>[];
    final results = _recommendationResultsEditing
        ? (pending['recommendation_results'] as List? ?? [])
              .take(100 - cells.length)
              .toList()
        : <dynamic>[];
    if (cells.isEmpty && results.isEmpty) {
      throw const FormatException('共有用Apps Scriptの更新後に再読み込みしてください。');
    }
    final answer = jsonDecode(
      await postSharedEvents(
        url,
        jsonEncode({
          'file': 'event-history',
          'cells': cells,
          'recommendation_results': results,
        }),
      ),
    );
    if (answer is! Map || answer['ok'] != true || answer['history'] is! Map) {
      throw FormatException(
        '端末には保存済みです。${answer is Map ? answer['error'] ?? '共有へ送信できませんでした。' : '共有の返答が不正です。'}',
      );
    }
    final remote = Map<String, dynamic>.from(answer['history'] as Map);
    final sent = {'cells': cells, 'recommendation_results': results};
    for (final group in sent.keys) {
      for (final c in sent[group]!) {
        final key = group == 'cells'
            ? historyKey(group, c)
            : recommendationResultKey(c);
        final hits = (remote[group] as List? ?? []).where((r) {
          try {
            return (group == 'cells'
                    ? historyKey(group, r)
                    : recommendationResultKey(r)) ==
                key;
          } on Object {
            return false;
          }
        }).toList();
        if (!hits.any(
          (r) =>
              !historyStamp(r['updated_at'])
                  .isBefore(historyStamp(c['updated_at'])),
        )) {
          throw const FormatException('共有の保存確認ができません。端末の送信待ちを保持します。');
        }
      }
    }
    final remaining = _pendingWebHistory();
    for (final group in sent.keys) {
      remaining[group] = (remaining[group] as List? ?? [])
          .where((c) => !sent[group]!.any((s) => sameRecommendation(c, s)))
          .toList();
    }
    final text = jsonEncode(remaining);
    saveViewerSetting(_historyPendingKey, text);
    saveViewerSetting('event-history:$url', jsonEncode(remote));
    final stillPending =
        (remaining['cells'] as List).length +
        (remaining['recommendation_results'] as List).length;
    if (mounted) {
      setState(() {
        _edits = {
          ...remote,
          ...mergeHistoryEdits(remote, remaining, _base!).edits,
        };
        _status = loadViewerSetting(_historyPendingKey) != text
            ? '共有へ保存しましたが、端末の送信済み状態を更新できません。'
            : stillPending > 0
            ? '共有へ保存しました。残り$stillPending件は送信待ちです。'
            : '共有へ保存しました。ほかの画面は最新を読むと反映します。';
      });
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
    if (kIsWeb) {
      setState(() => _busy = true);
      try {
        await _saveWebHistory(group, entry);
      } on Object catch (e) {
        _say('顔文字は共有への送信待ちです：$e');
      } finally {
        if (mounted) setState(() => _busy = false);
      }
      return;
    }
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

  Widget _browserTable(Map<String, dynamic> week) {
    final first = historyDate(week['from']);
    final days = List.generate(
      7,
      (i) => historyDay(first.add(Duration(days: i))),
    );
    final machines = week['machines'] as List;
    final recordedDays =
        _index.keys
            .where(
              (d) =>
                  d.compareTo(week['from'] as String) >= 0 &&
                  d.compareTo(week['to'] as String) <= 0,
            )
            .toList()
          ..sort();
    final lastRecordDay = recordedDays.lastOrNull;
    final allWeeks = historyWeeks(_base!, _edits);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(
            '${machines.length}機種${week['lineup_day'] == null ? '' : ' · 分類日：${week['lineup_day']}'}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        if (_saiwaichou)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              lastRecordDay == null
                  ? 'この週は記録がないため赤字判定はしません。'
                  : '赤字：$lastRecordDayまでの直近5暦日、優・良なし（空欄の日を含む）。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        for (final machine in machines)
          Container(
            key: ValueKey('history-card:${week['from']}:${machine['name']}'),
            margin: const EdgeInsets.only(bottom: 14),
            padding: const EdgeInsets.fromLTRB(10, 14, 10, 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              border: Border.all(color: const Color(0xffdce4ef)),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  displayMachineName(machine['name'] as String),
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 15,
                    color:
                        (_saiwaichou &&
                                historyGradeGap(
                                  allWeeks,
                                  machine as Map,
                                  lastRecordDay,
                                )) ||
                            (!_saiwaichou &&
                                week['type'] == 'バラエティ' &&
                                !(machine['results'] as List).contains('😍'))
                        ? const Color(0xffb91c1c)
                        : null,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '${machine['count']}台',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var i = 0; i < 7; i++)
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 1),
                          child: Builder(
                            builder: (context) {
                              final name = historySavedName(
                                machine as Map,
                                _index[days[i]] ?? {},
                              );
                              final grade = machine['results'][i] as String;
                              final background = grade == '優'
                                  ? const Color(0xfffff1ce)
                                  : grade == '良'
                                  ? const Color(0xffe7f4ed)
                                  : const Color(0xfff4f7fb);
                              final foreground = grade == '優'
                                  ? const Color(0xff8a4900)
                                  : grade == '良'
                                  ? const Color(0xff17634c)
                                  : const Color(0xff586576);
                              return Column(
                                children: [
                                  Text(
                                    '月火水木金土日'[i],
                                    style: const TextStyle(fontSize: 12),
                                  ),
                                  Text(
                                    days[i].substring(8),
                                    style: const TextStyle(fontSize: 11),
                                  ),
                                  const SizedBox(height: 6),
                                  if (_editable && kIsWeb)
                                    Semantics(
                                      label:
                                          '${days[i]} ${machine['name']}の顔文字',
                                      child: DropdownButton<String>(
                                        value: grade,
                                        isExpanded: true,
                                        iconSize: 10,
                                        items: [
                                          for (final s in [
                                            '',
                                            ..._base!['symbols'] as List,
                                          ])
                                            DropdownMenuItem(
                                              value: s as String,
                                              child: Text(
                                                s.isEmpty ? '—' : s,
                                                style: const TextStyle(
                                                  fontSize: 20,
                                                ),
                                              ),
                                            ),
                                        ],
                                        onChanged: _busy
                                            ? null
                                            : (v) => _save('cells', {
                                                'store': historyStore,
                                                'type': week['type'],
                                                'week': week['from'],
                                                'machine': machine['name'],
                                                'day': days[i],
                                                'value': v!,
                                              }),
                                      ),
                                    ),
                                  Semantics(
                                    label:
                                        '${days[i]} ${displayMachineName(machine['name'] as String)} ${grade.isEmpty ? '空欄' : grade} ${name == null ? _missingRecord(days[i]) : 'データを開く'}',
                                    child: Tooltip(
                                      message: name == null
                                          ? _missingRecord(days[i])
                                          : '${days[i]}のデータを開く',
                                      child: TextButton(
                                        key: ValueKey(
                                          'history-day:${week['from']}:${machine['name']}:$i',
                                        ),
                                        style: TextButton.styleFrom(
                                          minimumSize: const Size(0, 64),
                                          padding: EdgeInsets.zero,
                                          backgroundColor: background,
                                          foregroundColor: foreground,
                                          disabledBackgroundColor: background,
                                          disabledForegroundColor: foreground,
                                          shape: RoundedRectangleBorder(
                                            borderRadius: BorderRadius.circular(
                                              8,
                                            ),
                                          ),
                                        ),
                                        onPressed: name == null
                                            ? null
                                            : () => _open(days[i], name),
                                        child: Column(
                                          children: [
                                            if (!(_editable && kIsWeb))
                                              Text(
                                                grade.isEmpty ? '—' : grade,
                                                style: const TextStyle(
                                                  fontSize: 20,
                                                  fontWeight: FontWeight.w600,
                                                ),
                                              ),
                                            Text(
                                              name == null ? '—' : '↗',
                                              style: const TextStyle(
                                                fontSize: 12,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              );
                            },
                          ),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
      ],
    );
  }

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
    if (widget.browserLayout) {
      weeks.sort(
        (a, b) => (b['from'] as String).compareTo(a['from'] as String),
      );
    }
    if (!weeks.any((w) => w['from'] == _week)) {
      _week = weeks.isEmpty ? null : weeks.first['from'] as String;
    }
    final selected = weeks.where((w) => w['from'] == _week).firstOrNull;
    return Scaffold(
      appBar: AppBar(
        title: Text(_title),
        actions: [
          if (kIsWeb)
            IconButton(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              tooltip: '再読み込み',
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey(_type),
            isExpanded: true,
            initialValue: _type,
            decoration: const InputDecoration(labelText: 'イベント種別'),
            items: [
              for (final t in [
                ...historyTypesForStore(widget.store),
                if (!_saiwaichou) recommendationType,
              ])
                DropdownMenuItem(value: t, child: Text(t)),
            ],
            onChanged: _busy
                ? null
                : (v) {
                    if (v != null) setState(() => _type = v);
                  },
          ),
          const SizedBox(height: 12),
          if (_type != recommendationType && weeks.isNotEmpty)
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
          if (widget.browserLayout && selected != null)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Wrap(
                alignment: WrapAlignment.spaceBetween,
                spacing: 4,
                runSpacing: 4,
                children: [
                  OutlinedButton.icon(
                    onPressed: weeks.indexOf(selected) < weeks.length - 1
                        ? () => setState(
                            () => _week =
                                weeks[weeks.indexOf(selected) + 1]['from']
                                    as String,
                          )
                        : null,
                    icon: const Icon(Icons.chevron_left, size: 18),
                    label: const Text('前の週'),
                  ),
                  TextButton(
                    onPressed: weeks.indexOf(selected) == 0
                        ? null
                        : () => setState(
                            () => _week = weeks.first['from'] as String,
                          ),
                    child: const Text('最新の週'),
                  ),
                  OutlinedButton.icon(
                    onPressed: weeks.indexOf(selected) > 0
                        ? () => setState(
                            () => _week =
                                weeks[weeks.indexOf(selected) - 1]['from']
                                    as String,
                          )
                        : null,
                    icon: const Icon(Icons.chevron_right, size: 18),
                    label: const Text('次の週'),
                  ),
                ],
              ),
            ),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(_status),
            ),
          if (_busy) const LinearProgressIndicator(),
          if (kIsWeb && !_saiwaichou)
            TextButton(
              onPressed: () async {
                try {
                  await _flushWebHistory();
                } on Object catch (e) {
                  _say('再送できません：$e');
                }
              },
              child: const Text('未送信の顔文字を再送'),
            ),
          if (_type == recommendationType)
            RecommendationsView(
              records: widget.data.records,
              plans: _edits['recommendations'] as List? ?? [],
              results: _edits['recommendation_results'] as List? ?? [],
              onResult: _saveRecommendationResult,
              onOpen: (record) => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) =>
                      ViewerRecordPage(data: widget.data, record: record),
                ),
              ),
            )
          else if (selected == null)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Text('この種別の週表はまだありません。'),
            )
          else
            widget.browserLayout ? _browserTable(selected) : _table(selected),
          if (_type != recommendationType)
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
