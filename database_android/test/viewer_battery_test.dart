import 'dart:convert';

import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

// 閲覧ページの電池対策（2026-09-30）：グラフの線は描くときにだけ数値の一覧へ
// 直す。直し方は以前と同じなので、描く線（精度）は変わらない。

/// 以前の読み込み時と同じ直し方（比べる基準）。
List<List<double>> eager(List raw) => raw
    .map((p) => (p as List).map((v) => (v as num).toDouble()).toList())
    .toList();

Map<String, dynamic> graphJson(List curve) => {
  'baseline_y': 200.5,
  'peak_y': 87.5,
  'trough_y': 250.5,
  'end_y': 189.5,
  'preview_width': 420,
  'preview_height': 246,
  'curve': curve,
};

void main() {
  // JSONから読んだときと同じく、整数と小数が混ざった線。
  final curve = jsonDecode(
    '[[0.5, 200.5], [0, 200], [289.5, 200.5], [293, 219.5], [301.5, 207],'
    ' [419.5, 189.5]]',
  ) as List;

  test('グラフの線：数値は以前の直し方と同じ。使うまで直さず、直すのは1回だけ', () {
    final graph = GraphMeasurement.fromJson(graphJson(curve));
    final saved = graph.curve! as SavedCurve;
    expect(saved.converted, isFalse);
    expect(graph.curve, eager(curve));
    expect(saved.converted, isTrue);
    expect(graph.curve!.first, isA<List<double>>());
    expect(graph.curve![3], [293.0, 219.5]);
    // 描く部品は同じ線かどうかを identical で見分けるので、同じ一覧を返す。
    expect(identical(graph.curve![0], graph.curve![0]), isTrue);
  });

  test('グラフの線：描く大きさ・保存し直す中身も以前と同じ', () {
    final lazy = GraphMeasurement.fromJson(graphJson(curve));
    final before = GraphMeasurement(
      baselineY: 200.5,
      peakY: 87.5,
      troughY: 250.5,
      endY: 189.5,
      previewWidth: 420,
      previewHeight: 246,
      curve: eager(curve),
    );
    expect(curveCanvasSize(lazy), curveCanvasSize(before));
    expect(jsonEncode(lazy.toJson()), jsonEncode(before.toJson()));
    expect(
      GraphMeasurement.fromJson(jsonDecode(jsonEncode(lazy.toJson()))).curve,
      eager(curve),
    );
  });

  test('グラフの線：壊れた線は今までどおり読み込みの時点で失敗し、その台は飛ばす', () {
    for (final broken in [
      [
        [0, 'x'],
      ],
      ['not a point'],
    ]) {
      expect(
        () => GraphMeasurement.fromJson(graphJson(broken)),
        throwsA(isA<TypeError>()),
      );
    }
    expect(
      () => GraphMeasurement.fromJson({...graphJson(curve), 'curve': 'x'}),
      throwsA(isA<TypeError>()),
    );
    final record = {
      'store': 'saiwaichou',
      'day': '2026-09-25',
      'machine': 'テスト',
      'rack': 1,
      'games': 3000,
      'bb': 10,
      'rb': 5,
    };
    final data = ViewerData.parse(
      jsonEncode({
        'records': [
          {...record, 'graph_measurement': graphJson(curve)},
          {
            ...record,
            'rack': 2,
            'graph_measurement': graphJson([
              [0, 'x'],
            ]),
          },
        ],
      }),
    );
    expect(data.records.map((r) => r.rack), [1]);
    expect(data.skipped, 1);
    expect(data.records.single.graph!.curve, eager(curve));
  });

  test('線の無い台は、今までどおり線なし', () {
    final json = graphJson(curve)..remove('curve');
    expect(GraphMeasurement.fromJson(json).curve, isNull);
  });

  test('書き出した時刻は、ファイルに書かれていたままの文字で覚える', () {
    const exportedAt = '2026-09-30T01:19:50.746423+09:00';
    final data = ViewerData.parse(
      jsonEncode({
        'header': {'format': 'database-backup', 'exported_at': exportedAt},
        'records': [],
      }),
    );
    expect(data.exportedAtText, exportedAt);
    expect(data.exportedAt, DateTime.parse(exportedAt).toLocal());
    expect(ViewerData.parse('{"records": []}').exportedAtText, isNull);
  });
}
