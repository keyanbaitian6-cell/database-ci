import 'date_events.dart';
import 'models.dart';
import 'capture_health.dart';

/// P’s CUBEの日付ごとのイベント名1件（`web/pscube/data.mjs` の date_events と同じ形）。
/// [name] が null の記録は「イベントを消した」印（表示しない）。
class PscubeDateEvent {
  const PscubeDateEvent({
    required this.store,
    required this.rate,
    required this.day,
    required this.name,
    required this.updatedAt,
  });

  final String store, rate, day;
  final String? name;
  final String updatedAt;

  /// 画面で使う形（店舗は `pscube:店:貸玉`）。入力時刻はカレンダーの＊（前日までに入力したか）に使う。
  DateEvent get event => DateEvent(
    store: 'pscube:$store:$rate',
    day: day,
    name: name ?? '',
    updatedAt: updatedAt,
  );

  Map<String, Object?> toJson() => {
    'store': store,
    'rate': rate,
    'day': day,
    'name': name,
    'updated_at': updatedAt,
  };
}

/// イベント名を整える（`web/pscube/data.mjs` の cleanEventName と同じ）。空は null（イベントなし）。
String? cleanPscubeEventName(String? name) {
  if (name == null) return null;
  final text = name.trim();
  if (text.isEmpty) return null;
  // 文字数は PC（Python の len）と同じく1字ずつ数える（runes。🌈 も1字。2026-11-22、Codexの点検 #12）。
  if (text.runes.length > 60 || RegExp(r'[\u0000-\u001f\u007f]').hasMatch(text)) {
    throw const FormatException('イベント名は1〜60文字で入力してください。');
  }
  return text;
}

/// 同じ店舗・貸玉・日付は、更新時刻が新しい方（同じなら [incoming] の方）を残す。
List<PscubeDateEvent> mergePscubeDateEvents(
  Iterable<PscubeDateEvent> stored,
  Iterable<PscubeDateEvent> incoming,
) {
  final merged = {for (final e in stored) e.event.key: e};
  for (final e in incoming) {
    final previous = merged[e.event.key];
    if (previous == null ||
        !DateTime.parse(e.updatedAt)
            .isBefore(DateTime.parse(previous.updatedAt))) {
      merged[e.event.key] = e;
    }
  }
  return merged.values.toList();
}

final _pscubeStoreCode = RegExp(r'^c\d+$');
final _pscubeRate = RegExp(r'^\d+(?:\.\d+)?$');
final _eventTime = RegExp(r'^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$');

/// P’s CUBEのファイルの date_events を読む。以前の末尾イベの印（suffix_events）は
/// 「末尾イベ」という名前に読み替える（外した印は null）。同じ店舗・貸玉・日付は更新時刻が
/// 新しい方。形が違えば FormatException（`web/pscube/data.mjs` の validateDateEvents と同じ規則）。
List<PscubeDateEvent> pscubeDateEvents(Map<dynamic, dynamic> data) {
  List<PscubeDateEvent> read(
    Object? list,
    String what,
    String? Function(Map<dynamic, dynamic>) nameOf,
  ) {
    if (list == null) return const [];
    if (list is! List || list.length > 100000) {
      throw FormatException('$whatが不正です。');
    }
    final seen = <String>{};
    return [
      for (final raw in list)
        () {
          if (raw is! Map ||
              raw['store'] is! String ||
              !_pscubeStoreCode.hasMatch(raw['store']) ||
              raw['rate'] is! String ||
              !_pscubeRate.hasMatch(raw['rate']) ||
              raw['day'] is! String ||
              !isValidRecordDay(raw['day']) ||
              raw['updated_at'] is! String ||
              !_eventTime.hasMatch(raw['updated_at']) ||
              DateTime.tryParse(raw['updated_at']) == null) {
            throw FormatException('$whatが不正です。');
          }
          final event = PscubeDateEvent(
            store: raw['store'],
            rate: raw['rate'],
            day: raw['day'],
            name: nameOf(raw),
            updatedAt: raw['updated_at'],
          );
          if (!seen.add(event.event.key)) {
            throw FormatException('$whatが重複しています。');
          }
          return event;
        }(),
    ];
  }

  final legacy = read(data['suffix_events'], '末尾イベの印', (raw) {
    if (raw['enabled'] is! bool) {
      throw const FormatException('末尾イベの印が不正です。');
    }
    return raw['enabled'] == true ? suffixEventName : null;
  });
  final named = read(data['date_events'], 'イベント名', (raw) {
    final name = raw['name'];
    if (name == null) return null;
    if (name is! String) throw const FormatException('イベント名が不正です。');
    return cleanPscubeEventName(name);
  });
  return mergePscubeDateEvents(legacy, named);
}

/// 以前の末尾イベの印を読み替えるイベント名。
const suffixEventName = '末尾イベ';

/// 店舗（`pscube:店:貸玉`）ごとの、今までに付けたイベント名（新しく使った順、重複なし）。
Map<String, List<String>> pscubeEventNames(Iterable<PscubeDateEvent> events) {
  final latest = <String, Map<String, DateTime>>{};
  for (final e in events) {
    final name = e.name;
    if (name == null) continue;
    final names = latest.putIfAbsent(e.event.store, () => {});
    final time = DateTime.parse(e.updatedAt);
    if (names[name] == null || time.isAfter(names[name]!)) names[name] = time;
  }
  return {
    for (final entry in latest.entries)
      entry.key:
          (entry.value.entries.toList()..sort((a, b) {
                final byTime = b.value.compareTo(a.value);
                return byTime != 0 ? byTime : a.key.compareTo(b.key);
              }))
              .map((e) => e.key)
              .toList(),
  };
}

/// アナスロで補った台の推定差枚の形（PC `anaslo_net.valid` と同じ、2026-11-06）。
/// {'value': 整数, 'sure': 真偽, 'method': 'anaslo-graph-v1'} だけ。
const pscubeNetEstimateMethod = 'anaslo-graph-v1';
bool validPscubeNetEstimate(Object? value) =>
    value is Map &&
    value.length == 3 &&
    value['value'] is int &&
    (value['value'] as int).abs() <= 1000000 &&
    value['sure'] is bool &&
    value['method'] == pscubeNetEstimateMethod;

/// サイトセブンの台の推定差枚の形（PC `site777_net.valid` と同じ、2026-11-07）。グラフ画像の目盛りから
/// 読んだ値で、旧方式は50枚単位、新方式は1枚単位。
const site777LegacyNetEstimateMethod = 'site777-axis-pixels-v1';
const site777NetEstimateMethod = 'site777-axis-pixels-v2';
bool validSite777NetEstimate(Object? value) =>
    value is Map &&
    value.length == 3 &&
    value['value'] is int &&
    (value['value'] as int).abs() <= 1000000 &&
    value['sure'] is bool &&
    (value['method'] == site777NetEstimateMethod ||
        (value['method'] == site777LegacyNetEstimateMethod &&
            (value['value'] as int) % 50 == 0));

/// 補完の台の推定差枚が、出典に合った方式か（アナスロ・サイトセブン）。
bool validSupplementNetEstimate(Object? source, Object? value) =>
    (source == 'anaslo' && validPscubeNetEstimate(value)) ||
    (source == 'site777' && validSite777NetEstimate(value));

/// Convert at the input boundary so both data sites use the same viewer UI.
/// MY stays in extra['my']; it is never written to Meruhen's max_hold field.
void validateAnasloRecord(Map<dynamic, dynamic> row) {
  final url = Uri.tryParse(row['source_url']?.toString() ?? '');
  if (url == null ||
      url.scheme != 'https' ||
      url.host != 'ana-slo.com' ||
      url.userInfo.isNotEmpty ||
      url.hasPort ||
      !url.path.startsWith('/${row['day']}-') ||
      row['source_sha256'] is! String ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(row['source_sha256']) ||
      row['source_machine'] is! String ||
      (row['source_machine'] as String).trim().isEmpty ||
      [
        'my',
        'detail_url',
        'observed_at',
        'graph',
        'net_medals',
      ].any((k) => !row.containsKey(k) || row[k] != null)) {
    throw const FormatException('アナスロ履歴の出典または欠損値が不正です。');
  }
}

/// PCで採取したサイトセブンの出典・日付・未知値。追加通信は行わない。
void validateSite777Record(Map<dynamic, dynamic> row) {
  final url = Uri.tryParse(row['source_url']?.toString() ?? '');
  final day = row['day'];
  if (url == null ||
      url.scheme != 'https' ||
      url.host != 'm.site777.jp' ||
      url.userInfo.isNotEmpty ||
      url.hasPort ||
      url.path != '/f/D3300.do' ||
      url.queryParameters['pmc'] != '04034001' ||
      url.queryParameters['urt'] != '2000' ||
      !RegExp(r'^\d+$').hasMatch(url.queryParameters['mdc'] ?? '') ||
      [
        'pmc',
        'urt',
        'mdc',
        'dtdd',
        'pan',
      ].any((k) => (url.queryParametersAll[k]?.length ?? 0) > 1) ||
      row['store'] != 'c740601' ||
      row['rate'] != '20' ||
      day is! String ||
      !isValidRecordDay(day) ||
      row['source_sha256'] is! String ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(row['source_sha256']) ||
      row['source_machine'] is! String ||
      (row['source_machine'] as String).trim().isEmpty ||
      [
        'my',
        'at_art',
        'graph',
        'detail_url',
        'observed_at',
        'net_medals',
      ].any((k) => !row.containsKey(k)) ||
      ['detail_url', 'observed_at', 'net_medals'].any((k) => row[k] != null) ||
      (row.containsKey('net_estimate') &&
          !validSite777NetEstimate(row['net_estimate'])) ||
      row['net_capture'] != null ||
      ['my', 'at_art'].any(
        (k) =>
            row[k] != null &&
            (row[k] is! int || row[k] < 0 || row[k] > 1000000),
      )) {
    throw const FormatException('サイトセブンの出典・数値・欠損値が不正です。');
  }
  final label = row['source_day_label'] is String
      ? RegExp(r'^(\d{1,2})/(\d{1,2})$').firstMatch(row['source_day_label'])
      : null;
  final rawCaptured = row['source_captured_at'];
  final captured = rawCaptured is String
      ? DateTime.tryParse(rawCaptured)
      : null;
  if (label == null ||
      captured == null ||
      rawCaptured is! String ||
      !rawCaptured.endsWith('+09:00') ||
      int.parse(label[1]!) != int.parse(day.substring(5, 7)) ||
      int.parse(label[2]!) != int.parse(day.substring(8, 10))) {
    throw const FormatException('サイトセブンの採取日と営業日が不正です。');
  }
  final local = captured.toUtc().add(const Duration(hours: 9));
  final age = DateTime.utc(
    local.year,
    local.month,
    local.day,
  ).difference(DateTime.parse('${day}T00:00:00Z')).inDays;
  if (age < 0 || age > 9) throw const FormatException('サイトセブンの掲載期間が不正です。');
  final source = row['source_graph'], graph = row['graph'];
  if (source is! Map ||
      source['format'] != 'site777-yellow-pixels-v1' ||
      source['width'] != 260 ||
      source['height'] != 226 ||
      source['image_sha256'] is! String ||
      !RegExp(r'^[0-9a-f]{64}$').hasMatch(source['image_sha256'])) {
    throw const FormatException('サイトセブンの原画像の出典が不正です。');
  }
  if (graph == null &&
      ['zero_line_unknown', 'curve_unknown'].contains(source['error']))
    return;
  if (graph is! Map ||
      graph['kind'] != 'daily' ||
      graph['zero_y'] is! num ||
      !(graph['zero_y'] as num).isFinite ||
      graph['zero_y'] < 0 ||
      graph['zero_y'] > 226 ||
      graph['points'] is! List ||
      (graph['points'] as List).length < 2 ||
      (graph['points'] as List).length > 260 ||
      (graph['points'] as List).any(
        (p) =>
            p is! List ||
            p.length != 2 ||
            p.any((v) => v is! num || !v.isFinite) ||
            p[0] < 0 ||
            p[0] > 260 ||
            p[1] < 0 ||
            p[1] > 226,
      )) {
    throw const FormatException('サイトセブンの画像とグラフ座標が一致しません。');
  }
}

List<SlotRecord> pscubeViewerRecords(Map<dynamic, dynamic> data) {
  if (data['format'] != 'pscube-viewer' ||
      data['version'] != 1 ||
      data['machines'] is! List ||
      data['records'] is! List) {
    throw const FormatException('P’s CUBEの保存ファイルではありません。');
  }
  String machineKey(Map<dynamic, dynamic> m) =>
      '${m['store']}|${m['rate']}|${m['machine']}';
  final machines = <String, Map<dynamic, dynamic>>{};
  for (final item in data['machines'] as List) {
    if (item is! Map) throw const FormatException('機種情報が不正です。');
    if (item['store'] is! String ||
        !RegExp(r'^c\d+$').hasMatch(item['store']) ||
        item['rate'] is! String ||
        !RegExp(r'^\d+(?:\.\d+)?$').hasMatch(item['rate']) ||
        item['machine'] is! String ||
        (item['machine'] as String).trim().isEmpty ||
        ![null, 'normal', 'other'].contains(item['machine_type'])) {
      throw const FormatException('店舗・貸玉・機種タイプが不正です。');
    }
    if (machines.containsKey(machineKey(item)))
      throw const FormatException('機種が重複しています。');
    machines[machineKey(item)] = item;
  }
  final records = <SlotRecord>[];
  final seen = <String>{};
  for (final item in data['records'] as List) {
    if (item is! Map || !machines.containsKey(machineKey(item))) {
      throw const FormatException('台に対応する機種情報がありません。');
    }
    final m = machines[machineKey(item)]!;
    final name = normalizeMachineName(item['machine'] as String);
    // Preserve the existing exclusion chosen by the user.
    if (['沖ドキ', '沖ﾄﾞｷ', 'オキドキ', 'ｵｷﾄﾞｷ'].any(name.contains)) continue;
    final anaslo = item['source_site'] == 'anaslo';
    final site777 = item['source_site'] == 'site777';
    final external = anaslo || site777;
    if (anaslo) validateAnasloRecord(item);
    if (site777) validateSite777Record(item);
    for (final field
        in site777
            ? ['rack', 'games', 'bb', 'rb']
            : external
            ? ['rack', 'games', 'bb', 'rb', 'at_art']
            : ['rack', 'games', 'bb', 'rb', 'at_art', 'my']) {
      final value = item[field];
      if (value is! int || value < (field == 'rack' ? 1 : 0)) {
        throw FormatException('$field の数値が不正です。');
      }
    }
    if (item['net_medals'] != null &&
        (item['net_medals'] is! int ||
            (item['net_medals'] as int).abs() > 1000000)) {
      throw const FormatException('差枚の数値が不正です。');
    }
    final netEstimate = item['net_estimate'];
    if (netEstimate != null &&
        !validSupplementNetEstimate(item['source_site'], netEstimate)) {
      throw const FormatException('推定差枚の形式が不正です。');
    }
    final netCapture = validateNetCapture(item['net_capture'], record: item);
    final day = item['day'];
    if (day is! String || !isValidRecordDay(day))
      throw const FormatException('営業日が不正です。');
    final detail = Uri.tryParse(item['detail_url']?.toString() ?? '');
    if (!external &&
        (detail == null ||
            detail.origin != 'https://www.pscube.jp' ||
            !detail.path.endsWith('/${item['store']}/cgi-bin/nc-v06-001.php') ||
            detail.queryParameters['cd_dai'] != '${item['rack']}' ||
            detail.fragment != day.replaceAll('-', ''))) {
      throw const FormatException('台番号・営業日とリンクが一致しません。');
    }
    GraphMeasurement? graph;
    final rawGraph = item['graph'];
    if (rawGraph != null) {
      if (rawGraph is! Map ||
          !['daily', 'overview'].contains(rawGraph['kind']) ||
          rawGraph['zero_y'] is! num ||
          !(rawGraph['zero_y'] as num).isFinite ||
          rawGraph['points'] is! List)
        throw const FormatException('グラフが不正です。');
      final points = <List<double>>[];
      for (final p in rawGraph['points'] as List) {
        if (p is! List ||
            p.length != 2 ||
            p.any((v) => v is! num || !v.isFinite || v.abs() > 1e7)) {
          throw const FormatException('グラフ座標が不正です。');
        }
        points.add([(p[0] as num).toDouble(), (p[1] as num).toDouble()]);
      }
      if (points.length < 2 || points.length > 50000)
        throw const FormatException('グラフ座標がありません。');
      var peak = points.first, trough = points.first;
      for (var i = 0; i < points.length; i++) {
        final p = points[i];
        if (i > 0 && p[0] < points[i - 1][0])
          throw const FormatException('グラフの順序が不正です。');
        if (p[1] < peak[1]) peak = p;
        if (p[1] > trough[1]) trough = p;
      }
      graph = GraphMeasurement(
        baselineY: (rawGraph['zero_y'] as num).toDouble(),
        baselineX: points.first[0],
        peakY: peak[1],
        peakX: peak[0],
        troughY: trough[1],
        troughX: trough[0],
        endY: points.last[1],
        endX: points.last[0],
        curve: points,
      );
    }
    final record = SlotRecord(
      store: 'pscube:${item['store']}:${item['rate']}',
      day: day,
      machine: name,
      rack: item['rack'] as int,
      games: item['games'] as int,
      bb: item['bb'] as int,
      rb: item['rb'] as int,
      graph: graph,
      detailUrl: item['detail_url'] as String?,
      capturedAt: item['observed_at'] as String?,
      extra: {
        'source': 'pscube',
        if (external) 'source_site': item['source_site'],
        if (external) 'source_url': item['source_url'],
        if (external) 'source_machine': item['source_machine'],
        if (site777) 'source_sha256': item['source_sha256'],
        if (site777) 'source_day_label': item['source_day_label'],
        if (site777) 'source_captured_at': item['source_captured_at'],
        if (site777) 'source_graph': item['source_graph'],
        'source_store': item['store'],
        'rate': item['rate'],
        'my': item['my'],
        'net_medals': item['net_medals'],
        if (netEstimate != null) 'net_estimate': netEstimate,
        if (netCapture != null) 'net_capture': netCapture,
        'at_art': item['at_art'],
        'machine_type': m['machine_type'],
        'pscube_graph_kind': rawGraph is Map ? rawGraph['kind'] : null,
      },
    );
    if (!seen.add(record.key)) throw const FormatException('同じ台・営業日が重複しています。');
    records.add(record);
  }
  return records;
}
