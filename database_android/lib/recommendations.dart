import 'dart:convert';

import 'models.dart';

const recommendationType = '4大オススメ';
const recommendationDefault = <String, dynamic>{
  'store': 'nagamachiminami',
  'week': '2026-10-26',
  'machines': ['L 甲鉄城のｶﾊﾞﾈﾘ 海門決戦 XX', 'L戦国乙女5L8', 'L戦国乙女4S3', 'Lﾓﾝｷｰﾀｰﾝ5CE'],
  'updated_at': '2026-10-24T00:00:00Z',
  'device': 'pc',
};

String recommendationWeek(dynamic raw) {
  final d = raw is String ? DateTime.tryParse('${raw}T00:00:00Z') : null;
  if (d == null ||
      d.year < 1 ||
      d.weekday != 1 ||
      d.toIso8601String().substring(0, 10) != raw) {
    throw const FormatException('週開始日は月曜日を指定してください。');
  }
  return raw as String;
}

List<String> recommendationDays(String week) {
  final first = DateTime.parse('${recommendationWeek(week)}T00:00:00Z');
  return List.generate(
    7,
    (i) => first.add(Duration(days: i)).toIso8601String().substring(0, 10),
  );
}

String _normal(String s) =>
    s.replaceAll('+', ' ').replaceAll(RegExp(r'\s+'), '').toLowerCase();

Map<String, dynamic> recommendationPlan(dynamic raw) {
  if (raw is! Map ||
      raw['store'] != 'nagamachiminami' ||
      raw['machines'] is! List) {
    throw const FormatException('4機種の店舗・一覧が不正です。');
  }
  final names = raw['machines'] as List;
  if (names.length != 4 ||
      names.any(
        (n) =>
            n is! String ||
            n.trim().isEmpty ||
            n.runes.length > 300 ||
            RegExp(r'[\x00-\x1f]').hasMatch(n),
      ) ||
      names.cast<String>().map(_normal).toSet().length != 4) {
    throw const FormatException('異なる4機種を選んでください。');
  }
  recommendationWeek(raw['week']);
  final at = raw['updated_at'];
  if (at is! String ||
      !RegExp(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$',
      ).hasMatch(at) ||
      DateTime.tryParse(at) == null) {
    throw const FormatException('4機種の編集時刻が不正です。');
  }
  final match = RegExp(
    r'^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$',
  ).firstMatch(at)!;
  final date = DateTime.tryParse('${match[1]}T00:00:00Z');
  final zone = match[5]!;
  if (date == null ||
      date.year < 1 ||
      date.toIso8601String().substring(0, 10) != match[1] ||
      int.parse(match[2]!) > 23 ||
      int.parse(match[3]!) > 59 ||
      int.parse(match[4]!) > 59 ||
      (zone != 'Z' &&
          (int.parse(zone.substring(1, 3)) > 23 ||
              int.parse(zone.substring(4, 6)) > 59))) {
    throw const FormatException('4機種の編集時刻が不正です。');
  }
  return {
    'store': raw['store'],
    'week': raw['week'],
    'machines': List<String>.from(names),
    'updated_at': at,
    'device': ['pc', 'android', 'shared'].contains(raw['device'])
        ? raw['device']
        : 'pc',
  };
}

List<dynamic> mergeRecommendations(
  List<dynamic> stored,
  List<dynamic> incoming, {
  bool strict = true,
}) {
  if (stored.length > 3000 || incoming.length > 3000) {
    throw const FormatException('4機種の週一覧が上限に達しています。');
  }
  final plans = <String, Map<String, dynamic>>{}, orphans = <dynamic>[];
  for (final batch in [(stored, false), (incoming, strict)]) {
    for (final raw in batch.$1) {
      try {
        final p = recommendationPlan(raw), old = plans[p['week']];
        if (old == null ||
            !DateTime.parse(p['updated_at'])
                .isBefore(DateTime.parse(old['updated_at']))) {
          plans[p['week'] as String] = p;
        }
      } on Object {
        if (batch.$2) rethrow;
        orphans.add(raw);
      }
    }
  }
  final keys = plans.keys.toList()..sort((a, b) => b.compareTo(a));
  final result = [for (final key in keys) plans[key], ...orphans];
  if (result.length > 3000) throw const FormatException('4機種の週一覧が上限に達しています。');
  return result;
}

List<Map<String, dynamic>> recommendationPlans(List<dynamic> raw) =>
    mergeRecommendations([recommendationDefault], raw, strict: false).expand((
      p,
    ) {
      try {
        return [recommendationPlan(p)];
      } on Object {
        return <Map<String, dynamic>>[];
      }
    }).toList();

String? recommendationName(String selected, Iterable<String> names) {
  if (names.contains(selected)) return selected;
  final hits = names
      .where((n) => _normal(n) == _normal(selected))
      .toSet()
      .toList();
  return hits.length == 1 ? hits.first : null;
}

({String? day, Map<String, int> machines}) recommendationCandidates(
  List<SlotRecord> records,
  String week,
) {
  final end = recommendationDays(week).last;
  final rows = records
      .where((r) => r.store == 'nagamachiminami' && r.day.compareTo(end) <= 0)
      .toList();
  final dates = rows.map((r) => r.day).toList()..sort();
  final day = dates.lastOrNull;
  final groups = <String, Set<int>>{};
  for (final r in rows.where((r) => r.day == day)) {
    (groups[r.machine] ??= {}).add(r.rack);
  }
  final names = groups.keys.where((n) => groups[n]!.length >= 7).toList()
    ..sort();
  return (day: day, machines: {for (final n in names) n: groups[n]!.length});
}

List<({int rack, List<SlotRecord?> cells})> recommendationRows(
  List<SlotRecord> records,
  String week,
  String selected,
) {
  final days = recommendationDays(week);
  final rows = records
      .where((r) => r.store == 'nagamachiminami' && days.contains(r.day))
      .toList();
  final names = {
    for (final day in days)
      day: recommendationName(
        selected,
        rows.where((r) => r.day == day).map((r) => r.machine),
      ),
  };
  final cells = rows.where((r) => r.machine == names[r.day]).toList();
  final racks = cells.map((r) => r.rack).toSet().toList()..sort();
  return [
    for (final rack in racks)
      (
        rack: rack,
        cells: [
          for (final day in days)
            (() {
              final hits = cells
                  .where((r) => r.rack == rack && r.day == day)
                  .toList();
              return hits.length == 1 ? hits.first : null;
            })(),
        ],
      ),
  ];
}

String recommendationFace(num? net) => net == null || !net.isFinite
    ? ''
    : net >= 3000
    ? '😍'
    : net >= 1000
    ? '😀'
    : net >= 0
    ? '😌'
    : '🥶';

bool sameRecommendation(dynamic a, dynamic b) => jsonEncode(a) == jsonEncode(b);

const recommendationFaces = ['😀', '😍', '🥶', '😌', '😇'];
String recommendationResultKey(Map r) =>
    jsonEncode([r['store'], r['week'], r['machine'], r['rack'], r['day']]);
Map<String, dynamic> recommendationResult(dynamic raw) {
  if (raw is! Map ||
      ![
        'store',
        'week',
        'machine',
        'rack',
        'day',
        'value',
        'updated_at',
      ].every(raw.containsKey)) {
    throw const FormatException('台ごとの顔文字が不正です。');
  }
  final p = recommendationPlan({
    ...recommendationDefault,
    ...Map<String, dynamic>.from(raw),
    'machines': recommendationDefault['machines'],
  });
  if (raw['machine'] is! String ||
      (raw['machine'] as String).trim().isEmpty ||
      (raw['machine'] as String).runes.length > 300 ||
      RegExp(r'[\x00-\x1f]').hasMatch(raw['machine']) ||
      raw['rack'] is! int ||
      raw['rack'] < 0 ||
      raw['rack'] > 99999 ||
      !recommendationDays(raw['week']).contains(raw['day']) ||
      !raw.containsKey('value') ||
      ![null, '', ...recommendationFaces].contains(raw['value'])) {
    throw const FormatException('台ごとの顔文字が不正です。');
  }
  return {
    'store': p['store'],
    'week': p['week'],
    'machine': raw['machine'],
    'rack': raw['rack'],
    'day': raw['day'],
    'value': raw['value'],
    'updated_at': p['updated_at'],
    'device': p['device'],
  };
}

List<dynamic> mergeRecommendationResults(
  List<dynamic> stored,
  List<dynamic> incoming, {
  bool strict = true,
}) {
  if (stored.length > 30000 || incoming.length > 30000) {
    throw const FormatException('台ごとの結果一覧が上限に達しています。');
  }
  final results = <String, Map<String, dynamic>>{}, orphans = <dynamic>[];
  for (final batch in [(stored, false), (incoming, strict)]) {
    for (final raw in batch.$1) {
      try {
        final r = recommendationResult(raw);
        final key = recommendationResultKey(r), old = results[key];
        if (old == null ||
            !DateTime.parse(r['updated_at'])
                .isBefore(DateTime.parse(old['updated_at']))) {
          results[key] = r;
        }
      } on Object {
        if (batch.$2) rethrow;
        orphans.add(raw);
      }
    }
  }
  final keys = results.keys.toList()..sort();
  final out = [for (final key in keys) results[key], ...orphans];
  if (out.length > 30000) throw const FormatException('台ごとの結果一覧が上限に達しています。');
  return out;
}

Map<String, Map<String, dynamic>> recommendationResultIndex(List<dynamic> raw) {
  final out = <String, Map<String, dynamic>>{};
  for (final value in mergeRecommendationResults(raw, [], strict: false)) {
    try {
      final r = recommendationResult(value);
      out[recommendationResultKey(r)] = r;
    } on Object {
      /* 原文は保存したまま、表示に使わない。 */
    }
  }
  return out;
}
