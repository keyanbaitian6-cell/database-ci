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
String setRainbowMark(String text, SlotRecord record, bool on, DateTime now) =>
    updateRainbowMark(text, record, on, now).text;

/// [setRainbowMark] と同じ変更で、付け外しした印 [mark] と全部の印 [marks] も返す。
/// 閲覧ページの保存では、表示中のデータへこの印だけを当て、共有へ送る中身も [marks] から作る。
/// 端末の内容をもう一度まるごと読み直さない（iPhoneで🌈を付けると落ちた、2026-10-29）。
///
/// 端末の内容は数十MBあり、まるごと読むと一時的に数百MBを使う。印は最上位の `rainbow_marks` に
/// しか無いので、その値の部分だけを読んで差し替える（並び・ほかの中身は変えない）。最上位の形が
/// 読めないときだけ、従来どおりまるごと読む。
({String text, RainbowMark mark, Map<String, RainbowMark> marks})
updateRainbowMark(String text, SlotRecord record, bool on, DateTime now) {
  final span = topLevelJsonValue(text, 'rainbow_marks');
  final Map<String, dynamic>? decoded;
  final Map<String, RainbowMark> marks;
  if (span == null) {
    decoded = Map<String, dynamic>.from(jsonDecode(text) as Map);
    marks = rainbowMarksOf(decoded);
  } else {
    decoded = null;
    marks = span.start < 0
        ? <String, RainbowMark>{}
        : rainbowMarksOf({
            'rainbow_marks': jsonDecode(text.substring(span.start, span.end)),
          });
  }
  final mark = nextRainbowMark(marks, record, on, now);
  marks[mark.key] = mark;
  final value = jsonEncode(_json(marks));
  final String updated;
  if (decoded != null) {
    updated = jsonEncode({...decoded, 'rainbow_marks': _json(marks)});
  } else if (span!.start >= 0) {
    updated = text.substring(0, span.start) + value + text.substring(span.end);
  } else {
    // 無ければ最後に足す（まるごと読んで足したときと同じ並び）。
    updated =
        '${text.substring(0, span.end)}${span.empty ? '' : ','}'
        '"rainbow_marks":$value${text.substring(span.end)}';
  }
  return (text: updated, mark: mark, marks: marks);
}

/// 最上位のオブジェクトで [key] の値がある位置。無ければ start が -1 で、end は閉じ括弧の位置
/// （empty は中身が無いか）。次のときは null を返し、呼び出し側はまるごと読む（従来どおり）：
/// 最上位がオブジェクトとして読めない、[key] が最上位に2つ以上ある（まるごと読むと後の方が使われる。
/// 2026-10-29 Codexのレビュー）、最上位の値に数・true・false・null 以外の裸の語がある（`"tail":BROKEN`）、
/// 括弧の種類が合わない。入れ子の中身までは検査しない（全体の妥当性検査ではない）。
({int start, int end, bool empty})? topLevelJsonValue(String text, String key) {
  const quote = 0x22, backslash = 0x5c, colon = 0x3a, comma = 0x2c;
  const openBrace = 0x7b, closeBrace = 0x7d, openBracket = 0x5b;
  const closeBracket = 0x5d;
  final literal = RegExp(
    r'^(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)$',
  );
  final n = text.length;
  int space(int i) {
    while (i < n) {
      final c = text.codeUnitAt(i);
      if (c != 0x20 && c != 0x0a && c != 0x0d && c != 0x09) break;
      i++;
    }
    return i;
  }

  // 文字列の終わりの次の位置。
  int string(int i) {
    for (i++; i < n; i++) {
      final c = text.codeUnitAt(i);
      if (c == backslash) {
        i++;
      } else if (c == quote) {
        return i + 1;
      }
    }
    return -1;
  }

  // 値の終わりの次の位置（読めなければ -1）。
  int skipValue(int i) {
    if (i >= n) return -1;
    final first = text.codeUnitAt(i);
    if (first == quote) return string(i);
    if (first != openBrace && first != openBracket) {
      final from = i;
      while (i < n) {
        final c = text.codeUnitAt(i);
        if (c == comma || c == closeBrace || c == closeBracket) break;
        i++;
      }
      return literal.hasMatch(text.substring(from, i).trimRight()) ? i : -1;
    }
    final closers = <int>[];
    while (i < n) {
      final c = text.codeUnitAt(i);
      if (c == quote) {
        i = string(i);
        if (i < 0) return -1;
        continue;
      }
      if (c == openBrace) closers.add(closeBrace);
      if (c == openBracket) closers.add(closeBracket);
      if (c == closeBrace || c == closeBracket) {
        if (closers.isEmpty || closers.removeLast() != c) return -1;
        if (closers.isEmpty) return i + 1;
      }
      i++;
    }
    return -1;
  }

  var i = space(0);
  if (i >= n || text.codeUnitAt(i) != openBrace) return null;
  i = space(i + 1);
  var members = 0;
  ({int start, int end})? found;
  while (i < n) {
    if (text.codeUnitAt(i) == closeBrace) {
      if (members > 0 && text.codeUnitAt(i - 1) == comma) return null;
      if (space(i + 1) != n) return null;
      return found == null
          ? (start: -1, end: i, empty: members == 0)
          : (start: found.start, end: found.end, empty: false);
    }
    if (text.codeUnitAt(i) != quote) return null;
    final keyEnd = string(i);
    if (keyEnd < 0) return null;
    final name = jsonDecode(text.substring(i, keyEnd));
    i = space(keyEnd);
    if (i >= n || text.codeUnitAt(i) != colon) return null;
    final start = space(i + 1);
    final end = skipValue(start);
    if (end < 0) return null;
    if (name == key) {
      if (found != null) return null; // 同じ名前が2つ：まるごと読む
      found = (start: start, end: end);
    }
    members++;
    i = space(end);
    if (i < n && text.codeUnitAt(i) == comma) {
      i = space(i + 1);
      if (i < n && text.codeUnitAt(i) == closeBrace) return null;
    } else if (i >= n || text.codeUnitAt(i) != closeBrace) {
      return null;
    }
  }
  return null;
}

/// [record] の🌈を付ける・外す印。時刻は今で、[marks] の同じ台・日の印と記録の rainbow_at
/// （PCの時刻）より必ず後にする。
RainbowMark nextRainbowMark(
  Map<String, RainbowMark> marks,
  SlotRecord record,
  bool on,
  DateTime now,
) {
  final key = '${record.store}|${record.day}|${record.rack}';
  return RainbowMark(
    store: record.store,
    day: record.day,
    rack: record.rack,
    on: on,
    updatedAt: eventStamp(
      now,
      _later(marks[key]?.updatedAt, record.extra['rainbow_at'] as String?),
    ),
  );
}

/// 本体と別に置く印の文字（JSONの配列。閲覧ページの 'rainbow_marks'、2026-10-29）。
String rainbowMarksText(Map<String, RainbowMark> marks) =>
    jsonEncode(_json(marks));

/// [rainbowMarksText] の文字から印を読む。無い・読めない値は飛ばす。配列でなければ例外。
Map<String, RainbowMark> rainbowMarksFromText(String? text) =>
    text == null ? {} : rainbowMarksOf({'rainbow_marks': jsonDecode(text)});

/// 共有ファイル（`{format: database-rainbow, marks}`）の印。形が違えば null。
Map<String, RainbowMark>? sharedRainbowMarks(String shared) {
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
  return rainbowMarksOf({'rainbow_marks': doc['marks']});
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
String sharedRainbowBody(String text) =>
    sharedRainbowBodyOf(rainbowMarksOf(jsonDecode(text) as Map));

/// [sharedRainbowBody] と同じ中身を、読み取り済みの印から作る。
String sharedRainbowBodyOf(Map<String, RainbowMark> marks) =>
    jsonEncode({'file': 'rainbow', 'marks': _json(marks)});

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
