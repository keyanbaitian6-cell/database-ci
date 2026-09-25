import 'dart:convert';
import 'dart:typed_data';

const storeNames = <String, String>{
  'nagamachiminami': 'メルヘンワールド長町南店',
  'saiwaichou': 'スーパーメルヘンワールド幸町',
};

/// 手入力で保存できる、根拠を確認済みの設定情報です。
/// 採点や設定推測の入力には使わず、記録の注記としてだけ扱います。
const confirmedSettingOptions = <String>['4以上', '5以上', '6'];

/// 機種名の表記ゆれ（`+` 区切り・連続した空白）をそろえる。
///
/// サイトやPC版の古い記録では空白が `+` になっていることがある。そろえずに
/// 比べると、同じ台が別の機種として二重に保存される。保存・読み込み・
/// バックアップの取り込みでは必ずこれを通す。
String normalizeMachineName(String value) =>
    value.replaceAll('+', ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

/// [time] as ISO 8601 with its UTC offset, e.g. `2026-09-26T23:05:12.345+09:00`.
///
/// `DateTime.toIso8601String()` leaves the offset out for local times, so a
/// later reader cannot tell which time zone the phone was in. New timestamps
/// kept for analysis use this form instead.
String timestampWithOffset(DateTime time) {
  final local = time.toLocal();
  final offset = local.timeZoneOffset;
  final sign = offset.isNegative ? '-' : '+';
  final minutes = offset.inMinutes.abs();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${local.toIso8601String()}$sign${two(minutes ~/ 60)}:${two(minutes % 60)}';
}

/// The earlier of two timestamps; an unreadable or missing one loses.
String? earliestTimestamp(String? a, String? b) {
  final ta = a == null ? null : DateTime.tryParse(a);
  final tb = b == null ? null : DateTime.tryParse(b);
  if (ta == null) return tb == null ? null : b;
  if (tb == null) return a;
  return tb.isBefore(ta) ? b : a;
}

/// DateTime.parse normalizes overflowing days; record keys must not do that.
bool isValidRecordDay(String? value) {
  if (value == null || !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(value)) {
    return false;
  }
  final parsed = DateTime.tryParse(value);
  return parsed != null && parsed.toIso8601String().substring(0, 10) == value;
}

class GraphMeasurement {
  const GraphMeasurement({
    required this.baselineY,
    required this.peakY,
    required this.troughY,
    required this.endY,
    this.baselineX,
    this.peakX,
    this.troughX,
    this.endX,
    this.previewPng,
    this.previewWidth,
    this.previewHeight,
    this.curve,
  });

  /// The exact SVG curve as [x, y] pairs (kept so new indicators can be
  /// computed later without re-capturing; only four points are scored today).
  final List<List<double>>? curve;

  final double baselineY;
  final double peakY;
  final double troughY;
  final double endY;
  final double? baselineX;
  final double? peakX;
  final double? troughX;
  final double? endX;
  final Uint8List? previewPng;
  final int? previewWidth;
  final int? previewHeight;

  factory GraphMeasurement.fromJson(Map<String, dynamic> json) =>
      GraphMeasurement(
        baselineY: (json['baseline_y'] as num).toDouble(),
        peakY: (json['peak_y'] as num).toDouble(),
        troughY: ((json['trough_y'] ?? json['end_y']) as num).toDouble(),
        endY: (json['end_y'] as num).toDouble(),
        baselineX: (json['baseline_x'] as num?)?.toDouble(),
        peakX: (json['peak_x'] as num?)?.toDouble(),
        troughX: (json['trough_x'] as num?)?.toDouble(),
        endX: (json['end_x'] as num?)?.toDouble(),
        previewPng: _decodePreview(json['preview_image']),
        previewWidth: (json['preview_width'] as num?)?.toInt(),
        previewHeight: (json['preview_height'] as num?)?.toInt(),
        curve: (json['curve'] as List?)
            ?.map((p) => (p as List).map((v) => (v as num).toDouble()).toList())
            .toList(),
      );

  Map<String, dynamic> toJson() => {
    'baseline_y': baselineY,
    'peak_y': peakY,
    'trough_y': troughY,
    'end_y': endY,
    if (baselineX != null) 'baseline_x': baselineX,
    if (peakX != null) 'peak_x': peakX,
    if (troughX != null) 'trough_x': troughX,
    if (endX != null) 'end_x': endX,
    if (previewPng != null) 'preview_image': base64Encode(previewPng!),
    if (previewWidth != null) 'preview_width': previewWidth,
    if (previewHeight != null) 'preview_height': previewHeight,
    if (curve != null) 'curve': curve,
    'method': 'android-four-point',
  };

  static Uint8List? _decodePreview(Object? value) {
    if (value is! String || value.isEmpty) return null;
    try {
      return Uint8List.fromList(base64Decode(value));
    } on FormatException {
      return null;
    }
  }
}

class SlotRecord {
  const SlotRecord({
    required this.store,
    required this.day,
    required this.machine,
    required this.rack,
    required this.games,
    required this.bb,
    required this.rb,
    this.maxHold,
    this.previousStart,
    this.graph,
    this.detailUrl,
    this.capturedAt,
    this.firstCapturedAt,
    this.confirmedSetting,
    this.extra = const {},
  });

  /// JSON の項目のうち、このアプリが知らないもの（新しい版やPC版が足した
  /// 項目）。読み書きの途中で落とさず、そのまま書き戻す。
  final Map<String, Object?> extra;

  /// このアプリが読み書きする項目。これ以外は [extra] に残す。
  static const knownKeys = {
    'store',
    'kind_code',
    'day',
    'machine',
    'rack',
    'games',
    'bb',
    'rb',
    'max_hold',
    'previous_start',
    'graph_measurement',
    'detail_url',
    'captured_at',
    'first_captured_at',
    'confirmed_setting',
  };

  final String store;
  final String day;
  final String machine;
  final int rack;
  final int games;
  final int bb;
  final int rb;
  // saiwaichou's own list page never shows a 最大持玉 column at all; it is
  // filled in later from the individual rack's graph page instead.
  final int? maxHold;
  final int? previousStart;
  final GraphMeasurement? graph;

  /// The site's own link to this rack's graph page, recorded verbatim from the
  /// list table so "次の未取り込み台へ" can follow it (never constructed).
  final String? detailUrl;

  /// When these numbers were captured (ISO 8601). Rack totals depend on how
  /// late in the day they were read, so this lets later analysis compare
  /// like with like. Null on data saved before this was recorded.
  final String? capturedAt;

  /// When this rack's record was first saved on any device (ISO 8601 with
  /// offset). Unlike [capturedAt] it never moves on a re-capture, so a later
  /// check can tell what was already known at a given time. Null on records
  /// saved before this was kept -- their first capture time is unknown.
  final String? firstCapturedAt;

  /// ユーザーが根拠を確認して入力した設定情報。未入力は null。
  final String? confirmedSetting;

  String get key => '$store|$day|$machine|$rack';

  SlotRecord copyWith({
    String? store,
    String? day,
    String? machine,
    int? rack,
    int? games,
    int? bb,
    int? rb,
    int? maxHold,
    int? previousStart,
    GraphMeasurement? graph,
    String? detailUrl,
    String? capturedAt,
    String? firstCapturedAt,
    String? confirmedSetting,
    bool clearConfirmedSetting = false,
    Map<String, Object?>? extra,
  }) => SlotRecord(
    store: store ?? this.store,
    day: day ?? this.day,
    machine: machine ?? this.machine,
    rack: rack ?? this.rack,
    games: games ?? this.games,
    bb: bb ?? this.bb,
    rb: rb ?? this.rb,
    maxHold: maxHold ?? this.maxHold,
    previousStart: previousStart ?? this.previousStart,
    graph: graph ?? this.graph,
    detailUrl: detailUrl ?? this.detailUrl,
    capturedAt: capturedAt ?? this.capturedAt,
    firstCapturedAt: firstCapturedAt ?? this.firstCapturedAt,
    confirmedSetting: clearConfirmedSetting
        ? null
        : confirmedSetting ?? this.confirmedSetting,
    extra: extra ?? this.extra,
  );

  factory SlotRecord.fromJson(Map<String, dynamic> json) => SlotRecord(
    store: (json['store'] ?? 'nagamachiminami') as String,
    day: json['day'] as String,
    machine: json['machine'] as String,
    rack: (json['rack'] as num).toInt(),
    games: ((json['games'] ?? 0) as num).toInt(),
    bb: ((json['bb'] ?? 0) as num).toInt(),
    rb: ((json['rb'] ?? 0) as num).toInt(),
    maxHold: (json['max_hold'] as num?)?.toInt(),
    previousStart: (json['previous_start'] as num?)?.toInt(),
    graph: json['graph_measurement'] is Map
        ? GraphMeasurement.fromJson(
            Map<String, dynamic>.from(json['graph_measurement'] as Map),
          )
        : null,
    detailUrl: json['detail_url'] as String?,
    capturedAt: json['captured_at'] as String?,
    firstCapturedAt: json['first_captured_at'] as String?,
    confirmedSetting:
        confirmedSettingOptions.contains(json['confirmed_setting'])
        ? json['confirmed_setting'] as String
        : null,
    extra: {
      for (final entry in json.entries)
        if (!knownKeys.contains(entry.key)) entry.key: entry.value,
    },
  );

  Map<String, dynamic> toJson() => {
    ...extra,
    'store': store,
    'kind_code': 21,
    'day': day,
    'machine': machine,
    'rack': rack,
    'games': games,
    'bb': bb,
    'rb': rb,
    if (maxHold != null) 'max_hold': maxHold,
    if (previousStart != null) 'previous_start': previousStart,
    if (graph != null) 'graph_measurement': graph!.toJson(),
    if (detailUrl != null) 'detail_url': detailUrl,
    if (capturedAt != null) 'captured_at': capturedAt,
    if (firstCapturedAt != null) 'first_captured_at': firstCapturedAt,
    if (confirmedSetting != null) 'confirmed_setting': confirmedSetting,
  };

  String encode() => jsonEncode(toJson());
}

class ScoreResult {
  const ScoreResult({
    this.games,
    this.maxHold,
    this.hits,
    this.positive,
    this.retention,
    this.total,
    required this.provisional,
    required this.referenceCount,
    required this.reasons,
    this.referenceDays = 0,
    this.holdReferenceCount = 0,
    this.coverage = 0,
    this.missingLow,
    this.missingHigh,
  });

  final double? games;
  final double? maxHold;
  final double? hits;
  final double? positive;
  final double? retention;
  final double? total;
  final bool provisional;
  final int referenceCount;
  final List<String> reasons;
  final int referenceDays;
  final int holdReferenceCount;
  final int coverage;
  final double? missingLow;
  final double? missingHigh;
}
