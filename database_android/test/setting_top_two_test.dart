import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/setting_estimate.dart';
import 'package:database_android/setting_estimate_presentation.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';

SlotRecord row({
  String machine = 'SマイジャグラーVKD',
  int games = 10000,
  int bb = 44,
  int rb = 43,
  String? confirmed,
}) => SlotRecord(
  store: 'saiwaichou',
  day: '2026-09-28',
  machine: machine,
  rack: 123,
  games: games,
  bb: bb,
  rb: rb,
  confirmedSetting: confirmed,
);

const machines = [
  'SマイジャグラーVKD',
  'SネオアイムジャグラーEXKK',
  'Sハナハナホウオウ天翔EX30',
  'SBニューキングハナハナVPA30',
  'SキングハナハナSP30',
  'Sドラゴンハナハナ閃光SP30',
];

Widget host(Widget child, {bool viewer = true}) {
  final app = MaterialApp(
    theme: buildAppTheme(),
    home: Scaffold(body: SingleChildScrollView(child: child)),
  );
  return viewer ? SettingEstimatePresentation(child: app) : app;
}

void main() {
  test('全対応機種で必ず重複なしの上位2候補、残りの重みを消さない', () {
    for (final machine in machines) {
      for (final g in [100, 500, 1000, 3000, 8000, 20000]) {
        final e = estimateSetting(
          row(machine: machine, games: g, bb: g ~/ 250, rb: g ~/ 300),
        )!;
        expect(e.topTwo.length, 2);
        expect(e.topTwo.map((f) => f.setting).toSet().length, 2);
        expect(e.topTwo.first.setting, e.setting);
        expect(e.topTwoWeight + e.outsideWeight, closeTo(1, 1e-12));
        for (var i = 0; i < e.ranked.length; i++) {
          expect(e.ranked[i].weight.isFinite, isTrue);
          for (var j = i + 1; j < e.ranked.length; j++) {
            expect(
              e.topTwoWeight + 1e-12,
              greaterThanOrEqualTo(e.ranked[i].weight + e.ranked[j].weight),
            );
          }
        }
      }
    }
  });

  test('既存のモデル内重み・範囲を変えずに2候補を取り出す', () {
    final e = estimateSetting(row())!;
    expect(e.pairLabel, '6／5');
    expect(e.support, 51.2);
    expect(e.range80, ['4', '5', '6']);
    expect(e.topTwoWeight, lessThan(1));
    expect(e.pairWeightLabel, contains('候補外'));
  });

  test('100Gで無当選でも2候補は参考扱いで残りの重みは半分以上', () {
    final e = estimateSetting(row(games: 100, bb: 0, rb: 0))!;
    expect(e.pairLabel, '1／2');
    expect(e.pairCaution, '少数G・参考');
    expect(e.outsideWeight, greaterThan(.5));
  });

  test('設定Vを勝手に5や6へ変換しない・手入力情報は計算に使わない', () {
    final e = estimateSetting(
      row(machine: machines[3], games: 20000, bb: 79, rb: 54),
    )!;
    expect(e.pairLabel, 'V／4');
    expect(
      estimateSetting(row(confirmed: '4以上'))!.pairWeightLabel,
      estimateSetting(row())!.pairWeightLabel,
    );
  });

  test('0G・異常値・負の回数・未対応型式は2候補を作らない', () {
    for (final r in [
      row(games: 0),
      row(games: 88888888),
      row(bb: -1),
      row(rb: 501),
      row(games: 1, bb: 1, rb: 1),
      row(machine: 'マイジャグラーVI'),
    ]) {
      expect(estimateSetting(r), isNull);
    }
  });

  testWidgets('ブラウザの表・グラフ・遷移後の台詳細がすべて2候補', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final r = row();
    await tester.pumpWidget(
      SettingEstimatePresentation(
        child: MaterialApp(
          theme: buildAppTheme(),
          home: ViewerMachinePage(
            data: ViewerData(records: [r]),
            store: r.store,
            machine: r.machine,
            day: r.day,
          ),
        ),
      ),
    );
    expect(find.text('推定2候補'), findsOneWidget);
    expect(find.text('6／5'), findsOneWidget);
    expect(find.text('4・5・6'), findsNothing);
    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    expect(find.text('候補 6／5（参考）'), findsOneWidget);
    await tester.tap(find.text('123'));
    await tester.pumpAndSettle();
    expect(find.text('BB/RB推定2候補：設定 6／5'), findsOneWidget);
    expect(find.textContaining('全設定を分母'), findsOneWidget);
    expect(find.textContaining('中央80%'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Android側の詳細表示は従来の範囲を維持', (tester) async {
    await tester.pumpWidget(host(RackStats(record: row()), viewer: false));
    expect(find.textContaining('中央80%'), findsOneWidget);
    expect(find.textContaining('推定2候補'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ブラウザでも手入力の設定情報を表で優先', (tester) async {
    final r = row(confirmed: '4以上');
    await tester.pumpWidget(
      host(
        MachineDataTable(
          entries: [
            (r, scoreRecord(r, [r])),
          ],
          onTap: (_, _) {},
        ),
      ),
    );
    expect(find.text('設定情報 4以上'), findsOneWidget);
    expect(find.text('6／5'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ViewerAppがルートから全経路に2候補表示を適用', (tester) async {
    await tester.pumpWidget(const ViewerApp());
    await tester.pumpAndSettle();
    expect(
      SettingEstimatePresentation.twoChoicesOf(
        tester.element(find.byType(ViewerHome)),
      ),
      isTrue,
    );
  });
}
