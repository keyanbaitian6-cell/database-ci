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

/// 推定差枚を出さない店・日（ジャグラーオンラインの差枚は出す）。長町南の10/7は、サイトのグラフが全台
/// 「始点と終点を結んだ直線」で途中の推移が無く、推定が正しく決められないため
/// （2026-10-12 利用者「長町南10/7だけ消す」）。PC `core.MERUHEN_NET_HIDDEN_DAYS`・共有ページ
/// `share_viewer/net.mjs` と同じ。
const meruhenNetHiddenDays = <String, Set<String>>{
  'nagamachiminami': {'2026-10-07'},
};

/// その店・日の推定差枚を出さないか（[meruhenNetHiddenDays]）。
bool meruhenNetHidden(String? store, String? day) =>
    meruhenNetHiddenDays[store]?.contains(day) ?? false;

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

/// 線が下がった分の合計（その日に使った枚数の目安）の、1回転あたりの上限。グラフの形と最大持玉だけでは
/// 段階が決まらない台で、いちばん大きい段階を選ぶと、1回転に3枚しか入らないのに −8,944枚（1,634回転）
/// のような値になっていた（2026-10-06、幸町 東京リベンジャーズ517・北斗637）。段階が1つに決まる3,755台
/// （300回転以上）では1回転あたり中央値0.95・99.9%が1.71以下・最大1.93枚。これを超える段階は除き、
/// 残りが無ければ最も小さい段階を使い、それも物理的な上限（3枚）を超えるときだけ決められない（null）。
const meruhenPlausibleUsePerGame = 1.75;
const meruhenMaxUsePerGame = 3.0;

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
/// [games]（その日の総回転数）があれば、線の全座標から、1回転あたりに使った枚数がありえない段階を除く。
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
  int? games,
}) => meruhenNetEstimateDetail(
  baselineY: baselineY,
  peakY: peakY,
  troughY: troughY,
  endY: endY,
  peakX: peakX,
  troughX: troughX,
  endX: endX,
  curve: curve,
  maxHold: maxHold,
  games: games,
).value;

/// [meruhenNetEstimate] と同じ値に、要確認の印を添える。[needsCheck]：グラフの形と最大持玉で
/// 合う目盛りのうち、1回転あたりの使用枚数が多すぎるものを外して選び直した（2026-10-06の補正が
/// 効いた）。グラフだけでは目盛りを決めきれなかった台なので、画面では値に「※」を付ける。
({int? value, bool needsCheck}) meruhenNetEstimateDetail({
  required double baselineY,
  required double peakY,
  required double troughY,
  required double endY,
  double? peakX,
  double? troughX,
  double? endX,
  List<List<double>>? curve,
  required int? maxHold,
  int? games,
}) {
  const none = (value: null, needsCheck: false);
  if ((baselineY - _zeroY).abs() > 0.01) return none; // 別の大きさのSVGは未確認
  if (maxHold == null || maxHold < 0 || maxHold > 100000) return none;
  const half = _zeroY - _topY;
  final peak = baselineY - peakY, trough = baselineY - troughY;
  final end = baselineY - endY;
  final amp = [
    peak.abs(),
    trough.abs(),
    end.abs(),
  ].reduce((a, b) => a > b ? a : b);
  if (amp == 0) return (value: 0, needsCheck: false); // 一日中ゼロ線の上（未稼働など）

  bool fits(int index) {
    final range = meruhenAxisSteps[index];
    final previous = index == 0 ? 0 : meruhenAxisSteps[index - 1];
    final unit = range / half;
    // 振れ幅がその段階に収まり、1つ前の段階には収まらない（半ピクセルの丸めは許す）。
    return amp * unit > previous - unit / 2 && amp * unit <= range + unit / 2;
  }

  int? chosen;
  var needsCheck = false;
  if (curve != null && curve.length >= 2) {
    final values = [for (final p in curve) baselineY - p[1]];
    final rise = _rise(values);
    if (rise <= 0) return none;
    // 点は間引かれているので、測った上がり幅は実際より小さい（比は1以上になる）。
    // 比が1を下回らない段階のうち、1回転あたりの使用枚数がありえるものの最大を選ぶ。
    final candidates = [
      for (var i = 0; i < meruhenAxisSteps.length; i++)
        if (fits(i) && maxHold / (rise * meruhenAxisSteps[i] / half) >= 0.98)
          meruhenAxisSteps[i],
    ];
    var drops = 0.0;
    for (var i = 1; i < values.length; i++) {
      if (values[i] < values[i - 1]) drops += values[i - 1] - values[i];
    }
    bool within(int step, double perGame) =>
        games == null || games <= 0 || drops * step / half <= perGame * games;
    final plausible = [
      for (final step in candidates)
        if (within(step, meruhenPlausibleUsePerGame)) step,
    ];
    needsCheck = plausible.length != candidates.length;
    if (plausible.isNotEmpty) {
      chosen = plausible.last;
    } else if (candidates.isNotEmpty &&
        within(candidates.first, meruhenMaxUsePerGame)) {
      chosen = candidates.first;
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
  if (chosen == null) return none;
  return (value: (end * chosen / half).round(), needsCheck: needsCheck);
}
