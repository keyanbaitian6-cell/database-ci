import 'dart:io';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:image/image.dart' as imglib;

enum CaptureKind { table, graph, unknown }

class EditableRow {
  EditableRow({
    required this.rack,
    required this.games,
    required this.bb,
    required this.rb,
    this.maxHold,
    this.previousStart,
    this.detailUrl,
  });

  int rack;
  int games;
  int bb;
  int rb;
  // saiwaichou's own list page never shows a 最大持玉 column at all; it is
  // filled in later from the individual rack's graph page instead.
  int? maxHold;
  int? previousStart;
  String? detailUrl;
}

/// 保存する画像を小さくするための設定。グラフは線と目盛りだけなので、画素を半分・
/// 色数を32色にしても見た目はほとんど変わらず、容量は約1/6になる（実データで計測）。
const previewPixelScale = 2;
const previewColors = 32;

/// グラフの見た目用の画像を、保存する形（画素を半分・32色のPNG）にする。
///
/// 画像と一緒に保存する幅・高さは「座標の大きさ」（4点や曲線と同じ座標系）のままで、
/// 表示側はその大きさに引き伸ばして描くので、点の位置はずれない。
Uint8List encodePreviewPng(imglib.Image image) {
  final small = imglib.copyResize(
    image,
    width: max(1, image.width ~/ previewPixelScale),
    height: max(1, image.height ~/ previewPixelScale),
    interpolation: imglib.Interpolation.average,
  );
  final reduced = imglib.quantize(small, numberOfColors: previewColors);
  return Uint8List.fromList(imglib.encodePng(reduced, level: 9));
}

class GraphDetection {
  const GraphDetection({
    required this.previewPng,
    required this.width,
    required this.height,
    required this.points,
    this.curve,
    this.baselineY,
  });

  final Uint8List previewPng;
  final int width;
  final int height;
  final List<Offset> points;

  /// Exact SVG curve and zero line when the graph was read from the page's
  /// SVG (null for screenshot detection); used to decide whether the review
  /// screen can be skipped.
  final List<Offset>? curve;
  final double? baselineY;

  /// [curve] as rounded [x, y] pairs, ready to store with the record.
  List<List<double>>? get curveAsPairs => curve
      ?.map(
        (p) => [
          double.parse(p.dx.toStringAsFixed(1)),
          double.parse(p.dy.toStringAsFixed(1)),
        ],
      )
      .toList();
}

class CaptureAnalysis {
  const CaptureAnalysis({
    required this.path,
    required this.kind,
    required this.fullText,
    this.store,
    this.day,
    this.machine,
    this.rack,
    this.games,
    this.bb,
    this.rb,
    this.maxHold,
    this.rows = const [],
    this.graph,
  });

  final String path;
  final CaptureKind kind;
  final String fullText;
  final String? store;
  final String? day;
  final String? machine;
  final int? rack;
  final int? games;
  final int? bb;
  final int? rb;
  final int? maxHold;
  final List<EditableRow> rows;
  final GraphDetection? graph;
}

/// 台ページは曲線を先に描き、グラフ内の数字（総回転数・BIG・REG・最大持玉）を少し遅れて
/// 入れることがある（2026-10-16、PCの幸町で多発）。4つとも空のまま読み、一覧の記録でも
/// 最大持玉を補えないときは保存しない（幸町は一覧に最大持玉が無い）。PC版
/// `build_graph_context` と同じ条件・文。[resolved] は一覧の記録を引き継いだ後の値。
String? graphNumbersNotShown(
  CaptureAnalysis captured,
  CaptureAnalysis resolved,
) {
  final empty =
      captured.games == null &&
      captured.bb == null &&
      captured.rb == null &&
      captured.maxHold == null;
  if (!empty || resolved.maxHold != null) return null;
  return '${captured.rack}番台：グラフ内の数値（総回転数・最大持玉など）がまだ表示されていません。'
      '数値が表示されてから取り込み直してください。';
}

class PlatformImageBridge {
  static const _channel = MethodChannel('database/share');

  static Future<void> openUrl(String url) =>
      _channel.invokeMethod<void>('openUrl', url);
}

class _OcrItem {
  const _OcrItem(this.text, this.box);
  final String text;
  final Rect box;
  double get cx => box.center.dx;
  double get cy => box.center.dy;
}

class ImportService {
  Future<CaptureAnalysis> analyze(String path) async {
    final recognizer = TextRecognizer(script: TextRecognitionScript.japanese);
    late final RecognizedText recognized;
    try {
      recognized = await recognizer.processImage(InputImage.fromFilePath(path));
    } finally {
      await recognizer.close();
    }
    final items = <_OcrItem>[];
    for (final block in recognized.blocks) {
      for (final line in block.lines) {
        for (final element in line.elements) {
          items.add(_OcrItem(element.text, element.boundingBox));
        }
      }
    }
    final text = recognized.text;
    final graphLike = text.contains('BIG') && text.contains('REG');
    final tableLike =
        text.contains('台番号') || (text.contains('総回転') && text.contains('最大持'));
    final kind = graphLike
        ? CaptureKind.graph
        : tableLike
        ? CaptureKind.table
        : CaptureKind.unknown;
    final store = text.contains('幸町')
        ? 'saiwaichou'
        : text.contains('長町南')
        ? 'nagamachiminami'
        : null;
    final day = _readDate(text);
    final rack = _firstInt(text, RegExp(r'(\d{1,4})\s*番台'));
    final stats = _readGraphStats(items, text);
    final rows = kind == CaptureKind.table
        ? _readTable(items)
        : <EditableRow>[];
    final graph = kind == CaptureKind.graph ? await detectGraph(path) : null;
    return CaptureAnalysis(
      path: path,
      kind: kind,
      fullText: text,
      store: store,
      day: day,
      machine: _readMachine(recognized, rack),
      rack: rack,
      games: stats['games'],
      bb: stats['bb'],
      rb: stats['rb'],
      maxHold: stats['max_hold'],
      rows: rows,
      graph: graph,
    );
  }

  String? _readDate(String text) {
    final match = RegExp(r'(20\d{2})[/.\-年](\d{1,2})[/.\-月](\d{1,2})')
        .firstMatch(text);
    if (match == null) return null;
    final y = int.parse(match.group(1)!);
    final m = int.parse(match.group(2)!);
    final d = int.parse(match.group(3)!);
    return '$y-${m.toString().padLeft(2, '0')}-${d.toString().padLeft(2, '0')}';
  }

  int? _firstInt(String text, RegExp pattern) {
    final value = pattern.firstMatch(text)?.group(1);
    return value == null ? null : int.tryParse(value.replaceAll(',', ''));
  }

  String? _readMachine(RecognizedText text, int? rack) {
    for (final block in text.blocks) {
      for (final line in block.lines) {
        final value = line.text.trim();
        if (value.length < 3 || value.length > 40) continue;
        if (value.contains('番台') ||
            value.contains('グラフ') ||
            value.contains('データ'))
          continue;
        if (RegExp(r'[ぁ-んァ-ヶ一-龠A-Za-z]').hasMatch(value) &&
            (value.startsWith('L') ||
                value.startsWith('S') ||
                value.contains('スマスロ'))) {
          return value;
        }
      }
    }
    return null;
  }

  int? _plainInt(String text) {
    final normalized = text
        .replaceAll(',', '')
        .replaceAll('，', '')
        .replaceAllMapped(
          RegExp(r'[０-９]'),
          (m) => String.fromCharCode(m.group(0)!.codeUnitAt(0) - 0xFEE0),
        );
    return RegExp(r'^\d{1,7}$').hasMatch(normalized)
        ? int.tryParse(normalized)
        : null;
  }

  Map<String, int?> _readGraphStats(List<_OcrItem> items, String fullText) {
    int? findAfter(String label) => _firstInt(
      fullText.replaceAll('\n', ' '),
      RegExp('$label\\s*[:：]?\\s*(\\d[\\d,]*)', caseSensitive: false),
    );
    var bb = findAfter('BIG');
    var rb = findAfter('REG');
    var games = _firstInt(fullText, RegExp(r'総回転(?:数)?\s*[:：]?\s*(\d[\d,]*)'));
    var maxHold = _firstInt(
      fullText,
      RegExp(r'最大持(?:玉|ち玉)\s*[:：]?\s*(\d[\d,]*)'),
    );

    final bigLabel = items
        .where((e) => e.text.toUpperCase() == 'BIG')
        .firstOrNull;
    final regLabel = items
        .where((e) => e.text.toUpperCase() == 'REG')
        .firstOrNull;
    int? beside(_OcrItem? label) {
      if (label == null) return null;
      final candidates = items.where(
        (item) =>
            _plainInt(item.text) != null &&
            item.cx > label.box.right &&
            (item.cy - label.cy).abs() < 22,
      );
      if (candidates.isEmpty) return null;
      return _plainInt(
        candidates
            .reduce(
              (a, b) =>
                  (a.cy - label.cy).abs() < (b.cy - label.cy).abs() ? a : b,
            )
            .text,
      );
    }

    bb ??= beside(bigLabel);
    rb ??= beside(regLabel);
    if (bigLabel != null && games == null) {
      final above = items.where(
        (item) =>
            _plainInt(item.text) != null &&
            item.cx > bigLabel.box.right &&
            item.cy < bigLabel.cy - 5,
      );
      if (above.isNotEmpty) {
        games = _plainInt(above.reduce((a, b) => a.cy > b.cy ? a : b).text);
      }
    }
    return {'games': games, 'bb': bb, 'rb': rb, 'max_hold': maxHold};
  }

  List<EditableRow> _readTable(List<_OcrItem> items) {
    const aliases = <String, List<String>>{
      'rack': ['台番号', '台番'],
      'bb': ['BB'],
      'rb': ['RB'],
      'games': ['総回転数', '総回転', '回転数'],
      'previous': ['前日最終スタート', '前日最終'],
      'max': ['最大持玉', '最大持ち玉'],
    };
    final candidates = <String, List<_OcrItem>>{};
    for (final entry in aliases.entries) {
      candidates[entry.key] = items
          .where(
            (item) => entry.value.any(
              (alias) => item.text.replaceAll(' ', '').contains(alias),
            ),
          )
          .toList();
    }
    if (candidates.values.any((list) => list.isEmpty)) return [];
    Map<String, _OcrItem>? headers;
    var best = 0;
    for (final rackHeader in candidates['rack']!) {
      final selected = <String, _OcrItem>{'rack': rackHeader};
      for (final entry in candidates.entries.where(
        (entry) => entry.key != 'rack',
      )) {
        final close = entry.value
            .where((item) => (item.cy - rackHeader.cy).abs() < 45)
            .toList();
        if (close.isNotEmpty) {
          selected[entry.key] = close.reduce(
            (a, b) =>
                (a.cy - rackHeader.cy).abs() < (b.cy - rackHeader.cy).abs()
                ? a
                : b,
          );
        }
      }
      if (selected.length > best) {
        best = selected.length;
        headers = selected;
      }
    }
    if (headers == null || headers.length < 6) return [];
    final headerBottom = headers.values
        .map((item) => item.box.bottom)
        .reduce(max);
    final numeric = items
        .where((item) => item.cy > headerBottom && _plainInt(item.text) != null)
        .toList();
    final rackX = headers['rack']!.cx;
    final orderedX = headers.values.map((item) => item.cx).toList()..sort();
    final spacing = orderedX.length > 1
        ? orderedX
                  .skip(1)
                  .fold<double>(
                    0,
                    (sum, x) => sum + x - orderedX[orderedX.indexOf(x) - 1],
                  ) /
              (orderedX.length - 1)
        : 100.0;
    final rackItems = numeric.where(
      (item) => (item.cx - rackX).abs() < max(35, spacing * .45),
    );
    final rows = <EditableRow>[];
    int? at(String key, _OcrItem anchor) {
      final x = headers![key]!.cx;
      final choices = numeric.where(
        (item) =>
            (item.cx - x).abs() < max(35, spacing * .45) &&
            (item.cy - anchor.cy).abs() < 35,
      );
      if (choices.isEmpty) return null;
      return _plainInt(
        choices
            .reduce(
              (a, b) =>
                  (a.cy - anchor.cy).abs() < (b.cy - anchor.cy).abs() ? a : b,
            )
            .text,
      );
    }

    for (final anchor in rackItems) {
      final rack = _plainInt(anchor.text);
      final bb = at('bb', anchor);
      final rb = at('rb', anchor);
      final games = at('games', anchor);
      final maximum = at('max', anchor);
      if (rack == null ||
          rack < 1 ||
          rack > 9999 ||
          bb == null ||
          rb == null ||
          games == null ||
          maximum == null) {
        continue;
      }
      rows.add(
        EditableRow(
          rack: rack,
          games: games,
          bb: bb,
          rb: rb,
          maxHold: maximum,
          previousStart: at('previous', anchor),
        ),
      );
    }
    final unique = <int, EditableRow>{for (final row in rows) row.rack: row};
    return unique.values.toList()..sort((a, b) => a.rack.compareTo(b.rack));
  }

  Future<GraphDetection?> detectGraph(String path) async {
    final bytes = await File(path).readAsBytes();
    final source = imglib.decodeImage(bytes);
    if (source == null) return null;
    final width = source.width;
    final height = source.height;
    final redCounts = List<int>.filled(height, 0);
    for (var y = 0; y < height; y++) {
      var count = 0;
      for (var x = 0; x < width; x++) {
        final p = source.getPixel(x, y);
        if (p.r > 160 && p.g < 100 && p.b < 100) count++;
      }
      redCounts[y] = count;
    }
    final rows = <int>[];
    for (var y = 1; y < height - 1; y++) {
      final neighbours = max(redCounts[y - 1], redCounts[y + 1]);
      if (redCounts[y] > max(40, width * .02) &&
          redCounts[y] - neighbours > redCounts[y] * .5) {
        rows.add(y);
      }
    }
    if (rows.isEmpty) return null;
    final baselineFull = rows.reduce(
      (a, b) => redCounts[a] >= redCounts[b] ? a : b,
    );
    final redXs = <int>[];
    for (var x = 0; x < width; x++) {
      final p = source.getPixel(x, baselineFull);
      if (p.r > 160 && p.g < 100 && p.b < 100) redXs.add(x);
    }
    if (redXs.isEmpty) return null;
    final redLeft = redXs.first;
    final redRight = redXs.last;
    final darkRuns = <(int, int)>[];
    int? runStart;
    for (var x = 0; x < width; x++) {
      final p = source.getPixel(x, baselineFull);
      final dark = max(p.r, max(p.g, p.b)) < 180;
      if (dark && runStart == null) runStart = x;
      if ((!dark || x == width - 1) && runStart != null) {
        final end = dark && x == width - 1 ? x : x - 1;
        if (end - runStart + 1 >= 4) darkRuns.add((runStart, end));
        runStart = null;
      }
    }
    final leftRuns = darkRuns.where((run) => run.$2 < redLeft).toList();
    final rightRuns = darkRuns.where((run) => run.$1 > redRight).toList();
    int left;
    int right;
    if (leftRuns.isNotEmpty && rightRuns.isNotEmpty) {
      left = leftRuns.reduce((a, b) => a.$2 > b.$2 ? a : b).$1;
      right = rightRuns.reduce((a, b) => a.$1 < b.$1 ? a : b).$2;
    } else {
      final visible = max(1, redRight - redLeft);
      left = max(0, (redLeft - visible * .25).round());
      right = min(width - 1, (redRight + visible * .25).round());
    }
    final graphWidth = max(1, right - left);
    final top = max(0, (baselineFull - graphWidth * .32).round());
    final bottom = min(height, (baselineFull + graphWidth * .32).round());
    final crop = imglib.copyCrop(
      source,
      x: left,
      y: top,
      width: right - left + 1,
      height: bottom - top,
    );
    final baseline = baselineFull - top;
    final points = _detectCurve(crop, baseline);
    return GraphDetection(
      previewPng: encodePreviewPng(crop),
      width: crop.width,
      height: crop.height,
      points:
          points ??
          [
            Offset(crop.width * .85, baseline.toDouble()),
            Offset(crop.width * .35, baseline.toDouble()),
            Offset(crop.width * .55, baseline.toDouble()),
            Offset(crop.width * .75, baseline.toDouble()),
          ],
    );
  }

  List<Offset>? _detectCurve(imglib.Image image, int baseline) {
    final w = image.width;
    final h = image.height;
    double luminance(int x, int y) {
      final p = image.getPixel(x, y);
      return (p.r + p.g + p.b) / 3;
    }

    bool neutral(int x, int y) {
      final p = image.getPixel(x, y);
      return max(p.r, max(p.g, p.b)) - min(p.r, min(p.g, p.b)) < 25;
    }

    bool fill(int x, int y) =>
        (y - baseline).abs() <= 1 || (luminance(x, y) > 18 && neutral(x, y));
    final xStart = max(20, (w * .03).round());
    final xStop = min(w - 20, (w * .97).round());
    final yStart = max(30, (baseline - w * .28).round());
    final yStop = min(h - 20, (baseline + w * .27).round());
    final requiredBottom = min(
      yStop - 1,
      (baseline + max(35, w * .11)).round(),
    );
    final candidates = <(int, int, int)>[];
    for (var x = xStart; x < xStop; x++) {
      final runs = <(int, int)>[];
      int? start;
      for (var y = yStart; y < yStop; y++) {
        final yes = fill(x, y);
        if (yes && start == null) start = y;
        if ((!yes || y == yStop - 1) && start != null) {
          final end = yes && y == yStop - 1 ? y : y - 1;
          if (end >= requiredBottom && end - start >= 1) runs.add((start, end));
          start = null;
        }
      }
      if (runs.isNotEmpty) {
        final best = runs.reduce(
          (a, b) =>
              (a.$2 - a.$1 > b.$2 - b.$1 ||
                  (a.$2 - a.$1 == b.$2 - b.$1 && a.$2 > b.$2))
              ? a
              : b,
        );
        candidates.add((x, best.$1, best.$2));
      }
    }
    if (candidates.length < 10) return null;
    final groups = <List<(int, int, int)>>[];
    for (final item in candidates) {
      if (groups.isEmpty || item.$1 - groups.last.last.$1 > 3) {
        groups.add([item]);
      } else {
        groups.last.add(item);
      }
    }
    var active = groups.reduce((a, b) => a.length >= b.length ? a : b);
    if (active.length < 10) return null;
    var curve = <Offset>[];
    for (final item in active) {
      final searchEnd = min(item.$3, item.$2 + 30);
      var brightest = -1.0;
      var lineY = item.$2;
      for (var y = item.$2; y <= searchEnd; y++) {
        final value = luminance(item.$1, y);
        if (value > brightest) {
          brightest = value;
          lineY = y;
        }
      }
      if (brightest < 55) lineY = item.$2;
      if ((lineY - baseline).abs() <= 2) lineY = baseline;
      curve.add(Offset(item.$1.toDouble(), lineY.toDouble()));
    }
    final jumpLimit = max(20, (w * .04).round());
    final minimumPrefix = max(20, (curve.length * .70).round());
    final maximumTail = max(12, (w * .10).round());
    for (var i = 1; i < curve.length; i++) {
      if (i >= minimumPrefix &&
          curve.length - i <= maximumTail &&
          curve[i].dx - curve[i - 1].dx <= 3 &&
          (curve[i].dy - curve[i - 1].dy).abs() > jumpLimit) {
        curve = curve.sublist(0, i);
        break;
      }
    }
    if (curve.length < 10) return null;
    final peak = curve.reduce((a, b) => a.dy <= b.dy ? a : b);
    final trough = curve.reduce((a, b) => a.dy >= b.dy ? a : b);
    final endX = curve.map((p) => p.dx).reduce(max);
    final tail = curve.where((p) => endX - p.dx <= 2).toList();
    final endY = tail.map((p) => p.dy).reduce((a, b) => a + b) / tail.length;
    return [
      Offset(w * .85, baseline.toDouble()),
      peak,
      trough,
      Offset(endX, endY),
    ];
  }
}

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
