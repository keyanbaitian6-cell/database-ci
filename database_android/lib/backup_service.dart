import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'candidate_log.dart';
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

class BackupService {
  Future<File> export(
    List<SlotRecord> records, {
    String source = 'android',
    List<CandidateSnapshot> candidates = const [],
  }) async {
    final directory = await getTemporaryDirectory();
    final file = File(
      '${directory.path}${Platform.pathSeparator}'
      '${backupFileName(DateTime.now(), source: source)}',
    );
    final payload = backupPayload(
      records,
      source: source,
      candidates: candidates,
    );
    await file.writeAsString(jsonEncode(payload), flush: true);
    return file;
  }

  /// The JSON object [export] writes.
  Map<String, dynamic> backupPayload(
    List<SlotRecord> records, {
    String source = 'android',
    List<CandidateSnapshot> candidates = const [],
  }) => {
    'format': backupFormat,
    'version': backupVersion,
    'exported_at': DateTime.now().toIso8601String(),
    'source': source,
    'records': records.map((r) => r.toJson()).toList(),
    // 翌日候補（仮）の記録。PC版は読まずに無視する（Android版だけが持つ）。
    if (candidates.isNotEmpty)
      'candidate_snapshots': [for (final c in candidates) c.toJson()],
  };

  bool _validRaw(Map<String, dynamic> raw) {
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

  /// Classifies each backup record against what is already saved: new keys
  /// are safe to add, a matching key with only a missing graph is safe to
  /// enrich, and a matching key with different games/BB/RB/max_hold is a
  /// conflict left for the user -- it is never merged silently.
  BackupImportPlan plan(List<dynamic> rawRecords, List<SlotRecord> existing) {
    final byKey = {for (final r in existing) r.key: r};
    final added = <SlotRecord>[];
    final graphOnly = <SlotRecord>[];
    final unchanged = <SlotRecord>[];
    final linkOnly = <SlotRecord>[];
    final settingOnly = <SlotRecord>[];
    final conflicts = <BackupConflict>[];
    var skipped = 0;
    final seen = <String, String>{};
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
      final normalizedJson = incoming.toJson();
      // 比較順や機種名の表記が違うだけの同一記録も、同じ記録として扱う。
      final previousRaw = seen[incoming.key];
      if (previousRaw != null) {
        if (!_sameJson(jsonDecode(previousRaw), normalizedJson)) {
          throw FormatException(
            '${incoming.rack}番台の異なる記録がバックアップ内で重複しています。保存せず中止しました。',
          );
        }
        continue;
      }
      seen[incoming.key] = jsonEncode(normalizedJson);
      final local = byKey[incoming.key];
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

  bool _sameJson(Object? a, Object? b) {
    if (a is Map && b is Map) {
      return a.length == b.length &&
          a.keys.every(b.containsKey) &&
          a.keys.every((key) => _sameJson(a[key], b[key]));
    }
    if (a is List && b is List) {
      return a.length == b.length &&
          List.generate(a.length, (i) => i).every((i) => _sameJson(a[i], b[i]));
    }
    return a == b;
  }

  /// バックアップに入っている翌日候補の記録。無い・読めないものは飛ばす。
  List<CandidateSnapshot> candidatesFromJson(String jsonText) {
    final decoded = jsonDecode(jsonText);
    final raw = decoded is Map ? decoded['candidate_snapshots'] : null;
    if (raw is! List) return const [];
    return [for (final item in raw) ?CandidateSnapshot.tryFromJson(item)];
  }

  BackupImportPlan planFromJson(String jsonText, List<SlotRecord> existing) {
    final decoded = jsonDecode(jsonText);
    if (decoded is! Map || decoded['records'] is! List) {
      throw const FormatException('バックアップファイルの形式が不正です。');
    }
    return plan(decoded['records'] as List, existing);
  }
}
