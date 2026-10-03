import 'package:database_android/meruhen_net.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

/// ゼロ線200.5からの高さ（上がプラス）を、SVGの座標に直した線。
List<List<double>> curve(List<double> heights) => [
  for (final (i, h) in heights.indexed) [i * 10.0 + 0.5, 200.5 - h],
];

int? fromCurve(List<double> heights, int? maxHold) {
  final c = curve(heights);
  final ys = c.map((p) => p[1]);
  return meruhenNetEstimate(
    baselineY: 200.5,
    peakY: ys.reduce((a, b) => a < b ? a : b),
    troughY: ys.reduce((a, b) => a > b ? a : b),
    endY: c.last[1],
    curve: c,
    maxHold: maxHold,
  );
}

void main() {
  test('実例：片側2,000枚のグラフは1px＝2000/180枚で終点を換算する', () {
    // 長町南615番台・10/03（山+147px・谷−63px・終点+128px・最大持玉2376）→ +1,422
    expect(fromCurve([0, -63, 40, 147, 128], 2376), 1422);
    // 幸町779番台・10/02（谷−8px→山+163px・終点+97px・最大持玉1982）→ +1,078
    expect(fromCurve([0, -8, 163, 97], 1982), 1078);
  });

  test('振れ幅と最大持玉から段階を選ぶ（1,000枚・4,000枚の例、マイナス終点）', () {
    // 片側1,000枚：上がり60px×(1000/180)=333枚、最大持玉400 → 終点30px＝+167
    expect(fromCurve([0, 60, 30], 400), 167);
    // 片側4,000枚：振れ幅120px、上がり120px×22.2=2,667枚、最大持玉2,900 → 終点−50px＝−1,111
    expect(fromCurve([0, 120, 40, -50], 2900), -1111);
    // 片側2,000枚と見ると最大持玉が上がり幅の2倍以上になるが、4,000枚なら比が1に近い。
  });

  test('計算できないときは null（0にしない）、一日中ゼロ線なら0', () {
    expect(fromCurve([0, 50, 20], null), isNull, reason: '最大持玉が無い');
    expect(fromCurve([0, 50, 20], 88888888), isNull, reason: '最大持玉が異常値');
    expect(fromCurve([0, 0, 0], 0), 0);
    expect(fromCurve([0, -40, -80], 0), isNull, reason: '上がりが無く段階を決められない');
    expect(
      meruhenNetEstimate(
        baselineY: 150.5,
        peakY: 100,
        troughY: 160,
        endY: 120,
        maxHold: 500,
      ),
      isNull,
      reason: '高さ400以外のSVGは未確認',
    );
  });

  test('線が無いときは4点で、段階が1つに決まる台だけ計算する', () {
    // 谷→山の順：上がり幅は山−谷で確定（下限＝上限）。
    expect(
      meruhenNetEstimate(
        baselineY: 200.5,
        peakY: 200.5 - 147,
        troughY: 200.5 + 63,
        endY: 200.5 - 128,
        peakX: 300,
        troughX: 100,
        endX: 356,
        maxHold: 2376,
      ),
      1422,
    );
    // 山・谷の時刻が無い古い記録：下限は始点から山まで。ここでは2,000枚だけが合う。
    expect(
      meruhenNetEstimate(
        baselineY: 200.5,
        peakY: 200.5 - 147,
        troughY: 200.5 + 63,
        endY: 200.5 - 128,
        maxHold: 2376,
      ),
      1422,
    );
    // 山→谷の順で上がり幅の範囲が広く、2,000枚と4,000枚のどちらも合う → null。
    expect(
      meruhenNetEstimate(
        baselineY: 200.5,
        peakY: 200.5 - 100,
        troughY: 200.5 + 170,
        endY: 200.5 + 160,
        peakX: 100,
        troughX: 300,
        endX: 356,
        maxHold: 1500,
      ),
      isNull,
    );
  });

  test('メルヘンは推定差枚、P’s CUBEは確定差枚を表示に使う', () {
    final graph = GraphMeasurement(
      baselineY: 200.5,
      peakY: 200.5 - 147,
      troughY: 200.5 + 63,
      endY: 200.5 - 128,
      curve: curve([0, -63, 40, 147, 128]),
    );
    final meruhen = SlotRecord(
      store: 'nagamachiminami',
      day: '2026-10-03',
      machine: 'ハナハナ',
      rack: 615,
      games: 8584,
      bb: 32,
      rb: 30,
      maxHold: 2376,
      graph: graph,
    );
    expect(
      (meruhen.estimatedNetMedals, meruhen.netValue, meruhen.netLabel),
      (1422, 1422, '推定差枚'),
    );
    expect(meruhen.netMedals, isNull, reason: '推定を確定差枚の項目に入れない');
    final pscube = SlotRecord(
      store: 'pscube:c740601:20',
      day: '2026-10-03',
      machine: 'マイジャグラーV',
      rack: 1120,
      games: 5000,
      bb: 20,
      rb: 15,
      graph: graph,
      extra: {'source': 'pscube', 'my': 1500, 'rate': '20', 'net_medals': 300},
    );
    expect(
      (pscube.estimatedNetMedals, pscube.netValue, pscube.netLabel),
      (null, 300, '差枚'),
    );
  });
}
