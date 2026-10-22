import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show Offset;

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:file_picker/file_picker.dart';

import 'backup_service.dart';
import 'record_deletions.dart';
import 'candidate_log.dart';
import 'csv_export_service.dart';
import 'data_checks.dart';
import 'database_service.dart';
import 'date_events.dart';
import 'event_history_model.dart';
import 'graph_preview.dart';
import 'import_day.dart' show meruhenMachineListUrl;
import 'import_service.dart';
import 'import_spool.dart';
import 'record_analysis.dart';
import 'models.dart';
import 'picked_file.dart';
import 'ui_prefs.dart';
import 'web_import_page.dart';
import 'write_queue.dart';

export 'record_analysis.dart' show DayView;

/// 全期間のバックアップを促す注意。前回から3日以上たったか、まだ一度も
/// 保存していなければ出す（記録が無ければ出さない）。
String? backupReminderText(
  DateTime? lastFull,
  bool hasRecords, [
  DateTime? now,
]) {
  if (!hasRecords) return null;
  now ??= DateTime.now();
  if (lastFull == null) {
    return 'まだ全期間のバックアップを保存していません。上のバーのバックアップから「すべての店舗・すべての日付」で書き出し、'
        'Googleドライブなどに保存できたら「保存できた」を押してください。'
        '$retentionDays日より前の記録は、保存できた後でないと端末から片付けません。';
  }
  final days = DateTime(
    now.year,
    now.month,
    now.day,
  ).difference(DateTime(lastFull.year, lastFull.month, lastFull.day)).inDays;
  if (days < 3) return null;
  return '前回の全期間バックアップから$days日たっています（${lastFull.month}/${lastFull.day}）。'
      '「すべての店舗・すべての日付」で書き出して保存してください。';
}

/// 表を取り込み直したとき、保存済みの台と数値が変わったか。変わった台の
/// グラフは、その数値と合わないので外す。
bool tableNumbersChanged(SlotRecord previous, EditableRow row) =>
    previous.games != row.games ||
    previous.bb != row.bb ||
    previous.rb != row.rb ||
    (row.maxHold != null &&
        previous.maxHold != null &&
        previous.maxHold != row.maxHold);

/// 書き出したバックアップ。保存できたと利用者が確かめたら
/// [AppController.confirmBackupSaved] に渡す。
typedef BackupExport = ({
  File file,
  int records,
  int candidates,
  int events,
  int unreadable,

  /// 書き出しを始めた時刻。これより前に保存した台がファイルに入っている。
  DateTime exportedAt,

  /// すべての店舗・すべての日付か。
  bool full,
});

/// 直前の保存を取り消すための控え（1回分だけ）。保存前に無かった台は
/// 削除、あった台は元の内容へ戻す。
class UndoLog {
  String? label;
  List<(SlotRecord saved, SlotRecord? previous)>? entries;
  ImportSpool? spool;

  void rememberImport(ImportSpool value) {
    clear();
    label = 'バックアップの取り込み';
    spool = value;
  }

  void remember(String label, List<(SlotRecord, SlotRecord?)> entries) {
    clear();
    this.label = label;
    this.entries = entries;
  }

  void clear() {
    final old = spool;
    spool = null;
    if (old != null) unawaited(old.delete().catchError((_) {}));
    label = null;
    entries = null;
  }
}

/// アプリの記録と、その保存・削除・取り込み・書き出し。
///
/// 画面の小さな設定は [UiPrefs]、書き込みの順番待ちは [WriteQueue]、グラフ
/// 画像の読み込みは [GraphPreviews]、取り消しの控えは [UndoLog] に分けてある。
/// ここに残るのは記録とその書き込みで、書き込みは必ず [_write]（順番待ち）
/// の中で行う（[_commit] などは外から呼ばれると失敗する）。
class AppController extends ChangeNotifier {
  AppController({
    DatabaseService? database,
    UiPrefs? prefs,
    WriteQueue? queue,
    BackupService? backupService,
  }) : database = database ?? DatabaseService(),
       prefs = prefs ?? UiPrefs(),
       _queue = queue ?? WriteQueue(),
       backupService = backupService ?? BackupService() {
    previews = GraphPreviews(this.database.loadPreview);
    _queue.onLateFinish = _lateFinished;
  }

  /// 画面をまたいで短く知らせる（取り込み画面を開いていても見えるように）。
  /// main.dart が設定する。
  void Function(String text)? onNotice;

  /// 時間を超えた書き込みが、後から終わった。呼んだ画面はもう時間切れを
  /// 出しているので、結果をあらためて知らせる。
  void _lateFinished(Object? error) {
    message = error == null
        ? '時間がかかっていた処理が、いま終わりました。画面の記録は最新です。'
        : '時間がかかっていた処理は、失敗して終わりました。記録を確かめてください。\n$error';
    notifyListeners();
    onNotice?.call(message!);
  }

  final DatabaseService database;
  final UiPrefs prefs;
  final WriteQueue _queue;
  late final GraphPreviews previews;
  final csvExporter = CsvExportService();
  final BackupService backupService;
  final _undo = UndoLog();
  ImportSpool? _conflictSpool;

  /// 画面用の記録（グラフの画像・曲線は持たない軽い形）。変更できない一覧で、
  /// 書き込みのたびに新しい一覧に入れ替える（そのたびに [revision] が進む）。
  List<SlotRecord> get records => _records;
  List<SlotRecord> _records = const [];
  set records(List<SlotRecord> value) {
    // 対象外の機種（稼働停止の台など）は、以前に保存した記録が残っていても画面に出さない。
    _records = List.unmodifiable(
      value.where((r) => !isHiddenMachine(r.store, r.machine)),
    );
    _revision++;
    _dayViews.clear();
  }

  /// 記録の版。記録が変わるたびに1つ進む。画面の計算結果を使い回すかどうかは、
  /// これで決める。
  int get revision => _revision;
  int _revision = 0;

  /// 翌日候補（仮）の記録（candidate_log.dart）。バックアップにも入る。
  List<CandidateSnapshot> candidateSnapshots = [];
  Map<String, CandidateSnapshot> _latestCandidates = {};

  /// DBに残す小さな状態（前回の書き出し時刻・候補の記録に失敗した回数）。
  Map<String, String> appState = {};

  /// 店舗・日付ごとのイベント名。台の採点や候補計算には使わない。
  /// 「イベントを消した」印（[DateEvent.removed]）も、バックアップと統合のために含む。
  Map<String, DateEvent> dateEvents = {};

  Map<String, dynamic> get historyEdits =>
      appState['event_history_edits'] == null
      ? emptyHistoryEdits()
      : Map<String, dynamic>.from(
          jsonDecode(appState['event_history_edits']!) as Map,
        );

  Future<Map<String, dynamic>> saveHistoryEdits(
    Map<String, dynamic> incoming,
  ) => _write(() async {
    if (incoming.containsKey(saiwaichouHistoryKey)) {
      throw const FormatException('幸町の優・良はPCで入力・修正してください。');
    }
    final base = await loadHistoryBase();
    final merged = mergeHistoryEdits(historyEdits, incoming, base);
    final encoded = jsonEncode(merged.edits);
    await database.applyChanges(
      ChangeSet(state: {'event_history_edits': encoded}),
    );
    appState = {...appState, 'event_history_edits': encoded};
    if (merged.conflicts > 0) {
      onNotice?.call('履歴の不一致${merged.conflicts}件は、入力時刻の新しい方を採りました。');
    }
    notifyListeners();
    return merged.edits;
  });

  DateEvent? dateEventFor(String? store, String? day) {
    final event = store == null || day == null
        ? null
        : dateEvents['$store|$day'];
    return event == null || event.removed ? null : event;
  }

  /// イベント入力のプルダウン（既定の候補と、今付いている名前）。
  List<String> dateEventNamesFor(String store) =>
      dateEventNames(dateEvents.values, store: store);

  List<DateEvent> _decodeDateEvents(String? text) {
    if (text == null) return [];
    try {
      final raw = jsonDecode(text);
      if (raw is! List) return [];
      return [for (final item in raw) ?DateEvent.tryFromJson(item)];
    } on Object {
      return [];
    }
  }

  static String _encodeDateEvents(Iterable<DateEvent> events) => jsonEncode([
    for (final event
        in (events.toList()..sort((a, b) => a.key.compareTo(b.key))))
      event.toJson(),
  ]);

  Future<void> _saveDateEvents() async {
    _queue.checkInside('イベント名の保存');
    final json = _encodeDateEvents(dateEvents.values);
    await database.applyChanges(ChangeSet(state: {'date_events': json}));
    appState = {...appState, 'date_events': json};
  }

  Future<void> setDateEvent({
    required String store,
    required String day,
    required String? name,
  }) => setDateEventDays(store: store, days: [day], name: name);

  /// [days] に同じイベント名を付ける（null・空は消す）。入力した時刻を残し、名前が
  /// 変わらない日は前の時刻のまま（前日までに入力した印を消さない）。
  Future<void> setDateEventDays({
    required String store,
    required List<String> days,
    required String? name,
    DateTime? now,
  }) => _write(() async {
    if (!storeNames.containsKey(store) || !days.every(isValidRecordDay)) {
      throw ArgumentError('店舗または日付が不正です。');
    }
    final trimmed = name?.trim() ?? '';
    if (trimmed.length > eventNameMax) {
      throw ArgumentError('イベント名は1〜$eventNameMax文字で入力してください。');
    }
    final previous = Map.of(dateEvents);
    final at = now ?? DateTime.now();
    var changed = 0;
    for (final day in days) {
      final old = dateEvents['$store|$day'];
      if ((old == null || old.removed ? '' : old.name) == trimmed) continue;
      dateEvents['$store|$day'] = DateEvent(
        store: store,
        day: day,
        name: trimmed,
        updatedAt: eventStamp(at, old?.updatedAt),
      );
      changed++;
    }
    if (changed == 0) return;
    try {
      await _saveDateEvents();
    } on Object {
      // 保存できなければ画面の側も元に戻す。
      dateEvents = previous;
      rethrow;
    }
    final where = days.length == 1 ? days.single : '${days.first}〜${days.last}';
    message = trimmed.isEmpty
        ? '$where のイベントを解除しました。'
        : '$where に「$trimmed」を登録しました。';
    notifyListeners();
  });

  /// 前回バックアップを保存した時刻（まだなら null）。
  DateTime? get lastBackupExport =>
      DateTime.tryParse(appState['last_backup_export'] ?? '')?.toLocal();

  /// 前回「すべての店舗・すべての日付」のバックアップを保存できたと確かめた
  /// ときの、その書き出しの時刻。古い記録を端末から片付けてよいかは、これで
  /// 決める。
  DateTime? get lastFullBackupExport =>
      DateTime.tryParse(appState['last_full_backup_export'] ?? '')?.toLocal();

  /// 起動時に古い記録を片付けたときの知らせ（閉じるまで出す）。
  String? retentionNotice;

  /// 片付ける台が多すぎるので止めた台数（0なら止めていない）。
  int pausedCleanup = 0;

  /// 起動時に気づいた問題（読めない記録、翌日候補の記録を読めなかった等）。
  final startupWarnings = <String>[];

  /// 起動中に済んだ変更（起動に失敗したときの説明に使う）。
  final startupChanges = <String>[];

  /// 起動中の、後回しにできる片付け。失敗しても起動は止めず、注意だけ出す
  /// （片付けは1回でまとめて行うので、失敗すれば何も変わっていない）。
  /// [action] は済んだ変更の説明を返す（何も変えなければ null）。
  Future<void> _startupStep(
    Future<String?> Function() action, {
    required String failed,
  }) async {
    try {
      final done = await action();
      if (done != null) startupChanges.add(done);
    } catch (error) {
      startupWarnings.add('$failed\n$error');
    }
  }

  void dismissRetentionNotice() {
    retentionNotice = null;
    notifyListeners();
  }

  void dismissStartupWarnings() {
    startupWarnings.clear();
    notifyListeners();
  }

  /// 全期間のバックアップを促す注意（出さないときは null）。
  String? backupReminder([DateTime? now]) =>
      backupReminderText(lastFullBackupExport, records.isNotEmpty, now);

  /// 変わった翌日候補を求める関数（テストで失敗を差し込むため差し替えられる）。
  List<CandidateSnapshot> Function({
    required Iterable<SlotRecord> saved,
    required List<SlotRecord> all,
    required Map<String, CandidateSnapshot> latest,
    required DateTime now,
  })
  computeCandidates = changedCandidateSnapshots;

  /// 翌日候補を記録できなかった保存の累計回数。
  int get candidateLogFailures =>
      int.tryParse(appState['candidate_log_failures'] ?? '') ?? 0;

  /// 直前の操作の結果（取り込み画面・結果画面の上に出す）。閉じるか、タブを
  /// 切り替えると消える。
  String? message;

  void dismissMessage() {
    message = null;
    notifyListeners();
  }

  int tab = 0;

  void setTab(int value) {
    if (value != tab) message = null;
    tab = value;
    notifyListeners();
  }

  // 結果画面で最後に見た店舗・日付・機種（[UiPrefs]）。
  String? get lastStore => prefs.store;
  String? get lastDay => prefs.day;
  String? get lastMachine => prefs.machine;

  Future<void> rememberSelection(String? store, String? day, String? machine) =>
      prefs.remember(store, day, machine);

  /// 「表の確認画面を省く」設定（[UiPrefs.skipTableReview]）。
  bool get skipTableReview => prefs.skipTableReview;

  Future<void> setSkipTableReview(bool value) async {
    final saving = prefs.setSkipTableReview(value);
    notifyListeners();
    await saving;
  }

  /// 今日の日付（営業日、深夜2時で切り替わる）。テストで差し替える。
  String Function() today = todayIso;

  /// 保存してよい最後の日（明日）。それより先は打ち間違いか端末の日付の狂い。
  String _latestAllowedDay() =>
      DateTime.parse(today())
          .add(const Duration(days: 1))
          .toIso8601String()
          .substring(0, 10);

  void _checkDay(String day) {
    if (!isValidRecordDay(day)) {
      throw ArgumentError('日付（$day）が正しくありません。');
    }
    if (day.compareTo(_latestAllowedDay()) > 0) {
      throw ArgumentError('$day はまだ来ていない日付なので保存しません。日付と、端末の日付設定を確認してください。');
    }
  }

  Future<T> _write<T>(Future<T> Function() action, {bool unlimited = false}) =>
      _queue.run(action, unlimited: unlimited);

  /// [before] は保存する直前にDBから読んだ内容（無かった台は含まない）。
  /// 画面用の一覧は古いことがあるので、取り消しの控えには使わない。
  void _rememberUndo(
    String label,
    List<SlotRecord> rows,
    Map<String, SlotRecord> before,
  ) => _undo.remember(label, [for (final r in rows) (r, before[r.key])]);

  /// 直前の保存を取り消す。まとめて削除の取り消しは千台を超えることがある
  /// ので、時間の上限は設けない。
  Future<String> undoLastSave() => _write(() async {
    final spool = _undo.spool;
    if (spool != null) {
      final previous = <SlotRecord>[];
      final changed = <SlotRecord>[];
      final deleted = <String>[];
      await for (final chunk in spool.chunks()) {
        for (final row in chunk) {
          final saved = SlotRecord.fromJson(
            row['saved'] as Map<String, dynamic>,
          );
          changed.add(saved);
          if (row['previous'] == null) {
            deleted.add(saved.key);
          } else {
            previous.add(
              SlotRecord.fromJson(row['previous'] as Map<String, dynamic>)
                  .lightened(),
            );
          }
        }
      }
      final note = await _commit(
        upserts: previous,
        deleteKeys: deleted,
        changed: changed,
        restoreSpool: spool,
      );
      _undo.clear();
      message = '取り消しました：バックアップの取り込み$note';
      notifyListeners();
      return message!;
    }
    final entries = _undo.entries;
    if (entries == null) return '取り消せる保存がありません。';
    final label = _undo.label ?? '直前の保存';
    // まとめて削除の取り消しは百台を超えることがあるので、1台ずつではなくまとめて戻す。
    final note = await _commit(
      upserts: [for (final (_, previous) in entries) ?previous],
      deleteKeys: [
        for (final (saved, previous) in entries)
          if (previous == null) saved.key,
      ],
      changed: [for (final (saved, _) in entries) saved],
    );
    _undo.clear();
    message = '取り消しました：$label$note';
    notifyListeners();
    return message!;
  }, unlimited: true);

  /// "2026-09-18　長町南 42/80台・幸町 18/60台" (グラフ取り込み済み／一覧の台数)。
  /// 日付が分からないページ（機種一覧）では今日で表示する。
  String progressText({required String? store, required String? day}) {
    if (day == null && store == null) return '';
    final target = day ?? today();
    const shortNames = {'nagamachiminami': '長町南', 'saiwaichou': '幸町'};
    final parts = <String>[];
    for (final entry in shortNames.entries) {
      // 取り込みの対象外の機種（沖ドキなど）は数えない：サイトからは取らないのに、ジャグラーオンラインの
      // 読み取りで記録ができ、済まない台として残って見えていた（2026-10-12、PC progress_text と同じ規則）。
      final rows = records
          .where(
            (r) =>
                r.store == entry.key &&
                r.day == target &&
                !isExcludedMachine(r.store, r.machine),
          )
          .toList();
      if (rows.isEmpty) continue;
      final done = rows.where((r) => r.graphDone).length;
      parts.add('${entry.value} $done/${rows.length}台');
    }
    if (parts.isEmpty) return day == null ? '$target　まだ取り込みがありません' : '';
    return '$target　${parts.join('・')}';
  }

  /// 結果画面の [store]・[day] の採点と翌日候補。記録が変わるまでは、同じ
  /// 計算を使い回す（タブを切り替えて戻っても計算し直さない）。
  Future<DayView> dayView(String store, String day) {
    final key = '$store|$day';
    final cached = _dayViews.remove(key);
    if (cached != null) {
      _dayViews[key] = cached;
      return cached;
    }
    final snapshot = records;
    // 履歴を素早くスクロールしても同時に多数のIsolateを立ち上げない。
    final view = _analysisTail.then(
      (_) => compute(calculateDay, (snapshot, store, day)),
    );
    _analysisTail = view.then<void>(
      (_) {},
      onError: (Object e, StackTrace s) {},
    );
    _dayViews[key] = view;
    while (_dayViews.length > 6) {
      _dayViews.remove(_dayViews.keys.first);
    }
    return view;
  }

  final _dayViews = <String, Future<DayView>>{};
  Future<void> _analysisTail = Future<void>.value();

  /// 起動時の読み込み。書き込み（初回のイベント名・古い記録の片付け）も
  /// あるので、順番待ちの中で行う。
  Future<void> initialize() => _write(() async {
    await ImportSpool.cleanOld((await database.database).path)
        .catchError((_) {});
    startupWarnings.clear();
    startupChanges.clear();
    await prefs.load();
    appState = await database.loadState();
    if (appState.containsKey('date_events')) {
      dateEvents = {
        for (final event in _decodeDateEvents(appState['date_events']))
          event.key: event,
      };
    } else {
      dateEvents = {for (final event in initialDateEvents) event.key: event};
      await _startupStep(() async {
        await _saveDateEvents();
        return 'イベント名の初期値を保存しました。';
      }, failed: 'イベント名の初期値を保存できませんでした。今回は初期値を表示だけして、次の起動でもう一度保存します。');
    }
    // 保存期間（$retentionDays日）より古い台を、バックアップ済みのものだけ片付ける。
    await _startupStep(() async {
      final cleaned = await database.cleanupOldRecords(
        lastFullBackupExport,
        today: today(),
      );
      _noteCleanup(cleaned);
      if (cleaned.deleted == 0 && cleaned.snapshots == 0) return null;
      return '古い記録（${cleaned.deleted}台・翌日候補の記録${cleaned.snapshots}件）を'
          '端末から片付けました（バックアップには残っています）。';
    }, failed: '古い記録の片付けができませんでした。記録はそのままです（次の起動でもう一度行います）。');
    // ここから先の読み込みは起動に欠かせないので、失敗したら起動を止める。
    // 機種名をそろえた後の読み直しで止まっても、そろえた変更は説明に残す。
    await _loadNormalizedRecords(onChanged: startupChanges.add);
    final unreadable = database.unreadableKeys.length;
    if (unreadable > 0) {
      startupWarnings.add(
        '読めない記録が$unreadable件あります（壊れているか、形が違います）。'
        '端末には残してあり、書き出し時は元データを救出用として残します。画面と採点には使っていません。',
      );
    }
    await _startupStep(() async {
      final purged = await database.purgeTrash(
        DateTime.now().subtract(const Duration(days: trashDays)),
      );
      return purged == 0 ? null : '$trashDays日より前にゴミ箱へ入れた$purged件を消しました。';
    }, failed: 'ゴミ箱の古い分を消せませんでした。ゴミ箱はそのままです（次の起動でもう一度行います）。');
    try {
      candidateSnapshots = await database.loadLatestCandidateSnapshots();
      _latestCandidates = latestCandidateSnapshots(candidateSnapshots);
    } catch (error) {
      candidateSnapshots = [];
      _latestCandidates = {};
      startupWarnings.add(
        '翌日候補の記録を読み込めませんでした。記録そのものは端末に残っていて、'
        '書き出し時はDBから読み、読めない内容は元データを救出用として残します。\n$error',
      );
    }
    unawaited(_cleanTemporaryFiles());
  }, unlimited: true);

  void _noteCleanup(CleanupResult cleaned) {
    retentionNotice = null;
    pausedCleanup = cleaned.paused;
    final parts = <String>[];
    if (cleaned.deleted > 0) {
      parts.add(
        '${cleaned.cutoff!.substring(5).replaceAll('-', '/')}より前の${cleaned.deleted}台',
      );
    }
    if (cleaned.snapshots > 0) {
      parts.add('$candidateRetentionDays日より前の翌日候補の記録${cleaned.snapshots}件');
    }
    if (parts.isNotEmpty) {
      retentionNotice =
          '${parts.join('と')}を端末から片付けました'
          '（バックアップには残っています。必要なときはバックアップを読み込んでください）。';
    }
  }

  /// 多すぎるので止めた片付けを、利用者が確かめたうえで行う。バックアップ
  /// から一時的に取り込んだ台は、ここでは片付けない（次の起動時のまま）。
  Future<void> confirmLargeCleanup() => _write(() async {
    _noteCleanup(
      await database.cleanupOldRecords(
        lastFullBackupExport,
        today: today(),
        allowLarge: true,
        temporary: false,
      ),
    );
    await _loadNormalizedRecords();
    notifyListeners();
  }, unlimited: true);

  /// 共有のために作った一時ファイル（バックアップ・CSV・グラフ画像）のうち、
  /// 3日より前のものと、以前の版が残した一時ファイル（[isOldVersionLeftover]）を消す。共有先のアプリが後から読むことがあるので、すぐには
  /// 消さない。失敗しても動作には関係ない。
  Future<void> _cleanTemporaryFiles() async {
    // バックアップの読み込みでファイルを選んだときの写し（cache/file_picker）は、起動時にまとめて消す
    // （以前の版は消しておらず、読み込むたびに溜まっていた。2026-10-05、通常版で604.7MB）。
    // 起動の直後は、ファイルを選んでいる途中ではないので安全。
    if (Platform.isAndroid) {
      try {
        await FilePicker.clearTemporaryFiles();
      } on Object {
        // 片付けに失敗しても動作には関係ない。
      }
    }
    try {
      final dir = await getTemporaryDirectory();
      final limit = DateTime.now().subtract(const Duration(days: 3));
      await for (final entity in dir.list()) {
        if (entity is! File) continue;
        final name = entity.uri.pathSegments.last;
        if (isOldVersionLeftover(name) ||
            (isSharedTemporaryFile(name) &&
                (await entity.lastModified()).isBefore(limit))) {
          await entity.delete();
        }
      }
    } on Object {
      // 一時ファイルは端末の空きが減ればOSも消す。
    }
  }

  /// 1回の書き込み。台の保存・削除・ゴミ箱と、それで変わった翌日候補の
  /// 記録を、同じトランザクションで書く（片方だけ残ることはない）。
  /// 書けたら画面用の一覧を更新する。候補の計算に失敗したときは台だけを
  /// 保存し、失敗した回数をDBに残して、表示用の注記を返す。
  Future<String> _commit({
    List<SlotRecord> upserts = const [],
    List<String> deleteKeys = const [],
    List<String> trashKeys = const [],
    String trashLabel = '',
    TrashKind trashKind = TrashKind.delete,
    List<int> removeTrashIds = const [],
    Iterable<SlotRecord> changed = const [],
    ImportSpool? restoreSpool,
  }) async {
    _queue.checkInside('保存');
    final removed = deleteKeys.toSet();
    final next = _withSaved(
      [
        for (final r in records)
          if (!removed.contains(r.key)) r,
      ],
      [for (final r in upserts) r.lightened()],
    );
    var snapshots = const <CandidateSnapshot>[];
    final state = <String, String>{};
    if (changed.isNotEmpty) {
      try {
        snapshots = await compute(calculateCandidateChanges, (
          [for (final r in changed) r.lightened()],
          next,
          Map<String, CandidateSnapshot>.of(_latestCandidates),
          DateTime.now(),
          computeCandidates,
        ));
      } catch (error) {
        state['candidate_log_failures'] = '${candidateLogFailures + 1}';
        state['candidate_log_last_error'] = '$error';
      }
    }
    final changes = ChangeSet(
      upserts: upserts,
      deleteKeys: deleteKeys,
      trashKeys: trashKeys,
      trashLabel: trashLabel,
      trashKind: trashKind,
      removeTrashIds: removeTrashIds,
      snapshots: snapshots,
      state: state,
    );
    if (restoreSpool == null) {
      await database.applyChanges(changes);
    } else {
      await database.writeTransaction((writer) async {
        await for (final chunk in restoreSpool.chunks()) {
          await writer.apply(
            ChangeSet(
              upserts: [
                for (final row in chunk)
                  if (row['previous'] != null)
                    SlotRecord.fromJson(
                      row['previous'] as Map<String, dynamic>,
                    ),
              ],
              deleteKeys: [
                for (final row in chunk)
                  if (row['previous'] == null)
                    SlotRecord.fromJson(row['saved'] as Map<String, dynamic>)
                        .key,
              ],
            ),
          );
        }
        await writer.apply(ChangeSet(snapshots: snapshots, state: state));
      });
    }
    records = next;
    appState = {...appState, ...state};
    if (snapshots.isNotEmpty) {
      for (final c in snapshots) {
        _latestCandidates[c.groupKey] = c;
      }
      candidateSnapshots = _latestCandidates.values.toList();
    }
    previews.forget([...deleteKeys, for (final r in upserts) r.key]);
    return state.isEmpty ? '' : '（翌日候補を記録できませんでした。累計$candidateLogFailures回）';
  }

  /// DBを読み、機種名の表記ゆれをそろえて一覧にする。DBに `+` 区切りの
  /// 台が残っていれば（取り込み等で入った）、DBの側で画像込みにまとめて
  /// から読み直す。画面用の一覧（画像なし）をDBへ書き戻すことはしない。
  ///
  /// [onChanged] には、そろえた内容がDBに確定したとき（まとめた書き込みが
  /// 済み、1台以上そろえたとき）だけ、その説明を渡す。そろえる処理が失敗して
  /// 元に戻ったときや、そろえる台が無かったときは渡さない。その後の読み直しが
  /// 失敗しても、済んだ変更は渡し終えている。起動時だけ [startupChanges] を
  /// 渡す（引っ張って更新などの読み直しでは渡さないので、起動時の説明に混ざらない）。
  Future<void> _loadNormalizedRecords({
    void Function(String change)? onChanged,
  }) async {
    var loaded = await database.loadAll();
    if (loaded.any((r) => r.machine != normalizeMachineName(r.machine))) {
      final merged = await database.normalizeMachineNames();
      if (merged > 0) {
        onChanged?.call(
          '機種名の表記ゆれがある$merged台を、そろえた名前の台へまとめました'
          '（グラフの画像・設定の記録は残しています）。',
        );
      }
      loaded = await database.loadAll();
    }
    records = _normalizeRecords(loaded);
  }

  List<SlotRecord> _normalizeRecords(List<SlotRecord> source) {
    final merged = <String, SlotRecord>{};
    for (final original in source) {
      final record = original.copyWith(
        machine: normalizeMachineName(original.machine),
      );
      final current = merged[record.key];
      merged[record.key] = current == null
          ? record
          : mergeSameRack(current, record);
    }
    return merged.values.toList();
  }

  /// [base] に保存した台を入れた（置き換えた）新しい一覧。DBを読み直さない。
  List<SlotRecord> _withSaved(List<SlotRecord> base, List<SlotRecord> saved) {
    final index = {for (var i = 0; i < base.length; i++) base[i].key: i};
    final next = List<SlotRecord>.of(base);
    for (final record in saved) {
      final i = index[record.key];
      if (i == null) {
        index[record.key] = next.length;
        next.add(record);
      } else {
        next[i] = record;
      }
    }
    return next;
  }

  /// 画面から読み直す（引っ張って更新）。保存と同じ順番待ちに入れるので、
  /// 保存の途中で読んだ古い一覧が、保存後の一覧を上書きすることはない。
  Future<void> reload() => _write(() async {
    await _loadNormalizedRecords();
    notifyListeners();
  }, unlimited: true);

  /// 表をそのまま保存すると、グラフが外れる（数値が変わる）台の数。
  /// ブラウザの「確認なしで保存」は、これが0のときだけ使う。
  int graphsDroppedBy(WebTableExtraction extraction) {
    final store = extraction.store;
    final day = extraction.day;
    final machine = extraction.machine;
    if (store == null || day == null || machine == null) return 0;
    final name = normalizeMachineName(machine);
    final saved = {
      for (final r in records)
        if (r.store == store && r.day == day && r.machine == name) r.rack: r,
    };
    return extraction.rows.where((row) {
      final previous = saved[row.rack];
      return previous?.graph != null && tableNumbersChanged(previous!, row);
    }).length;
  }

  Future<void> saveTable(
    String store,
    String day,
    String machine,
    List<EditableRow> rows,
  ) => _write(() async {
    _checkDay(day);
    machine = normalizeMachineName(machine);
    if (!storeNames.containsKey(store) || machine.isEmpty || rows.isEmpty) {
      throw ArgumentError('店舗・機種名・台データのいずれかがありません。保存しませんでした。');
    }
    // 残すべきグラフ・設定情報などは、画面用の一覧ではなくDBから読む。
    final old = await database.loadByKeys([
      for (final row in rows) '$store|$day|$machine|${row.rack}',
    ]);
    final now = DateTime.now();
    final saved = rows.map((row) {
      final key = '$store|$day|$machine|${row.rack}';
      final previous = old[key];
      final changed = previous != null && tableNumbersChanged(previous, row);
      return SlotRecord(
        store: store,
        day: day,
        machine: machine,
        rack: row.rack,
        games: row.games,
        bb: row.bb,
        rb: row.rb,
        maxHold: row.maxHold ?? previous?.maxHold,
        previousStart: row.previousStart ?? previous?.previousStart,
        graph: changed ? null : previous?.graph,
        detailUrl: row.detailUrl ?? old[key]?.detailUrl,
        capturedAt: now.toIso8601String(),
        // 初めて保存した時刻だけを残す。以前から保存済みで時刻がない台は不明のまま。
        firstCapturedAt:
            previous?.firstCapturedAt ??
            (previous == null ? timestampWithOffset(now) : null),
        confirmedSetting: old[key]?.confirmedSetting,
        // ジャグラーオンラインの数字で作った台（JUGGLER_ONLINE.md）をサイトの表で取り込み直したら、
        // 作った台の印は外す（数値はサイトのもの。差枚 jo_net などは残す）。
        extra: {...?previous?.extra}..remove('jo_created'),
      );
    }).toList();
    // 数値が変わってグラフが外れる台は、前の内容（グラフ込み）をゴミ箱に残す。
    final dropped = [
      for (final r in saved)
        if (old[r.key]?.graph != null && r.graph == null) r.key,
    ];
    final note = await _commit(
      upserts: saved,
      trashKeys: dropped,
      trashLabel: '$day $machineの表の取り込み直しで外れたグラフ（${dropped.length}台）',
      trashKind: TrashKind.overwrite,
      changed: saved,
    );
    _rememberUndo('$machineの一覧${saved.length}台', saved, old);
    message = '${saved.length}台を保存しました。$note';
    notifyListeners();
  });

  CaptureAnalysis resolveWebGraph(CaptureAnalysis captured) {
    // 一覧の機種名が正本。個別グラフ画面には機種名が載らない場合があるため、
    // 同じ店舗・日付・台番号で保存済みの一覧記録を最優先で引き継ぐ。
    final matching = records.where(
      (record) =>
          record.rack == captured.rack &&
          (captured.store == null || record.store == captured.store) &&
          (captured.day == null || record.day == captured.day),
    );
    final saved = matching.firstOrNull;
    final capturedMachine = captured.machine == null
        ? null
        : normalizeMachineName(captured.machine!);
    return CaptureAnalysis(
      path: captured.path,
      kind: captured.kind,
      fullText: captured.fullText,
      store: captured.store,
      day: captured.day,
      machine:
          saved?.machine ??
          (capturedMachine == null || capturedMachine.isEmpty
              ? null
              : capturedMachine),
      rack: captured.rack,
      games: captured.games ?? saved?.games,
      bb: captured.bb ?? saved?.bb,
      rb: captured.rb ?? saved?.rb,
      maxHold: captured.maxHold ?? saved?.maxHold,
      graph: captured.graph,
    );
  }

  Future<void> saveGraph({
    required String store,
    required String day,
    required String machine,
    required int rack,
    required int games,
    required int bb,
    required int rb,
    required int? maxHold,
    required List<Offset> points,
    required Uint8List previewPng,
    required int previewWidth,
    required int previewHeight,
    List<List<double>>? curve,
  }) => _write(() async {
    _checkDay(day);
    machine = normalizeMachineName(machine);
    final key = '$store|$day|$machine|$rack';
    final before = await database.loadByKeys([key]);
    final existing = before[key];
    final now = DateTime.now();
    final record = SlotRecord(
      store: store,
      day: day,
      machine: machine,
      rack: rack,
      games: games,
      bb: bb,
      rb: rb,
      maxHold: maxHold,
      previousStart: existing?.previousStart,
      detailUrl: existing?.detailUrl,
      capturedAt: now.toIso8601String(),
      firstCapturedAt:
          existing?.firstCapturedAt ??
          (existing == null ? timestampWithOffset(now) : null),
      confirmedSetting: existing?.confirmedSetting,
      extra: existing?.extra ?? const {},
      graph: GraphMeasurement(
        baselineY: points[0].dy,
        peakY: points[1].dy,
        troughY: points[2].dy,
        endY: points[3].dy,
        baselineX: points[0].dx,
        peakX: points[1].dx,
        troughX: points[2].dx,
        endX: points[3].dx,
        previewPng: previewPng,
        previewWidth: previewWidth,
        previewHeight: previewHeight,
        curve: curve,
      ),
    );
    final note = await _commit(
      upserts: [record],
      // グラフを取り込み直すときは、前のグラフをゴミ箱に残す。
      trashKeys: [if (existing?.graph != null) key],
      trashLabel: '$day $rack番台のグラフの取り込み直し',
      trashKind: TrashKind.overwrite,
      changed: [record],
    );
    _rememberUndo('$rack番台のグラフ', [record], before);
    message = '$rack番台を採点しました。$note';
    notifyListeners();
  });

  /// 取り込みミスなどを、機種ごと・日付ごとにまとめて削除する。消した台数を返す。
  /// 消す前の内容を「直前の保存を取り消す」の控えに残すので、1回分は元に戻せる。
  Future<int> deleteGroup({
    required String day,
    String? store,
    String? machine,
  }) => _write(() async {
    final targets = recordsInGroup(
      records,
      day: day,
      store: store,
      machine: machine,
    );
    if (targets.isEmpty) return 0;
    final where = [day, storeNames[store] ?? '両店舗', ?machine].join(' ');
    final keys = [for (final r in targets) r.key];
    // 取り消しの控えは画像込みでDBから読む（画面用の一覧には画像がない）。
    final before = await database.loadByKeys(keys);
    final note = await _commit(
      deleteKeys: keys,
      trashKeys: keys,
      trashLabel: '$whereの削除（${targets.length}台）',
      changed: targets,
    );
    // 取り消すと、消した台を消す前の内容で保存し直す。
    _undo.remember('$whereの削除（${targets.length}台）', [
      for (final r in before.values) (r, r),
    ]);
    message =
        '$whereの記録を削除しました（${targets.length}台）。ゴミ箱から$trashDays日間は戻せます。$note';
    notifyListeners();
    return targets.length;
  }, unlimited: true);

  Future<void> deleteRecord(SlotRecord record) => _write(() async {
    final before = await database.loadByKeys([record.key]);
    final note = await _commit(
      deleteKeys: [record.key],
      trashKeys: [record.key],
      trashLabel: '${record.day} ${record.rack}番台の削除',
      changed: [record],
    );
    _rememberUndo('${record.rack}番台の削除', [record], before);
    message = '${record.rack}番台の記録を削除しました。ゴミ箱から$trashDays日間は戻せます。$note';
    notifyListeners();
  });

  /// Save a user-confirmed setting annotation. It deliberately does not feed
  /// into scoreRecord: a confirmed setting is evidence to retain, not a value
  /// that should make the day's descriptive score look better.
  Future<void> setConfirmedSetting(SlotRecord record, String? value) =>
      _write(() async {
        if (value != null && !confirmedSettingOptions.contains(value)) {
          throw ArgumentError.value(value, 'value', '設定情報が不正です。');
        }
        // 画面が持っている台は古いことがある（グラフ保存の前など）。DBの
        // 今の内容に設定情報だけを足し、グラフなどを巻き戻さない。
        final before = await database.loadByKeys([record.key]);
        final current = before[record.key];
        if (current == null) {
          throw StateError('${record.rack}番台の記録が見つかりません。画面を更新してください。');
        }
        final updated = current.copyWith(
          confirmedSetting: value,
          clearConfirmedSetting: value == null,
        );
        await _commit(upserts: [updated]);
        _rememberUndo('${record.rack}番台の設定情報', [updated], before);
        message = value == null
            ? '${record.rack}番台の設定情報を解除しました。'
            : '${record.rack}番台に「$value」を記録しました。';
        notifyListeners();
      });

  /// ジャグラーオンラインの画面から読んだ値を、取り込み済みの台（同じ店舗・営業日・台番号）に足す
  /// （お試し、`JUGGLER_ONLINE.md`）。台の数値・グラフは変えず、`jo_net`（差枚、推定差枚より優先）などを
  /// 添えるだけ。[create]（`planJoSave` が選んだ、メルヘンで取り込めなかった台）は、前の日の同じ台番号の
  /// 機種名で、ジャグラーオンラインのBB・RB・総回転数の台として作る（グラフ・最大持玉は無い）。
  /// それ以外の取り込んでいない台は作らない。戻り値は（足した台数、作った台数、どちらもしなかった台番号）。
  Future<({int updated, int created, List<int> missing})> attachJugglerOnline({
    required String store,
    required String day,
    required Map<int, Map<String, int>> racks,
    Map<int, ({SlotRecord reference, Map<String, int> values})> create =
        const {},
    DateTime? now,
  }) => _write(() async {
    final time = now ?? DateTime.now();
    final at = timestampWithOffset(time);
    Map<String, Object?> joExtra(Map<String, int> values) => {
      for (final field in const ['net', 'bb', 'rb', 'art', 'start', 'total'])
        if (values[field] != null)
          field == 'total' ? 'jo_games' : 'jo_$field': values[field],
      'jo_captured_at': at,
    };
    final targets = <String, Map<String, int>>{};
    final missing = <int>[];
    for (final entry in racks.entries) {
      final matches = [
        for (final r in _records)
          if (r.store == store && r.day == day && r.rack == entry.key) r.key,
      ];
      if (matches.isEmpty) {
        if (!create.containsKey(entry.key)) missing.add(entry.key);
      } else {
        for (final key in matches) {
          targets[key] = entry.value;
        }
      }
    }
    final created = <SlotRecord>[];
    if (create.isNotEmpty) {
      _checkDay(day);
      for (final MapEntry(key: rack, value: plan) in create.entries) {
        final values = plan.values;
        if (plan.reference.store != store ||
            plan.reference.rack != rack ||
            values['bb'] == null ||
            values['rb'] == null ||
            values['total'] == null) {
          throw ArgumentError('$rack番台を作る内容が正しくありません。保存しませんでした。');
        }
        created.add(
          SlotRecord(
            store: store,
            day: day,
            machine: plan.reference.machine,
            rack: rack,
            games: values['total']!,
            bb: values['bb']!,
            rb: values['rb']!,
            capturedAt: time.toIso8601String(),
            firstCapturedAt: at,
            // メルヘンではなくジャグラーオンラインの数字で作った台の印。
            extra: {...joExtra(values), 'jo_created': true},
          ),
        );
      }
    }
    if (targets.isEmpty && created.isEmpty) {
      message = 'この日の取り込み済みの台がありません。先にメルヘンで取り込んでください。';
      notifyListeners();
      return (updated: 0, created: 0, missing: missing..sort());
    }
    // 画面が持っている台は古いことがある。DBの今の内容に足し、グラフなどを巻き戻さない。
    final before = await database.loadByKeys([
      ...targets.keys,
      for (final r in created) r.key,
    ]);
    final upserts = <SlotRecord>[];
    for (final entry in targets.entries) {
      final current = before[entry.key];
      if (current == null) continue;
      upserts.add(
        current.copyWith(extra: {...current.extra, ...joExtra(entry.value)}),
      );
    }
    // 作る台が、読み込みのあとにほかの保存で入っていたら、作らずに足すだけにする。
    final made = <SlotRecord>[];
    for (final r in created) {
      final current = before[r.key];
      if (current == null) {
        upserts.add(r);
        made.add(r);
      } else {
        upserts.add(
          current.copyWith(
            extra: {...current.extra, ...joExtra(create[r.rack]!.values)},
          ),
        );
      }
    }
    // 作った台は、表を取り込んだときと同じく翌日候補の記録に回す。
    await _commit(upserts: upserts, changed: made);
    _rememberUndo('ジャグラーオンラインの取り込み', upserts, before);
    message =
        'ジャグラーオンラインの値を${upserts.length - made.length}台に足しました。'
        '${made.isEmpty ? '' : '${made.length}台を作りました（グラフ無し）。'}'
        '${missing.isEmpty ? '' : '取り込んでいない台（${missing.length}台）は足していません。'}';
    notifyListeners();
    return (
      updated: upserts.length - made.length,
      created: made.length,
      missing: missing..sort(),
    );
  });

  Future<File> exportCsv({String? store, String? day}) => csvExporter.create(
    records
        .where(
          (r) =>
              (store == null || r.store == store) &&
              (day == null || r.day == day),
        )
        .toList(),
  );

  /// バックアップのファイルを作る。DBから1台ずつ（画像込みで）書くので、
  /// 記録が増えてもメモリに全件を載せない。
  ///
  /// ファイルを作っただけでは「バックアップ済み」にしない（共有を取り消したり、
  /// Googleドライブへの保存に失敗したりしても、アプリからは分からないため）。
  /// 保存できたと利用者が確かめたら [confirmBackupSaved] を呼ぶ。
  Future<BackupExport> exportBackup({
    String? store,
    String? day,
    void Function(int written)? onProgress,
  }) => _write(() async {
    final file = await backupService.newBackupFile();
    final exportedAt = DateTime.now().toUtc();
    final events = [
      for (final event in dateEvents.values)
        if ((store == null || event.store == store) &&
            (day == null || event.day == day))
          event,
    ];
    final result = await database.exportBackup(
      file,
      store: store,
      day: day,
      events: events,
      onProgress: onProgress,
    );
    return (
      file: file,
      records: result.records,
      candidates: result.candidates,
      events: result.events,
      unreadable: result.unreadable,
      exportedAt: exportedAt,
      full: store == null && day == null,
    );
  }, unlimited: true);

  /// 書き出したバックアップを、Googleドライブなどへ保存できたと利用者が
  /// 確かめたときに呼ぶ。全期間の書き出しなら、それより前に保存した古い
  /// 記録を、次の起動から端末で片付けてよい印になる。
  Future<void> confirmBackupSaved(BackupExport exported) => _write(() async {
    if (exported.unreadable > 0) {
      throw StateError('救出用ファイルは通常のバックアップ済みにはできません。端末の記録は残してください。');
    }
    final at = exported.exportedAt.toUtc().toIso8601String();
    final previousFull = lastFullBackupExport;
    final state = {
      'last_backup_export': at,
      // 前の印より古い書き出しで、印を戻さない。
      if (exported.full &&
          (previousFull == null || exported.exportedAt.isAfter(previousFull)))
        'last_full_backup_export': at,
    };
    await database.applyChanges(ChangeSet(state: state));
    appState = {...appState, ...state};
    notifyListeners();
  });

  /// バックアップを取り込む。
  ///
  /// 2回読む。1回目は中身を確かめるだけで、何も書かない（形の違う行や、同じ
  /// 台の違う記録の重複があれば、ここで止まる）。2回目に、新しい台とグラフ・
  /// 設定情報の追加だけを1つのトランザクションで保存する。途中で失敗しても
  /// 何も保存されない。保存済みと数値・設定情報が食い違う台は、保存せずに
  /// 返す（[applyBackupOverrides] で利用者が選ぶ）。[onProgress] には進み
  /// 具合の文を渡す。
  Future<BackupImportResult> importBackup(
    File file, {
    void Function(String progress)? onProgress,
  }) => _write(() async {
    final latestAllowed = _latestAllowedDay();
    final checker = BackupPlanner(records, latestDay: latestAllowed);
    final incomingDeletions = <RecordDeletion>[];
    final storedState = await database.loadState();
    var checked = 0;
    Map<String, dynamic>? incomingHistory;
    await for (final chunk in backupService.readBackupFile(file)) {
      if (chunk.historyEdits != null) incomingHistory = chunk.historyEdits;
      incomingDeletions.addAll(chunk.deletions);
      if (chunk.records.isEmpty) continue;
      checker.plan(chunk.records);
      checked += chunk.records.length;
      onProgress?.call('中身を確かめています… $checked台');
    }

    // 履歴が合流できなくても台データの取り込みは続ける（PC `import_backup` の history_error と同じ）。
    // 端末の履歴はそのまま残し、理由を結果に出す。
    ({
      Map<String, dynamic> edits,
      int changed,
      int conflicts,
      int rejected,
      int weekConflicts,
    })?
    historyMerge;
    String? historyError;
    if (incomingHistory != null) {
      try {
        historyMerge = mergeHistoryEdits(
          storedState['event_history_edits'] == null
              ? emptyHistoryEdits()
              : Map<String, dynamic>.from(
                  jsonDecode(storedState['event_history_edits']!) as Map,
                ),
          incomingHistory,
          await loadHistoryBase(),
        );
      } on Object catch (error) {
        historyError = '履歴は取り込めませんでした（端末の履歴はそのまま残しています）：$error';
      }
    }
    final historyResult = historyMerge;
    final deletions = mergeRecordDeletions([
      ...readRecordDeletions(
        storedState['record_deletions'] == null
            ? null
            : jsonDecode(storedState['record_deletions']!),
      ),
      ...incomingDeletions,
    ]);
    final remainingRecords = records
        .where((r) => recordSurvivesDeletion(r.toJson(), deletions))
        .toList();
    final planner = BackupPlanner(remainingRecords, latestDay: latestAllowed);
    final result = BackupImportResult();
    final undo = await ImportSpool.create((await database.database).path);
    late final ImportSpool conflicts;
    try {
      conflicts = await ImportSpool.create((await database.database).path);
    } catch (_) {
      await undo.discard();
      rethrow;
    }
    final saved = <SlotRecord>[];
    final imported = <(String key, String day)>[];
    var freshCandidateCount = 0;
    final latestCandidates = Map<String, CandidateSnapshot>.of(
      _latestCandidates,
    );
    final events = Map.of(dateEvents);
    var eventsAdded = 0;
    var temporary = const <String>[];
    var written = 0;
    try {
      await database.writeTransaction((writer) async {
        await writer.apply(ChangeSet(deletions: incomingDeletions));
        await for (final chunk in backupService.readBackupFile(file)) {
          if (chunk.records.isNotEmpty) {
            final allowed = chunk.records
                .where((r) => recordSurvivesDeletion(r, deletions))
                .toList();
            result.skipped += chunk.records.length - allowed.length;
            final plan = planner.plan(allowed);
            result.add(plan, lightConflicts: true);
            for (final c in plan.conflicts) {
              await conflicts.add(c.incoming.toJson(), key: c.incoming.key);
            }
            final toSave = plan.toSave;
            if (toSave.isNotEmpty) {
              final before = await writer.loadByKeys([
                for (final r in toSave) r.key,
              ]);
              await writer.apply(
                ChangeSet(upserts: toSave, restoreDeleted: false),
              );
              for (final r in toSave) {
                final light = r.lightened();
                await undo.add({
                  'saved': light.toJson(),
                  'previous': before[r.key]?.toJson(),
                });
                saved.add(light);
                imported.add((r.key, r.day));
              }
            }
            written += chunk.records.length;
            onProgress?.call('保存しています… $written / $checked台');
          }
          freshCandidateCount += await writer.addSnapshots(chunk.candidates);
          for (final c in chunk.candidates) {
            final previous = latestCandidates[c.groupKey];
            if (previous == null ||
                earliestTimestamp(previous.takenAt, c.takenAt) ==
                    previous.takenAt) {
              latestCandidates[c.groupKey] = c;
            }
          }
          // 入力時刻の新しい方が残る（EVENT_CALENDAR.md）。消した印も同じ。
          final merged = mergeDateEvents(events, chunk.events);
          events
            ..clear()
            ..addAll(merged.events);
          eventsAdded += merged.changed;
          result.dateEventConflicts += merged.conflicts;
        }
        await writer.apply(
          ChangeSet(
            state: {
              if (eventsAdded > 0)
                'date_events': _encodeDateEvents(events.values),
              if (historyResult != null)
                'event_history_edits': jsonEncode(historyResult.edits),
            },
          ),
        );
        // 保存期間より古い台は一時的に取り込んだものとし、次の起動時に片付ける。
        final latest = await writer.latestDay();
        if (latest != null) {
          final cutoff = retentionCutoff(latest, today());
          temporary = [
            for (final (key, day) in imported)
              if (day.compareTo(cutoff) < 0) key,
          ];
          if (temporary.isNotEmpty) await writer.markTemporary(temporary);
        }
        // 控えの書き込み失敗もDBのコミット前に検知する。
        await undo.finish();
        await conflicts.finish();
      });
    } catch (_) {
      await undo.discard();
      await conflicts.discard();
      rethrow;
    }
    // ここまで来たら、すべて保存できている。画面用の一覧などを合わせる。
    records = _withSaved(remainingRecords, saved);
    previews.forget([for (final r in saved) r.key]);
    if (freshCandidateCount > 0) {
      _latestCandidates = latestCandidates;
      candidateSnapshots = latestCandidates.values.toList();
    }
    if (eventsAdded > 0) {
      dateEvents = events;
      appState = {...appState, 'date_events': _encodeDateEvents(events.values)};
    }
    if (historyResult != null) {
      appState = {
        ...appState,
        'event_history_edits': jsonEncode(historyResult.edits),
      };
      result.historyAdded = historyResult.changed;
      result.historyConflicts = historyResult.conflicts;
      result.historyRejected = historyResult.rejected;
      result.historyWeekConflicts = historyResult.weekConflicts;
    }
    result.historyError = historyError;
    result.candidates = freshCandidateCount;
    result.dateEventsAdded = eventsAdded;
    result.temporary = temporary.length;
    if (undo.count > 0) {
      _undo.rememberImport(undo);
      message =
          'バックアップから${result.added}件追加、'
          '${result.graphOnly}件にグラフ、${result.settingOnly}件に設定情報を追加しました。';
    } else {
      await undo.discard();
    }
    final oldConflicts = _conflictSpool;
    if (oldConflicts != null) unawaited(oldConflicts.discard());
    if (conflicts.count == 0) {
      await conflicts.discard();
      _conflictSpool = null;
    } else {
      _conflictSpool = conflicts;
      result.conflictSpool = conflicts;
    }
    notifyListeners();
    return result;
  }, unlimited: true);

  /// ゴミ箱（新しい順）。
  Future<List<TrashBatch>> trashBatches() => database.loadTrash();

  /// ゴミ箱の1回分を戻す。削除したものは、今の記録が無い台だけ戻す。
  /// 上書きで外れたものは今の記録を置き換えるので、今の内容をゴミ箱に残す。
  Future<String> restoreTrash(TrashBatch batch) => _write(() async {
    final entries = await database.loadTrashBatch(batch.batchId);
    final existing = await database.loadByKeys([
      for (final e in entries) e.record.key,
    ]);
    final overwrite = batch.kind == TrashKind.overwrite;
    final restore = [
      for (final e in entries)
        if (overwrite || !existing.containsKey(e.record.key)) e,
    ];
    final skipped = entries.length - restore.length;
    if (restore.isEmpty) {
      return '戻せる台はありませんでした（$skipped台は今の記録があります）。';
    }
    final upserts = [for (final e in restore) e.record];
    final note = await _commit(
      upserts: upserts,
      trashKeys: [
        for (final r in upserts)
          if (existing.containsKey(r.key)) r.key,
      ],
      trashLabel: '「${batch.label}」を戻す前の内容',
      trashKind: TrashKind.overwrite,
      removeTrashIds: [for (final e in restore) e.id],
      changed: upserts,
    );
    _rememberUndo('ゴミ箱から戻す', upserts, existing);
    message =
        '${upserts.length}台を戻しました'
        '${skipped > 0 ? '（$skipped台は今の記録があるので戻していません）' : ''}。$note';
    notifyListeners();
    return message!;
  }, unlimited: true);

  /// For each machine name on the site's machine-list page: graphed/listed
  /// counts for that store and day, or null when nothing was imported yet.
  List<Map<String, int>?> machineStatuses({
    required String? store,
    required String? day,
    required List<String> machines,
  }) {
    if (store == null) return [for (final _ in machines) null];
    // 日付が分からないとき（機種一覧ページ）は今日で判定する。
    final target = day ?? today();
    String key(String name) =>
        normalizeMachineName(name).replaceAll(RegExp(r'\s+'), '');
    final counts = <String, List<int>>{};
    // 'newest'：その機種の行の一番新しい取り込み時刻（ミリ秒）。昼に取ったきりの機種を見分ける。
    final newest = <String, int>{};
    for (final r in records.where((r) => r.store == store && r.day == target)) {
      final c = counts.putIfAbsent(key(r.machine), () => [0, 0]);
      c[1]++;
      if (r.graphDone) c[0]++;
      final at = DateTime.tryParse(r.capturedAt ?? '')?.millisecondsSinceEpoch;
      if (at != null && at > (newest[key(r.machine)] ?? 0)) {
        newest[key(r.machine)] = at;
      }
    }
    return [
      for (final name in machines)
        counts[key(name)] == null
            ? null
            : {
                'done': counts[key(name)]![0],
                'total': counts[key(name)]![1],
                if (newest[key(name)] case final at?) 'newest': at,
              },
    ];
  }

  /// The saved rack (for [store]/[day]/[machine]) that still has no graph,
  /// after [rack] if given, wrapping around. Mirrors the PC app's
  /// `_find_next_ungraphed`; the URL is always the one the site gave us.
  NextGraphTarget nextUngraphed({
    required String? store,
    required String? day,
    required String? machine,
    required int? rack,
  }) {
    if (store == null || day == null) {
      return const NextGraphTarget(reason: 'unknown_page');
    }
    final allStoresDayRows = records.where((r) => r.day == day);
    final dayComplete =
        allStoresDayRows.isNotEmpty &&
        allStoresDayRows.every((r) => r.graphDone);
    var name = machine == null || machine.trim().isEmpty
        ? null
        : normalizeMachineName(machine);
    if (name == null && rack != null) {
      name = records
          .where((r) => r.store == store && r.day == day && r.rack == rack)
          .firstOrNull
          ?.machine;
    }
    if (name == null) return const NextGraphTarget(reason: 'unknown_machine');
    final rows = records
        .where((r) => r.store == store && r.day == day && r.machine == name)
        .toList();
    if (rows.isEmpty) return const NextGraphTarget(reason: 'no_rows');
    final warning = duplicateWarning(rows, rack: rack);
    // 大当たり0回の台はグラフを取らないので、次の台にしない。
    final pending = rows.where((r) => !r.graphDone).toList()
      ..sort((a, b) => a.rack.compareTo(b.rack));
    if (pending.isEmpty) {
      return NextGraphTarget(
        url: meruhenMachineListUrl(store, day),
        reason: 'all_done',
        warning: warning,
        dayComplete: dayComplete,
      );
    }
    final later = pending.where((r) => rack == null || r.rack > rack).toList();
    final target = later.isNotEmpty ? later.first : pending.first;
    if (target.detailUrl == null) {
      return NextGraphTarget(
        rack: target.rack,
        remaining: pending.length,
        reason: 'no_link',
        warning: warning,
      );
    }
    return NextGraphTarget(
      url: target.detailUrl,
      rack: target.rack,
      remaining: pending.length,
      warning: warning,
    );
  }

  Future<void> applyBackupOverrides(List<SlotRecord> chosen) => _write(
    () async {
      if (chosen.isEmpty) return;
      final byKey = await database.loadByKeys([for (final r in chosen) r.key]);
      // 上書きしても、手元が持っている個別台リンクは失わない。
      chosen = [
        for (final r in chosen)
          r.copyWith(
            detailUrl: r.detailUrl ?? byKey[r.key]?.detailUrl,
            firstCapturedAt: earliestTimestamp(
              r.firstCapturedAt,
              byKey[r.key]?.firstCapturedAt,
            ),
          ),
      ];
      final note = await _commit(
        upserts: chosen,
        trashKeys: [for (final r in chosen) r.key],
        trashLabel: 'バックアップの内容で上書きする前（${chosen.length}台）',
        trashKind: TrashKind.overwrite,
        changed: chosen,
      );
      _rememberUndo('バックアップの競合反映', chosen, byKey);
      message = '${chosen.length}件を取り込んだ内容で上書きしました。$note';
      notifyListeners();
    },
    unlimited: true,
  );
}

/// 起動できなかったときの説明。起動の途中で済んだ変更（[done]）があれば、
/// それも書く。起動中の変更は1つずつまとめて行う（途中で止まっても、その
/// 変更は入らない）ので、書いたもの以外は変わっていない。
String startupFailureText(List<String> done, Object error) {
  if (done.isEmpty) return '起動できませんでした。記録は変更していません。\n$error';
  return [
    '起動できませんでした。起動の途中で、次のことだけは済んでいます'
        '（どれも最後まで済んでいて、中途半端な状態ではありません）。',
    for (final change in done) '・$change',
    'ほかの記録は変更していません。',
    '$error',
  ].join('\n');
}
