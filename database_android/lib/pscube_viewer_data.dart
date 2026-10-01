import 'models.dart';

/// Convert at the input boundary so both data sites use the same viewer UI.
/// MY stays in extra['my']; it is never written to Meruhen's max_hold field.
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
    for (final field in ['rack', 'games', 'bb', 'rb', 'at_art', 'my']) {
      final value = item[field];
      if (value is! int || value < (field == 'rack' ? 1 : 0)) {
        throw FormatException('$field の数値が不正です。');
      }
    }
    final day = item['day'];
    if (day is! String || !isValidRecordDay(day))
      throw const FormatException('営業日が不正です。');
    final detail = Uri.tryParse(item['detail_url']?.toString() ?? '');
    if (detail == null ||
        detail.origin != 'https://www.pscube.jp' ||
        !detail.path.endsWith('/${item['store']}/cgi-bin/nc-v06-001.php') ||
        detail.queryParameters['cd_dai'] != '${item['rack']}' ||
        detail.fragment != day.replaceAll('-', '')) {
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
      detailUrl: item['detail_url'] as String,
      capturedAt: item['observed_at'] as String?,
      extra: {
        'source': 'pscube',
        'source_store': item['store'],
        'rate': item['rate'],
        'my': item['my'],
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
