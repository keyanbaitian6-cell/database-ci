/// 保存領域の内訳（2026-10-05、利用者の依頼）。設定の「キャッシュ」が287MBあり、バックアップの写しを
/// 片付けても減らなかったため、何が場所を使っているかをアプリの中で見られるようにする。
/// 読むだけで、何も消さない。
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'shared_widgets.dart' show Notice;
import 'theme.dart';

/// フォルダ（またはファイル）1つの大きさ。[children] は大きい中身（[detailOver] 以上のフォルダの中）。
class StorageEntry {
  const StorageEntry(this.name, this.bytes, [this.children = const []]);
  final String name;
  final int bytes;
  final List<StorageEntry> children;
}

/// [dir] の中を1段ずつ、大きい順に数える。[detailOver] バイト以上のフォルダは、その中も1段数える。
/// 読めないものは数えない（0として扱う）。
Future<List<StorageEntry>> folderUsage(
  Directory dir, {
  int detailOver = 10 * 1000 * 1000,
  int depth = 1,
}) async {
  final entries = <StorageEntry>[];
  if (!await dir.exists()) return entries;
  try {
    await for (final entity in dir.list(followLinks: false)) {
      final name = entity.uri.pathSegments.where((s) => s.isNotEmpty).last;
      if (entity is File) {
        entries.add(StorageEntry(name, await _length(entity)));
      } else if (entity is Directory) {
        final bytes = await _size(entity);
        final children = depth > 0 && bytes >= detailOver
            ? await folderUsage(
                entity,
                detailOver: detailOver,
                depth: depth - 1,
              )
            : const <StorageEntry>[];
        entries.add(StorageEntry(name, bytes, children));
      }
    }
  } on FileSystemException {
    // 読めないフォルダは飛ばす。
  }
  entries.sort((a, b) => b.bytes.compareTo(a.bytes));
  return entries;
}

Future<int> _length(File file) async {
  try {
    return await file.length();
  } on FileSystemException {
    return 0;
  }
}

Future<int> _size(Directory dir) async {
  var total = 0;
  try {
    await for (final entity in dir.list(recursive: true, followLinks: false)) {
      if (entity is File) total += await _length(entity);
    }
  } on FileSystemException {
    // 途中で読めなくなったら、そこまでの合計。
  }
  return total;
}

/// 画面に出す名前（分かるものだけ日本語の説明を付ける）。
String storageLabel(String name) => switch (name) {
  'file_picker' => 'file_picker（バックアップ読み込みで選んだファイルの写し）',
  'WebView' => 'WebView（取り込み画面のブラウザ：サイトの画像・グラフなどの一時データ）',
  'app_webview' => 'app_webview（ブラウザの記録：Cookie・ログイン状態・サイトの保存データ）',
  'databases' => 'databases（記録のデータベース）',
  'app_flutter' => 'app_flutter（アプリの保存ファイル：P’s CUBEの記録・設定など）',
  'code_cache' => 'code_cache（実行用の一時ファイル）',
  'Default' => 'Default（ブラウザの本体のフォルダ）',
  'HTTP Cache' => 'HTTP Cache（サイトから読んだ画像などの一時データ）',
  'Code Cache' => 'Code Cache（サイトのスクリプトの一時データ）',
  'Service Worker' => 'Service Worker（サイトの裏側の保存データ）',
  'import-cache' => 'import-cache（バックアップ読み込みの作業用の控え）',
  _ => name,
};

String formatBytes(int bytes) {
  if (bytes >= 1000 * 1000) return '${(bytes / 1e6).toStringAsFixed(1)} MB';
  if (bytes >= 1000) return '${(bytes / 1e3).toStringAsFixed(0)} KB';
  return '$bytes B';
}

class StorageUsagePage extends StatefulWidget {
  const StorageUsagePage({super.key, this.cacheDir, this.dataDir});

  /// 試験用。省略するとアプリのキャッシュ（`getTemporaryDirectory`）と、その親（アプリのデータ）。
  final Directory? cacheDir;
  final Directory? dataDir;

  @override
  State<StorageUsagePage> createState() => _StorageUsagePageState();
}

class _StorageUsagePageState extends State<StorageUsagePage> {
  late final Future<(List<StorageEntry>, List<StorageEntry>)> _usage = _load();

  Future<(List<StorageEntry>, List<StorageEntry>)> _load() async {
    final cache = widget.cacheDir ?? await getTemporaryDirectory();
    final data = widget.dataDir ?? cache.parent;
    final cacheName = cache.uri.pathSegments.where((s) => s.isNotEmpty).last;
    final dataEntries = [
      for (final e in await folderUsage(data, depth: 3))
        if (e.name != cacheName) e,
    ];
    return (await folderUsage(cache, depth: 3), dataEntries);
  }

  Widget _section(String title, List<StorageEntry> entries) {
    final total = entries.fold<int>(0, (sum, e) => sum + e.bytes);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '$title　合計 ${formatBytes(total)}',
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
            ),
            const SizedBox(height: 8),
            if (entries.isEmpty)
              const Text('なし', style: TextStyle(color: AppColors.ash)),
            ..._tree(entries, 0),
          ],
        ),
      ),
    );
  }

  /// 大きいフォルダは中身も（3段まで、各段の大きい6つ）字下げして出す。
  List<Widget> _tree(List<StorageEntry> entries, int level) => [
    for (final e
        in entries.where((e) => e.bytes > 0).take(level == 0 ? 50 : 6)) ...[
      Padding(
        padding: EdgeInsets.only(left: 16.0 * level),
        child: _row(storageLabel(e.name), e.bytes, bold: level == 0),
      ),
      ..._tree(e.children, level + 1),
    ],
  ];

  Widget _row(String label, int bytes, {bool bold = false}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          formatBytes(bytes),
          style: const TextStyle(
            fontSize: 13,
            fontFeatures: [FontFeature.tabularFigures()],
          ),
        ),
      ],
    ),
  );

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('保存領域の内訳')),
    body: FutureBuilder(
      future: _usage,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Padding(
            padding: const EdgeInsets.all(16),
            child: Notice(text: '数えられませんでした：${snapshot.error}'),
          );
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final (cache, data) = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Notice(
              text:
                  '見るだけで、何も消しません。「キャッシュ」は端末の空きが減るとAndroidが自動で消す場所で、'
                  '消えても記録は残ります。数字は端末の設定の表示と少し違うことがあります（数え方の違い）。',
            ),
            const SizedBox(height: 12),
            _section('キャッシュ', cache),
            const SizedBox(height: 12),
            _section('データ（キャッシュ以外）', data),
          ],
        );
      },
    ),
  );
}
