import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'models.dart';

/// 保存時のグラフ画像を、表示する画面の分だけDBから読む。
///
/// 画面用の一覧には画像を載せない（記録が増えるとメモリに載り切らないため）。
/// 最近読んだ分だけを覚えておき、スクロールで戻っても読み直さない。
class GraphPreviews {
  GraphPreviews._();
  static final instance = GraphPreviews._();

  /// 画像を読む関数（アプリ起動時に `DatabaseService.loadPreview` を入れる）。
  Future<Uint8List?> Function(String key)? loader;

  static const _limit = 200;
  final _cache = <String, Future<Uint8List?>>{};

  Future<Uint8List?> load(SlotRecord record) {
    final graph = record.graph;
    if (graph == null) return Future.value(null);
    if (graph.previewPng != null) return Future.value(graph.previewPng);
    final read = loader;
    if (!graph.storedPreview || read == null) return Future.value(null);
    final future =
        _cache.remove(record.key) ??
        read(record.key).catchError((Object _) => null);
    _cache[record.key] = future;
    while (_cache.length > _limit) {
      _cache.remove(_cache.keys.first);
    }
    return future;
  }

  /// 保存・削除した台の画像を忘れる（次に表示するとき読み直す）。
  void forget(Iterable<String> keys) {
    for (final key in keys) {
      _cache.remove(key);
    }
  }
}

/// 保存時の画像があれば画像を、読めるまで・無ければ [fallback] を出す。
class StoredGraphImage extends StatelessWidget {
  const StoredGraphImage({
    super.key,
    required this.record,
    required this.fallback,
    this.background,
  });

  final SlotRecord record;
  final Widget fallback;
  final Color? background;

  @override
  Widget build(BuildContext context) => FutureBuilder<Uint8List?>(
    future: GraphPreviews.instance.load(record),
    builder: (context, snapshot) {
      final bytes = snapshot.data;
      if (bytes == null) return fallback;
      final image = Image.memory(
        bytes,
        fit: BoxFit.fill,
        filterQuality: FilterQuality.medium,
        gaplessPlayback: true,
      );
      return background == null
          ? image
          : ColoredBox(color: background!, child: image);
    },
  );
}
