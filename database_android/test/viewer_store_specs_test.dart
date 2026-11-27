import 'package:database_android/calendar_day_page.dart';
import 'package:database_android/daily_learning_page.dart';
import 'package:database_android/daily_net_page.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/shared_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _pstation = 'pscube:c740601:20';

SlotRecord _site777Rack(
  int rack, {
  String day = '2026-11-25',
  String machine = 'マイジャグラーV',
  int games = 5000,
  int bb = 20,
  int rb = 15,
  int estimate = 1200,
  bool sure = true,
  int? my = 2000,
}) => SlotRecord(
  store: _pstation,
  day: day,
  machine: machine,
  rack: rack,
  games: games,
  bb: bb,
  rb: rb,
  extra: {
    'source': 'pscube',
    'source_site': 'site777',
    'source_url':
        'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=123456',
    'my': my,
    'at_art': 0,
    'net_medals': null,
    'net_estimate': {
      'value': estimate,
      'sure': sure,
      'method': 'site777-axis-pixels-v2',
    },
  },
);

SlotRecord _anasloRack(
  int rack, {
  String day = '2026-11-04',
  int estimate = 400,
}) => SlotRecord(
  store: _pstation,
  day: day,
  machine: 'マイジャグラーV',
  rack: rack,
  games: 4000,
  bb: 15,
  rb: 10,
  extra: {
    'source': 'pscube',
    'source_site': 'anaslo',
    'my': null,
    'at_art': 0,
    'net_medals': null,
    'net_estimate': {
      'value': estimate,
      'sure': true,
      'method': 'anaslo-graph-v1',
    },
  },
);

SlotRecord _exactPscubeRack(int rack, {String day = '2026-11-20', int net = 800}) =>
    SlotRecord(
      store: _pstation,
      day: day,
      machine: 'ﾏｲｼﾞｬｸﾞﾗｰV',
      rack: rack,
      games: 5000,
      bb: 18,
      rb: 14,
      extra: {
        'source': 'pscube',
        'my': 1800,
        'at_art': 0,
        'net_medals': net,
      },
    );

void main() {
  testWidgets('CalendarDayPage：P-STATION のサイトセブン推定差枚はアナスロと誤記せず出典と推定注記を出す', (
    tester,
  ) async {
    final rows = [
      _site777Rack(101, estimate: 1500, sure: true),
      _site777Rack(102, estimate: -300, sure: false),
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarDayPage(
          store: _pstation,
          day: '2026-11-25',
          records: rows,
          eventFor: () => null,
          onEditEvent: () async {},
        ),
      ),
    );
    expect(find.textContaining('サイトセブンのグラフ画像から計算'), findsWidgets);
    expect(find.textContaining('アナスロの集計時点の値'), findsNothing);
    expect(find.textContaining('確定値ではありません（※は要確認）'), findsOneWidget);
  });

  testWidgets('CalendarDayPage：P-STATION でサイトセブンとアナスロが混在する日は両方の出典を出す', (
    tester,
  ) async {
    final rows = [
      _site777Rack(101, day: '2026-11-25', estimate: 1000),
      _anasloRack(102, day: '2026-11-25', estimate: 400),
    ];
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarDayPage(
          store: _pstation,
          day: '2026-11-25',
          records: rows,
          eventFor: () => null,
          onEditEvent: () async {},
        ),
      ),
    );
    expect(
      find.textContaining('サイトセブンのグラフ画像から計算・アナスロの集計時点の値'),
      findsWidgets,
    );
  });

  testWidgets('MachineDataTable：メルヘンで異常数値の台があっても10列がずれず例外を出さない', (
    tester,
  ) async {
    final normal = SlotRecord(
      store: 'nagamachiminami',
      day: '2026-11-25',
      machine: 'マイジャグラーV',
      rack: 101,
      games: 5000,
      bb: 20,
      rb: 15,
      extra: {'jo_net': 900},
    );
    final broken = SlotRecord(
      store: 'nagamachiminami',
      day: '2026-11-25',
      machine: 'マイジャグラーV',
      rack: 102,
      games: 88888888,
      bb: 0,
      rb: 0,
    );
    final score = const ScoreResult(
      total: 62.5,
      hits: 30,
      maxHold: 10,
      positive: 10,
      retention: 10,
      provisional: false,
      referenceCount: 20,
      reasons: [],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MachineDataTable(
              entries: [
                (normal, score),
                (
                  broken,
                  const ScoreResult(
                    total: null,
                    hits: null,
                    maxHold: null,
                    positive: null,
                    retention: null,
                    provisional: true,
                    referenceCount: 0,
                    reasons: [],
                  ),
                ),
              ],
              onTap: (_, _) {},
            ),
          ),
        ),
      ),
    );
    expect(tester.takeException(), isNull);
    expect(find.text('異常'), findsOneWidget);
    // 異常行の「—」は BB・RB・合成・BB確率・RB確率・最大持玉・差枚・推定設定の8個
    expect(find.text('—'), findsAtLeastNWidgets(7));
    expect(find.text('保留'), findsOneWidget);
  });

  testWidgets(
    'MachineDataTable：P-STATION の確定・推定混在でも列見出しが推定差枚になり、P-STATION用の※説明を出す',
    (tester) async {
      final exact = _exactPscubeRack(101, day: '2026-11-25', net: 800);
      final est = _site777Rack(
        102,
        day: '2026-11-25',
        estimate: -100,
        sure: false,
      );
      const s = ScoreResult(
        total: 55.0,
        hits: 30,
        maxHold: 10,
        positive: 10,
        retention: 5,
        provisional: false,
        referenceCount: 20,
        reasons: [],
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: MachineDataTable(
                entries: [(exact, s), (est, s)],
                onTap: (_, _) {},
              ),
            ),
          ),
        ),
      );
      expect(find.text('推定差枚'), findsOneWidget);
      expect(find.textContaining('うち推定1台・確定値ではありません'), findsOneWidget);
      expect(find.textContaining('※＝グラフからの推定で不確かな値（要確認）'), findsOneWidget);
      expect(find.textContaining('回転数から選び直した推定'), findsNothing);
    },
  );

  testWidgets('DaySummaryCard：P-STATION サイトセブン推定差枚の注記と重複警告の半角カナ全角化', (
    tester,
  ) async {
    final r1 = _site777Rack(101, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', estimate: 1200);
    final r2 = _site777Rack(102, machine: 'ﾏｲｼﾞｬｸﾞﾗｰV', estimate: 300);
    const s = ScoreResult(
      total: 60.0,
      hits: 30,
      maxHold: 10,
      positive: 10,
      retention: 10,
      provisional: false,
      referenceCount: 20,
      reasons: [],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: DaySummaryCard(entries: [(r1, s), (r2, s)], onPick: (_, _) {}),
          ),
        ),
      ),
    );
    expect(find.textContaining('記録内の推定差枚合計 +1,500枚'), findsOneWidget);
    expect(find.textContaining('サイトセブンやアナスロからの推定差枚を含みます'), findsOneWidget);
    // 重複警告（games/bb/rb が同一）の機種名は半角カナのまま出さない
    expect(find.textContaining('マイジャグラーV 101・102番台'), findsOneWidget);
    expect(find.textContaining('ﾏｲｼﾞｬｸﾞﾗｰV'), findsNothing);
  });

  testWidgets('DailyNetPage：P-STATION の注記に推定差枚と（※N）の説明を含める', (tester) async {
    final rows = [_site777Rack(101, estimate: -200, sure: false)];
    await tester.pumpWidget(
      MaterialApp(
        home: DailyNetPage(
          records: rows,
          store: _pstation,
          day: '2026-11-25',
        ),
      ),
    );
    expect(find.text('1/1（※1）'), findsOneWidget);
    expect(find.textContaining('サイトセブン・アナスロ由来の推定差枚は確定値ではありません'), findsOneWidget);
    expect(find.textContaining('推定が不確かな要確認の台数'), findsOneWidget);
  });

  testWidgets('NextDayCandidatesCard から日次学習画面へ遷移すると allRecords が引き継がれる', (
    tester,
  ) async {
    final rows = [_site777Rack(101)];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-11-25',
              store: _pstation,
              candidates: const [],
              machines: 1,
              judged: 0,
              allRecords: rows,
              onPick: (_) {},
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('日次学習・採用中の候補'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    final page = tester.widget<DailyLearningPage>(find.byType(DailyLearningPage));
    expect(page.store, _pstation);
    expect(page.records, rows);
  });
}
