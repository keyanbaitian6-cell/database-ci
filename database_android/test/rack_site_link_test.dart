import 'dart:convert';
import 'dart:io';

import 'package:database_android/candidate_list_page.dart';
import 'package:database_android/models.dart';
import 'package:database_android/rack_site_link.dart';
import 'package:database_android/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// 狙い台一覧の台番号からデータサイトのその台へ（2026-11-17 利用者「狙い台一覧からはピーステはサイトセブン、
/// メルヘンは取得元のデータサイトへその台番へ飛べるようにして。共有カレンダーの翌日候補と同じだね」）。
/// 規則は共有カレンダー（share_viewer/daily_learning.mjs の dailyRackUrl、試験 test_daily_learning.mjs）と同じ。
void main() {
  final now = DateTime.parse('2026-11-14T10:00:00+09:00');

  test('メルヘンは台のグラフの対象日のページ', () {
    expect(
      rackSiteUrl('nagamachiminami', 1162, '2026-11-14', now),
      'https://meruhenworld.pt.teramoba2.com/nagamachiminami/standgraph/?rack_no=1162&target_date=2026-11-14',
    );
    expect(
      rackSiteUrl('saiwaichou', 710, '2026-11-13', now),
      'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph/?rack_no=710&target_date=2026-11-13',
    );
  });

  test('P-STATIONはサイトセブンの出玉詳細（共有カレンダーと同じ値）', () {
    const models = {1286: '120141'};
    String? site777(String day, [DateTime? at]) =>
        rackSiteUrl('pscube:c740601:20', 1286, day, at ?? now, models: models);
    const base = 'https://m.site777.jp/f/D4000.do?pmc=04034001&mdc=120141';
    expect(site777('2026-11-14'), '$base&dtdd=0&dn=1286');
    expect(site777('2026-11-13'), '$base&dtdd=1&dn=1286');
    expect(
      site777('2026-11-15'),
      '$base&dtdd=0&dn=1286',
      reason: '翌日の分は今日の分を開く',
    );
    expect(
      site777('2026-11-13', DateTime.parse('2026-11-14T02:30:00+09:00')),
      '$base&dtdd=0&dn=1286',
      reason: '3時までは前の営業日',
    );
    expect(site777('2026-11-08'), '$base&dtdd=6&dn=1286');
    expect(site777('2026-11-07'), '$base&dtdd=7&dn=1286');
    expect(site777('2026-11-06'), isNull, reason: 'サイトが見せる8日分より古い日はリンクにしない');
    for (final day in [
      '2026-13-01',
      '2026-11-00',
      '2026-00-10',
      '2026-11-31',
    ]) {
      expect(site777(day), isNull, reason: day);
    }
    expect(
      rackSiteUrl('pscube:c740601:20', 1287, '2026-11-14', now, models: models),
      isNull,
      reason: '機種の番号が分からない台はリンクにしない',
    );
    expect(
      rackSiteUrl('pscube:c999999:20', 1286, '2026-11-14', now, models: models),
      isNull,
    );
    expect(
      site777('2026-11-14')!.contains('pscube.jp'),
      isFalse,
      reason: 'P’s CUBEへは飛ばさない',
    );
  });

  test('機種の番号は、その台のいちばん新しいサイトセブンの記録の出典URLから', () {
    SlotRecord row(
      int rack,
      String day, {
      String? mdc,
      String site = 'site777',
      String store = 'pscube:c740601:20',
    }) => SlotRecord(
      store: store,
      day: day,
      machine: 'A',
      rack: rack,
      games: 1000,
      bb: 1,
      rb: 1,
      extra: {
        'source': 'pscube',
        'source_site': site,
        if (mdc != null)
          'source_url':
              'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=$mdc&bn=1&soc=1&sw=1&pan=1&dtdd=0',
      },
    );
    final rows = [
      row(1286, '2026-11-10', mdc: '111'),
      row(1286, '2026-11-12', mdc: '120141'),
      row(1286, '2026-11-11', mdc: '222'),
      row(1300, '2026-11-12'),
      row(1301, '2026-11-12', mdc: '1x'),
      row(1302, '2026-11-12', mdc: '5', site: 'anaslo'),
      row(1286, '2026-11-13', mdc: '999', store: 'saiwaichou'),
    ];
    expect(rackModelCodes(rows, 'pscube:c740601:20'), {1286: '120141'});
  });

  testWidgets('狙い台一覧：台番号を押すとサイトの翌日のページ、行のほかの所は台の詳細', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 2400));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final doc = jsonDecode(
      File('../database/tests/fixtures/normal_next_day_rows.json')
          .readAsStringSync(),
    ) as Map<String, dynamic>;
    final all = [
      for (final r in doc['rows'] as List)
        SlotRecord.fromJson({
          ...Map<String, dynamic>.from(r as Map),
          'store': 'saiwaichou',
        }),
    ];
    const day = '2026-10-20';
    final list = candidateListRows('saiwaichou', day, all);
    expect(list, isNotEmpty);
    final rack = list.first.candidate.record.rack;
    final opened = <String>[];
    final picked = <int>[];
    var allow = true;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: CandidateListPage(
          store: 'saiwaichou',
          day: day,
          records: all,
          onPick: (r) => picked.add(r.rack),
          openSite: (url) {
            opened.add(url);
            return allow;
          },
        ),
      ),
    );
    final link = find.byKey(ValueKey('candidate-site-$rack'));
    expect(link, findsOneWidget);
    expect(
      tester.getSize(link).height,
      greaterThanOrEqualTo(48),
      reason: '押しやすい高さ',
    );
    await tester.tap(link);
    await tester.pump();
    expect(opened, [
      'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph/?rack_no=$rack&target_date=2026-10-21',
    ], reason: '候補が向けている日（選択日の翌日）');
    expect(picked, isEmpty, reason: '台番号はサイト、詳細は開かない');
    await tester.tap(find.byKey(ValueKey('candidate-row-$rack')));
    expect(picked, [rack]);
    // 開けなかった（ポップアップを止められた）ときは知らせる。
    allow = false;
    await tester.tap(link);
    await tester.pump();
    expect(find.textContaining('$rack番のサイトのページを開けませんでした'), findsOneWidget);
  });
}
