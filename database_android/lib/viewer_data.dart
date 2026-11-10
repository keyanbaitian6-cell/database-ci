import 'excluded_machines.dart';

import 'dart:convert';

import 'date_events.dart';
import 'models.dart';
import 'pscube_viewer_data.dart';
import 'capture_health.dart';
import 'rainbow_marks.dart';
import 'scoring.dart';

/// 閲覧ページで読んだバックアップ（画像を除いた軽い形）。
///
/// ページ内のJavaScript（web/index.html）が1行ずつ読んで作ったJSONを受け取り、
/// Android版と同じ規則（機種名の表記ゆれをそろえ、同じ台は1件にまとめる）で
/// 台の一覧にする。採点・翌日候補は、Android版と同じ関数でその場で計算する。
/// 当時の翌日候補の1台（[ViewerData.answerCandidates]）。
typedef SavedCandidate = ({int rack, double index, bool variety});

// データの版ごとに表示用の採点だけを共有する。候補の除外条件は画面ごとに保持する。
final _displayScores = Expando<Map<SlotRecord, ScoreResult>>(
  'viewerDisplayScores',
);

class ViewerData {
  const ViewerData({
    required this.records,
    this.dateEvents = const {},
    this.eventNames = const {},
    this.rainbowMarks = const {},
    this.file,
    this.exportedAt,
    this.exportedAtText,
    this.source,
    this.loadedAt,
    this.skipped = 0,
    this.keptOlder = 0,
    this.syncStatus,
    this.curveParts = const [],
    this.answerCandidates = const {},
  });

  /// 当時の翌日候補（{"店|日": [(台番号, 平均より, バラエティか)]}）。PCが閲覧用ファイルに載せる
  /// （core.py `saved_answer_candidates`、2026-11-04）。答え合わせで、計算し直した候補の代わりに使う。
  final Map<String, List<SavedCandidate>> answerCandidates;

  /// メルヘンのグラフの線パーツの参照（日付・ハッシュ・件数・大きさ）。台の画面を開いたときに
  /// その日の分だけ読む（remote_curve.dart、2026-10-25）。
  final List<Map<String, Object?>> curveParts;

  final List<SlotRecord> records;

  /// 同じ版・同じ記録の表示用採点。日付を巡っても保持は最大1024台まで。
  /// 新しいViewerDataや訂正された別の記録には、古い結果を流用しない。
  ScoreResult displayScore(SlotRecord record) {
    final cache = _displayScores[this] ??= <SlotRecord, ScoreResult>{};
    final cached = cache.remove(record);
    final result = cached ?? scoreRecord(record, records, sameDayForNew: true);
    cache[record] = result;
    if (cache.length > 1024) cache.remove(cache.keys.first);
    return result;
  }

  /// 未取り込み日の印も、数値の記録と別に保持する。
  final Map<String, RainbowMark> rainbowMarks;
  final Map<String, DateEvent> dateEvents;

  /// P’s CUBEの店舗（`pscube:店:貸玉`）ごとの、今までに付けたイベント名（新しく使った順）。
  /// イベント名の入力欄のプルダウンに使う。
  final Map<String, List<String>> eventNames;
  final String? file;
  final Map<String, dynamic>? syncStatus;
  final DateTime? exportedAt;

  /// 書き出した時刻の、ファイルに書かれていたままの文字。Driveの自動読み込みで
  /// 「前回と同じファイルか」を見分けるのに使う（時刻に直すと表記が変わるため）。
  final String? exportedAtText;
  final String? source;
  final DateTime? loadedAt;

  /// 形が合わず読み飛ばした台の数。
  final int skipped;

  /// Driveの内容に合わせて残した、前に読み込んだ古い日の台の数（[merge]）。
  final int keptOlder;

  static ViewerData parse(String text) => _parseDocument(jsonDecode(text));

  /// 端末に保存した🌈の印 [marks]（全部）を当てた内容。端末の内容を読み直した [parse] と同じ表示に
  /// なる（同じ [applyRainbowMarks] の規則。当て済みの印は記録の rainbow_at と同じ時刻なので変わらない）。
  /// 読み直すと、iPhoneでは一時的なメモリが足りず落ちた（2026-10-29）。
  ViewerData withRainbowMarks(Map<String, RainbowMark> marks) => ViewerData(
    records: applyRainbowMarks(records, marks),
    rainbowMarks: marks,
    dateEvents: dateEvents,
    eventNames: eventNames,
    file: file,
    exportedAt: exportedAt,
    exportedAtText: exportedAtText,
    source: source,
    loadedAt: loadedAt,
    skipped: skipped,
    keptOlder: keptOlder,
    syncStatus: syncStatus,
    curveParts: curveParts,
    answerCandidates: answerCandidates,
  );

  static ViewerData _parseDocument(Object? decoded) {
    if (decoded is! Map || decoded['records'] is! List) {
      throw const FormatException('databaseのバックアップファイルではありません。');
    }
    final header = decoded['header'] is Map ? decoded['header'] as Map : {};
    final merged = <String, SlotRecord>{};
    final dateEvents = <String, DateEvent>{};
    final rawEvents = decoded['date_events'];
    if (rawEvents is List) {
      for (final item in rawEvents) {
        final event = DateEvent.tryFromJson(item);
        if (event != null) dateEvents[event.key] = event;
      }
    }
    var skipped = 0;
    final pscube = decoded['format'] == 'pscube-viewer';
    final eventNames = <String, List<String>>{};
    if (pscube) {
      final events = pscubeDateEvents(decoded);
      for (final event in events) {
        if (event.name != null) {
          dateEvents[event.event.key] = event.event;
        }
      }
      for (final entry in pscubeEventNames(events).entries) {
        eventNames[entry.key] = entry.value;
      }
    }
    final incoming = pscube
        ? pscubeViewerRecords(decoded)
        : decoded['records'] as List;
    for (final item in incoming) {
      final record = item is SlotRecord ? item : _record(item);
      if (record == null) {
        skipped++;
        continue;
      }
      // 対象外の機種（稼働停止の台など）は、古い閲覧用ファイルに残っていても出さない。
      if (isHiddenMachine(record.store, record.machine)) continue;
      final current = merged[record.key];
      merged[record.key] = current == null
          ? record
          : mergeSameRack(current, record);
    }
    // 閲覧ページで付け外しした🌈（RAINBOW.md）は、記録の rainbow_at より新しいものだけ表示に使う。
    final records =
        (pscube
              ? merged.values.toList()
              : applyRainbowMarks(
                  merged.values.toList(),
                  rainbowMarksOf(decoded),
                ))
          ..sort((a, b) {
            final day = b.day.compareTo(a.day);
            if (day != 0) return day;
            final store = a.store.compareTo(b.store);
            if (store != 0) return store;
            final machine = a.machine.compareTo(b.machine);
            return machine != 0 ? machine : a.rack.compareTo(b.rack);
          });
    return ViewerData(
      records: records,
      rainbowMarks: pscube ? const {} : rainbowMarksOf(decoded),
      dateEvents: dateEvents,
      eventNames: eventNames,
      file: decoded['file'] as String?,
      exportedAt: DateTime.tryParse(header['exported_at'] as String? ?? '')
          ?.toLocal(),
      exportedAtText: header['exported_at'] is String
          ? header['exported_at'] as String
          : null,
      source: pscube ? 'pscube' : header['source'] as String?,
      loadedAt: DateTime.tryParse(decoded['loaded_at'] as String? ?? '')
          ?.toLocal(),
      skipped: skipped,
      keptOlder: (decoded['kept_older'] as num?)?.toInt() ?? 0,
      syncStatus: validateSyncStatus(
        decoded['sync_status'] ?? header['sync_status'],
      ),
      curveParts: pscube ? const [] : _curveParts(header['curve_parts']),
      answerCandidates: pscube
          ? const {}
          : _answerCandidates(
              decoded['answer_candidates'] ?? header['answer_candidates'],
            ),
    );
  }

  /// 形の合わない店・日・台は読み飛ばす（その日は計算し直した候補で答え合わせする）。
  static Map<String, List<SavedCandidate>> _answerCandidates(Object? raw) => {
    if (raw is Map)
      for (final entry in raw.entries)
        if (entry.key is String && entry.value is List)
          entry.key as String: [
            for (final c in entry.value as List)
              if (c is List &&
                  c.length == 3 &&
                  c[0] is int &&
                  c[1] is num &&
                  (c[2] == 0 || c[2] == 1))
                (
                  rack: c[0] as int,
                  index: (c[1] as num).toDouble(),
                  variety: c[2] == 1,
                ),
          ],
  };

  static List<Map<String, Object?>> _curveParts(Object? raw) => [
    if (raw is List)
      for (final c in raw)
        if (c is Map &&
            c['day'] is String &&
            c['hash'] is String &&
            c['count'] is int &&
            c['bytes'] is int)
          {
            'day': c['day'],
            'hash': c['hash'],
            'count': c['count'],
            'bytes': c['bytes'],
          },
  ];

  /// 画面に出すイベント（「イベントを消した」印は出さない）。
  DateEvent? dateEventFor(String store, String day) {
    final event = dateEvents['$store|$day'];
    return event == null || event.removed ? null : event;
  }

  /// [other]（端末に覚えていた内容など）のイベントを、[text] に統合する
  /// （`EVENT_CALENDAR.md`。入力時刻の新しい方が残り、消した印も同じ）。
  /// [other] の時刻の無いイベントは、[text] の記録より前の日の分だけ引き継ぐ
  /// （それ以降で [text] に無いものは、PC版で外したもの）。P’s CUBEは対象外。
  static String withOtherEvents(
    String? other,
    String text, {
    bool timedOnly = false,
  }) {
    Map<String, dynamic>? decode(String? value) {
      if (value == null) return null;
      try {
        final decoded = jsonDecode(value);
        return decoded is Map && decoded['format'] != 'pscube-viewer'
            ? Map<String, dynamic>.from(decoded)
            : null;
      } on FormatException {
        return null;
      }
    }

    final from = decode(other);
    final into = decode(text);
    if (from == null || into == null) return text;
    final result = _withEvents(
      into,
      _events(from).values,
      timedOnly: timedOnly,
    );
    return identical(result, into) ? text : jsonEncode(result);
  }

  static Map<String, dynamic> _withEvents(
    Map<String, dynamic> into,
    Iterable<DateEvent> incoming, {
    bool timedOnly = false,
  }) {
    String? first;
    if (into['records'] case final List records) {
      for (final item in records) {
        final day = item is Map ? item['day'] : null;
        if (day is String && (first == null || day.compareTo(first) < 0)) {
          first = day;
        }
      }
    }
    final kept = incoming.where(
      (event) =>
          event.updatedAt != null ||
          (!timedOnly && (first == null || event.day.compareTo(first) < 0)),
    );
    final merged = mergeDateEvents(_events(into), kept);
    if (merged.changed == 0) return into;
    return {...into, 'date_events': _eventsJson(merged.events)};
  }

  /// 手動読み込みは端末のイベントを引き継ぎ、古い台データを組み立て直さない。
  static ({String text, ViewerData data}) preparePicked(
    String incoming,
    ViewerData? previous, {
    String? events,
  }) {
    final fresh = _decodeDocument(incoming);
    if (fresh == null) {
      throw const FormatException('databaseのバックアップファイルではありません。');
    }
    final cachedEvents = _decodeDocument(events);
    final doc =
        fresh['format'] == 'pscube-viewer' || previous?.source == 'pscube'
        ? fresh
        : _withEvents(
            fresh,
            cachedEvents == null
                ? previous?.dateEvents.values ?? const <DateEvent>[]
                : _events(cachedEvents).values,
          );
    return (
      text: identical(doc, fresh) ? incoming : jsonEncode(doc),
      data: _parseDocument(doc),
    );
  }

  /// 統合と表示用モデルの組み立てで、同じ全文を繰り返し解析しない。
  static ({String text, String? note, ViewerData data}) prepareMerge(
    String? stored,
    String incoming,
  ) {
    final result = _mergeDocument(stored, incoming);
    return (
      text: result.text,
      note: result.note,
      data: _parseDocument(result.document),
    );
  }

  static Map<String, dynamic>? _decodeDocument(String? text) {
    if (text == null) return null;
    try {
      final doc = jsonDecode(text);
      return doc is Map && doc['records'] is List
          ? Map<String, dynamic>.from(doc)
          : null;
    } on FormatException {
      return null;
    }
  }

  /// 共有カレンダーのファイル [shared]（`{format: database-events, events}`）の入力時刻つきイベントを、
  /// 端末の内容 [stored] に足す（新しい方が残る）。変わらなければ・読めなければ null。
  /// 共有ファイルのイベント [shared] を、表示中のイベント [current]（端末の内容から作ったもの）に
  /// 足すと変わるか。[withSharedEvents] と同じ規則（時刻つきだけ・付け外しした時刻の新しい方）。
  /// 変わらなければ端末の本体（数十MB）を読まずに済む（開くたびに読んでいた、2026-10-29）。
  static bool sharedEventsChange(
    Map<String, DateEvent> current,
    String shared,
  ) {
    Object? doc;
    try {
      doc = jsonDecode(shared);
    } on FormatException {
      return false;
    }
    if (doc is! Map ||
        doc['format'] != 'database-events' ||
        doc['events'] is! List) {
      return false;
    }
    final incoming = _events({'date_events': doc['events']}).values
        .where((event) => event.updatedAt != null);
    return mergeDateEvents(current, incoming).changed > 0;
  }

  static String? withSharedEvents(String stored, String shared) {
    Object? doc;
    try {
      doc = jsonDecode(shared);
    } on FormatException {
      return null;
    }
    if (doc is! Map ||
        doc['format'] != 'database-events' ||
        doc['events'] is! List) {
      return null;
    }
    final merged = withOtherEvents(
      jsonEncode({'date_events': doc['events']}),
      stored,
      timedOnly: true,
    );
    return identical(merged, stored) ? null : merged;
  }

  /// スクリプトへ送る中身：その端末の入力時刻つきイベント（メルヘン）。
  static String sharedEventsBody(Iterable<DateEvent> events) => jsonEncode({
    'file': 'events',
    'events': _eventsJson({
      for (final e in events)
        if (e.updatedAt != null && storeNames.containsKey(e.store)) e.key: e,
    }),
  });

  /// スクリプトの返事を、利用者への知らせにする。送れたら ok が true。
  static ({bool ok, String message}) sharedResult(String response) {
    try {
      final doc = jsonDecode(response);
      if (doc is Map && doc['ok'] == true) {
        return (ok: true, message: 'イベントを共有カレンダーに送りました。');
      }
      if (doc is Map && doc['error'] is String) {
        return (ok: false, message: doc['error'] as String);
      }
    } on FormatException {
      // 下の知らせ
    }
    return (ok: false, message: 'スクリプトの返事が読めません（スクリプトを新しい版に更新したか確認してください）。');
  }

  /// [text] の [store] の [days] に同じイベント名を付ける（null・空は消す）。入力した時刻を
  /// 残し、名前の変わらない日は前の時刻のまま。何も変わらなければ [text] をそのまま返す。
  static String setEvents(
    String text,
    String store,
    List<String> days,
    String? name,
    DateTime now,
  ) {
    final decoded = Map<String, dynamic>.from(jsonDecode(text) as Map);
    final events = _events(decoded);
    final trimmed = name?.trim() ?? '';
    var changed = false;
    for (final day in days) {
      final old = events['$store|$day'];
      if ((old == null || old.removed ? '' : old.name) == trimmed) continue;
      events['$store|$day'] = DateEvent(
        store: store,
        day: day,
        name: trimmed,
        updatedAt: eventStamp(now, old?.updatedAt),
      );
      changed = true;
    }
    if (!changed) return text;
    return jsonEncode({...decoded, 'date_events': _eventsJson(events)});
  }

  /// イベントだけのバックアップ（台の記録は空）。PC・Androidのバックアップ読み込みで取り込める。
  static String eventsOnlyBackup(Iterable<DateEvent> events, DateTime now) =>
      jsonEncode({
        'format': 'database-backup',
        'version': 1,
        'source': 'browser',
        'exported_at': _withOffset(now),
        'date_events': _eventsJson({
          for (final e in events)
            if (storeNames.containsKey(e.store)) e.key: e,
        }),
        'records': <Object>[],
      });

  static String eventsBackupFileName(DateTime now) {
    final t = now.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    return 'database-backup-browser-events-${t.year}${two(t.month)}${two(t.day)}'
        '-${two(t.hour)}${two(t.minute)}${two(t.second)}.json';
  }

  static Map<String, DateEvent> _events(Map<dynamic, dynamic> decoded) {
    final events = <String, DateEvent>{};
    final items = decoded['date_events'];
    if (items is List) {
      for (final item in items) {
        final event = DateEvent.tryFromJson(item);
        if (event != null) events[event.key] = event;
      }
    }
    return events;
  }

  static List<Map<String, dynamic>> _eventsJson(
    Map<String, DateEvent> events,
  ) => [for (final key in events.keys.toList()..sort()) events[key]!.toJson()];

  static String _withOffset(DateTime now) {
    final local = now.toLocal();
    final offset = local.timeZoneOffset;
    final minutes = offset.inMinutes.abs();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${local.toIso8601String().substring(0, 19)}'
        '${offset.isNegative ? '-' : '+'}${two(minutes ~/ 60)}:${two(minutes % 60)}';
  }

  /// Driveから自動で読んだ内容 [incoming] と、端末に覚えていた内容 [stored] を
  /// 合わせる（どちらも閲覧ページのJSON）。
  ///
  /// * 覚えていた方が新しく書き出されたもの（手で新しいバックアップを読み込んだ
  ///   直後など）なら、置き換えずに覚えていた方を使う。
  /// * そうでなければDriveの方を使い、Driveの内容より前の日の台（手で全期間の
  ///   バックアップを読み込んでいた分）は残して足す。Driveの閲覧用ファイルは
  ///   直近60日分だけなので、そのまま置き換えると古い日が消えてしまうため。
  ///
  /// 返す [text] を表示・保存に使う。[note] は利用者への知らせ（無ければ null）。
  static ({String text, String? note}) merge(String? stored, String incoming) {
    try {
      final result = _mergeDocument(stored, incoming);
      return (text: result.text, note: result.note);
    } on FormatException {
      return (text: incoming, note: null);
    }
  }

  static ({String text, String? note, Map<String, dynamic> document})
  _mergeDocument(String? stored, String incoming) {
    final old = _decodeDocument(stored);
    final fresh = _decodeDocument(incoming);
    if (fresh == null) {
      throw const FormatException('databaseのバックアップファイルではありません。');
    }
    final result = _mergeRecords(old, fresh);
    var doc = result.document;
    final keptStored = identical(doc, old);
    final eventsFrom = keptStored ? fresh : old;
    if (doc['format'] != 'pscube-viewer' &&
        eventsFrom != null &&
        eventsFrom['format'] != 'pscube-viewer') {
      doc = _withEvents(doc, _events(eventsFrom).values, timedOnly: keptStored);
    }
    if (old != null && old['format'] == fresh['format']) {
      dynamic status(Map<String, dynamic> d) =>
          d['sync_status'] ??
          (d['header'] is Map ? d['header']['sync_status'] : null);
      final health = mergeSyncStatuses(status(old), status(fresh));
      if (health != null) doc = {...doc, 'sync_status': health};
    }
    if (old != null) {
      final marks = mergeRainbowMarks(
        rainbowMarksOf(doc),
        rainbowMarksOf(old).values,
      );
      if (marks.changed != 0) {
        doc = {
          ...doc,
          'rainbow_marks': [
            for (final key in marks.marks.keys.toList()..sort())
              marks.marks[key]!.toJson(),
          ],
        };
      }
    }
    return (
      document: doc,
      note: result.note,
      text: identical(doc, old)
          ? stored!
          : identical(doc, fresh)
          ? incoming
          : jsonEncode(doc),
    );
  }

  static ({Map<String, dynamic> document, String? note}) _mergeRecords(
    Map<String, dynamic>? old,
    Map<String, dynamic> fresh,
  ) {
    DateTime? exportedAt(Map<String, dynamic> doc) {
      final header = doc['header'];
      return header is Map
          ? DateTime.tryParse(header['exported_at'] as String? ?? '')
          : null;
    }

    String when(DateTime at) {
      final local = at.toLocal();
      String two(int v) => v.toString().padLeft(2, '0');
      return '${local.month}/${local.day} ${two(local.hour)}:${two(local.minute)}';
    }

    if (old == null) return (document: fresh, note: null);
    // P's CUBE's bridge merges records by shop/rate/machine/rack/day before
    // returning them, preserving older days and detailed graphs.
    if (fresh['format'] == 'pscube-viewer') {
      return (document: fresh, note: null);
    }
    final oldAt = exportedAt(old);
    final freshAt = exportedAt(fresh);
    if (oldAt != null && freshAt != null && oldAt.isAfter(freshAt)) {
      return (
        document: old,
        note:
            '前に読み込んだ内容（${when(oldAt)}書き出し）の方が、Googleドライブの内容'
            '（${when(freshAt)}書き出し）より新しいので、置き換えていません。',
      );
    }
    String? dayOf(Object? item) {
      final day = item is Map ? item['day'] : null;
      return day is String && isValidRecordDay(day) ? day : null;
    }

    final freshRecords = fresh['records'] as List;
    final freshDays = [for (final item in freshRecords) ?dayOf(item)];
    if (freshDays.isEmpty) return (document: fresh, note: null);
    final first = freshDays.reduce((a, b) => a.compareTo(b) <= 0 ? a : b);
    final completeDays = fresh['history_days'] is List
        ? (fresh['history_days'] as List).whereType<String>().toSet()
        : null;
    final older = [
      for (final item in old['records'] as List)
        if (dayOf(item) case final day?
            when completeDays != null
                ? !completeDays.contains(day)
                : day.compareTo(first) < 0)
          item,
    ];
    if (older.isEmpty) return (document: fresh, note: null);
    final events = <String, Object?>{};
    // 最新の対象期間ではイベントの解除も反映する。手元のイベントを
    // 引き継ぐのは、今回残した古い記録の店舗・日付だけ。
    final keptDays = {
      for (final item in older)
        if (item is Map) '${item['store']}|${item['day']}',
    };
    for (final list in [old['date_events'], fresh['date_events']]) {
      if (list is! List) continue;
      for (final item in list) {
        final event = DateEvent.tryFromJson(item);
        if (event != null &&
            (identical(list, fresh['date_events']) ||
                keptDays.contains(event.key))) {
          events[event.key] = item;
        }
      }
    }
    return (
      document: {
        ...fresh,
        'records': [...freshRecords, ...older],
        'date_events': events.values.toList(),
        'kept_older': older.length,
      },
      note:
          'Googleドライブの最新に、前に読み込んだ${first.substring(5).replaceAll('-', '/')}より前の'
          '${older.length}台を合わせて表示しています。',
    );
  }

  static SlotRecord? _record(Object? item) {
    if (item is! Map) return null;
    final raw = Map<String, dynamic>.from(item);
    final kind = raw['kind_code'];
    final machine = raw['machine'];
    final day = raw['day'];
    if (!storeNames.containsKey(raw['store']) ||
        (kind != null && kind != 21) ||
        !hasValidRecordNumbers(raw) ||
        machine is! String ||
        machine.trim().isEmpty ||
        day is! String ||
        !isValidRecordDay(day)) {
      return null;
    }
    try {
      final record = SlotRecord.fromJson(raw);
      return record.copyWith(machine: normalizeMachineName(record.machine));
    } on Object {
      return null;
    }
  }
}
