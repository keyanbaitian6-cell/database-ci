import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/machine_sections.dart';
import 'package:database_android/models.dart';
import 'package:database_android/scoring.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';
import 'package:database_android/viewer_pages.dart';

Map<String, dynamic> fixture({String type = 'normal', String rate = '20'}) {
  final records = <Map<String, dynamic>>[];
  for (var ago = 0; ago < 7; ago++) {
    final day = DateTime(
      2026,
      10,
      1,
    ).subtract(Duration(days: ago)).toIso8601String().substring(0, 10);
    for (var rack = 1; rack <= 8; rack++) {
      records.add({
        'store': 'c740601',
        'rate': rate,
        'machine': '試験機種',
        'rack': rack,
        'day': day,
        'games': 3000,
        'bb': (type == 'other' ? 9 - rack : rack) * 2,
        'rb': type == 'other' ? 9 - rack : rack,
        'at_art': 0,
        'my': rack * 500,
        'detail_url':
            'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v06-001.php?cd_dai=$rack#${day.replaceAll('-', '')}',
        'graph': {
          'kind': 'daily',
          'zero_y': 100,
          'points': [
            [0, 100],
            [10, 20],
            [20, 40],
          ],
        },
      });
    }
  }
  return {
    'format': 'pscube-viewer',
    'version': 1,
    'machines': [
      {
        'store': 'c740601',
        'rate': rate,
        'machine': '試験機種',
        'expected_count': 8,
        'machine_type': type,
        'url':
            'https://www.pscube.jp/dedamajyoho-P-townDMMpachi/c740601/cgi-bin/nc-v05-011.php?cd_ps=2&bai=$rate',
      },
    ],
    'records': records,
  };
}

void main() {
  test(
    'MY remains MY; seven days, original curves and rate identity survive adaptation',
    () {
      final data = ViewerData.parse(jsonEncode(fixture()));
      expect(data.source, 'pscube');
      expect(data.records.length, 56);
      final r = data.records.first;
      expect(r.store, 'pscube:c740601:20');
      expect(r.maxHold, isNull);
      expect(r.my, 500);
      expect(r.outputLabel, 'MY');
      expect(r.graph!.curve, [
        [0.0, 100.0],
        [10.0, 20.0],
        [20.0, 40.0],
      ]);
      expect(viewerStoreNames(data.records), {
        'pscube:c740601:20': 'P-STATION（20スロ）',
      });
      final another = ViewerData.parse(jsonEncode(fixture(rate: '5')));
      expect(another.records.first.key, isNot(r.key));
    },
  );
  test('other profile uses MY for score and next-day evidence', () {
    final data = ViewerData.parse(jsonEncode(fixture(type: 'other')));
    final row = data.records
        .where((r) => r.day == '2026-10-01' && r.rack == 8)
        .single;
    final score = scoreRecord(row, data.records);
    expect(score.hits, isNull);
    expect(score.positive, 25);
    expect(score.retention, 18.75);
    expect(score.total, greaterThan(70));
    final evidence = nextDayEvidence(row, data.records);
    expect(evidence.index, greaterThan(50));
    expect(evidence.todayText, contains('MY順位'));
  });
  test('mismatched rack URL and invalid day reject the imported payload', () {
    final raw = fixture();
    (raw['records'] as List).first['day'] = '2026-02-30';
    expect(() => ViewerData.parse(jsonEncode(raw)), throwsFormatException);
    final wrong = fixture();
    (wrong['records'] as List).first['rack'] = 999;
    expect(() => ViewerData.parse(jsonEncode(wrong)), throwsFormatException);
  });
  testWidgets(
    'P’s CUBE uses the existing home, date bar, table and graph widgets',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(393, 852));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final data = ViewerData.parse(jsonEncode(fixture()));
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: ViewerHome(initialData: data),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(ViewerDateBar), findsOneWidget);
      // 「日次学習・採用中の候補」のボタンが増え、翌日候補のカードは最初の画面の外になった（2026-11-11）。送ってから確かめる。
      await tester.scrollUntilVisible(
        find.byType(NextDayCandidatesCard),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.byType(NextDayCandidatesCard), findsOneWidget);
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 5000));
      await tester.pumpAndSettle();
      expect(find.text('database 閲覧'), findsOneWidget);
      expect(find.text('P-STATION（20スロ）'), findsOneWidget);
      expect(find.textContaining('準備版'), findsNothing);
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: ViewerMachinePage(
            data: data,
            store: data.records.first.store,
            machine: '試験機種',
            day: '2026-10-01',
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(MachineDataTable), findsOneWidget);
      expect(find.text('MY'), findsOneWidget);
      expect(find.text('最大持玉'), findsNothing);
      await tester.tap(find.text('グラフ表示'));
      await tester.pumpAndSettle();
      expect(find.byType(GraphGrid), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  test('P-STATIONで my=null（サイトセブン補完）が混在しても採点クラッシュせず0枚扱いもしない', () {
    SlotRecord pscubeRec(String day, int rack, int? my, {int bb = 10, int rb = 10}) =>
        SlotRecord(
          store: 'pscube:c1:20',
          day: day,
          machine: '試験AT機',
          rack: rack,
          games: 3000,
          bb: bb,
          rb: rb,
          extra: {
            'source': 'pscube',
            'source_store': 'c1',
            'rate': '20',
            'machine_type': 'other',
            'my': my,
            if (my == null) 'source_site': 'site777',
          },
        );
    final basePool = [
      pscubeRec('2026-09-30', 10, 1000),
      pscubeRec('2026-09-30', 11, 2000),
      pscubeRec('2026-09-30', 12, 3000),
      pscubeRec('2026-10-01', 1, 1500),
    ];
    final withNullPool = [
      ...basePool,
      pscubeRec('2026-09-30', 13, null),
    ];
    final sClean = scoreRecord(basePool.last, basePool);
    final sWithNull = scoreRecord(withNullPool[3], withNullPool);
    expect(sWithNull.maxHold, sClean.maxHold);
    expect(sWithNull.holdReferenceCount, 3);

    final nullRow = pscubeRec('2026-10-01', 2, null);
    final sNull = scoreRecord(nullRow, [...basePool, nullRow]);
    expect(sNull.maxHold, isNull);

    // AT機の nextDayEvidence / varietyHitPercent でも my=null を0枚扱いせず除外する。
    final days = ['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01'];
    final atAll = [
      for (final d in days) ...[
        pscubeRec(d, 1, 3000),
        pscubeRec(d, 2, 2000),
        pscubeRec(d, 3, 1000),
        pscubeRec(d, 4, null),
      ],
    ];
    final evNull = nextDayEvidence(
      atAll.firstWhere((r) => r.day == '2026-10-01' && r.rack == 4),
      atAll,
    );
    expect(evNull.rawIndex, isNull);
    expect(evNull.todayText, contains('MY未取得'));
    final evOne = nextDayEvidence(
      atAll.firstWhere((r) => r.day == '2026-10-01' && r.rack == 1),
      atAll,
    );
    expect(evOne.today!.peers, 3);
    expect(
      varietyHitPercent(
        atAll.firstWhere((r) => r.day == '2026-10-01' && r.rack == 4),
        atAll,
      ).percent,
      isNull,
    );

    // サイトセブン補完（at_art=null）で bb=0, rb=0 かつグラフ無しのAT機は「当たり0回省略」扱いしない。
    final s777NoGraph = SlotRecord(
      store: 'pscube:c740601:20',
      day: '2026-10-01',
      machine: '試験AT機',
      rack: 99,
      games: 2000,
      bb: 0,
      rb: 0,
      extra: const {
        'source': 'pscube',
        'source_site': 'site777',
        'source_store': 'c740601',
        'rate': '20',
        'machine_type': 'other',
        'my': null,
        'at_art': null,
      },
    );
    expect(s777NoGraph.graphNotNeeded, isFalse);
    final sNoGraph = scoreRecord(s777NoGraph, [s777NoGraph]);
    expect(sNoGraph.positive, isNull);
    expect(sNoGraph.retention, isNull);
  });
}
