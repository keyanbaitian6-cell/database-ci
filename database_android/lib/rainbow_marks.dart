/// 閲覧ページ（iPhone）で付け外しした確定の印🌈（2026-10-11、RAINBOW.md「iPhoneから付ける」）。
///
/// 端末の内容（閲覧ページが保存しているJSON）の `rainbow_marks` に、付け外しした時刻つきで持つ。
/// 送り先は Apps Script（tool/viewer_drive_script.gs の `?file=rainbow`）で、PC版は同期フォルダに届いた
/// 共有ファイルを読んで記録に取り込む（core.pull_shared_rainbow）。台の記録の `rainbow_at`（PCで付け外し
/// した時刻）と比べて、新しい方を表示に使う。PC版と同じ規則。
library;

import 'dart:convert';

import 'date_events.dart' show eventStamp, eventTime;
import 'models.dart';

class RainbowMark {
  const RainbowMark({
    required this.store,
    required this.day,
    required this.rack,
    required this.on,
    required this.updatedAt,
  });
  final String store, day, updatedAt;
  final int rack;
  final bool on;

  String get key => '$store|$day|$rack';

  Map<String, Object> toJson() => {
    'store': store,
    'day': day,
    'rack': rack,
    'on': on,
    'updated_at': updatedAt,
  };

  static RainbowMark? tryFromJson(Object? raw) {
    if (raw is! Map) return null;
    final store = raw['store'], day = raw['day'], rack = raw['rack'];
    final on = raw['on'], at = raw['updated_at'];
    if (store is! String ||
        !storeNames.containsKey(store) ||
        day is! String ||
        !isValidRecordDay(day) ||
        rack is! int ||
        rack < 1 ||
        on is! bool ||
        at is! String ||
        eventTime(at) == null) {
      return null;
    }
    return RainbowMark(
      store: store,
      day: day,
      rack: rack,
      on: on,
      updatedAt: at,
    );
  }
}

/// 端末の内容 [decoded] の🌈（キーごと）。
Map<String, RainbowMark> rainbowMarksOf(Map decoded) => {
  for (final raw in (decoded['rainbow_marks'] as List?) ?? const [])
    if (RainbowMark.tryFromJson(raw) case final mark?) mark.key: mark,
};

/// [incoming] を [into] に足す（同じ台・日は付け外しした時刻の新しい方、同じなら [incoming]）。変わった数も返す。
({Map<String, RainbowMark> marks, int changed}) mergeRainbowMarks(
  Map<String, RainbowMark> into,
  Iterable<RainbowMark> incoming,
) {
  final marks = {...into};
  var changed = 0;
  for (final mark in incoming) {
    final old = marks[mark.key];
    if (old != null) {
      if (eventTime(mark.updatedAt)!.isBefore(eventTime(old.updatedAt)!)) {
        continue;
      }
      if (old.on == mark.on && old.updatedAt == mark.updatedAt) continue;
    }
    marks[mark.key] = mark;
    changed++;
  }
  return (marks: marks, changed: changed);
}

List<Map<String, Object>> _json(Map<String, RainbowMark> marks) => [
  for (final key in marks.keys.toList()..sort()) marks[key]!.toJson(),
];

/// 端末の内容 [text] で、[record] の🌈を付ける・外す（付け外しした時刻を今に）。
String setRainbowMark(String text, SlotRecord record, bool on, DateTime now) {
  final decoded = Map<String, dynamic>.from(jsonDecode(text) as Map);
  final marks = rainbowMarksOf(decoded);
  final key = '${record.store}|${record.day}|${record.rack}';
  marks[key] = RainbowMark(
    store: record.store,
    day: record.day,
    rack: record.rack,
    on: on,
    // 記録の rainbow_at（PCの時刻）・前の印より必ず後にする。
    updatedAt: eventStamp(
      now,
      _later(marks[key]?.updatedAt, record.extra['rainbow_at'] as String?),
    ),
  );
  return jsonEncode({...decoded, 'rainbow_marks': _json(marks)});
}

String? _later(String? a, String? b) {
  final x = eventTime(a), y = eventTime(b);
  if (x == null) return y == null ? null : b;
  if (y == null) return a;
  return x.isAfter(y) ? a : b;
}

/// [from]（前に保存していた端末の内容など）の🌈を [into] に足す。変わらなければ [into] をそのまま返す。
String keepRainbowMarks(String? from, String into) {
  if (from == null) return into;
  Map? source, target;
  try {
    source = jsonDecode(from) as Map?;
    target = jsonDecode(into) as Map?;
  } on Object {
    return into;
  }
  if (source == null || target == null) return into;
  final merged = mergeRainbowMarks(
    rainbowMarksOf(target),
    rainbowMarksOf(source).values,
  );
  if (merged.changed == 0) return into;
  return jsonEncode({
    ...Map<String, dynamic>.from(target),
    'rainbow_marks': _json(merged.marks),
  });
}

/// 共有ファイル [shared]（`{format: database-rainbow, marks}`）の🌈を端末の内容 [stored] に足す。
/// 変わらなければ・読めなければ null。
String? withSharedRainbow(String stored, String shared) {
  Object? doc;
  try {
    doc = jsonDecode(shared);
  } on FormatException {
    return null;
  }
  if (doc is! Map ||
      doc['format'] != 'database-rainbow' ||
      doc['marks'] is! List) {
    return null;
  }
  final merged = keepRainbowMarks(
    jsonEncode({'rainbow_marks': doc['marks']}),
    stored,
  );
  return identical(merged, stored) ? null : merged;
}

/// スクリプトへ送る中身：この端末の🌈（全部。前に送れなかった分も届く）。
String sharedRainbowBody(String text) => jsonEncode({
  'file': 'rainbow',
  'marks': _json(rainbowMarksOf(jsonDecode(text) as Map)),
});

/// スクリプトの返事を、利用者への知らせにする。送れたら ok が true。古いスクリプト（🌈を足す前）は
/// 「指定できないファイルです」と返すので、スクリプトの更新を案内する。
({bool ok, String message}) rainbowSendResult(String response) {
  try {
    final doc = jsonDecode(response);
    if (doc is Map && doc['ok'] == true) return (ok: true, message: '');
    if (doc is Map && doc['error'] is String) {
      final error = doc['error'] as String;
      return (
        ok: false,
        message: error.contains('指定できない')
            ? 'スクリプトが🌈に対応していません。Apps Scriptを新しい版に更新してください（RAINBOW.md）'
            : error,
      );
    }
  } on FormatException {
    // 下の知らせ
  }
  return (ok: false, message: 'スクリプトの返事が読めません。');
}

/// 端末の🌈を台の記録に反映する（記録の rainbow_at より新しい印だけ）。
List<SlotRecord> applyRainbowMarks(
  List<SlotRecord> records,
  Map<String, RainbowMark> marks,
) {
  if (marks.isEmpty) return records;
  return [
    for (final r in records)
      if (marks['${r.store}|${r.day}|${r.rack}'] case final mark?
          when _newer(mark.updatedAt, r.extra['rainbow_at'] as String?))
        r.copyWith(
          extra: {
            ...Map<String, Object?>.from(r.extra)..remove('rainbow'),
            if (mark.on) 'rainbow': true,
            'rainbow_at': mark.updatedAt,
          },
        )
      else
        r,
  ];
}

bool _newer(String mark, String? record) {
  final at = eventTime(record);
  return at == null || eventTime(mark)!.isAfter(at);
}
