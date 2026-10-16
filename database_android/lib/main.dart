import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart'
    show RenderAbstractViewport, ScrollCacheExtent;
import 'package:quick_actions/quick_actions.dart';
import 'package:share_plus/share_plus.dart';

import 'app_controller.dart';
import 'android_record_page.dart';
import 'backup_service.dart';
import 'backup_destination.dart';
import 'data_checks.dart';
import 'daily_net_page.dart';
import 'date_events.dart';
import 'event_calendar_page.dart';
import 'database_service.dart';
import 'graph_preview.dart';
import 'import_service.dart' show graphNumbersNotShown;
import 'gradient_button.dart';
import 'juggler_capture_page.dart';
import 'list_views.dart';
import 'machine_sections.dart';
import 'models.dart';
import 'normal_type.dart';
import 'pscube_import_page.dart';
import 'pscube_store.dart';
import 'shared_widgets.dart';
import 'theme.dart';
import 'web_import_page.dart';
import 'picked_file.dart';
import 'storage_usage_page.dart';
import 'viewer_pages.dart' show ViewerDateBar, viewerDays;
import 'pscube_suffix.dart' show meruhenSuffixStores;
import 'pscube_suffix_page.dart';
import 'viewer_data.dart' show ViewerData;

// 翌日候補の「平均より +13」表示は machine_sections.dart へ移した。既存の
// 呼び出し元（テストを含む）がこのファイルから使えるよう公開し続ける。
export 'machine_sections.dart' show signedIndex;
export 'app_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final controller = AppController();
  try {
    await controller.initialize();
  } catch (error) {
    // 新しい版で作られたデータを古い版が書き換えないよう、ここで止める。
    // それ以外の失敗でも、真っ白な画面で固まらず理由を出す。
    runApp(
      StartupErrorApp(
        message: error is DatabaseTooNewException
            ? error.message
            : startupFailureText(controller.startupChanges, error),
        onExport: controller.database.exportRaw,
      ),
    );
    return;
  }
  controller.onNotice = (text) => messengerKey.currentState
    ?..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(content: Text(text), duration: const Duration(seconds: 10)),
    );
  runApp(DatabaseApp(controller: controller));
  _setUpLauncherShortcuts(controller);
}

/// 起動できないときに理由を出す画面。記録は書き換えない。
///
/// 非常用に、DBを読むだけで開いて記録をバックアップとして書き出し、共有
/// できる（アプリが開けないままでも、記録をPC版へ移せるように）。
class StartupErrorApp extends StatefulWidget {
  const StartupErrorApp({super.key, required this.message, this.onExport});
  final String message;
  final Future<({int records, int candidates, int events, int unreadable})>
  Function(File file)?
  onExport;

  @override
  State<StartupErrorApp> createState() => _StartupErrorAppState();
}

class _StartupErrorAppState extends State<StartupErrorApp> {
  var _busy = false;
  String? _result;

  Future<void> _export() async {
    final export = widget.onExport;
    if (export == null) return;
    setState(() {
      _busy = true;
      _result = null;
    });
    try {
      final file = await BackupService().newBackupFile();
      final written = await export(file);
      if (!await saveBackup(file)) {
        _result = '保存を取りやめました。端末の記録は残っています。';
        return;
      }
      _result =
          '${written.records}台・イベント${written.events}件・翌日候補の記録${written.candidates}件を書き出しました'
          '。'
          '${written.unreadable > 0 ? '読めないデータ${written.unreadable}件の元の内容を含む救出用ファイルです。通常の復元には使えません。ファイルと端末の記録を残して、修復を依頼してください。' : 'PC版で取り込めます。'}';
    } catch (error) {
      _result = '書き出せませんでした：$error';
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    theme: buildAppTheme(),
    home: Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(widget.message, textAlign: TextAlign.center),
                if (widget.onExport != null) ...[
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    onPressed: _busy ? null : _export,
                    icon: const Icon(Icons.ios_share),
                    label: Text(_busy ? '書き出し中…' : '記録を書き出す（非常用）'),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '端末の記録を読むだけで、書き換えません。',
                    style: TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
                if (_result != null) ...[
                  const SizedBox(height: 16),
                  Text(_result!, textAlign: TextAlign.center),
                ],
              ],
            ),
          ),
        ),
      ),
    ),
  );
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

final navigatorKey = GlobalKey<NavigatorState>();
final messengerKey = GlobalKey<ScaffoldMessengerState>();

class DatabaseApp extends StatelessWidget {
  const DatabaseApp({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) => GraphPreviewScope(
    previews: controller.previews,
    child: MaterialApp(
      navigatorKey: navigatorKey,
      scaffoldMessengerKey: messengerKey,
      debugShowCheckedModeBanner: false,
      title: 'database',
      theme: buildAppTheme(),
      home: AnimatedBuilder(
        animation: controller,
        builder: (context, _) => AppShell(controller: controller),
      ),
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
            onSelected: (value) => switch (value) {
              'export' => _shareBackup(context, controller),
              'import' => _importBackup(context, controller),
              'storage' => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const StorageUsagePage(),
                ),
              ),
              _ => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => TrashPage(controller: controller),
                ),
              ),
            },
            itemBuilder: (context) => [
              PopupMenuItem(
                value: 'export',
                child: Text(
                  'バックアップを保存（書き出し）\n全期間：${_lastExportText(controller.lastFullBackupExport)}',
                ),
              ),
              const PopupMenuItem(value: 'import', child: Text('バックアップを読み込む')),
              const PopupMenuItem(
                value: 'trash',
                child: Text('ゴミ箱（$trashDays日間）'),
              ),
              const PopupMenuItem(
                value: 'storage',
                child: Text('保存領域の内訳（見るだけ）'),
              ),
            ],
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (controller.tab == 0) _RetentionNotices(controller: controller),
            Expanded(child: pages[controller.tab]),
          ],
        ),
      ),
      // 下のタブの上にも、上のバーと同じ細い線を引く（影は使わない）。
      bottomNavigationBar: DecoratedBox(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: AppColors.hairline)),
        ),
        child: NavigationBar(
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

/// 「前回 9/26 23:40（1日前）」。まだ一度も書き出していなければ、その旨。
String _lastExportText(DateTime? last, [DateTime? now]) {
  if (last == null) return 'まだ書き出していません';
  now ??= DateTime.now();
  String two(int v) => v.toString().padLeft(2, '0');
  final days = DateTime(
    now.year,
    now.month,
    now.day,
  ).difference(DateTime(last.year, last.month, last.day)).inDays;
  final ago = days <= 0 ? '今日' : '$days日前';
  return '前回 ${last.month}/${last.day} ${two(last.hour)}:${two(last.minute)}（$ago）';
}

Future<void> _shareBackup(
  BuildContext context,
  AppController controller,
) async {
  final options = await showDialog<_BackupExportOptions>(
    context: context,
    builder: (_) =>
        _BackupExportDialog(records: controller.records, allowPscube: true),
  );
  if (options == null || !context.mounted) return;
  if (options.store == pscubeBackupChoice) {
    await _sharePscubeBackup(context);
    return;
  }
  try {
    final exported = await _withProgress(
      context,
      'バックアップを書き出しています',
      (progress) => controller.exportBackup(
        store: options.store,
        day: options.day,
        onProgress: (written) => progress('$written台'),
      ),
    );
    final file = exported.file;
    final savedToDestination = await saveBackup(file);
    if (!context.mounted) return;
    final summary =
        '${exported.records}台・イベント${exported.events}件・翌日候補の記録${exported.candidates}件'
        '${exported.unreadable > 0 ? '（読めないデータ${exported.unreadable}件の元の内容を含む救出用ファイル）' : ''}';
    if (!savedToDestination) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('保存を取りやめました（$summary）。バックアップ済みにはしていません。')),
      );
      return;
    }
    if (exported.unreadable > 0) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('救出用ファイルを書き出しました'),
          content: Text(
            '$summary。\n\n通常の復元には使えません。元のファイルと端末の記録を残して、データの修復を依頼してください。バックアップ済みの印は付けていません。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('閉じる'),
            ),
          ],
        ),
      );
      return;
    }
    // 保存先へ書き込めても、Googleドライブへのアップロード完了はアプリから分から
    // ない。全期間のバックアップは、保存できたと確かめてから印を付ける
    // （この印の後で、端末から古い記録を片付ける）。
    final saved = exported.full
        ? await showDialog<bool>(
            context: context,
            barrierDismissible: false,
            builder: (dialogContext) => AlertDialog(
              title: const Text('バックアップを保存できましたか？'),
              content: Text(
                '$summaryを書き出しました。\n\n'
                'Googleドライブなどへの保存が終わったら「保存できた」を押してください。'
                '押すと、$retentionDays日より前の記録を次の起動から端末で片付けてよい印になります。'
                '保存を取りやめた・失敗したときは「まだ」を押してください。',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: const Text('まだ'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(dialogContext, true),
                  child: const Text('保存できた'),
                ),
              ],
            ),
          )
        : true;
    if (saved == true) await controller.confirmBackupSaved(exported);
    if (!context.mounted) return;
    final failures = controller.candidateLogFailures;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          saved == true
              ? '$summaryを書き出しました'
                    '${failures > 0 ? '（翌日候補を記録できなかった保存が$failures回あります）' : ''}。'
              : '$summaryを書き出しました。保存できていないので、バックアップ済みにはしていません。',
        ),
      ),
    );
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('バックアップを保存できませんでした：$error')));
    }
  }
}

/// 時間のかかる処理の間、閉じられない進み具合の表示を出す。[task] には、
/// 表示を書き換える関数を渡す。
Future<T> _withProgress<T>(
  BuildContext context,
  String title,
  Future<T> Function(void Function(String text) progress) task,
) async {
  final text = ValueNotifier<String>('');
  final navigator = Navigator.of(context);
  var open = true;
  unawaited(
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => PopScope(
        canPop: false,
        child: AlertDialog(
          title: Text(title),
          content: Row(
            children: [
              const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: ValueListenableBuilder<String>(
                  valueListenable: text,
                  builder: (_, value, _) =>
                      Text(value.isEmpty ? 'お待ちください…' : value),
                ),
              ),
            ],
          ),
        ),
      ),
    ).whenComplete(() => open = false),
  );
  try {
    return await task((value) => text.value = value);
  } finally {
    if (open) navigator.pop();
    text.dispose();
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
    this.allowPscube = false,
  });
  final List<SlotRecord> records;
  final String title;

  /// 店舗の選択肢に P’s CUBE（専用の記録）を出す（バックアップのときだけ。CSVは対象外）。
  final bool allowPscube;
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
              if (widget.allowPscube)
                const DropdownMenuItem(
                  value: pscubeBackupChoice,
                  child: Text('P’s CUBE（専用の記録・全期間）'),
                ),
            ],
            onChanged: (v) => setState(() {
              _store = v;
              _day = null;
            }),
          ),
          const SizedBox(height: 12),
          if (widget.allowPscube) ...[
            const Text(
              '保存先はGoogle Driveの「database共有」を選んでください。次回は前回の保存場所を優先します。',
            ),
            const SizedBox(height: 12),
          ],
          if (_store == pscubeBackupChoice)
            const Text(
              'P’s CUBEの記録は、メルヘンとは別のファイル（pscube-backup-android-…）で全期間を書き出します。',
              style: TextStyle(fontSize: 12, color: AppColors.ash),
            )
          else
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
  // 選んだファイルの写し（アプリの一時置き場）は、読み終えたら消す（溜めない）。
  try {
    if (!context.mounted) return;
    await _importPickedBackup(context, controller, path);
  } finally {
    await discardPickedCopy(path);
  }
}

Future<void> _importPickedBackup(
  BuildContext context,
  AppController controller,
  String path,
) async {
  final pscube = await isPscubeBackupFile(File(path));
  if (!context.mounted) return;
  if (pscube) {
    await _importPscubeBackup(context, File(path));
    return;
  }
  try {
    // 大きなファイルも1行ずつ読む（全体を1つの文字列にしない）。中身を
    // 確かめてから1回で保存するので、途中で失敗しても何も保存されない。
    final result = await _withProgress(
      context,
      'バックアップを読み込んでいます',
      (progress) => controller.importBackup(File(path), onProgress: progress),
    );
    if (context.mounted && result.conflicts.isNotEmpty) {
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => BackupConflictsPage(
            conflicts: result.conflicts,
            onApply: (selected) async => controller.applyBackupOverrides(
              await result.readConflicts(selected),
            ),
          ),
        ),
      );
    }
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '新規${result.added}件、グラフ追加${result.graphOnly}件、設定情報追加${result.settingOnly}件、イベント${result.dateEventsAdded}件を取り込みました'
            '${result.dateEventConflicts > 0 ? 'イベント名の不一致${result.dateEventConflicts}件は既存値を維持。' : ''}'
            '（要確認${result.conflicts.length}件、対象外${result.skipped}件）。'
            '${result.temporary > 0 ? '$retentionDays日より前の${result.temporary}台は一時的な取り込みで、次にアプリを開いたときに片付けます。' : ''}',
          ),
        ),
      );
    }
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('バックアップを読み込めませんでした（何も保存していません）：$error')),
      );
    }
  }
}

/// ゴミ箱。消した記録と、上書きで外れた前の内容を$trashDays日間残す。
class TrashPage extends StatefulWidget {
  const TrashPage({super.key, required this.controller});
  final AppController controller;
  @override
  State<TrashPage> createState() => _TrashPageState();
}

class _TrashPageState extends State<TrashPage> {
  late Future<List<TrashBatch>> _batches = widget.controller.trashBatches();
  var _busy = false;

  Future<void> _restore(TrashBatch batch) async {
    final overwrite = batch.kind == TrashKind.overwrite;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('ゴミ箱から戻す'),
        content: Text(
          overwrite
              ? '「${batch.label}」の${batch.count}台を、この前の内容に戻します。'
                    '今の内容はゴミ箱に残ります。'
              : '「${batch.label}」の${batch.count}台を戻します。'
                    '今の記録がある台は戻しません。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('やめる'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('戻す'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    try {
      final text = await widget.controller.restoreTrash(batch);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
      setState(() => _batches = widget.controller.trashBatches());
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('戻せませんでした：$error')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    String two(int v) => v.toString().padLeft(2, '0');
    return Scaffold(
      appBar: AppBar(title: const Text('ゴミ箱（$trashDays日間）')),
      body: FutureBuilder<List<TrashBatch>>(
        future: _batches,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(child: Text('読み込めませんでした：${snapshot.error}'));
          }
          final batches = snapshot.data;
          if (batches == null) {
            return const Center(child: CircularProgressIndicator());
          }
          if (batches.isEmpty) {
            return const Center(child: Text('ゴミ箱は空です。'));
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: batches.length,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (context, i) {
              final b = batches[i];
              final at = b.deletedAt.toLocal();
              return Card(
                child: ListTile(
                  title: Text(b.label),
                  subtitle: Text(
                    '${b.kind == TrashKind.overwrite ? '上書き前の内容' : '削除'}・'
                    '${b.count}台・${at.month}/${at.day} ${two(at.hour)}:${two(at.minute)}',
                  ),
                  trailing: TextButton(
                    onPressed: _busy ? null : () => _restore(b),
                    child: const Text('戻す'),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
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
  static const _pageSize = 50;
  var _page = 0;
  final _applied = <int>{};
  var _saving = false;

  bool get _hasSelected => _selected.skip(_page).take(_pageSize).any((v) => v);

  Future<void> _apply() async {
    final chosen = [
      for (
        var i = _page;
        i < widget.conflicts.length && i < _page + _pageSize;
        i++
      )
        if (_selected[i]) widget.conflicts[i].incoming,
    ];
    setState(() => _saving = true);
    try {
      await widget.onApply(chosen);
      if (!mounted) return;
      for (
        var i = _page;
        i < widget.conflicts.length && i < _page + _pageSize;
        i++
      ) {
        if (_selected[i]) {
          _applied.add(i);
          _selected[i] = false;
        }
      }
      if (_page + _pageSize >= widget.conflicts.length) {
        Navigator.of(context).pop();
      } else {
        setState(() {
          _page += _pageSize;
          _saving = false;
        });
      }
    } catch (error) {
      // 失敗したら何も上書きされていない（1回の書き込み）。選び直して再試行できる。
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('上書きできませんでした（何も変えていません）：$error')));
    }
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
        const Text(
          '数値または設定情報が一致しない記録があります。取り込んだ内容を使う場合だけチェックしてください。50件ずつ確認・保存します。チェック中は保存するかチェックを外すと次へ進めます。',
        ),
        const SizedBox(height: 12),
        Text(
          '${_page + 1}〜${(_page + _pageSize).clamp(0, widget.conflicts.length)} / ${widget.conflicts.length}件',
        ),
        Row(
          children: [
            TextButton(
              onPressed: _saving || _hasSelected || _page == 0
                  ? null
                  : () => setState(() => _page -= _pageSize),
              child: const Text('前の50件'),
            ),
            TextButton(
              onPressed:
                  _saving ||
                      _hasSelected ||
                      _page + _pageSize >= widget.conflicts.length
                  ? null
                  : () => setState(() => _page += _pageSize),
              child: const Text('次の50件'),
            ),
          ],
        ),
        for (
          var i = _page;
          i < widget.conflicts.length && i < _page + _pageSize;
          i++
        )
          _ConflictCard(
            conflict: widget.conflicts[i],
            value: _selected[i],
            onChanged: _saving || _applied.contains(i)
                ? null
                : (v) => setState(() => _selected[i] = v ?? false),
          ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _saving ? null : _apply,
          child: Text(_saving ? '保存中…' : 'このページでチェックした内容を保存'),
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
  final ValueChanged<bool?>? onChanged;

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
              '${displayMachineName(local.machine)}｜${local.rack}番台',
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

  // 得点計算・翌日候補は AppController.dayView が、記録が変わるまで使い回す
  // （タブを切り替えて戻っても計算し直さない）。
  var _scoredByKey = <String, (SlotRecord, ScoreResult)>{};

  /// 機種名の絞り込み（ひらがな・半角カナでも一致する）。
  final _query = TextEditingController();

  // 全機種を縦に並べ、機種一覧から各機種の位置へ飛ぶ（アナスロと同じ並べ方）。
  // 機種は画面に近い分だけ組み立てる（全機種・全台を一度に作ると、記録が
  // 増えた日に開くまで何秒も待たされる）。
  final _scroll = ScrollController();
  final _topKey = GlobalKey();
  final _listKey = GlobalKey();
  final _sectionKeys = <String, GlobalKey>{};
  final _showTop = ValueNotifier(false);

  /// いま並べている機種（絞り込み後）と、グラフ表示にしている機種。
  var _shown = <MachineSummary>[];
  var _byMachine = <String, List<(SlotRecord, ScoreResult)>>{};
  final _graphMachines = <String>{};

  /// 最後に選んだ機種。選択状態の保存に使うが、画面を開いたときの移動には使わない。
  late String? _machine = widget.controller.lastMachine;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(
      () => _showTop.value = _scroll.hasClients && _scroll.offset > 600,
    );
  }

  @override
  void dispose() {
    _query.dispose();
    _scroll.dispose();
    _showTop.dispose();
    super.dispose();
  }

  /// 末尾別データまとめ（閲覧ページと同じ画面。台を押すとAndroid版の台の画面）。
  void _openSuffixPage() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => PscubeSuffixPage(
        data: ViewerData(
          records: widget.controller.records,
          dateEvents: widget.controller.dateEvents,
        ),
        store: store!,
        day: day!,
        onDayChanged: (changed) => setState(() => day = changed),
        onOpenRecord: (context, record) => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) =>
                AndroidRecordPage(controller: widget.controller, record: record),
          ),
        ),
      ),
    ),
  );

  void _openRecord(SlotRecord record, ScoreResult? score) =>
      Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) =>
              AndroidRecordPage(controller: widget.controller, record: record),
        ),
      );

  /// カレンダーの差枚（その店・その日の総差枚）。記録が変わったときだけ数え直す。
  List<SlotRecord>? _netRecords;
  DayNet? Function(String store, String day)? _netLookup;
  DayNet? _netFor(String store, String day) {
    final records = widget.controller.records;
    if (!identical(records, _netRecords)) {
      _netRecords = records;
      _netLookup = dailyNetLookup(records);
    }
    return _netLookup!(store, day);
  }

  /// 先の日にもイベントを入れられるカレンダー（EVENT_CALENDAR.md）。
  void _openEventCalendar() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => EventCalendarPage(
          stores: storeNames,
          initialStore: store ?? storeNames.keys.first,
          eventFor: widget.controller.dateEventFor,
          namesFor: widget.controller.dateEventNamesFor,
          onSave: (store, days, name) => widget.controller.setDateEventDays(
            store: store,
            days: days,
            name: name,
          ),
          netFor: _netFor,
          netNote: dailyNetNote(storeNames.keys.first),
        ),
      ),
    ),
  );

  Future<void> _editDateEvent() async {
    final selectedStore = store;
    final selectedDay = day;
    if (selectedStore == null || selectedDay == null) return;
    final current = widget.controller.dateEventFor(selectedStore, selectedDay);
    const custom = '自由記載';
    var selected = current == null
        ? ''
        : dateEventOptions.contains(current.name)
        ? current.name
        : custom;
    final text = TextEditingController(
      text: selected == custom ? current?.name : '',
    );
    final result = await showDialog<String?>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text('${dayWithWeekday(selectedDay)} のイベント'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: selected,
                decoration: const InputDecoration(labelText: 'イベント名'),
                items: [
                  const DropdownMenuItem(value: '', child: Text('イベントなし')),
                  ...dateEventOptions.map(
                    (name) => DropdownMenuItem(value: name, child: Text(name)),
                  ),
                  const DropdownMenuItem(value: custom, child: Text(custom)),
                ],
                onChanged: (value) =>
                    setDialogState(() => selected = value ?? ''),
              ),
              if (selected == custom) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: text,
                  autofocus:
                      current == null ||
                      !dateEventOptions.contains(current.name),
                  maxLength: 60,
                  onChanged: (_) => setDialogState(() {}),
                  decoration: const InputDecoration(labelText: 'イベント名を入力'),
                ),
              ],
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('キャンセル'),
            ),
            FilledButton(
              onPressed: selected == custom && text.text.trim().isEmpty
                  ? null
                  : () => Navigator.pop(
                      dialogContext,
                      selected == ''
                          ? ''
                          : selected == custom
                          ? text.text.trim()
                          : selected,
                    ),
              child: const Text('保存'),
            ),
          ],
        ),
      ),
    );
    text.dispose();
    if (result == null || !mounted) return;
    final name = result.isEmpty ? null : result;
    if (name != null && name.length > 60) return;
    await widget.controller.setDateEvent(
      store: selectedStore,
      day: selectedDay,
      name: name,
    );
  }

  void _jumpTo(GlobalKey key) {
    final target = key.currentContext;
    if (target == null) return;
    Scrollable.ensureVisible(
      target,
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeOutCubic,
    );
  }

  /// [key] の部品の上端を画面の上端に合わせるときのスクロール位置。
  /// まだ作られていなければ null。
  double? _revealOffset(GlobalKey key) {
    final object = key.currentContext?.findRenderObject();
    if (object == null || !object.attached) return null;
    return RenderAbstractViewport.of(object)
        .getOffsetToReveal(object, 0)
        .offset;
  }

  static const _sectionGap = 28.0;

  double _estimate(int index) =>
      _sectionGap +
      MachineSection.estimateHeight(
        _byMachine[_shown[index].machine]?.length ?? 0,
        graph: _graphMachines.contains(_shown[index].machine),
      );

  /// 機種 [target] の位置の見積もり。作られている機種（無ければ上の部分）を
  /// 起点に、間の機種の高さの見積もりを足し引きする。
  double _estimateOffset(int target) {
    int? below, above;
    for (var i = 0; i < _shown.length; i++) {
      if (_sectionKeys[_shown[i].machine]?.currentContext == null) continue;
      if (i <= target) below = i;
      if (i > target && above == null) above = i;
    }
    if (below != null) {
      var offset = _revealOffset(_sectionKeys[_shown[below].machine]!)!;
      for (var i = below; i < target; i++) {
        offset += _estimate(i);
      }
      return offset;
    }
    final top = _revealOffset(_topKey);
    final topBox = _topKey.currentContext?.size;
    if (top != null && topBox != null) {
      var offset = top + topBox.height + _sectionGap;
      for (var i = 0; i < target; i++) {
        offset += _estimate(i);
      }
      return offset;
    }
    if (above != null) {
      var offset = _revealOffset(_sectionKeys[_shown[above].machine]!)!;
      for (var i = target; i < above; i++) {
        offset -= _estimate(i);
      }
      return offset;
    }
    return _scroll.offset;
  }

  void _rememberSelection() =>
      unawaited(widget.controller.rememberSelection(store, day, _machine));

  Future<void> _openMachine(String machine) async {
    _machine = machine;
    _rememberSelection();
    final key = _sectionKeys.putIfAbsent(machine, GlobalKey.new);
    final target = _shown.indexWhere((s) => s.machine == machine);
    if (target < 0 || !_scroll.hasClients) return;
    // まだ作られていなければ、見積もった位置へ飛んで作らせてから合わせる。
    for (var tries = 0; tries < 5 && key.currentContext == null; tries++) {
      _scroll.jumpTo(
        _estimateOffset(target).clamp(0.0, double.infinity).toDouble(),
      );
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted) return;
    }
    _jumpTo(key);
  }

  Future<void> _backToList() async {
    if (_listKey.currentContext == null && _scroll.hasClients) {
      _scroll.jumpTo(0);
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted) return;
    }
    _jumpTo(_listKey);
  }

  @override
  Widget build(BuildContext context) {
    final all = widget.controller.records;
    store ??= all.firstOrNull?.store ?? 'nagamachiminami';
    final storeRows = all.where((r) => r.store == store).toList();
    final days = storeRows.map((r) => r.day).toSet().toList()
      ..sort((a, b) => b.compareTo(a));
    if (!days.contains(day)) day = days.firstOrNull;
    final dayRows = storeRows.where((r) => r.day == day).toList();
    if (!dayRows.any((r) => r.machine == _machine)) _machine = null;
    // 選んだ店舗・日付・機種は、選んだとき（onChanged）に覚える。ここ（画面の
    // 組み立て）ではファイルに書かない。
    return Column(
      children: [
        ViewerDateBar(
          days: days,
          day: day,
          event: widget.controller.dateEventFor(store, day)?.name,
          eventFor: (d) => widget.controller.dateEventFor(store, d)?.name,
          onChanged: (d) {
            if (d == null || d == day) return;
            setState(() => day = d);
            _rememberSelection();
          },
        ),
        Expanded(
          child: FutureBuilder<DayView>(
            future: widget.controller.dayView(store!, day ?? ''),
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                return Center(child: Text('採点を読み込めませんでした：${snapshot.error}'));
              }
              return _buildDay(context, dayRows, days, snapshot.data);
            },
          ),
        ),
      ],
    );
  }

  Widget _buildDay(
    BuildContext context,
    List<SlotRecord> dayRows,
    List<String> days,
    DayView? view,
  ) {
    _scoredByKey = view?.scored ?? const {};
    final candidates =
        view?.candidates ??
        (candidates: const <ProvisionalCandidate>[], machines: 0, judged: 0);
    final digest = [for (final r in dayRows) _scoredByKey[r.key]!];
    // 1〜3台の機種は「バラエティ」1つにまとめる（一覧・機種ごとの表とも）。
    final summaries = summarizeMachines(digest);
    final grouped = groupForList(digest);
    final machineCount = {for (final e in digest) e.$1.machine}.length;
    final byMachine = <String, List<(SlotRecord, ScoreResult)>>{};
    final shown = <MachineSummary>[];
    for (final s in summaries) {
      final rows = filterForList(s, grouped[s.machine]!, _query.text);
      if (rows == null) continue;
      shown.add(s);
      byMachine[s.machine] = rows;
    }
    _shown = shown;
    _byMachine = byMachine;
    final visibleKeys = {
      for (final rows in byMachine.values)
        for (final e in rows) e.$1.key,
    };
    final candidateRacks = <String, Set<int>>{};
    final longTrendRacks = <String, Set<int>>{};
    for (final c in candidates.candidates) {
      if (!visibleKeys.contains(c.record.key)) continue;
      (candidateIsFocus(c, widget.controller.records)
              ? candidateRacks
              : longTrendRacks)
          .putIfAbsent(
            c.variety ? varietyGroupName : c.record.machine,
            () => {},
          )
          .add(c.record.rack);
    }
    return Stack(
      children: [
        RefreshIndicator(
          onRefresh: widget.controller.reload,
          // 上の部分（候補・まとめ・機種一覧）と、機種ごとのまとまりを
          // 1つずつ並べる。機種は画面に近い分だけ組み立てる。
          child: ListView.builder(
            controller: _scroll,
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 88),
            scrollCacheExtent: const ScrollCacheExtent.pixels(1200),
            itemCount: 1 + (dayRows.isEmpty ? 0 : shown.length),
            itemBuilder: (context, index) {
              if (index == 0) {
                return Column(
                  key: _topKey,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (widget.controller.message != null)
                      Notice(
                        text: widget.controller.message!,
                        onClose: widget.controller.dismissMessage,
                      ),
                    Row(
                      children: [
                        // 日付切替はスクロールしない上部バーへ。
                        Expanded(
                          flex: 2,
                          child: storeDropdown(store!, (v) {
                            setState(() {
                              store = v;
                              day = null;
                            });
                            _rememberSelection();
                          }, short: true),
                        ),
                        IconButton(
                          tooltip: 'イベントを編集',
                          onPressed: _editDateEvent,
                          icon: const Icon(Icons.event_note_outlined),
                        ),
                        IconButton(
                          tooltip: 'イベントカレンダー',
                          onPressed: _openEventCalendar,
                          icon: const Icon(Icons.calendar_month_outlined),
                        ),
                        // 幸町の末尾別データまとめ（2026-10-12、閲覧ページと同じ画面）。
                        if (meruhenSuffixStores.contains(store) && day != null)
                          IconButton(
                            tooltip: '末尾別データまとめ',
                            onPressed: _openSuffixPage,
                            icon: const Icon(Icons.table_chart_outlined),
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
                    else ...[
                      NextDayCandidatesCard(
                        allRecords: widget.controller.records,
                        day: day!,
                        candidates: candidates.candidates,
                        machines: candidates.machines,
                        judged: candidates.judged,
                        onPick: (record) =>
                            _openRecord(record, _scoredByKey[record.key]?.$2),
                      ),
                      const SizedBox(height: 14),
                      DaySummaryCard(entries: digest, onPick: _openRecord),
                      const SizedBox(height: 18),
                      Text(
                        '設置機種一覧　$machineCount機種'
                        '・${digest.length}台',
                        key: _listKey,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 6),
                      MachineSearchField(
                        controller: _query,
                        onChanged: () => setState(() {}),
                      ),
                      const SizedBox(height: 8),
                      MachineSummaryList(
                        summaries: shown,
                        onPick: _openMachine,
                      ),
                    ],
                  ],
                );
              }
              final s = shown[index - 1];
              return Padding(
                padding: const EdgeInsets.only(top: _sectionGap),
                child: MachineSection(
                  key: _sectionKeys.putIfAbsent(s.machine, GlobalKey.new),
                  machine: s.machine,
                  entries: byMachine[s.machine]!,
                  candidateRacks: candidateRacks[s.machine] ?? const {},
                  longTrendRacks: longTrendRacks[s.machine] ?? const {},
                  onTap: _openRecord,
                  graph: _graphMachines.contains(s.machine),
                  onGraphChanged: (value) => setState(
                    () => value
                        ? _graphMachines.add(s.machine)
                        : _graphMachines.remove(s.machine),
                  ),
                  footer: Row(
                    children: [
                      TextButton(
                        onPressed: _backToList,
                        child: const Text('設置機種一覧へ戻る'),
                      ),
                      const Spacer(),
                      // 機種ごとに出るので、目立たない灰色にする。バラエティは
                      // 別々の機種の集まりなので出さない（機種ごとの削除は
                      // 「過去の記録」から）。台番号で一部だけを表示中も出さない。
                      if (!s.variety && byMachine[s.machine]!.length == s.racks)
                        TextButton.icon(
                          style: TextButton.styleFrom(
                            foregroundColor: AppColors.ash,
                          ),
                          onPressed: () =>
                              _deleteGroup(store!, day!, s.machine),
                          icon: const Icon(Icons.delete_sweep_outlined),
                          label: const Text('まとめて削除…'),
                        ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
        Positioned(
          right: 16,
          bottom: 16,
          child: ValueListenableBuilder<bool>(
            valueListenable: _showTop,
            builder: (context, visible, _) => visible
                ? Material(
                    color: AppColors.carbon.withValues(alpha: .8),
                    shape: const CircleBorder(),
                    elevation: 2,
                    child: IconButton(
                      tooltip: '一番上へ',
                      color: Colors.white,
                      iconSize: 28,
                      onPressed: () => _scroll.animateTo(
                        0,
                        duration: const Duration(milliseconds: 350),
                        curve: Curves.easeOutCubic,
                      ),
                      icon: const Icon(Icons.keyboard_arrow_up),
                    ),
                  )
                : const SizedBox.shrink(),
          ),
        ),
      ],
    );
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
          detail: '$shop　$day　${displayMachineName(machine)}',
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
            // 店舗・日付・機種名がそろった表だけがここへ来る（確認画面か、
            // canSaveWithoutReview）。欠けていたら既定値で埋めずに止める。
            extraction.store ??
                (throw const FormatException('店舗を読み取れていません。保存しませんでした。')),
            extraction.day ??
                (throw const FormatException('日付を読み取れていません。保存しませんでした。')),
            extraction.machine ??
                (throw const FormatException('機種名を読み取れていません。保存しませんでした。')),
            extraction.rows,
          ),
          graphsAtRisk: controller.graphsDroppedBy,
          onNext: controller.nextUngraphed,
          onUndo: controller.undoLastSave,
          onProgress: controller.progressText,
          onMachineStatus: controller.machineStatuses,
          skipTableReview: () => controller.skipTableReview,
          onGraph: (browserContext, captured) async {
            final analysis = controller.resolveWebGraph(captured);
            if (!browserContext.mounted) return false;
            final notShown = graphNumbersNotShown(captured, analysis);
            if (notShown != null) {
              ScaffoldMessenger.of(
                browserContext,
              ).showSnackBar(SnackBar(content: Text(notShown)));
              return false;
            }
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
                  child: GradientButton(
                    onPressed: () => ImportPage.openBrowser(
                      Navigator.of(context),
                      controller,
                    ),
                    label: 'メルヘンワールドを取り込む',
                  ),
                ),
                const SizedBox(height: 6),
                const Divider(height: 28),
                const Text(
                  'P’s CUBE（スロット）',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                const Text('サイトで認証後、機種一覧から全台一覧・台別7日分を順に保存します。'),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const PscubeImportPage(),
                      ),
                    ),
                    icon: const Icon(Icons.travel_explore),
                    label: const Text('P’s CUBE を開く'),
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
                const Divider(height: 28),
                // ジャグラーオンライン（お試し、2026-10-09から最長2週間。JUGGLER_ONLINE.md）。
                const Text(
                  'ジャグラーオンライン（お試し）',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 6),
                const Text('アプリの画面を撮って読み、取り込み済みの台に差枚を足します（差枚はこちらを優先）。'),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => JugglerCapturePage(controller: controller),
                      ),
                    ),
                    icon: const Icon(Icons.document_scanner_outlined),
                    label: const Text('ジャグラーオンラインの取り込み'),
                  ),
                ),
              ],
            ),
          ),
        ),
        if (controller.message != null) ...[
          const SizedBox(height: 12),
          Notice(text: controller.message!, onClose: controller.dismissMessage),
        ],
      ],
    );
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

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final all = widget.controller.records;
    final search = RecordQuery(_query.text);
    final matchedTypes = <String, bool>{};
    bool matchesType(String machine) =>
        matchedTypes[machine] ??= type?.matches(machine) ?? true;
    // バラエティの区分はその日・店舗の全台で決めてから検索する。
    final days = [
      for (final (day, groups) in groupHistoryByDay(
        all.where((r) => store.isEmpty || r.store == store),
      ))
        (
          day,
          [
            for (final g in groups)
              ...() {
                final groupMatches = search.matchesMachine(g.machine);
                final rows = [
                  for (final r in g.rows)
                    if (matchesType(r.machine) &&
                        (groupMatches || search.matches(r)))
                      r,
                ];
                return rows.isEmpty
                    ? const <HistoryGroup>[]
                    : [g.withRows(rows)];
              }(),
          ],
        ),
    ].where((d) => d.$2.isNotEmpty).toList();
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
                  body: '店舗・種別・機種名・台番号の絞り込みを変えてください。',
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

  /// 1日ぶん：日付の見出しと、機種ごとの1行（1〜3台の機種はバラエティ1行）。
  Widget _day(String day, List<HistoryGroup> groups, List<SlotRecord> all) {
    final racks = groups.fold<int>(0, (sum, g) => sum + g.rows.length);
    final machines = groups.fold<int>(0, (sum, g) => sum + g.machines);
    final event = widget.controller.dateEventFor(store, day);
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
                if (event != null) ...[
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      event.name,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.appleBlue,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
                const Spacer(),
                Text(
                  '$machines機種・$racks台',
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
    final settings = group.rows.where((r) => r.confirmedSetting != null).length;
    return InkWell(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => HistoryGroupPage(
            controller: widget.controller,
            day: group.day,
            store: group.store,
            machine: group.machine,
            query: _query.text,
            // 機種名で絞り込んだバラエティは、その機種の台だけを開く。
            only: group.variety
                ? {for (final r in group.rows) r.machine}
                : null,
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
                    group.variety
                        ? '$varietyGroupName（${group.machines}機種）'
                        : displayMachineName(group.machine),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    [
                      storeShortName(group.store),
                      group.variety
                          ? '${varietyRangeFor(group.store)}の機種の${group.rows.length}台'
                          : '${group.rows.length}台',
                      if (settings > 0) '設定情報$settings台',
                    ].join('・'),
                    style: const TextStyle(fontSize: 12, color: AppColors.ash),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            FutureBuilder<DayView>(
              future: widget.controller.dayView(group.store, group.day),
              builder: (context, snapshot) {
                if (snapshot.hasError) return const Text('採点エラー');
                if (snapshot.connectionState != ConnectionState.done) {
                  return const Text(
                    '採点中…',
                    style: TextStyle(color: AppColors.ash),
                  );
                }
                final totals = [
                  for (final r in group.rows)
                    snapshot.data?.scored[r.key]?.$2.total,
                ].whereType<double>().toList();
                return AverageBadge(
                  average: totals.isEmpty
                      ? null
                      : totals.reduce((a, b) => a + b) / totals.length,
                );
              },
            ),
            const Icon(Icons.chevron_right, color: AppColors.mist),
          ],
        ),
      ),
    );
  }
}

/// 過去の記録で1行（ある日・ある店舗・ある機種）を開いた画面。
/// 台は表で並べ、タップでグラフ、長押しで設定情報の記録・削除。
/// [machine] が [varietyGroupName] なら、その日その店で1〜3台の機種の台
/// （[only] があれば、その機種の台だけ）。
class HistoryGroupPage extends StatefulWidget {
  const HistoryGroupPage({
    super.key,
    required this.controller,
    required this.day,
    required this.store,
    required this.machine,
    this.only,
    this.query = '',
  });
  final AppController controller;
  final String day, store, machine;
  final Set<String>? only;
  final String query;

  @override
  State<HistoryGroupPage> createState() => _HistoryGroupPageState();
}

class _HistoryGroupPageState extends State<HistoryGroupPage> {
  late String _day = widget.day;
  bool _graph = false;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      return Scaffold(
        appBar: AppBar(
          title: Text(displayMachineName(widget.machine)),
          bottom: ViewerDateBar(
            days: viewerDays(widget.controller.records, widget.store),
            day: _day,
            event: widget.controller.dateEventFor(widget.store, _day)?.name,
            eventFor: (day) =>
                widget.controller.dateEventFor(widget.store, day)?.name,
            onChanged: (day) {
              if (day != null && day != _day) setState(() => _day = day);
            },
          ),
        ),
        body: FutureBuilder<DayView>(
          future: widget.controller.dayView(widget.store, _day),
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text('採点できませんでした：${snapshot.error}'));
            }
            final variety = widget.machine == varietyGroupName;
            // バラエティかどうかは、その日その店の全台で数える。
            final varietyNames = variety
                ? varietyMachines(snapshot.data!.scored.values.map((e) => e.$1))
                : const <String>{};
            final search = RecordQuery(widget.query);
            final scored =
                snapshot.data!.scored.values
                    .where(
                      (r) => variety
                          ? varietyNames.contains(r.$1.machine) &&
                                (widget.only?.contains(r.$1.machine) ?? true)
                          : r.$1.machine == widget.machine,
                    )
                    .where(
                      (e) =>
                          search.matchesMachine(widget.machine) ||
                          search.matches(e.$1),
                    )
                    .toList()
                  ..sort((a, b) => a.$1.rack.compareTo(b.$1.rack));
            final visibleKeys = {for (final e in scored) e.$1.key};
            final candidateRacks = {
              for (final c in snapshot.data!.candidates.candidates)
                if (visibleKeys.contains(c.record.key) &&
                    candidateIsFocus(c, widget.controller.records))
                  c.record.rack,
            };
            final longTrendRacks = {
              for (final c in snapshot.data!.candidates.candidates)
                if (visibleKeys.contains(c.record.key) &&
                    !candidateIsFocus(c, widget.controller.records))
                  c.record.rack,
            };
            return ListView(
              key: ValueKey(_day),
              padding: EdgeInsets.fromLTRB(
                16,
                12,
                16,
                16 + MediaQuery.of(context).viewPadding.bottom,
              ),
              children: [
                Text(
                  storeNames[widget.store] ?? widget.store,
                  style: const TextStyle(fontSize: 13, color: AppColors.ash),
                ),
                const SizedBox(height: 8),
                if (scored.isEmpty)
                  EmptyState(
                    icon: Icons.inbox_outlined,
                    title: '記録がありません',
                    body: variety
                        ? 'この日のバラエティ（${varietyRangeFor(widget.store)}の機種）の記録はありません。'
                        : 'この日のこの機種の記録はありません。別の日付を選んでください。',
                  )
                else
                  MachineSection(
                    machine: widget.machine,
                    entries: scored,
                    candidateRacks: candidateRacks,
                    longTrendRacks: longTrendRacks,
                    graph: _graph,
                    onGraphChanged: (value) => setState(() => _graph = value),
                    onTap: (record, score) => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => AndroidRecordPage(
                          controller: widget.controller,
                          record: record,
                        ),
                      ),
                    ),
                    onLongPress: _actions,
                    footer: const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Text(
                        'タップでグラフ、長押しで設定情報の記録・削除。',
                        style: TextStyle(fontSize: 12, color: AppColors.ash),
                      ),
                    ),
                  ),
              ],
            );
          },
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
          '${record.day}\n${storeNames[record.store]}\n${displayMachineName(record.machine)}\n${record.rack}番台の記録を削除します。',
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
              Text('${displayMachineName(record.machine)}\n${record.rack}番台'),
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

/// 結果画面の上に出す、バックアップの注意と古い記録を片付けた知らせ。
class _RetentionNotices extends StatelessWidget {
  const _RetentionNotices({required this.controller});
  final AppController controller;

  Widget _notice(String text, List<Widget> actions) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Notice(text: text),
      Align(
        alignment: Alignment.centerRight,
        child: Wrap(spacing: 4, children: actions),
      ),
    ],
  );

  Future<void> _confirmCleanup(BuildContext context) async {
    final count = controller.pausedCleanup;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('古い記録を片付けますか？'),
        content: Text(
          '$retentionDays日より前の$count台を端末から片付けます（ゴミ箱には入りません）。'
          '全期間のバックアップに入っている台だけですが、いつもより多いので止めていました。'
          '日付の打ち間違いの台がないか確かめてから進めてください。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('やめる'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('片付ける'),
          ),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      await controller.confirmLargeCleanup();
    } catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('片付けられませんでした：$error')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final reminder = controller.backupReminder();
    final cleaned = controller.retentionNotice;
    final paused = controller.pausedCleanup;
    final warnings = controller.startupWarnings;
    if (reminder == null &&
        cleaned == null &&
        paused == 0 &&
        warnings.isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (warnings.isNotEmpty)
            _notice(warnings.join('\n'), [
              TextButton(
                onPressed: controller.dismissStartupWarnings,
                child: const Text('閉じる'),
              ),
            ]),
          if (paused > 0)
            _notice(
              '$retentionDays日より前の記録が$paused台あり、いつもより多いので片付けを止めています'
              '（日付の打ち間違いなどがないか確かめてください）。',
              [
                TextButton(
                  onPressed: () => _confirmCleanup(context),
                  child: const Text('確かめて片付ける'),
                ),
              ],
            ),
          if (reminder != null)
            _notice(reminder, [
              TextButton(
                onPressed: () => _shareBackup(context, controller),
                child: const Text('バックアップを書き出す'),
              ),
            ]),
          if (cleaned != null)
            _notice(cleaned, [
              TextButton(
                onPressed: controller.dismissRetentionNotice,
                child: const Text('閉じる'),
              ),
            ]),
        ],
      ),
    );
  }
}

extension FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}

/// バックアップの店舗の選択肢で P’s CUBE を表す値（メルヘンの店舗コードと重ならない）。
const pscubeBackupChoice = '__pscube__';

/// P’s CUBEのバックアップ（format が pscube-viewer）か。先頭だけを読んで判断する
/// （メルヘンの全期間バックアップは大きいので丸ごと読まない）。
Future<bool> isPscubeBackupFile(File file) async {
  final raf = await file.open();
  try {
    final head = String.fromCharCodes(await raf.read(512));
    return RegExp(r'"format"\s*:\s*"pscube-viewer"').hasMatch(head);
  } finally {
    await raf.close();
  }
}

/// P’s CUBEのバックアップを書き出して共有する（P’s CUBE画面の共有ボタンと同じ）。
Future<void> _sharePscubeBackup(BuildContext context) async {
  final store = await PscubeStore.open();
  try {
    final file = await store.exportViewer();
    final fileName = file.uri.pathSegments.last;
    final savedToDestination = await saveBackup(file);
    if (savedToDestination) {
      await store.markBackedUp();
    }
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            !savedToDestination
                ? '保存を取りやめました。バックアップ済みにはしていません。'
                : 'P’s CUBEのバックアップを書き出しました（$fileName）。',
          ),
        ),
      );
    }
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('P’s CUBEのバックアップを書き出せませんでした：$error')),
      );
    }
  } finally {
    await store.close();
  }
}

/// P’s CUBEのバックアップを専用の記録へ統合する（メルヘンの記録には混ぜない）。
Future<void> _importPscubeBackup(BuildContext context, File file) async {
  final store = await PscubeStore.open();
  try {
    final result = await store.importBackup(await file.readAsString());
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'P’s CUBE：新規${result.added}件、更新${result.updated}件、同じ内容${result.unchanged}件、'
            '新しい自分の数値を維持${result.keptLocal}件を取り込みました。',
          ),
        ),
      );
    }
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('P’s CUBEのバックアップを読み込めませんでした（何も保存していません）：$error'),
        ),
      );
    }
  } finally {
    await store.close();
  }
}
