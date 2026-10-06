import 'package:database_android/models.dart';
import 'package:database_android/daily_net_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const store = 'pscube:c740601:20';
SlotRecord row(
  int rack,
  String day, {
  int? net,
  String scope = store,
  int games = 3000,
}) => SlotRecord(
  store: scope,
  day: day,
  rack: rack,
  machine: 'ノーマル',
  games: games,
  bb: 10,
  rb: 5,
  extra: {
    'source': 'pscube',
    'my': 1500,
    'rate': scope.split(':').last,
    'machine_type': 'normal',
    'at_art': 0,
    'net_medals': ?net,
  },
);

final records = [
  row(1, '2026-10-01', net: 100),
  row(2, '2026-10-01', net: -50),
  row(3, '2026-10-01'), // 差枚未取得（当たり0回・取得失敗など）
  row(4, '2026-10-01', net: 999999, games: 88888888), // サイトの数値異常
  row(1, '2026-10-02', net: 300),
  row(2, '2026-10-02', net: 9000, scope: 'pscube:c740601:5'), // 別貸玉
  row(1, '2026-09-30'),
  row(2, '2026-09-30'),
];

SlotRecord meruhen(
  int rack,
  String day, {
  required int maxHold,
  required List<double> heights,
  int games = 8000,
}) {
  final curve = [
    for (final (i, h) in heights.indexed) [i * 10.0 + 0.5, 200.5 - h],
  ];
  final ys = curve.map((p) => p[1]);
  return SlotRecord(
    store: 'nagamachiminami',
    day: day,
    rack: rack,
    machine: 'ハナハナ',
    games: games,
    bb: 30,
    rb: 30,
    maxHold: maxHold,
    graph: GraphMeasurement(
      baselineY: 200.5,
      peakY: ys.reduce((a, b) => a < b ? a : b),
      troughY: ys.reduce((a, b) => a > b ? a : b),
      endY: curve.last[1],
      curve: curve,
    ),
  );
}

void main() {
  test('日ごとの差枚は取得できた台だけを合計し、無い日は0にしない', () {
    final days = dailyNet(records, store);
    expect(
      [for (final d in days) d.day],
      ['2026-10-02', '2026-10-01', '2026-09-30'],
    );
    final oct1 = days[1];
    expect(
      (oct1.total, oct1.captured, oct1.racks, oct1.average),
      (50, 2, 3, 25),
    );
    expect((days[0].total, days[0].captured, days[0].racks), (300, 1, 1));
    final sep30 = days[2];
    expect(
      (sep30.total, sep30.average, sep30.captured, sep30.racks),
      (null, null, 0, 2),
    );
  });

  testWidgets('月ごとの表・期間累計・並べ替え・日付から当日へ', (tester) async {
    String? opened;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => DailyNetPage(
                    records: records,
                    store: store,
                    day: '2026-10-02',
                    onDayChanged: (day) => opened = day,
                    eventFor: (day) => day == '2026-10-01' ? '華の日' : null,
                  ),
                ),
              ),
              child: const Text('開く'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('開く'));
    await tester.pumpAndSettle();
    expect(find.text('P’s CUBE（20スロ）　2026年10月のデータ'), findsOneWidget);
    expect(find.text('10/1（木）'), findsOneWidget);
    expect(find.text('華の日'), findsOneWidget);
    // イベント名が日付の下で切れないよう、行は56（メルヘンで起きた件、86eb7f8）。P’s CUBEも同じ。
    expect(
      tester.widget<DataTable>(find.byType(DataTable)).dataRowMinHeight,
      56,
    );
    expect(find.text('10/2（金）'), findsOneWidget);
    expect(find.text('9/30（水）'), findsNothing, reason: '選んだ月だけ');
    expect(find.text('+50'), findsOneWidget);
    expect(find.text('+25'), findsOneWidget);
    expect(find.text('2/3'), findsOneWidget);
    expect(find.text('期間累計'), findsOneWidget);
    expect(find.text('+350'), findsOneWidget);
    expect(find.text('+117'), findsOneWidget, reason: '350 ÷ 取得3台');
    expect(find.text('3台'), findsOneWidget);
    expect(find.text('+9,000'), findsNothing, reason: '別貸玉は混ぜない');

    double top(String text) => tester.getTopLeft(find.text(text)).dy;
    expect(top('10/1（木）'), lessThan(top('10/2（金）')), reason: '初めは日付の古い順');
    await tester.tap(find.text('総差枚'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('総差枚'));
    await tester.pumpAndSettle();
    expect(top('10/2（金）'), lessThan(top('10/1（木）')), reason: '総差枚の多い順');
    expect(top('10/1（木）'), lessThan(top('期間累計')), reason: '累計は常に最後');

    // 9月：差枚の無い日は「—」（0ではない）。
    await tester.tap(find.text('2026年10月'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('2026年9月').last);
    await tester.pumpAndSettle();
    expect(find.text('9/30（水）'), findsOneWidget);
    expect(find.text('—'), findsNWidgets(4));
    expect(find.text('0/2'), findsOneWidget);

    await tester.tap(find.text('9/30（水）'));
    await tester.pumpAndSettle();
    expect(opened, '2026-09-30');
    expect(find.text('開く'), findsOneWidget, reason: 'ホームへ戻る');
  });

  testWidgets('メルヘンは推定差枚として同じ表を出す', (tester) async {
    final rows = [
      meruhen(
        615,
        '2026-10-03',
        maxHold: 2376,
        heights: [0, -63, 40, 147, 128],
      ),
      meruhen(779, '2026-10-03', maxHold: 1982, heights: [0, -8, 163, 97]),
      SlotRecord(
        store: 'nagamachiminami',
        day: '2026-10-03',
        rack: 1,
        machine: 'ハナハナ',
        games: 100,
        bb: 0,
        rb: 0,
      ), // グラフの無い台は数えない
    ];
    final days = dailyNet(rows, 'nagamachiminami');
    expect(
      (days.single.total, days.single.captured, days.single.racks),
      (2500, 2, 3),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: DailyNetPage(
          records: rows,
          store: 'nagamachiminami',
          day: '2026-10-03',
        ),
      ),
    );
    expect(find.text('日別の差枚（推定）'), findsOneWidget);
    expect(find.text('メルヘンワールド長町南店　2026年10月のデータ'), findsOneWidget);
    expect(find.text('+2,500'), findsNWidgets(2), reason: '当日と期間累計');
    expect(find.text('+1,250'), findsNWidgets(2));
    expect(find.text('2/3'), findsOneWidget);
    expect(find.textContaining('推定差枚です'), findsOneWidget);
  });

  testWidgets('要確認（※）の推定差枚がある日は、取得台数の横に台数を出す', (tester) async {
    final rows = [
      meruhen(
        615,
        '2026-10-04',
        maxHold: 2376,
        heights: [0, -63, 40, 147, 128],
      ),
      // 幸町517番台・10/04の形：目盛りを回転数から選び直した台。
      meruhen(
        517,
        '2026-10-04',
        maxHold: 234,
        heights: [
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
        games: 1634,
      ),
    ];
    final days = dailyNet(rows, 'nagamachiminami');
    expect(
      (days.single.total, days.single.captured, days.single.needsCheck),
      (1422 - 1789, 2, 1),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: DailyNetPage(
          records: rows,
          store: 'nagamachiminami',
          day: '2026-10-04',
        ),
      ),
    );
    expect(find.text('2/2（※1）'), findsOneWidget);
    expect(find.textContaining('要確認の台数'), findsOneWidget);
  });
}
