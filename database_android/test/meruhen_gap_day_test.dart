import 'package:database_android/app_controller.dart';
import 'package:database_android/models.dart';
import 'package:flutter_test/flutter_test.dart';

/// メルヘンの抜けた日（2026-11-04、利用者が選んだ「抜けた日を自動で取り戻す」）。
SlotRecord row(
  String day, {
  String store = 'nagamachiminami',
  String machine = '北斗',
  int rack = 1,
  bool graph = true,
  String? link = 'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info/detail?rack_no=1',
}) => SlotRecord(
  store: store,
  day: day,
  machine: machine,
  rack: rack,
  games: 3000,
  // グラフ済みの台は、大当たり0回（グラフを取らない台）として作る（graphDone が true になる）。
  bb: graph ? 0 : 15,
  rb: graph ? 0 : 5,
  detailUrl: link,
);

/// 11/1〜11/4 の4日、2機種をそろえた記録（[without] の日・機種は入れない）。
List<SlotRecord> days({Set<(String, String)> without = const {}}) => [
  for (final day in ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'])
    for (final machine in ['北斗', '番長'])
      if (!without.contains((day, machine))) row(day, machine: machine),
];

void main() {
  test('抜けが無ければ null（サイトへの通信を増やさない）', () {
    expect(
      meruhenGapDay(days(), store: 'nagamachiminami', day: '2026-11-04'),
      isNull,
    );
  });

  test('記録が1台も無い日を、記録のある最初の日より後で、新しい順に見つける', () {
    final records = days().where((r) => r.day != '2026-11-02').toList();
    expect(
      meruhenGapDay(records, store: 'nagamachiminami', day: '2026-11-04'),
      '2026-11-02',
    );
    expect(
      meruhenGapDay(
        records,
        store: 'nagamachiminami',
        day: '2026-11-04',
        skip: {'2026-11-02'},
      ),
      isNull,
      reason: '一度取り戻そうとした日はくり返さない。記録のある最初の日（11/1）より前は見ない',
    );
  });

  test('グラフが残る台がある日を見つける（個別リンクの無い台は数えない）', () {
    final records = [
      ...days(),
      row('2026-11-03', machine: '番長', rack: 2, graph: false),
    ];
    expect(
      meruhenGapDay(records, store: 'nagamachiminami', day: '2026-11-04'),
      '2026-11-03',
    );
    final linkless = [
      ...days(),
      row('2026-11-03', machine: '番長', rack: 2, graph: false, link: null),
    ];
    expect(
      meruhenGapDay(linkless, store: 'nagamachiminami', day: '2026-11-04'),
      isNull,
    );
  });

  test('前の日と次の日にある機種が、その日だけ無い日を見つける（機種一覧の途中で止まった日）', () {
    expect(
      meruhenGapDay(
        days(without: {('2026-11-02', '番長')}),
        store: 'nagamachiminami',
        day: '2026-11-04',
      ),
      '2026-11-02',
    );
    expect(
      meruhenGapDay(
        days(without: {('2026-11-01', '番長'), ('2026-11-02', '番長')}),
        store: 'nagamachiminami',
        day: '2026-11-04',
      ),
      isNull,
      reason: '前の日にも無い機種（新台）は抜けとみなさない',
    );
  });

  test('ほかの店の記録・取り込みの対象外の機種は見ない。7日より前は見ない', () {
    final records = [
      ...days(),
      row('2026-11-02', store: 'saiwaichou', machine: '北斗', graph: false),
    ];
    expect(
      meruhenGapDay(records, store: 'nagamachiminami', day: '2026-11-04'),
      isNull,
    );
    final old = [
      row('2026-10-20'),
      row('2026-10-27'),
      row('2026-11-03'),
      row('2026-11-04'),
    ];
    expect(
      meruhenGapDay(old, store: 'nagamachiminami', day: '2026-11-04'),
      '2026-11-02',
      reason: '11/2・11/1・10/31…と新しい順。10/28より前（7日の外）は見ない',
    );
    expect(
      meruhenGapDay(
        old,
        store: 'nagamachiminami',
        day: '2026-11-04',
        skip: {
          '2026-11-02',
          '2026-11-01',
          '2026-10-31',
          '2026-10-30',
          '2026-10-29',
        },
      ),
      isNull,
      reason: '10/28は前の6日の外',
    );
  });

  test('取り込みの対象外の機種（長町南のジャグラー）は、無い日があっても抜けとみなさない', () {
    final records = [
      ...days(),
      row('2026-11-01', machine: 'ジャグラー'),
      row('2026-11-03', machine: 'ジャグラー', graph: false),
    ];
    expect(
      meruhenGapDay(records, store: 'nagamachiminami', day: '2026-11-04'),
      isNull,
    );
  });
}
