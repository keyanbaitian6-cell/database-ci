import 'dart:convert';

import 'package:flutter/services.dart';

import 'models.dart';
import 'recommendations.dart';

const historyStore = 'nagamachiminami';
const saiwaichouHistoryStore = 'saiwaichou';
const saiwaichouHistoryKey = 'saiwaichou_variety';
const historyTypes = ['4台構成', '半列', 'バラエティ'];
const historyFormat = 'database-event-history';

List<String> historyTypesForStore(String store) =>
    store == saiwaichouHistoryStore ? ['バラエティ'] : historyTypes;

Map<String, dynamic> saiwaichouHistoryBase() => {
  'version': 2,
  'store': saiwaichouHistoryStore,
  'symbols': ['優', '良'],
  'user_blank_days': <String>[],
  'weeks': <dynamic>[],
};

Map<String, dynamic> historyEditsForStore(
  Map<String, dynamic> raw,
  String store,
) {
  if (store == historyStore) return raw;
  if (store != saiwaichouHistoryStore) {
    throw const FormatException('対応していない店舗です。');
  }
  return raw[saiwaichouHistoryKey] == null
      ? emptyHistoryEdits()
      : Map<String, dynamic>.from(raw[saiwaichouHistoryKey] as Map);
}

Map<String, dynamic> historyDocumentForStore(dynamic raw, String store) {
  if (raw is! Map) throw const FormatException('履歴ファイルを読めません。');
  final root = Map<String, dynamic>.from(raw);
  if (store == historyStore) return root;
  if (store != saiwaichouHistoryStore || root[saiwaichouHistoryKey] is! Map) {
    throw const FormatException('PCで幸町のバラエティ履歴を共有へ反映してください。');
  }
  return Map<String, dynamic>.from(root[saiwaichouHistoryKey] as Map);
}

Map<String, dynamic> emptyHistoryEdits() => {
  'format': historyFormat,
  'version': 1,
  'cells': <dynamic>[],
  'weeks': <dynamic>[],
  'links': <dynamic>[],
};

DateTime historyDate(Object? raw) {
  if (raw is! String || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(raw)) {
    throw const FormatException('履歴の日付が読めません。');
  }
  final d = DateTime.tryParse('${raw}T00:00:00Z');
  if (d == null || d.year < 1 || historyDay(d) != raw) {
    throw const FormatException('履歴の日付が不正です。');
  }
  return d;
}

String historyDay(DateTime d) => d.toUtc().toIso8601String().substring(0, 10);

/// 幸町の赤字（利用者指定、2026-10-29）：今日を除いた直前5暦日に、機種の合計差枚が
/// +800枚を超えた日が無い機種。記録の無い日・差枚不明の日は「超えていない」と数え、
/// 手入力の優（2,500枚以上の意味）は超えた日と数える。PC event_history_data.grade_gap と同じ。
const saiwaichouGapNet = 800;
const saiwaichouGapDays = 5;

/// 店の台を日ごとに分ける（自動の優・良と赤字の差枚計算用）。
Map<String, List<SlotRecord>> historyRacksByDay(
  List<SlotRecord> records, {
  String store = saiwaichouHistoryStore,
}) {
  final out = <String, List<SlotRecord>>{};
  for (final r in records) {
    if (r.store == store) (out[r.day] ??= []).add(r);
  }
  return out;
}

/// 週表の機種のその日の合計差枚。保存名が決まり、全台の差枚が分かり（数値異常の台なし）、
/// 台数が週表と同じときだけ。PC event_history_data.item_day_net と同じ。
int? saiwaichouMachineNet(
  Map machine,
  String day,
  Map<String, List<SlotRecord>> racks,
) {
  final rows = racks[day];
  if (rows == null) return null;
  final name = historySavedName(machine, {for (final r in rows) r.machine});
  if (name == null) return null;
  final mine = rows.where((r) => r.machine == name).toList();
  if (mine.length != machine['count'] ||
      mine.any((r) => hasImplausibleNumbers(r) || r.netValue == null)) {
    return null;
  }
  return mine.fold<int>(0, (sum, r) => sum + r.netValue!);
}

/// 2,500枚以上は優、0〜2,499枚は良。マイナス・不明は空欄（PC net_grade と同じ）。
String saiwaichouNetGrade(int? total) => total == null || total < 0
    ? ''
    : total >= 2500
    ? '優'
    : '良';

/// 空欄のマスに、その日の機種合計差枚からの優・良を入れた週一覧（表示用。保存しない）。
/// 手入力の優・良はそのまま（2026-10-29 利用者指定、4大オススメと同じく表示時に自動判定）。
List<Map<String, dynamic>> saiwaichouAutoWeeks(
  List<Map<String, dynamic>> weeks,
  Map<String, List<SlotRecord>> racks,
) => [
  for (final w in weeks)
    {
      ...w,
      'machines': [
        for (final m in w['machines'] as List)
          {
            ...m as Map,
            'results': [
              for (var i = 0; i < 7; i++)
                (m['results'] as List)[i] as String != ''
                    ? (m['results'] as List)[i] as String
                    : saiwaichouNetGrade(
                        saiwaichouMachineNet(
                          m,
                          historyDay(
                            historyDate(w['from']).add(Duration(days: i)),
                          ),
                          racks,
                        ),
                      ),
            ],
          },
      ],
    },
];

/// 赤字判定の最終日：表示週の最後の記録日。ただし今日（日本時間）は含めない。
String? saiwaichouGapEnd(String? lastRecordDay, DateTime now) {
  if (lastRecordDay == null) return null;
  final jst = now.toUtc().add(const Duration(hours: 9));
  final yesterday = historyDay(
    DateTime.utc(
      jst.year,
      jst.month,
      jst.day,
    ).subtract(const Duration(days: 1)),
  );
  return lastRecordDay.compareTo(yesterday) < 0 ? lastRecordDay : yesterday;
}

/// [endDay] までの5暦日に、合計差枚が+800枚を超えた日も優の日も無ければ true。
/// 前週にまたがる日も、同じ機種名・明示的な保存名の週表から優を探す。
bool saiwaichouGradeGap(
  Iterable<Map<String, dynamic>> weeks,
  Map machine,
  String? endDay,
  Map<String, List<SlotRecord>> racks,
) {
  if (endDay == null) return false;
  final end = historyDate(endDay);
  for (var offset = 0; offset < saiwaichouGapDays; offset++) {
    final target = historyDay(end.subtract(Duration(days: offset)));
    final total = saiwaichouMachineNet(machine, target, racks);
    if (total != null && total > saiwaichouGapNet) return false;
    for (final week in weeks) {
      if (week['type'] != 'バラエティ' ||
          target.compareTo(week['from'] as String) < 0 ||
          target.compareTo(week['to'] as String) > 0) {
        continue;
      }
      final saved = (week['machines'] as List)
          .where(
            (m) =>
                m['name'] == machine['name'] ||
                (machine['record_name'] != null &&
                    machine['record_name'] != '' &&
                    m['record_name'] == machine['record_name']),
          )
          .firstOrNull;
      if (saved == null) continue;
      final value =
          saved['results'][historyDate(target)
              .difference(historyDate(week['from']))
              .inDays];
      if (value == '優') return false;
    }
  }
  return true;
}

DateTime historyStamp(Object? raw) {
  if (raw is! String) throw const FormatException('履歴の編集時刻が読めません。');
  final match = RegExp(
    r'^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$',
  ).firstMatch(raw);
  if (match == null) throw const FormatException('履歴の編集時刻が読めません。');
  historyDate(match[1]);
  if (int.parse(match[2]!) > 23 ||
      int.parse(match[3]!) > 59 ||
      int.parse(match[4]!) > 59) {
    throw const FormatException('履歴の編集時刻が不正です。');
  }
  final zone = match[6]!;
  if (zone != 'Z' &&
      (int.parse(zone.substring(1, 3)) > 23 ||
          int.parse(zone.substring(4, 6)) > 59)) {
    throw const FormatException('履歴の時差が不正です。');
  }
  return DateTime.parse(raw).toUtc();
}

bool _name(Object? s) =>
    s is String &&
    s.trim().isNotEmpty &&
    s.runes.length <= 300 &&
    !RegExp(r'[\x00-\x1f]').hasMatch(s);

Map<String, dynamic> _machine(
  dynamic raw,
  List symbols, {
  bool results = true,
}) {
  if (raw is! Map ||
      !_name(raw['name']) ||
      raw['count'] is! int ||
      raw['count'] < 1 ||
      raw['count'] > 9999 ||
      (raw['record_name'] != null && !_name(raw['record_name']))) {
    throw const FormatException('履歴の機種情報が読めません。');
  }
  final values = raw['results'];
  if (results &&
      (values is! List ||
          values.length != 7 ||
          values.any(
            (v) => v is! String || (v != '' && !symbols.contains(v)),
          ))) {
    throw const FormatException('結果記号が読めません。');
  }
  return {
    'name': raw['name'],
    'count': raw['count'],
    'record_name': raw['record_name'],
    if (results) 'results': List<String>.from(values as List),
  };
}

Map<String, dynamic> parseHistoryBase(dynamic raw) {
  if (raw is! Map ||
      raw['version'] != 2 ||
      ![historyStore, saiwaichouHistoryStore].contains(raw['store']) ||
      raw['symbols'] is! List ||
      raw['weeks'] is! List) {
    throw const FormatException('履歴ファイルを読めません。');
  }
  final symbols = raw['symbols'] as List;
  final store = raw['store'] as String;
  if (store == saiwaichouHistoryStore &&
      jsonEncode(symbols) != jsonEncode(['優', '良'])) {
    throw const FormatException('幸町の評価は優・良だけです。');
  }
  if (symbols.isEmpty ||
      symbols.any((v) => !_name(v) || (v as String).runes.length > 16) ||
      symbols.toSet().length != symbols.length) {
    throw const FormatException('記号一覧が読めません。');
  }
  final seen = <String>{};
  final weeks = <Map<String, dynamic>>[];
  for (final w in raw['weeks']) {
    if (w is! Map ||
        !historyTypesForStore(store).contains(w['type']) ||
        w['machines'] is! List) {
      throw const FormatException('週の形式が違います。');
    }
    final first = historyDate(w['from']), last = historyDate(w['to']);
    if (first.weekday != 1 ||
        last.difference(first).inDays != 6 ||
        !seen.add(w['from'] as String)) {
      throw const FormatException('週が重複または不正です。');
    }
    final machines = [for (final m in w['machines']) _machine(m, symbols)];
    if (store == saiwaichouHistoryStore &&
        machines.any((m) => m['count'] > 2)) {
      throw const FormatException('幸町のバラエティは1〜2台機種です。');
    }
    if (machines.map((m) => m['name']).toSet().length != machines.length) {
      throw const FormatException('機種名が重複しています。');
    }
    weeks.add({
      'type': w['type'],
      'from': w['from'],
      'to': w['to'],
      'machines': machines,
    });
  }
  final blanks = raw['user_blank_days'] ?? [];
  if (blanks is! List) throw const FormatException('空欄の日付が読めません。');
  for (final d in blanks) {
    historyDate(d);
  }
  return {
    'version': 2,
    'store': store,
    'symbols': List<String>.from(symbols),
    'user_blank_days': blanks,
    'weeks': weeks,
  };
}

Future<Map<String, dynamic>> loadHistoryBase() async => parseHistoryBase(
  jsonDecode(await rootBundle.loadString('assets/event_history.json')),
);

/// バックアップ外枠の検証。値と機種の照合は基準ファイルと合わせて保存前に行う。
void validateHistoryEnvelope(dynamic raw, {bool nested = false}) {
  if (raw is! Map ||
      raw['format'] != historyFormat ||
      raw['version'] != 1 ||
      [
        'cells',
        'weeks',
        'links',
        'recommendations',
        'recommendation_results',
      ].any((k) => raw.containsKey(k) && raw[k] is! List)) {
    throw const FormatException('履歴編集の形式が不正です。');
  }
  if ([
    'cells',
    'weeks',
    'links',
    'recommendations',
    'recommendation_results',
  ].any((k) => raw.containsKey(k) && (raw[k] as List).length > 30000)) {
    throw const FormatException('履歴編集の保存件数の上限（各30,000件）を超えるため保存できません。');
  }
  if (raw.containsKey(saiwaichouHistoryKey)) {
    if (nested) throw const FormatException('幸町の履歴を入れ子にできません。');
    validateHistoryEnvelope(raw[saiwaichouHistoryKey], nested: true);
  }
}

/// バックアップに書く履歴。外枠が壊れた文書をそのまま書くとバックアップ全体が取り込めなくなるので、
/// 正しい空の外枠に包んで原文だけ残す（PC `Store.history_edits_raw` と同じ）。
Map<String, dynamic>? historyForBackup(String? raw) {
  if (raw == null || raw.isEmpty) return null;
  try {
    final decoded = jsonDecode(raw);
    validateHistoryEnvelope(decoded);
    return Map<String, dynamic>.from(decoded as Map);
  } on Object {
    return {...emptyHistoryEdits(), 'unreadable_raw': raw};
  }
}

({Map<String, dynamic> edits, int rejected, Map<String, List<dynamic>> orphans})
cleanHistoryEdits(dynamic raw, Map<String, dynamic> base) {
  validateHistoryEnvelope(raw);
  final store = base['store'] as String;
  final maxRacks = store == saiwaichouHistoryStore ? 2 : 3;
  final out = emptyHistoryEdits(), orphans = <String, List<dynamic>>{};
  var rejected = 0;
  void reject(String group, dynamic value) {
    rejected++;
    (orphans[group] ??= []).add(value);
  }

  final weeks = <String, dynamic>{
    for (final w in base['weeks']) '${w['type']}|${w['from']}': w,
  };
  final occupied = <String, String>{
    for (final w in base['weeks']) w['from'] as String: w['type'] as String,
  };
  final definitions = <String, Map<String, dynamic>>{};
  for (final w in (raw['weeks'] as List? ?? const [])) {
    try {
      if (w is! Map ||
          w['store'] != store ||
          w['type'] != 'バラエティ' ||
          (w.containsKey('removed') && w['removed'] is! bool) ||
          w['machines'] is! List) {
        throw const FormatException();
      }
      final first = historyDate(w['week']),
          lineup = historyDate(w['lineup_day']);
      historyStamp(w['updated_at']);
      if (first.weekday != 1 ||
          lineup.difference(first).inDays < 0 ||
          lineup.difference(first).inDays > 6 ||
          (occupied[w['week']] ?? 'バラエティ') != 'バラエティ') {
        throw const FormatException();
      }
      final machines = [
        for (final m in w['machines'])
          _machine(m, base['symbols'] as List, results: false),
      ];
      if (machines.isEmpty ||
          machines.any((m) => m['count'] > maxRacks) ||
          machines.map((m) => m['name']).toSet().length != machines.length) {
        throw const FormatException();
      }
      final entry = <String, dynamic>{
        'store': store,
        'type': 'バラエティ',
        'week': w['week'],
        'lineup_day': w['lineup_day'],
        'machines': machines,
        'updated_at': w['updated_at'],
        'removed': w['removed'] ?? false,
      };
      final key = 'バラエティ|${w['week']}', prior = definitions[key];
      if (prior != null &&
          historyStamp(entry['updated_at'])
              .isBefore(historyStamp(prior['updated_at']))) {
        continue;
      }
      definitions[key] = entry;
      weeks[key] = {'machines': machines};
      occupied[w['week'] as String] = 'バラエティ';
    } on Object {
      reject('weeks', w);
    }
  }
  out['weeks'] = definitions.values.toList();
  final names = <String>{
    for (final w in weeks.values)
      for (final m in w['machines']) m['name'] as String,
  };
  for (final group in ['cells', 'links']) {
    final entries = <String, Map<String, dynamic>>{};
    for (final c in (raw[group] as List? ?? const [])) {
      try {
        if (c is! Map || c['store'] != store || !_name(c['machine'])) {
          throw const FormatException();
        }
        historyStamp(c['updated_at']);
        final scoped =
            group == 'cells' || c.containsKey('week') || c.containsKey('type');
        final entry = <String, dynamic>{
          for (final k in ['store', 'machine', 'updated_at']) k: c[k],
          'device': ['pc', 'android', 'shared'].contains(c['device'])
              ? c['device']
              : 'pc',
        };
        DateTime? first;
        if (scoped) {
          if (!historyTypesForStore(store).contains(c['type'])) {
            throw const FormatException();
          }
          first = historyDate(c['week']);
          final w = weeks['${c['type']}|${c['week']}'];
          if (w == null ||
              !(w['machines'] as List).any((m) => m['name'] == c['machine'])) {
            throw const FormatException();
          }
          entry.addAll({'type': c['type'], 'week': c['week']});
        } else if (!names.contains(c['machine'])) {
          throw const FormatException();
        }
        if (group == 'cells') {
          final offset = historyDate(c['day']).difference(first!).inDays;
          if (offset < 0 ||
              offset > 6 ||
              c['value'] is! String ||
              (c['value'] != '' &&
                  !(base['symbols'] as List).contains(c['value']))) {
            throw const FormatException();
          }
          entry.addAll({'day': c['day'], 'value': c['value']});
        } else {
          if (c['record_name'] != null && !_name(c['record_name'])) {
            throw const FormatException();
          }
          entry['record_name'] = c['record_name'];
        }
        final key = historyKey(group, entry), prior = entries[key];
        if (prior == null ||
            !historyStamp(entry['updated_at'])
                .isBefore(historyStamp(prior['updated_at']))) {
          entries[key] = entry;
        }
      } on Object {
        reject(group, c);
      }
    }
    out[group] = entries.values.toList();
  }
  if (store == historyStore && raw['recommendations'] != null) {
    out['recommendations'] = mergeRecommendations(
      [],
      raw['recommendations'] as List,
      strict: false,
    );
  }
  if (store == historyStore && raw['recommendation_results'] != null) {
    out['recommendation_results'] = mergeRecommendationResults(
      raw['recommendation_results'] as List,
      [],
      strict: false,
    );
  }
  return (edits: out, rejected: rejected, orphans: orphans);
}

Map<String, dynamic> parseHistoryEdits(
  dynamic raw,
  Map<String, dynamic> base,
) => cleanHistoryEdits(raw, base).edits;

String historyKey(String group, dynamic c) => jsonEncode([
  c['store'],
  if (group == 'links' && !c.containsKey('week') && !c.containsKey('type')) ...[
    '',
    '',
    c['machine'],
  ] else ...[
    c['type'],
    c['week'],
    if (group != 'weeks') c['machine'],
    if (group == 'cells') c['day'],
  ],
]);

({
  Map<String, dynamic> edits,
  int changed,
  int conflicts,
  int rejected,
  int weekConflicts,
})
mergeHistoryEdits(
  Map<String, dynamic> stored,
  Map<String, dynamic> incoming,
  Map<String, dynamic> base,
) {
  validateHistoryEnvelope(incoming);
  if (stored.containsKey('unreadable_raw') ||
      incoming.containsKey('unreadable_raw')) {
    throw const FormatException('履歴の原文が読めません。原本とバックアップを保持してください。');
  }
  final current = cleanHistoryEdits(stored, base), old = current.edits;
  final fixed = <String, dynamic>{
    for (final w in old['weeks']) historyKey('weeks', w): w,
  };
  final proposed = cleanHistoryEdits({
    ...emptyHistoryEdits(),
    'weeks': incoming['weeks'] ?? [],
  }, base);
  final accepted = <String, dynamic>{...fixed};
  var skippedWeeks = 0;
  for (final w in proposed.edits['weeks']) {
    final key = historyKey('weeks', w), previous = fixed[key];
    if (previous != null &&
        [
          'lineup_day',
          'machines',
          'removed',
        ].any((k) => jsonEncode(previous[k]) != jsonEncode(w[k]))) {
      skippedWeeks++;
      continue;
    }
    if (previous == null) accepted[key] = w;
  }
  final fresh = cleanHistoryEdits({
    ...incoming,
    'weeks': accepted.values.toList(),
  }, base);
  final out = emptyHistoryEdits();
  var changed = 0, conflicts = 0;
  for (final group in ['weeks', 'cells', 'links']) {
    final entries = <String, dynamic>{
      for (final c in old[group]) historyKey(group, c): c,
    };
    final source = group == 'weeks'
        ? accepted.entries
              .where((e) => !fixed.containsKey(e.key))
              .map((e) => e.value)
        : fresh.edits[group] as List;
    for (final c in source) {
      final key = historyKey(group, c), previous = entries[key];
      final take =
          previous == null ||
          !historyStamp(c['updated_at'])
              .isBefore(historyStamp(previous['updated_at']));
      if (take && jsonEncode(c) != jsonEncode(previous)) {
        if (previous != null &&
            previous['device'] != c['device'] &&
            ['value', 'record_name'].any((k) => previous[k] != c[k])) {
          conflicts++;
        }
        entries[key] = c;
        changed++;
      }
    }
    out[group] = [
      for (final k in entries.keys.toList()..sort()) entries[k],
      // 同じ場所により新しい正しい編集がある基準外の編集は捨てる（PC `superseded` と同じ）。
      for (final o in current.orphans[group] ?? [])
        if (!_superseded(group, o, entries)) o,
    ];
  }
  var nestedRejected = 0;
  if (base['store'] == historyStore &&
      (stored.containsKey(saiwaichouHistoryKey) ||
          incoming.containsKey(saiwaichouHistoryKey))) {
    final variety = mergeHistoryEdits(
      historyEditsForStore(stored, saiwaichouHistoryStore),
      historyEditsForStore(incoming, saiwaichouHistoryStore),
      saiwaichouHistoryBase(),
    );
    out[saiwaichouHistoryKey] = variety.edits;
    changed += variety.changed;
    conflicts += variety.conflicts;
    skippedWeeks += variety.weekConflicts;
    nestedRejected = variety.rejected;
  }
  if (base['store'] == historyStore &&
      (stored.containsKey('recommendations') ||
          incoming.containsKey('recommendations'))) {
    final previous = stored['recommendations'] as List? ?? [];
    out['recommendations'] = mergeRecommendations(
      previous,
      incoming['recommendations'] as List? ?? [],
    );
    changed += (out['recommendations'] as List)
        .where((p) => !previous.any((old) => sameRecommendation(p, old)))
        .length;
  }
  if (base['store'] == historyStore &&
      (stored.containsKey('recommendation_results') ||
          incoming.containsKey('recommendation_results'))) {
    final previous = stored['recommendation_results'] as List? ?? [];
    out['recommendation_results'] = mergeRecommendationResults(
      previous,
      incoming['recommendation_results'] as List? ?? [],
    );
    changed += (out['recommendation_results'] as List)
        .where((p) => !previous.any((old) => sameRecommendation(p, old)))
        .length;
  }
  // 合流結果も読み取り側の上限内に保ち、保存済みの履歴を読めなくしない。
  validateHistoryEnvelope(out);
  return (
    edits: out,
    changed: changed,
    conflicts: conflicts,
    rejected:
        current.rejected + proposed.rejected + fresh.rejected + nestedRejected,
    weekConflicts: skippedWeeks,
  );
}

/// 基準外の編集 [orphan] と同じ場所に、同時刻以降の正しい編集があるか。場所を読めない原文は残す。
bool _superseded(String group, dynamic orphan, Map<String, dynamic> entries) {
  try {
    final valid = entries[historyKey(group, orphan)];
    return valid != null &&
        !historyStamp(valid['updated_at'])
            .isBefore(historyStamp(orphan['updated_at']));
  } on Object {
    return false;
  }
}

List<Map<String, dynamic>> historyWeeks(
  Map<String, dynamic> base,
  Map<String, dynamic> edits,
) {
  final clean = parseHistoryEdits(edits, base);
  final weeks = <String, Map<String, dynamic>>{
    for (final w in base['weeks'])
      '${w['type']}|${w['from']}': Map<String, dynamic>.from(
        jsonDecode(jsonEncode(w)) as Map,
      ),
  };
  for (final w in clean['weeks']) {
    final key = '${w['type']}|${w['week']}';
    if (w['removed'] == true) {
      weeks.remove(key);
      continue;
    }
    weeks[key] = {
      'type': w['type'],
      'from': w['week'],
      'to': historyDay(historyDate(w['week']).add(const Duration(days: 6))),
      'lineup_day': w['lineup_day'],
      'machines': [
        for (final m in w['machines'])
          {...m as Map, 'results': List.filled(7, '')},
      ],
    };
  }
  final globals = (clean['links'] as List).where((c) => !c.containsKey('week'));
  final scoped = (clean['links'] as List).where((c) => c.containsKey('week'));
  for (final c in [...globals, ...scoped]) {
    final Iterable<Map<String, dynamic>?> targets = c.containsKey('week')
        ? [weeks['${c['type']}|${c['week']}']]
        : weeks.values;
    for (final w in targets) {
      if (w == null) continue;
      for (final m in w['machines']) {
        if (m['name'] == c['machine']) m['record_name'] = c['record_name'];
      }
    }
  }
  for (final c in clean['cells']) {
    final w = weeks['${c['type']}|${c['week']}'];
    if (w == null) continue;
    for (final m in w['machines']) {
      if (m['name'] == c['machine']) {
        m['results'][historyDate(c['day'])
                .difference(historyDate(c['week']))
                .inDays] =
            c['value'];
      }
    }
  }
  return weeks.values.toList()
    ..sort((a, b) => (b['from'] as String).compareTo(a['from'] as String));
}

Map<String, Set<String>> historyRecordIndex(
  List<SlotRecord> records, {
  String store = historyStore,
}) {
  final index = <String, Set<String>>{};
  for (final r in records) {
    if (r.store == store) (index[r.day] ??= {}).add(r.machine);
  }
  return index;
}

String? historySavedName(Map m, Set<String> names) {
  if (m['record_name'] != null) {
    return names.contains(m['record_name']) ? m['record_name'] as String : null;
  }
  final hits = names
      .where(
        (n) =>
            normalizeMachineName(n) ==
            normalizeMachineName(m['name'] as String),
      )
      .toList();
  return hits.length == 1 ? hits.single : null;
}

Map<String, dynamic> newHistoryVarietyWeek(
  List<SlotRecord> records,
  String monday,
) {
  final first = historyDate(monday);
  if (first.weekday != 1) throw const FormatException('週開始日は月曜日を選んでください。');
  final days = <String, Map<String, SlotRecord>>{};
  for (final r in records) {
    if (r.store != historyStore) continue;
    final offset = historyDate(r.day).difference(first).inDays;
    if (offset >= -13 && offset <= 6) {
      (days[r.day] ??= {})['${r.machine}|${r.rack}'] = r;
    }
  }
  final usual = days.values.fold<int>(0, (a, b) => a > b.length ? a : b.length);
  final candidates =
      days.keys
          .where(
            (d) =>
                !historyDate(d).isBefore(first) &&
                days[d]!.length >= usual * .8,
          )
          .toList()
        ..sort();
  if (candidates.isEmpty) {
    throw const FormatException('対象週の記録が足りません。週表を作成しませんでした。');
  }
  final counts = <String, int>{};
  for (final r in days[candidates.first]!.values) {
    counts[r.machine] = (counts[r.machine] ?? 0) + 1;
  }
  final names = counts.keys.where((n) => counts[n]! <= 3).toList()..sort();
  if (names.isEmpty) throw const FormatException('対象日にバラエティの機種がありません。');
  return {
    'store': historyStore,
    'type': 'バラエティ',
    'week': monday,
    'lineup_day': candidates.first,
    'machines': [
      for (final n in names) {'name': n, 'record_name': n, 'count': counts[n]},
    ],
    'doubtful': names
        .where(
          (n) => days.values.any(
            (rows) => rows.values.where((r) => r.machine == n).length > 3,
          ),
        )
        .toList(),
    'removed': false,
    'updated_at': DateTime.now().toUtc().toIso8601String(),
  };
}
