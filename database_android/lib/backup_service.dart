import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'candidate_log.dart';
import 'date_events.dart';
import 'event_history_model.dart';
import 'record_deletions.dart';
import 'models.dart';
import 'import_spool.dart';

const backupFormat = 'database-backup';
const backupVersion = 1;

/// A saved record whose games/BB/RB/max_hold differ from an incoming backup
/// record for the same store/day/machine/rack. Never applied automatically.
class BackupConflict {
  const BackupConflict({required this.local, required this.incoming});
  final SlotRecord local;
  final SlotRecord incoming;
}

class BackupImportPlan {
  const BackupImportPlan({
    required this.added,
    required this.graphOnly,
    required this.unchanged,
    required this.conflicts,
    required this.skipped,
    this.linkOnly = const [],
    this.settingOnly = const [],
    this.extraOnly = const [],
  });

  final List<SlotRecord> added;
  final List<SlotRecord> graphOnly;
  final List<SlotRecord> unchanged;
  final List<BackupConflict> conflicts;
  final int skipped;

  /// Same numbers as the saved row, but the backup knows the rack's own site
  /// link that the local row lacks -- safe to fill in.
  final List<SlotRecord> linkOnly;

  /// Same data, but only the manually entered setting information is new.
  final List<SlotRecord> settingOnly;

  /// Same numbers, but the backup has a newer Juggler Online net (`jo_net`…)
  /// or 🌈 mark (`rainbow`・`rainbow_at`) than the saved row.
  final List<SlotRecord> extraOnly;

  List<SlotRecord> get toSave => [
    ...added,
    ...graphOnly,
    ...linkOnly,
    ...settingOnly,
    ...extraOnly,
  ];
}

const _joKeys = [
  'jo_net',
  'jo_bb',
  'jo_rb',
  'jo_art',
  'jo_start',
  'jo_games',
  'jo_captured_at',
];

DateTime? _extraTime(Object? value) =>
    value is String ? DateTime.tryParse(value) : null;

bool _extraNewer(Object? a, Object? b) {
  final x = _extraTime(a), y = _extraTime(b);
  return x != null && (y == null || x.isAfter(y));
}

/// 数値が同じ台でも、ジャグラーオンラインの差枚（jo_net…）と🌈は、[from] の方が新しければ [from] の値を返す
/// （PC・Googleの同期 meruhenPick と同じ考え方：差枚は jo_captured_at の新しい方、[base] に無ければ足す。
/// 🌈は rainbow_at の新しい方）。2026-11-22、Geminiの点検 H-11③：以前は比べる項目に入っておらず、PCの
/// バックアップで付いた差枚・🌈だけの更新は「変わらない」として取り込まれなかった。無ければ null。
Map<String, Object?>? newerExtras(SlotRecord base, SlotRecord from) {
  final out = <String, Object?>{};
  if (from.extra['jo_net'] is num &&
      (base.extra['jo_net'] is! num ||
          _extraNewer(
            from.extra['jo_captured_at'],
            base.extra['jo_captured_at'],
          ))) {
    for (final key in _joKeys) {
      if (from.extra.containsKey(key)) out[key] = from.extra[key];
    }
  }
  if (from.extra.containsKey('rainbow') &&
      _extraNewer(from.extra['rainbow_at'], base.extra['rainbow_at'])) {
    out['rainbow'] = from.extra['rainbow'];
    out['rainbow_at'] = from.extra['rainbow_at'];
  }
  return out.isEmpty ? null : out;
}

SlotRecord _withExtras(SlotRecord base, SlotRecord from) {
  final extras = newerExtras(base, from);
  return extras == null
      ? base
      : base.copyWith(extra: {...base.extra, ...extras});
}

/// Reads/writes the same portable JSON backup format the PC app uses
/// (`database/core.py`'s `export_backup`/`import_backup`), so either side's
/// file can be shared with and read by the other -- e.g. via a Google Drive
/// folder, with no Drive API wiring in either app.
/// 共有フォルダに置くバックアップの名前。例 database-backup-android-20260923-1140.json
///
/// Drive の共有フォルダには、PC版が書く database-backup-auto.json と、この
/// ファイルが並ぶ。どちらの機械のいつの分かが名前で分かるようにしてある。
/// 半角英数字だけ・空白なし：共有メニュー（「ドライブに保存」など）は、この名前や
/// 共有シートの件名をそのまま保存名に使うことがあり、全角が混ざると読みにくい。
/// 名前を固定して上書きにはしない。共有メニュー経由の保存は上書きにならず、
/// (1)(2) と枝番が付くだけで、かえって分かりにくくなるため。
/// PC版の「同期フォルダの最新を読み込む」は名前ではなく更新日時の新しい順に見る。
String backupFileName(DateTime now, {String source = 'android'}) {
  String two(int value) => value.toString().padLeft(2, '0');
  final stamp =
      '${now.year}${two(now.month)}${two(now.day)}'
      '-${two(now.hour)}${two(now.minute)}${two(now.second)}';
  final tag = source.replaceAll(RegExp(r'[^A-Za-z0-9]'), '');
  return 'database-backup-${tag.isEmpty ? 'app' : tag}-$stamp.json';
}

/// バックアップの一部。大きなファイルも少しずつ読む。
class BackupChunk {
  const BackupChunk({
    this.records = const [],
    this.candidates = const [],
    this.events = const [],
    this.deletions = const [],
    this.historyEdits,
  });
  final Map<String, dynamic>? historyEdits;
  final List<dynamic> records;
  final List<CandidateSnapshot> candidates;
  final List<DateEvent> events;
  final List<RecordDeletion> deletions;
}

/// 1行に1台の形ではない（以前のAndroid版の書き出しなど）ファイルは丸ごと
/// 読むしかない。その上限。これを超えると、メモリ不足で落ちる前に止める。
const wholeBackupLimitBytes = 64 * 1024 * 1024;

final _recordsStart = RegExp(r'"records"\s*:\s*\[$');
const _oversizedWholeBackup = FormatException(
  '以前の形式の大きなバックアップは、メモリ不足を避けるため読み込めません。'
  '最新のアプリで書き出し直したファイルを使ってください。',
);

class BackupService {
  /// 書き出し先（一時フォルダ）。
  Future<File> newBackupFile({String source = 'android'}) async {
    final directory = await getTemporaryDirectory();
    return File(
      '${directory.path}${Platform.pathSeparator}'
      '${backupFileName(DateTime.now(), source: source)}',
    );
  }

  /// バックアップ1つ分のJSON（小さなデータ・テスト用。実際の書き出しは
  /// `DatabaseService.exportBackup` が1台ずつ書く）。
  Map<String, dynamic> backupPayload(
    List<SlotRecord> records, {
    String source = 'android',
    List<CandidateSnapshot> candidates = const [],
    List<DateEvent> events = const [],
  }) => {
    'format': backupFormat,
    'version': backupVersion,
    'exported_at': DateTime.now().toUtc().toIso8601String(),
    'source': source,
    'records': records.map((r) => r.toJson()).toList(),
    if (events.isNotEmpty) 'date_events': [for (final e in events) e.toJson()],
    // 翌日候補（仮）の記録。PC版は読まずに無視する（Android版だけが持つ）。
    if (candidates.isNotEmpty)
      'candidate_snapshots': [for (final c in candidates) c.toJson()],
  };

  /// Classifies each backup record against what is already saved: new keys
  /// are safe to add, a matching key with only a missing graph is safe to
  /// enrich, and a matching key with different games/BB/RB/max_hold is a
  /// conflict left for the user -- it is never merged silently.
  BackupImportPlan plan(List<dynamic> rawRecords, List<SlotRecord> existing) =>
      BackupPlanner(existing).plan(rawRecords);

  /// バックアップに入っている翌日候補の記録。無い・読めないものは飛ばす。
  List<CandidateSnapshot> candidatesFromJson(String jsonText) =>
      _candidatesOf(jsonDecode(jsonText));

  List<DateEvent> eventsFromJson(String jsonText) =>
      _eventsOf(jsonDecode(jsonText));

  static List<CandidateSnapshot> _candidatesOf(Object? decoded) {
    final raw = decoded is Map ? decoded['candidate_snapshots'] : null;
    if (raw is! List) return const [];
    return [for (final item in raw) ?CandidateSnapshot.tryFromJson(item)];
  }

  static List<DateEvent> _eventsOf(Object? decoded) {
    final raw = decoded is Map ? decoded['date_events'] : null;
    if (raw is! List) return const [];
    return [for (final item in raw) ?DateEvent.tryFromJson(item)];
  }

  BackupImportPlan planFromJson(String jsonText, List<SlotRecord> existing) {
    final decoded = jsonDecode(jsonText);
    _validateEnvelope(decoded);
    return plan(decoded['records'] as List, existing);
  }

  static void _validateEnvelope(dynamic decoded, {bool valuesElided = false}) {
    if (decoded is! Map ||
        decoded['format'] != backupFormat ||
        decoded['records'] is! List) {
      throw const FormatException('バックアップファイルの形式が不正です。');
    }
    if (decoded['version'] is! int || decoded['version'] != backupVersion) {
      throw const FormatException('対応していないバックアップのバージョンです。');
    }
    if (decoded['source'] == 'pc-viewer') {
      throw const FormatException(
        'これは閲覧ページ用の軽いファイル（画像なし）です。バックアップとして取り込まないでください。',
      );
    }
    readRecordDeletions(decoded['record_deletions']);
    if (decoded.containsKey('event_history_edits')) {
      validateHistoryEnvelope(decoded['event_history_edits']);
    }
    for (final key in [
      'candidate_snapshots',
      'date_events',
      'record_deletions',
    ]) {
      if (decoded.containsKey(key) && decoded[key] is! List) {
        throw FormatException('$key の形式が不正です。');
      }
    }
    if ((decoded['recovery_required'] ?? 0) != 0 ||
        decoded.containsKey('unreadable_date_events')) {
      throw const FormatException(
        '読めないデータを含む救出用ファイルです。通常の復元には使えません。'
        '元のファイルと端末の記録を残して、データの修復を依頼してください。',
      );
    }
    for (final item in (decoded['date_events'] as List? ?? const [])) {
      if (DateEvent.tryFromJson(item) == null) {
        throw const FormatException('イベント情報に読めない項目があります。');
      }
    }
    if (!valuesElided) {
      for (final item
          in (decoded['candidate_snapshots'] as List? ?? const [])) {
        if (CandidateSnapshot.tryFromJson(item) == null) {
          throw const FormatException('翌日候補の記録に読めない項目があります。');
        }
      }
    }
  }

  /// 上限を超えるファイルでは、最初の空でない行が records の開始で終わるかを
  /// 先に調べる。行全体を作らず、空白の連続を縮めた末尾だけを保持する。
  static Future<bool> _hasStreamedBackupHeader(File file, int limit) async {
    if (limit <= 0) return false;
    final lineBreak = RegExp(r'[\r\n]');
    final whitespace = RegExp(r'\s+');
    const tailLength = '"records" : [ '.length;
    var tail = '';

    void keepTail(String part) {
      final compact = (tail + part).replaceAll(whitespace, ' ');
      tail = compact.length <= tailLength
          ? compact
          : compact.substring(compact.length - tailLength);
    }

    // 上限でUTF-8の途中まで読んだ場合も形式の判定を続ける。本読込では厳密に検証する。
    await for (final block
        in file
            .openRead(0, limit)
            .transform(const Utf8Decoder(allowMalformed: true))) {
      var start = 0;
      for (final separator in lineBreak.allMatches(block)) {
        keepTail(block.substring(start, separator.start));
        final endOfLine = tail.trimRight();
        if (endOfLine.isNotEmpty) return _recordsStart.hasMatch(endOfLine);
        tail = '';
        start = separator.end;
      }
      keepTail(block.substring(start));
    }
    return false;
  }

  /// バックアップを少しずつ読む。1行に1台の形（この版のAndroidとPC版の
  /// 書き出し）なら1行ずつ、そうでなければ上限までの大きさに限り丸ごと読む。
  Stream<BackupChunk> readBackupFile(
    File file, {
    int chunkSize = 300,
    int wholeFileLimit = wholeBackupLimitBytes,
  }) async* {
    if (chunkSize <= 0) throw ArgumentError.value(chunkSize, 'chunkSize');
    if (await file.length() > wholeFileLimit &&
        !await _hasStreamedBackupHeader(file, wholeFileLimit)) {
      throw _oversizedWholeBackup;
    }
    final records = <dynamic>[];
    final candidates = <CandidateSnapshot>[];
    var events = <DateEvent>[];
    var section = 'header';
    var lineLayout = false;
    var streamedCandidates = false;
    var recordCount = 0;
    var candidateCount = 0;
    // 各行の値はjsonDecodeで検証し、文書の外枠は値をnullに置換して検証する。
    // 画像の全文を保持せず、カンマ・閉じ括弧・末尾の余分な文字も検査できる。
    final structure = StringBuffer();
    await for (final line
        in file
            .openRead()
            .transform(utf8.decoder)
            .transform(const LineSplitter())) {
      final text = line.trim();
      if (text.isEmpty) continue;
      if (section == 'header') {
        final match = _recordsStart.firstMatch(text);
        if (!text.startsWith('{') || match == null) break;
        var head = text.substring(0, match.start).trimRight();
        if (head.endsWith(',')) head = head.substring(0, head.length - 1);
        final header = jsonDecode('$head}');
        _validateEnvelope({...header as Map, 'records': <dynamic>[]});
        structure.writeln(text);
        lineLayout = true;
        section = 'records';
        continue;
      }
      if (section == 'done') {
        structure.writeln(text);
        continue;
      }
      if (text.startsWith(']')) {
        structure.writeln(text);
        section =
            section == 'records' &&
                text.contains('"candidate_snapshots"') &&
                text.endsWith('[')
            ? 'candidates'
            : 'done';
        if (section == 'candidates') streamedCandidates = true;
        continue;
      }
      final item = jsonDecode(
        text.endsWith(',') ? text.substring(0, text.length - 1) : text,
      );
      structure.writeln(text.endsWith(',') ? 'null,' : 'null');
      if (section == 'records') {
        recordCount++;
        records.add(item);
        if (records.length >= chunkSize) {
          yield BackupChunk(records: List.of(records));
          records.clear();
        }
      } else {
        final snapshot = CandidateSnapshot.tryFromJson(item);
        if (snapshot == null) {
          throw const FormatException('翌日候補の記録に読めない項目があります。救出用ファイルは修復が必要です。');
        }
        candidates.add(snapshot);
        candidateCount++;
        if (candidates.length >= chunkSize) {
          yield BackupChunk(candidates: List.of(candidates));
          candidates.clear();
        }
      }
    }
    if (lineLayout) {
      // EOFまで到達しただけでは成功にしない。閉じ括弧不足もここで失敗する。
      final envelope = jsonDecode(structure.toString());
      _validateEnvelope(envelope, valuesElided: streamedCandidates);
      final outerRecords = envelope['records'] as List;
      if (outerRecords.length != recordCount ||
          outerRecords.any((r) => r != null)) {
        throw const FormatException('records が重複しているか、形式が不正です。');
      }
      if (streamedCandidates) {
        final outerCandidates = envelope['candidate_snapshots'] as List;
        if (outerCandidates.length != candidateCount ||
            outerCandidates.any((c) => c != null)) {
          throw const FormatException('candidate_snapshots が重複しているか、形式が不正です。');
        }
      } else {
        candidates.addAll(_candidatesOf(envelope));
      }
      events = _eventsOf(envelope);
      // PC版など候補の配列が末尾に別の書式で入る場合も、DBへは分割して渡す。
      var candidateOffset = 0;
      for (
        ;
        candidateOffset + chunkSize < candidates.length;
        candidateOffset += chunkSize
      ) {
        yield BackupChunk(
          candidates: candidates.sublist(
            candidateOffset,
            candidateOffset + chunkSize,
          ),
        );
      }
      yield BackupChunk(
        records: records,
        candidates: candidates.sublist(candidateOffset),
        events: events,
        deletions: readRecordDeletions(envelope['record_deletions']),
        historyEdits: envelope['event_history_edits'] == null
            ? null
            : Map<String, dynamic>.from(envelope['event_history_edits'] as Map),
      );
      return;
    }
    if (await file.length() > wholeFileLimit) {
      throw _oversizedWholeBackup;
    }
    final decoded = jsonDecode(await file.readAsString());
    _validateEnvelope(decoded);
    final all = decoded['records'] as List;
    for (var i = 0; i < all.length; i += chunkSize) {
      final end = i + chunkSize > all.length ? all.length : i + chunkSize;
      yield BackupChunk(records: all.sublist(i, end));
    }
    final rawCandidates = decoded['candidate_snapshots'] as List? ?? const [];
    for (var i = 0; i < rawCandidates.length; i += chunkSize) {
      final end = i + chunkSize > rawCandidates.length
          ? rawCandidates.length
          : i + chunkSize;
      yield BackupChunk(
        candidates: [
          for (final item in rawCandidates.sublist(i, end))
            CandidateSnapshot.tryFromJson(item)!,
        ],
      );
    }
    final parsedEvents = _eventsOf(decoded);
    final deletions = readRecordDeletions(decoded['record_deletions']);
    if (parsedEvents.isNotEmpty ||
        deletions.isNotEmpty ||
        decoded['event_history_edits'] != null) {
      yield BackupChunk(
        events: parsedEvents,
        deletions: deletions,
        historyEdits: decoded['event_history_edits'] == null
            ? null
            : Map<String, dynamic>.from(decoded['event_history_edits'] as Map),
      );
    }
  }
}

/// バックアップの取り込み計画を、少しずつ読んだ分ごとに作る。
/// ファイルの中の同じ台の重複は、分をまたいでも見つける。
class BackupPlanner {
  /// [latestDay] を渡すと、それより後の日付の台は取り込まない（対象外に数える）。
  /// 未来の日付の台が入ると、保存期間の基準や結果の日付一覧が狂うため。
  BackupPlanner(List<SlotRecord> existing, {this.latestDay})
    : _byKey = {for (final r in existing) r.key: r};

  final Map<String, SlotRecord> _byKey;
  final String? latestDay;

  /// 台ごとに、読んだ記録の中身の目印（全文は持たない）。
  final _seen = <String, String>{};

  bool _validRaw(Map<String, dynamic> raw) {
    final day = raw['day'];
    final limit = latestDay;
    if (limit != null && day is String && day.compareTo(limit) > 0) {
      return false;
    }
    return _validShape(raw);
  }

  static bool _validShape(Map<String, dynamic> raw) {
    final storeOk = storeNames.containsKey(raw['store']);
    final kindOk = raw['kind_code'] == null || raw['kind_code'] == 21;
    final machine = raw['machine'];
    final day = raw['day'];
    final setting = raw['confirmed_setting'];
    if (!storeOk || !kindOk || !hasValidRecordNumbers(raw)) return false;
    if (machine is! String || machine.trim().isEmpty) return false;
    if (day is! String) return false;
    if (setting != null && !confirmedSettingOptions.contains(setting)) {
      return false;
    }
    return isValidRecordDay(day);
  }

  /// 項目の順番に左右されない、中身の目印。全文を持つとメモリを使うので、
  /// 長さと、計算方法の違う2つの32ビットの値（FNV-1a と djb2）にする。
  /// 別の中身が同じ目印になるのは、およそ2の64乗分の1。
  static String _fingerprint(Object? value) {
    final text = _canonical(value);
    var fnv = 0x811c9dc5;
    var djb = 5381;
    for (final unit in text.codeUnits) {
      fnv = ((fnv ^ unit) * 0x01000193) & 0xffffffff;
      djb = ((djb * 33) ^ unit) & 0xffffffff;
    }
    return '${text.length}:$fnv:$djb';
  }

  static String _canonical(Object? value) {
    if (value is Map) {
      final keys = value.keys.map((k) => '$k').toList()..sort();
      final parts = [
        for (final k in keys) '${jsonEncode(k)}:${_canonical(value[k])}',
      ];
      return '{${parts.join(',')}}';
    }
    if (value is List) return '[${value.map(_canonical).join(',')}]';
    return jsonEncode(value);
  }

  BackupImportPlan plan(List<dynamic> rawRecords) {
    final added = <SlotRecord>[];
    final graphOnly = <SlotRecord>[];
    final unchanged = <SlotRecord>[];
    final linkOnly = <SlotRecord>[];
    final settingOnly = <SlotRecord>[];
    final extraOnly = <SlotRecord>[];
    final conflicts = <BackupConflict>[];
    var skipped = 0;
    for (final item in rawRecords) {
      if (item is! Map) {
        skipped++;
        continue;
      }
      final raw = Map<String, dynamic>.from(item);
      if (!_validRaw(raw)) {
        skipped++;
        continue;
      }
      // 項目の型が違う（数値の所が文字など）台は、取り込み全体を止めずに対象外にする。
      final SlotRecord parsed;
      try {
        parsed = SlotRecord.fromJson(raw);
      } on Object {
        skipped++;
        continue;
      }
      // 機種名の表記ゆれ（`+` 区切り）をそろえてから比べる。そろえないと、
      // 手元の同じ台が別の機種として二重に追加される。
      final incoming = parsed.copyWith(
        machine: normalizeMachineName(parsed.machine),
      );
      // 比較順や機種名の表記が違うだけの同一記録も、同じ記録として扱う。
      final fingerprint = _fingerprint(incoming.toJson());
      final previous = _seen[incoming.key];
      if (previous != null) {
        if (previous != fingerprint) {
          throw FormatException(
            '${incoming.rack}番台の異なる記録がバックアップ内で重複しています。保存せず中止しました。',
          );
        }
        continue;
      }
      _seen[incoming.key] = fingerprint;
      final local = _byKey[incoming.key];
      if (local == null) {
        added.add(incoming);
        continue;
      }
      // max_hold can be legitimately absent on either side (e.g. saiwaichou's
      // list has no such column yet) -- only a genuine value mismatch on
      // both sides counts as a conflict, never "known vs. not yet known".
      final differs =
          local.games != incoming.games ||
          local.bb != incoming.bb ||
          local.rb != incoming.rb ||
          (local.maxHold != null &&
              incoming.maxHold != null &&
              local.maxHold != incoming.maxHold) ||
          (local.confirmedSetting != null &&
              incoming.confirmedSetting != null &&
              local.confirmedSetting != incoming.confirmedSetting);
      if (differs) {
        conflicts.add(BackupConflict(local: local, incoming: incoming));
        continue;
      }
      if (incoming.graph != null && local.graph == null) {
        graphOnly.add(
          _withExtras(incoming, local).copyWith(
            firstCapturedAt: earliestTimestamp(
              incoming.firstCapturedAt,
              local.firstCapturedAt,
            ),
            detailUrl: incoming.detailUrl ?? local.detailUrl,
            maxHold: incoming.maxHold ?? local.maxHold,
            previousStart: incoming.previousStart ?? local.previousStart,
            confirmedSetting:
                incoming.confirmedSetting ?? local.confirmedSetting,
          ),
        );
      } else if (incoming.detailUrl != null && local.detailUrl == null) {
        // 手元の台（画像を読み込んでいない軽い形）に足すだけ。保存しても
        // DBの画像はそのまま残る。
        linkOnly.add(
          _withExtras(local, incoming).copyWith(
            detailUrl: incoming.detailUrl,
            confirmedSetting:
                incoming.confirmedSetting ?? local.confirmedSetting,
          ),
        );
      } else if (incoming.confirmedSetting != null &&
          local.confirmedSetting == null) {
        settingOnly.add(
          _withExtras(
            local,
            incoming,
          ).copyWith(confirmedSetting: incoming.confirmedSetting),
        );
      } else if (newerExtras(local, incoming) != null) {
        extraOnly.add(_withExtras(local, incoming));
      } else {
        unchanged.add(local);
      }
    }
    return BackupImportPlan(
      added: added,
      graphOnly: graphOnly,
      unchanged: unchanged,
      conflicts: conflicts,
      skipped: skipped,
      linkOnly: linkOnly,
      settingOnly: settingOnly,
      extraOnly: extraOnly,
    );
  }
}

/// 取り込みの結果（少しずつ読んだ分の合計）。台そのものは数だけ持つ
/// （確認が要る競合だけは、確認画面に出すため中身を持つ）。
class BackupImportResult {
  ImportSpool? conflictSpool;
  Future<List<SlotRecord>> readConflicts(List<SlotRecord> selected) async => [
    for (final r in selected)
      if (conflictSpool == null)
        r
      else
        SlotRecord.fromJson(await conflictSpool!.read(r.key)),
  ];
  int added = 0;
  int graphOnly = 0;
  int linkOnly = 0;
  int settingOnly = 0;
  int extraOnly = 0;
  int unchanged = 0;
  int skipped = 0;
  int candidates = 0;
  int historyAdded = 0;
  int historyConflicts = 0;
  int historyRejected = 0;
  int historyWeekConflicts = 0;

  /// 履歴だけ合流できなかったときの理由（台データの取り込みは続けている）。
  String? historyError;
  int dateEventsAdded = 0;
  int dateEventConflicts = 0;

  /// 保存期間より古く、一時的に取り込んだ台の数（次の起動時に片付ける）。
  int temporary = 0;
  final conflicts = <BackupConflict>[];

  void add(BackupImportPlan plan, {bool lightConflicts = false}) {
    added += plan.added.length;
    graphOnly += plan.graphOnly.length;
    linkOnly += plan.linkOnly.length;
    settingOnly += plan.settingOnly.length;
    extraOnly += plan.extraOnly.length;
    unchanged += plan.unchanged.length;
    skipped += plan.skipped;
    conflicts.addAll(
      lightConflicts
          ? [
              for (final c in plan.conflicts)
                BackupConflict(
                  local: c.local.lightened(),
                  incoming: c.incoming.lightened(),
                ),
            ]
          : plan.conflicts,
    );
  }
}
