import 'package:database_android/models.dart';
import 'package:database_android/pscube_daily_net_page.dart';
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

void main() {
  test('日ごとの差枚は取得できた台だけを合計し、無い日は0にしない', () {
    final days = pscubeDailyNet(records, store);
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
                  builder: (_) => PscubeDailyNetPage(
                    records: records,
                    store: store,
                    day: '2026-10-02',
                    onDayChanged: (day) => opened = day,
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
}
