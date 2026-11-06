import 'dart:convert';

const netProbeMax = 64 * 1024;
const netProbeBudget = 3 * 1024 * 1024;
const netProbeDays = 7;
const _numbers = ['bb', 'rb', 'at_art', 'games', 'my'];
Never _bad() => throw const FormatException('差枚の取得診断が不正です。');
bool _day(dynamic s) =>
    s is String &&
    RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(s) &&
    DateTime.tryParse(s)?.toIso8601String().substring(0, 10) == s;
bool _scalar(dynamic v) =>
    v == null ||
    (v is num && v.isFinite && v.abs() <= 1e12) ||
    (v is String && v.length <= 32 && RegExp(r'^[-+\d.eE]*$').hasMatch(v));

Map<String, dynamic> _probe(dynamic raw) {
  if (raw is! Map) _bad();
  final graph = raw['graph'];
  final datas = graph is Map ? graph['datas'] : null;
  final day = raw['day'];
  final numbers = raw['numbers'];
  if (raw['version'] != 1 ||
      raw['rack'] is! int ||
      (raw['rack'] as int) < 1 ||
      day is! String ||
      !RegExp(r'^\d{8}$').hasMatch(day) ||
      !_day(
        '${day.substring(0, 4)}-${day.substring(4, 6)}-${day.substring(6)}',
      ) ||
      numbers is! List ||
      numbers.isEmpty ||
      numbers.length > 7 ||
      datas is! Map ||
      datas['g'] is! List ||
      (datas['g'] as List).length > 7 ||
      datas['p'] is! List ||
      (datas['p'] as List).length > 50000 ||
      !_scalar(graph['anjYUnit'] ?? 1)) {
    _bad();
  }
  final counts = <Map<String, dynamic>>[];
  for (final r in numbers) {
    if (r is! Map ||
        !_day(r['day']) ||
        _numbers.any((k) => r[k] is! int || (r[k] as int) < 0)) {
      _bad();
    }
    counts.add({'day': r['day'], for (final k in _numbers) k: r[k]});
  }
  final fields = <String>{};
  final series = <Map<String, dynamic>>[];
  for (final line in datas['g'] as List) {
    if (line is! Map ||
        !_scalar(line['YMD_biz']) ||
        !RegExp(r'^\d{8}$').hasMatch('${line['YMD_biz']}') ||
        !RegExp(r'^out-\d{1,5}$').hasMatch('${line['xField']}') ||
        !RegExp(r'^value-\d{1,5}$').hasMatch('${line['yField']}')) {
      _bad();
    }
    fields.addAll([line['xField'] as String, line['yField'] as String]);
    series.add({
      for (final k in ['YMD_biz', 'xField', 'yField']) k: line[k],
    });
  }
  final points = <Map<String, dynamic>>[];
  for (final p in datas['p'] as List) {
    if (p is! Map || fields.any((k) => p.containsKey(k) && !_scalar(p[k]))) {
      _bad();
    }
    points.add({
      for (final k in fields)
        if (p.containsKey(k)) k: p[k],
    });
  }
  final result = <String, dynamic>{
    'version': 1,
    'rack': raw['rack'],
    'day': day,
    'numbers': counts,
    'graph': {
      'anjYUnit': graph['anjYUnit'] ?? 1,
      'datas': {'g': series, 'p': points},
    },
  };
  if (utf8.encode(jsonEncode(result)).length > netProbeMax) _bad();
  return result;
}

Map<String, dynamic>? validateNetCapture(dynamic value, {Map? record}) {
  if (value == null) return null;
  if (value is! Map ||
      value['version'] != 1 ||
      ![
        'ok',
        'empty',
        'invalid',
        'network',
        'unavailable',
        'unknown',
      ].contains(value['status']) ||
      ![
        'ok',
        'missing_series',
        'empty',
        'short_series',
        'invalid_points',
        'invalid_net',
        'invalid_response',
        'network',
        'not_ready',
      ].contains(value['reason']) ||
      value['checked_at'] is! String ||
      !RegExp(r'(Z|[+-]\d{2}:\d{2})$')
          .hasMatch(value['checked_at'] as String) ||
      DateTime.tryParse(value['checked_at'] as String) == null) {
    _bad();
  }
  final result = <String, dynamic>{
    for (final k in ['version', 'status', 'reason', 'checked_at']) k: value[k],
  };
  if (value['http_status'] != null) {
    if (value['http_status'] is! int ||
        (value['http_status'] as int) < 0 ||
        (value['http_status'] as int) > 599) {
      _bad();
    }
    result['http_status'] = value['http_status'];
  }
  if (value['probe_omitted'] != null) {
    if (![
      'size',
      'unsafe',
      'expired',
      'budget',
    ].contains(value['probe_omitted'])) {
      _bad();
    }
    result['probe_omitted'] = value['probe_omitted'];
  }
  if (value['probe'] != null) {
    final probe = _probe(value['probe']);
    if (record != null &&
        (probe['rack'] != record['rack'] ||
            !(probe['numbers'] as List).any(
              (n) =>
                  n['day'] == record['day'] &&
                  _numbers.every((k) => n[k] == record[k]),
            ))) {
      _bad();
    }
    result['probe'] = probe;
  }
  if (value['probe_available'] != null) {
    if (value['probe_available'] is! bool) _bad();
    result['probe_available'] = value['probe_available'];
  }
  return result;
}

void trimNetProbes(List<Map<String, dynamic>> records, {DateTime? now}) {
  final time = (now ?? DateTime.now()).millisecondsSinceEpoch;
  var remaining = netProbeBudget;
  final samples =
      records
          .where((r) => (r['net_capture'] as Map?)?['probe'] != null)
          .toList()
        ..sort(
          (a, b) => DateTime.parse(
            b['net_capture']['checked_at'] as String,
          ).compareTo(DateTime.parse(a['net_capture']['checked_at'] as String)),
        );
  for (final row in samples) {
    final capture = Map<String, dynamic>.from(row['net_capture'] as Map);
    final at = DateTime.parse(capture['checked_at'] as String)
        .millisecondsSinceEpoch;
    final size = utf8.encode(jsonEncode(capture['probe'])).length;
    final reason = at < time - netProbeDays * 86400000 || at > time + 300000
        ? 'expired'
        : size > remaining
        ? 'budget'
        : null;
    if (reason != null) {
      capture.remove('probe');
      capture.remove('probe_available');
      capture['probe_omitted'] = reason;
      row['net_capture'] = capture;
    } else {
      remaining -= size;
    }
  }
}

Map<String, dynamic>? mergeNetCapture(Map chosen, Map alternate, bool same) {
  final a = chosen['net_capture'] as Map?, b = alternate['net_capture'] as Map?;
  final pick =
      same &&
          b != null &&
          (a == null ||
              DateTime.parse(b['checked_at'] as String)
                  .isAfter(DateTime.parse(a['checked_at'] as String)) ||
              (b['checked_at'] == a['checked_at'] &&
                  b['probe'] != null &&
                  a['probe'] == null))
      ? b
      : a;
  return pick == null ? null : Map<String, dynamic>.from(pick);
}

String netCaptureLabel(Map row) {
  if (row['net_medals'] is int) {
    return row['net_medals'] == 0 ? '取得済み（0枚）' : '取得済み';
  }
  if (['anaslo', 'site777'].contains(row['source_site'])) return '出典に差枚なし';
  return {
        'missing_series': '日別の系列なし',
        'empty': '元数値が空',
        'short_series': '元数値の点が不足',
        'invalid_points': '元数値の形式不正',
        'invalid_net': '差枚の範囲不正',
        'invalid_response': '応答の形式不正',
        'network': '差枚の通信失敗',
        'not_ready': 'サイトの通信準備前',
      }[(row['net_capture'] as Map?)?['reason']] ??
      '未取得（理由未記録）';
}

Map<String, dynamic>? validateSyncStatus(dynamic raw) {
  if (raw == null) return null;
  bool time(dynamic x) =>
      x is String &&
      RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(x) &&
      DateTime.tryParse(x) != null;
  if (raw is! Map ||
      raw['version'] != 1 ||
      raw['writes'] is! List ||
      (raw['writes'] as List).length > 3) {
    throw const FormatException('更新状況の形式が不正です。');
  }
  final writes = <Map<String, dynamic>>[];
  for (final w in raw['writes'] as List) {
    if (w is! Map ||
        !['pc', 'android', 'browser'].contains(w['source']) ||
        !time(w['at']) ||
        (w['drive_at'] != null && !time(w['drive_at'])) ||
        w['stores'] is! List ||
        (w['stores'] as List).length > 100) {
      throw const FormatException('更新状況の形式が不正です。');
    }
    final stores = <Map<String, dynamic>>[];
    for (final s in w['stores'] as List) {
      if (s is! Map ||
          !RegExp(r'^[A-Za-z0-9_-]{1,80}$').hasMatch('${s['store'] ?? ''}') ||
          (s['rate'] != null &&
              !RegExp(r'^\d+(?:\.\d+)?$').hasMatch('${s['rate']}')) ||
          !_day(s['day']) ||
          s['count'] is! int ||
          (s['count'] as int) < 0) {
        throw const FormatException('更新状況の店舗情報が不正です。');
      }
      stores.add({
        'store': s['store'],
        if (s['rate'] != null) 'rate': s['rate'],
        'day': s['day'],
        'count': s['count'],
      });
    }
    writes.add({
      'source': w['source'],
      'at': w['at'],
      if (w['drive_at'] != null) 'drive_at': w['drive_at'],
      'stores': stores,
    });
  }
  if (writes.map((w) => w['source']).toSet().length != writes.length ||
      (raw['processed_at'] != null && !time(raw['processed_at']))) {
    throw const FormatException('更新状況の形式が不正です。');
  }
  final result = <String, dynamic>{
    'version': 1,
    'writes': writes,
    if (raw['processor_release'] is String &&
        RegExp(r'^[a-f0-9]{12}$').hasMatch(raw['processor_release']))
      'processor_release': raw['processor_release'],
    if (raw['processed_at'] != null) 'processed_at': raw['processed_at'],
  };
  for (final k in ['pending', 'failed_inputs']) {
    if (raw[k] != null) {
      if (raw[k] is! int || (raw[k] as int) < 0 || (raw[k] as int) > 1000000) {
        throw const FormatException('更新状況の形式が不正です。');
      }
      result[k] = raw[k];
    }
  }
  if (raw['supplement'] != null) {
    final s = raw['supplement'];
    if (s is! Map ||
        !time(s['at']) ||
        ['applied', 'known', 'mismatched', 'unmatched'].any(
          (k) => s[k] is! int || (s[k] as int) < 0 || (s[k] as int) > 1000000,
        )) {
      throw const FormatException('補完結果の形式が不正です。');
    }
    result['supplement'] = {
      'at': s['at'],
      for (final k in ['applied', 'known', 'mismatched', 'unmatched']) k: s[k],
    };
  }
  if (raw['supplement_supported'] != null) {
    if (raw['supplement_supported'] is! bool) {
      throw const FormatException('更新状況の形式が不正です。');
    }
    result['supplement_supported'] = raw['supplement_supported'];
  }
  return result;
}

Map<String, dynamic>? mergeSyncStatuses(dynamic first, dynamic second) {
  final writes = <String, Map<String, dynamic>>{};
  Map<String, dynamic>? latest;
  Map<String, dynamic>? supplement;
  for (final raw in [first, second]) {
    final status = validateSyncStatus(raw);
    if (status == null) continue;
    for (final item in status['writes'] as List) {
      final w = Map<String, dynamic>.from(item as Map),
          old = writes[w['source']];
      final time = DateTime.parse(w['at'] as String);
      final oldTime = old == null ? null : DateTime.parse(old['at'] as String);
      final drive = DateTime.tryParse('${w['drive_at'] ?? ''}');
      final oldDrive = DateTime.tryParse('${old?['drive_at'] ?? ''}');
      if (old == null ||
          time.isAfter(oldTime!) ||
          (time.isAtSameMomentAs(oldTime) &&
              drive != null &&
              (oldDrive == null || drive.isAfter(oldDrive)))) {
        writes[w['source'] as String] = w;
      }
    }
    if (status['processed_at'] != null &&
        (latest == null ||
            !DateTime.parse(status['processed_at'] as String)
                .isBefore(DateTime.parse(latest['processed_at'] as String)))) {
      latest = status;
    }
    final s = status['supplement'];
    if (s is Map &&
        (supplement == null ||
            !DateTime.parse(s['at'] as String)
                .isBefore(DateTime.parse(supplement['at'] as String)))) {
      supplement = Map<String, dynamic>.from(s);
    }
  }
  if (writes.isEmpty && latest == null && supplement == null) return null;
  return {
    'version': 1,
    'writes': writes.values.toList(),
    if (latest != null)
      for (final k in [
        'processed_at',
        'pending',
        'failed_inputs',
        'supplement_supported',
        'processor_release',
      ])
        if (latest[k] != null) k: latest[k],
    'supplement': ?supplement,
  };
}

Map<String, dynamic>? makeSyncWrite(
  String? source,
  String? at,
  List<Map<String, dynamic>> records,
) {
  if (!['pc', 'android', 'browser'].contains(source) ||
      at == null ||
      DateTime.tryParse(at) == null) {
    return null;
  }
  final stores = <String, Map<String, dynamic>>{};
  for (final r in records) {
    if (!_day(r['day'])) continue;
    final key = jsonEncode([r['store'], r['rate']]);
    final value = stores.putIfAbsent(
      key,
      () => {
        'store': r['store'],
        if (r['rate'] != null) 'rate': r['rate'],
        'day': r['day'],
        'count': 0,
      },
    );
    final order = (r['day'] as String).compareTo(value['day'] as String);
    if (order > 0) {
      value['day'] = r['day'];
      value['count'] = 1;
    } else if (order == 0) {
      value['count'] = (value['count'] as int) + 1;
    }
  }
  return validateSyncStatus({
    'version': 1,
    'writes': [
      {'source': source, 'at': at, 'stores': stores.values.toList()},
    ],
  });
}

List<String> updateStatusLines(
  dynamic raw, {
  String? exportedAt,
  String? loadedAt,
  String? checkedAt,
}) {
  final status = validateSyncStatus(raw);
  String when(dynamic value) {
    final at = value is String ? DateTime.tryParse(value)?.toLocal() : null;
    if (at == null) return '未確認';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${at.year}/${two(at.month)}/${two(at.day)} ${two(at.hour)}:${two(at.minute)}:${two(at.second)}';
  }

  final lines = <String>[
    for (final w in (status?['writes'] as List? ?? [])) ...[
      '${{'pc': 'PC', 'android': 'Android', 'browser': 'iPhone・ブラウザ'}[w['source']]}の書き出し：${when(w['at'])}／Driveファイルの更新：${when(w['drive_at'])}',
      for (final s in w['stores'] as List)
        'この出力の最新日：${{'nagamachiminami': '長町南', 'saiwaichou': '幸町'}[s['store']] ?? (RegExp(r'^c\d+$').hasMatch(s['store'] as String) ? 'P’s CUBE' : s['store'])}${s['rate'] == null ? '' : '（${s['rate']}スロ）'} ${s['day']}・${s['count']}台',
    ],
  ];
  if (lines.isEmpty) lines.add('元ファイルの書き出し：未確認');
  lines.add('Google処理の版：${status?['processor_release'] ?? '未確認'}');
  lines.add('Google側の処理：${when(status?['processed_at'])}');
  if ((status?['pending'] as int? ?? 0) > 0 ||
      (status?['failed_inputs'] as int? ?? 0) > 0) {
    lines.add(
      'Google側の処理待ち ${status?['pending'] ?? 0}件・入力失敗 ${status?['failed_inputs'] ?? 0}件',
    );
  }
  lines.addAll([
    '閲覧データの書き出し：${when(exportedAt)}',
    'この端末の読み込み：${when(loadedAt)}',
  ]);
  if (checkedAt != null) lines.add('この端末で最新か確認：${when(checkedAt)}');
  final s = status?['supplement'];
  if (s is Map) {
    lines.add(
      'スマホ補完：反映 ${s['applied']}件・取得済み ${s['known']}件・数値不一致 ${s['mismatched']}件・元記録なし ${s['unmatched']}件（${when(s['at'])}）',
    );
  }
  return lines;
}

/// 取り込み画面と閲覧画面で同じ区別を使う。欠測を0枚として数えない。
List<String> netStatusLines(List<Map<String, dynamic>> records) {
  final known = records.where((r) => r['net_medals'] is int).length;
  final zero = records.where((r) => r['net_medals'] == 0).length;
  final missing = records.where((r) => r['net_medals'] is! int).toList();
  return [
    '差枚：${records.length}台中$known台取得済み（0枚$zero台）・未取得${missing.length}台',
    for (final r in missing)
      '${r['rack']}番 ${r['machine']}：${netCaptureLabel(r)}',
    if (missing.length > 200) '残り${missing.length - 200}台は別の日・機種の表示で確認してください。',
    if (missing.isNotEmpty)
      '元数値を受信できていれば再解析できます。元数値自体が無い場合は、更新した取得アプリでの再取得が必要です。',
  ];
}
