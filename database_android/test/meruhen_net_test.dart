import 'package:database_android/meruhen_net.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

/// ゼロ線200.5からの高さ（上がプラス）を、SVGの座標に直した線。
List<List<double>> curve(List<double> heights) => [
  for (final (i, h) in heights.indexed) [i * 10.0 + 0.5, 200.5 - h],
];

int? fromCurve(List<double> heights, int? maxHold, [int? games]) {
  final c = curve(heights);
  final ys = c.map((p) => p[1]);
  return meruhenNetEstimate(
    baselineY: 200.5,
    peakY: ys.reduce((a, b) => a < b ? a : b),
    troughY: ys.reduce((a, b) => a > b ? a : b),
    endY: c.last[1],
    curve: c,
    maxHold: maxHold,
    games: games,
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

  test('1回転あたりの使用枚数がありえない段階は除く（PC版と同じ例）', () {
    // 実例（2026-10-06）：ほぼ下がり続けて上がりが数pxのグラフは、最大持玉だけでは段階が決まらず、
    // 最大の段階を選んで1回転あたり5〜14枚使ったことになっていた（1回転に入るのは3枚まで）。
    // 幸町517番台・10/04（1,634回転・最大持玉234）：−8,944 → 2,000枚の段階で −1,789（1回転1.14枚）
    expect(
      fromCurve([
        0,
        0,
        0,
        -5,
        -17,
        -17,
        -18,
        -36,
        -40,
        -55,
        -75,
        -89,
        -87,
        -109,
        -106,
        -105,
        -116,
        -139,
        -156,
        -161,
        -161,
      ], 234),
      -8944,
      reason: '回転数が無ければ従来どおり',
    );
    expect(
      fromCurve(
        [
          0,
          0,
          0,
          -5,
          -17,
          -17,
          -18,
          -36,
          -40,
          -55,
          -75,
          -89,
          -87,
          -109,
          -106,
          -105,
          -116,
          -139,
          -156,
          -161,
          -161,
        ],
        234,
        1634,
      ),
      -1789,
    );
    // 幸町637番台・10/05（790回転・最大持玉293）：−10,733 → 1,000枚の段階で −894（1回転1.16枚）
    expect(
      fromCurve(
        [
          0,
          0,
          0,
          -4,
          -4,
          -13,
          -21,
          -21,
          -26,
          -26,
          -28,
          -73,
          -69,
          -70,
          -77,
          -77,
          -95,
          -95,
          -112,
          -145,
          -161,
          -161,
        ],
        293,
        790,
      ),
      -894,
    );
    // 幸町513番台・10/05（1,228回転・最大持玉279）：4,000枚だと1回転1.94枚 → 2,000枚で −1,089
    expect(
      fromCurve(
        [
          0,
          0,
          0,
          -1,
          -24,
          -44,
          -41,
          -48,
          -48,
          -64,
          -81,
          -80,
          -72,
          -92,
          -98,
          -98,
          -98,
        ],
        279,
        1228,
      ),
      -1089,
    );
    // 最小の段階でも1回転3枚を超える（長町南176番台・9/30、168回転で136px下落）は決められない。
    expect(fromCurve([0, 0, 0, -136, -133, -133], 113, 168), isNull);
    // 1.75枚を超えても3枚以内なら、最小の段階を使う（「—」にしない）。
    expect(fromCurve([0, 0, 0, -136, -133, -133], 113, 300), -739);
    // 段階が1つに決まる従来の例は、回転数を渡しても変わらない。
    expect(fromCurve([0, -63, 40, 147, 128], 2376, 2000), 1422);
    expect(fromCurve([0, 120, 40, -50], 2900, 2500), -1111);
  });

  test('選び直した台だけ要確認（※）にする', () {
    ({int? value, bool needsCheck}) detail(
      List<double> heights,
      int maxHold, [
      int? games,
    ]) {
      final c = curve(heights);
      final ys = c.map((p) => p[1]);
      return meruhenNetEstimateDetail(
        baselineY: 200.5,
        peakY: ys.reduce((a, b) => a < b ? a : b),
        troughY: ys.reduce((a, b) => a > b ? a : b),
        endY: c.last[1],
        curve: c,
        maxHold: maxHold,
        games: games,
      );
    }

    // 517番台：大きい目盛りを外して選び直した → 要確認。
    expect(
      detail(
        [
          0,
          0,
          0,
          -5,
          -17,
          -17,
          -18,
          -36,
          -40,
          -55,
          -75,
          -89,
          -87,
          -109,
          -106,
          -105,
          -116,
          -139,
          -156,
          -161,
          -161,
        ],
        234,
        1634,
      ),
      (value: -1789, needsCheck: true),
    );
    // 回転数が無いときは選び直さないので印も付けない（従来どおりの値）。
    expect(
      detail([
        0,
        0,
        0,
        -5,
        -17,
        -17,
        -18,
        -36,
        -40,
        -55,
        -75,
        -89,
        -87,
        -109,
        -106,
        -105,
        -116,
        -139,
        -156,
        -161,
        -161,
      ], 234),
      (value: -8944, needsCheck: false),
    );
    // 1.75枚を超え、最小の目盛りに頼った台も要確認。
    expect(detail([0, 0, 0, -136, -133, -133], 113, 300), (
      value: -739,
      needsCheck: true,
    ));
    // 決められない台は値も印も無い。
    expect(detail([0, 0, 0, -136, -133, -133], 113, 168), (
      value: null,
      needsCheck: false,
    ));
    // 目盛りが1つに決まる台・外す目盛りが無い台は印を付けない。
    expect(detail([0, -63, 40, 147, 128], 2376, 8584), (
      value: 1422,
      needsCheck: false,
    ));
    expect(detail([0, 120, 40, -50], 2900, 2500), (
      value: -1111,
      needsCheck: false,
    ));
    // 画面の文字：要確認には「※」、それ以外は従来どおり。
    SlotRecord record(List<double> heights, int maxHold, int games) {
      final c = curve(heights);
      final ys = c.map((p) => p[1]);
      return SlotRecord(
        store: 'saiwaichou',
        day: '2026-10-04',
        machine: '東京リベンジャーズ',
        rack: 517,
        games: games,
        bb: 2,
        rb: 1,
        maxHold: maxHold,
        graph: GraphMeasurement(
          baselineY: 200.5,
          peakY: ys.reduce((a, b) => a < b ? a : b),
          troughY: ys.reduce((a, b) => a > b ? a : b),
          endY: c.last[1],
          curve: c,
        ),
      );
    }

    final flagged = record(
      [
        0,
        0,
        0,
        -5,
        -17,
        -17,
        -18,
        -36,
        -40,
        -55,
        -75,
        -89,
        -87,
        -109,
        -106,
        -105,
        -116,
        -139,
        -156,
        -161,
        -161,
      ],
      234,
      1634,
    );
    expect(flagged.netNeedsCheck, isTrue);
    expect(flagged.netText, '${signedMedals(-1789)}※');
    final plain = record([0, -63, 40, 147, 128], 2376, 8584);
    expect(plain.netNeedsCheck, isFalse);
    expect(plain.netText, '+1,422');
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
