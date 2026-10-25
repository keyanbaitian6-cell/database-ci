import 'package:flutter_test/flutter_test.dart';

import 'package:database_android/backup_service.dart';
import 'package:database_android/data_checks.dart';
import 'package:database_android/main.dart';
import 'package:database_android/models.dart';
import 'package:database_android/web_import_page.dart';

const _graph = GraphMeasurement(
  baselineY: 200,
  peakY: 100,
  troughY: 250,
  endY: 150,
);

SlotRecord rec(
  int rack, {
  GraphMeasurement? graph,
  String? link,
  String day = '2026-09-18',
  int bb = 10,
  int rb = 5,
}) => SlotRecord(
  store: 'saiwaichou',
  day: day,
  machine: 'Lモンキーターン5CE',
  rack: rack,
  games: 3000,
  bb: bb,
  rb: rb,
  graph: graph,
  detailUrl: link,
);

String url(int rack) =>
    'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no=$rack&target_date=2026-09-18';

NextGraphTarget next(
  AppController c, {
  int? rack,
  String? machine = 'Lモンキーターン5CE',
  String? day = '2026-09-18',
}) => c.nextUngraphed(
  store: 'saiwaichou',
  day: day,
  machine: machine,
  rack: rack,
);

void main() {
  test('次の未取り込み台: 台番号順・末尾で先頭へ戻る・理由別の結果', () {
    final c = AppController();
    c.records = [
      rec(701, graph: _graph, link: url(701)),
      rec(702, link: url(702)),
      rec(703, graph: _graph, link: url(703)),
      rec(704, link: url(704)),
    ];
    var t = next(c);
    expect((t.rack, t.remaining, t.url), (702, 2, url(702)));
    t = next(c, rack: 702);
    expect(t.rack, 704);
    t = next(c, rack: 704); // 最後の台からは先頭の未取り込み台へ
    expect(t.rack, 702);
    // 個別グラフのURLには機種名が無いことがある → 台番号から機種を逆引き
    t = next(c, rack: 703, machine: null);
    expect(t.rack, 704);
    expect(next(c, machine: null).reason, 'unknown_machine');
    expect(next(c, day: null).reason, 'unknown_page');
    expect(next(c, machine: 'ほかの機種').reason, 'no_rows');
    c.records = [rec(701, graph: _graph, link: url(701))];
    final done = next(c);
    expect(done.reason, 'all_done');
    // 機種が全部済んだらサイト自身の機種一覧ページへ案内し、日の完了も伝える
    expect(
      done.url,
      endsWith(
        '/saiwaichou/rack_info_kt/?kind_code=21'
        '#database_next_machine=1&database_day=2026-09-18',
      ),
    );
    expect(done.dayComplete, isTrue);
    c.records = [rec(705), rec(706, link: url(706))]; // リンクなしは飛ばして次のリンクへ
    t = next(c);
    expect((t.reason, t.rack, t.url), (null, 706, url(706)));
    expect(t.warning, contains('705番台はグラフ未取得のまま残します'));
    c.records = [rec(705)];
    t = next(c);
    expect(t.reason, 'linkless');
    expect(t.url, contains('rack_info_kt'));
    expect(t.warning, contains('705番台はグラフ未取得のまま残します'));
  });

  test('対象外の機種（沖ドキ）の台は進み具合に数えない（ジャグラーオンラインで記録ができても。2026-10-12）', () {
    final c = AppController();
    c.records = [
      rec(701, graph: _graph, link: url(701)),
      SlotRecord(
        store: 'saiwaichou',
        day: '2026-09-18',
        machine: 'L／オキドキデュオ2／FR',
        rack: 421,
        games: 2400,
        bb: 17,
        rb: 5,
      ),
    ];
    expect(c.progressText(store: 'saiwaichou', day: '2026-09-18'), '2026-09-18　幸町 1/1台');
  });

  test('大当たり0回の台はグラフを取らない：次の台・進み具合・印・日の完了で済み扱い', () {
    final c = AppController();
    c.records = [
      rec(701, graph: _graph, link: url(701)),
      rec(702, link: url(702), bb: 0, rb: 0), // 0回 → 飛ばす
      rec(703, link: url(703), bb: 0, rb: 1), // RBだけでも当たりあり → 取る
      rec(704, link: url(704), bb: 0, rb: 0),
    ];
    var t = next(c);
    expect((t.rack, t.remaining), (703, 1));
    t = next(c, rack: 703);
    expect((t.rack, t.remaining), (703, 1));
    expect(c.progressText(store: 'saiwaichou', day: '2026-09-18'), '2026-09-18　幸町 3/4台');
    expect(
      c.machineStatuses(
        store: 'saiwaichou',
        day: '2026-09-18',
        machines: ['Lモンキーターン5CE'],
      )[0],
      {'done': 3, 'total': 4},
    );
    // 当たりのある台のグラフが済めば、0回の台が残っていても機種・日は完了。
    c.records = [
      rec(701, graph: _graph, link: url(701)),
      rec(702, link: url(702), bb: 0, rb: 0),
    ];
    final done = next(c);
    expect((done.reason, done.dayComplete), ('all_done', true));
    expect(c.records[1].graphNotNeeded, isTrue);
    expect(c.records[0].graphNotNeeded, isFalse);
    // 表を取り込み直して当たりが付けば、また取る対象に戻る。
    c.records = [rec(702, link: url(702), bb: 1, rb: 0)];
    expect(next(c).rack, 702);
  });

  test('個別台リンクはJSONで往復し、バックアップ取り込みで補完される', () {
    final withLink = rec(801, link: url(801));
    expect(SlotRecord.fromJson(withLink.toJson()).detailUrl, url(801));
    expect(rec(802).toJson().containsKey('detail_url'), isFalse);

    final service = BackupService();
    final local = [rec(801), rec(802, link: url(802))];
    final plan = service.plan([
      withLink.toJson(), // 同じ数値・手元にリンクなし → 補完
      rec(802).toJson(), // 手元にリンクあり・相手になし → 何もしない
    ], local);
    expect(plan.linkOnly.map((r) => r.rack), [801]);
    expect(plan.linkOnly.single.detailUrl, url(801));
    expect(plan.unchanged.map((r) => r.rack), [802]);
    expect(plan.conflicts, isEmpty);

    // グラフだけ追加するときも、手元のリンクは失わない
    final graphOnly = service.plan([rec(802, graph: _graph).toJson()], local);
    expect(graphOnly.graphOnly.single.detailUrl, url(802));
  });

  test('数値が完全に同じ台は台番号ずれの疑いとして警告する', () {
    SlotRecord same(int rack, int games) => SlotRecord(
      store: 'saiwaichou',
      day: '2026-09-18',
      machine: 'M',
      rack: rack,
      games: games,
      bb: 25,
      rb: 4,
    );
    final rows = [same(285, 3649), same(286, 3649), same(287, 2527)];
    expect(suspiciousDuplicates(rows).single.$2, [285, 286]);
    expect(duplicateWarning(rows, rack: 286), contains('285・286'));
    expect(duplicateWarning(rows, rack: 287), isNull);
    // 未稼働台（0G）が並んでいても警告しない
    expect(duplicateWarning([same(1, 0), same(2, 0)]), isNull);
  });

  test('進捗表示と直前の保存の取り消し用の控え', () {
    final c = AppController();
    c.records = [
      rec(701, graph: _graph, link: url(701)),
      rec(702, link: url(702)),
    ];
    expect(
      c.progressText(store: 'saiwaichou', day: '2026-09-18'),
      '2026-09-18　幸町 1/2台',
    );
    // 日付が分からないとき（機種一覧ページ）は今日で表示する
    c.today = () => '2026-09-18';
    expect(c.progressText(store: 'saiwaichou', day: null), contains('1/2台'));
    c.today = () => '2026-09-19';
    expect(
      c.progressText(store: 'saiwaichou', day: null),
      '2026-09-19　まだ取り込みがありません',
    );
    expect(c.progressText(store: null, day: null), '');
  });

  test('台ごとの推移: 同じ機種の直近日だけを新しい順に返す', () {
    SlotRecord day(String d, {String machine = 'M', int games = 3000}) =>
        SlotRecord(
          store: 'saiwaichou',
          day: d,
          machine: machine,
          rack: 300,
          games: games,
          bb: 10,
          rb: 5,
        );
    final all = [
      day('2026-09-10'),
      day('2026-09-11', machine: '別機種'), // 機種が変わった日は含めない
      day('2026-09-12', games: 3500),
      day('2026-09-13', games: 4000),
      day('2026-09-14'), // 基準日より後は含めない
    ];
    final trend = rackTrend(all[3], all);
    expect(trend.map((e) => e.$1.day), [
      '2026-09-13',
      '2026-09-12',
      '2026-09-10',
    ]);
    expect(rackTrend(all[3], all, limit: 2).length, 2);
  });

  test('機種一覧ページの印用: 機種ごとの取り込み状況（空白・+の違いは無視）', () {
    final c = AppController();
    c.records = [
      SlotRecord(
        store: 'saiwaichou',
        day: '2026-09-18',
        machine: 'L 別 機',
        rack: 1,
        games: 100,
        bb: 1,
        rb: 0,
        graph: _graph,
      ),
      SlotRecord(
        store: 'saiwaichou',
        day: '2026-09-18',
        machine: 'L 別 機',
        rack: 2,
        games: 100,
        bb: 1,
        rb: 1,
      ),
      SlotRecord(
        store: 'nagamachiminami',
        day: '2026-09-18',
        machine: '他店',
        rack: 1,
        games: 100,
        bb: 1,
        rb: 1,
      ),
    ];
    final status = c.machineStatuses(
      store: 'saiwaichou',
      day: '2026-09-18',
      machines: ['L+別+機', '未取込機'],
    );
    expect(status[0], {'done': 1, 'total': 2});
    expect(status[1], isNull);
    // 日付が分からないとき（機種一覧ページ）は今日で判定する。
    // 前日の「済」は出さない（今日の分を消したときに紛らわしかった）
    c.today = () => '2026-09-18';
    expect(
      c.machineStatuses(store: 'saiwaichou', day: null, machines: ['L 別 機'])[0],
      {'done': 1, 'total': 2},
    );
    c.today = () => '2026-09-19';
    expect(
      c.machineStatuses(store: 'saiwaichou', day: null, machines: ['L 別 機'])[0],
      isNull,
    );
    expect(c.machineStatuses(store: null, day: null, machines: ['x']), [null]);
  });

  test('取得時刻・データ量の信頼度・翌日の参考指数', () {
    expect([1000, 1500, 3499, 3500].map(reliabilityLabel), [
      '少',
      '中',
      '中',
      '多',
    ]);
    SlotRecord at(String? stamp) => SlotRecord(
      store: 'saiwaichou',
      day: '2026-09-18',
      machine: 'M',
      rack: 1,
      games: 3000,
      bb: 10,
      rb: 5,
      capturedAt: stamp,
    );
    expect(capturedNote(at(null)), '');
    expect(capturedNote(at('2026-09-18T23:48:10')), '取得 09/18 23:48');
    expect(capturedNote(at('2026-09-18T15:05:00')), contains('早めの取得'));
    // JSONで往復する（バックアップでPC版と共有される）
    expect(
      SlotRecord.fromJson(at('2026-09-18T23:48:10').toJson()).capturedAt,
      '2026-09-18T23:48:10',
    );

    // 台301は毎日、同機種の他3台より明らかに回転・当たりが多い（3日分）
    SlotRecord day(String d, int rack, int games, int bb, int rb) => SlotRecord(
      store: 'saiwaichou',
      day: d,
      machine: 'M',
      rack: rack,
      games: games,
      bb: bb,
      rb: rb,
      maxHold: games ~/ 2,
      graph: _graph,
    );
    final all = [
      for (final d in ['2026-09-10', '2026-09-11', '2026-09-12']) ...[
        day(d, 301, 3000, 60, 20),
        day(d, 302, 2000, 8, 2),
        day(d, 303, 2100, 9, 2),
        day(d, 304, 1900, 7, 2),
      ],
    ];
    final latest = all.firstWhere(
      (r) => r.rack == 301 && r.day == '2026-09-12',
    );
    final forecast = nextDayIndex(latest, all);
    expect(forecast.days, 3);
    expect(forecast.index, greaterThan(50)); // 平均より高い傾向
    expect(forecast.index, lessThanOrEqualTo(100));
    expect(forecast.confidence, '少');
    final first = all.firstWhere((r) => r.rack == 301 && r.day == '2026-09-10');
    expect(nextDayIndex(first, all).index, isNull); // 1日分しかない → データ不足
    final selected = all.where((r) => r.day == '2026-09-12').toList();
    final candidates = provisionalNextDayCandidates(selected, all);
    expect(
      (candidates.total, candidates.eligible, candidates.candidates.length),
      (4, 4, 1),
    );
    expect(candidates.candidates.single.record.rack, 301);

    // 画面には「63 / 100」ではなく「平均より +13」と出す。素の指数だけでは
    // 50が中立であることも、上下どちらが良いのかも読み取れないため。
    expect(signedIndex(63.0), '平均より +13');
    expect(signedIndex(41.0), '平均より -9');
    expect(signedIndex(50.0), '平均より +0');
  });

  test('5日間のスランプ表示: 直近5日を古い順に。5日未満・別機種の日は数えない', () {
    SlotRecord d(int day, {String machine = 'M', bool graph = true}) =>
        SlotRecord(
          store: 'saiwaichou',
          day: '2026-09-${day.toString().padLeft(2, '0')}',
          machine: machine,
          rack: 300,
          games: 3000,
          bb: 10,
          rb: 5,
          graph: graph ? _graph : null,
        );
    final all = [for (var i = 10; i <= 16; i++) d(i), d(9, machine: '別機種')];
    final latest = all.firstWhere((r) => r.day == '2026-09-16');
    expect(slumpDays(latest, all).map((r) => r.day.substring(8)), [
      '12',
      '13',
      '14',
      '15',
      '16',
    ]);
    // 4日分しかない日は表示しない
    expect(
      slumpDays(all.firstWhere((r) => r.day == '2026-09-13'), all),
      isEmpty,
    );
    // グラフ未保存の日は数えない
    final gap = [
      ...all.where((r) => r.day != '2026-09-14'),
      d(14, graph: false),
    ];
    expect(slumpDays(latest, gap).map((r) => r.day.substring(8)), [
      '11',
      '12',
      '13',
      '15',
      '16',
    ]);
  });
}
