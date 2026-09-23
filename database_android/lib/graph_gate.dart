import 'dart:ui' show Offset;

import 'models.dart';

/// Conditions under which a graph may be saved without the review screen.
///
/// Mirrors the PC app's `graph_auto_save_blockers` (database/browser_import.py):
/// the thresholds come from the real captures in `observed_graphs.json` (every
/// curve starts within 0.5 of the zero line and its last x reaches the full
/// width). Any doubt sends the graph to the normal review screen instead.
const autoGraphMinPoints = 10;
const autoGraphStartTolerance = 2.0;
const autoGraphMinEndXRatio = 0.8;
const autoGraphEndZeroTolerance = 1.0;

/// Returns the reasons the graph must still be reviewed by hand; an empty
/// list means every check passed.
///
/// [curve] and [baselineY] are the exact SVG data read from the page (null
/// when the graph came from a screenshot, which is never auto-saved).
/// [existing] is the already-saved list row for the same store/day/machine/rack.
List<String> graphAutoSaveBlockers({
  required List<Offset>? curve,
  required double? baselineY,
  required double? width,
  required int? games,
  required int? bb,
  required int? rb,
  required int? maxHold,
  required SlotRecord? existing,
}) {
  final reasons = <String>[];
  if (existing == null) {
    return ['この台の一覧がまだ取り込まれていません'];
  }
  if (existing.graph != null) {
    reasons.add('この台は既にグラフが保存されています（上書きは確認が必要）');
  }
  if (games == null || bb == null || rb == null || maxHold == null) {
    reasons.add('数値（総回転・BIG・REG・最大持玉）を読み取れませんでした');
  } else {
    if (games <= 0) reasons.add('総回転数が0です');
    final differs =
        games != existing.games ||
        bb != existing.bb ||
        rb != existing.rb ||
        (existing.maxHold != null && maxHold != existing.maxHold);
    if (differs) reasons.add('一覧の数値と詳細画面の数値が異なります');
  }
  if (curve == null || baselineY == null) {
    reasons.add('グラフの線データを読み取れていません');
    return reasons;
  }
  if (curve.length < autoGraphMinPoints) {
    reasons.add('グラフの点が少なすぎます（${curve.length}点）');
    return reasons;
  }
  if ((curve.first.dy - baselineY).abs() > autoGraphStartTolerance) {
    reasons.add('グラフの開始位置がゼロ線と一致しません');
  }
  if (width != null &&
      width > 0 &&
      curve.last.dx < width * autoGraphMinEndXRatio) {
    reasons.add('グラフが右端まで描かれていません（読み込み途中の可能性）');
  }
  if ((curve.last.dy - baselineY).abs() <= autoGraphEndZeroTolerance) {
    reasons.add('終点がゼロ線とほぼ同じ位置です（上昇・下降を目で確認）');
  }
  return reasons;
}
