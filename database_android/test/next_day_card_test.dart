import 'package:database_android/data_checks.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('選択日の表示：9/27（日）の形。読めない日付は空', () {
    expect(shortDayLabel('2026-09-27'), '9/27（日）');
    expect(shortDayLabel('2026-10-01'), '10/1（木）');
    expect(shortDayLabel('bad'), '');
  });

  testWidgets('翌日候補のカード：選択日と対象日、検証の結果、データ量の意味を出す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    const record = SlotRecord(
      store: 'nagamachiminami',
      day: '2026-09-27',
      machine: 'テスト',
      rack: 5,
      games: 4000,
      bb: 20,
      rb: 10,
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-09-27',
              candidates: const [
                (
                  record: record,
                  index: 58.0,
                  days: 7,
                  confidence: '中',
                  variety: false,
                ),
              ],
              machines: 3,
              judged: 1,
              onPick: (_) {},
            ),
          ),
        ),
      ),
    );
    expect(find.text('9/28（月） の候補（仮）'), findsOneWidget);
    expect(
      find.textContaining('9/27（日）（選択日）までの記録から、9/28（月）向けに選んだ台です'),
      findsOneWidget,
    );
    expect(find.text(nextDayValidationNote), findsOneWidget);
    expect(find.textContaining('当たりやすさを示すものではありません'), findsOneWidget);
    expect(find.textContaining('過去7日分・データ量 中'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('翌日候補のカード：バラエティは「501番台　機種名（バラエティ）」で、前日の回転数と終わり方を出す', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 1600));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    SlotRecord at(int rack, String machine, {int games = 4000, int endY = 150}) =>
        SlotRecord(
          store: 'saiwaichou',
          day: '2026-09-27',
          machine: machine,
          rack: rack,
          games: games,
          bb: 20,
          rb: 10,
          graph: GraphMeasurement(
            baselineY: 200,
            peakY: 100,
            troughY: 250,
            endY: endY.toDouble(),
          ),
        );
    ProvisionalCandidate regular(int rack, double index) => (
      record: at(rack, '4台以上の機種'),
      index: index,
      days: 7,
      confidence: '中',
      variety: false,
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-09-27',
              candidates: [
                // 4台以上の機種の候補が7台を超えても、バラエティは最初から出す。
                for (var i = 0; i < 9; i++) regular(10 + i, 70.0 - i),
                (
                  record: at(801, '1台の機種', games: 12345),
                  index: 63.0,
                  days: 4,
                  confidence: '少',
                  variety: true,
                ),
                (
                  record: at(802, '別の1台の機種', endY: 230),
                  index: 50.0,
                  days: 0,
                  confidence: '比較なし',
                  variety: true,
                ),
              ],
              machines: 2,
              judged: 2,
              onPick: (_) {},
            ),
          ),
        ),
      ),
    );
    expect(find.text('すべて表示（9台）'), findsOneWidget);
    expect(find.text('バラエティ（1〜3台の機種）から2台'), findsOneWidget);
    expect(find.text('801番台'), findsOneWidget);
    expect(find.text('1台の機種'), findsOneWidget);
    expect(find.text('（バラエティ）'), findsNWidgets(2));
    expect(
      find.text('前日 12,345G・回ってプラス・当たり 普段より +13（比べた記録4件）'),
      findsOneWidget,
    );
    expect(
      find.text('前日 4,000G・回ったのに凹み・当たりは普段と比べる記録が足りない'),
      findsOneWidget,
    );
    expect(find.text('プラス'), findsOneWidget);
    expect(find.text('凹み'), findsOneWidget);
    expect(
      find.textContaining('幸町の狙い方：前日3000G以上回った台から、「回ってプラス」の台を先に'),
      findsOneWidget,
    );
    expect(find.textContaining('（バラエティはまとめて1つ）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
