import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'models.dart';

/// 保存時のグラフ画像を、表示する画面の分だけDBから読む。
///
/// 画面用の一覧には画像を載せない（記録が増えるとメモリに載り切らないため）。
/// 最近読んだ分だけを覚えておき、スクロールで戻っても読み直さない。
///
/// 覚えた画像は、台の取得時刻（captured_at）と組にしておく。保存し直すと
/// 取得時刻が変わるので、古い画像を出し続けることはない（[forget] を呼び
/// 忘れても）。読み込みに失敗したときは覚えず、次に表示するとき読み直す。
class GraphPreviews {
  GraphPreviews(this._read);

  final Future<Uint8List?> Function(String key) _read;

  static const _limit = 200;
  final _cache =
      <
        String,
        ({String? capturedAt, Future<Uint8List?> image, Object token})
      >{};

  Future<Uint8List?> load(SlotRecord record) {
    final graph = record.graph;
    if (graph == null) return Future.value(null);
    if (graph.previewPng != null) return Future.value(graph.previewPng);
    if (!graph.storedPreview) return Future.value(null);
    final key = record.key;
    final cached = _cache.remove(key);
    if (cached != null && cached.capturedAt == record.capturedAt) {
      _cache[key] = cached; // 最近使った分として後ろへ
      return cached.image;
    }
    final token = Object();
    var failed = false;
    Future<Uint8List?> read() async {
      try {
        return await _read(key);
      } on Object {
        // 失敗は覚えない（次に表示するとき読み直す）。
        failed = true;
        if (identical(_cache[key]?.token, token)) _cache.remove(key);
        return null;
      }
    }

    final image = read();
    if (!failed) {
      _cache[key] = (capturedAt: record.capturedAt, image: image, token: token);
      while (_cache.length > _limit) {
        _cache.remove(_cache.keys.first);
      }
    }
    return image;
  }

  /// 保存・削除した台の画像を忘れる（次に表示するとき読み直す）。
  void forget(Iterable<String> keys) {
    for (final key in keys) {
      _cache.remove(key);
    }
  }
}

/// 画面の木に [GraphPreviews] を渡す。Android版ではアプリ全体を包む。
/// 閲覧ページ（DBがない）では置かないので、画像は出さず概略図になる。
class GraphPreviewScope extends InheritedWidget {
  const GraphPreviewScope({
    super.key,
    required this.previews,
    required super.child,
  });

  final GraphPreviews previews;

  static GraphPreviews? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<GraphPreviewScope>()?.previews;

  @override
  bool updateShouldNotify(GraphPreviewScope oldWidget) =>
      !identical(previews, oldWidget.previews);
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

  Widget _image(Uint8List bytes) {
    final image = Image.memory(
      bytes,
      fit: BoxFit.fill,
      filterQuality: FilterQuality.medium,
      gaplessPlayback: true,
    );
    return background == null
        ? image
        : ColoredBox(color: background!, child: image);
  }

  @override
  Widget build(BuildContext context) {
    final inMemory = record.graph?.previewPng;
    if (inMemory != null) return _image(inMemory);
    final previews = GraphPreviewScope.maybeOf(context);
    if (previews == null) return fallback;
    return FutureBuilder<Uint8List?>(
      future: previews.load(record),
      builder: (context, snapshot) {
        final bytes = snapshot.data;
        return bytes == null ? fallback : _image(bytes);
      },
    );
  }
}
