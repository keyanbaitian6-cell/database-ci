import 'package:database_android/pscube_list_wait.dart';
import 'package:flutter_test/flutter_test.dart';

/// 実サイトの動きの模型：一番下に着く（arrive）と続きが届く。届くまでの時間は [latency]。
class FakeList {
  FakeList({
    required this.total,
    this.first = 6,
    this.batch = 20,
    this.latency = Duration.zero,
    this.loads = true,
    this.ignoredArrivals = 0,
  }) : count = first;

  final int total, first, batch;

  /// 最初の何回の到着では続きが始まらないか（着き直したときに始まるサイト）。
  int ignoredArrivals;
  final Duration latency;
  final bool loads;
  int count;
  Duration elapsed = Duration.zero;
  Duration? _arrivesAt;
  var atBottom = false;
  final actions = <PscubeScroll>[];

  Future<void> delay(Duration duration) async {
    elapsed += duration;
  }

  Future<PscubeListView> scroll(PscubeScroll action) async {
    actions.add(action);
    switch (action) {
      case PscubeScroll.arrive:
        atBottom = true;
        if (loads && count < total && _arrivesAt == null) {
          if (ignoredArrivals > 0) {
            ignoredArrivals--;
          } else {
            _arrivesAt = elapsed + latency;
          }
        }
      case PscubeScroll.nudge:
        atBottom = false;
        _arrivesAt = null; // 読み込みが始まらなかったので、もう一度下に着けば始まる
      case PscubeScroll.step:
        atBottom = actions.where((a) => a == PscubeScroll.step).length % 3 == 0;
      case PscubeScroll.none:
        break;
    }
    if (_arrivesAt != null && elapsed >= _arrivesAt!) {
      count = (count + batch).clamp(0, total);
      _arrivesAt = null;
      atBottom = false; // 台が増えて、また下に続く
    }
    return (count: count, atBottom: atBottom);
  }
}

void main() {
  test('各機種で6台の一時安定を越えて、3秒後に届く31台まで待つ', () async {
    for (var machine = 0; machine < 2; machine++) {
      final list = FakeList(
        total: 31,
        batch: 25,
        latency: const Duration(seconds: 3),
      );
      await waitForPscubeList(
        expectedCount: 31,
        isCurrent: () => true,
        scroll: list.scroll,
        delay: list.delay,
      );
      expect(list.count, 31);
      expect(list.elapsed, greaterThan(const Duration(seconds: 3)));
    }
  });

  test('台数の多い機種は20台ずつ届く64台まで、少しずつ進んで届いたところで終わる', () async {
    final list = FakeList(total: 64, first: 20);
    await waitForPscubeList(
      expectedCount: 64,
      isCurrent: () => true,
      scroll: list.scroll,
      delay: list.delay,
    );
    expect(list.count, 64);
    expect(list.elapsed, lessThan(const Duration(seconds: 30)));
    expect(
      list.actions.where((a) => a == PscubeScroll.nudge),
      isEmpty,
      reason: '読み込みが止まっていないので戻らない',
    );
  });

  test('続きが来ないときは、速く何度も下へ押し込まず、4秒ごとに少し戻って最大5回で終わる', () async {
    final list = FakeList(total: 31, loads: false);
    await waitForPscubeList(
      expectedCount: 31,
      isCurrent: () => true,
      scroll: list.scroll,
      delay: list.delay,
    );
    final arrives = list.actions.where((a) => a == PscubeScroll.arrive).length;
    final nudges = list.actions.where((a) => a == PscubeScroll.nudge).length;
    expect(nudges, 5);
    expect(arrives, lessThanOrEqualTo(6), reason: '着いたときの1回と、戻ってからの再試行だけ');
    expect(list.count, 6);
    // 以前は70回、毎回一番下へ飛んでいた。
    expect(
      list.actions.where((a) => a == PscubeScroll.arrive).length +
          list.actions.where((a) => a == PscubeScroll.step).length,
      lessThan(40),
    );
  });

  test('設置台数が不明の一覧は、増えないことを着き直しながら3回確かめてから終わる', () async {
    final list = FakeList(total: 6, loads: false);
    await waitForPscubeList(
      isCurrent: () => true,
      scroll: list.scroll,
      delay: list.delay,
    );
    expect(list.count, 6);
    expect(
      list.actions.where((a) => a == PscubeScroll.nudge).length,
      pscubeUnknownListNudges,
    );
    expect(list.elapsed, greaterThan(const Duration(seconds: 12)));
    expect(list.elapsed, lessThan(const Duration(seconds: 30)));
  });

  // 2026-10-24〜26：20件ずつ届く機種一覧を、一番下で3秒増えないところで20件・40件として読み取り、
  // 残りの機種を取り込まずに「すべて取り込みました」で止まった。
  test('機種一覧（台数不明）は、続きが3秒より遅く届いても最後まで待つ', () async {
    for (final ignored in [0, 1]) {
      final list = FakeList(
        total: 61,
        first: 20,
        latency: const Duration(milliseconds: 3500),
        ignoredArrivals: ignored,
      );
      await waitForPscubeList(
        isCurrent: () => true,
        scroll: list.scroll,
        delay: list.delay,
      );
      expect(list.count, 61, reason: '最初の到着を無視するサイト：$ignored回');
    }
  });

  test('多数の機種で増えるたびに戻り回数を数え直し最後まで待つ', () async {
    var count = 20;
    var bottom = false;
    var wasNudged = false;
    var nudges = 0;
    await waitForPscubeList(
      isCurrent: () => true,
      delay: (_) async {},
      scroll: (action) async {
        if (action == PscubeScroll.nudge) {
          bottom = false;
          wasNudged = true;
          nudges++;
        } else if (action == PscubeScroll.step) {
          bottom = true;
        } else if (action == PscubeScroll.arrive) {
          bottom = true;
          if (wasNudged && count < 140) {
            count += 20;
            bottom = false;
            wasNudged = false;
          }
        }
        return (count: count, atBottom: bottom);
      },
    );
    expect(count, 140);
    expect(nudges, greaterThan(5));
  });

  test('台別など一覧がないページは待機しない', () async {
    await waitForPscubeList(
      isCurrent: () => true,
      scroll: (_) async => (count: -1, atBottom: false),
      delay: (_) async => fail('一覧がない場合は待たない'),
    );
  });

  test('別ページへ移動した後はそのページをスクロールしない', () async {
    var current = true;
    var calls = 0;
    await waitForPscubeList(
      expectedCount: 31,
      isCurrent: () => current,
      scroll: (_) async {
        calls++;
        return (count: 6, atBottom: false);
      },
      delay: (_) async => current = false,
    );
    expect(calls, 1);
  });

  test('最長でも360回（およそ90秒）で終わる', () async {
    var calls = 0;
    var elapsed = Duration.zero;
    await waitForPscubeList(
      expectedCount: 31,
      isCurrent: () => true,
      // 台は増えず、一番下でも上でもない位置を行き来する（戻る回数の上限にも掛からない状態）
      scroll: (_) async {
        calls++;
        return (count: 6, atBottom: false);
      },
      delay: (duration) async => elapsed += duration,
    );
    expect(calls, pscubeListMaxTicks);
    expect(elapsed, const Duration(milliseconds: 250 * 360 + 400));
  });
}
