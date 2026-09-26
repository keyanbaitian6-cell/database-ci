import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'candidate_log.dart';
import 'date_events.dart';
import 'models.dart';

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

  List<SlotRecord> get toSave => [
    ...added,
    ...graphOnly,
    ...linkOnly,
    ...settingOnly,
  ];
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
  });
  final List<dynamic> records;
  final List<CandidateSnapshot> candidates;
  final List<DateEvent> events;
}

/// 1行に1台の形ではない（以前のAndroid版の書き出しなど）ファイルは丸ごと
/// 読むしかない。その上限。これを超えると、メモリ不足で落ちる前に止める。
const wholeBackupLimitBytes = 64 * 1024 * 1024;

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
    'exported_at': DateTime.now().toIso8601String(),
    'source': source,
    'records': records.map((r) => r.toJson()).toList(),
    if (events.isNotEmpty)
      'date_events': [for (final e in events) e.toJson()],
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
    if (decoded is! Map || decoded['records'] is! List) {
      throw const FormatException('バックアップファイルの形式が不正です。');
    }
    return plan(decoded['records'] as List, existing);
  }

  /// バックアップを少しずつ読む。1行に1台の形（この版のAndroidとPC版の
  /// 書き出し）なら1行ずつ、そうでなければ上限までの大きさに限り丸ごと読む。
  Stream<BackupChunk> readBackupFile(
    File file, {
    int chunkSize = 300,
    int wholeFileLimit = wholeBackupLimitBytes,
  }) async* {
    final records = <dynamic>[];
    final candidates = <CandidateSnapshot>[];
    var events = <DateEvent>[];
    var section = 'header';
    var lineLayout = false;
    final recordsStart = RegExp(r'"records"\s*:\s*\[$');
    await for (final line
        in file
            .openRead()
            .transform(utf8.decoder)
            .transform(const LineSplitter())) {
      final text = line.trim();
      if (text.isEmpty) continue;
      if (section == 'header') {
        final match = recordsStart.firstMatch(text);
        if (!text.startsWith('{') || match == null) break;
        var head = text.substring(0, match.start).trimRight();
        if (head.endsWith(',')) head = head.substring(0, head.length - 1);
        final header = jsonDecode('$head}');
        if (header is! Map || header['format'] != backupFormat) {
          throw const FormatException('バックアップファイルの形式が不正です。');
        }
        if (header['source'] == 'pc-viewer') {
          throw const FormatException(
            'これは閲覧ページ用の軽いファイル（画像なし）です。バックアップとして取り込まないでください。',
          );
        }
        events = _eventsOf(header);
        lineLayout = true;
        section = 'records';
        continue;
      }
      if (text.startsWith(']')) {
        section =
            section == 'records' &&
                text.contains('"candidate_snapshots"') &&
                text.endsWith('[')
            ? 'candidates'
            : 'done';
        continue;
      }
      if (section == 'done') continue;
      final item = jsonDecode(
        text.endsWith(',') ? text.substring(0, text.length - 1) : text,
      );
      if (section == 'records') {
        records.add(item);
        if (records.length >= chunkSize) {
          yield BackupChunk(records: List.of(records));
          records.clear();
        }
      } else {
        final snapshot = CandidateSnapshot.tryFromJson(item);
        if (snapshot != null) candidates.add(snapshot);
      }
    }
    if (lineLayout) {
      yield BackupChunk(records: records, candidates: candidates, events: events);
      return;
    }
    if (await file.length() > wholeFileLimit) {
      throw const FormatException(
        '以前の形式の大きなバックアップは、メモリ不足を避けるため読み込めません。'
        '最新のアプリで書き出し直したファイルを使ってください。',
      );
    }
    final decoded = jsonDecode(await file.readAsString());
    if (decoded is! Map || decoded['records'] is! List) {
      throw const FormatException('バックアップファイルの形式が不正です。');
    }
    final all = decoded['records'] as List;
    for (var i = 0; i < all.length; i += chunkSize) {
      final end = i + chunkSize > all.length ? all.length : i + chunkSize;
      yield BackupChunk(records: all.sublist(i, end));
    }
    yield BackupChunk(candidates: _candidatesOf(decoded));
    final parsedEvents = _eventsOf(decoded);
    if (parsedEvents.isNotEmpty) yield BackupChunk(events: parsedEvents);
  }
}

/// バックアップの取り込み計画を、少しずつ読んだ分ごとに作る。
/// ファイルの中の同じ台の重複は、分をまたいでも見つける。
class BackupPlanner {
  BackupPlanner(List<SlotRecord> existing)
    : _byKey = {for (final r in existing) r.key: r};

  final Map<String, SlotRecord> _byKey;

  /// 台ごとに、読んだ記録の中身の目印（全文は持たない）。
  final _seen = <String, int>{};

  static bool _validRaw(Map<String, dynamic> raw) {
    final storeOk = storeNames.containsKey(raw['store']);
    final kindOk = raw['kind_code'] == null || raw['kind_code'] == 21;
    final machine = raw['machine'];
    final day = raw['day'];
    final setting = raw['confirmed_setting'];
    if (!storeOk || !kindOk || raw['rack'] == null) return false;
    if (machine is! String || machine.trim().isEmpty) return false;
    if (day is! String) return false;
    if (setting != null && !confirmedSettingOptions.contains(setting)) {
      return false;
    }
    return isValidRecordDay(day);
  }

  /// 項目の順番に左右されない、中身の目印。
  static int _fingerprint(Object? value) {
    final text = _canonical(value);
    return Object.hash(text.length, text.hashCode);
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
      final parsed = SlotRecord.fromJson(raw);
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
          incoming.copyWith(
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
          local.copyWith(
            detailUrl: incoming.detailUrl,
            confirmedSetting:
                incoming.confirmedSetting ?? local.confirmedSetting,
          ),
        );
      } else if (incoming.confirmedSetting != null &&
          local.confirmedSetting == null) {
        settingOnly.add(
          local.copyWith(confirmedSetting: incoming.confirmedSetting),
        );
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
    );
  }
}

/// 取り込みの結果（少しずつ読んだ分の合計）。台そのものは数だけ持つ
/// （確認が要る競合だけは、確認画面に出すため中身を持つ）。
class BackupImportResult {
  int added = 0;
  int graphOnly = 0;
  int linkOnly = 0;
  int settingOnly = 0;
  int unchanged = 0;
  int skipped = 0;
  int candidates = 0;
  int dateEventsAdded = 0;
  int dateEventConflicts = 0;

  /// 保存期間より古く、一時的に取り込んだ台の数（次の起動時に片付ける）。
  int temporary = 0;
  final conflicts = <BackupConflict>[];

  void add(BackupImportPlan plan) {
    added += plan.added.length;
    graphOnly += plan.graphOnly.length;
    linkOnly += plan.linkOnly.length;
    settingOnly += plan.settingOnly.length;
    unchanged += plan.unchanged.length;
    skipped += plan.skipped;
    conflicts.addAll(plan.conflicts);
  }
}
