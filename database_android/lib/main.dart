import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:quick_actions/quick_actions.dart';
import 'package:share_plus/share_plus.dart';

import 'backup_service.dart';
import 'csv_export_service.dart';
import 'data_checks.dart';
import 'database_service.dart';
import 'graph_gate.dart';
import 'import_service.dart';
import 'list_views.dart';
import 'models.dart';
import 'normal_type.dart';
import 'scoring.dart';
import 'setting_estimate.dart';
import 'theme.dart';
import 'web_import_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final controller = AppController();
  await controller.initialize();
  runApp(DatabaseApp(controller: controller));
  _setUpLauncherShortcuts(controller);
}

/// Long-press menu on the app icon: jump straight to importing or to results.
void _setUpLauncherShortcuts(AppController controller) {
  const quickActions = QuickActions();
  quickActions.initialize((type) async {
    // A cold start reaches here before the first screen exists.
    await Future<void>.delayed(const Duration(milliseconds: 500));
    final navigator = navigatorKey.currentState;
    if (navigator == null) return;
    navigator.popUntil((route) => route.isFirst);
    if (type == 'import') {
      controller.setTab(1);
      await ImportPage.openBrowser(navigator, controller);
    } else {
      controller.setTab(0);
    }
  });
  quickActions.setShortcutItems(const [
    ShortcutItem(type: 'import', localizedTitle: '取り込みを始める'),
    ShortcutItem(type: 'results', localizedTitle: '結果を見る'),
  ]);
}

String normalizeMachineName(String value) =>
    value.replaceAll('+', ' ').replaceAll(RegExp(r'\s+'), ' ').trim();

class AppController extends ChangeNotifier {
  AppController({DatabaseService? database})
    : database = database ?? DatabaseService();

  final DatabaseService database;
  final csvExporter = CsvExportService();
  final backupService = BackupService();
  List<SlotRecord> records = [];
  String? message;
  int tab = 0;

  // The results screen's last store/date/machine, kept in a tiny JSON file so
  // reopening the app lands where the user left off instead of re-picking
  // three dropdowns every time. Best effort: a read/write failure is ignored.
  String? lastStore;
  String? lastDay;
  String? lastMachine;

  // 直前の保存（表または1台のグラフ）を保存前の状態へ戻すための控え。
  // 1回分だけ。保存前に無かった台は削除、あった台は元の内容へ戻す。
  String? _undoLabel;
  List<(SlotRecord saved, SlotRecord? previous)>? _undoEntries;
  Future<void> _writeTail = Future<void>.value();

  Future<T> _write<T>(Future<T> Function() action) {
    final result = _writeTail.then((_) => action());
    _writeTail = result.then<void>(
      (_) {},
      onError: (Object error, StackTrace stack) {},
    );
    return result;
  }

  void _rememberUndo(String label, List<SlotRecord> rows) {
    final byKey = {for (final r in records) r.key: r};
    _undoLabel = label;
    _undoEntries = [for (final r in rows) (r, byKey[r.key])];
  }

  Future<String> undoLastSave() => _write(() async {
    final entries = _undoEntries;
    if (entries == null) return '取り消せる保存がありません。';
    final label = _undoLabel ?? '直前の保存';
    // まとめて削除の取り消しは百台を超えることがあるので、1台ずつではなくまとめて戻す。
    await database.restoreRecords(entries);
    _undoEntries = null;
    _undoLabel = null;
    message = '取り消しました：$label';
    await reload();
    return '取り消しました：$label';
  });

  /// 今日の日付。機種一覧ページ（日付なし）の判定に使う。テストで差し替える。
  String Function() today = todayIso;

  /// "2026-09-18　長町南 42/80台・幸町 18/60台" (グラフ取り込み済み／一覧の台数)。
  /// 日付が分からないページ（機種一覧）では今日で表示する。
  String progressText({required String? store, required String? day}) {
    if (day == null && store == null) return '';
    final target = day ?? today();
    const shortNames = {'nagamachiminami': '長町南', 'saiwaichou': '幸町'};
    final parts = <String>[];
    for (final entry in shortNames.entries) {
      final rows = records
          .where((r) => r.store == entry.key && r.day == target)
          .toList();
      if (rows.isEmpty) continue;
      final done = rows.where((r) => r.graph != null).length;
      parts.add('${entry.value} $done/${rows.length}台');
    }
    if (parts.isEmpty) return day == null ? '$target　まだ取り込みがありません' : '';
    return '$target　${parts.join('・')}';
  }

  // 「グラフの確認画面を省く」設定。既定はオフ。条件（graph_gate.dart）を
  // 満たした台だけ、確認なしで保存する。
  bool autoConfirmGraph = false;

  // 「表の確認画面を省く」設定。既定は省く（表はサイトのHTMLをそのまま読むので、
  // 読み違いが起きない。PC版も元から確認画面なしで保存する）。
  bool skipTableReview = true;

  Future<File> _uiStateFile() async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}${Platform.pathSeparator}ui_state.json');
  }

  Future<void> _loadUiState() async {
    try {
      final file = await _uiStateFile();
      if (!await file.exists()) return;
      final decoded = jsonDecode(await file.readAsString());
      if (decoded is Map) {
        lastStore = decoded['store'] as String?;
        lastDay = decoded['day'] as String?;
        lastMachine = decoded['machine'] as String?;
        autoConfirmGraph = decoded['auto_confirm_graph'] == true;
        skipTableReview = decoded['skip_table_review'] != false;
      }
    } catch (_) {}
  }

  Future<void> rememberSelection(
    String? store,
    String? day,
    String? machine,
  ) async {
    if (store == lastStore && day == lastDay && machine == lastMachine) return;
    lastStore = store;
    lastDay = day;
    lastMachine = machine;
    await _writeUiState();
  }

  Future<void> setAutoConfirmGraph(bool value) async {
    autoConfirmGraph = value;
    notifyListeners();
    await _writeUiState();
  }

  Future<void> setSkipTableReview(bool value) async {
    skipTableReview = value;
    notifyListeners();
    await _writeUiState();
  }

  Future<void> _writeUiState() async {
    try {
      final file = await _uiStateFile();
      await file.writeAsString(
        jsonEncode({
          'store': lastStore,
          'day': lastDay,
          'machine': lastMachine,
          'auto_confirm_graph': autoConfirmGraph,
          'skip_table_review': skipTableReview,
        }),
      );
    } catch (_) {}
  }

  /// Reasons [analysis] still needs a manual review; empty = safe to save as is.
  List<String> graphReviewReasons(CaptureAnalysis analysis) {
    final graph = analysis.graph;
    final existing = records
        .where(
          (r) =>
              r.store == analysis.store &&
              r.day == analysis.day &&
              r.rack == analysis.rack &&
              (analysis.machine == null ||
                  r.machine == normalizeMachineName(analysis.machine!)),
        )
        .firstOrNull;
    final reasons = graphAutoSaveBlockers(
      curve: graph?.curve,
      baselineY: graph?.baselineY,
      width: graph?.width.toDouble(),
      games: analysis.games,
      bb: analysis.bb,
      rb: analysis.rb,
      maxHold: analysis.maxHold,
      existing: existing,
    );
    if (graph == null || graph.points.length != 4) {
      reasons.add('4点を自動検出できていません');
    }
    if (analysis.store == null ||
        analysis.day == null ||
        analysis.rack == null ||
        (analysis.machine ?? '').trim().isEmpty) {
      reasons.add('店舗・日付・台番号・機種名のいずれかを特定できません');
    }
    return reasons;
  }

  Future<void> initialize() async {
    await _loadUiState();
    final loaded = await database.loadAll();
    records = _normalizeRecords(loaded);
    final requiresMigration =
        loaded.length != records.length ||
        loaded.any(
          (record) => record.machine != normalizeMachineName(record.machine),
        );
    if (requiresMigration) await database.replaceAll(records);
  }

  List<SlotRecord> _normalizeRecords(List<SlotRecord> source) {
    final merged = <String, SlotRecord>{};
    for (final original in source) {
      final record = original.copyWith(
        machine: normalizeMachineName(original.machine),
      );
      final current = merged[record.key];
      if (current == null) {
        merged[record.key] = record;
        continue;
      }
      final newestNumbers = record.games >= current.games ? record : current;
      final graph = record.graph ?? current.graph;
      merged[record.key] = SlotRecord(
        store: newestNumbers.store,
        day: newestNumbers.day,
        machine: newestNumbers.machine,
        rack: newestNumbers.rack,
        games: newestNumbers.games,
        bb: newestNumbers.bb,
        rb: newestNumbers.rb,
        maxHold: newestNumbers.maxHold,
        previousStart: newestNumbers.previousStart ?? current.previousStart,
        graph: graph,
        detailUrl:
            newestNumbers.detailUrl ?? current.detailUrl ?? record.detailUrl,
        capturedAt: newestNumbers.capturedAt ?? current.capturedAt,
        confirmedSetting:
            newestNumbers.confirmedSetting ??
            current.confirmedSetting ??
            record.confirmedSetting,
      );
    }
    return merged.values.toList();
  }

  /// Puts just-saved records into the in-memory list (replace in place, or
  /// append) instead of re-reading and re-decoding the whole database, whose
  /// rows carry graph images. After each save this used to be the slowest step
  /// before the browser could move on to the next rack.
  void _mergeRecords(List<SlotRecord> saved) {
    final index = {for (var i = 0; i < records.length; i++) records[i].key: i};
    final next = List<SlotRecord>.of(records);
    for (final record in saved) {
      final i = index[record.key];
      if (i == null) {
        index[record.key] = next.length;
        next.add(record);
      } else {
        next[i] = record;
      }
    }
    records = next;
    notifyListeners();
  }

  Future<void> reload() async {
    records = await database.loadAll();
    notifyListeners();
  }

  Future<void> saveTable(
    String store,
    String day,
    String machine,
    List<EditableRow> rows,
  ) => _write(() async {
    machine = normalizeMachineName(machine);
    final old = {for (final record in records) record.key: record};
    final saved = rows.map((row) {
      final key = '$store|$day|$machine|${row.rack}';
      final previous = old[key];
      final changed =
          previous != null &&
          (previous.games != row.games ||
              previous.bb != row.bb ||
              previous.rb != row.rb ||
              (row.maxHold != null &&
                  previous.maxHold != null &&
                  previous.maxHold != row.maxHold));
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
        capturedAt: DateTime.now().toIso8601String(),
        confirmedSetting: old[key]?.confirmedSetting,
      );
    }).toList();
    await database.saveAll(saved);
    _rememberUndo('$machineの一覧${saved.length}台', saved);
    message = '${saved.length}台を保存しました。';
    tab = 0;
    _mergeRecords(saved);
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
    bool returnToBrowser = false,
  }) => _write(() async {
    machine = normalizeMachineName(machine);
    final existing = records
        .where(
          (item) =>
              item.store == store &&
              item.day == day &&
              item.machine == machine &&
              item.rack == rack,
        )
        .firstOrNull;
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
      capturedAt: DateTime.now().toIso8601String(),
      confirmedSetting: existing?.confirmedSetting,
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
    await database.saveAll([record]);
    _rememberUndo('$rack番台のグラフ', [record]);
    message = '$rack番台を採点しました。';
    tab = returnToBrowser ? 1 : 0;
    _mergeRecords([record]);
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
    // 取り消すと、消した台を消す前の内容で保存し直す。
    await database.deleteRecords(targets);
    _undoLabel = '$whereの削除（${targets.length}台）';
    _undoEntries = [for (final r in targets) (r, r)];
    message = '$whereの記録を削除しました（${targets.length}台）。';
    await reload();
    return targets.length;
  });

  Future<void> deleteRecord(SlotRecord record) => _write(() async {
    await database.deleteRecord(record);
    _rememberUndo('${record.rack}番台の削除', [record]);
    message = '${record.rack}番台の記録を削除しました。';
    await reload();
  });

  /// Save a user-confirmed setting annotation. It deliberately does not feed
  /// into scoreRecord: a confirmed setting is evidence to retain, not a value
  /// that should make the day's descriptive score look better.
  Future<void> setConfirmedSetting(SlotRecord record, String? value) =>
      _write(() async {
        if (value != null && !confirmedSettingOptions.contains(value)) {
          throw ArgumentError.value(value, 'value', '設定情報が不正です。');
        }
        final updated = record.copyWith(
          confirmedSetting: value,
          clearConfirmedSetting: value == null,
        );
        await database.saveAll([updated]);
        _rememberUndo('${record.rack}番台の設定情報', [updated]);
        message = value == null
            ? '${record.rack}番台の設定情報を解除しました。'
            : '${record.rack}番台に「$value」を記録しました。';
        _mergeRecords([updated]);
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

  Future<File> exportBackup({String? store, String? day}) {
    final filtered = records
        .where(
          (r) =>
              (store == null || r.store == store) &&
              (day == null || r.day == day),
        )
        .toList();
    return backupService.export(filtered);
  }

  /// Reads a backup file's JSON and applies its safe records (new and
  /// graph-only additions). Records whose numbers or manual setting note conflict with a saved
  /// entry are returned in the plan, unapplied, for the caller to show the
  /// user -- see [applyBackupOverrides].
  Future<BackupImportPlan> importBackup(String jsonText) => _write(() async {
    final plan = backupService.planFromJson(jsonText, records);
    if (plan.toSave.isNotEmpty) {
      await database.saveAll(plan.toSave);
      _rememberUndo('バックアップの取り込み', plan.toSave);
      message =
          'バックアップから${plan.added.length}件追加、'
          '${plan.graphOnly.length}件にグラフ、${plan.settingOnly.length}件に設定情報を追加しました。';
      await reload();
    }
    return plan;
  });

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
    for (final r in records.where((r) => r.store == store && r.day == target)) {
      final c = counts.putIfAbsent(key(r.machine), () => [0, 0]);
      c[1]++;
      if (r.graph != null) c[0]++;
    }
    return [
      for (final name in machines)
        counts[key(name)] == null
            ? null
            : {'done': counts[key(name)]![0], 'total': counts[key(name)]![1]},
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
        allStoresDayRows.every((r) => r.graph != null);
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
    final pending = rows.where((r) => r.graph == null).toList()
      ..sort((a, b) => a.rack.compareTo(b.rack));
    if (pending.isEmpty) {
      return NextGraphTarget(
        url:
            'https://meruhenworld.pt.teramoba2.com/$store/rack_info_kt/?kind_code=21'
            '#database_next_machine=1&database_day=${Uri.encodeComponent(day)}',
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

  Future<void> applyBackupOverrides(List<SlotRecord> chosen) =>
      _write(() async {
        if (chosen.isEmpty) return;
        final byKey = {for (final r in records) r.key: r};
        // 上書きしても、手元が持っている個別台リンクは失わない。
        chosen = [
          for (final r in chosen)
            r.copyWith(detailUrl: r.detailUrl ?? byKey[r.key]?.detailUrl),
        ];
        await database.saveAll(chosen);
        _rememberUndo('バックアップの競合反映', chosen);
        message = '${chosen.length}件を取り込んだ内容で上書きしました。';
        await reload();
      });

  void setTab(int value) {
    tab = value;
    notifyListeners();
  }
}

final navigatorKey = GlobalKey<NavigatorState>();

class DatabaseApp extends StatelessWidget {
  const DatabaseApp({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) => MaterialApp(
    navigatorKey: navigatorKey,
    debugShowCheckedModeBanner: false,
    title: 'database',
    theme: buildAppTheme(),
    home: AnimatedBuilder(
      animation: controller,
      builder: (context, _) => AppShell(controller: controller),
    ),
  );
}

class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final pages = [
      ResultsPage(controller: controller),
      ImportPage(controller: controller),
      HistoryPage(controller: controller),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'database',
          style: TextStyle(fontWeight: FontWeight.w800),
        ),
        actions: [
          IconButton(
            tooltip: 'CSVを共有',
            onPressed: controller.records.isEmpty
                ? null
                : () => _shareCsv(context, controller),
            icon: const Icon(Icons.ios_share),
          ),
          PopupMenuButton<String>(
            tooltip: 'バックアップ（PC版と共有）',
            icon: const Icon(Icons.cloud_sync_outlined),
            onSelected: (value) => value == 'export'
                ? _shareBackup(context, controller)
                : _importBackup(context, controller),
            itemBuilder: (context) => const [
              PopupMenuItem(value: 'export', child: Text('バックアップを共有（書き出し）')),
              PopupMenuItem(value: 'import', child: Text('バックアップを読み込む')),
            ],
          ),
        ],
      ),
      body: SafeArea(child: pages[controller.tab]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: controller.tab,
        onDestinationSelected: controller.setTab,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.score_outlined),
            selectedIcon: Icon(Icons.score),
            label: '結果',
          ),
          NavigationDestination(
            icon: Icon(Icons.add_a_photo_outlined),
            selectedIcon: Icon(Icons.add_a_photo),
            label: '取り込み',
          ),
          NavigationDestination(icon: Icon(Icons.history), label: '過去の記録'),
        ],
      ),
    );
  }
}

Future<void> _shareCsv(BuildContext context, AppController controller) async {
  final options = await showDialog<_BackupExportOptions>(
    context: context,
    builder: (_) =>
        _BackupExportDialog(records: controller.records, title: 'CSVの範囲を選択'),
  );
  if (options == null || !context.mounted) return;
  try {
    final file = await controller.exportCsv(
      store: options.store,
      day: options.day,
    );
    await SharePlus.instance.share(
      ShareParams(
        title: 'databaseの記録',
        subject: 'database スロット記録',
        text: 'databaseから出力したスロット記録CSVです。',
        files: [XFile(file.path, mimeType: 'text/csv')],
      ),
    );
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('CSVを共有できませんでした：$error')));
    }
  }
}

Future<void> _shareBackup(
  BuildContext context,
  AppController controller,
) async {
  final options = await showDialog<_BackupExportOptions>(
    context: context,
    builder: (_) => _BackupExportDialog(records: controller.records),
  );
  if (options == null || !context.mounted) return;
  try {
    final file = await controller.exportBackup(
      store: options.store,
      day: options.day,
    );
    // Some share targets (e.g. "Save to Drive") name the saved file after
    // this title/subject rather than the actual file, so keep both equal to
    // the real filename -- plain ASCII, no half-width/full-width mixing.
    final fileName = file.uri.pathSegments.last;
    await SharePlus.instance.share(
      ShareParams(
        title: fileName,
        subject: fileName,
        text: 'PC版と共有するdatabaseのバックアップです。Google Driveなどに保存してください。',
        files: [XFile(file.path, mimeType: 'application/json')],
      ),
    );
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('バックアップを共有できませんでした：$error')));
    }
  }
}

class _BackupExportOptions {
  const _BackupExportOptions({this.store, this.day});
  final String? store;
  final String? day;
}

/// Lets the user narrow a backup export to one store and/or one date --
/// without this, sharing a backup always dumped every store, every date,
/// every machine, which made a single day's worth of data hard to isolate.
class _BackupExportDialog extends StatefulWidget {
  const _BackupExportDialog({
    required this.records,
    this.title = 'バックアップの範囲を選択',
  });
  final List<SlotRecord> records;
  final String title;
  @override
  State<_BackupExportDialog> createState() => _BackupExportDialogState();
}

class _BackupExportDialogState extends State<_BackupExportDialog> {
  String? _store;
  String? _day;

  @override
  Widget build(BuildContext context) {
    final storeRecords = widget.records
        .where((r) => _store == null || r.store == _store)
        .toList();
    final days = storeRecords.map((r) => r.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    if (_day != null && !days.contains(_day)) _day = null;
    return AlertDialog(
      title: Text(widget.title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          DropdownButtonFormField<String?>(
            initialValue: _store,
            decoration: const InputDecoration(labelText: '店舗'),
            items: [
              const DropdownMenuItem(value: null, child: Text('すべての店舗')),
              ...storeNames.entries.map(
                (e) => DropdownMenuItem(value: e.key, child: Text(e.value)),
              ),
            ],
            onChanged: (v) => setState(() {
              _store = v;
              _day = null;
            }),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String?>(
            initialValue: _day,
            decoration: const InputDecoration(labelText: '日付'),
            items: [
              const DropdownMenuItem(value: null, child: Text('すべての日付')),
              ...days.map((d) => DropdownMenuItem(value: d, child: Text(d))),
            ],
            onChanged: (v) => setState(() => _day = v),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('キャンセル'),
        ),
        FilledButton(
          onPressed: () =>
              Navigator.of(context)
                  .pop(_BackupExportOptions(store: _store, day: _day)),
          child: const Text('書き出す'),
        ),
      ],
    );
  }
}

Future<void> _importBackup(
  BuildContext context,
  AppController controller,
) async {
  final picked = await FilePicker.pickFile(
    type: FileType.custom,
    allowedExtensions: ['json'],
  );
  final path = picked?.path;
  if (path == null) return;
  try {
    final text = await File(path).readAsString();
    final plan = await controller.importBackup(text);
    if (context.mounted && plan.conflicts.isNotEmpty) {
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => BackupConflictsPage(
            conflicts: plan.conflicts,
            onApply: controller.applyBackupOverrides,
          ),
        ),
      );
    }
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '新規${plan.added.length}件、グラフ追加${plan.graphOnly.length}件、設定情報追加${plan.settingOnly.length}件を取り込みました'
            '（要確認${plan.conflicts.length}件、対象外${plan.skipped}件）。',
          ),
        ),
      );
    }
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('バックアップを読み込めませんでした：$error')));
    }
  }
}

class BackupConflictsPage extends StatefulWidget {
  const BackupConflictsPage({
    super.key,
    required this.conflicts,
    required this.onApply,
  });

  final List<BackupConflict> conflicts;
  final Future<void> Function(List<SlotRecord>) onApply;

  @override
  State<BackupConflictsPage> createState() => _BackupConflictsPageState();
}

class _BackupConflictsPageState extends State<BackupConflictsPage> {
  late final _selected = List<bool>.filled(widget.conflicts.length, false);
  var _saving = false;

  Future<void> _apply() async {
    final chosen = [
      for (var i = 0; i < widget.conflicts.length; i++)
        if (_selected[i]) widget.conflicts[i].incoming,
    ];
    setState(() => _saving = true);
    await widget.onApply(chosen);
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('バックアップの不一致を確認')),
    body: ListView(
      // 端末の下部バー（ホームボタン等）に最後の行が隠れないように余白を足す
      padding: EdgeInsets.fromLTRB(
        16,
        12,
        16,
        24 + MediaQuery.of(context).viewPadding.bottom,
      ),
      children: [
        const Text('数値または設定情報が一致しない記録があります。取り込んだ内容を使う場合だけチェックしてください。'),
        const SizedBox(height: 12),
        for (var i = 0; i < widget.conflicts.length; i++)
          _ConflictCard(
            conflict: widget.conflicts[i],
            value: _selected[i],
            onChanged: (v) => setState(() => _selected[i] = v ?? false),
          ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _saving ? null : _apply,
          child: Text(_saving ? '保存中…' : 'チェックした内容で上書きして保存'),
        ),
      ],
    ),
  );
}

class _ConflictCard extends StatelessWidget {
  const _ConflictCard({
    required this.conflict,
    required this.value,
    required this.onChanged,
  });
  final BackupConflict conflict;
  final bool value;
  final ValueChanged<bool?> onChanged;

  @override
  Widget build(BuildContext context) {
    final local = conflict.local;
    final incoming = conflict.incoming;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${storeNames[local.store] ?? local.store}｜${local.day}｜'
              '${local.machine}｜${local.rack}番台',
              style: const TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 6),
            Text('総回転数：保存済み ${local.games} → 取り込み ${incoming.games}'),
            Text('BIG：保存済み ${local.bb} → 取り込み ${incoming.bb}'),
            Text('REG：保存済み ${local.rb} → 取り込み ${incoming.rb}'),
            Text(
              '最大持玉：保存済み ${local.maxHold ?? '—'} → 取り込み ${incoming.maxHold ?? '—'}',
            ),
            Text(
              '設定情報：保存済み ${local.confirmedSetting ?? '—'} → 取り込み ${incoming.confirmedSetting ?? '—'}',
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: value,
              onChanged: onChanged,
              title: const Text('取り込んだ内容で上書きする'),
            ),
          ],
        ),
      ),
    );
  }
}

class ResultsPage extends StatefulWidget {
  const ResultsPage({super.key, required this.controller});
  final AppController controller;
  @override
  State<ResultsPage> createState() => _ResultsPageState();
}

class _ResultsPageState extends State<ResultsPage> {
  late String? store = widget.controller.lastStore;
  late String? day = widget.controller.lastDay;

  /// 表示中の機種。null のときは機種一覧を出す（機種が多いと、プルダウンから
  /// 探すより一覧で台数・平均点を見ながら選ぶ方が早いため）。
  late String? machine = widget.controller.lastMachine;

  // 得点計算は、その日の全台を1回だけ。機種を切り替えるたびに
  // 全台を計算し直さない（データが入れ替わったとき・店舗や日付を変えたときだけ再計算）。
  Object? _scoredFor;
  var _scoredByKey = <String, (SlotRecord, ScoreResult)>{};

  /// 台の並び順。既定は台番号順（サイトの一覧と見比べやすいため）。
  var byScore = false;

  /// 機種一覧の絞り込み（機種名の一部。ひらがな・半角カナでも一致する）。
  final _query = TextEditingController();

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  void _openRecord(SlotRecord record, ScoreResult? score) =>
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => SavedGraphPage(
            record: record,
            score: score,
            allRecords: widget.controller.records,
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final all = widget.controller.records;
    store ??= all.firstOrNull?.store ?? 'nagamachiminami';
    final storeRows = all.where((r) => r.store == store).toList();
    final days = storeRows.map((r) => r.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    if (!days.contains(day)) day = days.firstOrNull;
    final dayRows = storeRows.where((r) => r.day == day).toList();
    final machines = dayRows.map((r) => r.machine).toSet().toList()..sort();
    if (!machines.contains(machine)) machine = null;
    widget.controller.rememberSelection(store, day, machine);
    final scoredKey = (identityHashCode(all), store, day);
    if (_scoredFor != scoredKey) {
      _scoredByKey = {for (final r in dayRows) r.key: (r, scoreRecord(r, all))};
      _scoredFor = scoredKey;
    }
    final digest = [for (final r in dayRows) _scoredByKey[r.key]!];
    return PopScope(
      // 機種を開いているときの「戻る」は、アプリを閉じずに機種一覧へ戻す。
      canPop: machine == null,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) setState(() => machine = null);
      },
      child: RefreshIndicator(
        onRefresh: widget.controller.reload,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
          children: [
            if (widget.controller.message != null)
              Notice(text: widget.controller.message!),
            Row(
              children: [
                // 店舗は短い名前にして、日付が「2026-09」で切れないよう幅を回す。
                Expanded(
                  flex: 2,
                  child: storeDropdown(
                    store!,
                    (v) => setState(() {
                      store = v;
                      day = null;
                      machine = null;
                    }),
                    short: true,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  flex: 3,
                  child: DropdownButtonFormField<String>(
                    initialValue: day,
                    isExpanded: true,
                    decoration: const InputDecoration(labelText: '日付'),
                    items: days
                        .map((v) => DropdownMenuItem(value: v, child: Text(v)))
                        .toList(),
                    onChanged: (v) => setState(() {
                      day = v;
                      machine = null;
                    }),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            if (dayRows.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: '該当するデータがありません',
                body: '「取り込み」から一覧スクリーンショットを追加します。',
              )
            else if (machine == null)
              ..._machineList(digest)
            else
              ..._machineDetail(machines, all),
            if (day != null) ...[
              const SizedBox(height: 18),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: () => _deleteGroup(store!, day!, machine),
                  icon: const Icon(Icons.delete_sweep_outlined),
                  label: const Text('まとめて削除…'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// その日の機種一覧（1機種1行）と、その日のまとめ。
  List<Widget> _machineList(List<(SlotRecord, ScoreResult)> digest) {
    final summaries = summarizeMachines(digest);
    final shown = summaries
        .where((s) => machineMatches(s.machine, _query.text))
        .toList();
    return [
      Text(
        '機種を選ぶ　${summaries.length}機種・${digest.length}台',
        style: const TextStyle(fontSize: 13, color: AppColors.ash),
      ),
      const SizedBox(height: 6),
      if (summaries.length > 6) ...[
        MachineSearchField(
          controller: _query,
          onChanged: () => setState(() {}),
        ),
        const SizedBox(height: 8),
      ],
      MachineSummaryList(
        summaries: shown,
        onPick: (name) => setState(() {
          machine = name;
          byScore = false;
        }),
      ),
      const SizedBox(height: 14),
      DaySummaryCard(entries: digest, onPick: _openRecord),
    ];
  }

  /// 選んだ機種の台（1台1行の表）。前後の機種へはボタンで移れる。
  List<Widget> _machineDetail(List<String> machines, List<SlotRecord> all) {
    final index = machines.indexOf(machine!);
    final rows = [
      for (final r in all)
        if (r.store == store && r.day == day && r.machine == machine) r,
    ]..sort((a, b) => a.rack.compareTo(b.rack));
    // 翌日候補（仮）は当日の点数計算とは完全に別です。選択日までに
    // 保存した同一台・同一機種の当たり頻度傾向だけを使います。
    final provisionalCandidates = provisionalNextDayCandidates(rows, all);
    final scored = [for (final r in rows) _scoredByKey[r.key]!];
    if (byScore) {
      // 点数が出ていない台（保留）は最後にまとめる
      scored.sort((a, b) => (b.$2.total ?? -1).compareTo(a.$2.total ?? -1));
    }
    final totals = scored.map((e) => e.$2.total).whereType<double>().toList();
    final average = totals.isEmpty
        ? null
        : totals.reduce((a, b) => a + b) / totals.length;
    final best = scored
        .where((e) => e.$2.total != null)
        .fold<(SlotRecord, ScoreResult)?>(
          null,
          (value, e) =>
              value == null || e.$2.total! > value.$2.total! ? e : value,
        );
    void go(int to) => setState(() => machine = machines[to]);
    return [
      Row(
        children: [
          IconButton(
            tooltip: '機種一覧へ戻る',
            onPressed: () => setState(() => machine = null),
            icon: const Icon(Icons.arrow_back),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  machine!,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  '${index + 1} / ${machines.length}機種　${rows.length}台',
                  style: const TextStyle(fontSize: 12, color: AppColors.ash),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: '前の機種',
            onPressed: index > 0 ? () => go(index - 1) : null,
            icon: const Icon(Icons.chevron_left),
          ),
          IconButton(
            tooltip: '次の機種',
            onPressed: index < machines.length - 1 ? () => go(index + 1) : null,
            icon: const Icon(Icons.chevron_right),
          ),
        ],
      ),
      const SizedBox(height: 8),
      // 「最高」だけ2行になってカードの高さがそろわなかったので、
      // 台番号は小さな補足に回し、3枚の高さをそろえる。
      IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: MetricCard(label: '採点済み', value: '${totals.length}台'),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(
                label: '平均',
                value: average == null ? '—' : '${average.toStringAsFixed(1)}点',
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(
                label: '最高',
                value: best == null
                    ? '—'
                    : '${best.$2.total!.toStringAsFixed(1)}点',
                note: best == null ? null : '${best.$1.rack}番台',
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 14),
      Row(
        children: [
          SegmentedButton<bool>(
            style: const ButtonStyle(
              visualDensity: VisualDensity.compact,
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: false, label: Text('台番号順')),
              ButtonSegment(value: true, label: Text('点数順')),
            ],
            selected: {byScore},
            onSelectionChanged: (v) => setState(() => byScore = v.first),
          ),
          const Spacer(),
          const Text(
            'タップで詳細',
            style: TextStyle(fontSize: 12, color: AppColors.ash),
          ),
        ],
      ),
      const SizedBox(height: 8),
      RackTable(entries: scored, onTap: _openRecord),
      const SizedBox(height: 14),
      ProvisionalCandidatesCard(
        total: provisionalCandidates.total,
        eligible: provisionalCandidates.eligible,
        candidates: provisionalCandidates.candidates,
        onPick: (record) => _openRecord(record, _scoredByKey[record.key]?.$2),
      ),
    ];
  }

  /// 取り込みミスなどを、機種ごと・日付ごとにまとめて削除する。
  /// 範囲を選ぶ → 確認 → 削除。削除後は「元に戻す」で1回分だけ戻せる。
  Future<void> _deleteGroup(String store, String day, String? machine) async {
    final all = widget.controller.records;
    final shop = storeNames[store] ?? store;
    int count({String? store, String? machine}) =>
        recordsInGroup(all, day: day, store: store, machine: machine).length;
    final List<
      ({String label, String detail, String? store, String? machine, int count})
    >
    options = [
      if (machine != null)
        (
          label: 'この機種だけ',
          detail: '$shop　$day　$machine',
          store: store,
          machine: machine,
          count: count(store: store, machine: machine),
        ),
      (
        label: 'この店舗のこの日すべて',
        detail: '$shop　$day',
        store: store,
        machine: null,
        count: count(store: store),
      ),
      (
        label: '両店舗のこの日すべて',
        detail: day,
        store: null,
        machine: null,
        count: count(),
      ),
    ];
    final picked = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                '取り込みミスなどを、機種ごと・日付ごとに消します。消す範囲を選んでください（次に確認があります）。',
                style: TextStyle(fontSize: 13, color: AppColors.ash),
              ),
            ),
            for (var i = 0; i < options.length; i++)
              ListTile(
                enabled: options[i].count > 0,
                leading: const Icon(Icons.delete_outline),
                title: Text('${options[i].label}（${options[i].count}台）'),
                subtitle: Text(options[i].detail),
                onTap: () => Navigator.pop(sheetContext, i),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (picked == null || !mounted) return;
    final option = options[picked];
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('まとめて削除しますか？'),
        content: Text(
          '${option.detail}\nの記録${option.count}台を削除します。\n\n'
          '誤って消した場合は、すぐ後なら「元に戻す」（または取り込み画面の'
          '「直前の保存を取り消す」）で戻せます。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('キャンセル'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('削除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    final deleted = await widget.controller.deleteGroup(
      day: day,
      store: option.store,
      machine: option.machine,
    );
    if (!mounted || deleted == 0) return;
    messenger.showSnackBar(
      SnackBar(
        duration: const Duration(seconds: 8),
        content: Text('${option.detail} の記録を$deleted台削除しました。'),
        action: SnackBarAction(
          label: '元に戻す',
          onPressed: () => widget.controller.undoLastSave(),
        ),
      ),
    );
  }
}

/// A deliberately conservative, visible trial. Candidates are a small list
/// derived solely from past same-rack hit-frequency tendencies. They never
/// influence the 100-point daily result.
class ProvisionalCandidatesCard extends StatelessWidget {
  const ProvisionalCandidatesCard({
    super.key,
    required this.total,
    required this.eligible,
    required this.candidates,
    required this.onPick,
  });

  final int total;
  final int eligible;
  final List<ProvisionalCandidate> candidates;
  final void Function(SlotRecord record) onPick;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                '翌日候補（仮）',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 3,
                ),
                decoration: BoxDecoration(
                  color: AppColors.pebble,
                  borderRadius: BorderRadius.circular(980),
                ),
                child: const Text(
                  '試験中',
                  style: TextStyle(fontSize: 11, color: AppColors.ash),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // 何の数字かを最初に書く。「50が中立」という前提が伝わらないと
          // 「63 / 100」だけでは読めないため、差分（平均より+13）で出す。
          const Text(
            'この機種で、過去に当たりが周りの台より軽かった台です。'
            '明日どの台から見るかの参考用で、今日の合計点には影響しません。',
            style: TextStyle(color: AppColors.ash, fontSize: 13, height: 1.45),
          ),
          const SizedBox(height: 10),
          if (candidates.isEmpty)
            Text(
              'まだ判定できません。過去の実績から傾向を出せた台が$total台中$eligible台です'
              '（4台以上で表示）。同じ台・同じ機種のデータが3日分たまると傾向を出せます。',
              style: const TextStyle(
                color: AppColors.ash,
                fontSize: 13,
                height: 1.45,
              ),
            )
          else ...[
            ...candidates.map(
              (candidate) => ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                onTap: () => onPick(candidate.record),
                title: Text(
                  '${candidate.record.rack}番台',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                subtitle: Text(
                  '当たりの軽さ ${signedIndex(candidate.index)}'
                  '・過去${candidate.days}日分',
                ),
                trailing: const Icon(Icons.chevron_right),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              '傾向を出せた$total台中$eligible台から、上位${candidates.length}台。'
              '「平均より」は、同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。',
              style: const TextStyle(
                color: AppColors.ash,
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ],
          const SizedBox(height: 8),
          const Text(
            '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。',
            style: TextStyle(color: AppColors.ash, fontSize: 12, height: 1.45),
          ),
        ],
      ),
    ),
  );
}

/// 50を中立とした過去傾向の指数を「平均より +13」の形にする。
/// 素の「63 / 100」では、50が中立であることも、上下どちらが良いのかも
/// 画面から読み取れないため。
String signedIndex(double index) {
  final delta = index - 50;
  final sign = delta >= 0 ? '+' : '-';
  return '平均より $sign${delta.abs().toStringAsFixed(0)}';
}

/// Top racks of the selected store and date across every machine, plus how
/// complete the day is. Tapping a row opens that rack's graph and hit details.
class DaySummaryCard extends StatelessWidget {
  const DaySummaryCard({
    super.key,
    required this.entries,
    required this.onPick,
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord, ScoreResult) onPick;

  @override
  Widget build(BuildContext context) {
    final scored = entries.where((e) => e.$2.total != null).toList()
      ..sort((a, b) => b.$2.total!.compareTo(a.$2.total!));
    final provisional = scored.where((e) => e.$2.provisional).length;
    final noGraph = entries.where((e) => e.$1.graph == null).length;
    final odd = suspiciousDuplicates(entries.map((e) => e.$1));
    final missingByMachine = <String, List<int>>{};
    for (final e in entries.where((e) => e.$1.graph == null)) {
      missingByMachine.putIfAbsent(e.$1.machine, () => []).add(e.$1.rack);
    }
    for (final racks in missingByMachine.values) {
      racks.sort();
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'この日のまとめ',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 4),
            Text(
              '${entries.length}台　合計点確定${scored.length}台（暫定$provisional台）'
              '　保留${entries.length - scored.length}台　グラフ未取得$noGraph台',
              style: const TextStyle(color: AppColors.ash, fontSize: 13),
            ),
            const SizedBox(height: 8),
            if (scored.isEmpty)
              const Text(
                '合計点が確定した台はまだありません。',
                style: TextStyle(color: AppColors.ash),
              ),
            if (odd.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  '⚠ 要確認：数値（回転・BIG・REG）が完全に同じ台 — '
                  '${odd.map((g) => '${g.$1} ${g.$2.join('・')}番台').join('、')}。'
                  '台番号のずれで別の台のデータが保存された可能性があります。',
                  style: const TextStyle(fontSize: 13),
                ),
              ),
            if (missingByMachine.isNotEmpty)
              Theme(
                data: Theme.of(context)
                    .copyWith(dividerColor: Colors.transparent),
                child: ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  childrenPadding: EdgeInsets.zero,
                  title: Text(
                    'グラフ未取得の台（$noGraph台）',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  children: [
                    for (final entry in missingByMachine.entries)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Text(
                            '${entry.key}　${entry.value.length}台：${entry.value.join('、')}',
                          ),
                        ),
                      ),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '「取り込み」のブラウザで各台のグラフを取り込むと、この一覧から消えます。',
                        style: TextStyle(color: AppColors.ash, fontSize: 12),
                      ),
                    ),
                    const SizedBox(height: 8),
                  ],
                ),
              ),
            for (final e in scored.take(5))
              InkWell(
                onTap: () => onPick(e.$1, e.$2),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(
                    children: [
                      // 台番号は必ず出す。長い機種名の方を縮める
                      // （以前は機種名に押し出されて「710…」と切れていた）。
                      Expanded(
                        child: Text(
                          e.$1.machine,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '${e.$1.rack}番台',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(width: 8),
                      ScorePill(
                        text:
                            '${e.$2.provisional ? '暫定 ' : ''}${e.$2.total!.toStringAsFixed(1)}',
                        tier: scoreTier(e.$2.total),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class ImportPage extends StatelessWidget {
  const ImportPage({super.key, required this.controller});
  final AppController controller;

  /// Opens the in-app browser for importing. Shared by the button below and the
  /// launcher-icon shortcut ("取り込みを始める"), which has no widget context.
  static Future<void> openBrowser(
    NavigatorState navigator,
    AppController controller,
  ) async {
    await navigator.push<void>(
      MaterialPageRoute(
        builder: (_) => WebImportPage(
          onSave: (extraction) => controller.saveTable(
            extraction.store ?? 'nagamachiminami',
            extraction.day ?? todayIso(),
            extraction.machine ?? '',
            extraction.rows,
          ),
          onNext: controller.nextUngraphed,
          onUndo: controller.undoLastSave,
          onProgress: controller.progressText,
          onMachineStatus: controller.machineStatuses,
          skipTableReview: () => controller.skipTableReview,
          onGraph: (browserContext, captured) async {
            final analysis = controller.resolveWebGraph(captured);
            if (!browserContext.mounted) return false;
            final graph = analysis.graph;
            if (graph == null ||
                graph.points.length != 4 ||
                analysis.store == null ||
                analysis.day == null ||
                analysis.machine == null ||
                analysis.machine!.trim().isEmpty ||
                analysis.rack == null ||
                analysis.games == null ||
                analysis.bb == null ||
                analysis.rb == null) {
              ScaffoldMessenger.of(browserContext).showSnackBar(
                const SnackBar(content: Text('グラフまたは台データを読み取れませんでした。保存しません。')),
              );
              return false;
            }
            await controller.saveGraph(
              store: analysis.store!,
              day: analysis.day!,
              machine: analysis.machine!,
              rack: analysis.rack!,
              games: analysis.games!,
              bb: analysis.bb!,
              rb: analysis.rb!,
              maxHold: analysis.maxHold,
              points: graph.points,
              previewPng: graph.previewPng,
              previewWidth: graph.width,
              previewHeight: graph.height,
              curve: graph.curveAsPairs,
              returnToBrowser: true,
            );
            // 「◯番台を保存しました」は取り込み画面の上部に出す（下に出すと
            // 取り込みボタンに重なって操作の邪魔になるため）。
            return true;
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '表とグラフを取り込む',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                const Text('店・機種・日付を選んで一覧を保存し、そのまま個別グラフを採点できます。'),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: () => ImportPage.openBrowser(
                      Navigator.of(context),
                      controller,
                    ),
                    icon: const Icon(Icons.table_chart_outlined),
                    label: const Text('アプリ内ブラウザを開く'),
                  ),
                ),
                const SizedBox(height: 6),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: controller.skipTableReview,
                  onChanged: controller.setSkipTableReview,
                  title: const Text('表の確認画面を省く'),
                  subtitle: const Text(
                    '一覧はサイトの表をそのまま読むので、確認なしで保存します。'
                    '店舗・日付・機種名を読み取れなかったときだけ確認画面が出ます。',
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  '機種一覧・機種別の表・個別台グラフで「この画面を取り込む」を押してください。',
                  style: TextStyle(fontSize: 12),
                ),
              ],
            ),
          ),
        ),
        if (controller.message != null) ...[
          const SizedBox(height: 12),
          Notice(text: controller.message!),
        ],
      ],
    );
  }
}

class TableReview extends StatefulWidget {
  const TableReview({
    super.key,
    required this.controller,
    required this.analysis,
  });
  final AppController controller;
  final CaptureAnalysis analysis;
  @override
  State<TableReview> createState() => _TableReviewState();
}

class _TableReviewState extends State<TableReview> {
  late String store;
  late final TextEditingController day;
  late final TextEditingController machine;
  late List<RowControllers> rows;

  @override
  void initState() {
    super.initState();
    store = widget.analysis.store ?? 'nagamachiminami';
    day = TextEditingController(text: widget.analysis.day ?? todayIso());
    machine = TextEditingController(text: widget.analysis.machine ?? '');
    rows = widget.analysis.rows.map(RowControllers.fromEditable).toList();
  }

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '一覧OCR結果　${rows.length}台',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text('誤読があれば直してから保存してください。'),
          const SizedBox(height: 14),
          IdentityFields(
            store: store,
            onStore: (v) => setState(() => store = v),
            day: day,
            machine: machine,
          ),
          const SizedBox(height: 12),
          if (rows.isEmpty)
            const Text('行を認識できませんでした。「1台追加」から入力できます。')
          else
            ...rows.asMap().entries.map(
              (entry) => EditableRowCard(
                index: entry.key,
                row: entry.value,
                onDelete: () => setState(() => rows.removeAt(entry.key)),
              ),
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => setState(() => rows.add(RowControllers.empty())),
              icon: const Icon(Icons.add),
              label: const Text('1台追加'),
            ),
          ),
          SizedBox(
            width: double.infinity,
            child: FilledButton(onPressed: save, child: const Text('この内容で保存')),
          ),
        ],
      ),
    ),
  );

  Future<void> save() async {
    try {
      final parsed = rows.map((r) => r.value()).toList();
      if (machine.text.trim().isEmpty || parsed.isEmpty)
        throw const FormatException('機種名と1台以上のデータが必要です。');
      DateTime.parse(day.text.trim());
      await widget.controller.saveTable(
        store,
        day.text.trim(),
        machine.text.trim(),
        parsed,
      );
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('入力を確認してください：$error')));
    }
  }
}

class GraphReview extends StatefulWidget {
  const GraphReview({
    super.key,
    required this.controller,
    required this.analysis,
    this.returnToBrowser = false,
  });
  final AppController controller;
  final CaptureAnalysis analysis;
  final bool returnToBrowser;
  @override
  State<GraphReview> createState() => _GraphReviewState();
}

class _GraphReviewState extends State<GraphReview> {
  late String store;
  late final TextEditingController day, machine, rack, games, bb, rb, maxHold;
  late List<Offset> points;
  late final List<Offset> automaticPoints;
  int selected = 3;
  var _saving = false;
  static const pointLabels = ['ゼロ線', '最高点', '最低点', '終点'];
  static const pointColors = [
    Colors.red,
    Colors.amber,
    Colors.cyan,
    Colors.green,
  ];

  @override
  void initState() {
    super.initState();
    final a = widget.analysis;
    store = a.store ?? 'nagamachiminami';
    day = TextEditingController(text: a.day ?? todayIso());
    machine = TextEditingController(text: a.machine ?? '');
    rack = TextEditingController(text: a.rack?.toString() ?? '');
    games = TextEditingController(text: a.games?.toString() ?? '');
    bb = TextEditingController(text: a.bb?.toString() ?? '');
    rb = TextEditingController(text: a.rb?.toString() ?? '');
    maxHold = TextEditingController(text: a.maxHold?.toString() ?? '');
    automaticPoints = List.of(a.graph!.points);
    points = List.of(automaticPoints);
  }

  @override
  Widget build(BuildContext context) {
    final graph = widget.analysis.graph!;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'グラフ確認',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 4),
            const Text('色を選び、位置が違う場合はグラフをタップして直します。'),
            const SizedBox(height: 10),
            Wrap(
              spacing: 6,
              children: List.generate(
                4,
                (i) => ChoiceChip(
                  label: Text('${i + 1} ${pointLabels[i]}'),
                  selected: selected == i,
                  avatar: CircleAvatar(
                    backgroundColor: pointColors[i],
                    radius: 6,
                  ),
                  onSelected: (_) => setState(() => selected = i),
                ),
              ),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: () =>
                    setState(() => points = List.of(automaticPoints)),
                icon: const Icon(Icons.restart_alt),
                label: const Text('自動点に戻す'),
              ),
            ),
            const SizedBox(height: 8),
            AspectRatio(
              aspectRatio: graph.width / graph.height,
              child: LayoutBuilder(
                builder: (context, box) => GestureDetector(
                  onTapDown: (event) {
                    final x =
                        event.localPosition.dx / box.maxWidth * graph.width;
                    final y =
                        event.localPosition.dy / box.maxHeight * graph.height;
                    setState(
                      () => points = List.of(points)..[selected] = Offset(x, y),
                    );
                  },
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.memory(
                        graph.previewPng,
                        fit: BoxFit.fill,
                        filterQuality: FilterQuality.medium,
                      ),
                      CustomPaint(
                        painter: PointPainter(
                          points,
                          graph.width.toDouble(),
                          graph.height.toDouble(),
                          pointColors,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),
            IdentityFields(
              store: store,
              onStore: (v) => setState(() => store = v),
              day: day,
              machine: machine,
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                numberField('台番号', rack, 105),
                numberField('総回転数', games, 120),
                numberField('BIG', bb, 90),
                numberField('REG', rb, 90),
                numberField('最大持玉', maxHold, 120),
              ],
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: save,
                icon: const Icon(Icons.check),
                label: const Text('採点を確定して保存'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> save() async {
    if (_saving) return;
    try {
      DateTime.parse(day.text.trim());
      if (machine.text.trim().isEmpty) throw const FormatException('機種名が必要です。');
      int read(TextEditingController c) => int.parse(c.text.trim());
      setState(() => _saving = true);
      await widget.controller.saveGraph(
        store: store,
        day: day.text.trim(),
        machine: machine.text.trim(),
        rack: read(rack),
        games: read(games),
        bb: read(bb),
        rb: read(rb),
        maxHold: read(maxHold),
        points: points,
        previewPng: widget.analysis.graph!.previewPng,
        previewWidth: widget.analysis.graph!.width,
        previewHeight: widget.analysis.graph!.height,
        curve: widget.analysis.graph!.curveAsPairs,
        returnToBrowser: widget.returnToBrowser,
      );
      if (widget.returnToBrowser && mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('入力を確認してください：$error')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}

class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key, required this.controller});
  final AppController controller;
  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  String store = '';

  /// 種別の絞り込み。ノーマルタイプ（ジャグラー・ハナハナ）はBB/RBから設定候補を
  /// 出せるので、系列でまとめて見比べられるようにしている。
  /// null は「すべての種別」。
  HistoryType? type;

  /// 機種名の絞り込み（一部一致。ひらがな・半角カナでも一致する）。
  /// 機種が多くプルダウンでは探しにくいため、文字で絞る。
  final _query = TextEditingController();

  // 得点は、データが変わったときだけ計算し直す（絞り込みを変えても同じ台の点は同じ）。
  // 画面を組み立て直すたびに全記録を採点し直すと、記録が増えるほど待たされる。
  Object? _scoredFor;
  var _scoredByKey = <String, ScoreResult>{};

  ScoreResult _score(SlotRecord row, List<SlotRecord> all) =>
      _scoredByKey[row.key] ??= scoreRecord(row, all);

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final all = widget.controller.records;
    final days = groupHistoryByDay(
      all.where(
        (r) =>
            (store.isEmpty || r.store == store) &&
            (type?.matches(r.machine) ?? true) &&
            machineMatches(r.machine, _query.text),
      ),
    );
    if (_scoredFor != identityHashCode(all)) {
      _scoredByKey = {};
      _scoredFor = identityHashCode(all);
    }
    // 日付ごとのカードは数が増え続けるので、画面に出ている分だけ組み立てる。
    // （以前は全部まとめて作っていたため、記録が増えるほど開くのが遅くなった）
    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
      itemCount: 1 + (days.isEmpty ? 1 : days.length),
      itemBuilder: (context, index) {
        if (index == 0) return _filters();
        if (days.isEmpty) {
          return all.isEmpty
              ? const EmptyState(
                  icon: Icons.history,
                  title: '記録がありません',
                  body: 'スクリーンショットを取り込むと日付別に残ります。',
                )
              : const EmptyState(
                  icon: Icons.search_off,
                  title: '条件に合う記録がありません',
                  body: '店舗・種別・機種名の絞り込みを変えてください。',
                );
        }
        final (day, groups) = days[index - 1];
        return _day(day, groups, all);
      },
    );
  }

  /// 絞り込み。スマホの幅でも2段に収める（以前は3段で画面の上を占めていた）。
  Widget _filters() => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Column(
      children: [
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: store,
                isExpanded: true,
                decoration: const InputDecoration(labelText: '店舗'),
                items: [
                  const DropdownMenuItem(value: '', child: Text('すべて')),
                  ...storeNames.keys.map(
                    (key) => DropdownMenuItem(
                      value: key,
                      child: Text(storeShortName(key)),
                    ),
                  ),
                ],
                onChanged: (v) => setState(() => store = v ?? ''),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: DropdownButtonFormField<HistoryType?>(
                initialValue: type,
                isExpanded: true,
                decoration: const InputDecoration(labelText: '種別'),
                items: [
                  const DropdownMenuItem(value: null, child: Text('すべて')),
                  ...HistoryType.values.map(
                    (v) => DropdownMenuItem(
                      value: v,
                      child: Text(v.label, overflow: TextOverflow.ellipsis),
                    ),
                  ),
                ],
                onChanged: (v) => setState(() => type = v),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        MachineSearchField(
          controller: _query,
          onChanged: () => setState(() {}),
        ),
      ],
    ),
  );

  /// 1日ぶん：日付の見出しと、機種ごとの1行。
  Widget _day(String day, List<HistoryGroup> groups, List<SlotRecord> all) {
    final racks = groups.fold<int>(0, (sum, g) => sum + g.rows.length);
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 6),
            child: Row(
              children: [
                Text(
                  dayWithWeekday(day),
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const Spacer(),
                Text(
                  '${groups.length}機種・$racks台',
                  style: const TextStyle(fontSize: 12, color: AppColors.ash),
                ),
              ],
            ),
          ),
          Card(
            clipBehavior: Clip.antiAlias,
            child: Column(
              children: [
                for (var i = 0; i < groups.length; i++) ...[
                  if (i > 0) const Divider(height: 1),
                  _groupRow(groups[i], all),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _groupRow(HistoryGroup group, List<SlotRecord> all) {
    final totals = [for (final r in group.rows) _score(r, all).total]
        .whereType<double>()
        .toList();
    final average = totals.isEmpty
        ? null
        : totals.reduce((a, b) => a + b) / totals.length;
    final settings = group.rows.where((r) => r.confirmedSetting != null).length;
    return InkWell(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => HistoryGroupPage(
            controller: widget.controller,
            day: group.day,
            store: group.store,
            machine: group.machine,
          ),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    group.machine,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    [
                      storeShortName(group.store),
                      '${group.rows.length}台',
                      if (settings > 0) '設定情報$settings台',
                    ].join('・'),
                    style: const TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            AverageBadge(average: average),
            const Icon(Icons.chevron_right, color: AppColors.mist),
          ],
        ),
      ),
    );
  }
}

/// 過去の記録で1行（ある日・ある店舗・ある機種）を開いた画面。
/// 台は表で並べ、タップでグラフ、長押しで設定情報の記録・削除。
class HistoryGroupPage extends StatefulWidget {
  const HistoryGroupPage({
    super.key,
    required this.controller,
    required this.day,
    required this.store,
    required this.machine,
  });
  final AppController controller;
  final String day, store, machine;

  @override
  State<HistoryGroupPage> createState() => _HistoryGroupPageState();
}

class _HistoryGroupPageState extends State<HistoryGroupPage> {
  var byScore = false;
  Object? _scoredFor;
  var _scored = <(SlotRecord, ScoreResult)>[];

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final all = widget.controller.records;
      if (_scoredFor != identityHashCode(all)) {
        _scored = [
          for (final r in all)
            if (r.day == widget.day &&
                r.store == widget.store &&
                r.machine == widget.machine)
              (r, scoreRecord(r, all)),
        ];
        _scoredFor = identityHashCode(all);
      }
      final entries = [..._scored]
        ..sort(
          (a, b) => byScore
              ? (b.$2.total ?? -1).compareTo(a.$2.total ?? -1)
              : a.$1.rack.compareTo(b.$1.rack),
        );
      final totals = entries.map((e) => e.$2.total).whereType<double>();
      final average = totals.isEmpty
          ? null
          : totals.reduce((a, b) => a + b) / totals.length;
      return Scaffold(
        appBar: AppBar(title: Text(dayWithWeekday(widget.day))),
        body: ListView(
          padding: EdgeInsets.fromLTRB(
            16,
            12,
            16,
            16 + MediaQuery.of(context).viewPadding.bottom,
          ),
          children: [
            Text(
              widget.machine,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
            Text(
              '${storeNames[widget.store] ?? widget.store}　'
              '${entries.length}台・平均 ${average?.toStringAsFixed(1) ?? '—'}点',
              style: const TextStyle(fontSize: 13, color: AppColors.ash),
            ),
            const SizedBox(height: 12),
            if (entries.isEmpty)
              const EmptyState(
                icon: Icons.inbox_outlined,
                title: '記録がありません',
                body: 'この日のこの機種の記録はすべて削除されました。',
              )
            else ...[
              Row(
                children: [
                  SegmentedButton<bool>(
                    style: const ButtonStyle(
                      visualDensity: VisualDensity.compact,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment(value: false, label: Text('台番号順')),
                      ButtonSegment(value: true, label: Text('点数順')),
                    ],
                    selected: {byScore},
                    onSelectionChanged: (v) =>
                        setState(() => byScore = v.first),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              const Text(
                'タップでグラフ、長押しで設定情報の記録・削除。',
                style: TextStyle(fontSize: 12, color: AppColors.ash),
              ),
              const SizedBox(height: 8),
              RackTable(
                entries: entries,
                onTap: (record, score) => Navigator.of(context).push(
                  MaterialPageRoute<void>(
                    builder: (_) => SavedGraphPage(
                      record: record,
                      score: score,
                      allRecords: widget.controller.records,
                    ),
                  ),
                ),
                onLongPress: _actions,
              ),
            ],
          ],
        ),
      );
    },
  );

  /// 1台ぶんの操作（設定情報の記録・削除）。
  Future<void> _actions(SlotRecord record) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
              child: Text(
                '${record.rack}番台　${record.games}G',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.verified_outlined),
              title: const Text('設定情報を記録'),
              subtitle: Text('現在：${record.confirmedSetting ?? '未入力'}'),
              onTap: () => Navigator.pop(sheetContext, 'setting'),
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline),
              title: const Text('この記録を削除'),
              onTap: () => Navigator.pop(sheetContext, 'delete'),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (!mounted) return;
    if (picked == 'setting') await _editConfirmedSetting(record);
    if (picked == 'delete') await _confirmDelete(record);
  }

  Future<void> _confirmDelete(SlotRecord record) async {
    final delete = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('記録を削除しますか？'),
        content: Text(
          '${record.day}\n${storeNames[record.store]}\n${record.machine}\n${record.rack}番台の記録を削除します。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('キャンセル'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('削除'),
          ),
        ],
      ),
    );
    if (delete == true) await widget.controller.deleteRecord(record);
  }

  Future<void> _editConfirmedSetting(SlotRecord record) async {
    var selected = record.confirmedSetting;
    final value = await showDialog<String>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('設定情報を記録'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${record.machine}\n${record.rack}番台'),
              const SizedBox(height: 8),
              const Text(
                '確定・根拠ありの情報だけを手入力で残します。採点には影響しません。',
                style: TextStyle(color: AppColors.ash, fontSize: 13),
              ),
              const SizedBox(height: 8),
              DropdownButtonFormField<String>(
                value: selected ?? '',
                decoration: const InputDecoration(labelText: '設定情報'),
                items: [
                  const DropdownMenuItem(value: '', child: Text('未入力（解除）')),
                  for (final option in confirmedSettingOptions)
                    DropdownMenuItem(value: option, child: Text(option)),
                ],
                onChanged: (value) => setDialogState(
                  () => selected = value?.isEmpty == true ? null : value,
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('キャンセル'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, selected ?? ''),
              child: const Text('保存'),
            ),
          ],
        ),
      ),
    );
    if (!mounted || value == null) return;
    await widget.controller.setConfirmedSetting(
      record,
      value.isEmpty ? null : value,
    );
  }
}

/// 機種名で絞り込む入力欄。ひらがな・半角カナでも一致する（[machineMatches]）。
class MachineSearchField extends StatelessWidget {
  const MachineSearchField({
    super.key,
    required this.controller,
    required this.onChanged,
  });
  final TextEditingController controller;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) => TextField(
    controller: controller,
    onChanged: (_) => onChanged(),
    textInputAction: TextInputAction.search,
    decoration: InputDecoration(
      isDense: true,
      prefixIcon: const Icon(Icons.search),
      hintText: '機種名で絞り込み（例：じゃぐらー）',
      suffixIcon: controller.text.isEmpty
          ? null
          : IconButton(
              tooltip: '絞り込みを消す',
              icon: const Icon(Icons.close),
              onPressed: () {
                controller.clear();
                onChanged();
              },
            ),
    ),
  );
}

/// 平均点の小さな表示（一覧の行の右端用）。
class AverageBadge extends StatelessWidget {
  const AverageBadge({super.key, required this.average});
  final double? average;

  @override
  Widget build(BuildContext context) => Column(
    mainAxisSize: MainAxisSize.min,
    crossAxisAlignment: CrossAxisAlignment.end,
    children: [
      const Text('平均', style: TextStyle(fontSize: 10, color: AppColors.ash)),
      ScorePill(
        compact: true,
        text: average?.toStringAsFixed(1) ?? '—',
        tier: scoreTier(average),
      ),
    ],
  );
}

/// 結果タブの機種一覧。1機種1行で、台数・平均点・最高点を並べる。
class MachineSummaryList extends StatelessWidget {
  const MachineSummaryList({
    super.key,
    required this.summaries,
    required this.onPick,
  });
  final List<MachineSummary> summaries;
  final void Function(String machine) onPick;

  @override
  Widget build(BuildContext context) {
    if (summaries.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Text(
          '機種名に一致する機種がありません。',
          style: TextStyle(color: AppColors.ash),
        ),
      );
    }
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (var i = 0; i < summaries.length; i++) ...[
            if (i > 0) const Divider(height: 1),
            InkWell(
              onTap: () => onPick(summaries[i].machine),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            summaries[i].machine,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            _detail(summaries[i]),
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.ash,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    AverageBadge(average: summaries[i].average),
                    const Icon(Icons.chevron_right, color: AppColors.mist),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  static String _detail(MachineSummary s) => [
    '${s.racks}台',
    if (s.best != null) '最高${s.best!.toStringAsFixed(1)}',
    if (s.noGraph > 0) 'グラフ未取得${s.noGraph}台',
  ].join('・');
}

/// 1台1行の表。台番号・回転・BIG・REG・最大持玉・点数を並べ、
/// 設定推測・設定情報・グラフ未取得の補足は、ある台だけ2行目に小さく出す。
/// 暫定点は表の上に1回だけ書く。
/// 以前は1台1枚の大きなカードで、20台並ぶと何画面も続いていた。
class RackTable extends StatelessWidget {
  const RackTable({
    super.key,
    required this.entries,
    required this.onTap,
    this.onLongPress,
  });
  final List<(SlotRecord, ScoreResult)> entries;
  final void Function(SlotRecord record, ScoreResult score) onTap;
  final void Function(SlotRecord record)? onLongPress;

  // 列の幅の比。狭い端末でも1行に収まるよう、数字は縮めて表示する。
  static const _flex = [3, 4, 3, 3, 4, 5];

  static Widget _cell(
    String text,
    int flex, {
    TextStyle? style,
    Alignment alignment = Alignment.centerRight,
  }) => Expanded(
    flex: flex,
    child: Align(
      alignment: alignment,
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: Text(text, maxLines: 1, style: style),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    const head = TextStyle(fontSize: 11, color: AppColors.ash);
    // 暫定点は、記録が少ないうちはほぼ全台に付く。各行には書かず、
    // 表の上に1回だけ断る。
    final provisional = entries
        .where((e) => e.$2.total != null && e.$2.provisional)
        .length;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          if (provisional > 0)
            Container(
              width: double.infinity,
              color: AppColors.ice,
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
              child: Text(
                provisional == entries.length
                    ? '点数はすべて暫定（少数データ・欠測を含む）'
                    : '$provisional台の点数は暫定（少数データ・欠測を含む）',
                style: const TextStyle(fontSize: 11, color: AppColors.ash),
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
            child: Row(
              children: [
                _cell(
                  '台',
                  _flex[0],
                  style: head,
                  alignment: Alignment.centerLeft,
                ),
                _cell('回転', _flex[1], style: head),
                _cell('BIG', _flex[2], style: head),
                _cell('REG', _flex[3], style: head),
                _cell('持玉', _flex[4], style: head),
                _cell('点', _flex[5], style: head),
              ],
            ),
          ),
          for (final (record, score) in entries) ...[
            const Divider(height: 1),
            InkWell(
              onTap: () => onTap(record, score),
              onLongPress: onLongPress == null
                  ? null
                  : () => onLongPress!(record),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
                child: Column(
                  children: [
                    Row(
                      children: [
                        _cell(
                          '${record.rack}',
                          _flex[0],
                          style: const TextStyle(fontWeight: FontWeight.w700),
                          alignment: Alignment.centerLeft,
                        ),
                        _cell('${record.games}', _flex[1]),
                        _cell('${record.bb}', _flex[2]),
                        _cell('${record.rb}', _flex[3]),
                        _cell('${record.maxHold ?? '—'}', _flex[4]),
                        Expanded(
                          flex: _flex[5],
                          child: Align(
                            alignment: Alignment.centerRight,
                            child: FittedBox(
                              fit: BoxFit.scaleDown,
                              child: ScorePill(
                                compact: true,
                                text: score.total?.toStringAsFixed(1) ?? '保留',
                                tier: scoreTier(score.total),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                    if (_note(record, score) case final note?)
                      Padding(
                        padding: const EdgeInsets.only(top: 3),
                        child: Align(
                          alignment: Alignment.centerLeft,
                          child: Text(
                            note,
                            style: const TextStyle(
                              fontSize: 11,
                              color: AppColors.ash,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  /// 2行目の補足。何も無い台は1行で済ませる。
  static String? _note(SlotRecord record, ScoreResult score) {
    final parts = [
      if (estimateSetting(record) case final estimate?) estimate.shortLabel,
      if (record.confirmedSetting case final setting?) '設定情報：$setting',
      if (record.graph == null) 'グラフ未取得',
    ];
    return parts.isEmpty ? null : parts.join('・');
  }
}

class SavedGraphPage extends StatelessWidget {
  const SavedGraphPage({
    super.key,
    required this.record,
    this.score,
    this.allRecords,
  });
  final SlotRecord record;
  final ScoreResult? score;
  final List<SlotRecord>? allRecords;

  @override
  Widget build(BuildContext context) {
    final graph = record.graph;
    return Scaffold(
      appBar: AppBar(title: Text('${record.rack}番台')),
      body: graph == null
          ? ListView(
              padding: EdgeInsets.fromLTRB(
                16,
                16,
                16,
                16 + MediaQuery.of(context).viewPadding.bottom,
              ),
              children: [
                RackStats(record: record, score: score),
                const SizedBox(height: 12),
                const EmptyState(
                  icon: Icons.show_chart,
                  title: 'グラフは未保存です',
                  body: 'この台は一覧だけが保存されています。',
                ),
                if (allRecords != null)
                  SlumpStrip(record: record, all: allRecords!),
                if (allRecords != null)
                  RackTrend(record: record, all: allRecords!),
              ],
            )
          : _SavedGraphBody(
              record: record,
              graph: graph,
              score: score,
              allRecords: allRecords,
            ),
    );
  }
}

/// Recent days of this rack (same machine): score, games and hit rate, so a
/// rack's habits are visible without opening each day.
class RackTrend extends StatelessWidget {
  const RackTrend({super.key, required this.record, required this.all});
  final SlotRecord record;
  final List<SlotRecord> all;

  @override
  Widget build(BuildContext context) {
    final trend = rackTrend(record, all);
    if (trend.length < 2) {
      return const Padding(
        padding: EdgeInsets.only(top: 12),
        child: Text(
          'この台の過去データ（同じ機種）はまだありません。',
          style: TextStyle(color: AppColors.ash, fontSize: 13),
        ),
      );
    }
    final forecast = nextDayIndex(record, all);
    final totals = trend.map((e) => e.$2.total).whereType<double>().toList();
    final average = totals.isEmpty
        ? ''
        : '（平均 ${(totals.reduce((a, b) => a + b) / totals.length).toStringAsFixed(1)}点）';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'この台の推移（同じ機種・直近${trend.length}日）$average',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              for (final (r, s) in trend)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      Expanded(child: Text(r.day)),
                      SizedBox(
                        width: 84,
                        child: Text(
                          s.total == null
                              ? '—'
                              : '${s.provisional ? '暫定 ' : ''}${s.total!.toStringAsFixed(1)}',
                          textAlign: TextAlign.right,
                          style: TextStyle(
                            fontWeight: FontWeight.w600,
                            color: r.day == record.day
                                ? AppColors.linkBlue
                                : null,
                          ),
                        ),
                      ),
                      SizedBox(
                        width: 70,
                        child: Text('${r.games}G', textAlign: TextAlign.right),
                      ),
                      SizedBox(
                        width: 72,
                        child: Text(
                          r.bb + r.rb > 0
                              ? '1/${(r.games / (r.bb + r.rb)).toStringAsFixed(1)}'
                              : '—',
                          textAlign: TextAlign.right,
                        ),
                      ),
                    ],
                  ),
                ),
              const SizedBox(height: 8),
              Text(
                forecast.index == null
                    ? 'この台の当たりの軽さ（過去傾向）：まだ判定できません'
                          '（同じ機種で${forecast.days}日分／3日分から判定）'
                    : 'この台の当たりの軽さ（過去傾向）：'
                          '${signedIndex(forecast.index!)}'
                          '（過去${forecast.days}日分・データ量${forecast.confidence}）\n'
                          '同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。'
                          '「翌日候補（仮）」の根拠に使っています。今日の合計点とは別で、'
                          '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。',
                style: const TextStyle(
                  color: AppColors.ash,
                  fontSize: 12,
                  height: 1.45,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Score, hit count and hit rate at a glance -- the numbers worth reading
/// next to the graph, without expanding a list card first.
class RackStats extends StatelessWidget {
  const RackStats({super.key, required this.record, this.score});
  final SlotRecord record;
  final ScoreResult? score;

  @override
  Widget build(BuildContext context) {
    final hits = record.bb + record.rb;
    final estimate = estimateSetting(record);
    final rate = hits > 0
        ? '1/${(record.games / hits).toStringAsFixed(1)}'
        : '—';
    final total = score?.total;
    Widget chip(String label, double? value) => Chip(
      label: Text('$label　${value == null ? '—' : value.toStringAsFixed(1)}'),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${record.day}　${storeNames[record.store]}',
          style: const TextStyle(color: AppColors.ash),
        ),
        const SizedBox(height: 2),
        Text(
          record.machine,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
        ),
        if (score != null) ...[
          const SizedBox(height: 10),
          Row(
            children: [
              ScorePill(
                text: total == null
                    ? '保留'
                    : '${score!.provisional ? '暫定 ' : ''}${total.toStringAsFixed(1)}',
                tier: scoreTier(total),
              ),
              const SizedBox(width: 10),
              const Text('合計点', style: TextStyle(color: AppColors.ash)),
            ],
          ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: MetricCard(label: '当たり回数', value: '$hits回'),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(label: '当たり確率', value: rate),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: MetricCard(label: '総回転', value: '${record.games}G'),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text('BIG ${record.bb}　REG ${record.rb}　最大持玉 ${record.maxHold ?? '—'}'),
        Text(
          '観測量（設定判別の信頼度ではありません）：${reliabilityLabel(record.games)}'
          '${capturedNote(record).isEmpty ? '' : '　｜　${capturedNote(record)}'}',
          style: const TextStyle(color: AppColors.ash, fontSize: 12),
        ),
        if (estimate != null) ...[
          const SizedBox(height: 8),
          Text(
            estimate.detailLabel,
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          const Text(
            'BB/RBのみ・各設定同じ事前重みで比較。実際の設定確率や翌日の予測ではありません。',
            style: TextStyle(color: AppColors.ash, fontSize: 12),
          ),
        ],
        if (score != null) ...[
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              chip('持玉 /20', score!.maxHold),
              chip('当り /60', score!.hits),
              chip('終点 /10', score!.positive),
              chip('維持 /10', score!.retention),
            ],
          ),
          Text(
            score!.reasons.join('・'),
            style: const TextStyle(color: AppColors.ash, fontSize: 12),
          ),
        ],
      ],
    );
  }
}

class _SavedGraphBody extends StatelessWidget {
  const _SavedGraphBody({
    required this.record,
    required this.graph,
    this.score,
    this.allRecords,
  });
  final SlotRecord record;
  final GraphMeasurement graph;
  final ScoreResult? score;
  final List<SlotRecord>? allRecords;

  @override
  Widget build(BuildContext context) {
    final hasImage = graph.previewPng != null;
    final values = [graph.baselineY, graph.peakY, graph.troughY, graph.endY];
    final width = (graph.previewWidth ?? 400).toDouble();
    final maxY = values.reduce((a, b) => a > b ? a : b);
    final height = math
        .max((graph.previewHeight ?? 400).toDouble(), maxY + 30)
        .toDouble();
    final points =
        hasImage &&
            graph.baselineX != null &&
            graph.peakX != null &&
            graph.troughX != null &&
            graph.endX != null
        ? [
            Offset(graph.baselineX!, graph.baselineY),
            Offset(graph.peakX!, graph.peakY),
            Offset(graph.troughX!, graph.troughY),
            Offset(graph.endX!, graph.endY),
          ]
        : [
            Offset(width * .06, graph.baselineY),
            Offset(width * .34, graph.peakY),
            Offset(width * .66, graph.troughY),
            Offset(width * .94, graph.endY),
          ];
    return ListView(
      padding: EdgeInsets.fromLTRB(
        16,
        16,
        16,
        16 + MediaQuery.of(context).viewPadding.bottom,
      ),
      children: [
        RackStats(record: record, score: score),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                AspectRatio(
                  aspectRatio: width / height,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (hasImage)
                        Image.memory(
                          graph.previewPng!,
                          fit: BoxFit.fill,
                          filterQuality: FilterQuality.medium,
                        )
                      else
                        CustomPaint(
                          painter: ReconstructedGraphPainter(
                            points: points,
                            sourceWidth: width,
                            sourceHeight: height,
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  hasImage
                      ? '保存時のグラフです。'
                      : '保存時の画像がないため、採点に使った4点から復元した概略グラフです。',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (allRecords != null) SlumpStrip(record: record, all: allRecords!),
        if (allRecords != null) RackTrend(record: record, all: allRecords!),
      ],
    );
  }
}

/// The last five days' graphs of this rack side by side (oldest on the left),
/// shown once five days have a saved graph. Each graph keeps its own vertical
/// scale -- the site auto-scales every day -- so it is the shape over the days,
/// not one cumulative medal count.
class SlumpStrip extends StatelessWidget {
  const SlumpStrip({super.key, required this.record, required this.all});
  final SlotRecord record;
  final List<SlotRecord> all;

  @override
  Widget build(BuildContext context) {
    final days = slumpDays(record, all);
    if (days.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${days.length}日間のスランプグラフ（左が古い日）',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 8),
              LayoutBuilder(
                builder: (context, constraints) {
                  // 5日分を横スクロールなしで一度に見渡せるよう、幅を等分する。
                  final tile = constraints.maxWidth / days.length;
                  return Row(
                    children: [
                      for (final r in days)
                        SizedBox(
                          width: tile,
                          child: Column(
                            children: [
                              SizedBox(
                                height: 96,
                                width: tile,
                                child: _SlumpTile(record: r),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                r.day.substring(5).replaceAll('-', '/'),
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.ash,
                                ),
                              ),
                              Text(
                                () {
                                  final total = scoreRecord(r, all).total;
                                  return total == null
                                      ? '—'
                                      : '${total.toStringAsFixed(1)}点';
                                }(),
                                style: const TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  );
                },
              ),
              const SizedBox(height: 6),
              const Text(
                '縦軸は日ごとに自動調整される相対形状です（日をまたいだ差枚の合計ではありません）。',
                style: TextStyle(color: AppColors.ash, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SlumpTile extends StatelessWidget {
  const _SlumpTile({required this.record});
  final SlotRecord record;

  @override
  Widget build(BuildContext context) {
    final graph = record.graph!;
    // 保存された画像は作った端末・時期で背景の暗さが違う（透明・黒・濃紺）。
    // 5日分の明るさを揃えるため、どのタイルも同じ背景色の上に描く。
    if (graph.previewPng != null) {
      return ColoredBox(
        color: _slumpBackground,
        child: Image.memory(
          graph.previewPng!,
          fit: BoxFit.fill,
          filterQuality: FilterQuality.medium,
        ),
      );
    }
    // 保存時の画像がない古い記録は、採点に使った4点から復元した概略で描く。
    final width = (graph.previewWidth ?? 400).toDouble();
    final height = math.max(
      (graph.previewHeight ?? 400).toDouble(),
      [
            graph.baselineY,
            graph.peakY,
            graph.troughY,
            graph.endY,
          ].reduce((a, b) => a > b ? a : b) +
          30,
    );
    return CustomPaint(
      painter: ReconstructedGraphPainter(
        points: [
          Offset(width * .06, graph.baselineY),
          Offset(width * .34, graph.peakY),
          Offset(width * .66, graph.troughY),
          Offset(width * .94, graph.endY),
        ],
        sourceWidth: width,
        sourceHeight: height,
        background: _slumpBackground,
      ),
    );
  }
}

const _slumpBackground = Color(0xFF0C0C10);

class ReconstructedGraphPainter extends CustomPainter {
  const ReconstructedGraphPainter({
    required this.points,
    required this.sourceWidth,
    required this.sourceHeight,
    this.background = AppColors.carbon,
  });
  final List<Offset> points;
  final double sourceWidth, sourceHeight;
  final Color background;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(Offset.zero & size, Paint()..color = background);
    Offset scale(Offset p) => Offset(
      p.dx / sourceWidth * size.width,
      p.dy / sourceHeight * size.height,
    );
    final baseline = scale(points.first).dy;
    canvas.drawLine(
      Offset(0, baseline),
      Offset(size.width, baseline),
      Paint()
        ..color = Colors.redAccent
        ..strokeWidth = 1.5,
    );
    final path = Path()..moveTo(0, baseline);
    for (final point in points.skip(1)) {
      final scaled = scale(point);
      path.lineTo(scaled.dx, scaled.dy);
    }
    path.lineTo(size.width, scale(points.last).dy);
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xffe8edf0)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
  }

  @override
  bool shouldRepaint(covariant ReconstructedGraphPainter oldDelegate) =>
      oldDelegate.points != points ||
      oldDelegate.sourceWidth != sourceWidth ||
      oldDelegate.sourceHeight != sourceHeight ||
      oldDelegate.background != background;
}

class PointPainter extends CustomPainter {
  const PointPainter(
    this.points,
    this.sourceWidth,
    this.sourceHeight,
    this.colors,
  );
  final List<Offset> points;
  final double sourceWidth, sourceHeight;
  final List<Color> colors;
  @override
  void paint(Canvas canvas, Size size) {
    for (var i = 0; i < points.length; i++) {
      final p = Offset(
        points[i].dx / sourceWidth * size.width,
        points[i].dy / sourceHeight * size.height,
      );
      canvas.drawCircle(p, 8, Paint()..color = Colors.white);
      canvas.drawCircle(p, 6, Paint()..color = colors[i]);
      final text = TextPainter(
        text: TextSpan(
          text: '${i + 1}',
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(canvas, p + const Offset(9, -18));
    }
  }

  @override
  bool shouldRepaint(covariant PointPainter oldDelegate) =>
      oldDelegate.points != points;
}

class RowControllers {
  RowControllers(
    this.rack,
    this.games,
    this.bb,
    this.rb,
    this.maxHold,
    this.previous,
  );
  factory RowControllers.fromEditable(EditableRow row) => RowControllers(
    TextEditingController(text: '${row.rack}'),
    TextEditingController(text: '${row.games}'),
    TextEditingController(text: '${row.bb}'),
    TextEditingController(text: '${row.rb}'),
    TextEditingController(text: row.maxHold?.toString() ?? ''),
    TextEditingController(text: row.previousStart?.toString() ?? '0'),
  );
  factory RowControllers.empty() => RowControllers(
    TextEditingController(),
    TextEditingController(),
    TextEditingController(),
    TextEditingController(),
    TextEditingController(),
    TextEditingController(text: '0'),
  );
  final TextEditingController rack, games, bb, rb, maxHold, previous;
  EditableRow value() => EditableRow(
    rack: int.parse(rack.text),
    games: int.parse(games.text),
    bb: int.parse(bb.text),
    rb: int.parse(rb.text),
    maxHold: int.parse(maxHold.text),
    previousStart: int.parse(previous.text),
  );
}

class EditableRowCard extends StatelessWidget {
  const EditableRowCard({
    super.key,
    required this.index,
    required this.row,
    required this.onDelete,
  });
  final int index;
  final RowControllers row;
  final VoidCallback onDelete;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: DecoratedBox(
      decoration: BoxDecoration(
        color: AppColors.ice,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          children: [
            Row(
              children: [
                Text(
                  '${index + 1}台目',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                IconButton(
                  onPressed: onDelete,
                  icon: const Icon(Icons.delete_outline),
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                numberField('台番号', row.rack, 95),
                numberField('G', row.games, 105),
                numberField('BIG', row.bb, 85),
                numberField('REG', row.rb, 85),
                numberField('最大持玉', row.maxHold, 110),
                numberField('前日最終', row.previous, 105),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}

class IdentityFields extends StatelessWidget {
  const IdentityFields({
    super.key,
    required this.store,
    required this.onStore,
    required this.day,
    required this.machine,
  });
  final String store;
  final ValueChanged<String> onStore;
  final TextEditingController day, machine;
  @override
  Widget build(BuildContext context) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      SizedBox(width: 280, child: storeDropdown(store, onStore)),
      SizedBox(
        width: 150,
        child: TextField(
          controller: day,
          decoration: const InputDecoration(labelText: '日付'),
        ),
      ),
      SizedBox(
        width: 330,
        child: TextField(
          controller: machine,
          decoration: const InputDecoration(labelText: '機種名'),
        ),
      ),
    ],
  );
}

/// 店舗のプルダウン。[short] は狭い場所用の短い名前（長町南・幸町）。
Widget storeDropdown(
  String value,
  ValueChanged<String> onChanged, {
  bool short = false,
}) => DropdownButtonFormField<String>(
  initialValue: value,
  isExpanded: true,
  decoration: const InputDecoration(labelText: '店舗'),
  items: storeNames.entries
      .map(
        (e) => DropdownMenuItem(
          value: e.key,
          child: Text(
            short ? storeShortName(e.key) : e.value,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      )
      .toList(),
  onChanged: (v) {
    if (v != null) onChanged(v);
  },
);

Widget numberField(
  String label,
  TextEditingController controller,
  double width,
) => SizedBox(
  width: width,
  child: TextField(
    controller: controller,
    keyboardType: TextInputType.number,
    decoration: InputDecoration(labelText: label, isDense: true),
  ),
);

class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    this.note,
  });
  final String label, value;

  /// 数字の下に小さく添える一言（例：最高点だった台番号）。
  final String? note;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(color: AppColors.ash, fontSize: 12),
          ),
          const SizedBox(height: 3),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          if (note != null)
            Text(
              note!,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: AppColors.ash, fontSize: 12),
            ),
        ],
      ),
    ),
  );
}

class Notice extends StatelessWidget {
  const Notice({super.key, required this.text});
  final String text;
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: AppColors.ice,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: AppColors.hairline),
    ),
    child: Row(
      children: [
        const Icon(Icons.info_outline, color: AppColors.linkBlue),
        const SizedBox(width: 8),
        Expanded(
          child: Text(text, style: const TextStyle(color: AppColors.carbon)),
        ),
      ],
    ),
  );
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.body,
  });
  final IconData icon;
  final String title, body;
  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        children: [
          Icon(icon, size: 42, color: AppColors.mist),
          const SizedBox(height: 10),
          Text(
            title,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 5),
          Text(body, textAlign: TextAlign.center),
        ],
      ),
    ),
  );
}

extension FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
