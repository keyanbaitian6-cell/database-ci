/// メルヘンの推定差枚（グラフの座標と最大持玉から計算する。追加の通信なし）。
///
/// サイトは差枚の数値を返さない（machine_detail の sadama は null、slump_data はSVGだけ）。
/// SVGの縦軸は高さ400でゼロ線200.5・上下に180px。片側の幅 R 枚は
/// 1,000・2,000・4,000・6,000…（以降2,000刻み）のうち、その日の振れ幅が収まる最小の段階で、
/// 最大持玉は「谷から山までの最大の上がり幅」。保存済み約6,200件の統計、BIG・REG・回転数との
/// 照合（ジャグラーで R²0.97）、実機での高さ変更で確かめた推定（2026-10-03、
/// outputs/meruhen-investigation/REPORT_20261003_claude.md）。サイトのコードでの証明や
/// 正解の差枚との照合はないため、確定差枚（P’s CUBEの net_medals）とは分けて「推定」とする。
/// 誤差は1ピクセル分の丸め（±R/360枚）。R を1つに決められない台は null（0にしない）。
/// PC版 `core.meruhen_net_estimate` と同じ規則。
library;

/// グラフの縦軸の片側の幅（枚）の段階。
const meruhenAxisSteps = <int>[
  1000,
  2000,
  4000,
  6000,
  8000,
  10000,
  12000,
  14000,
  16000,
  18000,
  20000,
  22000,
  24000,
  26000,
  28000,
  30000,
  32000,
  34000,
  36000,
  38000,
  40000,
];

/// サイトのSVG（高さ400）のゼロ線と上端。
const _zeroY = 200.5, _topY = 20.5;

double _rise(Iterable<double> values) {
  var low = 0.0, rise = 0.0;
  for (final v in values) {
    if (v < low) low = v;
    if (v - low > rise) rise = v - low;
  }
  return rise;
}

/// 推定差枚（枚）。計算できないときは null。
///
/// [curve] があれば線の全座標で上がり幅を測る（閲覧ページ・グラフを読み込んだ画面）。
/// 無ければ4点（ゼロ線・山・谷・終点）から上がり幅の下限・上限を出し、最大持玉が
/// その範囲に入る段階が1つだけのときに限って計算する（Androidの一覧）。
int? meruhenNetEstimate({
  required double baselineY,
  required double peakY,
  required double troughY,
  required double endY,
  double? peakX,
  double? troughX,
  double? endX,
  List<List<double>>? curve,
  required int? maxHold,
}) {
  if ((baselineY - _zeroY).abs() > 0.01) return null; // 別の大きさのSVGは未確認
  if (maxHold == null || maxHold < 0 || maxHold > 100000) return null;
  const half = _zeroY - _topY;
  final peak = baselineY - peakY, trough = baselineY - troughY;
  final end = baselineY - endY;
  final amp = [
    peak.abs(),
    trough.abs(),
    end.abs(),
  ].reduce((a, b) => a > b ? a : b);
  if (amp == 0) return 0; // 一日中ゼロ線の上（未稼働など）

  bool fits(int index) {
    final range = meruhenAxisSteps[index];
    final previous = index == 0 ? 0 : meruhenAxisSteps[index - 1];
    final unit = range / half;
    // 振れ幅がその段階に収まり、1つ前の段階には収まらない（半ピクセルの丸めは許す）。
    return amp * unit > previous - unit / 2 && amp * unit <= range + unit / 2;
  }

  int? chosen;
  if (curve != null && curve.length >= 2) {
    final rise = _rise(curve.map((p) => baselineY - p[1]));
    if (rise <= 0) return null;
    // 点は間引かれているので、測った上がり幅は実際より小さい（比は1以上になる）。
    // 比が1を下回らない最大の段階を選ぶ。
    for (var i = 0; i < meruhenAxisSteps.length; i++) {
      final unit = meruhenAxisSteps[i] / half;
      if (fits(i) && maxHold / (rise * unit) >= 0.98)
        chosen = meruhenAxisSteps[i];
    }
  } else {
    // 4点だけ：時刻順のゼロ・山・谷・終点で測った上がり幅が下限、山−谷（0を含む）が上限。
    // 山・谷の時刻が無い古い記録は順番が分からないので、下限は始点から山まで。
    final double low;
    if (peakX == null || troughX == null) {
      low = peak > 0 ? peak : 0;
    } else {
      final points = <(double, double)>[
        (0, 0),
        (peakX, peak),
        (troughX, trough),
        (endX ?? double.infinity, end),
      ]..sort((a, b) => a.$1.compareTo(b.$1));
      low = _rise(points.map((p) => p.$2));
    }
    final high = (peak > 0 ? peak : 0) - (trough < 0 ? trough : 0);
    final feasible = <int>[];
    for (var i = 0; i < meruhenAxisSteps.length; i++) {
      final unit = meruhenAxisSteps[i] / half;
      if (fits(i) &&
          maxHold >= low * unit * 0.98 - unit &&
          maxHold <= high * unit * 1.3 + unit) {
        feasible.add(meruhenAxisSteps[i]);
      }
    }
    if (feasible.length == 1) chosen = feasible.single;
  }
  if (chosen == null) return null;
  return (end * chosen / half).round();
}
