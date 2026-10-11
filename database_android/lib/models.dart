import 'dart:collection';
import 'dart:convert';
import 'dart:typed_data';

import 'meruhen_net.dart';

const storeNames = <String, String>{
  'nagamachiminami': 'メルヘンワールド長町南店',
  'saiwaichou': 'スーパーメルヘンワールド幸町',
};

/// Viewer scopes keep P's CUBE shops and rates apart from the original stores.
bool isPscubeStore(String value) =>
    RegExp(r'^pscube:c\d+:\d+(?:\.\d+)?$').hasMatch(value);

String signedMedals(int value) {
  final digits = value.abs().toString();
  final chunks = <String>[];
  for (var end = digits.length; end > 0; end -= 3) {
    chunks.add(digits.substring(end - 3 < 0 ? 0 : end - 3, end));
  }
  return '${value > 0
      ? '+'
      : value < 0
      ? '-'
      : ''}${chunks.reversed.join(',')}';
}

String storeDisplayName(String store) {
  if (isPscubeStore(store)) {
    final parts = store.split(':');
    return 'P’s CUBE（${parts[2]}スロ）';
  }
  return storeNames[store] ?? store;
}

Map<String, String> viewerStoreNames(Iterable<SlotRecord> records) {
  final scopes = records.map((r) => r.store).toSet();
  return {
    if (scopes.any((s) => !isPscubeStore(s))) ...storeNames,
    for (final scope in scopes)
      if (isPscubeStore(scope)) scope: storeDisplayName(scope),
  };
}

/// 手入力で保存できる、根拠を確認済みの設定情報です。
/// 採点や設定推測の入力には使わず、記録の注記としてだけ扱います。
const confirmedSettingOptions = <String>['4以上', '5以上', '6'];

/// 読み込む台の必須数値。未取得を0にせず、端数の台番号も切り捨てない。
bool hasValidRecordNumbers(Map<String, dynamic> raw) {
  bool integer(Object? value) =>
      value is num &&
      value.isFinite &&
      value >= 0 &&
      value == value.truncateToDouble();
  return integer(raw['rack']) &&
      (raw['rack'] as num) > 0 &&
      ['games', 'bb', 'rb'].every((key) => integer(raw[key])) &&
      [
        'max_hold',
        'previous_start',
      ].every((key) => raw[key] == null || integer(raw[key]));
}

/// 機種名の表記ゆれ（`+` 区切り・連続した空白）をそろえる。
///
/// サイトやPC版の古い記録では空白が `+` になっていることがある。そろえずに
/// 比べると、同じ台が別の機種として二重に保存される。保存・読み込み・
/// バックアップの取り込みでは必ずこれを通す。
String normalizeMachineName(String value) =>
    value.replaceAll('+', ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

/// サイトが点検中などの台に出す印（G数88888888・BB/RB 888・最大持玉88888888）や、
/// 1日ではあり得ない数値の台。採点・比較・翌日候補・設定推測・平均のどれにも
/// 使わない（PC版 core.py の implausible_numbers と同じ基準）。
bool hasImplausibleNumbers(SlotRecord record) =>
    record.games > 20000 ||
    record.bb > 500 ||
    record.rb > 500 ||
    (record.outputValue ?? 0) > 100000;

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
    this.storedPreview = false,
    this.storedCurve = false,
  });

  /// 画像・曲線はDBの別の列にだけ置き、画面用の一覧には読み込まない
  /// （記録が増えるとメモリに載り切らなくなるため）。これらは「別の列に
  /// ある」印で、[previewPng]・[curve] が null でも消えたわけではない。
  /// 必要な画面だけ `DatabaseService.loadPreview` で読む。
  final bool storedPreview;
  final bool storedCurve;

  /// 画像か曲線を別の列に残したまま、読み込んでいない。
  bool get detached =>
      (storedPreview && previewPng == null) || (storedCurve && curve == null);

  /// 保存時の画像がある（読み込み済みか、別の列にある）。
  bool get hasPreview => previewPng != null || storedPreview;

  /// 画面用の一覧に置く軽い形。画像と曲線を外し、別の列にある印だけ残す。
  GraphMeasurement lightened() => GraphMeasurement(
    baselineY: baselineY,
    peakY: peakY,
    troughY: troughY,
    endY: endY,
    baselineX: baselineX,
    peakX: peakX,
    troughX: troughX,
    endX: endX,
    previewWidth: previewWidth,
    previewHeight: previewHeight,
    storedPreview: hasPreview,
    storedCurve: curve != null || storedCurve,
  );

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
        curve: switch (json['curve'] as List?) {
          final List raw => SavedCurve(raw),
          null => null,
        },
        storedPreview: json['preview_stored'] == true,
        storedCurve: json['curve_stored'] == true,
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
    if (storedPreview && previewPng == null) 'preview_stored': true,
    if (storedCurve && curve == null) 'curve_stored': true,
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

/// JSONから読んだグラフの線（[x, y] の組）。数値の一覧へ直すのは、線を描く
/// など初めて中身を使うときに1回だけ（直し方は以前の読み込み時と同じなので、
/// 描く線は変わらない）。閲覧ページは起動のたびに8,000台以上の線を読むが、
/// 描くのは表示する台だけなので、全部を先に直すと時間と電池を使う。
/// 形は読み込みの時点で確かめ、壊れた線は今までどおりそこで失敗させる。
class SavedCurve extends ListBase<List<double>> {
  SavedCurve(List raw) : _raw = raw {
    for (final point in raw) {
      for (final value in point as List) {
        value as num;
      }
    }
  }

  List? _raw;
  late final List<List<double>> _points = () {
    final raw = _raw!;
    _raw = null;
    return raw
        .map((p) => (p as List).map((v) => (v as num).toDouble()).toList())
        .toList();
  }();

  /// 数値の一覧へ直し済みか（テスト用）。
  bool get converted => _raw == null;

  @override
  int get length => _points.length;

  @override
  set length(int value) => _points.length = value;

  @override
  List<double> operator [](int index) => _points[index];

  @override
  void operator []=(int index, List<double> value) => _points[index] = value;
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
  bool get isPscube => extra['source'] == 'pscube' && isPscubeStore(store);
  int? get my => isPscube ? (extra['my'] as num?)?.toInt() : null;
  int? get netMedals =>
      isPscube ? (extra['net_medals'] as num?)?.toInt() : null;

  /// メルヘンの推定差枚（グラフと最大持玉から計算、`meruhen_net.dart`）。確定差枚ではない。
  int? get estimatedNetMedals => _meruhenNet?.value;

  /// ジャグラーオンラインから取り込んだ差枚（お試し、2026-10-09〜。`JUGGLER_ONLINE.md`）。
  /// あれば推定差枚より優先する（利用者「差枚はこっちを優先」）。
  int? get joNet => isPscube ? null : (extra['jo_net'] as num?)?.toInt();

  /// 推定差枚に「※」（要確認）を付けるか。グラフだけでは縦軸の目盛りを決めきれず、
  /// 1回転あたりの使用枚数で選び直した台（`meruhenNetEstimateDetail`）。
  /// ジャグラーオンラインの差枚を使うときは付けない。
  bool get netNeedsCheck => joNet == null && (_meruhenNet?.needsCheck ?? false);

  ({int? value, bool needsCheck})? get _meruhenNet {
    final g = graph;
    if (isPscube || g == null) return null;
    return meruhenNetEstimateDetail(
      baselineY: g.baselineY,
      peakY: g.peakY,
      troughY: g.troughY,
      endY: g.endY,
      peakX: g.peakX,
      troughX: g.troughX,
      endX: g.endX,
      curve: g.curve,
      maxHold: maxHold,
      games: games,
    );
  }

  /// 画面に出す差枚：P’s CUBEは元グラフの確定差枚、メルヘンはジャグラーオンラインの差枚、
  /// 無ければ推定差枚。
  int? get netValue => isPscube ? netMedals : (joNet ?? estimatedNetMedals);

  /// 画面に出す差枚の文字（符号つき）。要確認の推定差枚には「※」を付ける。
  String? get netText => netValue == null
      ? null
      : '${signedMedals(netValue!)}${netNeedsCheck ? '※' : ''}';

  /// [netValue] の呼び方。メルヘンは推定であることを必ず添える。
  String get netLabel => isPscube || joNet != null ? '差枚' : '推定差枚';
  int get atArt => isPscube ? (extra['at_art'] as num?)?.toInt() ?? 0 : 0;
  int? get outputValue => isPscube ? my : maxHold;
  String get outputLabel => isPscube ? 'MY' : '最大持玉';
  bool get pscubeNormal {
    if (extra['machine_type'] == 'normal') return true;
    if (extra['machine_type'] == 'other') return false;
    return ['ジャグラー', 'ｼﾞｬｸﾞﾗｰ', 'ハナハナ', 'ﾊﾅﾊﾅ'].any(machine.contains);
  }

  bool get pscubeOutputProfile => isPscube && !pscubeNormal;
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

  /// 表の大当たり（BB+RB）が0回。グラフは取らない（利用者の指定、2026-09-29。
  /// 実データの0回550台で、終点がプラスだったのは24Gの1台だけ）。表を取り
  /// 込み直して当たりが付けば、また取る対象に戻る。PC版 `graph_not_needed`。
  bool get graphNotNeeded => graph == null && bb + rb + atArt == 0;

  /// グラフが済んでいる（取り込み済み、または大当たり0回で不要）。
  bool get graphDone => graph != null || bb + rb + atArt == 0;

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

  /// 画面用の一覧に置く軽い形（グラフの画像と曲線を外す）。
  SlotRecord lightened() => graph == null || graph!.detached
      ? this
      : copyWith(graph: graph!.lightened());
}

/// 確定が出た台の印🌈（PCで付ける。RAINBOW.md）。このアプリの知らない項目として [SlotRecord.extra] に
/// そのまま入っている（読み書きで落とさない）。
const rainbowMark = '🌈';

extension SlotRecordRainbow on SlotRecord {
  bool get rainbow => extra['rainbow'] == true;
}

/// 最終🌈：同じ店舗・同じ台番号で、[day] 以前に最後に🌈が付いた日（無ければ null）。
/// 台番号で見る（機種が入れ替わっても同じ台番号なら続けて数える。PC版 `last_rainbow_days` と同じ）。
String? lastRainbowDay(
  Iterable<SlotRecord> all,
  String store,
  int rack,
  String day,
) {
  String? last;
  for (final r in all) {
    if (r.store == store &&
        r.rack == rack &&
        r.rainbow &&
        r.day.compareTo(day) <= 0 &&
        (last == null || r.day.compareTo(last) > 0)) {
      last = r.day;
    }
  }
  return last;
}

/// 最終🌈の表示：その日なら「当日」、前の日なら「9/26（15日前）」、無ければ「なし」。PC版 `last_rainbow_text` と同じ。
String lastRainbowText(String? last, String day) {
  if (last == null) return 'なし';
  if (last == day) return '当日';
  final days = DateTime.parse('${day}T00:00:00Z')
      .difference(DateTime.parse('${last}T00:00:00Z'))
      .inDays;
  return '${int.parse(last.substring(5, 7))}/${int.parse(last.substring(8, 10))}（$days日前）';
}

/// 同じ台（同じ店舗・日付・機種・台番号）の2件を1件にまとめる。
///
/// 回転数の多い方を新しい数値とし（同じなら [b]）、片方にしかない
/// グラフ・リンク・設定情報は残す。初回取り込み時刻は早い方。機種名の
/// 表記ゆれを揃えるとき、画面用の一覧とDBの両方で同じ規則を使う。
SlotRecord mergeSameRack(SlotRecord a, SlotRecord b) {
  final newest = b.games >= a.games ? b : a;
  final older = identical(newest, b) ? a : b;
  return SlotRecord(
    store: newest.store,
    day: newest.day,
    machine: normalizeMachineName(newest.machine),
    rack: newest.rack,
    games: newest.games,
    bb: newest.bb,
    rb: newest.rb,
    maxHold: newest.maxHold,
    previousStart: newest.previousStart ?? older.previousStart,
    graph: b.graph ?? a.graph,
    detailUrl: newest.detailUrl ?? older.detailUrl,
    capturedAt: newest.capturedAt ?? older.capturedAt,
    firstCapturedAt: earliestTimestamp(a.firstCapturedAt, b.firstCapturedAt),
    confirmedSetting: newest.confirmedSetting ?? older.confirmedSetting,
    extra: {...older.extra, ...newest.extra},
  );
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
