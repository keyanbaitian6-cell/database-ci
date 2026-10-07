import 'package:database_android/data_checks.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

SlotRecord rec(int day, int rack, {int games = 6000, int? hits}) => SlotRecord(
  store: 'nagamachiminami',
  day: '2026-09-${day.toString().padLeft(2, '0')}',
  machine: '通常機種',
  rack: rack,
  games: games,
  bb: hits ?? (rack == 1 ? 80 : 10 + rack),
  rb: 0,
  maxHold: rack == 1 ? 19000 : 1000,
  graph: const GraphMeasurement(
    baselineY: 200,
    peakY: 100,
    troughY: 200,
    endY: 100,
  ),
);
List<SlotRecord> steady() => [
  for (var d = 1; d <= 10; d++)
    for (var rack = 1; rack <= 8; rack++) rec(d, rack),
];

void main() {
  test('88点ちょうど以上は注目から除外、87.9と未採点は除外しない', () {
    final all = steady();
    final e = nextDayEvidence(
      all.firstWhere((r) => r.day == '2026-09-10' && r.rack == 1),
      all,
    );
    expect(e.todayUsed, isTrue);
    expect(e.stabilityZ, greaterThanOrEqualTo(1.96));
    expect(qualifiesForNextDayFocus(e, 87.9), isTrue);
    expect(qualifiesForNextDayFocus(e, null), isTrue);
    expect(qualifiesForNextDayFocus(e, 88), isFalse);
    expect(qualifiesForNextDayFocus(e, 100), isFalse);
  });
  test('当日の得点が88以上でも長期上位の集合には残る', () {
    final all = steady();
    final picks = provisionalNextDayCandidates(
      all.where((r) => r.day == '2026-09-10').toList(),
      all,
    ).candidates;
    final c = picks.firstWhere((c) => c.record.rack == 1);
    expect(scoreRecord(c.record, all).total, greaterThanOrEqualTo(88));
    expect(candidateIsFocus(c, all), isFalse);
    expect(focusReason(nextDayEvidence(c.record, all), 88), contains('88点以上'));
  });
  test('当日0G・499G・比較不足は長期上位でも注目にしない', () {
    for (final games in [0, 499, 19000]) {
      final all = [
        for (final r in steady())
          if (r.day == '2026-09-10' && r.rack == 1)
            rec(10, 1, games: games, hits: games == 19000 ? 80 : 0)
          else
            r,
      ];
      final e = nextDayEvidence(
        all.firstWhere((r) => r.day == '2026-09-10' && r.rack == 1),
        all,
      );
      expect(e.todayUsed, isFalse);
      expect(qualifiesForNextDayFocus(e, null), isFalse);
      expect(e.todayText, contains('入っていません'));
    }
  });
  test('全台同じ成績ならz=0、指数50の長期上位だけで注目なし', () {
    final all = [for (final r in steady()) r.copyWith(bb: 20)];
    final picks = provisionalNextDayCandidates(
      all.where((r) => r.day == '2026-09-10').toList(),
      all,
    ).candidates;
    expect(picks.length, 2);
    for (final c in picks) {
      expect(nextDayEvidence(c.record, all).stabilityZ, 0);
      expect(candidateIsFocus(c, all), isFalse);
    }
  });
  test('同じ生指数なら、その日の回転数が多い台を使用日数・最新使用日・台番より先に上へ', () {
    NextDayEvidence e(int rack, int games, int days, String last, double raw) =>
        NextDayEvidence(rec(10, rack, games: games), [
          for (var i = 0; i < days; i++)
            NextDayContribution(last, 4000, 8, .8, 20),
        ], raw);
    expect(
      compareNextDayEvidence(
        e(8, 6000, 3, '2026-09-09', 55),
        e(1, 5000, 4, '2026-09-10', 55),
      ),
      lessThan(0),
    );
    expect(
      compareNextDayEvidence(
        e(1, 5000, 4, '2026-09-10', 55),
        e(8, 5000, 4, '2026-09-10', 55),
      ),
      lessThan(0),
    );
    expect(
      compareNextDayEvidence(
        e(8, 1000, 4, '2026-09-10', 55.1),
        e(1, 9000, 4, '2026-09-10', 55),
      ),
      lessThan(0),
    );
  });
  test('同じ生指数では使用日数、最新使用日、台番の順に決める', () {
    NextDayEvidence e(int rack, int days, String last, double raw) =>
        NextDayEvidence(rec(10, rack), [
          for (var i = 0; i < days; i++)
            NextDayContribution(last, 4000, 8, .8, 20),
        ], raw);
    expect(
      compareNextDayEvidence(
        e(1, 3, '2026-09-10', 55),
        e(8, 4, '2026-09-09', 55),
      ),
      greaterThan(0),
    );
    expect(
      compareNextDayEvidence(
        e(1, 4, '2026-09-09', 55),
        e(8, 4, '2026-09-10', 55),
      ),
      greaterThan(0),
    );
    expect(
      compareNextDayEvidence(
        e(1, 4, '2026-09-10', 55),
        e(8, 4, '2026-09-10', 55),
      ),
      lessThan(0),
    );
    expect(
      compareNextDayEvidence(
        e(1, 4, '2026-09-10', 55.001),
        e(8, 4, '2026-09-10', 55.002),
      ),
      greaterThan(0),
    );
  });
  test('未来の台・別店舗・別機種を足しても内訳と注目判定を変えない', () {
    final all = steady(), row = rec(10, 1);
    final extra = [
      ...all,
      rec(11, 1, hits: 1),
      rec(10, 1).copyWith(store: 'saiwaichou', bb: 1),
      rec(10, 1).copyWith(machine: '別機種', bb: 1),
    ];
    final a = nextDayEvidence(row, all), b = nextDayEvidence(row, extra);
    expect(b.rawIndex, a.rawIndex);
    expect(b.stabilityZ, a.stabilityZ);
    expect(
      regularCandidateDetail(row, extra, b),
      isNot(contains('2026-09-11')),
    );
    expect(nextDayBottomScenario(row, all), contains('他台は固定'));
    expect(nextDayBottomScenario(row, all), contains('★継続の予測ではありません'));
  });
  test('iPhoneの閲覧ページ用：専門用語のあとに意味を添え、数字と判定は同じ', () {
    final all = steady();
    final row = all.firstWhere((r) => r.day == '2026-09-10' && r.rack == 1);
    final e = nextDayEvidence(row, all);
    final score = scoreRecord(row, all).total;
    final plain = regularCandidateDetail(row, all, e);
    final explained = regularCandidateDetail(row, all, e, explain: true);
    expect(explained, isNot(plain));
    // 同じ数字・同じ判定を出す。
    expect(explained, contains('z=${e.stabilityZ.toStringAsFixed(2)}'));
    expect(explained, contains('寄与${signedContribution(e.today!.gap!)}'));
    expect(explained, contains('☆ 長期傾向の上位'));
    expect(plain, contains('☆ 長期傾向の上位'));
    // 専門用語のあとに意味がある。
    expect(
      explained,
      contains('当たり順位 上（同じ日・同じ機種で回転数が近い台の中で、当たりの回数が多い方から4分の1以内）'),
    );
    expect(explained, contains('（この日だけで見た当たりの軽さ。0が平均'));
    expect(
      explained,
      contains('安定性 z=${e.stabilityZ.toStringAsFixed(2)}（毎日のように当たりが多い側だったかの目安'),
    );
    expect(
      explained,
      contains('当日の合計点（この日の結果の点数）が${score!.toStringAsFixed(1)}点で、88点以上のため'),
    );
    expect(explained, contains('翌日最下位の仮定（もし翌日この台が同じ機種で一番当たりが少なかったら）'));
    expect(focusReason(e, score, explain: true), startsWith('★注目にしない理由'));
    expect(focusReason(e, 80, explain: true), startsWith('★注目の条件をすべて満たしています'));
    // Androidアプリ（explainなし）の文は変えていない。
    expect(focusReason(e, score), contains('88点以上のため★注目から除外'));
    expect(e.todayText, startsWith('選択日 6000G・当たり順位 上・寄与'));
    final skipped = nextDayEvidence(rec(10, 1, games: 499, hits: 0), [
      for (final r in all)
        if (r.day == '2026-09-10' && r.rack == 1)
          rec(10, 1, games: 499, hits: 0)
        else
          r,
    ]);
    expect(
      skipped.todayTextExplained,
      '選択日（この日）の結果は、当たりの軽さ（指数）の計算に入っていません（500G未満）',
    );
  });
  test('バラエティは88以上を理由に除外しない', () {
    final row = rec(10, 1).copyWith(machine: '少数機種');
    expect(
      candidateIsFocus(
        (record: row, index: 50, days: 0, confidence: '比較なし', variety: true),
        [row],
      ),
      isTrue,
    );
  });
  testWidgets('狭い画面の表・グラフで★と☆が混ざらない', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final rows = [rec(10, 1), rec(10, 2), rec(10, 3), rec(10, 4)];
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListView(
            children: [
              MachineSection(
                machine: '通常機種',
                entries: [for (final r in rows) (r, scoreRecord(r, rows))],
                candidateRacks: const {2},
                longTrendRacks: const {1},
                onTap: (_, _) {},
              ),
            ],
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text(' ★'), findsOneWidget);
    expect(find.text(' ☆'), findsOneWidget);
    await tester.tap(find.text('グラフ表示'));
    await tester.pumpAndSettle();
    expect(find.text('2 ★'), findsOneWidget);
    expect(find.text('1 ☆'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('カードは88以上を☆に表示し、除外理由を読める', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final all = steady();
    final candidates = provisionalNextDayCandidates(
      all.where((r) => r.day == '2026-09-10').toList(),
      all,
    ).candidates;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NextDayCandidatesCard(
              day: '2026-09-10',
              candidates: candidates,
              machines: 1,
              judged: 1,
              allRecords: all,
              onPick: (_) {},
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('☆ 1番台'), findsOneWidget);
    expect(find.textContaining('88点以上のため★注目から除外'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
