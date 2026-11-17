import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:database_android/models.dart';
import 'package:database_android/store_pattern.dart';
import 'package:database_android/store_pattern_page.dart';
import 'package:database_android/theme.dart';
import 'package:database_android/viewer_data.dart';
import 'package:database_android/viewer_main.dart';

/// 店の入れ方のふり返り（2026-11-17 利用者「２だけ作る。iPhoneブラウザ版の2種類のみで」）。
const store = 'nagamachiminami';
const day = '2026-11-14';

/// メルヘンの台。差枚（ジャグラーオンラインの差枚の項目）の符号でプラス・マイナスが決まる。
SlotRecord rack(
  int number,
  bool plus, {
  String machine = 'A',
  String on = day,
  int games = 3000,
  bool? known = true,
}) => SlotRecord(
  store: store,
  day: on,
  machine: machine,
  rack: number,
  games: games,
  bb: 5,
  rb: 5,
  extra: {if (known == true) 'jo_net': plus ? 500 : -500},
);

void main() {
  test('機種の偏りは超幾何分布の確率を、比べた数で割り引く', () {
    // 10台中5台プラス。機種Aの3台が全部プラス：C(5,3)/C(10,3)=10/120。2機種比べたので2倍。
    final rows = [
      for (var i = 1; i <= 3; i++) rack(i, true, machine: 'A'),
      for (var i = 4; i <= 10; i++) rack(i, i <= 5, machine: 'B'),
    ];
    final r = storePatternDay(store, day, rows);
    expect((r.total, r.plus, r.excluded), (10, 5, 0));
    expect(r.usable, isTrue);
    final a = r.machines.firstWhere((g) => g.label == 'A');
    expect(a.plus, 3);
    expect(a.p, closeTo(10 / 120, 1e-12));
    expect(a.compared, 2);
    expect(a.adjusted, closeTo(20 / 120, 1e-12));
    expect(a.chance, PatternChance.sometimes);
    final b = r.machines.firstWhere((g) => g.label == 'B');
    expect((b.plus, b.total), (2, 7));
    expect(b.p, closeTo(1, 1e-12), reason: '7台選べば必ず2台以上プラス');
    expect(r.machines.first.label, 'A', reason: '割り引いたあとの確率の小さい順');
  });

  test('全台系がはっきりした日は「偶然では出にくい」で、履歴の印に出る', () {
    // 40台中20台プラス。機種Xの8台が全部プラス：C(20,8)/C(40,8)。比べたのは5機種。
    final rows = <SlotRecord>[
      for (var i = 0; i < 8; i++) rack(100 + i * 2, true, machine: 'X'),
      for (final (k, m) in ['P', 'Q', 'R', 'S'].indexed)
        for (var i = 0; i < 8; i++)
          rack(200 + k * 20 + i * 2, i < 3, machine: m),
    ];
    final r = storePatternDay(store, day, rows);
    expect(r.total, 40);
    final x = r.machines.firstWhere((g) => g.label == 'X');
    expect((x.plus, x.total, x.compared), (8, 8, 5));
    expect(x.chance, PatternChance.rare);
    expect(r.highlights, contains('全台系：X（8/8）'));
  });

  test('除く台：500G以下・プラスか分からない台・同じ台の重複', () {
    final rows = [
      for (var i = 1; i <= 10; i++) rack(i, i.isEven),
      rack(11, true, games: 500),
      rack(12, true, known: null), // 差枚もグラフも無く、当たりもある台は分からない
      rack(1, false), // 同じ台の2回目は後の記録
      rack(13, true, on: '2026-11-13'),
      SlotRecord(
        store: 'saiwaichou',
        day: day,
        machine: 'A',
        rack: 14,
        games: 3000,
        bb: 1,
        rb: 1,
        extra: const {'jo_net': 10},
      ),
    ];
    final r = storePatternDay(store, day, rows);
    expect((r.total, r.plus, r.excluded), (10, 5, 2));
  });

  test('末尾は店の末尾ごと、3台以上の末尾だけ比べる', () {
    final rows = [
      for (var i = 0; i < 30; i++) rack(1000 + i, i % 10 == 7 || i < 6),
    ];
    final r = storePatternDay(store, day, rows);
    expect(r.suffixes.map((g) => g.label).toList(), [
      for (var s = 0; s <= 9; s++) '末尾$s',
    ]);
    final seven = r.suffixes.firstWhere((g) => g.label == '末尾7');
    expect((seven.plus, seven.total, seven.compared), (3, 3, 10));
    final few = storePatternDay(store, day, [
      for (var i = 0; i < 22; i++) rack(1000 + i, i.isEven),
    ]);
    expect(few.suffixes.map((g) => g.label), [
      '末尾0',
      '末尾1',
    ], reason: '2台以下の末尾は比べない');
  });

  test('並び：台番が続く台だけを隣とみなし、並べ替えの結果は毎回同じ', () {
    // 101〜112番の12台で、103〜107番の5台だけプラス。5台が続く確率は 8/C(12,5)=8/792 ≒ 1%。
    final rows = [
      for (var i = 101; i <= 112; i++) rack(i, i >= 103 && i <= 107),
    ];
    final r = storePatternDay(store, day, rows);
    expect(r.run!.racks, [103, 104, 105, 106, 107]);
    expect(r.run!.label, '103〜107番');
    expect(r.run!.p, inInclusiveRange(.003, .03));
    expect(r.run!.chance, PatternChance.rare);
    expect(
      storePatternDay(store, day, rows).run!.p,
      r.run!.p,
      reason: '同じ日なら毎回同じ',
    );
    expect(r.highlights, contains('並び：103〜107番（5台）'));
    // 台番が飛ぶ（103番が無い）と、続いていない。
    final gap = storePatternDay(store, day, [
      for (final i in [
        101,
        102,
        104,
        105,
        106,
        110,
        111,
        112,
        113,
        114,
        115,
        116,
      ])
        rack(i, i <= 105),
    ]);
    expect(gap.run!.racks, [101, 102], reason: '同じ長さなら若い方。104〜105番も2台');
  });

  test('全部プラス・台が少ない日は判定しない', () {
    final all = storePatternDay(store, day, [
      for (var i = 1; i <= 12; i++) rack(i, true),
    ]);
    expect(all.usable, isFalse);
    expect(all.highlights, isEmpty);
    expect(all.run!.p, 1);
    final few = storePatternDay(store, day, [
      for (var i = 1; i <= 9; i++) rack(i, i.isEven),
    ]);
    expect(few.usable, isFalse);
    final none = storePatternDay(store, day, const []);
    expect((none.total, none.run), (0, null));
  });

  testWidgets('画面：その日の判定と履歴、履歴から日を選べる', (tester) async {
    final rows = [
      for (var i = 101; i <= 112; i++)
        rack(i, i >= 103 && i <= 107, machine: i <= 104 ? 'マイジャグラーV' : 'ハナハナ'),
      for (var i = 101; i <= 112; i++) rack(i, i.isOdd, on: '2026-11-13'),
    ];
    final data = ViewerData(records: rows);
    String? changed;
    await tester.pumpWidget(
      MaterialApp(
        home: StorePatternPage(
          data: data,
          store: store,
          day: day,
          onDayChanged: (d) => changed = d,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('店の入れ方のふり返り'), findsOneWidget);
    expect(find.textContaining('判定に使った台 12台・プラス 5台'), findsOneWidget);
    expect(find.text('全台系（機種ごと）'), findsOneWidget);
    expect(find.textContaining('いちばん長い並び：103〜107番（5台）'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('pattern-day-2026-11-13')),
      300,
    );
    await tester.tap(find.byKey(const ValueKey('pattern-day-2026-11-13')));
    await tester.pumpAndSettle();
    expect(changed, '2026-11-13');
    await tester.scrollUntilVisible(find.textContaining('探索の結果です'), 300);
    expect(find.textContaining('探索の結果です'), findsOneWidget);
    await tester.scrollUntilVisible(find.textContaining('判定に使った台'), -300);
    expect(find.textContaining('判定に使った台 12台・プラス 6台'), findsOneWidget);
  });

  testWidgets('閲覧ページの日の画面に入口があり、押すと開く（メルヘン）', (tester) async {
    await tester.binding.setSurfaceSize(const Size(393, 852));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final data = ViewerData(
      records: [for (var i = 101; i <= 112; i++) rack(i, i >= 103 && i <= 107)],
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: ViewerHome(initialData: data),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.byKey(const ValueKey('open-store-pattern'));
    await tester.scrollUntilVisible(
      button,
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.ensureVisible(button);
    await tester.pumpAndSettle();
    expect(find.text('店の入れ方のふり返り（全台系・末尾・並び）'), findsOneWidget);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.byType(StorePatternPage), findsOneWidget);
    expect(find.textContaining('いちばん長い並び：103〜107番（5台）'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  test('PC（database/store_pattern.py）と同じ数字になる（共通の試験データ）', () {
    // 2026-11-18 利用者「PCでも表示させてほしい」。正解は PC の計算で作った test/fixtures/store_pattern_cases.json。
    final doc = jsonDecode(
      File('test/fixtures/store_pattern_cases.json').readAsStringSync(),
    ) as Map<String, dynamic>;
    for (final c in doc['cases'] as List) {
      final rows = [
        for (final r in c['rows'] as List)
          SlotRecord(
            store: r['store'],
            day: r['day'],
            machine: r['machine'],
            rack: r['rack'],
            games: r['games'],
            bb: r['bb'],
            rb: r['rb'],
            extra: {
              for (final k in [
                'jo_net',
                'source',
                'my',
                'rate',
                'machine_type',
                'net_medals',
              ])
                if ((r as Map).containsKey(k)) k: r[k],
            },
          ),
      ];
      final got = storePatternDay(c['store'], c['day'], rows);
      final e = c['expected'] as Map<String, dynamic>;
      final where = '${c['store']} ${c['day']}';
      expect(
        [got.plus, got.total, got.played, got.excluded, got.usable],
        [e['plus'], e['total'], e['played'], e['excluded'], e['usable']],
        reason: where,
      );
      void groups(List<PatternGroup> actual, List expected, String kind) {
        expect(actual.length, expected.length, reason: '$where $kind');
        for (var i = 0; i < actual.length; i++) {
          final g = actual[i], x = expected[i] as List;
          expect(
            [g.label, g.plus, g.total, g.compared, g.chance.label],
            [x[0], x[1], x[2], x[3], x[5]],
            reason: '$where $kind $i',
          );
          expect(g.p, closeTo((x[4] as num).toDouble(), 1e-9));
        }
      }

      groups(got.machines, e['machines'] as List, '機種');
      groups(got.suffixes, e['suffixes'] as List, '末尾');
      if (e['run'] == null) {
        expect(got.run, isNull, reason: where);
      } else {
        final x = e['run'] as List;
        expect(got.run!.racks, x[0], reason: where);
        expect(
          got.run!.p,
          closeTo((x[1] as num).toDouble(), 1e-12),
          reason: '$where 並びの並べ替え',
        );
        expect(got.run!.chance.label, x[2]);
      }
      expect(got.highlights, e['highlights'], reason: where);
    }
  });
}
